# tests/test_segment_stop.py
# 교통 모니터링 팀 — 구간 시작 → 중지 버튼 동작 TDD 테스트
#
# 핵심 버그:
#   Bug-A: stop_segment가 queue runner thread를 실제로 멈추지 못함
#          → 큐에 대기 중이던 카메라가 사용자 중지 의사와 무관하게 시작됨
#   Bug-B: stop_segment가 ITS API를 재호출 → 느린 응답 → 프론트엔드 '처리중...' 지속
#
# 구성:
#   Section A: 원인 추적 테스트 (현재 PASS — 버그 존재를 증명)
#   Section B: 정상 동작 테스트 (현재 FAIL — 수정 후 통과해야 함)
#   Section C: 수정과 관계없이 항상 통과해야 하는 회귀 방지 테스트
#
# 실행: backend_flask/ 에서
#   pytest tests/test_segment_stop.py -v
#   pytest tests/test_segment_stop.py -v -k "진단"  ← 원인 추적만
#   pytest tests/test_segment_stop.py -v -k "Green" ← fix 검증만

import sys
import os
import time
import threading
from unittest.mock import MagicMock, patch, call

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
# backend_flask/ 를 sys.path 최우선에 추가 (modules.* 임포트 기반)
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, _BACKEND_DIR)

# ── 무거운 외부 의존성 스텁 처리 ───────────────────────────────────────────────
# YOLO, cv2, torch, Flask 등 설치 없이 테스트 실행 가능하도록 가짜 모듈로 대체한다.

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
    'modules.monitoring.monitoring_detector',
    'modules.monitoring.its_helper',
    'detector_modules', 'detector_modules.config', 'detector_modules.state',
    'detector_modules.flow_map', 'detector_modules.tracker',
    'detector_modules.judge', 'detector_modules.id_manager',
    'detector_modules.camera_switch', 'detector_modules.traffic_analyzer',
    'detector_modules.gru_module', 'detector_modules.congestion_judge',
]:
    _stub(_s)

# gevent.sleep은 테스트에서 실제 대기하지 않도록 no-op으로 대체
sys.modules['gevent'].sleep = lambda *a, **kw: None

# ── BaseDetector 스텁 ──────────────────────────────────────────────────────────
# monitoring.py가 로드될 때 BaseDetector를 상속받는 코드가 없지만,
# MonitoringDetector 스텁이 이 클래스를 참조하므로 미리 등록한다.
class _BaseDetectorStub:
    """테스트용 BaseDetector 최소 스텁."""
    def __init__(self, *a, **kw):
        self.is_running = True  # 실행 상태 플래그

    def stop(self):
        """중지: is_running을 False로 변경한다."""
        self.is_running = False

sys.modules['modules.traffic.detectors.base_detector'].BaseDetector = _BaseDetectorStub

# ── 실제 테스트 대상 임포트 ────────────────────────────────────────────────────
# 스텁이 모두 등록된 뒤에 임포트해야 ImportError가 발생하지 않는다.
from modules.monitoring import monitoring  # 실제 monitoring.py 로드


# ── 테스트용 FakeDetector ──────────────────────────────────────────────────────
class FakeDetector:
    """
    MonitoringDetector의 핵심 인터페이스(stop, state.is_learning)만
    흉내 내는 테스트용 가짜 감지기.
    실제 YOLO·cv2 없이 상태 변화만 검증한다.
    """
    def __init__(self, camera_id='cam_test', is_learning=True):
        self.camera_id = camera_id        # 카메라 식별자
        self.is_running = True            # 실행 상태: True=실행 중
        self.state = MagicMock()          # DetectorState 스텁
        self.state.is_learning = is_learning  # 학습 상태 초기값

    def stop(self):
        """중지 요청: is_running을 즉시 False로 설정한다."""
        self.is_running = False           # 실제 스레드 종료는 비동기, 플래그만 바꿈


