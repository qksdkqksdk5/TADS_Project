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
import threading
import gevent
from gevent.threadpool import ThreadPool as _GeventThreadPool
from datetime import datetime
from pathlib import Path

# ── final_pj 모듈 경로 등록 ──────────────────────────────────────────────
# _FINAL_PJ_ROOT = r'C:\final_pj'
# _FINAL_PJ_SRC  = r'C:\final_pj\src'

# monitoring_detector.py 기준: monitoring/
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# detector_modules/
_MODULES_DIR = os.path.join(_BASE_DIR, 'detector_modules')

for _p in (_BASE_DIR, _MODULES_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from detector_modules.config          import DetectorConfig
from detector_modules.state           import DetectorState
from detector_modules.flow_map        import FlowMap
from detector_modules.tracker         import YoloTracker
from detector_modules.judge           import WrongWayJudge
from detector_modules.id_manager      import IDManager
from detector_modules.camera_switch   import CameraSwitchDetector
from detector_modules.traffic_analyzer import TrafficAnalyzer, CongestionPredictor

# GRU: PyTorch 없는 환경에서도 동작하도록 try/except
try:
    from detector_modules.gru_module import GRUModule
    _GRU_AVAILABLE = True
except ImportError:
    _GRU_AVAILABLE = False

from modules.traffic.detectors.base_detector import BaseDetector

# ── 상수 ────────────────────────────────────────────────────────────────
# _YOLO_MODEL    = r'C:\final_pj\runs\yolo11n_v2\weights\best.pt'
_YOLO_MODEL = os.path.join(_BASE_DIR, 'best.pt')
_EMIT_INTERVAL = 30   # 30프레임마다 traffic_update emit (약 1초@30fps)

# ── gevent 호환 OS 스레드 풀 ──────────────────────────────────────────────
# cap.read() / tracker.track() 등 C 익스텐션 블로킹 호출을 실제 OS 스레드에서
# 실행하여 gevent 이벤트 루프를 차단하지 않도록 한다.
# (카메라 수 × 2 작업 여유치로 8 설정)
_FRAME_POOL = _GeventThreadPool(maxsize=8)

# ── 공유 YOLO 가중치 ─────────────────────────────────────────────────────
# 여러 MonitoringDetector 인스턴스가 동일한 nn.Module(가중치)을 공유한다.
# YOLO 모델 가중치(~30MB)를 최초 1회만 로드하고, 이후 인스턴스는 참조만 복사.
# ByteTrack 상태(model.predictor.trackers)는 YOLO 인스턴스별로 독립 유지된다.
_SHARED_YOLO_WEIGHTS = None
_SHARED_YOLO_LOCK    = threading.Lock()


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

        # ── DetectorConfig ─────────────────────────────────────────────
        # flow_map_path=None + detect_only=False → 옵션 B: 매번 새로 학습
        # gru_blend_ratio는 config 기본값(0.2) 유지
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
        # ── YOLO 가중치 공유 ────────────────────────────────────────────────
        global _SHARED_YOLO_WEIGHTS, _SHARED_YOLO_LOCK
        with _SHARED_YOLO_LOCK:
            if _SHARED_YOLO_WEIGHTS is None:
                _SHARED_YOLO_WEIGHTS = self.tracker.model.model
                print(f"🧠 [MonitoringDetector] YOLO 가중치 최초 로드 완료")
            else:
                self.tracker.model.model = _SHARED_YOLO_WEIGHTS
                print(f"🧠 [{self.camera_id}] YOLO 가중치 공유 적용 (메모리 절약)")

        self.judge  = WrongWayJudge(self.cfg, self.flow, self.state)
        self.idm    = IDManager(self.cfg, self.flow, self.state)
        self.switch = CameraSwitchDetector(self.cfg)

        # TrafficAnalyzer: 프레임 크기 확인 후 run() 에서 초기화
        self.traffic_analyzer_a = None
        self.traffic_analyzer_b = None
        self.predictor_a        = None
        self.predictor_b        = None
        self.gru_module_a       = None
        self.gru_module_b       = None

        # ── 방향 분류 상태 ────────────────────────────────────────────────
        self._ref_direction  = None
        self._dir_label_a    = "상행"
        self._dir_label_b    = "하행"
        self._valid_cells_a  = 1
        self._valid_cells_b  = 1
        self._track_direction: dict = {}   # {track_id: 'a' | 'b'}

        # ── Socket.IO emit / REST API 공유 상태 ──────────────────────────
        # frame_lock(BaseDetector 제공)으로 스레드 안전하게 접근
        self._prev_level        = "SMOOTH"   # 레벨 전환 감지용
        self._wrongway_alerted  = set()      # 이미 알림 보낸 역주행 track_id
        self.latest_tracks_info = []         # Step 4 REST API용
        self.latest_speeds      = {}         # Step 4 REST API용
        self.debug_info: dict   = {}         # /debug/<camera_id> 응답용

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
        print(f"🧭 [{self.camera_id}] 기준 방향 "
              f"({self._ref_direction[0]:.3f}, {self._ref_direction[1]:.3f}) "
              f"A={self._dir_label_a} B={self._dir_label_b}")

    def _compute_direction_cell_counts(self):
        """방향별 유효 셀 수를 계산해 TrafficAnalyzer에 주입한다."""
        if self._ref_direction is None:
            return
        ref_x, ref_y   = self._ref_direction
        count_a, count_b = 0, 0
        for r in range(self.flow.grid_size):
            for c in range(self.flow.grid_size):
                if self.flow.count[r, c] <= 0:
                    continue
                vx  = float(self.flow.flow[r, c, 0])
                vy  = float(self.flow.flow[r, c, 1])
                cos = vx * ref_x + vy * ref_y
                if cos >= self.cfg.lane_cos_threshold:
                    count_a += 1
                else:
                    count_b += 1
        self._valid_cells_a = max(count_a, 1)
        self._valid_cells_b = max(count_b, 1)
        if self.traffic_analyzer_a:
            self.traffic_analyzer_a.set_valid_cell_count(self._valid_cells_a)
        if self.traffic_analyzer_b:
            self.traffic_analyzer_b.set_valid_cell_count(self._valid_cells_b)
        print(f"📐 [{self.camera_id}] 방향별 셀 A={self._valid_cells_a} B={self._valid_cells_b}")

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

        payload = {
            "camera_id":         self.camera_id,
            "lat":               self.lat,
            "lng":               self.lng,
            "location":          self.location,
            "level":             level,
            "jam_score":         round((jam_a + jam_b) / 2, 3),
            "jam_up":            round(jam_a, 3),
            "jam_down":          round(jam_b, 3),
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
        }
        self.socketio.emit('traffic_update', payload)

        # ── 레벨 전환 감지 ──
        if level != self._prev_level:
            self.socketio.emit('level_change', {
                "camera_id":  self.camera_id,
                "from_level": self._prev_level,
                "to_level":   level,
                "jam_score":  payload["jam_score"],
                "timestamp":  datetime.utcnow().isoformat(),
            })
            if level in ("SLOW", "JAM"):
                self.socketio.emit('anomaly_alert', {
                    "camera_id":   self.camera_id,
                    "event_type":  "CONGESTION",
                    "level":       level,
                    "jam_score":   payload["jam_score"],
                    "detected_at": datetime.utcnow().isoformat(),
                    "location":    self.location,
                })
            self._prev_level = level

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
            "gru_blend_ratio":   cfg.gru_blend_ratio,
            "wrongway_ids":      list(st.wrong_way_ids),
        }

    # ────────────────────────────────────────────────────────────────────
    # 메인 루프
    # ────────────────────────────────────────────────────────────────────
    def run(self):
        cfg = self.cfg
        st  = self.state
        print(f"🚦 [{self.camera_id}] MonitoringDetector 시작 url={self.url}")

        # ── 스트림 열기 (OS 스레드에서 실행) ─────────────────────────────
        # VideoCapture 초기화도 FFMPEG C 코드 → gevent 루프 차단 방지를 위해 threadpool 사용.
        # RTSP: FFMPEG 백엔드 강제 + 버퍼 최소화
        # HTTP/HLS: 백엔드 자동 선택 (CAP_FFMPEG 강제 시 HLS 열기 실패)
        is_rtsp = self.url.lower().startswith(('rtsp://', 'rtsps://'))

        def _open_cap():
            if is_rtsp:
                c = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            else:
                c = cv2.VideoCapture(self.url)
            return c

        self.cap = _FRAME_POOL.apply(_open_cap)
        if not self.cap.isOpened():
            print(f"❌ [{self.camera_id}] 스트림 열기 실패: {self.url}")
            return

        fw  = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        fh  = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        st.frame_w, st.frame_h, st.video_fps = fw, fh, fps
        self.flow.init_grid(fw, fh)

        # ── GRU 초기화 ────────────────────────────────────────────────
        if _GRU_AVAILABLE:
            self.gru_module_a = GRUModule(cfg, fps=fps)
            self.gru_module_b = GRUModule(cfg, fps=fps)
            print(f"🧠 [{self.camera_id}] GRUModule ×2 초기화 (blend={cfg.gru_blend_ratio})")
        else:
            print(f"ℹ️  [{self.camera_id}] GRU 없음 → rule-only 모드")

        # ── TrafficAnalyzer ×2 초기화 ────────────────────────────────
        self.traffic_analyzer_a = TrafficAnalyzer(
            cfg, frame_w=fw, frame_h=fh, fps=fps,
            flow_map=self.flow, gru_module=self.gru_module_a
        )
        self.traffic_analyzer_a.set_state(st)

        self.traffic_analyzer_b = TrafficAnalyzer(
            cfg, frame_w=fw, frame_h=fh, fps=fps,
            flow_map=self.flow, gru_module=self.gru_module_b
        )
        self.traffic_analyzer_b.set_state(st)

        self.predictor_a = CongestionPredictor(cfg, fps=fps)
        self.predictor_b = CongestionPredictor(cfg, fps=fps)

        # 옵션 B: 항상 학습 모드로 시작
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

        print(f"📚 [{self.camera_id}] 학습 모드 시작 (목표: {cfg.learning_frames}프레임 ≈ {cfg.learning_frames/fps:.0f}초)")

        # ── 메인 루프 ────────────────────────────────────────────────
        while self.is_running and self.cap.isOpened():
            # cap.read(): FFMPEG C 코드가 HLS 세그먼트 다운로드 시 수십 초 블로킹.
            # OS 스레드에서 실행해 gevent 이벤트 루프(소켓 하트비트·MJPEG 스트림)를 보호.
            success, frame = _FRAME_POOL.apply(self.cap.read)
            if not success:
                reconnected = self.reconnect(delay=3, max_retries=5)
                if not reconnected:
                    gevent.sleep(10)
                continue

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
                _jump_thr_dynamic = _base_jump_px * min(_scale, 5.0)

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
                print(f"[{self.camera_id}] ⚠️ 프레임 스킵 감지 ({_jump_count}/{_jump_total}대 jump) → 스킵")
                for _t in tracks:
                    _tid = _t["id"]
                    if st.trajectories[_tid]:
                        _cur_pos = (_t["cx"], _t["cy"])
                        st.trajectories[_tid] = [_cur_pos] * len(st.trajectories[_tid])
                    st.last_velocity.pop(_tid, None)
                    st.wrong_way_count[_tid] = 0
                    st.direction_change_frame[_tid] = st.frame_num
                    st.wrong_way_ids.discard(_tid)

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
                        if self.gru_module_a:
                            self.gru_module_a.reset()
                        if self.gru_module_b:
                            self.gru_module_b.reset()
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
                            st.reset_for_relearn()
                            self.flow.reset()
                            self.traffic_analyzer_a.congestion_judge.reset()
                            self.traffic_analyzer_b.congestion_judge.reset()
                            self._ref_direction = None
                            _relearn_smooth_80 = _relearn_smooth_95 = False

                # (C) 재학습 중: 또 흔들리면 중단 → 대기 복귀
                elif st.relearning:
                    self.switch.check(frame, st.frame_num, st.cooldown_until)
                    _cur_diff = self.switch.last_adj_diff
                    if _cur_diff > _relearn_abort:
                        print(f"⚠️ [{self.camera_id}] 재학습 중 화면 불안정 (diff={_cur_diff:.1f}) → 중단, 안정 대기 복귀")
                        st.relearning = False
                        st.waiting_stable = True
                        st.stable_since_frame = st.frame_num
                        self.flow.reset()
                        _relearn_smooth_80 = _relearn_smooth_95 = False
                        if self.gru_module_a:
                            self.gru_module_a.reset()
                        if self.gru_module_b:
                            self.gru_module_b.reset()

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
                    st.is_learning = False
                    print(f"✅ [{self.camera_id}] 초기 학습 완료! frame={st.frame_num}")

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
                    st.relearning      = False
                    st.cooldown_until  = st.frame_num + cfg.cooldown_frames
                    self.switch.set_reference(frame)
                    print(f"✅ [{self.camera_id}] 재학습 완료!")

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
                    _prev_fx, _prev_fy = st.trajectories[tid][-1]
                    _solo_dist = ((fx - _prev_fx)**2 + (fy - _prev_fy)**2) ** 0.5
                    if _solo_dist > _jump_thr * 1.5:   # 단독 jump는 더 엄격한 기준
                        _solo_jump = True
                        _cur_pos = (fx, fy)
                        st.trajectories[tid] = [_cur_pos] * len(st.trajectories[tid])
                        st.last_velocity.pop(tid, None)
                        st.wrong_way_count[tid] = 0
                        st.direction_change_frame[tid] = st.frame_num
                        st.wrong_way_ids.discard(tid)

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
                if len(traj) >= cfg.velocity_window:
                    vdx = traj[-1][0] - traj[-cfg.velocity_window][0]
                    vdy = traj[-1][1] - traj[-cfg.velocity_window][1]
                    mag = np.sqrt(vdx**2 + vdy**2)
                    speeds[tid] = mag

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
                            learn_min_mag = max(1.0, bh * cfg.norm_learn_threshold)
                            self.flow.learn_step(
                                traj[-cfg.velocity_window][0],
                                traj[-cfg.velocity_window][1],
                                fx, fy, learn_min_mag
                            )
                        elif not st.waiting_stable:
                            # 역주행 판정 (탐지 모드, 안정 대기 중이 아닐 때만)
                            bbox_h = max(y2 - y1, 1)
                            is_wrong, _, _ = self.judge.check(
                                tid, traj, ndx, ndy, mag, cy, bbox_h
                            )
                            if is_wrong and tid in st.wrong_way_ids:
                                self.idm.assign_label(tid)
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

                # REST API용 트랙 정보 수집 (Step 4에서 사용)
                bh_info = max(y2 - y1, cfg.min_bbox_h)
                nm_info = speeds.get(tid, 0.0) / bh_info if speeds.get(tid) else 0.0
                current_tracks_info.append({
                    "id":        tid,
                    "x1": int(x1), "y1": int(y1),
                    "x2": int(x2), "y2": int(y2),
                    "nm":        round(nm_info, 4),
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

            # ── 최신 상태 저장 (frame_lock: BaseDetector 제공) ──
            with self.frame_lock:
                self.latest_frame       = frame.copy()
                self.latest_tracks_info = current_tracks_info
                self.latest_speeds      = speeds.copy()

            # ── 30프레임마다 emit + 콘솔 로그 ──
            if st.frame_num % _EMIT_INTERVAL == 0:
                self._emit_traffic_update()
                if st.is_learning:
                    progress = min(st.frame_num, cfg.learning_frames)
                    print(f"[{self.camera_id}] f={st.frame_num} | "
                          f"학습중({progress}/{cfg.learning_frames}) | "
                          f"차량:{len(tracks)}대")
                elif st.relearning:
                    elapsed = st.frame_num - st.relearn_start_frame
                    print(f"[{self.camera_id}] f={st.frame_num} | "
                          f"재보정중({elapsed}/{cfg.relearn_frames}) | "
                          f"차량:{len(tracks)}대")
                elif st.waiting_stable:
                    stable_elapsed = st.frame_num - st.stable_since_frame
                    print(f"[{self.camera_id}] f={st.frame_num} | "
                          f"안정대기중(diff={self.switch.last_adj_diff:.1f}, {stable_elapsed}f) | "
                          f"차량:{len(tracks)}대")
                else:
                    ja = self.traffic_analyzer_a.get_jam_score()
                    jb = self.traffic_analyzer_b.get_jam_score()
                    la = self.traffic_analyzer_a.get_congestion_level()
                    lb = self.traffic_analyzer_b.get_congestion_level()
                    print(f"[{self.camera_id}] f={st.frame_num} | "
                          f"A:{la}({ja:.3f}) B:{lb}({jb:.3f}) | "
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

                def _open_cap():
                    if is_rtsp:
                        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    else:
                        cap = cv2.VideoCapture(self.url)
                    return cap

                self.cap = _FRAME_POOL.apply(_open_cap)
                if self.cap.isOpened():
                    print(f"✅ [{self.camera_id}] 재연결 성공")
                    return True
            except Exception as e:
                print(f"⚠️ [{self.camera_id}] 재연결 중 오류: {e}")

        print(f"❌ [{self.camera_id}] {max_retries}회 재연결 실패")
        return False

    def stop(self):
        super().stop()
        if hasattr(self, 'cap') and self.cap.isOpened():
            self.cap.release()
        print(f"🛑 [{self.camera_id}] MonitoringDetector 정지")
