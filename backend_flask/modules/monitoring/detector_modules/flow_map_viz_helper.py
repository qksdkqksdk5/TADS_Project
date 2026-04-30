# 파일 경로: modules/monitoring/detector_modules/flow_map_viz_helper.py
# 역할: 저장된 flow map 파일을 읽어 시각화용 JSON-직렬화 가능한 dict 로 반환한다.
# Flask/gevent 의존성 없이 독립 실행 가능하도록 순수 Python/NumPy 만 사용한다.
#
# 파일명 규칙 (flow_map_matcher.save_flow_snapshot 기준):
#   타임스탬프 형식(신규): flow_map_YYYYMMDD_HHMMSS.npy
#                          ref_frame_YYYYMMDD_HHMMSS.jpg
#                          meta_YYYYMMDD_HHMMSS.json
#   레거시 형식(구형):     flow_map.npy  +  ref_frame.jpg  (meta 없음)
#
# 두 형식 모두 지원한다. 타임스탬프 파일이 없고 레거시 파일도 없으면 FileNotFoundError.

import base64        # ref_frame.jpg → base64 인코딩
import json          # meta JSON 파일 파싱
import numpy as np   # npy 파일 로드 및 배열 변환
from pathlib import Path   # 파일 경로 조작


def _resolve_npy_and_assets(flow_map_dir: Path):
    """폴더에서 사용할 npy 파일 경로와 대응하는 ref_frame / meta 경로를 결정한다.

    우선순위:
      1. 타임스탬프 파일 쌍 (flow_map_YYYYMMDD_HHMMSS.npy + ref_frame_*.jpg + meta_*.json)
         여러 개면 파일명 역순(최신 우선) 정렬 후 첫 번째 선택.
      2. 레거시 파일 (flow_map.npy + ref_frame.jpg, meta 없음).

    Returns:
        (npy_path, ref_frame_path, meta_path)
        ref_frame_path: 존재하면 Path, 없으면 None
        meta_path: 존재하면 Path, 없으면 None

    Raises:
        FileNotFoundError: 사용 가능한 npy 파일이 하나도 없을 때.
    """
    # ── 타임스탬프 쌍 탐색 ──────────────────────────────────────────────
    # ref_frame_YYYYMMDD_HHMMSS.jpg 와 동명의 npy가 동시에 있는 쌍만 수집
    ts_candidates = []
    for jpg in sorted(flow_map_dir.glob("ref_frame_????????_??????.jpg"), reverse=True):
        ts_part  = jpg.stem[len("ref_frame_"):]             # "YYYYMMDD_HHMMSS" 추출
        npy      = flow_map_dir / f"flow_map_{ts_part}.npy"
        if npy.exists():
            meta = flow_map_dir / f"meta_{ts_part}.json"   # 없으면 None 처리
            ts_candidates.append((npy, jpg, meta if meta.exists() else None))

    if ts_candidates:
        # 가장 최신 타임스탬프 쌍 사용 (역순 정렬 기준 첫 번째)
        npy_path, ref_frame_path, meta_path = ts_candidates[0]
        return npy_path, ref_frame_path, meta_path

    # ── 레거시 파일 (flow_map.npy + ref_frame.jpg) ───────────────────────
    legacy_npy = flow_map_dir / "flow_map.npy"
    if legacy_npy.exists():
        legacy_jpg  = flow_map_dir / "ref_frame.jpg"
        # 레거시에도 meta_*.json이 있으면 사용 (드문 경우지만 방어 처리)
        meta_files  = sorted(flow_map_dir.glob("meta_*.json"), reverse=True)
        meta_path   = meta_files[0] if meta_files else None
        ref_path    = legacy_jpg if legacy_jpg.exists() else None
        return legacy_npy, ref_path, meta_path

    # 둘 다 없으면 → 학습 미완료
    raise FileNotFoundError(
        f"flow map 파일 없음 (학습 미완료 또는 잘못된 camera_id): {flow_map_dir}"
    )


