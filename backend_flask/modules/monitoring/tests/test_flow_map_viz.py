# 파일 경로: modules/monitoring/tests/test_flow_map_viz.py
# 역할: /api/monitoring/flow_map_viz/<camera_id> 엔드포인트의 데이터 준비 로직을 검증한다.
# TDD Red 단계: 아직 구현되지 않은 함수를 호출하므로 테스트가 실패해야 정상이다.

import sys
import os
import json
import base64
import tempfile
import numpy as np
import pytest
from pathlib import Path

# ── 테스트 대상 모듈 경로 등록 ────────────────────────────────────────────
# Flask/gevent 의존성 없이 순수 헬퍼만 임포트하기 위해 detector_modules 폴더를 추가한다
_MONITORING_DIR       = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DETECTOR_MODULES_DIR = os.path.join(_MONITORING_DIR, "detector_modules")
for _p in (_MONITORING_DIR, _DETECTOR_MODULES_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flow_map_viz_helper import load_flow_map_data as _load_flow_map_data


# ── 픽스처: 임시 flow_maps 디렉터리 ─────────────────────────────────────────

@pytest.fixture
def tmp_flow_dir(tmp_path):
    """임시 폴더에 카메라 ID 서브폴더를 만들어 반환한다."""
    cam_dir = tmp_path / "gyeongbu_test_cam"  # 가상 카메라 디렉터리
    cam_dir.mkdir()                            # 폴더 생성
    return cam_dir


@pytest.fixture
def sample_npy(tmp_flow_dir):
    """최소한의 유효한 flow_map.npy를 임시 폴더에 만들고 경로를 반환한다."""
    grid = 5   # 테스트용 5×5 그리드 (실제는 20×20)

    # 유효한 방향 벡터 (우→하 방향)
    flow = np.zeros((grid, grid, 2), dtype=np.float32)
    flow[1, 1] = [0.0, 1.0]   # 셀 (1,1): 아래 방향
    flow[2, 2] = [1.0, 0.0]   # 셀 (2,2): 오른쪽 방향

    count = np.zeros((grid, grid), dtype=np.int32)
    count[1, 1] = 10           # 셀 (1,1): 10회 학습
    count[2, 2] = 3            # 셀 (2,2): 3회 학습 (min_samples=5 미만)

    flow_a  = flow.copy()      # A채널 (단순화: 글로벌과 동일)
    count_a = count.copy()
    flow_b  = np.zeros_like(flow)   # B채널 비어있음
    count_b = np.zeros_like(count)

    smoothed_mask = np.zeros((grid, grid), dtype=bool)
    smoothed_mask[3, 3] = True     # 셀 (3,3): 보간 채움

    eroded_mask = np.zeros((grid, grid), dtype=bool)
    eroded_mask[0, 0] = True       # 셀 (0,0): 경계 삭제

    speed_ref = np.zeros((grid, grid), dtype=np.float32)
    speed_ref[1, 1] = 0.35         # 셀 (1,1): 정상 속도 기준

    data = {
        "version":       4,
        "flow":          flow,
        "count":         count,
        "flow_a":        flow_a,
        "count_a":       count_a,
        "flow_b":        flow_b,
        "count_b":       count_b,
        "smoothed_mask": smoothed_mask,
        "eroded_mask":   eroded_mask,
        "speed_ref":     speed_ref,
    }
    npy_path = tmp_flow_dir / "flow_map.npy"
    np.save(npy_path, data)   # .npy로 저장
    return npy_path


@pytest.fixture
def sample_ref_frame(tmp_flow_dir):
    """5×5 픽셀 더미 JPEG 파일을 임시 폴더에 만들고 경로를 반환한다."""
    try:
        import cv2                                     # OpenCV로 JPEG 생성
        img = np.zeros((5, 5, 3), dtype=np.uint8)     # 5×5 검은 이미지
        img_path = tmp_flow_dir / "ref_frame.jpg"
        cv2.imwrite(str(img_path), img)                # JPEG로 저장
        return img_path
    except ImportError:
        # OpenCV 없으면 최소 JPEG 바이트로 더미 파일 생성 (FFD8FFE0 소이 헤더)
        jpg_bytes = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10,       # SOI + APP0 헤더
            0x4A, 0x46, 0x49, 0x46, 0x00,             # "JFIF\0"
            0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, # 버전·밀도
            0x00, 0x00,                                # 썸네일 없음
            0xFF, 0xD9,                                # EOI (파일 끝)
        ])
        img_path = tmp_flow_dir / "ref_frame.jpg"
        img_path.write_bytes(jpg_bytes)
        return img_path


