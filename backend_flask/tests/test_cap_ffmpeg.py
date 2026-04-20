# tests/test_cap_ffmpeg.py
# monitoring_detector — CAP_FFMPEG 강제 지정 및 전역 잠금 TDD 테스트
#
# 발견된 버그: cv2.VideoCapture(url) (백엔드 자동 선택) 는 여러 스레드에서
# 동시에 호출될 때 FFMPEG가 선택되지 않고 MSMF/CAP_IMAGES 등 엉뚱한 백엔드로
# fallback되어 HTTP(ITS HLS) URL 열기에 실패한다.
#
# 해결책: cv2.VideoCapture(url, cv2.CAP_FFMPEG) 로 FFMPEG 명시 + 전역 잠금 직렬화.
#
# pytest 실행: backend_flask/ 에서 `pytest tests/test_cap_ffmpeg.py -v`

import sys
import os
import threading
from unittest.mock import MagicMock, patch

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, _BACKEND_DIR)


# ── 무거운 외부 의존성 스텁 ─────────────────────────────────────────────────────

def _stub(name):
    """빈 MagicMock 모듈을 sys.modules에 등록해 ImportError를 방지한다."""
    mod = MagicMock()
    mod.__name__ = name
    sys.modules.setdefault(name, mod)
    return mod


for _s in [
    'cv2', 'numpy',
    'torch', 'ultralytics',
    'gevent', 'gevent.threadpool',
    'flask', 'flask_socketio',
    'models',
    'modules.traffic.detectors.base_detector',
    'detector_modules',
    'detector_modules.config', 'detector_modules.state',
    'detector_modules.flow_map', 'detector_modules.tracker',
    'detector_modules.judge', 'detector_modules.id_manager',
    'detector_modules.camera_switch', 'detector_modules.traffic_analyzer',
    'detector_modules.gru_module', 'detector_modules.congestion_judge',
]:
    _stub(_s)

# gevent.sleep 은 no-op 으로 대체 (테스트 중 실제 대기 방지)
sys.modules['gevent'].sleep = lambda *a, **kw: None

# gevent.threadpool.ThreadPool mock 설정 (maxsize 인자 허용)
sys.modules['gevent.threadpool'].ThreadPool = MagicMock(return_value=MagicMock())

# cv2 상수: 실제 값을 설정해야 assert_called_with 비교가 가능하다
_cv2_stub = sys.modules['cv2']
_cv2_stub.CAP_FFMPEG        = 1900   # cv2.CAP_FFMPEG 실제 값
_cv2_stub.CAP_PROP_BUFFERSIZE = 38   # cv2.CAP_PROP_BUFFERSIZE 실제 값

# BaseDetector 최소 스텁
class _BaseDetectorStub:
    """monitoring_detector.MonitoringDetector 의 상속 기반 최소 스텁."""
    def __init__(self, *a, **kw):
        self.is_running = True
    def start_alert_worker(self): pass
    def stop(self): self.is_running = False

sys.modules['modules.traffic.detectors.base_detector'].BaseDetector = _BaseDetectorStub

# ── 실제 테스트 대상 임포트 ────────────────────────────────────────────────────
from modules.monitoring import monitoring_detector   # 실제 monitoring_detector.py


# ════════════════════════════════════════════════════════════════════════════
# 1. _CAP_OPEN_LOCK 전역 잠금 존재 여부
# ════════════════════════════════════════════════════════════════════════════

class TestCapOpenLock:
    """_CAP_OPEN_LOCK 전역 잠금이 모듈에 존재하고 정상 동작하는지 검증."""

    def test_잠금_속성이_모듈에_존재함(self):
        """모듈에 _CAP_OPEN_LOCK 속성이 있어야 한다."""
        assert hasattr(monitoring_detector, '_CAP_OPEN_LOCK')

    def test_잠금이_acquire_release_인터페이스를_가짐(self):
        """_CAP_OPEN_LOCK은 acquire / release 메서드를 가져야 한다."""
        lock = monitoring_detector._CAP_OPEN_LOCK
        assert hasattr(lock, 'acquire')
        assert hasattr(lock, 'release')

    def test_잠금을_컨텍스트_매니저로_사용_가능(self):
        """_CAP_OPEN_LOCK 을 with 문으로 사용할 때 예외가 발생하지 않아야 한다."""
        with monitoring_detector._CAP_OPEN_LOCK:
            pass   # 정상 통과 확인


# ════════════════════════════════════════════════════════════════════════════
# 2. _open_http_cap() 함수 동작
# ════════════════════════════════════════════════════════════════════════════

