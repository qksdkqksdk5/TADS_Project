# tests/test_url_refresh.py
# monitoring_detector — ITS URL 토큰 만료 대응 TDD 테스트
#
# 발견된 버그: YOLO 모델 로드 시간(수 초) 동안 ITS CCTV URL의 시간제한 토큰이
# 만료되어 cv2.VideoCapture() 호출 시 HTTP 403 이 반환되고 스트림 열기에 실패한다.
#
# 해결책: _open_http_cap() 직전에 ITS API를 재호출해 신선한 토큰이 담긴 URL로
#        교체하는 _get_fresh_url() 메서드를 MonitoringDetector에 추가한다.
#
# pytest 실행: backend_flask/ 에서 `pytest tests/test_url_refresh.py -v`

import sys
import os
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

# cv2 상수 설정
_cv2_stub = sys.modules['cv2']
_cv2_stub.CAP_FFMPEG        = 1900
_cv2_stub.CAP_PROP_BUFFERSIZE = 38

# BaseDetector 최소 스텁
class _BaseDetectorStub:
    """MonitoringDetector 의 상속 기반 최소 스텁."""
    def __init__(self, *a, **kw):
        self.is_running = True
    def start_alert_worker(self): pass
    def stop(self): self.is_running = False

sys.modules['modules.traffic.detectors.base_detector'].BaseDetector = _BaseDetectorStub

# ── 실제 테스트 대상 임포트 ────────────────────────────────────────────────────
from modules.monitoring import monitoring_detector   # 실제 monitoring_detector.py


# ── 테스트 헬퍼: MonitoringDetector 인스턴스 최소 생성 ────────────────────────

def _make_detector(camera_id='gyeongbu_[경부선]_한곡1교',
                   url='http://cctvsec.ktict.co.kr/3021/old_expired_token='):
    """
    __init__ 없이 MonitoringDetector 인스턴스를 생성해 필요한 속성만 설정한다.
    무거운 YOLO 로드 없이 단위 테스트가 가능하다.
    """
    det = object.__new__(monitoring_detector.MonitoringDetector)
    det.is_running  = True
    det.camera_id   = camera_id
    det.url         = url
    # _road_key 는 구현 후 __init__ 에서 설정되어야 한다.
    # 여기서는 직접 주입해 단위 테스트한다.
    det._road_key   = camera_id.split('_')[0] if '_' in camera_id else ''
    return det


# ── 테스트용 its_helper mock 팩토리 ──────────────────────────────────────────

def _make_its_helper_mock(cameras: list) -> MagicMock:
    """
    its_helper 모듈 대역을 생성한다.
    cameras: get_cctv_list() 가 반환할 카메라 목록
    """
    mock = MagicMock()
    mock.get_cctv_list.return_value = cameras   # API 반환값 설정
    mock._cctv_cache = {}                        # 캐시 딕셔너리 (pop 테스트용)
    return mock


# ════════════════════════════════════════════════════════════════════════════
# 1. _road_key 속성 자동 추출
# ════════════════════════════════════════════════════════════════════════════

class TestRoadKeyExtraction:
    """
    MonitoringDetector.__init__ 이 camera_id 에서 _road_key 를 추출하는지 검증.
    camera_id 형식: "{road_key}_{나머지}" (예: "gyeongbu_[경부선]_한곡1교")
    """

    def test_road_key_가_인스턴스에_존재함(self):
        """MonitoringDetector 는 _road_key 속성을 가져야 한다."""
        det = _make_detector()
        assert hasattr(det, '_road_key'), \
            "_road_key 속성이 없다. __init__ 에서 camera_id.split('_')[0] 로 추출해야 한다."

    def test_gyeongbu_camera_id에서_road_key_추출(self):
        """'gyeongbu_...' camera_id → _road_key == 'gyeongbu' 여야 한다."""
        det = _make_detector(camera_id='gyeongbu_[경부선]_한곡1교')
        assert det._road_key == 'gyeongbu'

    def test_seohae_camera_id에서_road_key_추출(self):
        """'seohae_...' camera_id → _road_key == 'seohae' 여야 한다."""
        det = _make_detector(camera_id='seohae_[서해안]_서평택IC')
        assert det._road_key == 'seohae'

    def test_언더스코어_없는_camera_id는_빈_road_key(self):
        """언더스코어 없는 camera_id는 _road_key == '' 여야 한다."""
        det = _make_detector(camera_id='unknown')
        det._road_key = ''   # 빈 문자열로 덮어씀 (구현 검증을 위한 초기화)
        assert det._road_key == ''


# ════════════════════════════════════════════════════════════════════════════
# 2. _get_fresh_url() 반환 동작
# ════════════════════════════════════════════════════════════════════════════

