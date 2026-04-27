# 파일 경로: modules/monitoring/detector_modules/flow_map_matcher.py
# 역할: 현재 카메라 프레임과 저장된 ref_frame_*.jpg 스냅샷을 비교해
#        가장 유사한 flow_map을 자동 선택한다. (133차: 교차 카메라 매칭 제거)
# 의존성: cv2, numpy, json (표준 환경)

import cv2  # OpenCV — 이미지 처리·비교
import json  # 메타 JSON 직렬화·역직렬화
import re    # 도로 접두어 추출 (끝 숫자 제거)
import numpy as np  # 배열 연산
from pathlib import Path  # 파일 경로 처리
from datetime import datetime  # 타임스탬프 파일명 생성용


# ── 매칭에 사용할 축소 해상도 (속도·정확도 균형) ─────────────────────────
_MATCH_SIZE = (128, 128)   # 두 프레임 모두 이 크기로 리사이즈 후 비교


def _score_orb(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """ORB 키포인트 매칭 점수 (0~1, 높을수록 유사).

    조명·각도 변화에 강함 — 주요 매칭 방법.
    """
    orb = cv2.ORB_create(nfeatures=500)  # ORB 특징점 최대 500개 검출
    kp_a, des_a = orb.detectAndCompute(img_a, None)
    kp_b, des_b = orb.detectAndCompute(img_b, None)

    # 디스크립터가 없거나 키포인트가 너무 적으면 점수 0
    if des_a is None or des_b is None:
        return 0.0
    if len(kp_a) < 10 or len(kp_b) < 10:
        return 0.0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)  # Hamming 거리 기반 매칭
    matches = bf.match(des_a, des_b)
    if not matches:
        return 0.0

    # 거리 기준 정렬 후 상위 50%만 사용 (노이즈 제거)
    matches = sorted(matches, key=lambda m: m.distance)
    good    = matches[:len(matches) // 2]

    # 좋은 매칭 수 / 키포인트 수로 정규화
    score = len(good) / max(len(kp_a), len(kp_b))
    return float(np.clip(score, 0.0, 1.0))


def _score_hist(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """전역 히스토그램 상관 점수 (0~1, 높을수록 유사)."""
    # 64-bin 히스토그램 계산 후 정규화
    hist_a = cv2.calcHist([img_a], [0], None, [64], [0, 256])
    hist_b = cv2.calcHist([img_b], [0], None, [64], [0, 256])
    cv2.normalize(hist_a, hist_a)
    cv2.normalize(hist_b, hist_b)
    score = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)  # 결과: -1~1
    return float(np.clip((score + 1.0) / 2.0, 0.0, 1.0))        # 0~1 정규화


def _score_edge_structure(img_a: np.ndarray, img_b: np.ndarray,
                           grid: int = 4) -> float:
    """엣지 밀도 공간 분포 비교 점수 (0~1) — 조명에 독립적인 도로 구조 유사도.

    Canny 엣지 맵을 grid×grid 셀로 나눠 각 셀의 엣지 밀도 벡터를 구하고,
    두 벡터의 피어슨 상관계수를 0~1로 정규화한다.
    가드레일·차선·교각·건물 윤곽은 조명이 바뀌어도 같은 위치에 나타나므로
    밝기·반사 변화에 강하다. (132차 신규 추가)
    """
    # Canny 엣지 검출: 임계값 40~120 (도로 구조선 검출에 적합)
    edges_a = cv2.Canny(img_a, 40, 120)
    edges_b = cv2.Canny(img_b, 40, 120)
    h, w = img_a.shape[:2]
    if h == 0 or w == 0:
        return 0.0  # 빈 배열 방어
    ch, cw = h // grid, w // grid  # 셀 높이·너비
    dens_a, dens_b = [], []
    for r in range(grid):
        for c in range(grid):
            # 각 셀의 엣지 평균 밀도 계산
            ea = edges_a[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw]
            eb = edges_b[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw]
            if ea.size == 0:
                continue
            dens_a.append(float(ea.mean()))
            dens_b.append(float(eb.mean()))
    if not dens_a:
        return 0.0
    da = np.array(dens_a)
    db = np.array(dens_b)
    # 두 밀도 벡터가 거의 평탄(엣지 극소)하면 절대 차이로 유사도 판단
    if da.std() < 1e-6 or db.std() < 1e-6:
        denom = max(da.mean(), db.mean(), 1.0)
        return float(np.clip(1.0 - abs(da.mean() - db.mean()) / denom, 0.0, 1.0))
    # 피어슨 상관계수로 구조 유사도 측정 (−1~1 → 0~1 정규화)
    corr = float(np.corrcoef(da, db)[0, 1])
    return float(np.clip((corr + 1.0) / 2.0, 0.0, 1.0))


def _score_spatial_hist(img_a: np.ndarray, img_b: np.ndarray,
                        grid: int = 4) -> float:
    """공간 분할 히스토그램 점수 (0~1).

    이미지를 grid×grid 셀로 나눠 각 셀의 히스토그램을 비교한다.
    전역 히스토그램보다 도로 구조(건물·차선·배경)를 더 잘 반영하고,
    차량 대수 변화에 덜 민감하다. (132차 신규 추가)
    """
    h, w = img_a.shape[:2]
    ch, cw = h // grid, w // grid  # 셀 높이·너비
    scores = []
    for r in range(grid):
        for c in range(grid):
            # 각 셀 영역 추출
            cell_a = img_a[r*ch:(r+1)*ch, c*cw:(c+1)*cw]
            cell_b = img_b[r*ch:(r+1)*ch, c*cw:(c+1)*cw]
            if cell_a.size == 0 or cell_b.size == 0:
                continue
            # 32-bin 히스토그램으로 셀 단위 비교 (64-bin보다 안정적)
            ha = cv2.calcHist([cell_a], [0], None, [32], [0, 256])
            hb = cv2.calcHist([cell_b], [0], None, [32], [0, 256])
            cv2.normalize(ha, ha)
            cv2.normalize(hb, hb)
            s = cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL)  # −1~1
            scores.append(float(np.clip((s + 1.0) / 2.0, 0.0, 1.0)))  # 0~1
    return float(np.mean(scores)) if scores else 0.0


