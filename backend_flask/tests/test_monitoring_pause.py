# tests/test_monitoring_pause.py
# 교통 모니터링 팀 — 탭 이탈 시 일시정지 기능 TDD 테스트 (Red → Green → Refactor)
# pytest 실행: backend_flask/ 에서 `pytest tests/test_monitoring_pause.py -v`

import sys
import os
import threading
from queue import Queue
from unittest.mock import MagicMock, patch

# ── 경로 설정 ──────────────────────────────────────────────────────────────
# backend_flask/ 를 sys.path 최우선으로 추가 (modules.* 임포트 기반)
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, _BACKEND_DIR)

# ── 무거운 외부 의존성 스텁 처리 ─────────────────────────────────────────────
# YOLO, cv2, torch 등 설치 없이 테스트 실행 가능하도록 가짜 모듈로 대체

def _stub(name):
    """빈 MagicMock 모듈을 sys.modules에 등록해 ImportError를 방지한다."""
    mod = MagicMock()
    mod.__name__ = name
    sys.modules.setdefault(name, mod)
    return mod

for _s in [
    'cv2', 'torch', 'ultralytics',
    'gevent', 'gevent.threadpool',
    'flask', 'flask_socketio',
    'models',
    'modules.traffic.detectors.base_detector',
    'modules.traffic.detectors.manager',
    # its_helper 는 os/time/requests 만 사용 → 스텁 불필요, 실제 모듈 로드
    'modules.monitoring.monitoring_detector',
    'detector_modules', 'detector_modules.config', 'detector_modules.state',
    'detector_modules.flow_map', 'detector_modules.tracker',
    'detector_modules.judge', 'detector_modules.id_manager',
    'detector_modules.camera_switch', 'detector_modules.traffic_analyzer',
    'detector_modules.gru_module', 'detector_modules.congestion_judge',
]:
    _stub(_s)

# gevent.sleep 은 테스트에서 실제 대기하지 않도록 no-op으로 대체
sys.modules['gevent'].sleep = lambda *a, **kw: None


# ── BaseDetector 스텁 ──────────────────────────────────────────────────────
class _BaseDetectorStub:
    """테스트용 BaseDetector 최소 스텁."""
    def __init__(self, *a, **kw):
        self.cctv_name   = kw.get('cctv_name', 'test_cam')
        self.is_running  = True
        self.frame_lock  = threading.Lock()
        self.alert_queue = Queue()
    def start_alert_worker(self): pass
    def stop(self): self.is_running = False
    def process_alert(self, data): pass

sys.modules['modules.traffic.detectors.base_detector'].BaseDetector = _BaseDetectorStub

# ── 실제 테스트 대상 임포트 ──────────────────────────────────────────────────
from modules.monitoring import monitoring  # 실제 monitoring.py


# ── 헬퍼: 가짜 MonitoringDetector ────────────────────────────────────────────
class FakeDetector:
    """
    MonitoringDetector 의 pause/resume 인터페이스만 흉내내는 가짜 감지기.
    실제 YOLO 로드 없이 상태 변화만 검증한다.
    """
    def __init__(self, camera_id='cam_test'):
        self.camera_id  = camera_id  # 카메라 식별자
        self.is_running = True       # 실행 중 여부
        self._paused    = False      # 일시정지 플래그 — 구현 후 존재해야 함

    def pause(self):
        """일시정지: 추론 루프를 멈춘다."""
        self._paused = True

    def resume(self):
        """재개: 추론 루프를 다시 시작한다."""
        self._paused = False


# ════════════════════════════════════════════════════════════════════════════
# 1. FakeDetector 자체 동작 (인터페이스 명세 확인용)
# ════════════════════════════════════════════════════════════════════════════

class TestDetectorPauseResume:
    """감지기의 pause/resume 플래그 동작 검증."""

    def setup_method(self):
        self.det = FakeDetector('cam_001')

    def test_초기_상태는_일시정지_아님(self):
        """감지기 생성 직후 _paused 는 False 여야 한다."""
        assert self.det._paused is False

    def test_pause_호출_후_paused_True(self):
        """pause() 호출 시 _paused 가 True 로 바뀐다."""
        self.det.pause()
        assert self.det._paused is True

    def test_resume_호출_후_paused_False(self):
        """pause() 후 resume() 호출 시 _paused 가 다시 False 로 바뀐다."""
        self.det.pause()
        self.det.resume()
        assert self.det._paused is False

    def test_resume_를_pause_없이_호출해도_안전(self):
        """resume() 을 pause 없이 호출해도 예외가 발생하지 않는다."""
        self.det.resume()
        assert self.det._paused is False