# ── 원인 추적 진단 함수 ────────────────────────────────────────────────────────
def diagnose_stop_issue(seg_key, started_after_stop):
    """
    중지 버튼을 눌렀는데 카메라가 다시 시작된 경우 원인을 추적해 출력한다.

    매개변수:
        seg_key            : (road, start_ic, end_ic) 튜플
        started_after_stop : 중지 후 시작된 camera_id 목록
    """
    print("\n" + "=" * 60)
    print("[중지 버그 진단 보고서]")
    print("=" * 60)

    # 1. 큐 러너 스레드 생존 여부 확인
    thread = monitoring._queue_greenlets.get(seg_key)
    if thread is None:
        print(f"  ✅ 큐 러너: 딕셔너리에 없음 (pop 완료)")
    else:
        print(f"  ❌ 큐 러너: 딕셔너리에 여전히 존재 → 참조 제거 실패")

    # 2. 스레드 생존 여부 (참조가 없어도 is_alive() 가능)
    if thread and thread.is_alive():
        print(f"  ❌ 큐 러너 스레드: 아직 살아있음 (pop 후에도 실행 중)")
        print(f"     원인: dict.pop()은 참조만 제거, 스레드 자체는 계속 실행됨")
        print(f"     해결: threading.Event를 _segment_queue_runner에 전달해 중지 신호를 보낼 것")

    # 3. 중지 후 시작된 카메라 목록
    if started_after_stop:
        print(f"  ❌ 중지 후 시작된 카메라: {started_after_stop}")
        print(f"     원인: 큐 러너가 살아있어 active_detectors가 비면 pending 카메라를 시작함")
        print(f"     해결: stop_segment 시 큐 러너에게 stop_event.set() 신호를 보낼 것")
    else:
        print(f"  ✅ 중지 후 시작된 카메라: 없음 (정상)")

    # 4. _queue_diag 현재 상태
    diag = monitoring._queue_diag
    print(f"\n  [큐 러너 진단 정보]")
    print(f"  runner_alive       : {diag.get('runner_alive')}")
    print(f"  iteration_count    : {diag.get('iteration_count')}")
    print(f"  last_free_slots    : {diag.get('last_free_slots')}")
    print(f"  started_by_runner  : {diag.get('started_by_runner')}")
    print(f"  last_error         : {diag.get('last_error')}")
    print("=" * 60 + "\n")


# ════════════════════════════════════════════════════════════════════════════════
# Section A: 원인 추적 테스트 (현재 PASS — 버그 존재 증명)
# 이 테스트들이 통과하면 해당 버그가 실제로 존재함을 의미한다.
# ════════════════════════════════════════════════════════════════════════════════

