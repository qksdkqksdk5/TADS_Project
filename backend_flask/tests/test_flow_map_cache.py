# tests/test_flow_map_cache.py
# 교통 모니터링 팀 — flow_map 캐시 재사용 기능 TDD 테스트
# Red → Green → Refactor
#
# 실행: backend_flask/ 에서
#     pytest tests/test_flow_map_cache.py -v
#
# 섹션별 범위:
#   A. FlowMapMatcher 단위 테스트 (final_pj/src/flow_map_matcher.py)
#   B. FlowMap.eroded_mask 저장/로드 검증 (flow_map.py 수정 필요 → Red)
#   C. MonitoringDetector._try_load_cache 계약 검증 (신규 메서드 → Red)
#   D. MonitoringDetector._save_cache 계약 검증 (신규 메서드 → Red)

import os
import sys
import threading
import tempfile
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch, call

# ── 실제 모듈 강제 복원 ────────────────────────────────────────────────────────
# test_cap_ffmpeg.py 가 알파벳 순서상 먼저 실행되면서 cv2, numpy,
# detector_modules.* 를 MagicMock 으로 교체한다.
# 이 테스트는 실제 cv2/numpy/FlowMap 이 필요하므로,
# 이미 등록된 스텁을 제거하고 실제 패키지를 강제 임포트한다.
# (sys.modules.pop → import 순서로 파일시스템에서 다시 로드됨)
for _force_real in [
    'cv2',
    'numpy', 'numpy.core', 'numpy.lib',
    'detector_modules', 'detector_modules.flow_map',
    'flow_map_matcher',
    'modules.monitoring.monitoring_detector',
]:
    sys.modules.pop(_force_real, None)

import numpy as np
import cv2

# ── sys.path 설정 ────────────────────────────────────────────────────────────
_HERE             = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR      = os.path.normpath(os.path.join(_HERE, '..'))
_MONITORING_DIR   = os.path.join(_BACKEND_DIR, 'modules', 'monitoring')
_DETECTOR_MODULES = os.path.join(_MONITORING_DIR, 'detector_modules')
_FINAL_PJ_SRC     = r'C:\final_pj\src'