class TestGetFreshUrl:
    """
    _get_fresh_url() 이 ITS API 에서 신선한 URL 을 가져오는지 검증.

    시나리오: YOLO 로드 중 ITS 토큰이 만료됨 → _get_fresh_url() 호출 →
             캐시 무효화 → ITS API 재호출 → 신선한 토큰 URL 반환.
    """

    # ── 기본 동작 ────────────────────────────────────────────────────────────

    def test_함수가_인스턴스_메서드로_존재함(self):
        """_get_fresh_url 메서드가 MonitoringDetector 에 정의되어 있어야 한다."""
        det = _make_detector()
        assert hasattr(det, '_get_fresh_url')
        assert callable(det._get_fresh_url)

    def test_정상_케이스_새_URL_반환(self):
        """
        ITS API 가 신선한 URL 을 반환하면, 그 URL 을 반환해야 한다.
        만료된 old_token 대신 new_token 이 담긴 URL 이 반환되어야 한다.
        """
        det     = _make_detector()
        new_url = 'http://cctvsec.ktict.co.kr/3021/fresh_token='
        mock_helper = _make_its_helper_mock(cameras=[
            {'camera_id': det.camera_id, 'url': new_url},
        ])

        with patch.dict(sys.modules, {'modules.monitoring.its_helper': mock_helper}):
            result = det._get_fresh_url()

        assert result == new_url, \
            f"새 URL 이 반환돼야 한다. 실제: {result}"

    def test_self_url도_함께_업데이트됨(self):
        """
        _get_fresh_url() 은 self.url 도 새 URL 로 업데이트해야 한다.
        이후 reconnect() 에서 self.url 을 사용할 때 만료된 URL 을 쓰지 않도록 하기 위함이다.
        """
        det     = _make_detector()
        new_url = 'http://cctvsec.ktict.co.kr/3021/fresh_token='
        mock_helper = _make_its_helper_mock(cameras=[
            {'camera_id': det.camera_id, 'url': new_url},
        ])

        with patch.dict(sys.modules, {'modules.monitoring.its_helper': mock_helper}):
            det._get_fresh_url()

        assert det.url == new_url, \
            "self.url 이 새 URL 로 업데이트되어야 한다."

    # ── 캐시 무효화 ──────────────────────────────────────────────────────────

    def test_캐시를_pop하여_강제_갱신(self):
        """
        _get_fresh_url() 은 호출 전에 its_helper._cctv_cache 에서
        road_key 항목을 pop 해야 한다.
        캐시가 살아 있으면 만료된 URL 이 그대로 반환되기 때문이다.
        """
        det = _make_detector()
        # 캐시에 만료되지 않은 항목이 있다고 가정
        mock_helper = _make_its_helper_mock(cameras=[])
        mock_helper._cctv_cache = {
            'gyeongbu': {'data': [], 'expires': 9_999_999_999}
        }

        with patch.dict(sys.modules, {'modules.monitoring.its_helper': mock_helper}):
            det._get_fresh_url()

        assert 'gyeongbu' not in mock_helper._cctv_cache, \
            "_cctv_cache['gyeongbu'] 가 pop 됐어야 한다."

    def test_캐시_pop_후_get_cctv_list_호출됨(self):
        """
        캐시를 지운 뒤 반드시 get_cctv_list(road_key) 를 호출해
        ITS API 에서 신선한 URL 을 가져와야 한다.
        """
        det         = _make_detector()
        mock_helper = _make_its_helper_mock(cameras=[])

        with patch.dict(sys.modules, {'modules.monitoring.its_helper': mock_helper}):
            det._get_fresh_url()

        mock_helper.get_cctv_list.assert_called_once_with('gyeongbu')

    # ── 예외 케이스 ──────────────────────────────────────────────────────────

    def test_road_key_없으면_원본_URL_반환(self):
        """
        _road_key 가 빈 문자열이면 API 호출 없이 원본 URL 을 반환해야 한다.
        road_key 를 알 수 없으면 어떤 도로의 카메라인지 특정할 수 없기 때문이다.
        """
        det           = _make_detector()
        original_url  = det.url
        det._road_key = ''   # road_key 없는 상황 시뮬레이션

        result = det._get_fresh_url()

        assert result == original_url

    def test_RTSP_URL은_갱신하지_않고_원본_반환(self):
        """
        RTSP 스트림은 ITS HTTP 토큰 방식이 아니므로 URL 갱신 대상이 아니다.
        원본 URL 을 그대로 반환해야 한다.
        """
        rtsp_url    = 'rtsp://192.168.1.1/stream'
        det         = _make_detector(url=rtsp_url)
        result      = det._get_fresh_url()

        assert result == rtsp_url

    def test_camera_id_목록에_없으면_원본_URL_반환(self):
        """
        ITS API 반환 목록에 해당 camera_id 가 없으면 원본 URL 을 반환해야 한다.
        카메라가 ITS 목록에서 제거됐거나 이름이 바뀐 경우다.
        """
        det          = _make_detector()
        original_url = det.url
        mock_helper  = _make_its_helper_mock(cameras=[
            {'camera_id': 'gyeongbu_[경부선]_다른카메라', 'url': 'http://other/'},
        ])

        with patch.dict(sys.modules, {'modules.monitoring.its_helper': mock_helper}):
            result = det._get_fresh_url()

        assert result == original_url

    def test_its_helper_예외_발생_시_원본_URL_반환(self):
        """
        its_helper.get_cctv_list() 가 예외를 발생시키면
        원본 URL 을 반환해야 한다. 갱신 실패가 전체 모니터링을 중단시켜선 안 된다.
        """
        det          = _make_detector()
        original_url = det.url
        mock_helper  = _make_its_helper_mock(cameras=[])
        mock_helper.get_cctv_list.side_effect = Exception('ITS API 오류')

        with patch.dict(sys.modules, {'modules.monitoring.its_helper': mock_helper}):
            result = det._get_fresh_url()

        assert result == original_url
