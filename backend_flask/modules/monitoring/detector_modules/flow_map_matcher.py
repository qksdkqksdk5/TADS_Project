# 파일 경로: modules/monitoring/detector_modules/flow_map_matcher.py
# 역할: 현재 카메라 프레임과 저장된 ref_frame_*.jpg 스냅샷을 비교해
#        가장 유사한 flow_map을 자동 선택한다. (134차: 동일 도로 다른 카메라 오매칭 차단)
# 의존성: cv2, numpy, json (표준 환경)

import cv2    # OpenCV — 이미지 처리·비교
import json   # 메타 JSON 직렬화·역직렬화
import re     # 도로 접두어 추출 (끝 숫자 제거)
import numpy as np   # 배열 연산
from pathlib import Path     # 파일 경로 처리
from datetime import datetime  # 타임스탬프 파일명 생성용


# ── 매칭에 사용할 축소 해상도 (속도·정확도 균형) ─────────────────────────
_MATCH_SIZE = (128, 128)   # 두 프레임 모두 이 크기로 리사이즈 후 비교


def _score_orb(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """ORB 키포인트 매칭 점수 (0~1, 높을수록 유사). score_frames에서 가중치 0.10 보조 신호.

    조명·각도 변화에 강함 — 같은 카메라라면 도로 구조물이 같은 위치에 보이므로 매칭 수 많음.
    다른 카메라로 전환되면 배경 구조 자체가 달라서 매칭이 거의 안 됨.
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
    밝기·반사 변화에 강하다.
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
    차량 대수 변화에 덜 민감하다.
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


def _score_static_region(current_frame: np.ndarray, ref_img: np.ndarray,
                          static_mask: np.ndarray) -> float:
    """flow_map 정적 영역(차량 미검출 구역)만 비교한 유사도 (0~1).

    저장된 flow_map의 count==0 영역은 학습 기간 동안 차량이 한 번도
    지나가지 않은 구역 — 가드레일·방음벽·중앙분리대·노면 표시·
    원거리 구조물 등 카메라 위치 고유 배경을 담는다.

    같은 고속도로 다른 카메라라도 이 배경 구조가 다르므로 구별 가능하다.

    ▸ 상단 20%(하늘) 제거 — 같은 도로라도 동일한 하늘이 찍힐 수 있음
    ▸ 밝기 NCC + 엣지 NCC 혼합 → 시간대·날씨 변화에 강인
    ▸ 정적 픽셀 < 40개이면 중립값 0.5 반환 (판단 불가)
    """
    small_a = cv2.resize(current_frame, _MATCH_SIZE, interpolation=cv2.INTER_AREA)
    small_b = cv2.resize(ref_img,       _MATCH_SIZE, interpolation=cv2.INTER_AREA)

    # static_mask(임의 크기, bool) → _MATCH_SIZE 이진 마스크
    mask_rs = cv2.resize(
        static_mask.astype(np.uint8) * 255,
        _MATCH_SIZE, interpolation=cv2.INTER_NEAREST
    ) > 128

    # 상단 20% (하늘) 제거 — 같은 도로끼리도 하늘은 유사할 수 있어서 변별력 없음
    sky_cut = max(1, int(_MATCH_SIZE[1] * 0.20))
    mask_rs[:sky_cut, :] = False

    if int(mask_rs.sum()) < 40:
        return 0.5   # 비교 가능한 정적 픽셀 부족 → 중립값

    gray_a = cv2.cvtColor(small_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(small_b, cv2.COLOR_BGR2GRAY)
    # CLAHE: 밝기 차이(낮/밤·날씨) 제거 후 비교
    clahe  = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    norm_a = clahe.apply(gray_a)
    norm_b = clahe.apply(gray_b)

    def _ncc(arr_a, arr_b, mask):
        """정규화 교차 상관 (NCC) — -1~1 → 0~1 변환."""
        pa = arr_a[mask].astype(np.float64)
        pb = arr_b[mask].astype(np.float64)
        da = pa - pa.mean()
        db = pb - pb.mean()
        denom = np.sqrt((da ** 2).sum() * (db ** 2).sum())
        if denom < 1e-6:
            return 0.5  # 분산이 없으면 중립값
        return float(np.clip(((da * db).sum() / denom + 1.0) / 2.0, 0.0, 1.0))

    s_bright = _ncc(norm_a, norm_b, mask_rs)              # 밝기 패턴 유사도
    # 엣지 패턴 비교: 조명 변화에 완전 독립적 (구조물 윤곽만 비교)
    edge_a = cv2.Canny(norm_a, 30, 90).astype(np.float64)
    edge_b = cv2.Canny(norm_b, 30, 90).astype(np.float64)
    s_edge = _ncc(edge_a, edge_b, mask_rs)                # 엣지 패턴 유사도

    return 0.5 * s_bright + 0.5 * s_edge                  # 밝기·엣지 동등 혼합


def _coverage_iou(mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    """두 bool 격자 마스크의 Intersection over Union (0~1).

    IoU = 교집합 셀 수 / 합집합 셀 수

    mask_a: 저장된 스냅샷의 flow_map count>0 셀 (이 카메라가 학습한 도로 영역)
    mask_b: 현재 프레임의 차량 위치 격자 (vehicle_grid)

    같은 카메라라면 차량이 학습된 도로 영역 위에 나타나므로 IoU 높음.
    다른 카메라로 전환되면 차량 위치 분포가 달라져 교집합이 줄고 IoU 낮아짐.
    """
    inter = float(np.logical_and(mask_a, mask_b).sum())  # 두 마스크가 모두 True인 셀 수
    union = float(np.logical_or(mask_a,  mask_b).sum())  # 둘 중 하나라도 True인 셀 수
    return inter / union if union > 0 else 0.0           # 합집합이 0이면 IoU=0


def _estimate_scene_flow_hint(frame: np.ndarray,
                              prev_frame: "np.ndarray | None" = None
                              ) -> "tuple[float, float] | None":
    """현재 장면의 지배적 교통 흐름 방향을 추정한다.

    전략 1 (우선): prev_frame이 있고 차량 이동이 감지되면 Farneback optical flow 사용.
    전략 2 (fallback): 현재 프레임에서 차선 마킹을 Hough 변환으로 검출 → 차선 각도.

    차량이 정체 중이라도 차선 마킹은 프레임에 남아 있으므로 전략 2는 정체 상황에서도 동작.

    Returns
    -------
    (dx, dy) 정규화 방향 벡터 또는 None (추정 실패).
    """
    # ── 전략 1: Farneback optical flow ─────────────────────────────────
    if prev_frame is not None:
        _sz = (64, 64)
        g1 = cv2.resize(cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY), _sz)
        g2 = cv2.resize(cv2.cvtColor(frame,      cv2.COLOR_BGR2GRAY), _sz)
        try:
            _of = cv2.calcOpticalFlowFarneback(
                g1, g2, None, 0.5, 3, 7, 3, 5, 1.2, 0
            )
            _dx = float(np.median(_of[..., 0]))  # x방향 중앙값 흐름
            _dy = float(np.median(_of[..., 1]))  # y방향 중앙값 흐름
            _mag = np.sqrt(_dx**2 + _dy**2)
            if _mag >= 0.5:                       # 유효한 이동량이면 사용
                return (_dx / _mag, _dy / _mag)
        except Exception:
            pass

    # ── 전략 2: Hough 차선 검출 ─────────────────────────────────────────
    # 이미지 하단 50%(도로 영역)에서 차선 마킹 각도를 추출한다.
    # 차선은 차량 이동 방향과 평행 → 차선 각도 ≈ 흐름 방향 각도.
    try:
        _h, _w = frame.shape[:2]
        _roi = frame[int(_h * 0.40): int(_h * 0.92), :]   # 도로 ROI (상단 배경 제거)
        _gray = cv2.cvtColor(_roi, cv2.COLOR_BGR2GRAY)
        _edges = cv2.Canny(_gray, 40, 120, apertureSize=3)
        _lines = cv2.HoughLinesP(
            _edges, 1, np.pi / 180,
            threshold=20, minLineLength=20, maxLineGap=15
        )
        if _lines is not None:
            _angles = []
            for _ln in _lines:
                _x1, _y1, _x2, _y2 = _ln[0]
                _angles.append(float(np.arctan2(_y2 - _y1, _x2 - _x1)))
            if len(_angles) >= 4:                          # 최소 4개 선분 필요
                _med = float(np.median(_angles))
                return (float(np.cos(_med)), float(np.sin(_med)))
    except Exception:
        pass

    return None   # 추정 실패


def _load_flow_dir(npy_path: Path) -> "tuple[float, float] | None":
    """후보 flow_map의 지배적 흐름 방향을 반환한다.

    1차: meta JSON의 flow_dir_x/y 빠른 읽기.
    2차: npy 직접 로드 → 가중 평균 방향 계산 (구형 스냅샷 호환).
    방향을 처음 계산한 경우 meta JSON에 캐싱해 다음 호출 속도를 높인다.
    """
    _stem = npy_path.stem   # "flow_map_YYYYMMDD_HHMMSS"
    _ts   = _stem[len("flow_map_"):] if _stem.startswith("flow_map_") else ""
    _meta_path = npy_path.parent / f"meta_{_ts}.json" if _ts else None

    # ── 1차: meta 캐시 ──────────────────────────────────────────────────
    if _meta_path and _meta_path.exists():
        try:
            _meta = json.loads(_meta_path.read_text(encoding="utf-8"))
            if "flow_dir_x" in _meta and "flow_dir_y" in _meta:
                return (float(_meta["flow_dir_x"]), float(_meta["flow_dir_y"]))
        except Exception:
            pass

    # ── 2차: npy 직접 계산 ─────────────────────────────────────────────
    try:
        _data  = np.load(npy_path, allow_pickle=True).item()
        _flow  = _data.get("flow")    # (grid, grid, 2)
        _count = _data.get("count")   # (grid, grid)
        if _flow is None or _count is None:
            return None
        _mask = _count > 3            # 의미있는 셀만 (노이즈 제거)
        if not _mask.any():
            return None
        _vx = _flow[_mask, 0]
        _vy = _flow[_mask, 1]
        _w  = _count[_mask].astype(float)
        _dx = float(np.average(_vx, weights=_w))  # 샘플 수 가중 평균 x
        _dy = float(np.average(_vy, weights=_w))  # 샘플 수 가중 평균 y
        _mag = np.sqrt(_dx**2 + _dy**2)
        if _mag < 1e-6:
            return None
        _dir = (_dx / _mag, _dy / _mag)

        # meta에 캐싱 (다음 실행 시 npy 로드 생략)
        if _meta_path:
            try:
                _m = {}
                if _meta_path.exists():
                    _m = json.loads(_meta_path.read_text(encoding="utf-8"))
                _m["flow_dir_x"] = round(_dir[0], 4)
                _m["flow_dir_y"] = round(_dir[1], 4)
                _meta_path.write_text(json.dumps(_m), encoding="utf-8")
            except Exception:
                pass

        return _dir
    except Exception:
        return None


def _load_coverage_mask(npy_path: Path) -> "np.ndarray | None":
    """후보 flow_map의 coverage 마스크(bool 2D array)를 반환한다.

    1차: meta JSON의 "coverage" 필드 (빠름).
    2차: npy 직접 로드 → count>0 계산 (구형 스냅샷 호환, 결과를 meta에 캐싱).
    """
    _stem = npy_path.stem
    _ts   = _stem[len("flow_map_"):] if _stem.startswith("flow_map_") else ""
    _meta_path = npy_path.parent / f"meta_{_ts}.json" if _ts else None

    # ── 1차: meta 캐시 ──────────────────────────────────────────────────
    if _meta_path and _meta_path.exists():
        try:
            _meta = json.loads(_meta_path.read_text(encoding="utf-8"))
            if "coverage" in _meta:
                return np.array(_meta["coverage"], dtype=bool)
        except Exception:
            pass

    # ── 2차: npy 직접 계산 ─────────────────────────────────────────────
    try:
        _data  = np.load(npy_path, allow_pickle=True).item()
        _count = _data.get("count")
        if _count is None:
            return None
        _mask = (_count > 0)    # 학습된 셀 = True

        # meta에 캐싱 (다음 실행 시 npy 로드 생략)
        if _meta_path:
            try:
                _m = {}
                if _meta_path.exists():
                    _m = json.loads(_meta_path.read_text(encoding="utf-8"))
                _m["coverage"] = _mask.tolist()
                _meta_path.write_text(json.dumps(_m), encoding="utf-8")
            except Exception:
                pass
        return _mask
    except Exception:
        return None


def score_frames(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
    """두 BGR 프레임의 시각 유사도를 0~1로 반환한다.

    엣지 구조(0.35) + 공간 히스토그램(0.35) + 전역 히스토그램(0.20) + ORB(0.10) 혼합.
    - CLAHE 정규화: 비교 전 두 이미지의 명도를 평탄화 → 밝기 변화·햇빛 반사에 강함
    - 엣지 구조: 가드레일·차선·건물 윤곽 등 조명 불변 특징 비교
    - 공간 히스토그램: 도로 구조·배경을 셀 단위로 비교 → 차량 변화에 강함
    - ORB는 보조 역할만
    """
    # 두 프레임을 동일 크기로 축소한 뒤 그레이스케일 변환
    small_a = cv2.resize(frame_a, _MATCH_SIZE, interpolation=cv2.INTER_AREA)
    small_b = cv2.resize(frame_b, _MATCH_SIZE, interpolation=cv2.INTER_AREA)
    gray_a  = cv2.cvtColor(small_a, cv2.COLOR_BGR2GRAY)
    gray_b  = cv2.cvtColor(small_b, cv2.COLOR_BGR2GRAY)

    # CLAHE 정규화: 밝기 차이 제거 (clipLimit=2.0, tileGridSize=(8,8))
    clahe  = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    norm_a = clahe.apply(gray_a)
    norm_b = clahe.apply(gray_b)

    s_edge    = _score_edge_structure(norm_a, norm_b, grid=4)   # 엣지 구조 (0.35)
    s_spatial = _score_spatial_hist(norm_a, norm_b, grid=4)     # 공간 히스토 (0.35)
    s_hist    = _score_hist(norm_a, norm_b)                     # 전역 히스토 (0.20)
    s_orb     = _score_orb(norm_a, norm_b)                      # ORB 특징점 (0.10)
    return 0.35 * s_edge + 0.35 * s_spatial + 0.20 * s_hist + 0.10 * s_orb


# ── 하위 호환 심벌 (traffic/reverse_detector.py 등 외부 팀 의존) ─────────────
# monitoring_detector.py는 이 두 심벌을 더 이상 사용하지 않지만,
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
        같은 도로 그룹의 폴더만 탐색한다.

        Returns
        -------
        (best_dir, score) — best_dir=None이면 min_score 미달 → 새 학습 필요.
        """
        prefix = _road_prefix(exclude_dir.name) if exclude_dir is not None else ""

        candidates = self._candidates(road_prefix=prefix)
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
            s = score_frames(current_frame, ref_img)     # 시각 유사도 계산
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
        meta_YYYYMMDD_HHMMSS.json        — A방향 레이블 + flow 방향 벡터 + coverage 마스크

    Parameters
    ----------
    frame : np.ndarray
        저장할 BGR 프레임.
    flow_map_obj : FlowMap
        저장할 FlowMap 객체 (save(path) 메서드 사용).
    save_dir : Path
        저장 대상 폴더.
    dir_label_a : str
        A방향 레이블 ("UP" 또는 "DOWN"). 빈 문자열이면 메타에 저장 안 함.

    Returns
    -------
    bool : 저장 성공 여부.
    """
    save_dir.mkdir(parents=True, exist_ok=True)          # 폴더 없으면 생성
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S") # 현재 시각 → 파일명 접미사
    npy_path  = save_dir / f"flow_map_{ts}.npy"
    jpg_path  = save_dir / f"ref_frame_{ts}.jpg"
    meta_path = save_dir / f"meta_{ts}.json"

    flow_map_obj.save(npy_path)                          # flow_map 배열 저장

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        return False
    jpg_path.write_bytes(buf.tobytes())                  # ref_frame 저장

    # ── 메타데이터 구성: dir_label_a + 흐름 방향 벡터 + coverage 마스크 ──
    # flow_dir_x/y: 스냅샷 매칭 시 방향 일치도 계산에 사용 (_load_flow_dir 캐시 역할)
    # coverage: 차량이 학습된 도로 영역 마스크 — IoU 비교로 같은 카메라 판별에 사용
    meta: dict = {}
    if dir_label_a:
        meta["dir_label_a"] = dir_label_a                # A방향 레이블 저장

    try:
        _mask = flow_map_obj.count > 3                   # 의미있는 학습 셀 마스크
        if _mask.any():
            # 샘플 수 가중 평균 방향 벡터 저장
            _vx = flow_map_obj.flow[_mask, 0]
            _vy = flow_map_obj.flow[_mask, 1]
            _w  = flow_map_obj.count[_mask].astype(float)
            _dx = float(np.average(_vx, weights=_w))
            _dy = float(np.average(_vy, weights=_w))
            _mag = np.sqrt(_dx**2 + _dy**2)
            if _mag > 1e-6:
                meta["flow_dir_x"] = round(_dx / _mag, 4)  # 정규화된 x성분
                meta["flow_dir_y"] = round(_dy / _mag, 4)  # 정규화된 y성분
        # coverage 마스크: count>0인 셀 (차량이 최소 1회 통과한 도로 영역)
        _cov = (flow_map_obj.count > 0)
        meta["coverage"] = _cov.tolist()                 # bool 2D → 리스트로 JSON 직렬화
    except Exception:
        pass                                             # flow_map_obj 구조 문제 시 무시

    if meta:
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

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
    dict : {"dir_label_a": "UP", "flow_dir_x": 0.1, ...} 형태. 파일 없으면 {}.
    """
    stem = npy_path.stem                                 # "flow_map_YYYYMMDD_HHMMSS"
    if not stem.startswith("flow_map_"):
        return {}
    ts_part   = stem[len("flow_map_"):]                  # "YYYYMMDD_HHMMSS" 부분
    meta_path = npy_path.parent / f"meta_{ts_part}.json" # 같은 폴더의 메타 경로

    if not meta_path.exists():
        return {}                                        # 메타 파일 없으면 빈 dict
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}                                        # 파싱 오류 시 빈 dict