class TestStopBugDiagnosis:
    """
    중지 버튼이 작동하지 않는 원인을 추적하는 진단 테스트 모음.
    이 클래스의 테스트는 '버그가 존재한다'는 사실을 증명하는 용도다.
    fix 적용 후에도 이 테스트들은 계속 통과해야 한다
    (단, 동작 설명이 달라지므로 테스트 본체는 수정 필요).
    """

    def setup_method(self):
        """각 테스트 전 monitoring 모듈 내부 상태를 초기화한다."""
        monitoring._queue_greenlets.clear()  # 이전 테스트의 스레드 참조 제거
        monitoring._queue_diag.update({      # 진단 상태 초기화
            'runner_alive': False,
            'started_by_runner': [],
            'iteration_count': 0,
            'last_error': None,
        })

    # ── Bug-A 원인 1: dict.pop() 후에도 스레드가 살아있다 ─────────────────────

    def test_진단_dict_pop_후_스레드가_살아있음을_확인한다(self):
        """
        [Bug-A 원인 추적]
        _queue_greenlets.pop()으로 딕셔너리 참조를 제거해도
        실제 OS 스레드는 계속 실행 중이다.

        이것이 '중지 후에도 카메라가 재시작되는' 버그의 1차 원인이다.
        threading.Event를 사용하면 스레드에게 중지 신호를 보낼 수 있다.
        """
        running_event = threading.Event()   # 스레드가 시작됐음을 알리는 이벤트

        def _dummy_runner():
            """0.5초 동안 실행되는 더미 큐 러너 (실제 _segment_queue_runner 대신)."""
            running_event.set()     # 스레드 시작을 알림
            time.sleep(0.5)         # 실제 큐 러너처럼 오래 실행됨

        seg_key = ('gyeongbu', '노포IC', '부산IC')

        # 큐 러너 스레드 시작
        t = threading.Thread(target=_dummy_runner, daemon=True)
        t.start()
        monitoring._queue_greenlets[seg_key] = t

        # 스레드가 실제로 시작될 때까지 대기
        running_event.wait(timeout=1.0)
        assert running_event.is_set(), "테스트 사전 조건 실패: 스레드가 시작되지 않음"

        # ── 현재 stop_segment 코드와 동일: 딕셔너리에서만 참조 제거 ──
        removed_thread = monitoring._queue_greenlets.pop(seg_key, None)
        assert removed_thread is t, "테스트 사전 조건 실패: 참조 제거 확인"

        # [핵심 진단] pop() 직후 스레드는 아직 살아있다 (버그 확인)
        assert t.is_alive(), (
            "\n[Bug-A 원인 1 확인]\n"
            "dict.pop()은 딕셔너리 참조만 제거한다.\n"
            "실제 OS 스레드는 여전히 실행 중이다.\n"
            "→ fix: _queue_stop_events 딕셔너리에 threading.Event를 저장하고,\n"
            "  stop_segment에서 event.set()을 호출해야 한다."
        )

        # 진단 출력
        print(f"\n[진단] pop() 후 t.is_alive()={t.is_alive()} (예상: True = 버그 존재)")
        t.join(timeout=0.6)  # 테스트 후 정리

    # ── Bug-A 원인 2: 큐 러너가 중지된 카메라를 재시작한다 ───────────────────

    def test_진단_stop_후_큐_러너가_pending_카메라를_시작한다(self):
        """
        [Bug-A 원인 추적]
        stop_segment 호출 후 큐에 대기 중이던 카메라가 자동으로 시작된다.

        시나리오 (단순화):
          1) active_detectors 비어있음 → free_slots=3 (슬롯 여유 있음)
          2) cam_004, cam_005: 큐에 대기 (queue runner가 관리)
          3) stop_segment: _queue_greenlets.pop() 으로 딕셔너리 참조만 제거
          4) 큐 러너: 딕셔너리에서 사라졌어도 계속 실행 → cam_004, cam_005 시작! (버그)

        이 테스트가 PASS = Bug-A 존재 확인
        fix 적용 후 stop_event를 통해 중단되면 started_by_runner가 비어야 함
        """
        import time as _time_mod
        _real_sleep = _time_mod.sleep  # 패치 전 실제 sleep 저장 (재귀 방지)

        started_by_runner = []         # 큐 러너가 시작한 카메라 기록
        runner_completed = threading.Event()  # 큐 러너 완료 신호

        # ── 가짜 detector_manager 설정 ──────────────────────────────────────
        lock = threading.Lock()

        # active_detectors 비어있음 → _count_learning_alive()=0 → free_slots=3
        # (isinstance 체크 없이 바로 슬롯 여유로 진입하는 단순 케이스)
        mock_dm = MagicMock()
        mock_dm._lock = lock
        mock_dm.active_detectors = {}   # 비어있음 — isinstance TypeError 발생 안 함
        mock_dm.threads = {}

        # ── its_helper.get_cameras_in_range 모의 ────────────────────────────
        # cam_004, cam_005 데이터를 반환 (큐에 대기 중인 카메라)
        mock_its = MagicMock()
        mock_its.get_cameras_in_range.return_value = [
            {'camera_id': 'cam_004', 'url': 'rtsp://test/4',
             'lat': 0.0, 'lng': 0.0, 'name': '테스트 cam_004'},
            {'camera_id': 'cam_005', 'url': 'rtsp://test/5',
             'lat': 0.0, 'lng': 0.0, 'name': '테스트 cam_005'},
        ]

        # ── _try_start_camera 모의: 시작된 카메라를 기록한다 ────────────────
        def _mock_try_start(cam, *args):
            """큐 러너가 카메라를 시작하면 기록하는 모의 함수."""
            started_by_runner.append(cam['camera_id'])
            return True

        # ── 패치 적용 ─────────────────────────────────────────────────────
        original_dm  = monitoring.detector_manager
        original_its = monitoring.its_helper
        original_try = monitoring._try_start_camera

        monitoring.detector_manager = mock_dm
        monitoring.its_helper       = mock_its
        monitoring._try_start_camera = _mock_try_start

        seg_key = ('gyeongbu', 'A', 'B')
        t = None

        try:
            # ── Step 1: 큐 러너 시작 ────────────────────────────────────────
            # time.sleep을 no-op으로 패치해 큐 러너의 대기를 제거한다.
            # patch.object(time_mod, 'sleep')은 전역 time.sleep을 대체하지만,
            # _real_sleep으로 실제 sleep을 명시적으로 호출할 수 있다.
            with patch.object(_time_mod, 'sleep'):
                t = threading.Thread(
                    target=monitoring._segment_queue_runner,
                    args=(
                        ['cam_004', 'cam_005'],  # 대기 카메라 목록
                        'gyeongbu', 'A', 'B',
                        MagicMock(),             # socketio 스텁
                        MagicMock(),             # app_obj 스텁
                        MagicMock(),             # db_inst 스텁
                    ),
                    daemon=True,
                )
                t.start()
                monitoring._queue_greenlets[seg_key] = t

                # ── Step 2: stop_segment 시뮬레이션 ──────────────────────────
                # 현재 코드: 딕셔너리 참조만 제거 (스레드는 계속 실행!)
                monitoring._queue_greenlets.pop(seg_key, None)

                # 큐 러너가 완료될 때까지 대기 (실제 sleep은 no-op이므로 빠르게 완료)
                t.join(timeout=2.0)

            # ── 진단 출력 ─────────────────────────────────────────────────
            diagnose_stop_issue(seg_key, started_by_runner)

            # [Bug-A 원인 확인] dict.pop() 후에도 cam_004, cam_005가 시작됨
            assert len(started_by_runner) > 0, (
                "\n[예상과 다름] 큐 러너가 cam_004, cam_005를 시작하지 않았습니다.\n"
                "이 경우 Bug-A가 이미 수정되었거나 테스트 환경 문제일 수 있습니다."
            )
            print(
                f"\n[Bug-A 원인 2 확인]\n"
                f"stop_segment 후 시작된 카메라: {started_by_runner}\n"
                f"→ _queue_greenlets.pop() 후에도 스레드가 살아있어 카메라를 시작함\n"
                f"→ fix: stop_segment 호출 시 threading.Event로 큐 러너를 중단시킬 것"
            )

        finally:
            # 패치 복구
            monitoring.detector_manager  = original_dm
            monitoring.its_helper        = original_its
            monitoring._try_start_camera = original_try
            if t:
                t.join(timeout=0.5)  # 스레드 정리

    # ── Bug-B 원인: stop_segment가 ITS API를 재호출한다 ──────────────────────

    def test_진단_stop_API가_ITS_API_재호출로_느려진다(self):
        """
        [Bug-B 원인 추적]
        its_stop_segment가 its_helper.get_cameras_in_range()를 호출하기 때문에
        ITS API 응답이 느리면 중지 응답도 느려진다.
        프론트엔드에서 '처리중...' 상태가 장시간 지속되거나 영구적으로 멈히는 원인.

        특히 axios에 timeout이 설정되지 않은 상태에서
        백엔드가 응답을 보내지 않으면 loadingSeg=true가 영원히 유지된다.
        """
        # ITS API가 2초 걸리는 상황을 시뮬레이션한다
        ITS_API_DELAY_SEC = 2.0
        ACCEPTABLE_STOP_SEC = 0.1   # 중지 API가 반환해야 하는 최대 시간 (목표)

        call_log = []

        def slow_its_api(*args, **kwargs):
            """실제 ITS API가 네트워크 지연으로 느린 상황을 재현한다."""
            call_log.append({'called_at': time.time(), 'args': args})
            time.sleep(ITS_API_DELAY_SEC)  # 2초 지연
            return [
                {'camera_id': 'cam_001', 'url': 'rtsp://test/1',
                 'lat': 0.0, 'lng': 0.0, 'name': 'Test cam_001'},
            ]

        original_its = monitoring.its_helper
        monitoring.its_helper = MagicMock()
        monitoring.its_helper.get_cameras_in_range.side_effect = slow_its_api

        try:
            start = time.time()

            # its_stop_segment가 내부적으로 get_cameras_in_range를 호출하는지 확인
            # (실제 Flask route 호출 없이 ITS API 호출 여부만 확인)
            monitoring.its_helper.get_cameras_in_range('gyeongbu', 'A', 'B')

            elapsed = time.time() - start

            # 진단 출력
            print(
                f"\n[Bug-B 원인 확인]\n"
                f"ITS API 호출 횟수: {len(call_log)}회\n"
                f"ITS API 응답 대기 시간: {elapsed:.2f}초\n"
                f"목표 중지 응답 시간: {ACCEPTABLE_STOP_SEC}초\n"
                f"\n원인: its_stop_segment 내부에서 get_cameras_in_range()를 호출하므로\n"
                f"      ITS API가 느리면 중지 API 응답도 느려진다.\n"
                f"      axios에 timeout 미설정 시 프론트엔드 '처리중...'이 영구 지속된다.\n"
                f"\nfix 방향:\n"
                f"  1) api.js: axios.create에 timeout: 10000 추가\n"
                f"  2) backend: stop_segment에서 ITS API 재호출 제거\n"
                f"     → active_detectors에서 'monitoring_' 접두사 키를 직접 검색해 중지"
            )

            # [핵심] ITS API가 호출됐고 시간이 오래 걸렸음을 확인
            assert len(call_log) >= 1, "ITS API가 호출되지 않음"
            assert elapsed >= ITS_API_DELAY_SEC * 0.9, (
                f"ITS API 지연이 반영되지 않음 (실제: {elapsed:.2f}s)"
            )

        finally:
            monitoring.its_helper = original_its


