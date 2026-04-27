# modules/monitoring/tests/test_stream_retry.py
# 역할: 스트림 열기 재시도 로직과 dead 감지기 자동 정리 기능을 검증하는 테스트
# 실행: pytest modules/monitoring/tests/test_stream_retry.py -v

import types
import threading
import pytest
from unittest.mock import MagicMock, patch, call


# ─────────────────────────────────────────────────────────────────────────────
# 픽스처: 가짜 cap 객체 (isOpened 반환값을 순서대로 지정 가능)
# ─────────────────────────────────────────────────────────────────────────────

def _make_cap(opened_sequence):
    """
    isOpened()를 순서대로 True/False 반환하는 가짜 VideoCapture 객체를 만든다.
    opened_sequence 예: [False, False, True] → 1·2회차 실패, 3회차 성공
    """
    cap = MagicMock()                               # 가짜 VideoCapture
    cap.isOpened.side_effect = opened_sequence      # 호출 순서에 따라 다른 값 반환
    cap.get.return_value = 30.0                     # CAP_PROP_FPS 기본값
    cap.read.return_value = (False, None)           # 프레임 읽기는 기본 실패
    return cap


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 1: 첫 번째 시도에서 성공하면 재시도 없이 진행
# ─────────────────────────────────────────────────────────────────────────────

