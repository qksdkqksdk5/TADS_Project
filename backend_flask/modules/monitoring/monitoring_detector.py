"""
monitoring_detector.py
final_pj 역주행·정체 탐지 파이프라인을 Flask-SocketIO에 통합하는 감지기.
FireDetector(BaseDetector) 와 동일한 패턴으로 구현.
"""

import sys
import os

import cv2
import numpy as np
import time
import threading   # _CAP_OPEN_LOCK 전역 잠금용

# ── OpenCV 로그 레벨 억제 ───────────────────────────────────────────────────
# [DEBUG:N@...] retrieveFrame 등의 OpenCV FFMPEG 디버그 메시지가 터미널을
# 도배하는 것을 막기 위해 WARNING 수준 이상만 출력하도록 설정한다.
#
# cv2.setLogLevel()은 이 빌드에서 사용 불가(AttributeError)이므로
# cv2.utils.logging.setLogLevel() 을 시도하고, 그것도 없으면 조용히 넘어간다.
# 이 빌드에서도 안 된다면 서버 시작 전에 아래 환경변수를 설정하면 된다:
#   Windows:  set OPENCV_LOG_LEVEL=WARNING
#   Linux:    export OPENCV_LOG_LEVEL=WARNING
try:
    # OpenCV 4.5+ 일부 빌드: cv2.utils.logging 서브모듈
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_WARNING)
except AttributeError:
    # 위 API 없으면 환경변수로 대체 시도
    # (이미 cv2가 로드된 경우에는 효과 없으나, 재시작 시 적용됨)
    os.environ.setdefault('OPENCV_LOG_LEVEL', 'WARNING')
import gevent
from gevent.threadpool import ThreadPool as _GeventThreadPool
from datetime import datetime
from pathlib import Path

# ── 모듈 경로 등록 ───────────────────────────────────────────────────────
# monitoring_detector.py 기준: monitoring/
_BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
# detector_modules/ — flow_map_matcher 포함한 모든 감지기 서브모듈 위치
_MODULES_DIR = os.path.join(_BASE_DIR, 'detector_modules')