# ════════════════════════════════════════════════════════════════════════════
# 2. monitoring.py — _pause_all_monitoring / _resume_all_monitoring 테스트
#    (Green 단계에서 이 함수들이 monitoring.py 에 추가되어야 통과)
# ════════════════════════════════════════════════════════════════════════════

class TestPauseResumeAll:
    """detector_manager 내 모든 MonitoringDetector 일괄 pause/resume 검증."""

    def setup_method(self):
        """각 테스트 전 monitoring 모듈 내부 상태 초기화."""
        monitoring._monitoring_sids.clear()

        # 가짜 감지기 2개 (monitoring) + 1개 (타 팀)
        self.det_a    = FakeDetector('cam_001')
        self.det_b    = FakeDetector('cam_002')
        self.plate_det = MagicMock()   # 타 팀 감지기

        # detector_manager Mock
        mock_manager = MagicMock()
        mock_manager.active_detectors = {
            'monitoring_cam_001': self.det_a,
            'monitoring_cam_002': self.det_b,
            'plate_cam_003':      self.plate_det,  # 타 팀 감지기
        }
        mock_manager._lock = threading.Lock()
        monitoring.detector_manager   = mock_manager

        # isinstance 체크가 FakeDetector 도 통과하도록 패치
        monitoring.MonitoringDetector = FakeDetector

    def test_pause_all_이_모니터링_감지기만_pause(self):
        """_pause_all_monitoring() 은 monitoring_ 키 감지기만 pause 한다."""
        monitoring._pause_all_monitoring()
        assert self.det_a._paused is True
        assert self.det_b._paused is True

    def test_pause_all_이_타팀_감지기_건드리지_않음(self):
        """_pause_all_monitoring() 은 monitoring_ 접두사가 아닌 감지기는 건드리지 않는다."""
        monitoring._pause_all_monitoring()
        self.plate_det.pause.assert_not_called()

    def test_resume_all_이_모니터링_감지기만_resume(self):
        """_resume_all_monitoring() 은 일시정지된 monitoring_ 키 감지기를 resume 한다."""
        self.det_a.pause()
        self.det_b.pause()
        monitoring._resume_all_monitoring()
        assert self.det_a._paused is False
        assert self.det_b._paused is False


# ════════════════════════════════════════════════════════════════════════════
# 3. PERSIST_MODE 플래그 동작 테스트
# ════════════════════════════════════════════════════════════════════════════

class TestPersistMode:
    """PERSIST_MODE 값에 따른 disconnect 처리 분기 검증."""

    def setup_method(self):
        monitoring._monitoring_sids.clear()
        self.det = FakeDetector('cam_001')
        mock_manager = MagicMock()
        mock_manager.active_detectors = {'monitoring_cam_001': self.det}
        mock_manager._lock = threading.Lock()
        monitoring.detector_manager   = mock_manager
        monitoring.MonitoringDetector = FakeDetector

    def test_PERSIST_MODE_속성이_존재함(self):
        """monitoring 모듈에 PERSIST_MODE 속성이 있어야 한다."""
        assert hasattr(monitoring, 'PERSIST_MODE')

    def test_persist_mode_false_sid_없으면_pause_실행(self):
        """
        PERSIST_MODE=False, 연결 SID 0개 → 일시정지 실행.
        (on_disconnect 로직 시뮬레이션)
        """
        orig = monitoring.PERSIST_MODE
        monitoring.PERSIST_MODE = False
        try:
            monitoring._monitoring_sids.add('sid_x')
            monitoring._monitoring_sids.discard('sid_x')
            # SID 없고 PERSIST_MODE=False → pause
            if not monitoring._monitoring_sids and not monitoring.PERSIST_MODE:
                monitoring._pause_all_monitoring()
            assert self.det._paused is True
        finally:
            monitoring.PERSIST_MODE = orig

    def test_persist_mode_true_sid_없어도_pause_안함(self):
        """
        PERSIST_MODE=True → 탭을 닫아도 감지기를 일시정지하지 않는다.
        """
        orig = monitoring.PERSIST_MODE
        monitoring.PERSIST_MODE = True
        try:
            # SID 없고 PERSIST_MODE=True → pause 하면 안 됨
            if not monitoring._monitoring_sids and not monitoring.PERSIST_MODE:
                monitoring._pause_all_monitoring()
            assert self.det._paused is False
        finally:
            monitoring.PERSIST_MODE = orig

    def test_monitoring_sids_속성이_존재함(self):
        """monitoring 모듈에 _monitoring_sids set 이 있어야 한다."""
        assert hasattr(monitoring, '_monitoring_sids')
        assert isinstance(monitoring._monitoring_sids, set)