@pytest.fixture
def sample_meta(tmp_flow_dir):
    """meta_20260101_000000.json 파일을 임시 폴더에 만들고 경로를 반환한다."""
    meta = {
        "camera_id":    "gyeongbu_test_cam",
        "dir_label_a":  "상행",
        "dir_label_b":  "하행",
        "ref_direction": [0.0, -1.0],       # 위쪽 방향
        "timestamp":    "2026-01-01T00:00:00Z",
    }
    meta_path = tmp_flow_dir / "meta_20260101_000000.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta_path


def _make_npy_data(grid=5):
    """테스트용 flow map numpy 배열 dict 를 생성한다."""
    flow = np.zeros((grid, grid, 2), dtype=np.float32)
    flow[1, 1] = [0.0, 1.0]
    count = np.zeros((grid, grid), dtype=np.int32)
    count[1, 1] = 10
    return {
        "version":       4,
        "flow":          flow,
        "count":         count,
        "flow_a":        flow.copy(),
        "count_a":       count.copy(),
        "flow_b":        np.zeros_like(flow),
        "count_b":       np.zeros_like(count),
        "smoothed_mask": np.zeros((grid, grid), dtype=bool),
        "eroded_mask":   np.zeros((grid, grid), dtype=bool),
        "speed_ref":     np.zeros((grid, grid), dtype=np.float32),
    }


@pytest.fixture
def ts_npy_only(tmp_flow_dir):
    """타임스탬프 npy 만 있고 ref_frame / meta 는 없는 케이스 — 학습 스킵 최소 상황.

    save_flow_snapshot() 이 저장하는 형식: flow_map_YYYYMMDD_HHMMSS.npy
    ref_frame_YYYYMMDD_HHMMSS.jpg 가 없어야 타임스탬프 쌍이 아닌 'npy만 존재' 케이스가 됨.
    """
    npy_path = tmp_flow_dir / "flow_map_20260101_120000.npy"
    np.save(npy_path, _make_npy_data())
    return npy_path


@pytest.fixture
def ts_full_pair(tmp_flow_dir):
    """타임스탬프 npy + ref_frame + meta 모두 있는 케이스 — 실제 save_flow_snapshot 결과.

    flow_map_YYYYMMDD_HHMMSS.npy + ref_frame_YYYYMMDD_HHMMSS.jpg + meta_YYYYMMDD_HHMMSS.json
    """
    ts      = "20260430_090000"
    npy     = tmp_flow_dir / f"flow_map_{ts}.npy"
    jpg     = tmp_flow_dir / f"ref_frame_{ts}.jpg"
    meta_p  = tmp_flow_dir / f"meta_{ts}.json"

    np.save(npy, _make_npy_data())

    # 최소 유효 JPEG (SOI + EOI)
    jpg.write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10,
                            0x4A, 0x46, 0x49, 0x46, 0x00,
                            0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01,
                            0x00, 0x00, 0xFF, 0xD9]))

    meta    = {"dir_label_a": "상행", "dir_label_b": "하행",
               "ref_direction": [0.0, -1.0]}
    meta_p.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    return npy, jpg, meta_p


# ═══════════════════════════════════════════════════════════════════════════
#  테스트 클래스
# ═══════════════════════════════════════════════════════════════════════════