for _p in (_BASE_DIR, _MODULES_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── flow_map_matcher 임포트 ───────────────────────────────────────────────
# 저장된 flow_map 중 현재 카메라 화면과 가장 유사한 것을 자동 선택한다.
# 학습 결과 재사용으로 서버 재시작 시 매번 학습하는 비효율을 제거한다.
# (이전: C:\final_pj\src → 현재: detector_modules/ 로 이전)
from detector_modules.flow_map_matcher import (       # 스냅샷 저장·검색 함수 임포트
    FlowMapMatcher,                                   # 교차 카메라 매칭
    save_flow_snapshot,                               # 타임스탬프 기반 스냅샷 저장
    find_best_snapshot,                               # 현재 프레임과 가장 유사한 스냅샷 검색
)

# ── flow_map 캐시 저장 루트 ────────────────────────────────────────────────
# {_FLOW_MAPS_ROOT}/{camera_id}/flow_map.npy  — 학습 결과 저장
# {_FLOW_MAPS_ROOT}/{camera_id}/ref_frame.jpg — 매칭용 기준 프레임
_FLOW_MAPS_ROOT = Path(_BASE_DIR) / "flow_maps"

from detector_modules.config           import DetectorConfig
from detector_modules.state            import DetectorState
from detector_modules.flow_map         import FlowMap
from detector_modules.tracker          import YoloTracker
from detector_modules.judge            import WrongWayJudge
from detector_modules.id_manager       import IDManager
from detector_modules.camera_switch    import CameraSwitchDetector
from detector_modules.traffic_analyzer import TrafficAnalyzer, CongestionPredictor
from modules.monitoring.detector_modules.config          import DetectorConfig
from modules.monitoring.detector_modules.state           import DetectorState
from modules.monitoring.detector_modules.flow_map        import FlowMap
from modules.monitoring.detector_modules.tracker         import YoloTracker
from modules.monitoring.detector_modules.judge           import WrongWayJudge
from modules.monitoring.detector_modules.id_manager      import IDManager
from modules.monitoring.detector_modules.camera_switch   import CameraSwitchDetector
from modules.monitoring.detector_modules.traffic_analyzer      import TrafficAnalyzer, CongestionPredictor
from modules.monitoring.detector_modules.historical_predictor  import HistoricalPredictor

from modules.traffic.detectors.base_detector import BaseDetector

# ── 상수 ────────────────────────────────────────────────────────────────
# _YOLO_MODEL    = r'C:\final_pj\runs\yolo11n_v6\weights\best.pt'
_YOLO_MODEL      = os.path.join(_BASE_DIR, 'best.pt')
_EMIT_INTERVAL   = 30    # 30프레임마다 traffic_update emit (약 1초@30fps) — Socket.IO 주기는 유지
_LOG_INTERVAL    = 300   # 콘솔 상태 출력 주기 (약 10초@30fps) — 터미널 노이즈 억제
_SKIP_LOG_COOL   = 300   # 프레임 스킵 로그 쿨타임 (같은 카메라 300프레임 이내 중복 출력 방지)


# ─────────────────────────────────────────────────────────────────────────────
# 프레임 스킵·단독 점프 리셋 헬퍼 (모듈 레벨 순수 함수 — 단독 테스트 가능)
# ─────────────────────────────────────────────────────────────────────────────

def _apply_frame_skip_reset(st, tracks, frame_num):
    """전역 프레임 스킵 감지 시 모든 추적 차량의 상태를 현재 위치로 초기화한다.

    전역 프레임 스킵이란 HLS 스트림 끊김으로 추적 차량의 절반 이상이
    한 프레임 사이에 비정상적으로 큰 변위를 보이는 상황을 말한다.

    수행 동작:
    1. post_reconnect_frame = frame_num 설정
       → judge.py 의 _reconnect_guard 를 활성화해
         스킵 이후 새로 등장한 차량(ByteTrack 신규 ID)의 fast-track 오탐을 차단.
    2. 각 차량 궤적을 현재 위치로 전부 덮어씀
       → velocity 계산(traj[-window]→traj[-1])에서 점프 전 좌표를 제거.
    3. last_velocity, wrong_way_count, direction_change_frame, wrong_way_ids 초기화
       → 스킵 전 누적된 역주행 의심·확정 상태를 모두 리셋.

    Args:
        st        : DetectorState — 수정 대상 상태 객체
        tracks    : 현재 프레임 추적 결과 [{"id": int, "cx": float, "cy": float}, ...]
        frame_num : 현재 프레임 번호 (st.frame_num 과 동일해야 함)
    """
    # ① reconnect_guard 활성화 — 기존 ID 보호(direction_change_frame)만으로는
    #   스킵 후 새로 발급된 ByteTrack ID 가 보호되지 않는다.
    #   post_reconnect_frame 을 설정해야 judge.py 의 _reconnect_guard 가 발동되어
    #   direction_change_guard_frames 동안 fast-track 과 최종 확정을 모두 차단한다.
    st.post_reconnect_frame = frame_num  # 재연결 이벤트 프레임 기록

    for t in tracks:
        tid = t["id"]                          # 추적 ID

        # ② 궤적 전체를 현재 위치로 초기화
        # 마지막 점만 바꾸면 이전 점(점프 전 좌표)이 남아 있어
        # velocity 계산 시 "순간이동 벡터"가 계속 사용되어 오탐이 이어진다.
        if st.trajectories[tid]:               # 기존 궤적이 있을 때만 초기화
            cur_pos = (t["cx"], t["cy"])        # 현재(점프 후) 위치
            st.trajectories[tid] = [cur_pos] * len(st.trajectories[tid])

        # ③ 점프 전 방향 벡터 제거 — dir_jump 필터 오작동 방지
        st.last_velocity.pop(tid, None)

        # ④ 역주행 의심 카운트 초기화 — 점프 전 누적된 의심 횟수 제거
        st.wrong_way_count[tid] = 0

        # ⑤ direction_change_guard 발동 — 이 ID 가 다음 guard_frames 동안 판정 차단
        st.direction_change_frame[tid] = frame_num

        # ⑥ 스킵 직전 오탐으로 확정된 역주행 취소
        st.wrong_way_ids.discard(tid)


def _apply_solo_jump_reset(st, tid, cur_pos, frame_num):
    """단독 차량 점프 감지 시 해당 차량의 상태를 현재 위치로 초기화한다.

    "단독 점프"란 전역 프레임 스킵으로 분류되지 않지만
    특정 차량 1대의 프레임 간 변위가 임계값(jump_px × 1.5)을 초과하는 상황이다.
    ByteTrack 이 해당 차량 ID 를 놓쳤다가 재할당하는 경우가 많다.

    수행 동작:
    1. post_reconnect_frame = frame_num 설정
       → 점프 후 등장한 신규 ID 도 reconnect_guard 보호 범위에 포함.
    2~6. _apply_frame_skip_reset 과 동일한 단일 차량 초기화.

    Args:
        st        : DetectorState — 수정 대상 상태 객체
        tid       : 단독 점프가 감지된 차량의 추적 ID
        cur_pos   : 점프 후 현재 위치 (fx, fy) 튜플
        frame_num : 현재 프레임 번호
    """
    # ① reconnect_guard 활성화 (전역 스킵과 동일한 이유로 필요)
    st.post_reconnect_frame = frame_num  # 재연결 이벤트 프레임 기록

    # ② 궤적 전체를 현재 위치로 초기화
    st.trajectories[tid] = [cur_pos] * len(st.trajectories[tid])

    # ③ 점프 전 방향 벡터 제거
    st.last_velocity.pop(tid, None)

    # ④ 역주행 의심 카운트 초기화
    st.wrong_way_count[tid] = 0

    # ⑤ direction_change_guard 발동
    st.direction_change_frame[tid] = frame_num

    # ⑥ 스킵 직전 확정된 역주행 취소
    st.wrong_way_ids.discard(tid)


# ── gevent 호환 OS 스레드 풀 ──────────────────────────────────────────────
# cap.read() / tracker.track() 등 C 익스텐션 블로킹 호출을 실제 OS 스레드에서
# 실행하여 gevent 이벤트 루프를 차단하지 않도록 한다.
# (카메라 수 × 2 작업 여유치로 8 설정)
_FRAME_POOL = _GeventThreadPool(maxsize=16)

# ── VideoCapture open() 직렬화 잠금 ───────────────────────────────────────────
# 여러 MonitoringDetector 스레드가 동시에 cv2.VideoCapture()를 호출하면
# OpenCV의 FFMPEG 플러그인 전역 초기화 상태가 경쟁(race condition)을 일으켜
# FFMPEG 대신 MSMF/CAP_IMAGES 같은 엉뚱한 백엔드가 선택되고, HTTP(HLS) URL
# 열기에 실패한다. 이 잠금으로 VideoCapture open()을 직렬화해 문제를 방지한다.
_CAP_OPEN_LOCK = threading.Lock()

# ── ITS URL 갱신 직렬화 잠금 ──────────────────────────────────────────────────
# 여러 MonitoringDetector 스레드가 동시에 _get_fresh_url() 을 호출하면
# _cctv_cache.pop() 경쟁이 발생해 일부 카메라가 빈 캐시를 보고 API 재호출에 실패,
# 만료된(404) URL 을 그대로 사용하게 된다.
# 이 잠금으로 pop+재조회를 직렬화해 경쟁을 없애고,
# 두 번째 이후 스레드는 첫 번째 스레드가 갱신한 캐시를 재사용한다.
_FRESH_URL_LOCK = threading.Lock()


def _open_rtsp_cap(url: str):
    """
    RTSP 스트림을 FFMPEG 백엔드로 여는 헬퍼.
    thread pool(OS 스레드)에서 호출해도 무방하다.
    RTSP는 Python 소켓과 무관한 FFMPEG 자체 TCP 연결을 사용하기 때문이다.
    """
    c = cv2.VideoCapture(url, cv2.CAP_FFMPEG)   # FFMPEG 백엔드 강제
    c.set(cv2.CAP_PROP_BUFFERSIZE, 1)            # 버퍼 최소화 → 실시간성 확보
    return c


def _open_http_cap(url: str):
    """
    HTTP/HLS 스트림을 여는 헬퍼.

    ※ cv2.CAP_FFMPEG 를 명시하지 않는다.
    ITS 서버는 FFMPEG 백엔드의 User-Agent("Lavf/xx.xx.xx")를 거부해 HTTP 403을
    반환한다. cv2.VideoCapture(url, cv2.CAP_FFMPEG) 를 쓰면 ITS 서버가 항상 403을
    돌려보내 스트림 열기에 실패한다.

    백엔드를 명시하지 않으면 Windows에서 OpenCV 가 MSMF(Windows Media Foundation)를
    자동 선택한다. MSMF 는 Windows 표준 HTTP 스택을 사용하므로 ITS 서버가 허용한다.
    (view_feed 엔드포인트가 cv2.VideoCapture(url) 로 정상 동작하는 것과 같은 원리)

    _CAP_OPEN_LOCK 은 여전히 유지한다.
    여러 스레드가 cv2.VideoCapture() 를 동시에 호출하면 백엔드 플러그인 초기화
    경쟁 상태가 발생하므로, 잠금으로 직렬화해 이를 방지한다.
    """
    with _CAP_OPEN_LOCK:
        # 백엔드 자동 선택 — Windows 에서 MSMF 를 선택해 ITS 서버와 호환된다
        c = cv2.VideoCapture(url)
        # 버퍼를 최소화해 실시간 스트림 지연을 줄인다
        c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return c


class MonitoringDetector(BaseDetector):
    """
    역주행·정체 탐지 파이프라인 + Socket.IO 연동.

    Parameters
    ----------
    cctv_name : str   BaseDetector에서 사용하는 감지기 이름
    url       : str   RTSP / HLS 스트림 URL
    camera_id : str   프론트엔드 식별자 (traffic_update 페이로드에 포함)
    lat, lng  : float CCTV 위치 좌표
    location  : str   위치 설명 문자열 (이벤트 로그에 표시)
    """

    def __init__(self, cctv_name, url, camera_id,
                 lat=37.5, lng=127.0, location="",
                 socketio=None, db=None, app=None):

        super().__init__(cctv_name, url, app=app,
                         socketio=socketio, db=db, ResultModel=None)

        self.camera_id = camera_id
        self.lat       = lat
        self.lng       = lng
        self.location  = location

        # ── flow_map 캐시 저장 루트 (인스턴스 속성으로 관리) ─────────────
        # 모듈 상수 _FLOW_MAPS_ROOT 를 인스턴스 속성으로 연결해 테스트에서 교체 가능하게 한다.
        self._flow_maps_root = _FLOW_MAPS_ROOT

        # ── DetectorConfig ─────────────────────────────────────────────
        # flow_map_path=None + detect_only=False → 옵션 B: 매번 새로 학습
        self.cfg = DetectorConfig(
            model_path   = Path(_YOLO_MODEL),
            conf         = 0.3,
            detect_only  = False,   # 항상 학습 모드로 시작
            flow_map_path= None,    # flow_map 저장/로드 없음
            log_dir      = None,    # CSV 로그 비활성
        )

        # ── AI 파이프라인 컴포넌트 ────────────────────────────────────────
        self.state  = DetectorState()
        self.flow   = FlowMap(self.cfg.grid_size, self.cfg.alpha, self.cfg.min_samples)
        self.tracker = YoloTracker(
            self.cfg.model_path, self.cfg.conf, self.cfg.target_classes,
            night_enhance=getattr(self.cfg, 'night_enhance', True)
        )
        print(f"🧠 [{self.camera_id}] YOLO 모델 로드 완료")

        self.judge  = WrongWayJudge(self.cfg, self.flow, self.state)
        self.idm    = IDManager(self.cfg, self.flow, self.state)
        self.switch = CameraSwitchDetector(self.cfg)

        # TrafficAnalyzer: 프레임 크기 확인 후 run() 에서 초기화
        self.traffic_analyzer_a = None   # A방향 정체 분석기 (run()에서 초기화)
        self.traffic_analyzer_b = None   # B방향 정체 분석기 (run()에서 초기화)
        self.predictor_a        = None   # A방향 단기 추세 예측기
        self.predictor_b        = None   # B방향 단기 추세 예측기
        self._hist_pred_a       = None   # A방향 시각별 이력 기반 5분 후 예측기
        self._hist_pred_b       = None   # B방향 시각별 이력 기반 5분 후 예측기
        self._prev_ref_direction = None  # 재학습 직전 방향 벡터 (방향 반전 감지용)
                                         # 재학습 완료 후 전후 방향 비교 → 180° 회전 감지 →
                                         # HistoricalPredictor 슬롯 스왑에 사용

        # ── 방향 분류 상태 ────────────────────────────────────────────────
        self._ref_direction  = None
        self._dir_label_a    = "상행"
        self._dir_label_b    = "하행"
        self._valid_cells_a  = 1
        self._valid_cells_b  = 1
        self._dir_a_is_left  = True    # A방향이 화면 왼쪽인지 여부 — 학습 완료 후 갱신
        self._track_direction: dict = {}   # {track_id: 'a' | 'b'}

        # ── Socket.IO emit / REST API 공유 상태 ──────────────────────────
        # frame_lock(BaseDetector 제공)으로 스레드 안전하게 접근
        self._prev_level_a      = "SMOOTH"   # 방향 A(상행 or 하행) 레벨 전환 감지용 — 방향별 독립 알림을 위해 분리
        self._prev_level_b      = "SMOOTH"   # 방향 B(하행 or 상행) 레벨 전환 감지용
        self._wrongway_alerted  = set()      # 이미 알림 보낸 역주행 track_id
        self.latest_tracks_info = []         # Step 4 REST API용
        self.latest_speeds      = {}         # Step 4 REST API용
        self.debug_info: dict   = {}         # /debug/<camera_id> 응답용

        # ── MJPEG 스트림 최적화용 ─────────────────────────────────────────
        # generate_frames()에서 같은 프레임을 반복 인코딩하지 않기 위한 카운터.
        # latest_frame이 교체될 때마다 증가 → 스트림이 last_frame_id와 비교해 스킵 판단.
        self._stream_frame_id = 0
        # 스트림 다운스케일 비율 (run()에서 실제 해상도 확인 후 설정).
        # 트랙 좌표도 동일 비율로 스케일링해 canvas overlay 싱크 유지.
        self._stream_scale = 1.0

        # ── 탭 이탈 시 일시정지 플래그 ───────────────────────────────────
        # True: run() 루프에서 cap.read/YOLO/emit 을 건너뛰고 gevent.sleep만 실행
        # → CPU 사용률 거의 0%로 낮추면서 학습된 모델 상태는 메모리에 유지
        # monitoring.py 의 _pause_all_monitoring() / _resume_all_monitoring() 에서 제어
        self._paused = False

        # ── 진단 정보 딕셔너리 ────────────────────────────────────────────
        # /api/monitoring/diagnostics 엔드포인트에서 실시간으로 조회 가능.
        # reconnect_count 급증 → 스트림 불안정
        # read_max_ms ≥ 29000 → FFMPEG 타임아웃 발생 (이벤트 루프 차단 위험)
        # last_frame_age_s 급증 → 해당 카메라 프레임 공급 중단
        self._diag: dict = {
            'read_last_ms':     0,      # 최근 cap.read() 소요 시간 (ms)
            'read_max_ms':      0,      # 세션 중 cap.read() 최대 소요 시간 (ms)
            'reconnect_count':  0,      # reconnect() 호출 누적 횟수
            'reconnect_last_at': None,  # 마지막 reconnect 시각 (ISO 문자열)
            'last_frame_ok_at': None,   # 마지막 정상 프레임 수신 시각 (ISO 문자열)
        }

        # ── ITS 도로 키 ────────────────────────────────────────────────────
        # camera_id 형식: "{road_key}_{카메라명}" (예: "gyeongbu_[경부선]_한곡1교")
        # URL 갱신 시 어느 도로의 카메라인지 알아야 하므로 road_key를 미리 추출해둔다.
        self._road_key = camera_id.split('_')[0] if '_' in camera_id else ''

    # ────────────────────────────────────────────────────────────────────
    # ITS URL 토큰 갱신
    # ────────────────────────────────────────────────────────────────────

    def _get_fresh_url(self) -> str:
        """
        ITS CCTV URL에 포함된 시간제한 토큰을 갱신한다.

        ITS URL 구조: http://cctvsec.ktict.co.kr/{id}/{base64_token}=
        토큰은 수십 초 이내에 만료된다. YOLO 모델 로드 시간(수 초) 동안
        토큰이 만료되면 cv2.VideoCapture() 가 HTTP 403을 받아 실패한다.

        이 메서드는 VideoCapture 호출 직전에 실행해야 한다:
          1. its_helper._cctv_cache 에서 road_key 항목을 pop → 캐시 강제 무효화
          2. its_helper.get_cctv_list(road_key) 로 ITS API 재호출 → 신선한 토큰 획득
          3. camera_id 가 일치하는 카메라의 새 URL을 self.url 에 저장 후 반환

        Returns
        -------
        str
            갱신된 URL. 갱신 불가(road_key 없음·RTSP·API 오류·목록 미존재)이면
            기존 self.url 을 그대로 반환한다.
        """
        # road_key 를 알 수 없으면 어느 도로인지 특정 불가 → 원본 반환
        if not self._road_key:
            return self.url

        # RTSP 스트림은 ITS HTTP 토큰 방식이 아니므로 갱신 불필요
        if self.url.lower().startswith(('rtsp://', 'rtsps://')):
            return self.url

        try:
            from modules.monitoring import its_helper   # 지연 임포트로 순환 참조 방지
            import time as _time

            # ── 직렬화 잠금으로 동시 pop 경쟁 방지 ──────────────────────────
            # 여러 카메라 스레드가 동시에 이 메서드를 호출하면
            #   스레드 A: pop → 캐시 비워짐 → API 호출 중
            #   스레드 B: pop(이미 비어있음) → API 호출(A 결과 덮어씀 or 실패)
            # 의 경쟁이 생겨 일부 카메라가 카메라 목록에서 자신을 찾지 못한다.
            # 잠금 안에서: 캐시가 방금 갱신됐으면(만료까지 5초 이상 남음) pop 없이
            # 재사용하고, 그렇지 않으면 pop 후 ITS API 를 직접 재호출한다.
            with _FRESH_URL_LOCK:
                cached = its_helper._cctv_cache.get(self._road_key)   # 현재 캐시 확인
                now    = _time.time()

                # 캐시가 5초 이상 됐으면 항상 강제 무효화 후 ITS API 재호출.
                # ITS URL 토큰은 15~30초 내 만료될 수 있다.
                # 직렬화 잠금(_FRESH_URL_LOCK) 덕분에 "5초 이내 갱신된 캐시"는
                # 다음 카메라가 재사용하므로 API 과다 호출 없이도 신선한 URL을 보장한다.
                # (이전 30초 임계값: 카메라 4-7이 12-28초 된 URL을 받아 만료 → 스트림 열기 실패)
                cache_age = (now - (cached['expires'] - its_helper.CCTV_TTL)) if cached else 999
                if not cached or cache_age > 5:
                    # 캐시가 없거나 5초 이상 됐으면 강제 무효화
                    its_helper._cctv_cache.pop(self._road_key, None)
                else:
                    pass  # 5초 이내 갱신된 캐시 → 재사용 (API 절약)

                # get_cctv_list: 캐시가 살아 있으면 캐시 반환, 없으면 ITS API 호출
                cameras = its_helper.get_cctv_list(self._road_key)

                # camera_id 일치 항목의 URL 추출 (잠금 안에서 race-free 하게 탐색)
                new_url = next(
                    (c['url'] for c in cameras if c['camera_id'] == self.camera_id),
                    None,
                )

            # 잠금 해제 후 결과 적용
            if new_url:
                self.url = new_url   # reconnect() 에서도 최신 URL을 쓸 수 있도록 갱신
                return new_url

            # 목록에 없는 경우 — 카메라가 ITS 에서 잠시 제외됐을 가능성
            print(f"⚠️  [{self.camera_id}] ITS 목록에서 카메라를 찾지 못함 — 기존 URL 유지")

        except Exception as e:
            # 갱신 실패가 전체 모니터링을 중단시켜선 안 된다 → 기존 URL로 계속 시도
            print(f"⚠️  [{self.camera_id}] ITS URL 갱신 실패: {e}")

        return self.url   # 갱신 불가 시 원본 URL 반환

    # ────────────────────────────────────────────────────────────────────
    # 탭 이탈/복귀 시 CPU 절약을 위한 일시정지/재개
    # ────────────────────────────────────────────────────────────────────

    def pause(self):
        """
        AI 추론 루프를 일시정지한다.
        run() 루프가 cap.read/YOLO/emit 없이 gevent.sleep만 실행하게 되어
        CPU 점유가 거의 0% 로 낮아진다.
        학습 완료 상태(flow_map 가중치, TrafficAnalyzer 등)는 메모리에 유지된다.
        """
        self._paused = True
        print(f"⏸️  [{self.camera_id}] 감지기 일시정지 (탭 이탈 — CPU 절약 모드)")

    def resume(self):
        """
        일시정지된 AI 추론 루프를 재개한다.
        run() 루프가 다시 cap.read/YOLO/emit 을 실행하며,
        학습 완료 상태가 그대로 이어진다.
        """
        self._paused = False
        print(f"▶️  [{self.camera_id}] 감지기 재개 (탭 복귀 — 추론 재시작)")

    # ────────────────────────────────────────────────────────────────────
    # BaseDetector 추상 메서드 구현
    # ────────────────────────────────────────────────────────────────────
    def process_alert(self, data):
        """alert_queue에서 꺼낸 역주행 데이터를 DB에 저장한다."""
        track_id, detected_at, display_label = data
        try:
            with self.app.app_context():
                from models import db as db_inst, DetectionResult, ReverseResult
                base = DetectionResult(
                    event_type   = "reverse",
                    address      = self.location or self.cctv_name,
                    latitude     = self.lat,
                    longitude    = self.lng,
                    detected_at  = detected_at,
                    is_simulation= False,
                    video_origin = "monitoring",
                    is_resolved  = False,
                )
                db_inst.session.add(base)
                db_inst.session.flush()
                detail = ReverseResult(
                    result_id    = base.id,
                    vehicle_info = f"track_id={track_id} label={display_label}",
                )
                db_inst.session.add(detail)
                db_inst.session.commit()
                print(f"💾 [{self.camera_id}] 역주행 DB 저장 track_id={track_id}")
        except Exception as e:
            print(f"❌ [{self.camera_id}] 역주행 DB 저장 실패: {e}")

    # ────────────────────────────────────────────────────────────────────
    # 방향 분류 헬퍼 (detector.py 동일 로직)
    # ────────────────────────────────────────────────────────────────────
    def _compute_ref_direction(self):
        """flow_map에서 샘플이 가장 많은 셀의 방향을 기준 벡터로 설정한다."""
        grid = self.flow
        best_r, best_c, best_count = 0, 0, 0
        for r in range(grid.grid_size):
            for c in range(grid.grid_size):
                if grid.count[r, c] > best_count:
                    best_count    = grid.count[r, c]
                    best_r, best_c = r, c
        vx  = float(grid.flow[best_r, best_c, 0])
        vy  = float(grid.flow[best_r, best_c, 1])
        mag = np.sqrt(vx ** 2 + vy ** 2)
        self._ref_direction = (vx / mag, vy / mag) if mag > 1e-6 else (1.0, 0.0)
        # vy 부호로 UP/DOWN 자동 판별
        self._dir_label_a, self._dir_label_b = (
            ("UP", "DOWN") if self._ref_direction[1] < 0 else ("DOWN", "UP")
        )

    def _compute_direction_cell_counts(self):
        """방향별 유효 셀 수를 계산해 TrafficAnalyzer에 주입하고, 화면 좌/우 위치를 판별한다."""
        if self._ref_direction is None:
            return
        ref_x, ref_y   = self._ref_direction
        count_a, count_b = 0, 0
        col_sum_a, col_sum_b = 0, 0   # 각 방향 셀의 컬럼(가로) 좌표 합계
        for r in range(self.flow.grid_size):
            for c in range(self.flow.grid_size):
                if self.flow.count[r, c] <= 0:
                    continue
                vx  = float(self.flow.flow[r, c, 0])
                vy  = float(self.flow.flow[r, c, 1])
                cos = vx * ref_x + vy * ref_y
                if cos >= self.cfg.lane_cos_threshold:
                    count_a   += 1
                    col_sum_a += c   # c가 작을수록 화면 왼쪽
                else:
                    count_b   += 1
                    col_sum_b += c
        self._valid_cells_a = max(count_a, 1)
        self._valid_cells_b = max(count_b, 1)
        if self.traffic_analyzer_a:
            self.traffic_analyzer_a.set_valid_cell_count(self._valid_cells_a)
        if self.traffic_analyzer_b:
            self.traffic_analyzer_b.set_valid_cell_count(self._valid_cells_b)

        # A방향 셀의 평균 컬럼 < B방향 셀의 평균 컬럼 → A가 화면 왼쪽
        avg_col_a = col_sum_a / count_a if count_a > 0 else 0
        avg_col_b = col_sum_b / count_b if count_b > 0 else self.flow.grid_size
        self._dir_a_is_left = avg_col_a < avg_col_b   # True: A=왼쪽, False: B=왼쪽

    def _classify_direction(self, fx, fy) -> str:
        """flow_map 보간 기반 방향 분류 (fallback)."""
        if self._ref_direction is None:
            return 'a'
        flow_v = self.flow.get_interpolated(fx, fy)
        if flow_v is None:
            flow_v = self.flow.get_nearest_direction(fx, fy)
        if flow_v is None:
            return 'a'
        ref_x, ref_y = self._ref_direction
        return 'a' if (flow_v[0] * ref_x + flow_v[1] * ref_y) >= self.cfg.lane_cos_threshold else 'b'

    # ────────────────────────────────────────────────────────────────────
    # Socket.IO emit 헬퍼
    # ────────────────────────────────────────────────────────────────────
    def _worst_level(self) -> str:
        """두 방향 중 더 나쁜 레벨을 반환한다."""
        if not self.traffic_analyzer_a or not self.traffic_analyzer_b:
            return "SMOOTH"
        order = {"SMOOTH": 0, "SLOW": 1, "JAM": 2}
        la = self.traffic_analyzer_a.get_congestion_level()
        lb = self.traffic_analyzer_b.get_congestion_level()
        return la if order.get(la, 0) >= order.get(lb, 0) else lb

    def _emit_traffic_update(self):
        """traffic_update + 필요 시 level_change / anomaly_alert 를 emit한다."""
        if not self.socketio:
            return

        st  = self.state
        cfg = self.cfg
        ta_a = self.traffic_analyzer_a
        ta_b = self.traffic_analyzer_b

        jam_a = ta_a.get_jam_score() if ta_a else 0.0
        jam_b = ta_b.get_jam_score() if ta_b else 0.0
        level = self._worst_level()

        # ── 방향 레이블 기반 상/하행 jam_score 매핑 ──────────────────────────
        # 학습 완료 후 _dir_label_a는 "UP"(상행) 또는 "DOWN"(하행)으로 자동 설정된다.
        # 초기값 "상행"도 UP 취급 — 학습 전 기본 가정(a=상행)을 유지한다.
        # 이 매핑이 없으면 카메라 방향에 따라 a채널이 실제 하행임에도 상행으로 표시된다.
        _a_is_up   = self._dir_label_a in ("UP", "상행")  # a채널이 상행이면 True
        _jam_up    = jam_a if _a_is_up else jam_b          # 실제 상행 jam_score
        _jam_down  = jam_b if _a_is_up else jam_a          # 실제 하행 jam_score
        # 프론트 뱃지 순서용 한국어 레이블 — A방향이 왼쪽, B방향이 오른쪽으로 고정된다.
        # 카메라마다 광학흐름 기준이 다르므로, A의 실제 방향(상행/하행)에 따라 왼쪽 뱃지가 결정된다.
        _dir_label_a_kr = "상행" if _a_is_up else "하행"   # A방향 한국어 레이블
        _dir_label_b_kr = "하행" if _a_is_up else "상행"   # B방향 한국어 레이블

        # learning_progress 계산
        if st.is_learning:
            progress = min(st.frame_num, cfg.learning_frames)
            total    = cfg.learning_frames
        elif st.relearning:
            elapsed  = st.frame_num - st.relearn_start_frame
            progress = min(elapsed, cfg.relearn_frames)
            total    = cfg.relearn_frames
        elif st.waiting_stable:
            progress = total = 0   # 안정 대기 중은 progress 없음
        else:
            progress = total = 0

        vc_a = ta_a._vehicle_count if ta_a else 0
        vc_b = ta_b._vehicle_count if ta_b else 0

        # 방향별 실제 레벨 — _a_is_up 매핑에 따라 상/하행에 올바른 레벨을 할당한다.
        # 히스테리시스가 적용된 값을 그대로 사용하기 위해 TrafficAnalyzer에서 직접 읽는다.
        _level_a = ta_a.get_congestion_level() if ta_a else "SMOOTH"
        _level_b = ta_b.get_congestion_level() if ta_b else "SMOOTH"
        _level_up   = _level_a if _a_is_up else _level_b   # 실제 상행 레벨
        _level_down = _level_b if _a_is_up else _level_a   # 실제 하행 레벨

        payload = {
            "camera_id":         self.camera_id,
            "lat":               self.lat,
            "lng":               self.lng,
            "location":          self.location,
            "level":             level,
            "level_up":          _level_up,              # 상행 방향 정체 레벨 (jam_up 대응)
            "level_down":        _level_down,             # 하행 방향 정체 레벨 (jam_down 대응)
            "dir_label_a":       _dir_label_a_kr,         # A방향 레이블(상행/하행)
            "dir_label_b":       _dir_label_b_kr,         # B방향 레이블(하행/상행)
            "dir_a_is_left":     self._dir_a_is_left,     # A방향이 화면 왼쪽이면 True — 뱃지 순서 결정용
            "level_a":           _level_a,                # A방향(왼쪽 뱃지) 정체 레벨
            "level_b":           _level_b,                # B방향(오른쪽 뱃지) 정체 레벨
            "jam_score":         round((jam_a + jam_b) / 2, 3),
            "jam_up":            round(_jam_up,   3),   # 광학흐름 기반 실제 상행 값
            "jam_down":          round(_jam_down, 3),   # 광학흐름 기반 실제 하행 값
            "jam_a":             round(jam_a, 3),        # A방향(왼쪽 뱃지) jam_score
            "jam_b":             round(jam_b, 3),        # B방향(오른쪽 뱃지) jam_score
            "vehicle_count":     vc_a + vc_b,
            "affected":          (
                (ta_a.get_affected_vehicles() if ta_a else 0) +
                (ta_b.get_affected_vehicles() if ta_b else 0)
            ),
            "occupancy":         round(
                ((ta_a.get_occupancy() if ta_a else 0.0) +
                 (ta_b.get_occupancy() if ta_b else 0.0)) / 2, 2
            ),
            "avg_speed":         round(
                ((ta_a.get_avg_speed() if ta_a else 0.0) +
                 (ta_b.get_avg_speed() if ta_b else 0.0)) / 2, 2
            ),
            "duration_sec":      round(max(
                ta_a.get_duration_sec() if ta_a else 0.0,
                ta_b.get_duration_sec() if ta_b else 0.0
            ), 1),
            "is_learning":       st.is_learning,
            "relearning":        st.relearning,
            "waiting_stable":    st.waiting_stable,
            "learning_progress": progress,
            "learning_total":    total,
            # ── HistoricalPredictor: 5분 후 예측 ──────────────────────────
            # 각 방향의 predict()는 학습 데이터 없으면 None ("Training..." 표시).
            # [{horizon_sec, horizon_min, predicted_level, confidence, jam_score, interpolated}]
            "prediction_a":      self._hist_pred_a.predict() if self._hist_pred_a else None,
            "prediction_b":      self._hist_pred_b.predict() if self._hist_pred_b else None,
        }
        self.socketio.emit('traffic_update', payload)

        # ── 방향별 레벨 전환 감지 ─────────────────────────────────────────
        # 각 방향의 이전 레벨을 독립적으로 추적한다.
        # 기존 단일 _prev_level 방식은 한 방향이 이미 악화된 상태에서
        # 다른 방향이 처음 막히기 시작해도 알림이 발화되지 않는 문제가 있었다.
        la = ta_a.get_congestion_level() if ta_a else "SMOOTH"  # a방향 현재 레벨
        lb = ta_b.get_congestion_level() if ta_b else "SMOOTH"  # b방향 현재 레벨

        # a방향이 상행이면 (label_a=상행, label_b=하행), 아니면 반대
        _label_a = "상행" if _a_is_up else "하행"
        _label_b = "하행" if _a_is_up else "상행"

        # (현재 레벨, 이전 레벨 속성명, 방향 레이블, 해당 방향 jam_score) 쌍으로 순회
        for _cur, _prev_attr, _dir_label, _dir_jam in (
            (la, "_prev_level_a", _label_a, jam_a),
            (lb, "_prev_level_b", _label_b, jam_b),
        ):
            _prev = getattr(self, _prev_attr)
            if _cur == _prev:  # 레벨 변화 없으면 건너뜀
                continue

            # 방향별 레벨 전환 로그 이벤트
            self.socketio.emit('level_change', {
                "camera_id":  self.camera_id,
                "direction":  _dir_label,           # 어느 방향인지 명시
                "from_level": _prev,
                "to_level":   _cur,
                "jam_score":  round(_dir_jam, 3),   # 해당 방향 jam_score
                "timestamp":  datetime.utcnow().isoformat(),
            })

            # SLOW 또는 JAM 진입 시에만 이상 알림 발화
            if _cur in ("SLOW", "JAM"):
                self.socketio.emit('anomaly_alert', {
                    "camera_id":   self.camera_id,
                    "event_type":  "CONGESTION",
                    "level":       _cur,
                    "direction":   _dir_label,       # 어느 방향이 막혔는지
                    "jam_score":   round(_dir_jam, 3),
                    "detected_at": datetime.utcnow().isoformat(),
                    "location":    self.location,
                })

            setattr(self, _prev_attr, _cur)  # 이전 레벨 갱신

        # ── 디버그 정보 갱신 ──
        total_cells = cfg.grid_size ** 2
        learned_cells = int(np.count_nonzero(self.flow.count))
        self.debug_info = {
            "camera_id":         self.camera_id,
            "is_running":        self.is_running,
            "is_learning":       st.is_learning,
            "relearning":        st.relearning,
            "waiting_stable":    st.waiting_stable,
            "learning_progress": f"{progress} / {total}" if total else "완료",
            "frame_num":         st.frame_num,
            "jam_score_a":       round(jam_a, 3),
            "jam_score_b":       round(jam_b, 3),
            "level_a":           ta_a.get_congestion_level() if ta_a else "N/A",
            "level_b":           ta_b.get_congestion_level() if ta_b else "N/A",
            "vehicle_count":     vc_a + vc_b,
            "flow_map_coverage": f"{int(learned_cells / total_cells * 100)}% 셀 학습 완료",
            "yolo_model":        "yolo11n_v2/best.pt",
            "wrongway_ids":      list(st.wrong_way_ids),
        }

    # ────────────────────────────────────────────────────────────────────
    # MJPEG 스트림 (base_detector.generate_frames 오버라이드)
    # ────────────────────────────────────────────────────────────────────
    def generate_frames(self):
        """
        base_detector의 generate_frames()를 오버라이드.
        개선 사항:
          1) _stream_frame_id 비교로 새 프레임이 없으면 인코딩 완전 스킵
          2) 스트림용 640px 다운스케일 → 인코딩 부하 대폭 감소
          3) gevent.sleep으로 20fps 상한 + 이벤트 루프 양보 보장
        """
        _TARGET_INTERVAL = 1.0 / 20   # 20fps 상한
        last_frame_id = -1

        while self.is_running:
            with self.frame_lock:
                frame_id = self._stream_frame_id
                frame    = self.latest_frame

            if frame is not None and frame_id != last_frame_id:
                last_frame_id = frame_id
                frame_copy = frame.copy()

                # 스트림 다운스케일 (트랙 좌표와 동일 비율 사용)
                ss = self._stream_scale
                if ss < 1.0:
                    h, w       = frame_copy.shape[:2]
                    frame_copy = cv2.resize(
                        frame_copy, (int(w * ss), int(h * ss)),
                        interpolation=cv2.INTER_LINEAR,
                    )

                ret, buffer = cv2.imencode(
                    '.jpg', frame_copy, [cv2.IMWRITE_JPEG_QUALITY, 60]
                )
                if ret:
                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' +
                        buffer.tobytes() +
                        b'\r\n'
                    )

            gevent.sleep(_TARGET_INTERVAL)

    # ────────────────────────────────────────────────────────────────────
    # 메인 루프
    # ────────────────────────────────────────────────────────────────────
    def run(self):
        cfg = self.cfg
        st  = self.state
        print(f"🚦 [{self.camera_id}] MonitoringDetector 시작 url={self.url}")

        # ── 스트림 열기 ────────────────────────────────────────────────────
        # 진단 결과: 여러 스레드가 동시에 cv2.VideoCapture(url)를 호출하면
        # OpenCV 백엔드 자동 선택 과정에서 FFMPEG 대신 MSMF/CAP_IMAGES 등이
        # 선택되어 HTTP(HLS) URL 열기에 실패한다.
        # 해결: _open_http_cap()을 통해 cv2.CAP_FFMPEG 명시 + _CAP_OPEN_LOCK 직렬화.
        is_rtsp = self.url.lower().startswith(('rtsp://', 'rtsps://'))

        if is_rtsp:
            # RTSP: FFMPEG 백엔드 강제 + 버퍼 최소화 → thread pool에서 열어도 무방
            self.cap = _FRAME_POOL.apply(lambda: _open_rtsp_cap(self.url))
        else:
            # HTTP/HLS: VideoCapture 직전에 ITS URL 토큰을 갱신한다.
            # YOLO 모델 로드 시간(수 초) 동안 ITS 시간제한 토큰이 만료되어
            # cv2.VideoCapture() 가 HTTP 403을 받아 실패하는 것을 방지한다.
            self.url  = self._get_fresh_url()
            # FFMPEG 명시 + 직렬화 잠금으로 멀티스레드 백엔드 선택 문제도 함께 해결
            self.cap = _open_http_cap(self.url)

        if not self.cap.isOpened():
            print(f"❌ [{self.camera_id}] 스트림 열기 실패: {self.url}")

            # ── 진단: HTTP 탐침으로 실패 원인 추적 ──────────────────────────
            # cv2.VideoCapture 가 실패한 이유를 알기 위해 HTTP 수준에서 URL 을 탐침한다.
            # 결과를 보고 아래 중 어느 케이스인지 판단한다:
            #   [케이스 A] http_error 있음        → URL 자체에 접근 불가 (서버 다운 / DNS)
            #   [케이스 B] http_status 403/404    → 토큰 만료 또는 잘못된 URL
            #   [케이스 C] http_status 200, m3u8  → HLS 플레이리스트. FFMPEG 설정 문제
            #   [케이스 D] http_status 200, mpegts → MPEG-TS 직접 스트림. cv2 백엔드 문제
            try:
                from modules.monitoring.its_helper import probe_stream_url as _probe
                _p = _probe(self.url)
                # HTTP 상태와 포맷을 한 줄로 출력해 원인 추적을 돕는다
                if 'http_error' in _p:
                    print(f"   🔍 [PROBE] HTTP 접근 자체 실패: {_p['http_error']}")
                    print(f"   → 케이스 A: ITS 서버 다운 또는 URL 자체 오류")
                else:
                    print(
                        f"   🔍 [PROBE] HTTP {_p.get('http_status')} | "
                        f"Content-Type: {_p.get('content_type')} | "
                        f"Format: {_p.get('stream_format')} | "
                        f"첫바이트: {_p.get('first_bytes_hex', '')[:8]}..."
                    )
                    status = _p.get('http_status', 0)
                    fmt    = _p.get('stream_format', 'unknown')
                    if status in (403, 401):
                        print(f"   → 케이스 B: 토큰 만료 또는 인증 실패 (HTTP {status})")
                    elif status == 404:
                        print(f"   → 케이스 B: 카메라 URL 없음 (HTTP 404)")
                    elif status == 200 and fmt == 'm3u8':
                        print(f"   → 케이스 C: HLS m3u8 플레이리스트 확인됨 → FFMPEG 설정 문제")
                    elif status == 200 and fmt == 'mpegts':
                        print(f"   → 케이스 D: MPEG-TS 직접 스트림 확인됨 → cv2 백엔드 문제")
                    elif status == 200:
                        print(f"   → 케이스 D (미확인 포맷): HTTP 200 이지만 cv2 열기 실패")
                    else:
                        print(f"   → 케이스 미확인: HTTP {status}")
            except Exception as _probe_exc:
                # 탐침 자체가 실패해도 감지기 종료 흐름에는 영향 없음
                print(f"   🔍 [PROBE] 탐침 중 오류: {_probe_exc}")

            return

        fw  = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        fh  = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        st.frame_w, st.frame_h, st.video_fps = fw, fh, fps
        self.flow.init_grid(fw, fh)

        # 스트림 다운스케일 비율 확정 (640px 상한)
        self._stream_scale = min(1.0, 640 / fw) if fw > 640 else 1.0

        # ── TrafficAnalyzer ×2 초기화 (Rule 기반 단독, GRU 제거) ────
        self.traffic_analyzer_a = TrafficAnalyzer(
            cfg, frame_w=fw, frame_h=fh, fps=fps, flow_map=self.flow
        )
        self.traffic_analyzer_a.set_state(st)

        self.traffic_analyzer_b = TrafficAnalyzer(
            cfg, frame_w=fw, frame_h=fh, fps=fps, flow_map=self.flow
        )
        self.traffic_analyzer_b.set_state(st)

        # ── HistoricalPredictor ×2 초기화 (시각별 5분 후 예측) ───────
        # 현재는 메모리에만 슬롯 데이터를 보관한다 (재시작 시 초기화).
        # 영속 저장은 추후 DB 연동으로 구현한다.
        self._hist_pred_a = HistoricalPredictor(
            smooth_threshold=cfg.smooth_jam_threshold,   # SMOOTH 경계값 (0.25)
            slow_threshold=cfg.slow_jam_threshold,       # JAM 경계값 (0.60)
        )
        self._hist_pred_b = HistoricalPredictor(
            smooth_threshold=cfg.smooth_jam_threshold,
            slow_threshold=cfg.slow_jam_threshold,
        )

        self.predictor_a = CongestionPredictor(cfg, fps=fps)
        self.predictor_b = CongestionPredictor(cfg, fps=fps)

        # ── 캐시 탐색: 첫 프레임으로 저장된 flow_map 재사용 여부 결정 ─────
        # init_grid() 이후에 호출해야 cell_w/cell_h 가 올바르게 설정된다.
        # (init_grid() 전 호출 시 cell_w=1.0, cell_h=1.0 → 좌표 계산 전부 오류)
        # OS 스레드 풀에서 첫 프레임을 읽어 매칭에 사용한다.
        _cache_frame_ok, _cache_frame = _FRAME_POOL.apply(self.cap.read)
        if _cache_frame_ok:
            # 첫 프레임을 스트림에 즉시 반영 (generate_frames 가 빈 화면 안 보이게)
            with self.frame_lock:
                self.latest_frame      = _cache_frame
                self._stream_frame_id += 1
            # 첫 프레임으로 캐시 탐색 (예외는 _try_load_cache 내부에서 처리)
            _cache_hit = self._try_load_cache(_cache_frame)
        else:
            # 첫 프레임 읽기 실패 → 캐시 탐색 불가, 학습 모드로 진행
            _cache_hit = False
            print(f"⚠️  [{self.camera_id}] 첫 프레임 읽기 실패 → 캐시 탐색 건너뜀")

        # 캐시 히트 여부에 따라 시작 모드 결정
        if _cache_hit:
            # 캐시 히트 → 탐지 모드로 바로 진입 (학습 생략)
            st.is_learning = False
            # FeatureExtractor._ready / CongestionJudge._baseline_set 를 활성화한다.
            # set_baseline() 을 호출하지 않으면 두 플래그가 False 상태로 남아
            # feature_extractor.compute() 가 None 을 반환해 jam_score 가 항상 0이 된다.
            self.traffic_analyzer_a.set_baseline()
            self.traffic_analyzer_b.set_baseline()
        else:
            # 캐시 미스 → 기존대로 학습 모드 시작
            st.is_learning = True
            self.traffic_analyzer_a.set_baseline()
            self.traffic_analyzer_b.set_baseline()

        max_learn = int(cfg.learning_frames * cfg.max_learning_extension)
        prev_active_ids   = set()
        last_footpoints   = {}
        _learn_smooth_80  = False
        _learn_smooth_95  = False
        _relearn_smooth_80 = False
        _relearn_smooth_95 = False

        # ── 프레임 스킵 감지 변수 ────────────────────────────────────────
        _proc_fps_samples = []
        _proc_fps_win     = 30
        _last_frame_time  = time.time()
        _base_jump_px     = getattr(cfg, 'frame_skip_jump_px', 80.0)
        _jump_thr_dynamic = _base_jump_px

        # ── timestamp gap 감지 변수 ───────────────────────────────────────
        # CAP_PROP_POS_MSEC 기반: 1~3프레임 partial drop 시 jump 임계값 확대
        # _prev_cap_ts_ms: 직전 프레임 스트림 타임스탬프 (ms) — 첫 프레임은 None
        # _is_time_gap: 이번 프레임이 타임스탬프 갭 직후이면 True
        _prev_cap_ts_ms  = None  # 직전 프레임 타임스탬프 (ms), 첫 프레임에는 미정
        _is_time_gap     = False  # 타임스탬프 갭 플래그 (partial drop 감지)

        # ── 로그 노이즈 억제 변수 ────────────────────────────────────────
        # 학습 진행률 마일스톤: 이미 출력한 10% 단위 % 값을 저장해 중복 출력 방지
        _learn_logged_pcts:   set = set()   # 초기 학습 마일스톤 (10, 20, ..., 100)
        _relearn_logged_pcts: set = set()   # 재학습 마일스톤
        # 프레임 스킵 쿨타임: 마지막으로 스킵 로그를 찍은 프레임 번호
        _last_skip_log_frame: int = -_SKIP_LOG_COOL   # 초기값 → 첫 감지 시 바로 출력

        # 캐시 히트 여부에 따라 시작 모드 로그 출력
        if st.is_learning:
            print(f"📚 [{self.camera_id}] 학습 모드 시작 (목표: {cfg.learning_frames}프레임 ≈ {cfg.learning_frames/fps:.0f}초)")
        else:
            print(f"🔍 [{self.camera_id}] 탐지 모드로 시작 (캐시 히트 — 학습 생략)")

        # ── 메인 루프 ────────────────────────────────────────────────
        while self.is_running and self.cap.isOpened():
            # 일시정지 상태이면 프레임 읽기/YOLO 추론/emit 을 전부 건너뛴다.
            # gevent.sleep 으로 이벤트 루프를 양보해 소켓 하트비트 등은 계속 처리된다.
            # 학습 완료 상태(flow_map, TrafficAnalyzer 등)는 메모리에 그대로 유지됨.
            if self._paused:
                gevent.sleep(0.3)  # 0.3초 대기 후 루프 재확인 (CPU 점유 없음)
                continue

            # ── [진단] cap.read() 소요 시간 측정 ────────────────────────────
            # FFMPEG HLS 타임아웃(30초)이 발생하면 이 값이 급등한다.
            # → _diag['read_max_ms'] 가 29000ms 이상이면 타임아웃 발생 확인
            _read_t0 = time.time()

            # cap.read(): FFMPEG C 코드가 HLS 세그먼트 다운로드 시 수십 초 블로킹.
            # OS 스레드에서 실행해 gevent 이벤트 루프(소켓 하트비트·MJPEG 스트림)를 보호.
            success, frame = _FRAME_POOL.apply(self.cap.read)

            # cap.read() 소요 시간 갱신 (진단 목적)
            _read_ms = (time.time() - _read_t0) * 1000
            self._diag['read_last_ms']  = round(_read_ms, 1)
            self._diag['read_max_ms']   = round(max(self._diag.get('read_max_ms', 0), _read_ms), 1)

            # 5초 이상 걸린 read → 경고 로그 (타임아웃 임박 징후)
            if _read_ms > 5000:
                print(
                    f"⚠️ [DIAG][{self.camera_id}] cap.read 지연 {_read_ms:.0f}ms "
                    f"(타임아웃 임박 가능성)"
                )

            if not success:
                # ── [진단] reconnect 호출 기록 ───────────────────────────────
                self._diag['reconnect_count'] = self._diag.get('reconnect_count', 0) + 1
                self._diag['reconnect_last_at'] = datetime.utcnow().isoformat()
                reconnected = self.reconnect(delay=3, max_retries=5)
                if not reconnected:
                    gevent.sleep(10)
                continue

            # ── [진단] 정상 프레임 수신 시각 갱신 ──────────────────────────
            self._diag['last_frame_ok_at'] = datetime.utcnow().isoformat()

            with self.frame_lock:
                self.latest_frame      = frame
                self._stream_frame_id += 1

            st.frame_num += 1

            # ── 실제 처리 fps 측정 및 jump 임계값 동적 갱신 ────────────
            _now = time.time()
            _proc_fps_samples.append(_now - _last_frame_time)
            _last_frame_time = _now
            if len(_proc_fps_samples) > _proc_fps_win:
                _proc_fps_samples.pop(0)
            if len(_proc_fps_samples) >= 5:
                _avg_interval = sum(_proc_fps_samples) / len(_proc_fps_samples)
                _proc_fps = 1.0 / max(_avg_interval, 0.01)
                _scale = max(1.0, fps / max(_proc_fps, 1.0))
                # ITS CCTV 는 실제 6fps 인데 OpenCV 가 fps=30 을 리포트해
                # scale=5, threshold=400px 이 되는 문제 방지.
                # 200px 상한 = 차량이 1프레임에 화면 너비의 ~31% 를 이동해야 감지 → 충분한 여유.
                _jump_thr_dynamic = min(_base_jump_px * min(_scale, 5.0),
                                        getattr(cfg, 'frame_skip_jump_px_max', 200.0))

            # ── CAP_PROP_POS_MSEC 기반 timestamp gap 감지 ────────────────────
            # 1~3프레임 partial drop 시: adj_diff는 정상(다른 장면이므로),
            # 차량 displacement는 정상 범위 내일 수 있지만 시간 갭이 발생.
            # 갭 감지 시: solo_jump 임계값을 시간 비율만큼 확대하여 정상 이동을
            # jump로 오판하는 것을 방지 + 속도 벡터에 갭 보정 적용.
            _cur_cap_ts_ms  = self.cap.get(cv2.CAP_PROP_POS_MSEC)  # 현재 프레임 스트림 타임스탬프 (ms)
            _time_gap_ratio = 1.0  # 기본값: 갭 없음 (비율 1.0 = 정상)
            _is_time_gap    = False  # 갭 플래그 초기화 (매 프레임 갱신)
            if _prev_cap_ts_ms is not None and _cur_cap_ts_ms > 0:
                _ts_delta_ms  = _cur_cap_ts_ms - _prev_cap_ts_ms  # 프레임 간 실제 시간 차이 (ms)
                _expected_ms  = 1000.0 / max(fps, 1.0)  # 예상 프레임 간격 (ms) — fps 기반
                if _expected_ms > 0 and _ts_delta_ms > 0:
                    _time_gap_ratio = _ts_delta_ms / _expected_ms  # 실제/예상 비율 (1.0 = 정상)
                    if _time_gap_ratio > 2.5 and _ts_delta_ms > 400:  # 2.5배 이상 + 0.4초 이상
                        _is_time_gap = True  # partial drop 확인 → jump 임계값 확대
            _prev_cap_ts_ms = _cur_cap_ts_ms  # 다음 프레임 비교용 저장

            # YOLO+ByteTrack: 추론도 C 익스텐션 블로킹 → OS 스레드로 실행
            tracks = _FRAME_POOL.apply(self.tracker.track, (frame,))
            active_ids = {t["id"] for t in tracks}

            for t in tracks:
                if t["id"] not in st.first_seen_frame:
                    st.first_seen_frame[t["id"]] = st.frame_num

            # ── 프레임 스킵(신호 끊김) 감지 ──────────────────────────────
            # HLS 스트림 끊김 시 모든 차량이 동시에 큰 변위를 가짐
            # → 절반 이상이 jump_px 초과 시 해당 프레임의 궤적·학습·판정 전부 스킵
            _jump_thr   = _jump_thr_dynamic
            _jump_ratio = getattr(cfg, 'frame_skip_ratio', 0.5)
            _jump_count = 0
            _jump_total = 0
            for _t in tracks:
                _tid = _t["id"]
                _traj = st.trajectories.get(_tid)
                if _traj:
                    _dx = _t["cx"] - _traj[-1][0]
                    _dy = _t["cy"] - _traj[-1][1]
                    _dist = (_dx**2 + _dy**2) ** 0.5
                    _jump_total += 1
                    if _dist > _jump_thr:
                        _jump_count += 1
            _is_frame_skip = (
                _jump_total >= 2
                and _jump_count / _jump_total >= _jump_ratio
            )
            if _is_frame_skip:
                # 쿨타임(_SKIP_LOG_COOL) 이내 중복 출력 방지 — HLS 끊김이 연속될 때 터미널 도배 억제
                if st.frame_num - _last_skip_log_frame >= _SKIP_LOG_COOL:
                    print(f"[{self.camera_id}] ⚠️ 프레임 스킵 감지 ({_jump_count}/{_jump_total}대 jump) → 스킵")
                    _last_skip_log_frame = st.frame_num
                # 전역 리셋 헬퍼 호출:
                # post_reconnect_frame 포함 모든 상태 초기화 (Bug #1 수정)
                _apply_frame_skip_reset(st, tracks, st.frame_num)

            # ── 카메라 전환 감지 (3-state 상태 머신) ──────────────────────
            # 탐지 중 → (전환 감지) → waiting_stable → (안정 확인) → 재학습 → 탐지 중
            # 재학습 중 또 흔들리면 → waiting_stable 복귀 (잘못된 흐름 학습 방지)
            _stability_required_frames = int(getattr(cfg, 'stability_required_sec', 4.0) * fps)
            _stability_thr = getattr(cfg, 'stability_diff_threshold', 8.0)
            _relearn_abort = getattr(cfg, 'relearn_abort_diff', 15.0)

            if not st.is_learning:
                # (A) 탐지 중: 전환 감지 → waiting_stable 진입
                if not st.relearning and not st.waiting_stable:
                    if self.switch.check(frame, st.frame_num, st.cooldown_until):
                        print(f"📷 [{self.camera_id}] 카메라 전환 감지 → 화면 안정 대기 중...")
                        st.waiting_stable = True
                        st.stable_since_frame = st.frame_num
                        # waiting_stable 최초 진입 시각만 기록한다 (재연결 반복 시 리셋 방지)
                        if st.waiting_stable_entered_frame == 0:
                            st.waiting_stable_entered_frame = st.frame_num
                        self._track_direction.clear()

                # (B) 안정 대기 중: diff 모니터링 → 안정되면 재학습 시작
                elif st.waiting_stable:
                    self.switch.check(frame, st.frame_num, st.cooldown_until)
                    _cur_diff = self.switch.last_adj_diff
                    if _cur_diff > _stability_thr:
                        st.stable_since_frame = st.frame_num   # 아직 불안정 → 타이머 리셋
                    else:
                        stable_frames = st.frame_num - st.stable_since_frame
                        if stable_frames >= _stability_required_frames:
                            print(f"✅ [{self.camera_id}] 화면 안정 확인 ({stable_frames}프레임) → 재학습 시작")
                            st.waiting_stable = False
                            self._prev_ref_direction = self._ref_direction   # 재학습 전 방향 저장 (반전 감지용)
                            st.reset_for_relearn()
                            self.flow.reset()
                            self.traffic_analyzer_a.congestion_judge.reset()
                            self.traffic_analyzer_b.congestion_judge.reset()
                            self._ref_direction = None
                            _relearn_smooth_80 = _relearn_smooth_95 = False
                            _relearn_logged_pcts = set()   # 재학습 마일스톤 초기화

                # (C) 재학습 중: 또 흔들리면 중단 → 대기 복귀
                elif st.relearning:
                    self.switch.check(frame, st.frame_num, st.cooldown_until)
                    _cur_diff = self.switch.last_adj_diff
                    if _cur_diff > _relearn_abort:
                        print(f"⚠️ [{self.camera_id}] 재학습 중 화면 불안정 (diff={_cur_diff:.1f}) → 중단, 안정 대기 복귀")
                        st.relearning = False
                        st.waiting_stable = True
                        st.stable_since_frame = st.frame_num
                        # waiting_stable 최초 진입 시각만 기록 (재연결 반복 시 리셋 방지)
                        if st.waiting_stable_entered_frame == 0:
                            st.waiting_stable_entered_frame = st.frame_num
                        self.flow.reset()
                        _relearn_smooth_80 = _relearn_smooth_95 = False

            # ── 초기 학습 완료 처리 ──
            if st.is_learning:
                ratio = st.frame_num / cfg.learning_frames
                if not _learn_smooth_80 and ratio >= 0.80:
                    self.flow.apply_spatial_smoothing(verbose=False)
                    _learn_smooth_80 = True
                if not _learn_smooth_95 and ratio >= 0.95:
                    self.flow.apply_spatial_smoothing(verbose=False)
                    _learn_smooth_95 = True
                if st.frame_num >= cfg.learning_frames or st.frame_num >= max_learn:
                    self.flow.apply_spatial_smoothing(verbose=True)
                    gevent.sleep(0)   # heavy numpy → 다른 그린렛에 양보
                    self.flow.apply_boundary_erosion()
                    gevent.sleep(0)
                    self._compute_ref_direction()
                    gevent.sleep(0)
                    self._compute_direction_cell_counts()
                    # A/B 양방향 채널을 분리 빌드 → get_interpolated(direction='a'/'b') 활성화
                    # 반대 차선 벡터가 섞이지 않도록 채널을 미리 계산해 두어야 한다
                    # _compute_ref_direction() 이후이므로 self._ref_direction 이 항상 유효
                    _rd = self._ref_direction or (1.0, 0.0)   # None 방어 (초기화 실패 대비)
                    self.flow.build_directional_channels(_rd[0], _rd[1])
                    gevent.sleep(0)
                    st.is_learning = False
                    print(f"✅ [{self.camera_id}] 초기 학습 완료! frame={st.frame_num}")
                    # 학습 결과를 디스크에 저장 → 다음 서버 시작 시 재사용
                    # 예외는 _save_cache 내부에서 처리하므로 run() 은 계속 동작
                    self._save_cache(frame)

            # ── 재학습 완료 처리 ──
            if st.relearning:
                elapsed   = st.frame_num - st.relearn_start_frame
                max_relearn = int(cfg.relearn_frames * cfg.max_learning_extension)
                ratio     = elapsed / cfg.relearn_frames
                if not _relearn_smooth_80 and ratio >= 0.80:
                    self.flow.apply_spatial_smoothing(verbose=False)
                    _relearn_smooth_80 = True
                if not _relearn_smooth_95 and ratio >= 0.95:
                    self.flow.apply_spatial_smoothing(verbose=False)
                    _relearn_smooth_95 = True
                if elapsed >= cfg.relearn_frames or elapsed >= max_relearn:
                    self.flow.apply_spatial_smoothing(verbose=True)
                    gevent.sleep(0)   # heavy numpy → 다른 그린렛에 양보
                    self.flow.apply_boundary_erosion()
                    gevent.sleep(0)
                    self._compute_ref_direction()
                    gevent.sleep(0)
                    self._compute_direction_cell_counts()
                    # 재학습 후에도 A/B 채널을 새로 빌드 → 방향 분류 정확도 유지
                    _rd = self._ref_direction or (1.0, 0.0)   # None 방어
                    self.flow.build_directional_channels(_rd[0], _rd[1])
                    gevent.sleep(0)
                    # ── 방향 반전 감지 → HistoricalPredictor 슬롯 스왑 ──────────────────
                    # 재학습 전후 기준 방향 벡터 dot product < -0.5 → 카메라 180° 회전
                    # a/b 예측기의 누적 데이터를 교환해 방향 레이블을 올바르게 유지
                    if (self._prev_ref_direction is not None
                            and self._ref_direction is not None
                            and self._hist_pred_a is not None):
                        _dot = (self._prev_ref_direction[0] * self._ref_direction[0]
                                + self._prev_ref_direction[1] * self._ref_direction[1])
                        if _dot < -0.5:                     # dot < -0.5 → 방향 반전 감지
                            self._hist_pred_a.swap_slots_with(self._hist_pred_b)
                    self._prev_ref_direction = None          # 사용 후 초기화
                    st.relearning                = False
                    st.waiting_stable_entered_frame = 0   # 재학습 완료 → 진입 프레임 리셋
                    st.cooldown_until            = st.frame_num + cfg.cooldown_frames
                    self.switch.set_reference(frame)
                    print(f"✅ [{self.camera_id}] 재학습 완료!")
                    # 재학습 결과도 저장 → 카메라 전환 후 새 화면을 캐시로 보존
                    self._save_cache(frame)

            # ── 차량별 속도·방향 처리 ──
            speeds             = {}
            current_tracks_info = []

            for t in tracks:
                tid          = t["id"]
                x1, y1, x2, y2 = t["x1"], t["y1"], t["x2"], t["y2"]
                cx, cy       = t["cx"], t["cy"]
                fx, fy       = cx, cy
                last_footpoints[tid] = (fx, fy)

                # 방향 분류 (학습 완료 후, flow_map 기반 fallback)
                if (not st.is_learning and not st.relearning and not st.waiting_stable
                        and self._ref_direction is not None):
                    traj_cur = st.trajectories[tid]
                    win      = min(cfg.velocity_window, len(traj_cur))
                    if win >= 3:
                        ddx  = traj_cur[-1][0] - traj_cur[-win][0]
                        ddy  = traj_cur[-1][1] - traj_cur[-win][1]
                        dmag = np.sqrt(ddx**2 + ddy**2)
                        if dmag > 1.0:
                            ref_x, ref_y = self._ref_direction
                            cos_d = (ddx / dmag) * ref_x + (ddy / dmag) * ref_y
                            self._track_direction[tid] = (
                                'a' if cos_d >= cfg.lane_cos_threshold else 'b'
                            )
                        else:
                            self._track_direction[tid] = self._classify_direction(fx, fy)
                    else:
                        self._track_direction[tid] = self._classify_direction(fx, fy)

                # ID 재매칭 (탐지 모드에서만)
                if not st.is_learning and not st.relearning and not st.waiting_stable:
                    self.idm.check_reappear(tid, cx, cy)

                # ── 개별 차량 단독 jump 체크 (프레임 스킵 미감지 시에도 1대가 튀는 경우) ──
                _solo_jump = False
                if st.trajectories[tid]:
                    _prev_fx, _prev_fy = st.trajectories[tid][-1]                    # 직전 위치
                    _solo_dist = ((fx - _prev_fx)**2 + (fy - _prev_fy)**2) ** 0.5   # 변위 거리
                    if _solo_dist > _jump_thr * 1.5:   # 단독 jump는 더 엄격한 기준 (전역 스킵의 1.5배)
                        _solo_jump = True
                        # 단독 리셋 헬퍼 호출:
                        # post_reconnect_frame 포함 해당 차량 상태 초기화 (Bug #2 수정)
                        _apply_solo_jump_reset(st, tid, (fx, fy), st.frame_num)

                # 궤적 갱신 (3프레임 이상 된 트랙만, EMA 스무딩 적용, 스킵 시 건너뜀)
                age = st.frame_num - st.first_seen_frame.get(tid, st.frame_num)
                if age >= 3 and not _is_frame_skip and not _solo_jump:
                    traj_hist = st.trajectories[tid]
                    if traj_hist:
                        px, py = traj_hist[-1]
                        fx = 0.4 * fx + 0.6 * px   # EMA: 현재 40% + 직전 60%
                        fy = 0.4 * fy + 0.6 * py
                    st.trajectories[tid].append((fx, fy))
                if len(st.trajectories[tid]) > cfg.trail_length:
                    st.trajectories[tid].pop(0)

                traj     = st.trajectories[tid]
                speed    = 0
                ndx, ndy = 0.0, 0.0
                is_wrong = False

                # ── 속도 계산 (velocity_window 이상 궤적 있을 때) ──
                # endpoint-to-endpoint 대신 per-frame 변위 중앙값을 사용.
                # 단일 프레임 끊김·순간이동이 있어도 중앙값은 영향 없음.
                # IQR 이상치 필터 추가: partial drop 후 궤적에 남은 이상 변위 제거.
                # 2~3프레임 연속 드롭 시 velocity_window 내 이상치 비율 20~30%가 돼
                # 중앙값이 이상치 방향으로 편향될 수 있음 → IQR로 방어.
                if len(traj) >= cfg.velocity_window:
                    _w   = cfg.velocity_window  # 속도 계산 윈도우 크기
                    _si  = len(traj) - _w  # 윈도우 시작 인덱스
                    # per-frame 변위 리스트: 인접 포인트 간 x/y 차이
                    _pfx = [traj[_si+i+1][0] - traj[_si+i][0] for i in range(_w-1)]
                    _pfy = [traj[_si+i+1][1] - traj[_si+i][1] for i in range(_w-1)]

                    # IQR 이상치 필터: per-frame 변위 크기의 Q1~Q3 범위 밖 제거
                    _pf_mags = [(_pfx[i]**2 + _pfy[i]**2)**0.5 for i in range(len(_pfx))]
                    if len(_pf_mags) >= 5:  # 충분한 샘플 수일 때만 IQR 적용
                        _q1    = float(np.percentile(_pf_mags, 25))  # 1사분위수
                        _q3    = float(np.percentile(_pf_mags, 75))  # 3사분위수
                        _iqr   = _q3 - _q1  # IQR (사분위 범위)
                        _upper = _q3 + 2.0 * _iqr  # 상한 (2×IQR — 보수적)
                        if _upper > 0:  # 유효한 상한이 있을 때만 필터 적용
                            _keep = [i for i in range(len(_pfx)) if _pf_mags[i] <= _upper]
                            if len(_keep) >= 3:  # 필터 후 최소 3개 남아야 적용
                                _pfx = [_pfx[i] for i in _keep]  # 이상치 제거된 x 변위
                                _pfy = [_pfy[i] for i in _keep]  # 이상치 제거된 y 변위

                    # 중앙값 속도 벡터: 중앙값 × 창 크기 (mag 단위 유지)
                    vdx = float(np.median(_pfx)) * (_w - 1)
                    vdy = float(np.median(_pfy)) * (_w - 1)
                    mag = np.sqrt(vdx**2 + vdy**2)  # 속도 크기 (픽셀)
                    speeds[tid] = mag  # feature_extractor 에서 nm 계산에 사용

                    # 속도 벡터 기반 방향 override (더 정확)
                    if (not st.is_learning and not st.relearning
                            and self._ref_direction is not None and mag > 1.0):
                        vn_x, vn_y = vdx / mag, vdy / mag
                        ref_x, ref_y = self._ref_direction
                        cos_v = vn_x * ref_x + vn_y * ref_y
                        self._track_direction[tid] = (
                            'a' if cos_v >= cfg.lane_cos_threshold else 'b'
                        )

                    bh     = max(y2 - y1, cfg.min_bbox_h)
                    nm_move = mag / bh
                    if nm_move > cfg.norm_learn_threshold and mag > 1.0:
                        ndx, ndy = vdx / mag, vdy / mag
                        speed    = mag
                        speeds[tid] = speed

                        if _is_frame_skip or _solo_jump:
                            pass   # 프레임 스킵·단독 jump → 학습/판정 스킵
                        elif st.is_learning or st.relearning:
                            # FlowMap 학습
                            # bbox=(x1,y1,x2,y2): bbox 풋프린트 전체를 학습에 활용 (v4)
                            # traj_ndx/traj_ndy: 방향 게이팅·반대 차선 침범 방지에 사용
                            learn_min_mag = max(1.0, bh * cfg.norm_learn_threshold)
                            self.flow.learn_step(
                                traj[-cfg.velocity_window][0],
                                traj[-cfg.velocity_window][1],
                                fx, fy, learn_min_mag,
                                bbox=(x1, y1, x2, y2),   # v4: 박스 풋프린트 학습
                                traj_ndx=ndx,             # v4: 이동 방향 x (정규화)
                                traj_ndy=ndy,             # v4: 이동 방향 y (정규화)
                            )
                        elif not st.waiting_stable:
                            # 역주행 판정 (탐지 모드, 안정 대기 중이 아닐 때만)
                            bbox_h = max(y2 - y1, 1)
                            # judge.check() 호출 전 확정 여부 기록
                            # → 이웃 가드는 이번 프레임에 새로 확정된 차량에만 적용
                            #   (이미 확정된 차량은 debug_info에 global_cos가 없어 매 프레임 취소되는 루프 방지)
                            _was_confirmed_before = (tid in st.wrong_way_ids)
                            # track_dir: A/B 채널 구분값 ('a'/'b') → 반대 차선 벡터 오염 방지
                            is_wrong, _, debug_info = self.judge.check(
                                tid, traj, ndx, ndy, mag, cy, bbox_h,
                                track_dir=self._track_direction.get(tid),
                            )

                            # ── 이웃 차량 방향 일치 확인 (neighbor_agreement_guard) ────────
                            # 진짜 역주행: 이 차량만 반대 방향, 같은 분류 이웃은 정방향
                            # flow map 오탐: 같은 분류 이웃 차량들도 동일 방향으로 이동 중
                            # → 이웃 N대 이상이 같은 방향이면 flow map 오류로 판단 → 확정 취소
                            #
                            # 적용 조건:
                            # ① 이번 프레임에 새로 확정된 경우만 (_was_confirmed_before=False)
                            # ② global_cos < -0.8이면 강한 flow 증거 → 가드 bypass
                            _nbr_min   = getattr(cfg, "neighbor_guard_min_total", 3)   # 최소 이웃 수
                            _nbr_agree = getattr(cfg, "neighbor_guard_agree",     2)   # 동방향 이웃 수 기준
                            _sus_dir   = self._track_direction.get(tid)                # 의심 차량 방향 분류
                            _gc        = debug_info.get("global_cos")                  # 전체 궤적 cos
                            _has_strong_flow  = (_gc is not None and _gc < -0.8)       # 강한 flow 증거 여부
                            _newly_confirmed  = is_wrong and not _was_confirmed_before  # 이번 프레임 신규 확정 여부
                            if (_newly_confirmed
                                    and (ndx != 0.0 or ndy != 0.0)        # 이동 방향 있을 때만
                                    and _sus_dir is not None               # 방향 분류된 차량만
                                    and not _has_strong_flow):             # 강한 flow 증거 없을 때만
                                _same_dir  = 0    # 의심 차량과 같은 방향으로 달리는 이웃 수
                                _total_nbr = 0    # 같은 방향 분류 이웃 총 수
                                for _ov, _ovv in st.last_velocity.items():
                                    if _ov == tid or _ov in st.wrong_way_ids:
                                        continue   # 자기 자신 및 확정 역주행 차량 제외
                                    if self._track_direction.get(_ov) != _sus_dir:
                                        continue   # 같은 방향 분류 차량만 비교
                                    _total_nbr += 1
                                    if float(ndx * _ovv[0] + ndy * _ovv[1]) > 0.5:
                                        _same_dir += 1   # 의심 차량과 같은 방향 → 카운트
                                if _total_nbr >= _nbr_min and _same_dir >= _nbr_agree:
                                    # 이웃 다수가 같은 방향 → flow map 오류로 판단 → 취소
                                    st.wrong_way_ids.discard(tid)
                                    st.wrong_way_count[tid]       = 0
                                    st.first_suspect_frame.pop(tid, None)
                                    # lcf 갱신: fast-track이 즉시 재확정하는 루프 방지
                                    # (lcf > age_gate_end → _ft_lcf_ok=False → guard_frames 동안 차단)
                                    st.last_correct_frame[tid] = st.frame_num
                                    is_wrong = False
                                    # ── cascade reset: 의심 누적 중인 같은 방향 이웃도 초기화 ──
                                    # W1 취소 직후 W2·W3이 연속 확정되는 패턴 방지
                                    for _ov2, _ovv2 in list(st.last_velocity.items()):
                                        if _ov2 == tid or _ov2 in st.wrong_way_ids:
                                            continue
                                        if self._track_direction.get(_ov2) != _sus_dir:
                                            continue
                                        if float(ndx * _ovv2[0] + ndy * _ovv2[1]) > 0.5:
                                            if st.wrong_way_count.get(_ov2, 0) > 0:
                                                st.wrong_way_count[_ov2] = 0
                                                st.first_suspect_frame.pop(_ov2, None)

                            if is_wrong and tid in st.wrong_way_ids:
                                self.idm.assign_label(tid)   # W1, W2... 라벨 배정
                else:
                    # 궤적 짧아도 이미 확정된 역주행이면 플래그 유지
                    if tid in st.wrong_way_ids:
                        is_wrong = True

                # ── 역주행 신규 탐지 → Socket.IO emit + DB 저장 예약 ──
                if tid in st.wrong_way_ids and tid not in self._wrongway_alerted:
                    self._wrongway_alerted.add(tid)
                    label = self.idm.get_display_label(tid) or str(tid)
                    self.alert_queue.put((tid, datetime.now(), label))
                    if self.socketio:
                        self.socketio.emit('wrongway_alert', {
                            "camera_id":   self.camera_id,
                            "track_id":    tid,
                            "label":       label,
                            "detected_at": datetime.utcnow().isoformat(),
                            "location":    self.location,
                        })
                        print(f"⚠️  [{self.camera_id}] 역주행 탐지 track_id={tid} label={label}")

                # REST API용 트랙 정보 수집 (궤적·중앙점·방향 벡터)
                # 스트림 다운스케일과 동일 비율로 좌표 변환 → canvas overlay 싱크 유지
                bh_info  = max(y2 - y1, cfg.min_bbox_h)
                nm_info  = speeds.get(tid, 0.0) / bh_info if speeds.get(tid) else 0.0
                ss       = self._stream_scale
                traj_pts = [[int(p[0] * ss), int(p[1] * ss)] for p in traj[-20:]]
                current_tracks_info.append({
                    "id":          tid,
                    "cx":          int(cx * ss),
                    "cy":          int(cy * ss),
                    "vx":          round(ndx, 3),   # 정규화 방향 벡터 x (-1~1)
                    "vy":          round(ndy, 3),   # 정규화 방향 벡터 y (-1~1)
                    "trail":       traj_pts,
                    "nm":          round(nm_info, 4),
                    "is_wrongway": tid in st.wrong_way_ids,
                })

            # ── 퇴장 차량 정리 ──
            gone_ids = prev_active_ids - active_ids
            for gone_id in gone_ids:
                self._track_direction.pop(gone_id, None)
                last_footpoints.pop(gone_id, None)
                self._wrongway_alerted.discard(gone_id)   # 재등장 대비
            prev_active_ids = active_ids.copy()

            # ── 방향별 TrafficAnalyzer 업데이트 (탐지 모드에서만) ──
            if (self.traffic_analyzer_a is not None
                    and not st.is_learning and not st.relearning and not st.waiting_stable):
                tracks_a, speeds_a = [], {}
                tracks_b, speeds_b = [], {}
                for t in tracks:
                    d = self._track_direction.get(t["id"], 'a')
                    if d == 'a':
                        tracks_a.append(t)
                        if t["id"] in speeds:
                            speeds_a[t["id"]] = speeds[t["id"]]
                    else:
                        tracks_b.append(t)
                        if t["id"] in speeds:
                            speeds_b[t["id"]] = speeds[t["id"]]

                self.traffic_analyzer_a.update(tracks_a, speeds_a, st.frame_num)
                self.traffic_analyzer_b.update(tracks_b, speeds_b, st.frame_num)
                self.predictor_a.update(self.traffic_analyzer_a.get_avg_speed())
                self.predictor_b.update(self.traffic_analyzer_b.get_avg_speed())

                # ── HistoricalPredictor: jam_score 이력 누적 ──────────────
                # grace period 내(재연결 직후 속도 이력 미구성 구간)는 기록하지 않는다.
                # 오염된 jam_score가 CSV에 쌓이는 것을 방지하기 위함이다.
                _post_grace = getattr(cfg, "post_skip_grace_frames", 30)
                _skip_frame = getattr(st, "_last_skip_frame", -9999)    # 없으면 -9999
                _in_grace   = (st.frame_num - _skip_frame) <= _post_grace
                if not _in_grace:
                    if self._hist_pred_a is not None:
                        self._hist_pred_a.record(self.traffic_analyzer_a.get_jam_score())
                    if self._hist_pred_b is not None:
                        self._hist_pred_b.record(self.traffic_analyzer_b.get_jam_score())

            # ── 최신 상태 저장 (frame_lock: BaseDetector 제공) ──
            with self.frame_lock:
                self.latest_frame       = frame.copy()
                self.latest_tracks_info = current_tracks_info
                self.latest_speeds      = speeds.copy()

            # ── 30프레임마다 Socket.IO emit ──────────────────────────────
            # emit 주기(_EMIT_INTERVAL)는 유지 — 프론트엔드 실시간성 보장
            if st.frame_num % _EMIT_INTERVAL == 0:
                self._emit_traffic_update()

            # ── 콘솔 로그: 학습 중 10% 마일스톤 + 탐지 중 10초 주기 ──────
            # 학습 단계별로 로그 전략을 달리해 터미널 노이즈를 최소화한다.
            if st.is_learning:
                # 초기 학습: 10% 단위(10, 20, ..., 100)에 한 번씩만 출력
                progress = min(st.frame_num, cfg.learning_frames)
                pct = int(progress / cfg.learning_frames * 100) // 10 * 10   # 10% 버킷
                if pct > 0 and pct not in _learn_logged_pcts:
                    _learn_logged_pcts.add(pct)
                    print(f"[{self.camera_id}] 학습 {pct}% ({progress}/{cfg.learning_frames}) | "
                          f"차량:{len(tracks)}대")
            elif st.relearning:
                # 재학습: 동일하게 10% 마일스톤
                elapsed = st.frame_num - st.relearn_start_frame
                pct = int(elapsed / cfg.relearn_frames * 100) // 10 * 10
                if pct > 0 and pct not in _relearn_logged_pcts:
                    _relearn_logged_pcts.add(pct)
                    print(f"[{self.camera_id}] 재보정 {pct}% ({elapsed}/{cfg.relearn_frames}) | "
                          f"차량:{len(tracks)}대")
            elif st.waiting_stable:
                # 안정 대기: _LOG_INTERVAL(~10초)마다 1줄
                if st.frame_num % _LOG_INTERVAL == 0:
                    stable_elapsed = st.frame_num - st.stable_since_frame
                    print(f"[{self.camera_id}] 안정대기중 "
                          f"(diff={self.switch.last_adj_diff:.1f}, {stable_elapsed}f) | "
                          f"차량:{len(tracks)}대")
            else:
                # 탐지 모드: _LOG_INTERVAL(~10초)마다 상태 출력
                if st.frame_num % _LOG_INTERVAL == 0:
                    ja = self.traffic_analyzer_a.get_jam_score()
                    jb = self.traffic_analyzer_b.get_jam_score()
                    la = self.traffic_analyzer_a.get_congestion_level()
                    lb = self.traffic_analyzer_b.get_congestion_level()
                    print(f"[{self.camera_id}] A:{la}({ja:.3f}) B:{lb}({jb:.3f}) | "
                          f"차량:{len(tracks)}대")

            # ── gevent 이벤트 루프 양보 ──────────────────────────────
            # YOLO 추론·OpenCV read 등 C 익스텐션이 GIL을 잡고 블로킹하면
            # 다른 그린렛(Socket.IO 하트비트 등)이 실행 기회를 얻지 못한다.
            # 매 프레임마다 gevent 이벤트 루프에 제어권을 양보해 소켓 끊김 방지.
            gevent.sleep(0)

    def reconnect(self, delay=3, max_retries=5):
        """
        base_detector.reconnect() 오버라이드.
        HTTP(HLS) URL은 CAP_FFMPEG 없이 열어야 한다.
        cap.read()와 동일하게 블로킹 재연결도 OS 스레드에서 실행.
        """
        if not hasattr(self, 'cap'):
            return False

        is_rtsp = self.url.lower().startswith(('rtsp://', 'rtsps://'))

        for i in range(max_retries):
            if not self.is_running:
                return False
            print(f"📡 [{self.camera_id}] 재연결 시도 ({i+1}/{max_retries})...")
            try:
                self.cap.release()
                gevent.sleep(delay)   # 실제 대기 (이벤트 루프 양보)

                if not is_rtsp:
                    # HTTP/HLS: 재연결 전 ITS URL 토큰을 갱신한다.
                    # 스트림이 끊긴 사이에 토큰이 만료됐을 수 있으므로
                    # 최신 토큰을 받아 self.url 을 업데이트한다.
                    self.url = self._get_fresh_url()

                def _open_cap():
                    """재연결용 VideoCapture 열기 헬퍼."""
                    if is_rtsp:
                        # RTSP: FFMPEG 백엔드 강제 (기존 방식 유지)
                        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    else:
                        # HTTP/HLS: _open_http_cap() 으로 FFMPEG 명시 + 직렬화 잠금
                        # (URL은 위에서 이미 갱신됨)
                        cap = _open_http_cap(self.url)
                    return cap

                self.cap = _FRAME_POOL.apply(_open_cap)
                if self.cap.isOpened():
                    print(f"✅ [{self.camera_id}] 재연결 성공")
                    return True
            except Exception as e:
                print(f"⚠️ [{self.camera_id}] 재연결 중 오류: {e}")

        print(f"❌ [{self.camera_id}] {max_retries}회 재연결 실패")
        return False

    # ────────────────────────────────────────────────────────────────────
    # flow_map 캐시 로드 / 저장 헬퍼
    # ────────────────────────────────────────────────────────────────────

    def _try_load_cache(self, first_frame: np.ndarray) -> bool:
        """
        저장된 flow_map 중 현재 카메라 화면과 가장 유사한 것을 찾아 로드한다.

        반드시 flow.init_grid() 호출 이후에 실행해야 cell_w/cell_h 가 올바르다.

        모든 작업을 try/except 로 감싸서 예외가 run() 을 종료시키지 않도록 한다.
        예외가 run() 까지 전파되면 generate_frames() 가 마지막 프레임을 무한 반복해
        "사진처럼 멈춘" 화면이 발생한다 — 이전 freeze 의 핵심 원인.

        Parameters
        ----------
        first_frame : np.ndarray | None
            스트림에서 읽은 첫 번째 프레임. None 이면 즉시 False 반환.

        Returns
        -------
        bool
            True  = 캐시 히트 → 학습 불필요, 탐지 모드로 바로 진입.
            False = 캐시 미스 → 기존대로 학습 모드 시작.
        """
        try:
            # None 프레임 방어: cap.read() 실패 시 None 이 전달될 수 있다.
            # cv2.resize(None) 등에서 예외가 발생해 run() 이 죽는 것을 막는다.
            if first_frame is None:
                print(f"  [{self.camera_id}] 캐시 탐색 건너뜀 (첫 프레임 없음)")
                return False

            my_dir = self._flow_maps_root / self.camera_id  # 자기 자신의 저장 폴더 경로

            # ── 1단계: 자기 자신의 저장 폴더에서 최적 스냅샷 검색 ──────────────
            # 타임스탬프 스냅샷(flow_map_YYYYMMDD_HHMMSS.npy + ref_frame_*.jpg) 또는
            # 레거시(flow_map.npy + ref_frame.jpg) 중 현재 프레임과 가장 유사한 것을 선택.
            # find_best_snapshot: ORB + 히스토그램 유사도로 최적 쌍을 찾아 .npy 경로 반환.
            _best_npy, _snap_score = find_best_snapshot(first_frame, my_dir)
            if _best_npy is not None:
                if self.flow.load(_best_npy):
                    # 학습 완료 직후와 동일하게 방향 분류 기준 설정
                    self._compute_ref_direction()
                    self._compute_direction_cell_counts()
                    # v3 이하 파일은 A/B 채널이 없으므로 로드 후 반드시 재빌드
                    # (v4 파일은 load() 내부에서 채널이 복원되지만 재빌드해도 무해)
                    _rd = self._ref_direction or (1.0, 0.0)   # None 방어
                    self.flow.build_directional_channels(_rd[0], _rd[1])
                    print(f"✅ [{self.camera_id}] 자체 캐시 히트! (score={_snap_score:.3f}) → 학습 생략, 탐지 모드 진입")
                    return True
                else:
                    # grid_size 불일치(해상도 변경) → 자체 캐시 로드 실패 → 2단계로 진행
                    print(f"  [{self.camera_id}] 자체 flow_map grid 불일치 → 다른 카메라 탐색")

            # ── 2단계: 다른 카메라 중 유사한 화면 탐색 (교차 재사용) ──────────
            # 처음 등록하는 카메라라 자체 flow_map 이 없을 때,
            # 같은 도로의 다른 카메라가 비슷한 앵글이면 그 flow_map 을 빌려 쓴다.
            # 자기 자신 폴더는 제외 (1단계에서 이미 시도했으므로 중복 방지).
            matcher = FlowMapMatcher(self._flow_maps_root)
            best_dir, score = matcher.find_best(first_frame, exclude_dir=my_dir)

            if best_dir is None:
                # 유사한 다른 카메라 캐시도 없음 → 학습 모드 진행
                print(f"  [{self.camera_id}] 캐시 미스 (score={score:.3f}) → 학습 시작")
                return False

            # 다른 카메라 flow_map 로드: init_grid() 이후이므로 cell_w/cell_h 가 올바르다.
            flow_npy = best_dir / "flow_map.npy"
            if not self.flow.load(flow_npy):
                # grid_size 불일치 → 로드 실패 → 학습 모드 fallback
                print(f"  [{self.camera_id}] 교차 flow_map 로드 실패 → 학습 모드 fallback")
                return False

            # 학습 완료 직후 자동 호출되는 두 함수를 캐시 히트 시에도 반드시 호출한다.
            # 미호출 시 self._ref_direction=None → 방향 분류 불가 (모든 차량이 'a' 방향).
            self._compute_ref_direction()
            self._compute_direction_cell_counts()
            # 교차 캐시 파일도 v3 이하일 수 있으므로 A/B 채널을 재빌드한다
            _rd = self._ref_direction or (1.0, 0.0)   # None 방어
            self.flow.build_directional_channels(_rd[0], _rd[1])

            print(f"✅ [{self.camera_id}] 교차 캐시 히트! {best_dir.name} "
                  f"(score={score:.3f}) → 학습 생략, 탐지 모드 진입")
            return True

        except Exception as e:
            # 예외를 run() 까지 전파하지 않고 학습 모드로 안전하게 fallback 한다.
            # 전파 시 run() 이 종료되어 generate_frames() 가 마지막 프레임을 무한 반복.
            print(f"⚠️  [{self.camera_id}] 캐시 로드 중 오류: {e} → 학습 모드 fallback")
            return False

    def _save_cache(self, frame: np.ndarray):
        """
        학습(또는 재학습) 완료 후 flow_map 과 ref_frame 을 저장한다.

        모든 작업을 try/except 로 감싸서 디스크 꽉 참 등의 예외가
        run() 을 종료시키지 않도록 한다.

        Parameters
        ----------
        frame : np.ndarray
            학습 완료 시점의 BGR 프레임 (다음 매칭 시 기준 이미지로 사용).
        """
        try:
            # 저장 경로: {_flow_maps_root}/{camera_id}/
            road_dir = self._flow_maps_root / self.camera_id
            # 타임스탬프 기반 스냅샷으로 저장
            # → flow_map_YYYYMMDD_HHMMSS.npy + ref_frame_YYYYMMDD_HHMMSS.jpg 쌍 생성
            # → 다음 시작 시 find_best_snapshot()이 현재 프레임과 가장 유사한 쌍을 선택
            save_flow_snapshot(frame, self.flow, road_dir)
        except Exception as e:
            # 저장 실패가 탐지 루프를 중단시켜서는 안 된다.
            print(f"⚠️  [{self.camera_id}] 캐시 저장 중 오류: {e}")

    def stop(self):
        super().stop()
        if hasattr(self, 'cap') and self.cap.isOpened():
            self.cap.release()
        print(f"🛑 [{self.camera_id}] MonitoringDetector 정지")