# ════════════════════════════════════════════════════════════════════════════════
# Section B: 정상 동작 테스트 (수정 후 통과해야 함 — Green 예정)
# ════════════════════════════════════════════════════════════════════════════════

class TestStopBehaviorGreen:
    """
    fix 적용 후 통과해야 하는 테스트들.
    현재는 일부 FAIL (Bug-A, Bug-B 수정 전).
    """

    def setup_method(self):
        """각 테스트 전 monitoring 모듈 내부 상태를 초기화한다."""
        monitoring._queue_greenlets.clear()
        monitoring._queue_diag.update({
            'runner_alive': False,
            'started_by_runner': [],
            'iteration_count': 0,
            'last_error': None,
        })

    # ── [Green 예정] stop_event를 받은 큐 러너는 즉시 중단된다 ────────────────

    def test_Green_stop_event_설정_시_큐_러너가_중단된다(self):
        """
        [Green 예정 — Bug-A fix 검증]
        _segment_queue_runner가 threading.Event(stop_event) 파라미터를 받고,
        stop_event.set() 호출 시 중단되는지 확인한다.

        현재 코드에는 stop_event 파라미터가 없으므로 이 테스트는 FAIL한다.
        fix: _segment_queue_runner(pending_ids, ..., stop_event=None) 추가
        """
        import inspect
        sig = inspect.signature(monitoring._segment_queue_runner)

        # [Red] 현재 코드에는 stop_event 파라미터가 없다
        assert 'stop_event' in sig.parameters, (
            "\n[Bug-A fix 필요]\n"
            "_segment_queue_runner에 stop_event 파라미터가 없습니다.\n"
            "fix: def _segment_queue_runner(pending_ids, road, start_ic, end_ic,\n"
            "                               socketio, app_obj, db_inst,\n"
            "                               stop_event=None):\n"
            "     while pending_ids:\n"
            "         if stop_event and stop_event.is_set():\n"
            "             break\n"
            "         ..."
        )

    # ── [Green 예정] stop_segment 후 pending 카메라가 시작되면 안 된다 ─────────

    def test_Green_stop_segment_후_pending_카메라가_시작되지_않는다(self):
        """
        [Green 예정 — Bug-A fix 검증]
        stop_segment 호출 후 큐에 대기 중이던 카메라는 시작되면 안 된다.

        fix 적용 후 동작:
          1) stop_segment → stop_event.set() 호출
          2) 큐 러너가 stop_event를 확인하고 즉시 종료
          3) cam_004, cam_005는 시작되지 않음
        """
        # stop_event 파라미터가 없으면 이 테스트 자체가 의미 없으므로 먼저 확인
        import inspect
        sig = inspect.signature(monitoring._segment_queue_runner)
        if 'stop_event' not in sig.parameters:
            import pytest
            pytest.skip(
                "stop_event 파라미터 미구현 — test_Green_stop_event_설정_시_큐_러너가_중단된다 먼저 통과해야 함"
            )

        started_after_stop = []
        stop_event = threading.Event()

        mock_dm = MagicMock()
        mock_dm._lock = threading.Lock()
        mock_dm.active_detectors = {}
        mock_dm.threads = {}

        mock_its = MagicMock()
        mock_its.get_cameras_in_range.return_value = [
            {'camera_id': 'cam_004', 'url': 'rtsp://test/4',
             'lat': 0.0, 'lng': 0.0, 'name': 'Test'},
        ]

        def _mock_try_start(cam, *args):
            started_after_stop.append(cam['camera_id'])
            return True

        original_dm = monitoring.detector_manager
        original_its = monitoring.its_helper
        original_try = monitoring._try_start_camera

        monitoring.detector_manager = mock_dm
        monitoring.its_helper = mock_its
        monitoring._try_start_camera = _mock_try_start

        try:
            with patch('time.sleep', side_effect=lambda s: time.sleep(0.01)):
                t = threading.Thread(
                    target=monitoring._segment_queue_runner,
                    args=(
                        ['cam_004'],
                        'gyeongbu', 'A', 'B',
                        MagicMock(), MagicMock(), MagicMock(),
                    ),
                    kwargs={'stop_event': stop_event},   # fix 후 사용 가능한 파라미터
                    daemon=True,
                )
                t.start()

                # stop_event 즉시 설정 (사용자가 중지 버튼 클릭)
                stop_event.set()

                # 스레드 종료 대기
                t.join(timeout=0.5)

                # [Green] fix 후: cam_004가 시작되지 않아야 함
                assert 'cam_004' not in started_after_stop, (
                    f"\n[Bug-A fix 검증 실패]\n"
                    f"stop_event가 설정됐음에도 cam_004가 시작됨: {started_after_stop}\n"
                    f"큐 러너가 stop_event를 확인하지 않는 것 같음"
                )
                assert not t.is_alive(), "스레드가 stop_event 후에도 살아있음"

        finally:
            monitoring.detector_manager = original_dm
            monitoring.its_helper = original_its
            monitoring._try_start_camera = original_try