def load_flow_map_data(flow_map_dir: Path) -> dict:
    """flow_maps/{camera_id}/ 폴더를 읽어 시각화 데이터 dict 를 반환한다.

    타임스탬프 형식(flow_map_YYYYMMDD_HHMMSS.npy)과 레거시 형식(flow_map.npy) 모두 지원.
    학습을 스킵하고 스냅샷을 불러오는 경우에도 타임스탬프 파일을 통해 정상 조회된다.

    Args:
        flow_map_dir: flow_map 관련 파일들이 들어있는 camera_id 서브폴더 경로.

    Returns:
        시각화에 필요한 모든 데이터가 담긴 dict.
        JSON 직렬화 가능하도록 numpy 배열은 모두 중첩 리스트로 변환된다.

    Raises:
        FileNotFoundError: 사용 가능한 npy 파일이 존재하지 않을 때.
    """
    # ── 사용할 파일 경로 결정 ─────────────────────────────────────────────
    # 타임스탬프 파일(최신) > 레거시 파일 순서로 자동 선택
    npy_path, ref_frame_path, meta_path = _resolve_npy_and_assets(flow_map_dir)

    # ── npy 로드 ─────────────────────────────────────────────────────────
    raw = np.load(npy_path, allow_pickle=True).item()   # dict 형태로 로드

    flow          = raw["flow"]                          # 글로벌 흐름 벡터 (N×N×2)
    count         = raw["count"]                         # 셀별 학습 샘플 수 (N×N)
    grid_size     = int(flow.shape[0])                   # 격자 크기 (20 등)

    # 버전 4 미만 파일이면 A/B 채널 없음 → 빈 배열로 대체
    flow_a        = raw.get("flow_a",  np.zeros_like(flow))     # A방향 채널 벡터
    count_a       = raw.get("count_a", np.zeros_like(count))    # A방향 채널 샘플 수
    flow_b        = raw.get("flow_b",  np.zeros_like(flow))     # B방향 채널 벡터
    count_b       = raw.get("count_b", np.zeros_like(count))    # B방향 채널 샘플 수

    # 마스크: 저장 안 됐으면 모두 False(0)으로 초기화
    smoothed_mask = raw.get("smoothed_mask", np.zeros((grid_size, grid_size), dtype=bool))
    eroded_mask   = raw.get("eroded_mask",   np.zeros((grid_size, grid_size), dtype=bool))
    speed_ref     = raw.get("speed_ref",     np.zeros((grid_size, grid_size), dtype=np.float32))

    # ── ref_frame → base64 ────────────────────────────────────────────────
    has_ref_frame = ref_frame_path is not None and ref_frame_path.exists()
    ref_frame_b64 = None                              # 기본값: 없음

    if has_ref_frame:
        # 이진 파일을 base64 로 인코딩해 data URI 형식으로 반환
        raw_bytes     = ref_frame_path.read_bytes()
        b64_str       = base64.b64encode(raw_bytes).decode("ascii")
        ref_frame_b64 = f"data:image/jpeg;base64,{b64_str}"

    # ── meta JSON 로드 ────────────────────────────────────────────────────
    dir_label_a   = "A방향"    # 기본 레이블 (meta 없을 때)
    dir_label_b   = "B방향"    # 기본 레이블 (meta 없을 때)
    ref_direction = None        # 기준 방향 벡터 (meta 없을 때 None)

    if meta_path is not None and meta_path.exists():
        try:
            meta          = json.loads(meta_path.read_text(encoding="utf-8"))
            dir_label_a   = meta.get("dir_label_a",  dir_label_a)   # 예: "상행"
            dir_label_b   = meta.get("dir_label_b",  dir_label_b)   # 예: "하행"
            ref_direction = meta.get("ref_direction", None)          # 예: [0.0, -1.0]
        except (json.JSONDecodeError, OSError):
            pass   # 파일 손상 시 기본값 유지

    # ── numpy 배열 → JSON-직렬화 가능한 Python list 변환 ─────────────────
    # bool_ 타입은 Python bool 로, float32 는 float 로 변환해야 json.dumps 가 가능
    return {
        "grid_size":     grid_size,           # 격자 크기 (정수)
        "min_samples":   5,                   # 셀 확정 최소 샘플 수 (DetectorConfig 기본값)
        "flow":          _arr_to_list(flow),  # (N,N,2) → 중첩 리스트
        "count":         count.tolist(),      # (N,N) int 리스트
        "flow_a":        _arr_to_list(flow_a),
        "count_a":       count_a.tolist(),
        "flow_b":        _arr_to_list(flow_b),
        "count_b":       count_b.tolist(),
        "smoothed_mask": _bool_arr_to_list(smoothed_mask),  # bool 중첩 리스트
        "eroded_mask":   _bool_arr_to_list(eroded_mask),
        "speed_ref":     speed_ref.tolist(),
        "dir_label_a":   dir_label_a,         # 예: "상행"
        "dir_label_b":   dir_label_b,         # 예: "하행"
        "ref_direction": ref_direction,        # [dx, dy] 또는 None
        "ref_frame_b64": ref_frame_b64,        # data URI 또는 None
        "has_ref_frame": has_ref_frame,        # bool
    }


def _arr_to_list(arr: np.ndarray) -> list:
    """numpy float 배열을 Python float 중첩 리스트로 변환한다.

    numpy float32 는 json.dumps 에서 직렬화 에러 발생하므로 float() 로 캐스팅한다.
    """
    if arr.ndim == 3:
        # (N, N, 2) 형태: 각 셀이 [dx, dy] 2원소 벡터
        return [
            [[float(arr[r, c, 0]), float(arr[r, c, 1])]
             for c in range(arr.shape[1])]
            for r in range(arr.shape[0])
        ]
    # (N, N) 형태: 단순 2D 배열 (사용처는 없지만 범용성 확보)
    return [[float(arr[r, c]) for c in range(arr.shape[1])]
            for r in range(arr.shape[0])]


def _bool_arr_to_list(arr: np.ndarray) -> list:
    """numpy bool 배열을 Python bool 중첩 리스트로 변환한다.

    numpy bool_ 은 json.dumps 에서 직렬화 에러 발생하므로 bool() 로 캐스팅한다.
    """
    return [
        [bool(arr[r, c]) for c in range(arr.shape[1])]
        for r in range(arr.shape[0])
    ]