class TestOpenHttpCap:
    """_open_http_cap() 이 백엔드 자동 선택 + 잠금 획득으로 VideoCapture를 여는지 검증."""

    def setup_method(self):
        """각 테스트 전 cv2.VideoCapture mock 초기화."""
        _cv2_stub.VideoCapture.reset_mock()
        _cv2_stub.VideoCapture.side_effect = None

        self._mock_cap = MagicMock()
        self._mock_cap.isOpened.return_value = True
        _cv2_stub.VideoCapture.return_value = self._mock_cap

    def test_함수가_모듈에_존재함(self):
        """_open_http_cap 함수가 모듈 수준에 정의되어 있어야 한다."""
        assert hasattr(monitoring_detector, '_open_http_cap')
        assert callable(monitoring_detector._open_http_cap)

    def test_백엔드_명시_없이_VideoCapture_호출됨(self):
        """
        _open_http_cap()은 cv2.VideoCapture(url) 형태로 호출해야 한다.
        (백엔드 인자를 넘기지 않는다.)

        이유: ITS 서버는 FFMPEG 백엔드의 User-Agent("Lavf/xx.xx.xx")를 거부해 HTTP 403을
        반환한다. cv2.VideoCapture(url, cv2.CAP_FFMPEG) 로 강제 지정하면 ITS 서버가 항상
        403을 돌려보내 스트림 열기에 실패한다.

        백엔드를 명시하지 않으면 Windows에서 OpenCV가 MSMF(Windows Media Foundation)를
        선택한다. MSMF는 Windows 표준 HTTP 스택을 사용하므로 ITS 서버가 정상 허용한다.
        (view_feed 엔드포인트가 cv2.VideoCapture(url)로 정상 동작하는 것과 같은 원리)

        _CAP_OPEN_LOCK 잠금은 여전히 유지한다.
        여러 스레드가 cv2.VideoCapture()를 동시에 호출할 때 백엔드 플러그인 초기화
        경쟁 상태가 발생하는 것을 방지하기 위함이다.
        """
        monitoring_detector._open_http_cap('http://cctvsec.ktict.co.kr/test')

        _cv2_stub.VideoCapture.assert_called_once_with(
            'http://cctvsec.ktict.co.kr/test',
            # CAP_FFMPEG 인자 없음 — ITS 서버 User-Agent 거부 우회
        )

    def test_버퍼_크기를_1로_설정(self):
        """
        _open_http_cap()은 cap.set(CAP_PROP_BUFFERSIZE, 1)을 호출해야 한다.
        버퍼를 최소화해 실시간 스트림 지연을 줄이기 위함이다.
        """
        monitoring_detector._open_http_cap('http://cctvsec.ktict.co.kr/test')

        self._mock_cap.set.assert_called_with(38, 1)  # 38 = CAP_PROP_BUFFERSIZE

    def test_cap_객체를_반환함(self):
        """_open_http_cap()은 VideoCapture 인스턴스를 반환해야 한다."""
        cap = monitoring_detector._open_http_cap('http://cctvsec.ktict.co.kr/test')
        assert cap is self._mock_cap

    def test_VideoCapture_호출_시_잠금이_획득돼_있음(self):
        """
        _open_http_cap() 이 VideoCapture를 여는 순간 _CAP_OPEN_LOCK이
        이미 획득된 상태여야 한다. 잠금이 없으면 다른 스레드가 동시에
        VideoCapture를 열어 FFMPEG 전역 초기화 경쟁 상태가 발생한다.
        """
        lock = monitoring_detector._CAP_OPEN_LOCK
        lock_held_during_open = []

        def _side_effect(url):
            """VideoCapture 호출 시점에 잠금 보유 여부를 기록한다."""
            # blocking=False 로 잠금 재획득 시도 → 이미 획득됐으면 False 반환
            acquired = lock.acquire(blocking=False)
            if acquired:
                lock.release()           # 잘못 획득했으면 즉시 해제
                lock_held_during_open.append(False)
            else:
                lock_held_during_open.append(True)   # 올바르게 선점됨
            return self._mock_cap

        _cv2_stub.VideoCapture.side_effect = _side_effect
        monitoring_detector._open_http_cap('http://cctvsec.ktict.co.kr/test')
        _cv2_stub.VideoCapture.side_effect = None

        assert lock_held_during_open == [True], \
            "VideoCapture 호출 시 _CAP_OPEN_LOCK이 획득돼 있어야 한다"