def find_best_snapshot(current_frame: np.ndarray, save_dir: Path,
                       min_score: float = 0.25,
                       prev_frame: "np.ndarray | None" = None,
                       vehicle_grid: "np.ndarray | None" = None) -> tuple:
    """save_dir에서 current_frame과 가장 유사한 스냅샷 쌍을 찾는다.

    타임스탬프 파일(ref_frame_*.jpg + flow_map_*.npy)과
    레거시 파일(ref_frame.jpg + flow_map.npy) 모두 검색한다.

    점수 산출:
        vehicle_grid 제공 시: 시각×0.25 + 정적배경×0.55 + coverage_IoU×0.20
        vehicle_grid 없을 시: 시각×0.40 + 정적배경×0.40 + 방향×0.20

    이중 필터: vis ≥ min_score AND static_score ≥ 0.62 를 모두 통과해야 후보 인정.
    0.62 임계값 근거 — 같은 도로 다른 구도 실측값이 0.607로 이 임계값 바로 아래에 위치.

    Parameters
    ----------
    current_frame : np.ndarray
        현재 카메라 BGR 프레임.
    save_dir : Path
        스냅샷이 저장된 폴더.
    min_score : float
        시각 점수 하한 (이 미만이면 후보 제외).
    prev_frame : np.ndarray | None
        직전 프레임. 제공 시 optical flow로 방향 추정 정확도 향상.
    vehicle_grid : np.ndarray | None
        현재 프레임의 차량 위치 격자 마스크 (bool, shape=(grid_size, grid_size)).

    Returns
    -------
    (best_npy_path, visual_score)
        best_npy_path: 매칭된 .npy 경로 (None이면 매칭 실패)
        visual_score: 시각 유사도 0~1
    """
    if not save_dir.exists():
        return None, 0.0

    candidates = []

    # 타임스탬프 쌍 수집 (glob 패턴: ref_frame_YYYYMMDD_HHMMSS.jpg)
    for jpg_path in sorted(save_dir.glob("ref_frame_????????_??????.jpg")):
        ts_part  = jpg_path.stem[len("ref_frame_"):]     # YYYYMMDD_HHMMSS 부분 추출
        npy_path = save_dir / f"flow_map_{ts_part}.npy"  # 대응 npy 경로
        if npy_path.exists():
            candidates.append((jpg_path, npy_path))

    # 레거시 단일 파일 (기존 flow_map.npy + ref_frame.jpg)
    legacy_jpg = save_dir / "ref_frame.jpg"
    legacy_npy = save_dir / "flow_map.npy"
    if legacy_jpg.exists() and legacy_npy.exists():
        candidates.append((legacy_jpg, legacy_npy))

    if not candidates:
        return None, 0.0

    # 현재 장면 흐름 방향 추정 (1회만 계산 — 후보마다 반복하지 않음)
    _scene_hint = _estimate_scene_flow_hint(current_frame, prev_frame)

    _use_coverage = vehicle_grid is not None   # coverage IoU 사용 여부

    scored = []   # [(vis, static_score, combined, npy_path)]

    for jpg_path, npy_path in candidates:
        # 한글 경로 대응을 위해 numpy 경유로 읽기
        ref_img = cv2.imdecode(
            np.fromfile(str(jpg_path), dtype=np.uint8), cv2.IMREAD_COLOR
        )
        if ref_img is None:
            continue

        vis = score_frames(current_frame, ref_img)   # 시각 유사도 계산

        # coverage 마스크 로드 (정적 배경 비교 + IoU 두 곳에 공통 사용)
        _cov_mask = _load_coverage_mask(npy_path)    # count>0 bool 마스크 또는 None

        # 정적 배경 영역 점수 — flow_map count==0 구역 = 카메라 위치 고유 배경
        static_score = 0.5                           # 기본값: 중립 (마스크 없을 때)
        if _cov_mask is not None:
            _static_mask = ~_cov_mask                # count==0 → 정적 영역
            static_score = _score_static_region(current_frame, ref_img, _static_mask)

        # 흐름 방향 일치도 — vehicle_grid 없을 때만 사용
        # (같은 고속도로 다른 카메라는 방향이 동일하여 변별력 없으므로 cov_score로 대체)
        dir_score = 0.5                              # 기본값: 중립
        if _scene_hint is not None:
            _fdir = _load_flow_dir(npy_path)
            if _fdir is not None:
                # 두 방향 벡터의 내적 절댓값 — 1이면 동일 방향, 0이면 수직
                dir_score = abs(
                    _scene_hint[0] * _fdir[0] + _scene_hint[1] * _fdir[1]
                )

        # coverage IoU — 차량 위치 분포가 저장된 도로 영역과 겹치는지 확인
        cov_score = 0.5                              # 기본값: 중립
        if (_use_coverage
                and _cov_mask is not None
                and _cov_mask.shape == vehicle_grid.shape):
            cov_score = _coverage_iou(_cov_mask, vehicle_grid)

        # combined 점수 산출
        # vehicle_grid 있을 때: 정적배경(0.55) + 시각(0.25) + coverage_IoU(0.20)
        # vehicle_grid 없을 때: 정적배경(0.40) + 시각(0.40) + 방향(0.20)
        if _use_coverage:
            combined = 0.25 * vis + 0.55 * static_score + 0.20 * cov_score
        else:
            combined = 0.40 * vis + 0.40 * static_score + 0.20 * dir_score

        scored.append((vis, static_score, combined, npy_path))

    if not scored:
        return None, 0.0

    # ── 이중 필터: vis ≥ min_score AND static_score ≥ 0.62 ─────────────
    # 같은 도로 다른 카메라 실측: static ≈ 0.607 → 0.62 임계값으로 차단
    _ST_MIN = 0.62
    qualifying = [
        (v, c, p) for v, st, c, p in scored
        if v >= min_score and st >= _ST_MIN
    ]

    if not qualifying:
        return None, max(v for v, _st, _c, _p in scored)  # 시각 점수 최댓값만 반환

    qualifying.sort(key=lambda x: x[1], reverse=True)     # combined 내림차순 정렬
    best_vis, _best_comb, best_npy = qualifying[0]

    return best_npy, best_vis