for _p in (_BACKEND_DIR, _MONITORING_DIR, _DETECTOR_MODULES, _FINAL_PJ_SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── 무거운 의존성 스텁 ────────────────────────────────────────────────────────
# cv2, numpy 는 실제 기능이 필요하므로 스텁하지 않는다.
# torch, ultralytics, gevent 등 설치 불필요 패키지만 스텁한다.

def _stub(name):
    """빈 MagicMock 모듈을 sys.modules 에 등록해 ImportError 를 방지한다."""
    mod = MagicMock()
    mod.__name__ = name
    sys.modules.setdefault(name, mod)
    return mod

for _s in [
    'torch', 'torch.nn', 'torch.optim', 'torch.nn.functional',
    'ultralytics',
    'gevent', 'gevent.threadpool',
    'flask', 'flask_socketio',
    'models',
    'modules.traffic',
    'modules.traffic.detectors',
    'modules.traffic.detectors.base_detector',
    'modules.traffic.detectors.manager',
    'modules.monitoring.its_helper',
]:
    _stub(_s)

# gevent.sleep 은 실제 대기 없이 즉시 반환
sys.modules['gevent'].sleep = lambda *a, **kw: None

# gevent.threadpool.ThreadPool: apply() 를 동기 함수 호출로 대체
_tp = sys.modules['gevent.threadpool']
_tp.ThreadPool = lambda **kw: MagicMock(
    apply=lambda f, args=(): f(*args) if args else f()
)

# BaseDetector 최소 스텁 — MonitoringDetector 가 상속하므로 필요
class _BaseDetectorStub:
    """테스트용 BaseDetector 최소 스텁."""
    def __init__(self, *a, **kw):
        # 위치 인수: (cctv_name, url, ...)
        self.cctv_name    = a[0] if a else 'stub'
        self.url          = a[1] if len(a) > 1 else 'rtsp://stub'
        self.is_running   = True
        self.frame_lock   = threading.Lock()
        self.alert_queue  = Queue()
        self.latest_frame = None
    def stop(self):              self.is_running = False
    def process_alert(self, d): pass
    def reconnect(self, **kw):  return False
    def generate_frames(self):  return iter([])

sys.modules['modules.traffic.detectors.base_detector'].BaseDetector = _BaseDetectorStub

# ── 실제 모듈 로드 ────────────────────────────────────────────────────────────
# detector_modules 는 순수 Python+numpy+cv2 → 실제 모듈 로드 가능
from detector_modules.flow_map import FlowMap

# flow_map_matcher 는 C:\final_pj\src 에 위치 → 실제 로드
from flow_map_matcher import FlowMapMatcher, save_ref_frame, score_frames

# MonitoringDetector: 위 스텁 처리 후 로드
from modules.monitoring.monitoring_detector import MonitoringDetector


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

def _make_color_frame(h=200, w=320, color=(100, 150, 80)) -> np.ndarray:
    """테스트용 단색 BGR 프레임을 생성한다."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)  # 3채널 배열 초기화
    frame[:] = color                              # 단일 색으로 채움
    return frame


def _save_fake_flow_npy(path: Path, grid_size: int = 20):
    """FlowMap.save() 포맷과 동일한 가짜 .npy 파일을 저장한다."""
    data = {
        "version":       3,
        "flow":          np.zeros((grid_size, grid_size, 2), np.float32),
        "count":         np.ones((grid_size, grid_size), np.int32) * 10,
        "speed_ref":     np.zeros((grid_size, grid_size), np.float32),
        "smoothed_mask": np.zeros((grid_size, grid_size), dtype=bool),
        "eroded_mask":   np.zeros((grid_size, grid_size), dtype=bool),
    }
    np.save(str(path), data)  # .npy 파일로 저장


# ═══════════════════════════════════════════════════════════════════════════════
# A. FlowMapMatcher 단위 테스트
#    flow_map_matcher.py 의 기존 코드를 직접 검증한다.
#    Green (이미 통과) — 회귀 방지 목적.
# ═══════════════════════════════════════════════════════════════════════════════

class TestFlowMapMatcherUnit:
    """FlowMapMatcher 의 후보 탐색·유사도 판정·ref_frame 저장을 검증한다."""

    def test_candidates_empty_when_root_not_exist(self, tmp_path):
        """flow_maps 루트 폴더가 없으면 후보 목록이 비어야 한다."""
        matcher = FlowMapMatcher(tmp_path / "no_such_dir")
        # 존재하지 않는 경로 → 후보 없음
        assert matcher._candidates() == []

    def test_candidates_skips_folder_without_ref_frame(self, tmp_path):
        """flow_map.npy 만 있고 ref_frame.jpg 없는 폴더는 후보에서 제외된다."""
        road_dir = tmp_path / "road_A"
        road_dir.mkdir()
        _save_fake_flow_npy(road_dir / "flow_map.npy")
        # ref_frame.jpg 없음 → 제외 대상

        matcher = FlowMapMatcher(tmp_path)
        assert matcher._candidates() == []

    def test_candidates_skips_folder_without_flow_npy(self, tmp_path):
        """ref_frame.jpg 만 있고 flow_map.npy 없는 폴더는 후보에서 제외된다."""
        road_dir = tmp_path / "road_B"
        road_dir.mkdir()
        # flow_map.npy 없음 → 제외 대상
        cv2.imwrite(str(road_dir / "ref_frame.jpg"), _make_color_frame())

        matcher = FlowMapMatcher(tmp_path)
        assert matcher._candidates() == []

    def test_candidates_includes_valid_folder(self, tmp_path):
        """flow_map.npy 와 ref_frame.jpg 가 모두 있는 폴더는 후보에 포함된다."""
        road_dir = tmp_path / "road_C"
        road_dir.mkdir()
        _save_fake_flow_npy(road_dir / "flow_map.npy")
        cv2.imwrite(str(road_dir / "ref_frame.jpg"), _make_color_frame())

        matcher = FlowMapMatcher(tmp_path)
        candidates = matcher._candidates()
        assert len(candidates) == 1         # 후보 1개 확인
        assert candidates[0][0] == road_dir  # 올바른 폴더 확인

    def test_find_best_returns_none_when_no_candidates(self, tmp_path):
        """후보가 없으면 (None, 0.0) 을 반환해야 한다."""
        matcher = FlowMapMatcher(tmp_path)
        best_dir, score = matcher.find_best(_make_color_frame())
        assert best_dir is None
        assert score == 0.0

    def test_find_best_returns_none_below_min_score(self, tmp_path):
        """min_score 미만 점수만 있으면 None 을 반환해야 한다."""
        road_dir = tmp_path / "road_D"
        road_dir.mkdir()
        _save_fake_flow_npy(road_dir / "flow_map.npy")
        # 순수 검은 이미지를 ref 로 저장
        cv2.imwrite(str(road_dir / "ref_frame.jpg"),
                    _make_color_frame(color=(0, 0, 0)))

        # 흰 이미지로 매칭 시도 + 매우 높은 임계값 → 미달 확실
        matcher = FlowMapMatcher(tmp_path, min_score=0.99)
        best_dir, score = matcher.find_best(_make_color_frame(color=(255, 255, 255)))
        assert best_dir is None

    def test_find_best_returns_dir_for_same_image(self, tmp_path):
        """저장된 ref_frame 과 동일한 이미지를 입력하면 해당 폴더를 반환한다."""
        road_dir = tmp_path / "road_E"
        road_dir.mkdir()
        _save_fake_flow_npy(road_dir / "flow_map.npy")
        same_frame = _make_color_frame(color=(80, 120, 200))
        cv2.imwrite(str(road_dir / "ref_frame.jpg"), same_frame)

        # min_score 매우 낮게 → 동일 이미지면 반드시 통과
        matcher = FlowMapMatcher(tmp_path, min_score=0.01)
        best_dir, score = matcher.find_best(same_frame)
        assert best_dir == road_dir
        assert score > 0.0

    def test_find_best_excludes_self_dir(self, tmp_path):
        """exclude_dir 로 지정한 폴더는 매칭에서 제외되어야 한다."""
        road_dir = tmp_path / "road_F"
        road_dir.mkdir()
        _save_fake_flow_npy(road_dir / "flow_map.npy")
        frame = _make_color_frame()
        cv2.imwrite(str(road_dir / "ref_frame.jpg"), frame)

        # min_score=0.01 → exclude_dir 제외 후 best_score=0.0 < 0.01 → None 반환
        # (min_score=0.0 은 flow_map_matcher.py 내부 비교 0.0<0.0=False 로 버그 발생)
        matcher = FlowMapMatcher(tmp_path, min_score=0.01)
        best_dir, _ = matcher.find_best(frame, exclude_dir=road_dir)
        assert best_dir is None

    def test_save_ref_frame_creates_jpg(self, tmp_path):
        """save_ref_frame() 호출 시 ref_frame.jpg 파일이 생성된다."""
        road_dir = tmp_path / "cam_01"
        frame = _make_color_frame()
        result = save_ref_frame(frame, road_dir)
        assert result is True                          # 성공 반환값
        assert (road_dir / "ref_frame.jpg").exists()  # 파일 생성 확인

    def test_save_ref_frame_overwrites_existing_file(self, tmp_path):
        """동일 경로에 두 번 저장해도 예외 없이 덮어써야 한다."""
        road_dir = tmp_path / "cam_02"
        frame_a = _make_color_frame(color=(100, 100, 100))
        frame_b = _make_color_frame(color=(200, 200, 200))
        # 첫 번째 저장
        assert save_ref_frame(frame_a, road_dir) is True
        # 두 번째 저장 (덮어쓰기) — 예외 없이 True 반환해야 함
        assert save_ref_frame(frame_b, road_dir) is True
        assert (road_dir / "ref_frame.jpg").exists()


# ═══════════════════════════════════════════════════════════════════════════════
# B. FlowMap.eroded_mask 저장/로드 검증
#    현재 save() 에 eroded_mask 가 없어 Red 상태.
#    flow_map.py 수정 후 Green 으로 전환된다.
# ═══════════════════════════════════════════════════════════════════════════════

class TestFlowMapErodedMask:
    """FlowMap.save() / .load() 가 eroded_mask 를 보존하는지 검증한다."""

    def _make_flow_map(self) -> FlowMap:
        """테스트용 FlowMap 인스턴스를 생성한다 (20×20 그리드, 320×240)."""
        fm = FlowMap(grid_size=20, alpha=0.1, min_samples=5)
        fm.init_grid(320, 240)
        return fm

    def test_save_includes_eroded_mask_key(self, tmp_path):
        """save() 결과 .npy 파일에 'eroded_mask' 키가 포함되어야 한다.

        [Red] 현재 flow_map.py 의 save() 에 eroded_mask 가 없어 실패.
        [Green] flow_map.py save() 딕셔너리에 eroded_mask 추가 후 통과.
        """
        fm = self._make_flow_map()
        fm.eroded_mask[2, 3] = True   # 일부 경계 셀 표시
        fm.eroded_mask[5, 7] = True

        save_path = tmp_path / "flow_map.npy"
        fm.save(save_path)

        data = np.load(str(save_path), allow_pickle=True).item()
        assert "eroded_mask" in data, \
            "save() 에 eroded_mask 키가 없습니다 — flow_map.py 수정 필요"

    def test_load_restores_eroded_mask_values(self, tmp_path):
        """load() 후 eroded_mask 가 저장 시점 값으로 정확히 복원되어야 한다.

        [Red] load() 에 eroded_mask 복원 코드가 없어 실패.
        [Green] flow_map.py load() 에 eroded_mask 복원 추가 후 통과.
        """
        fm_orig = self._make_flow_map()
        fm_orig.eroded_mask[2, 3] = True
        fm_orig.eroded_mask[5, 7] = True

        save_path = tmp_path / "flow_map.npy"
        fm_orig.save(save_path)

        fm_loaded = self._make_flow_map()
        success = fm_loaded.load(save_path)

        assert success is True
        assert bool(fm_loaded.eroded_mask[2, 3]) is True, \
            "eroded_mask[2,3] 이 True 로 복원되어야 합니다"
        assert bool(fm_loaded.eroded_mask[5, 7]) is True, \
            "eroded_mask[5,7] 이 True 로 복원되어야 합니다"
        assert bool(fm_loaded.eroded_mask[0, 0]) is False, \
            "eroded_mask[0,0] 은 False 여야 합니다 (설정하지 않은 셀)"

    def test_eroded_mask_shape_preserved(self, tmp_path):
        """로드 후 eroded_mask 의 shape 가 (grid_size, grid_size) 여야 한다."""
        fm = self._make_flow_map()
        save_path = tmp_path / "flow_map.npy"
        fm.save(save_path)

        fm2 = self._make_flow_map()
        fm2.load(save_path)
        # shape 가 그리드 크기와 일치해야 함
        assert fm2.eroded_mask.shape == (20, 20)


# ═══════════════════════════════════════════════════════════════════════════════
# C. MonitoringDetector._try_load_cache 계약 검증
#    메서드가 없으면 AttributeError → Red.
#    monitoring_detector.py 에 메서드 추가 후 Green.
# ═══════════════════════════════════════════════════════════════════════════════

class _MinimalDetector:
    """
    _try_load_cache / _save_cache 를 테스트하기 위한 최소 스텁.
    MonitoringDetector 의 해당 메서드를 빌려 실행한다.
    """
    def __init__(self, flow_maps_root: Path):
        self.camera_id        = "test_gyeongbu_cam01"  # 카메라 식별자
        self._flow_maps_root  = flow_maps_root          # 캐시 저장 루트
        self.flow             = MagicMock()             # FlowMap 모의
        self.flow.load        = MagicMock(return_value=True)
        self.flow.save        = MagicMock()
        self._ref_dir_called  = False   # _compute_ref_direction 호출 여부
        self._cell_cnt_called = False   # _compute_direction_cell_counts 호출 여부
        # build_directional_channels(ref_dx, ref_dy) 호출 시 필요한 기준 방향
        # _compute_ref_direction() 모의가 실제로 값을 설정하도록 초기화
        self._ref_direction   = (1.0, 0.0)   # 테스트용 고정 기준 방향 (→)

    def _compute_ref_direction(self):
        """기준 방향 벡터 계산 모의 — 호출 여부 기록 및 _ref_direction 설정."""
        self._ref_dir_called  = True
        self._ref_direction   = (1.0, 0.0)   # 테스트 고정값 유지

    def _compute_direction_cell_counts(self):
        """방향별 셀 수 계산 모의 — 호출 여부 기록."""
        self._cell_cnt_called = True


class TestTryLoadCache:
    """`MonitoringDetector._try_load_cache` 행동 계약 검증."""

    # ── 메서드 존재 확인 ─────────────────────────────────────────────────────
    def test_method_exists(self):
        """MonitoringDetector 에 _try_load_cache 메서드가 있어야 한다.

        [Red] 메서드 미구현 → AttributeError.
        """
        assert hasattr(MonitoringDetector, '_try_load_cache'), \
            "_try_load_cache 메서드가 MonitoringDetector 에 없습니다"

    # ── None 프레임 안전 처리 ────────────────────────────────────────────────
    def test_returns_false_when_frame_is_none(self, tmp_path):
        """frame 이 None 이면 예외 없이 False 를 반환해야 한다.

        [위험 2 대응] cap.read() 실패 시 None 프레임이 전달될 수 있다.
        이 때 cv2.resize(None) 등에서 예외가 발생해 run() 이 죽으면 안 된다.
        """
        method = MonitoringDetector._try_load_cache
        det    = _MinimalDetector(tmp_path / "flow_maps")
        result = method(det, None)
        assert result is False

    # ── 캐시 미스 ────────────────────────────────────────────────────────────
    def test_returns_false_on_cache_miss(self, tmp_path):
        """FlowMapMatcher 가 None 을 반환하면 False 를 반환해야 한다."""
        method = MonitoringDetector._try_load_cache
        det    = _MinimalDetector(tmp_path / "flow_maps")

        with patch('modules.monitoring.monitoring_detector.FlowMapMatcher') as M:
            M.return_value.find_best.return_value = (None, 0.1)  # 매칭 실패
            result = method(det, _make_color_frame())

        assert result is False

    # ── 캐시 히트 ────────────────────────────────────────────────────────────
    def test_returns_true_on_cache_hit(self, tmp_path):
        """캐시 히트 시 True 를 반환해야 한다."""
        method         = MonitoringDetector._try_load_cache
        flow_maps_root = tmp_path / "flow_maps"
        det            = _MinimalDetector(flow_maps_root)
        best_dir       = flow_maps_root / "gyeongbu_ref"
        best_dir.mkdir(parents=True)
        _save_fake_flow_npy(best_dir / "flow_map.npy")

        with patch('modules.monitoring.monitoring_detector.FlowMapMatcher') as M:
            M.return_value.find_best.return_value = (best_dir, 0.75)
            result = method(det, _make_color_frame())

        assert result is True

    def test_flow_load_called_with_correct_path(self, tmp_path):
        """캐시 히트 시 flow.load() 가 best_dir/flow_map.npy 경로로 호출된다."""
        method         = MonitoringDetector._try_load_cache
        flow_maps_root = tmp_path / "flow_maps"
        det            = _MinimalDetector(flow_maps_root)
        best_dir       = flow_maps_root / "gyeongbu_ref"
        best_dir.mkdir(parents=True)
        _save_fake_flow_npy(best_dir / "flow_map.npy")

        with patch('modules.monitoring.monitoring_detector.FlowMapMatcher') as M:
            M.return_value.find_best.return_value = (best_dir, 0.75)
            method(det, _make_color_frame())

        # flow.load() 가 정확한 경로로 호출됐는지 확인
        det.flow.load.assert_called_once_with(best_dir / "flow_map.npy")

    def test_calls_compute_ref_direction_on_hit(self, tmp_path):
        """캐시 히트 시 _compute_ref_direction() 이 반드시 호출되어야 한다.

        [위험 4 대응] 미호출 시 self._ref_direction=None → 방향 분류 불가.
        """
        method         = MonitoringDetector._try_load_cache
        flow_maps_root = tmp_path / "flow_maps"
        det            = _MinimalDetector(flow_maps_root)
        best_dir       = flow_maps_root / "gyeongbu_ref"
        best_dir.mkdir(parents=True)
        _save_fake_flow_npy(best_dir / "flow_map.npy")

        with patch('modules.monitoring.monitoring_detector.FlowMapMatcher') as M:
            M.return_value.find_best.return_value = (best_dir, 0.75)
            method(det, _make_color_frame())

        assert det._ref_dir_called is True, \
            "_compute_ref_direction() 이 호출되지 않았습니다"

    def test_calls_compute_direction_cell_counts_on_hit(self, tmp_path):
        """캐시 히트 시 _compute_direction_cell_counts() 가 호출되어야 한다."""
        method         = MonitoringDetector._try_load_cache
        flow_maps_root = tmp_path / "flow_maps"
        det            = _MinimalDetector(flow_maps_root)
        best_dir       = flow_maps_root / "gyeongbu_ref"
        best_dir.mkdir(parents=True)
        _save_fake_flow_npy(best_dir / "flow_map.npy")

        with patch('modules.monitoring.monitoring_detector.FlowMapMatcher') as M:
            M.return_value.find_best.return_value = (best_dir, 0.75)
            method(det, _make_color_frame())

        assert det._cell_cnt_called is True, \
            "_compute_direction_cell_counts() 이 호출되지 않았습니다"

    # ── 예외 안전 처리 (이전 freeze 핵심 원인 방지) ─────────────────────────
    def test_exception_returns_false_not_raise(self, tmp_path):
        """내부 예외가 발생해도 False 를 반환하고 예외를 전파하지 않아야 한다.

        [위험 1 대응] 예외가 run() 까지 전파되면 generate_frames() 가 마지막
        프레임을 무한 반복해 "사진처럼 멈춘" 화면이 된다.
        """
        method = MonitoringDetector._try_load_cache
        det    = _MinimalDetector(tmp_path / "flow_maps")

        with patch(
            'modules.monitoring.monitoring_detector.FlowMapMatcher',
            side_effect=RuntimeError("테스트용 예외 — run() 을 죽이면 안 됨")
        ):
            try:
                result = method(det, _make_color_frame())
            except Exception as e:
                assert False, f"_try_load_cache 가 예외를 전파했습니다: {e}"

        assert result is False, "예외 발생 시 False 를 반환해야 합니다"

    def test_returns_false_when_flow_load_fails(self, tmp_path):
        """flow.load() 가 False 를 반환하면 캐시 미스로 처리해야 한다.

        [위험 7 대응] 해상도 불일치 등으로 load() 가 실패할 수 있다.
        """
        method         = MonitoringDetector._try_load_cache
        flow_maps_root = tmp_path / "flow_maps"
        det            = _MinimalDetector(flow_maps_root)
        det.flow.load  = MagicMock(return_value=False)  # 로드 실패 시뮬레이션
        best_dir       = flow_maps_root / "ref_dir"
        best_dir.mkdir(parents=True)

        with patch('modules.monitoring.monitoring_detector.FlowMapMatcher') as M:
            M.return_value.find_best.return_value = (best_dir, 0.75)
            result = method(det, _make_color_frame())

        assert result is False, "flow.load() 실패 시 False 를 반환해야 합니다"

    # ── 자체 캐시 히트 (동일 카메라 재시작 시나리오) ─────────────────────────
    def test_self_cache_hit_returns_true(self, tmp_path):
        """같은 카메라 ID 의 flow_map.npy 가 있으면 FlowMapMatcher 없이 바로 True 를 반환해야 한다.

        [핵심 버그 수정] 기존 코드는 자기 자신 폴더를 exclude_dir 로 제외해서
        서버 재시작 후 같은 구간을 선택해도 항상 학습 모드로 빠지는 문제가 있었다.
        1단계: my_dir/flow_map.npy 존재 시 바로 로드 → FlowMapMatcher 호출 불필요.
        """
        method         = MonitoringDetector._try_load_cache
        flow_maps_root = tmp_path / "flow_maps"
        det            = _MinimalDetector(flow_maps_root)

        # 자기 자신의 폴더(camera_id 이름)에 flow_map.npy 를 미리 생성
        my_dir = flow_maps_root / det.camera_id
        my_dir.mkdir(parents=True)
        _save_fake_flow_npy(my_dir / "flow_map.npy")

        # FlowMapMatcher 는 호출되어선 안 된다 (1단계에서 이미 히트)
        with patch('modules.monitoring.monitoring_detector.FlowMapMatcher') as M:
            result = method(det, _make_color_frame())

        assert result is True, "자체 flow_map 이 있으면 True 를 반환해야 합니다"
        M.assert_not_called()   # FlowMapMatcher 가 생성되지 않았는지 확인

    def test_self_cache_hit_calls_compute_functions(self, tmp_path):
        """자체 캐시 히트 시 _compute_ref_direction / _compute_direction_cell_counts 가 호출된다."""
        method         = MonitoringDetector._try_load_cache
        flow_maps_root = tmp_path / "flow_maps"
        det            = _MinimalDetector(flow_maps_root)

        # 자기 자신 폴더에 flow_map.npy 생성
        my_dir = flow_maps_root / det.camera_id
        my_dir.mkdir(parents=True)
        _save_fake_flow_npy(my_dir / "flow_map.npy")

        with patch('modules.monitoring.monitoring_detector.FlowMapMatcher'):
            method(det, _make_color_frame())

        assert det._ref_dir_called is True, \
            "_compute_ref_direction() 이 호출되지 않았습니다"
        assert det._cell_cnt_called is True, \
            "_compute_direction_cell_counts() 이 호출되지 않았습니다"

    def test_self_cache_load_fail_falls_back_to_matcher(self, tmp_path):
        """자체 flow_map 로드 실패(grid 불일치 등) 시 FlowMapMatcher 교차 탐색으로 넘어간다."""
        method         = MonitoringDetector._try_load_cache
        flow_maps_root = tmp_path / "flow_maps"
        det            = _MinimalDetector(flow_maps_root)
        # flow.load() 가 항상 False 를 반환하도록 설정 (grid 불일치 시뮬레이션)
        det.flow.load  = MagicMock(return_value=False)

        # 자기 자신 폴더에 flow_map.npy 생성 (로드는 실패)
        my_dir = flow_maps_root / det.camera_id
        my_dir.mkdir(parents=True)
        _save_fake_flow_npy(my_dir / "flow_map.npy")

        # FlowMapMatcher 는 교차 탐색을 위해 호출되어야 한다
        with patch('modules.monitoring.monitoring_detector.FlowMapMatcher') as M:
            M.return_value.find_best.return_value = (None, 0.0)  # 교차 탐색도 실패
            result = method(det, _make_color_frame())

        assert result is False, "자체 로드 실패 + 교차 탐색 실패 → False"
        M.assert_called_once()  # FlowMapMatcher 가 fallback 으로 호출됐는지 확인


# ═══════════════════════════════════════════════════════════════════════════════
# D. MonitoringDetector._save_cache 계약 검증
#    메서드가 없으면 AttributeError → Red.
# ═══════════════════════════════════════════════════════════════════════════════

class TestSaveCache:
    """`MonitoringDetector._save_cache` 행동 계약 검증."""

    def test_method_exists(self):
        """MonitoringDetector 에 _save_cache 메서드가 있어야 한다.

        [Red] 메서드 미구현 → AttributeError.
        """
        assert hasattr(MonitoringDetector, '_save_cache'), \
            "_save_cache 메서드가 MonitoringDetector 에 없습니다"

    def test_flow_save_called_with_camera_id_path(self, tmp_path):
        """_save_cache() 호출 시 flow.save() 가 camera_id 기반 경로로 호출된다."""
        method         = MonitoringDetector._save_cache
        flow_maps_root = tmp_path / "flow_maps"
        det            = _MinimalDetector(flow_maps_root)
        frame          = _make_color_frame()

        with patch('modules.monitoring.monitoring_detector.save_ref_frame'):
            method(det, frame)

        # 저장 경로: flow_maps_root / camera_id / flow_map.npy
        expected = flow_maps_root / det.camera_id / "flow_map.npy"
        det.flow.save.assert_called_once_with(expected)

    def test_save_ref_frame_called_with_correct_args(self, tmp_path):
        """_save_cache() 호출 시 save_ref_frame(frame, road_dir) 가 호출된다."""
        method         = MonitoringDetector._save_cache
        flow_maps_root = tmp_path / "flow_maps"
        det            = _MinimalDetector(flow_maps_root)
        frame          = _make_color_frame()

        with patch(
            'modules.monitoring.monitoring_detector.save_ref_frame'
        ) as mock_save_ref:
            method(det, frame)

        mock_save_ref.assert_called_once()
        # 두 번째 인자가 camera_id 기반 road_dir 인지 확인
        _, call_kwargs = mock_save_ref.call_args
        call_positional = mock_save_ref.call_args[0]
        assert call_positional[1] == flow_maps_root / det.camera_id

    def test_exception_does_not_propagate(self, tmp_path):
        """flow.save() 에서 예외가 발생해도 _save_cache 는 예외를 전파하지 않는다.

        [위험 1 대응] 디스크 꽉 참 등의 예외가 run() 을 종료시키면 안 된다.
        """
        method        = MonitoringDetector._save_cache
        det           = _MinimalDetector(tmp_path / "flow_maps")
        det.flow.save = MagicMock(side_effect=OSError("디스크 꽉 참"))
        frame         = _make_color_frame()

        try:
            method(det, frame)   # 예외가 전파되면 안 됨
        except Exception as e:
            assert False, f"_save_cache 가 예외를 전파했습니다: {e}"