def score_frames(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
    """두 BGR 프레임의 유사도를 0~1로 반환한다.

    엣지 구조(0.35) + 공간 히스토그램(0.35) + 전역 히스토그램(0.20) + ORB(0.10) 혼합.
    - CLAHE 정규화: 비교 전 두 이미지의 명도를 평탄화 → 밝기 변화·햇빛 반사에 강함
    - 엣지 구조: 가드레일·차선·건물 윤곽 등 조명 불변 특징 비교
    - 공간 히스토그램: 도로 구조·배경을 셀 단위로 비교 → 차량 변화에 강함
    - ORB는 보조 역할만 (132차 가중치 전면 개편)
    """
    # 두 프레임을 동일 크기로 축소한 뒤 그레이스케일 변환
    small_a = cv2.resize(frame_a, _MATCH_SIZE, interpolation=cv2.INTER_AREA)
    small_b = cv2.resize(frame_b, _MATCH_SIZE, interpolation=cv2.INTER_AREA)
    gray_a  = cv2.cvtColor(small_a, cv2.COLOR_BGR2GRAY)
    gray_b  = cv2.cvtColor(small_b, cv2.COLOR_BGR2GRAY)

    # ── CLAHE 정규화: 밝기 차이 제거 (132차 신규) ─────────────────────
    # clipLimit=2.0, tileGridSize=(8,8) — 과도한 노이즈 증폭 방지
    clahe  = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    norm_a = clahe.apply(gray_a)  # 명도 평탄화된 A 이미지
    norm_b = clahe.apply(gray_b)  # 명도 평탄화된 B 이미지

    # ── 4가지 점수 혼합 (132차 가중치 변경) ────────────────────────────
    s_edge    = _score_edge_structure(norm_a, norm_b, grid=4)  # 엣지 구조 (0.35)
    s_spatial = _score_spatial_hist(norm_a, norm_b, grid=4)    # 공간 히스토 (0.35)
    s_hist    = _score_hist(norm_a, norm_b)                    # 전역 히스토 (0.20)
    s_orb     = _score_orb(norm_a, norm_b)                     # ORB 특징점 (0.10)
    return 0.35 * s_edge + 0.35 * s_spatial + 0.20 * s_hist + 0.10 * s_orb


# ── 하위 호환 심벌 (traffic/reverse_detector.py 등 외부 팀 의존) ─────────────
# 133차에서 monitoring_detector.py는 이 두 심벌을 더 이상 사용하지 않지만,
# traffic 팀의 reverse_detector.py가 직접 import하므로 제거하지 않는다.

def _road_prefix(camera_id: str) -> str:
    """카메라 ID에서 도로 접두어를 추출한다.

    끝에 붙은 숫자를 제거해 도로 그룹 이름을 반환한다.
    예) "달래내2" → "달래내",  "경부고속도로3" → "경부고속도로"
    숫자만 있거나 접두어가 빈 문자열이면 원본 그대로 반환 (비교 생략 방지).
    """
    prefix = re.sub(r'\d+$', '', camera_id)  # 끝 숫자 제거
    return prefix if prefix else camera_id   # 빈 문자열 방어


class FlowMapMatcher:
    """저장된 flow_map 폴더들 중 현재 화면과 가장 유사한 것을 선택한다.

    같은 도로 그룹(카메라 ID 끝 숫자를 제거한 접두어가 동일)의 폴더만 탐색한다.
    예) "달래내2"가 호출 카메라이면 "달래내1", "달래내3"만 후보, 타 도로는 제외.

    Parameters
    ----------
    flow_maps_root : Path
        flow_maps/ 루트 폴더.
    min_score : float
        이 점수 미만이면 매칭 실패로 판단 (새로 학습).
    """

    def __init__(self, flow_maps_root: Path, min_score: float = 0.73):
        self.root      = flow_maps_root  # flow_maps/ 루트 디렉터리
        self.min_score = min_score       # 매칭 성공 최소 임계값

    def _candidates(self, road_prefix: str = "") -> list:
        """(road_dir, ref_frame_path) 목록 반환 — ref_frame.jpg 있는 폴더만.

        road_prefix가 비어 있지 않으면 같은 도로 그룹(폴더명 접두어 일치)만 포함한다.
        """
        result = []
        if not self.root.exists():
            return result
        for d in sorted(self.root.iterdir()):
            if not d.is_dir():
                continue
            # 도로 그룹 필터: 접두어가 지정된 경우 해당 접두어로 시작하는 폴더만 허용
            if road_prefix and not d.name.startswith(road_prefix):
                continue                                  # 다른 도로 그룹 제외
            flow_npy = d / "flow_map.npy"
            ref_jpg  = d / "ref_frame.jpg"
            if flow_npy.exists() and ref_jpg.exists():   # 두 파일 모두 있어야 유효한 후보
                result.append((d, ref_jpg))
        return result

    def find_best(self, current_frame: np.ndarray,
                  exclude_dir: Path | None = None) -> tuple:
        """current_frame과 가장 유사한 flow_map 폴더를 찾는다.

        exclude_dir이 제공된 경우 해당 폴더명에서 도로 접두어를 추출하여
        같은 도로 그룹의 폴더만 탐색한다. (예: "달래내2" → "달래내" 접두어만 허용)

        Parameters
        ----------
        current_frame : np.ndarray
            현재 카메라 BGR 프레임.
        exclude_dir : Path | None
            자기 자신 폴더 (자기 자신 제외 + 도로 그룹 기준 추출).

        Returns
        -------
        (best_dir, score) — best_dir=None이면 min_score 미달 → 새 학습 필요.
        """
        # 도로 접두어 추출: exclude_dir 이름에서 끝 숫자 제거
        prefix = _road_prefix(exclude_dir.name) if exclude_dir is not None else ""

        candidates = self._candidates(road_prefix=prefix)  # 같은 도로 그룹만 탐색
        if not candidates:
            return None, 0.0

        best_dir   = None
        best_score = 0.0

        for road_dir, ref_path in candidates:
            if exclude_dir is not None and road_dir == exclude_dir:
                continue                                  # 자기 자신 제외
            ref_img = cv2.imdecode(
                np.fromfile(str(ref_path), dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if ref_img is None:
                continue
            s = score_frames(current_frame, ref_img)     # 유사도 계산
            if s > best_score:
                best_score = s
                best_dir   = road_dir

        if best_score < self.min_score:
            return None, best_score                      # 기준 미달 → 새 학습 필요

        return best_dir, best_score


def save_ref_frame(frame: np.ndarray, road_dir: Path) -> bool:
    """학습 완료 시점의 프레임을 ref_frame.jpg로 저장한다.

    Parameters
    ----------
    frame : np.ndarray
        저장할 BGR 프레임.
    road_dir : Path
        저장 대상 폴더 (flow_map.npy와 같은 위치).

    Returns
    -------
    bool : 저장 성공 여부.
    """
    road_dir.mkdir(parents=True, exist_ok=True)          # 폴더 없으면 생성
    out_path = road_dir / "ref_frame.jpg"
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        return False
    out_path.write_bytes(buf.tobytes())                  # ref_frame 저장
    return True


def save_flow_snapshot(frame: np.ndarray, flow_map_obj, save_dir: Path,
                       dir_label_a: str = "") -> bool:
    """학습 완료 시점의 프레임·flow_map·방향 메타데이터를 타임스탬프 이름으로 저장한다.

    파일명 형식:
        flow_map_YYYYMMDD_HHMMSS.npy     — flow_map 배열
        ref_frame_YYYYMMDD_HHMMSS.jpg    — 매칭용 기준 프레임
        meta_YYYYMMDD_HHMMSS.json        — A방향 레이블 ("UP"/"DOWN") 메타

    Parameters
    ----------
    frame : np.ndarray
        저장할 BGR 프레임.
    flow_map_obj : FlowMap
        저장할 FlowMap 객체 (save(path) 메서드 사용).
    save_dir : Path
        저장 대상 폴더.
    dir_label_a : str
        A방향 레이블 ("UP" 또는 "DOWN"). 빈 문자열이면 메타에 빈 값으로 저장.

    Returns
    -------
    bool : 저장 성공 여부.
    """
    save_dir.mkdir(parents=True, exist_ok=True)          # 폴더 없으면 생성
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S") # 현재 시각 → 파일명 접미사 (세 파일 공유)
    npy_path  = save_dir / f"flow_map_{ts}.npy"          # 타임스탬프 npy 경로
    jpg_path  = save_dir / f"ref_frame_{ts}.jpg"         # 타임스탬프 jpg 경로
    meta_path = save_dir / f"meta_{ts}.json"             # 타임스탬프 메타 경로

    flow_map_obj.save(npy_path)                          # flow_map 배열 저장

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        return False
    jpg_path.write_bytes(buf.tobytes())                  # ref_frame 저장

    # A방향 레이블을 메타 JSON에 기록 — load_snapshot_meta()가 읽어 방향 반전 감지에 사용
    meta_path.write_text(
        json.dumps({"dir_label_a": dir_label_a}),
        encoding="utf-8"
    )
    return True


def load_snapshot_meta(npy_path: Path) -> dict:
    """npy 파일에 대응하는 meta_YYYYMMDD_HHMMSS.json을 읽어 반환한다.

    npy 파일명에서 타임스탬프를 추출하여 같은 폴더의 메타 파일을 찾는다.
    파일이 없거나 파싱 실패 시 빈 dict를 반환한다.

    Parameters
    ----------
    npy_path : Path
        대응 메타를 찾을 flow_map_YYYYMMDD_HHMMSS.npy 경로.

    Returns
    -------
    dict : {"dir_label_a": "UP"} 형태. 파일 없으면 {}.
    """
    # "flow_map_" 접두어 이후 타임스탬프 부분 추출
    stem     = npy_path.stem                               # "flow_map_YYYYMMDD_HHMMSS"
    ts_part  = stem[len("flow_map_"):]                     # "YYYYMMDD_HHMMSS"
    meta_path = npy_path.parent / f"meta_{ts_part}.json"  # 같은 폴더의 메타 경로

    if not meta_path.exists():
        return {}                                          # 메타 파일 없으면 빈 dict
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}                                          # 파싱 오류 시 빈 dict


def find_best_snapshot(current_frame: np.ndarray, save_dir: Path,
                       min_score: float = 0.73) -> tuple:  # 132차: 0.35 → 0.73 (새 점수 체계 반영)
    """save_dir에서 current_frame과 가장 유사한 스냅샷 쌍을 찾는다.

    타임스탬프 파일(ref_frame_*.jpg + flow_map_*.npy)과
    레거시 파일(ref_frame.jpg + flow_map.npy) 모두 검색한다.

    Parameters
    ----------
    current_frame : np.ndarray
        현재 카메라 BGR 프레임.
    save_dir : Path
        스냅샷이 저장된 폴더.
    min_score : float
        이 점수 미만이면 매칭 실패 (새 학습 필요).

    Returns
    -------
    (best_npy_path, score)
        best_npy_path: 매칭된 .npy 경로 (None이면 매칭 실패)
        score: 유사도 0~1
    """
    if not save_dir.exists():
        return None, 0.0

    candidates = []

    # 타임스탬프 쌍 수집 (glob 패턴: ref_frame_YYYYMMDD_HHMMSS.jpg)
    for jpg_path in sorted(save_dir.glob("ref_frame_????????_??????.jpg")):
        ts_part = jpg_path.stem[len("ref_frame_"):]       # YYYYMMDD_HHMMSS 부분 추출
        npy_path = save_dir / f"flow_map_{ts_part}.npy"   # 대응 npy 경로
        if npy_path.exists():
            candidates.append((jpg_path, npy_path))

    # 레거시 단일 파일 (기존 flow_map.npy + ref_frame.jpg)
    legacy_jpg = save_dir / "ref_frame.jpg"
    legacy_npy = save_dir / "flow_map.npy"
    if legacy_jpg.exists() and legacy_npy.exists():
        candidates.append((legacy_jpg, legacy_npy))

    if not candidates:
        return None, 0.0

    best_npy   = None
    best_score = 0.0

    for jpg_path, npy_path in candidates:
        # 한글 경로 대응을 위해 numpy 경유로 읽기
        ref_img = cv2.imdecode(
            np.fromfile(str(jpg_path), dtype=np.uint8), cv2.IMREAD_COLOR
        )
        if ref_img is None:
            continue
        s = score_frames(current_frame, ref_img)   # 유사도 계산
        if s > best_score:
            best_score = s
            best_npy   = npy_path

    if best_score < min_score:
        return None, best_score   # 기준 미달 → 새 학습 필요

    return best_npy, best_score