class TestLoadFlowMapData:
    """_load_flow_map_data(flow_map_dir) 함수의 동작을 검증한다."""

    def test_missing_npy_raises_file_not_found(self, tmp_flow_dir):
        """flow_map.npy 가 없으면 FileNotFoundError 가 발생해야 한다."""
        with pytest.raises(FileNotFoundError):
            _load_flow_map_data(tmp_flow_dir)

    def test_returns_dict_with_required_keys(self, tmp_flow_dir, sample_npy):
        """npy 파일이 있으면 필수 키를 모두 포함한 dict를 반환해야 한다."""
        result = _load_flow_map_data(tmp_flow_dir)

        required_keys = [
            "grid_size", "min_samples",
            "flow", "count",
            "flow_a", "count_a",
            "flow_b", "count_b",
            "smoothed_mask", "eroded_mask", "speed_ref",
            "dir_label_a", "dir_label_b",
            "ref_frame_b64", "has_ref_frame",
        ]
        for key in required_keys:
            assert key in result, f"필수 키 누락: {key}"

    def test_grid_size_matches_npy(self, tmp_flow_dir, sample_npy):
        """반환된 grid_size 가 실제 npy 배열 크기와 일치해야 한다."""
        result = _load_flow_map_data(tmp_flow_dir)
        assert result["grid_size"] == 5, "grid_size가 npy 배열 크기(5)와 다르다"

    def test_flow_shape_is_list(self, tmp_flow_dir, sample_npy):
        """flow 배열이 중첩 리스트로 직렬화돼야 한다 (JSON 직렬화 가능)."""
        result = _load_flow_map_data(tmp_flow_dir)
        assert isinstance(result["flow"], list), "flow는 list여야 한다"
        assert isinstance(result["flow"][0], list), "flow[0]은 list여야 한다"
        assert isinstance(result["flow"][0][0], list), "flow[0][0]은 [dx, dy] list여야 한다"
        assert len(result["flow"][0][0]) == 2, "[dx, dy] 길이는 2여야 한다"

    def test_count_values_preserved(self, tmp_flow_dir, sample_npy):
        """count 값이 npy 원본과 동일하게 반환돼야 한다."""
        result = _load_flow_map_data(tmp_flow_dir)
        assert result["count"][1][1] == 10, "셀(1,1) count가 10이어야 한다"
        assert result["count"][2][2] == 3,  "셀(2,2) count가 3이어야 한다"

    def test_smoothed_eroded_mask_as_bool_list(self, tmp_flow_dir, sample_npy):
        """smoothed_mask / eroded_mask 가 bool 값의 중첩 리스트여야 한다."""
        result = _load_flow_map_data(tmp_flow_dir)
        assert result["smoothed_mask"][3][3] is True,  "smoothed_mask[3][3]이 True여야 한다"
        assert result["eroded_mask"][0][0]  is True,   "eroded_mask[0][0]이 True여야 한다"
        assert result["smoothed_mask"][0][0] is False, "smoothed_mask[0][0]이 False여야 한다"

    def test_no_ref_frame(self, tmp_flow_dir, sample_npy):
        """ref_frame.jpg 가 없으면 has_ref_frame=False, ref_frame_b64=None이어야 한다."""
        result = _load_flow_map_data(tmp_flow_dir)
        assert result["has_ref_frame"] is False
        assert result["ref_frame_b64"] is None

    def test_with_ref_frame(self, tmp_flow_dir, sample_npy, sample_ref_frame):
        """ref_frame.jpg 가 있으면 has_ref_frame=True, base64 문자열을 반환해야 한다."""
        result = _load_flow_map_data(tmp_flow_dir)
        assert result["has_ref_frame"] is True
        assert result["ref_frame_b64"] is not None
        # data URI 형식 확인
        assert result["ref_frame_b64"].startswith("data:image/jpeg;base64,"), \
            "base64 문자열이 data URI 형식이어야 한다"

    def test_meta_labels_loaded(self, tmp_flow_dir, sample_npy, sample_meta):
        """meta JSON이 있으면 dir_label_a / dir_label_b / ref_direction 이 로드돼야 한다."""
        result = _load_flow_map_data(tmp_flow_dir)
        assert result["dir_label_a"] == "상행",       "dir_label_a가 '상행'이어야 한다"
        assert result["dir_label_b"] == "하행",       "dir_label_b가 '하행'이어야 한다"
        assert result["ref_direction"] == [0.0, -1.0], "ref_direction이 [0.0, -1.0]이어야 한다"

    def test_default_labels_without_meta(self, tmp_flow_dir, sample_npy):
        """meta JSON이 없어도 기본 레이블로 대체돼야 한다 (에러 없음)."""
        result = _load_flow_map_data(tmp_flow_dir)
        # 기본값이 존재하면 됨 (빈 문자열이 아닌 무언가)
        assert isinstance(result["dir_label_a"], str)
        assert isinstance(result["dir_label_b"], str)