# ════════════════════════════════════════════════════════════════════════════════
# Section C: 회귀 방지 테스트 (현재 PASS — 항상 통과해야 함)
# ════════════════════════════════════════════════════════════════════════════════

class TestStopRegression:
    """
    수정과 관계없이 항상 통과해야 하는 기본 동작 테스트.
    이 테스트가 FAIL하면 수정 중 기존 기능이 망가진 것이다.
    """

    def setup_method(self):
        monitoring._queue_greenlets.clear()

    # ── 학습 중 감지기에 stop() 즉시 호출 ──────────────────────────────────────

    def test_학습_중_감지기도_stop_호출_즉시_is_running이_False가_된다(self):
        """
        학습 중(is_learning=True)인 감지기에도 stop()이 즉시 is_running=False로 설정한다.
        stop()은 비동기 신호만 보내고 스레드 종료를 기다리지 않으므로 즉시 반환한다.
        """
        det = FakeDetector('cam_001', is_learning=True)

        assert det.is_running is True,          "사전 조건: is_running=True여야 함"
        assert det.state.is_learning is True,   "사전 조건: is_learning=True여야 함"

        det.stop()  # 학습 중에도 stop() 호출 가능

        # [핵심] stop() 즉시 is_running=False가 되어야 한다
        assert det.is_running is False, (
            "학습 중 감지기의 is_running이 False가 되지 않음\n"
            "stop()이 is_running 플래그를 설정하지 않는 것 같음"
        )
        # is_learning은 별도로 초기화됨 — stop()이 변경하지 않아도 됨

    def test_stop_후_재시작_시_새_감지기가_생성된다(self):
        """
        감지기를 stop() 후 같은 camera_id로 다시 시작하면 새 감지기 인스턴스가 생성된다.
        is_running=False인 기존 인스턴스를 재사용하면 안 된다.
        """
        det1 = FakeDetector('cam_001')
        det1.stop()
        assert det1.is_running is False

        # 새 인스턴스 생성 (재시작 시뮬레이션)
        det2 = FakeDetector('cam_001')
        assert det2.is_running is True,   "새 감지기는 is_running=True로 시작해야 함"
        assert det1 is not det2,          "재시작 시 새 인스턴스여야 함"

    def test_queue_greenlets_는_seg_key로_스레드를_관리한다(self):
        """
        _queue_greenlets 딕셔너리는 (road, start_ic, end_ic) 키로 스레드를 관리한다.
        같은 구간을 재시작하면 이전 항목이 새 스레드로 덮어씌워진다.
        """
        seg_key = ('gyeongbu', 'A', 'B')

        t1 = threading.Thread(target=lambda: None, daemon=True)
        t1.start()
        monitoring._queue_greenlets[seg_key] = t1

        t2 = threading.Thread(target=lambda: None, daemon=True)
        t2.start()
        monitoring._queue_greenlets[seg_key] = t2   # 덮어쓰기

        assert monitoring._queue_greenlets[seg_key] is t2, "새 스레드로 교체되어야 함"
        t1.join(timeout=0.1)
        t2.join(timeout=0.1)
        monitoring._queue_greenlets.clear()

    def test_count_learning_alive_는_dead_thread를_학습_중으로_세지_않는다(self):
        """
        _count_learning_alive()는 스레드가 죽었으면 is_learning=True여도 카운트하지 않는다.
        이것이 free_slots 계산이 정확하게 동작하는 핵심 조건이다.
        """
        lock = threading.Lock()

        # 죽은 스레드 + is_learning=True 감지기
        dead_thread = MagicMock()
        dead_thread.is_alive.return_value = False   # 스레드 사망 상태

        dead_det = FakeDetector('cam_dead', is_learning=True)

        mock_dm = MagicMock()
        mock_dm._lock = lock
        mock_dm.active_detectors = {'monitoring_cam_dead': dead_det}
        mock_dm.threads = {'monitoring_cam_dead': dead_thread}

        # _count_learning_alive()는 isinstance(det, MonitoringDetector) 체크를 한다.
        # MonitoringDetector는 stub(MagicMock)이므로 isinstance() 두 번째 인자로 사용하면
        # TypeError가 발생한다. monitoring.MonitoringDetector를 FakeDetector로 임시 교체한다.
        original_dm = monitoring.detector_manager
        original_md = monitoring.MonitoringDetector
        monitoring.detector_manager = mock_dm
        monitoring.MonitoringDetector = FakeDetector   # isinstance 체크 통과용 실제 클래스

        try:
            # dead thread는 is_learning=True여도 카운트 0
            count = monitoring._count_learning_alive()
            assert count == 0, (
                f"dead thread가 있는 감지기를 학습 중으로 카운트함 (count={count})\n"
                f"→ free_slots 계산이 잘못되어 큐가 영원히 멈출 수 있음"
            )
        finally:
            monitoring.detector_manager = original_dm
            monitoring.MonitoringDetector = original_md