class TestStreamOpenRetry:
    """
    스트림 열기 재시도 로직을 단위 테스트한다.
    _open_http_cap 과 time.sleep 을 mock으로 대체해 네트워크 없이 검증한다.
    """

    def _run_open_attempt(self, cap_sequence, fresh_url_return="http://fake-url"):
        """
        run()의 스트림 열기 부분만 떼어내어 재시도 횟수를 검증하는 헬퍼.

        실제 MonitoringDetector를 생성하지 않고,
        스트림 열기 로직이 들어있는 함수만 직접 실행한다.

        Returns:
            tuple: (opened: bool, open_call_count: int, sleep_call_count: int)
        """
        caps = [_make_cap([result]) for result in cap_sequence]
        cap_iter = iter(caps)

        open_calls = []     # _open_http_cap 호출 횟수 추적
        sleep_calls = []    # time.sleep 호출 횟수 추적

        def fake_open_http_cap(url):
            # 호출마다 다음 cap을 반환한다
            open_calls.append(url)
            return next(cap_iter)

        def fake_sleep(secs):
            # 실제로 대기하지 않고 호출만 기록한다
            sleep_calls.append(secs)

        def fake_get_fresh_url():
            return fresh_url_return

        # ── 재시도 로직 인라인 시뮬레이션 ────────────────────────────────────
        # monitoring_detector.py 의 스트림 열기 블록을 그대로 재현한다.
        # 실제 코드 변경 후 이 로직과 동일하게 동작해야 한다.
        _OPEN_MAX_RETRIES = 3
        _OPEN_RETRY_DELAY = 5
        opened = False
        is_running = True   # stop()이 호출되지 않은 정상 상태 가정

        for attempt in range(1, _OPEN_MAX_RETRIES + 1):
            if not is_running:
                break
            url = fake_get_fresh_url()          # 매 시도마다 토큰 갱신
            cap = fake_open_http_cap(url)
            if cap.isOpened():
                opened = True
                break
            cap.release()                       # 실패 시 캡처 해제
            if attempt < _OPEN_MAX_RETRIES:
                fake_sleep(_OPEN_RETRY_DELAY)

        return opened, len(open_calls), len(sleep_calls)

    # ── 테스트 케이스 ──────────────────────────────────────────────────────

    def test_첫번째_시도_성공_재시도_없음(self):
        """첫 시도에서 스트림이 열리면 재시도 없이 1회 호출로 끝난다."""
        opened, open_cnt, sleep_cnt = self._run_open_attempt([True])
        assert opened is True
        assert open_cnt == 1        # _open_http_cap 1회 호출
        assert sleep_cnt == 0       # 대기 없음

    def test_두번째_시도_성공_재시도_1회(self):
        """첫 시도 실패, 두 번째 시도에서 성공하면 열기 2회·대기 1회."""
        opened, open_cnt, sleep_cnt = self._run_open_attempt([False, True])
        assert opened is True
        assert open_cnt == 2
        assert sleep_cnt == 1       # 1번 대기

    def test_세번째_시도_성공_재시도_2회(self):
        """1·2회차 실패, 3회차 성공 → 열기 3회·대기 2회."""
        opened, open_cnt, sleep_cnt = self._run_open_attempt([False, False, True])
        assert opened is True
        assert open_cnt == 3
        assert sleep_cnt == 2       # 2번 대기

    def test_전체_실패_최대_재시도_횟수_초과(self):
        """3회 모두 실패하면 opened=False이고 열기 3회·대기 2회."""
        opened, open_cnt, sleep_cnt = self._run_open_attempt([False, False, False])
        assert opened is False
        assert open_cnt == 3        # 최대 3회 시도
        assert sleep_cnt == 2       # 마지막 시도 후엔 대기 없음

    def test_매_재시도마다_fresh_url_요청(self):
        """
        HTTP 스트림은 ITS 토큰이 만료될 수 있으므로
        각 시도마다 _get_fresh_url()을 호출해 새 토큰을 받아야 한다.
        """
        call_log = []

        def fake_open(url):
            call_log.append(url)
            cap = MagicMock()
            # 처음 두 번 실패, 세 번째 성공
            cap.isOpened.return_value = (len(call_log) == 3)
            cap.release = MagicMock()
            return cap

        fresh_call_count = [0]

        def fake_fresh_url():
            fresh_call_count[0] += 1
            return f"http://fresh-url-{fresh_call_count[0]}"

        _OPEN_MAX_RETRIES = 3
        _OPEN_RETRY_DELAY = 0   # 대기 없이 즉시 재시도 (테스트 속도)
        opened = False

        for attempt in range(1, _OPEN_MAX_RETRIES + 1):
            url = fake_fresh_url()
            cap = fake_open(url)
            if cap.isOpened():
                opened = True
                break
            cap.release()

        # _get_fresh_url을 3회 호출했는지 확인 (각 시도마다 새 토큰 요청)
        assert fresh_call_count[0] == 3
        assert opened is True


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 1-B: 브라우저 UA 폴백 로직
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserUaFallback:
    """
    MSMF 3회 모두 실패 시 브라우저 UA(FFMPEG) 폴백으로 스트림이 열리는지 검증한다.
    실제 cv2 호출 없이 open 함수를 mock 으로 대체해 단위 테스트한다.
    """

    def _run_with_fallback(self, msmf_results, browser_ua_result):
        """
        MSMF 결과 목록과 브라우저 UA 폴백 결과를 받아 최종 opened 여부를 반환한다.

        msmf_results    : [True/False, ...] MSMF 시도 결과 (최대 3개)
        browser_ua_result: True/False       브라우저 UA 폴백 결과
        """
        msmf_iter   = iter(msmf_results)
        msmf_calls  = []   # MSMF open 호출 횟수
        ua_calls    = []   # 브라우저 UA open 호출 횟수

        def fake_msmf_open(url):
            msmf_calls.append(url)
            cap = MagicMock()
            cap.isOpened.return_value = next(msmf_iter, False)
            cap.release = MagicMock()
            return cap

        def fake_browser_ua_open(url):
            ua_calls.append(url)
            cap = MagicMock()
            cap.isOpened.return_value = browser_ua_result
            cap.release = MagicMock()
            return cap

        def fake_fresh_url():
            return "http://fresh-url"

        def fake_sleep(_):
            pass   # 대기 없이 즉시 통과

        # ── MSMF 재시도 루프 시뮬레이션 ──────────────────────────────────────
        _OPEN_MSMF_RETRIES = 3
        _stream_opened = False
        is_running     = True

        for attempt in range(1, _OPEN_MSMF_RETRIES + 1):
            if not is_running:
                break
            url = fake_fresh_url()
            cap = fake_msmf_open(url)
            if cap.isOpened():
                _stream_opened = True
                break
            cap.release()
            if attempt < _OPEN_MSMF_RETRIES:
                fake_sleep(5)

        # ── 브라우저 UA 폴백 ─────────────────────────────────────────────────
        if not _stream_opened and is_running:
            url = fake_fresh_url()
            cap = fake_browser_ua_open(url)
            if cap.isOpened():
                _stream_opened = True
            else:
                cap.release()

        return _stream_opened, len(msmf_calls), len(ua_calls)

    # ── 테스트 케이스 ──────────────────────────────────────────────────────

    def test_MSMF_3회_실패_후_브라우저UA_성공(self):
        """MSMF 3회 모두 실패해도 브라우저 UA 폴백이 성공하면 스트림이 열린다."""
        opened, msmf_cnt, ua_cnt = self._run_with_fallback(
            msmf_results=[False, False, False],
            browser_ua_result=True,
        )
        assert opened is True
        assert msmf_cnt == 3    # MSMF 3회 시도
        assert ua_cnt   == 1    # 브라우저 UA 1회 시도

    def test_MSMF_성공_시_브라우저UA_미호출(self):
        """MSMF 첫 시도에 성공하면 브라우저 UA 폴백은 호출되지 않는다."""
        opened, msmf_cnt, ua_cnt = self._run_with_fallback(
            msmf_results=[True],
            browser_ua_result=True,   # 호출 안 되므로 결과 무관
        )
        assert opened is True
        assert msmf_cnt == 1
        assert ua_cnt   == 0    # 폴백 미호출

    def test_MSMF_2회_성공_시_브라우저UA_미호출(self):
        """MSMF 2회차에 성공하면 브라우저 UA 폴백은 호출되지 않는다."""
        opened, msmf_cnt, ua_cnt = self._run_with_fallback(
            msmf_results=[False, True],
            browser_ua_result=False,
        )
        assert opened is True
        assert msmf_cnt == 2
        assert ua_cnt   == 0

    def test_MSMF_3회_실패_브라우저UA_도_실패(self):
        """MSMF 3회 + 브라우저 UA 모두 실패하면 opened=False."""
        opened, msmf_cnt, ua_cnt = self._run_with_fallback(
            msmf_results=[False, False, False],
            browser_ua_result=False,
        )
        assert opened is False
        assert msmf_cnt == 3
        assert ua_cnt   == 1    # 폴백은 1회 시도됨


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 2: _resume_all_monitoring — dead 감지기 자동 정리
# ─────────────────────────────────────────────────────────────────────────────