class TestTimestampedFiles:
    """학습 스킵 시나리오: save_flow_snapshot() 이 저장한 타임스탬프 파일로 조회 가능한지 검증."""

    def test_ts_npy_without_ref_frame_raises_or_no_ref(self, tmp_flow_dir, ts_npy_only):
        """타임스탬프 npy 만 있고 ref_frame_*.jpg 가 없으면
        has_ref_frame=False 로 정상 반환돼야 한다 (FileNotFoundError 아님).

        이 케이스: npy는 있지만 jpg 쌍이 없어서 타임스탬프 쌍 탐색에서 탈락,
        legacy flow_map.npy 도 없으므로 FileNotFoundError 발생이 올바른 동작.
        """
        # ref_frame_YYYYMMDD_HHMMSS.jpg 가 없으면 타임스탬프 쌍 탐색에서 탈락
        # → legacy flow_map.npy 도 없음 → FileNotFoundError
        with pytest.raises(FileNotFoundError):
            _load_flow_map_data(tmp_flow_dir)

    def test_ts_full_pair_loaded_successfully(self, tmp_flow_dir, ts_full_pair):
        """타임스탬프 쌍(npy + ref_frame + meta) 이 있으면 정상 조회돼야 한다.

        이것이 '학습 스킵' 시나리오의 핵심 케이스:
        save_flow_snapshot() 이 저장한 파일만 있어도 플로우맵 보기가 가능해야 한다.
        """
        result = _load_flow_map_data(tmp_flow_dir)

        assert result["grid_size"]    == 5,      "grid_size 가 5 여야 한다"
        assert result["has_ref_frame"] is True,  "ref_frame 이 있어야 한다"
        assert result["ref_frame_b64"] is not None, "base64 인코딩 값이 있어야 한다"
        assert result["ref_frame_b64"].startswith("data:image/jpeg;base64,")
        assert result["dir_label_a"]  == "상행",  "meta의 dir_label_a 가 로드돼야 한다"
        assert result["dir_label_b"]  == "하행",  "meta의 dir_label_b 가 로드돼야 한다"
        assert result["ref_direction"] == [0.0, -1.0]

    def test_ts_preferred_over_legacy(self, tmp_flow_dir, ts_full_pair, sample_npy):
        """타임스탬프 쌍과 레거시 flow_map.npy 가 동시에 있으면 타임스탬프를 우선 사용한다.

        최신 스냅샷이 더 정확하므로 타임스탬프 파일이 우선순위를 가져야 한다.
        """
        # ts_full_pair: flow_map_20260430_090000.npy (count[1][1]=10)
        # sample_npy: flow_map.npy (count[1][1]=10, 동일하므로 구분을 위해 값 변경)
        # legacy npy를 다른 count 값으로 덮어쓴다
        legacy_data = _make_npy_data()
        legacy_data["count"][1][1] = 99   # 레거시는 99로 덮어씀
        np.save(tmp_flow_dir / "flow_map.npy", legacy_data)

        result = _load_flow_map_data(tmp_flow_dir)
        # 타임스탬프 파일(count=10)이 선택돼야 한다 (레거시 count=99 가 아님)
        assert result["count"][1][1] == 10, "타임스탬프 파일(count=10)이 우선 사용돼야 한다"

    def test_missing_all_raises_file_not_found(self, tmp_flow_dir):
        """npy 파일이 하나도 없으면 FileNotFoundError 가 발생해야 한다."""
        with pytest.raises(FileNotFoundError):
            _load_flow_map_data(tmp_flow_dir)