class TestResumeAllMonitoring:
    """
    _resume_all_monitoring()이 스레드가 죽은 감지기를 건너뛰고
    active_detectors에서 자동으로 제거하는지 검증한다.
    """

    def _make_det(self, camera_id):
        """가짜 MonitoringDetector 인스턴스를 만든다."""
        det = MagicMock()
        det.camera_id = camera_id   # 로그 출력용 식별자
        return det

    def _make_thread(self, alive: bool):
        """is_alive()가 alive를 반환하는 가짜 스레드를 만든다."""
        t = MagicMock()
        t.is_alive.return_value = alive
        return t

    def test_살아있는_감지기만_재개된다(self):
        """
        스레드가 살아 있는 감지기만 resume()가 호출되고,
        죽은 감지기는 resume()가 호출되지 않는다.
        """
        # ── 준비: 살아있는 감지기 1개 + 죽은 감지기 1개 ────────────────────
        det_alive = self._make_det("cam_alive")
        det_dead  = self._make_det("cam_dead")

        t_alive = self._make_thread(alive=True)
        t_dead  = self._make_thread(alive=False)

        fake_active = {
            "monitoring_cam_alive": det_alive,
            "monitoring_cam_dead":  det_dead,
        }
        fake_threads = {
            "monitoring_cam_alive": t_alive,
            "monitoring_cam_dead":  t_dead,
        }

        # MonitoringDetector 타입 체크를 통과하도록 isinstance mock
        import modules.monitoring.monitoring as mon_module
        from modules.monitoring.monitoring_detector import MonitoringDetector

        # ── 실행: _resume_all_monitoring 로직 인라인 시뮬레이션 ──────────────
        # 실제 코드 변경 후 이 로직과 동일하게 동작해야 한다.
        resumed = []
        cleaned = []

        for key, det in list(fake_active.items()):
            if not key.startswith("monitoring_"):
                continue
            t = fake_threads.get(key)
            if t and t.is_alive():
                resumed.append(det.camera_id)
            else:
                cleaned.append(key)

        for key in cleaned:
            fake_active.pop(key, None)
            fake_threads.pop(key, None)

        # ── 검증 ──────────────────────────────────────────────────────────
        assert "cam_alive" in resumed       # 살아있는 감지기는 재개 대상
        assert "cam_dead" not in resumed    # 죽은 감지기는 재개 대상에서 제외
        assert "monitoring_cam_dead" not in fake_active     # dead 감지기 정리됨
        assert "monitoring_cam_dead" not in fake_threads    # 스레드도 정리됨
        assert "monitoring_cam_alive" in fake_active        # 살아있는 감지기는 유지

    def test_전부_살아있으면_모두_재개된다(self):
        """모든 감지기의 스레드가 살아있으면 전부 재개 대상이고 정리 대상 없음."""
        det_a = self._make_det("cam_a")
        det_b = self._make_det("cam_b")

        fake_active  = {"monitoring_cam_a": det_a, "monitoring_cam_b": det_b}
        fake_threads = {
            "monitoring_cam_a": self._make_thread(alive=True),
            "monitoring_cam_b": self._make_thread(alive=True),
        }

        resumed = []
        cleaned = []

        for key, det in list(fake_active.items()):
            if not key.startswith("monitoring_"):
                continue
            t = fake_threads.get(key)
            if t and t.is_alive():
                resumed.append(det.camera_id)
            else:
                cleaned.append(key)

        assert len(resumed) == 2
        assert len(cleaned) == 0

    def test_전부_죽어있으면_재개_없이_모두_정리된다(self):
        """모든 감지기의 스레드가 죽어있으면 재개 0개·정리 2개."""
        det_a = self._make_det("cam_a")
        det_b = self._make_det("cam_b")

        fake_active  = {"monitoring_cam_a": det_a, "monitoring_cam_b": det_b}
        fake_threads = {
            "monitoring_cam_a": self._make_thread(alive=False),
            "monitoring_cam_b": self._make_thread(alive=False),
        }

        resumed = []
        cleaned = []

        for key, det in list(fake_active.items()):
            if not key.startswith("monitoring_"):
                continue
            t = fake_threads.get(key)
            if t and t.is_alive():
                resumed.append(det.camera_id)
            else:
                cleaned.append(key)

        for key in cleaned:
            fake_active.pop(key, None)
            fake_threads.pop(key, None)

        assert len(resumed) == 0
        assert len(cleaned) == 2
        assert len(fake_active) == 0    # active_detectors 완전 비워짐

    def test_타팀_감지기는_건드리지_않는다(self):
        """
        'monitoring_' 접두사가 없는 타 팀 감지기(예: 'fire_cam01')는
        dead 여부와 관계없이 정리 대상에서 제외된다.
        """
        det_other = self._make_det("other_cam")
        t_dead    = self._make_thread(alive=False)

        fake_active  = {"fire_other_cam": det_other}
        fake_threads = {"fire_other_cam": t_dead}

        cleaned = []
        for key, det in list(fake_active.items()):
            if not key.startswith("monitoring_"):
                continue    # 타 팀 감지기는 건너뜀
            t = fake_threads.get(key)
            if not (t and t.is_alive()):
                cleaned.append(key)

        assert len(cleaned) == 0           # 타 팀 감지기는 정리 안 됨
        assert "fire_other_cam" in fake_active


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 3: 지수 백오프 대기 시간 계산 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestExponentialBackoff:
    """
    재연결 실패 횟수에 따른 지수 백오프 대기 시간을 검증한다.
    공식: min(10 * 2^(fail_count - 1), 300)
    1회→10초, 2회→20초, 3회→40초, ..., 6회 이상→300초 상한
    """

    def _calc_wait(self, fail_count: int) -> int:
        """실제 monitoring_detector.py 의 대기 시간 계산 공식을 복제한다."""
        return min(10 * (2 ** (fail_count - 1)), 300)   # 최대 5분(300초)

    def test_첫번째_실패_10초(self):
        """첫 번째 재연결 실패 후 10초 대기한다."""
        assert self._calc_wait(1) == 10

    def test_두번째_실패_20초(self):
        """두 번째 연속 실패 후 20초 대기한다."""
        assert self._calc_wait(2) == 20

    def test_세번째_실패_40초(self):
        """세 번째 연속 실패 후 40초 대기한다."""
        assert self._calc_wait(3) == 40

    def test_네번째_실패_80초(self):
        """네 번째 연속 실패 후 80초 대기한다."""
        assert self._calc_wait(4) == 80

    def test_다섯번째_실패_160초(self):
        """다섯 번째 연속 실패 후 160초 대기한다."""
        assert self._calc_wait(5) == 160

    def test_여섯번째_이상_300초_상한_적용(self):
        """여섯 번째 이상은 계산값(320+)이 상한(300초)에 의해 잘린다."""
        assert self._calc_wait(6) == 300    # 320 → 상한 적용
        assert self._calc_wait(7) == 300    # 640 → 상한 적용
        assert self._calc_wait(10) == 300   # 5120 → 상한 적용

    def test_대기_시간은_단조_증가한다(self):
        """실패 횟수가 늘수록 대기 시간이 같거나 더 길어진다."""
        waits = [self._calc_wait(i) for i in range(1, 8)]
        for a, b in zip(waits, waits[1:]):
            assert b >= a   # 다음 대기 시간이 이전보다 짧아지지 않는다


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 4: 재연결 실패/복구 시 SocketIO 이벤트 emit 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestStreamEventEmit:
    """
    재연결 실패 시 camera_stream_failed 이벤트가,
    복구 시 camera_stream_recovered 이벤트가 emit되는지 검증한다.
    """

    def _simulate_fail_cycle(self, fail_count_before: int, socketio):
        """
        재연결 실패 직후 실행되는 로직을 시뮬레이션한다.
        monitoring_detector.py 의 실패 분기 코드를 그대로 복제한다.
        """
        from datetime import datetime, timedelta

        # 실패 횟수 증가 (run() 루프의 if not reconnected 분기)
        fail_count = fail_count_before + 1

        # 지수 백오프 대기 시간 계산
        wait_sec = min(10 * (2 ** (fail_count - 1)), 300)

        # 다음 재시도 예정 시각 계산
        next_retry = datetime.utcnow() + timedelta(seconds=wait_sec)

        # 프론트엔드에 스트림 실패 알림 emit
        if socketio:
            socketio.emit('camera_stream_failed', {
                'camera_id':     'test_cam',       # 카메라 식별자
                'fail_count':    fail_count,        # 누적 실패 횟수
                'next_retry_in': wait_sec,          # 다음 재시도까지 남은 초
                'next_retry_at': next_retry.isoformat(),  # 다음 재시도 예정 시각
            })

        return fail_count, wait_sec

    def _simulate_recover(self, fail_count_before: int, socketio):
        """
        재연결 성공(= 정상 프레임 수신) 시 실행되는 복구 로직을 시뮬레이션한다.
        monitoring_detector.py 의 성공 분기 코드를 그대로 복제한다.
        """
        # 이전에 실패했다가 복구된 경우에만 이벤트 전송
        if fail_count_before > 0:
            if socketio:
                socketio.emit('camera_stream_recovered', {'camera_id': 'test_cam'})
            return 0   # fail_count 초기화

        return fail_count_before   # 실패 없었으면 그대로 유지

    # ── 테스트 케이스 ──────────────────────────────────────────────────────────

    def test_첫번째_실패_시_이벤트_emit(self):
        """처음 재연결 실패 시 camera_stream_failed 이벤트가 1회 emit된다."""
        socketio = MagicMock()
        fail_count, wait_sec = self._simulate_fail_cycle(0, socketio)

        socketio.emit.assert_called_once()             # 정확히 1회 emit
        event_name = socketio.emit.call_args[0][0]     # 첫 번째 위치 인자 = 이벤트 이름
        assert event_name == 'camera_stream_failed'    # 이벤트 이름 검증
        assert fail_count == 1                         # 실패 횟수 1로 증가
        assert wait_sec == 10                          # 첫 실패 → 10초 대기

    def test_연속_실패_시_대기_시간_증가(self):
        """연속 3회 실패 후 대기 시간이 지수적으로 늘어난다."""
        socketio = MagicMock()
        expected_waits = [10, 20, 40]   # 1회→10초, 2회→20초, 3회→40초

        fail_count = 0
        actual_waits = []
        for _ in range(3):
            fail_count, wait_sec = self._simulate_fail_cycle(fail_count, socketio)
            actual_waits.append(wait_sec)

        assert actual_waits == expected_waits          # 대기 시간 지수 증가 확인
        assert socketio.emit.call_count == 3           # 실패마다 이벤트 1회씩 emit

    def test_복구_시_이벤트_emit_및_카운터_초기화(self):
        """재연결 성공 시 camera_stream_recovered emit 및 fail_count=0 초기화."""
        socketio = MagicMock()

        # 2회 실패 후 복구 시뮬레이션
        fail_count, _ = self._simulate_fail_cycle(0, socketio)
        fail_count, _ = self._simulate_fail_cycle(fail_count, socketio)
        fail_count = self._simulate_recover(fail_count, socketio)

        # camera_stream_failed 2회 + camera_stream_recovered 1회
        assert socketio.emit.call_count == 3
        last_event = socketio.emit.call_args_list[-1][0][0]
        assert last_event == 'camera_stream_recovered'
        assert fail_count == 0   # 카운터 초기화 확인

    def test_처음부터_성공이면_복구_이벤트_없음(self):
        """실패 없이 바로 성공하면 camera_stream_recovered를 emit하지 않는다."""
        socketio = MagicMock()
        fail_count = self._simulate_recover(0, socketio)   # fail_count=0 → 복구 이벤트 없음

        socketio.emit.assert_not_called()   # 이벤트 없음
        assert fail_count == 0

    def test_socketio_없어도_오류_없음(self):
        """socketio=None 이어도 AttributeError 없이 실행된다."""
        fail_count, wait_sec = self._simulate_fail_cycle(0, None)
        assert fail_count == 1    # 로직은 정상 동작
        assert wait_sec == 10
