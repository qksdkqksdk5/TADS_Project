"""
reverse_detector.py
detector_modules (monitoring 팀) 기반 역주행 탐지기.
- TrafficAnalyzer / GRUModule 제외 (역주행 전용)
- is_simulation, switch_mode, realtime_url 등 기존 기능 유지
- judge.py: detector_modules 버전 (fast-track, 장기 윈도우, 방향 급변 가드 등)
- FlowMapMatcher 캐시 재사용 지원
"""

import os
import sys
import cv2
import numpy as np
import time
import threading
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from ultralytics import YOLO
from .base_detector import BaseDetector
from shared.discord_helper import send_discord_notification
import shared.state as shared

# ── detector_modules 경로 등록 ────────────────────────────────────────────────
_BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
_MODULES_DIR = os.path.dirname(os.path.dirname(_BASE_DIR))
_MON_DIR = os.path.join(_MODULES_DIR, 'monitoring')
# ── flow_map 캐시 저장 루트 ───────────────────────────────────────────────────
# monitoring/flow_maps/simulation/ 에 저장
_FLOW_MAPS_ROOT = os.path.join(_MON_DIR, 'flow_maps')
_MOD_DIR      = os.path.join(_MON_DIR, 'detector_modules')

for _p in (_MON_DIR, _MOD_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── detector_modules 임포트 ───────────────────────────────────────────────────
from modules.monitoring.detector_modules.config         import DetectorConfig
from modules.monitoring.detector_modules.state          import DetectorState
from modules.monitoring.detector_modules.flow_map       import FlowMap
from modules.monitoring.detector_modules.tracker        import YoloTracker
from modules.monitoring.detector_modules.judge          import WrongWayJudge
from modules.monitoring.detector_modules.id_manager     import IDManager
from modules.monitoring.detector_modules.camera_switch  import CameraSwitchDetector
from modules.monitoring.detector_modules.flow_map_matcher import FlowMapMatcher, save_ref_frame

# ── 환경 변수 ─────────────────────────────────────────────────────────────────
_USE_GPU = os.getenv('USE_GPU', 'false').lower() == 'true'

# ── 블로킹 C 익스텐션용 스레드풀 ─────────────────────────────────────────────
_FRAME_POOL = ThreadPoolExecutor(max_workers=8)

# ── VideoCapture 직렬화 잠금 ──────────────────────────────────────────────────
_CAP_OPEN_LOCK = threading.Lock()

# ── 상수 ─────────────────────────────────────────────────────────────────────
_SKIP_LOG_COOL = 300


def _open_cap_ffmpeg(url: str):
    with _CAP_OPEN_LOCK:
        c = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return c


def _open_cap_auto(url: str):
    """백엔드 자동 선택 (로컬 파일·웹캠·시뮬레이션 영상용)"""
    c = cv2.VideoCapture(url)
    return c


# ── 프레임 스킵 / 단독 점프 리셋 헬퍼 ────────────────────────────────────────

def _apply_frame_skip_reset(st: DetectorState, tracks, frame_num: int):
    st.post_reconnect_frame = frame_num
    for t in tracks:
        tid = t["id"]
        if st.trajectories[tid]:
            cur = (t["cx"], t["cy"])
            st.trajectories[tid] = [cur] * len(st.trajectories[tid])
        st.last_velocity.pop(tid, None)
        st.wrong_way_count[tid] = 0
        st.direction_change_frame[tid] = frame_num
        st.wrong_way_ids.discard(tid)


def _apply_solo_jump_reset(st: DetectorState, tid: int, cur_pos, frame_num: int):
    st.post_reconnect_frame = frame_num
    st.trajectories[tid] = [cur_pos] * len(st.trajectories[tid])
    st.last_velocity.pop(tid, None)
    st.wrong_way_count[tid] = 0
    st.direction_change_frame[tid] = frame_num
    st.wrong_way_ids.discard(tid)


def discord_task(url, location, image_path):
    send_discord_notification(url, event_type="역주행", location=location, image_path=image_path)


class ReverseDetector(BaseDetector):
    """
    역주행 탐지기 — detector_modules(monitoring) 기반.

    Parameters
    ----------
    cctv_name    : str   감지기 이름 (BaseDetector)
    url          : str   스트림 URL
    lat, lng     : float CCTV 위치
    is_simulation: bool  시뮬레이션 모드 여부
    realtime_url : str   시뮬레이션 종료 후 복귀할 실시간 URL
    video_origin : str   shared.latest_frames 키
    """

    def __init__(self, cctv_name, url,
                 lat=37.5, lng=127.0,
                 socketio=None, db=None, ResultModel=None, ReverseModel=None,
                 conf=None, app=None,
                 is_simulation=False,
                 realtime_url=None,
                 video_origin="realtime_its"):

        super().__init__(cctv_name, url, app=app,
                         socketio=socketio, db=db, ResultModel=ResultModel)

        self.lat           = lat
        self.lng           = lng
        self.ReverseModel  = ReverseModel
        self.is_simulation = is_simulation
        self.realtime_url  = realtime_url if realtime_url else url
        self.original_url  = url
        self.video_origin  = f"{video_origin}_{cctv_name}"

        # ── DetectorConfig (detector_modules 버전) ────────────────────────
        conf_val = float(os.getenv('CONFIDENCE_THRESHOLD') or conf or 0.5)
        _DIR = os.path.dirname(os.path.abspath(__file__))

        if _USE_GPU:
            _model_path = os.path.join(_DIR, "detect_models/best_DW.pt")
            print(f"🖥️ [{cctv_name}] GPU 모드로 로드")
        else:
            _model_path = os.path.join(_DIR, "detect_models/best_DW.pt")
            print(f"💻 [{cctv_name}] CPU(OpenVINO) 모드로 로드")

        self.cfg = DetectorConfig(
            model_path    = Path(_model_path),
            conf          = conf_val,
            detect_only   = False,
            flow_map_path = None,
            log_dir       = None,
        )

        # ── AI 파이프라인 ─────────────────────────────────────────────────
        self.state  = DetectorState()
        self.flow   = FlowMap(self.cfg.grid_size, self.cfg.alpha, self.cfg.min_samples)
        self.tracker = YoloTracker(
            self.cfg.model_path, self.cfg.conf, self.cfg.target_classes,
            night_enhance=getattr(self.cfg, 'night_enhance', True)
        )
        self.judge  = WrongWayJudge(self.cfg, self.flow, self.state)
        self.idm    = IDManager(self.cfg, self.flow, self.state)
        self.switch = CameraSwitchDetector(self.cfg)
        print(f"🧠 [{cctv_name}] YOLO 모델 로드 완료")

        # ── 방향 분류 상태 ────────────────────────────────────────────────
        self._ref_direction = None
        self._track_direction: dict = {}  # {track_id: 'a' | 'b'}

        # ── 역주행 알림 추적 ──────────────────────────────────────────────
        self._wrongway_alerted: set = set()

        # ── flow_map 캐시 ─────────────────────────────────────────────────
        self._flow_maps_root = Path(_FLOW_MAPS_ROOT)
        safe_name = cctv_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        self._cache_id = safe_name  # 캐시 폴더명

        # ── 진단 정보 ─────────────────────────────────────────────────────
        self._diag: dict = {
            'read_last_ms':      0,
            'read_max_ms':       0,
            'reconnect_count':   0,
            'reconnect_last_at': None,
            'last_frame_ok_at':  None,
        }

        # cap은 run() 내부에서 생성 (스레드 안전)
        self.cap = None

    # ────────────────────────────────────────────────────────────────────
    # flow_map 캐시 로드 / 저장
    # ────────────────────────────────────────────────────────────────────

    def _try_load_cache(self, first_frame) -> bool:
        try:
            if first_frame is None:
                return False

            my_dir      = self._flow_maps_root / self._cache_id
            print(f"🔍 [{self.cctv_name}] flow_map 캐시 탐색: {my_dir}")
            my_flow_npy = my_dir / "flow_map.npy"
            print(f"  [{self.cctv_name}] 자체 캐시 경로: {my_flow_npy}")

            if my_flow_npy.exists():
                if self.flow.load(my_flow_npy):
                    self._compute_ref_direction()
                    _rd = self._ref_direction or (1.0, 0.0)
                    self.flow.build_directional_channels(_rd[0], _rd[1])
                    print(f"✅ [{self.cctv_name}] 자체 캐시 히트! → 학습 생략")
                    return True
                else:
                    print(f"  [{self.cctv_name}] 자체 flow_map grid 불일치 → 다른 캐시 탐색")

            matcher = FlowMapMatcher(self._flow_maps_root)
            best_dir, score = matcher.find_best(first_frame, exclude_dir=my_dir)

            if best_dir is None:
                print(f"  [{self.cctv_name}] 캐시 미스 (score={score:.3f}) → 학습 시작")
                return False

            if not self.flow.load(best_dir / "flow_map.npy"):
                print(f"  [{self.cctv_name}] 교차 flow_map 로드 실패 → 학습 모드 fallback")
                return False

            self._compute_ref_direction()
            _rd = self._ref_direction or (1.0, 0.0)
            self.flow.build_directional_channels(_rd[0], _rd[1])
            print(f"✅ [{self.cctv_name}] 교차 캐시 히트! {best_dir.name} (score={score:.3f})")
            return True

        except Exception as e:
            print(f"⚠️ [{self.cctv_name}] 캐시 로드 오류: {e} → 학습 모드 fallback")
            return False

    def _save_cache(self, frame):
        try:
            road_dir = self._flow_maps_root / self._cache_id
            self.flow.save(road_dir / "flow_map.npy")
            save_ref_frame(frame, road_dir)
            print(f"💾 [{self.cctv_name}] flow_map 캐시 저장 완료")
        except Exception as e:
            print(f"⚠️ [{self.cctv_name}] 캐시 저장 오류: {e}")

    # ────────────────────────────────────────────────────────────────────
    # 방향 분류 헬퍼
    # ────────────────────────────────────────────────────────────────────

    def _compute_ref_direction(self):
        grid = self.flow
        best_r, best_c, best_count = 0, 0, 0
        for r in range(grid.grid_size):
            for c in range(grid.grid_size):
                if grid.count[r, c] > best_count:
                    best_count    = grid.count[r, c]
                    best_r, best_c = r, c
        vx  = float(grid.flow[best_r, best_c, 0])
        vy  = float(grid.flow[best_r, best_c, 1])
        mag = np.sqrt(vx**2 + vy**2)
        self._ref_direction = (vx / mag, vy / mag) if mag > 1e-6 else (1.0, 0.0)
        print(f"🧭 [{self.cctv_name}] 기준 방향 "
              f"({self._ref_direction[0]:.3f}, {self._ref_direction[1]:.3f})")

    def _classify_direction(self, fx, fy) -> str:
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
    # BaseDetector 추상 메서드
    # ────────────────────────────────────────────────────────────────────

    def process_alert(self, data):
        frame, alert_time, track_id = data
        try:
            with self.app.app_context():
                new_alert = self.ResultModel(
                    event_type   = "reverse",
                    address      = self.cctv_name,
                    latitude     = self.lat,
                    longitude    = self.lng,
                    detected_at  = alert_time,
                    is_simulation= self.is_simulation,
                    video_origin = self.video_origin,
                    is_resolved  = False,
                )
                self.db.session.add(new_alert)
                self.db.session.flush()

                ts       = alert_time.strftime("%Y%m%d_%H%M%S")
                filename = f"reverse_{new_alert.id}_{ts}.jpg"
                save_dir = os.path.join(self.app.root_path, "static", "captures")
                os.makedirs(save_dir, exist_ok=True)
                full_path = os.path.join(save_dir, filename)
                cv2.imwrite(full_path, frame)

                from models import ReverseResult
                self.db.session.add(ReverseResult(
                    result_id    = new_alert.id,
                    image_path   = f"/static/captures/{filename}",
                    vehicle_info = f"ID:{track_id} 탐지",
                ))
                self.db.session.commit()

                MY_DISCORD_WEBHOOK_URL = ""
                threading.Thread(
                    target=discord_task,
                    args=(MY_DISCORD_WEBHOOK_URL, self.cctv_name, full_path),
                    daemon=True,
                ).start()

                if self.socketio:
                    self.socketio.emit('anomaly_detected', {
                        "alert_id":      new_alert.id,
                        "type":          "역주행",
                        "address":       self.cctv_name,
                        "lat":           float(self.lat),
                        "lng":           float(self.lng),
                        "video_origin":  self.video_origin,
                        "is_simulation": self.is_simulation,
                        "image_url":     f"/static/captures/{filename}",
                    })
                print(f"🚨 [역주행 알람 완료] {self.cctv_name} - ID:{track_id}")

        except Exception as e:
            self.db.session.rollback()
            print(f"❌ 역주행 비동기 저장 에러: {e}")

    # ────────────────────────────────────────────────────────────────────
    # 모드 전환 (시뮬레이션 ↔ 실시간)
    # ────────────────────────────────────────────────────────────────────

    def switch_mode(self, is_simulation, video_path=None, recovery_url=None):
        if self.cap and self.cap.isOpened():
            self.cap.release()

        # 상태 완전 재생성
        self.state = DetectorState()
        self.is_simulation = is_simulation

        # 하위 모듈이 새 state를 바라보도록 재생성
        self.judge   = WrongWayJudge(self.cfg, self.flow, self.state)
        self.idm     = IDManager(self.cfg, self.flow, self.state)
        self._track_direction.clear()
        self._wrongway_alerted.clear()

        target_url = video_path if is_simulation else (recovery_url or self.original_url)
        print(f"🔄 [Mode Switch] {'Simulation' if is_simulation else 'Realtime'} 모드 전환: {target_url}")

        if is_simulation:
            self.cap = cv2.VideoCapture(target_url)
        else:
            self.cap = _open_cap_ffmpeg(target_url)
            self._load_flow_map_for_realtime()
            self.state.cooldown_until = 150

    def _load_flow_map_for_realtime(self):
        """실시간 복귀 시 저장된 flow_map 로드."""
        my_npy = self._flow_maps_root / self._cache_id / "flow_map.npy"
        if my_npy.exists() and self.flow.load(my_npy):
            self.state.is_learning = False
            self._compute_ref_direction()
            _rd = self._ref_direction or (1.0, 0.0)
            self.flow.build_directional_channels(_rd[0], _rd[1])
            print(f"✅ [{self.cctv_name}] 실시간 복귀 — flow_map 로드 완료")
        else:
            self.state.is_learning = True
            print(f"⚠️ [{self.cctv_name}] 실시간 복귀 — flow_map 없음 → 학습 시작")

    # ────────────────────────────────────────────────────────────────────
    # 메인 루프
    # ────────────────────────────────────────────────────────────────────

    def run(self):
        cfg = self.cfg
        st  = self.state

        print(f"🚗 [{self.cctv_name}] ReverseDetector 시작 "
              f"({'GPU' if _USE_GPU else 'CPU/OpenVINO'}) "
              f"(is_simulation={self.is_simulation})")

        # ── VideoCapture 생성 (run() 내부에서 — 스레드 안전) ─────────────
        if self.is_simulation:
            self.cap = _open_cap_auto(self.url)
        else:
            self.cap = _FRAME_POOL.submit(_open_cap_ffmpeg, self.url).result()

        if not self.cap.isOpened():
            print(f"❌ [{self.cctv_name}] 스트림 열기 실패: {self.url}")
            return

        fw  = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        fh  = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        st.frame_w, st.frame_h, st.video_fps = fw, fh, fps
        self.flow.init_grid(fw, fh)

        # ── 캐시 탐색 ────────────────────────────────────────────────────
        _cache_ok, _cache_frame = _FRAME_POOL.submit(self.cap.read).result()
        if _cache_ok:
            with self.frame_lock:
                self.latest_frame = _cache_frame
            if self.is_simulation:
                # 시뮬레이션은 캐시 필수 (학습 없음)
                hit = self._try_load_cache(_cache_frame)
                st.is_learning = False  # 시뮬레이션은 학습 안 함
                if not hit:
                    print(f"⚠️ [{self.cctv_name}] 시뮬레이션 — flow_map 없음, 탐지 정확도 낮을 수 있음")
            else:
                hit = self._try_load_cache(_cache_frame)
                st.is_learning = not hit
        else:
            print(f"⚠️ [{self.cctv_name}] 첫 프레임 읽기 실패")
            st.is_learning = not self.is_simulation

        max_learn        = int(cfg.learning_frames * cfg.max_learning_extension)
        _learn_smooth_80 = False
        _learn_smooth_95 = False
        _relearn_smooth_80 = False
        _relearn_smooth_95 = False

        # ── 프레임 스킵 감지 변수 ────────────────────────────────────────
        _proc_fps_samples = []
        _last_frame_time  = time.time()
        _base_jump_px     = getattr(cfg, 'frame_skip_jump_px', 80.0)
        _jump_thr_dynamic = _base_jump_px
        _last_skip_log    = -_SKIP_LOG_COOL

        session_key = self.video_origin if self.video_origin in shared.alert_sent_session else None

        if st.is_learning:
            print(f"📚 [{self.cctv_name}] 학습 모드 시작 (목표: {cfg.learning_frames}프레임)")
        else:
            print(f"🔍 [{self.cctv_name}] 탐지 모드로 시작 (캐시 히트)")

        # ── 메인 루프 ────────────────────────────────────────────────────
        while self.is_running and self.cap.isOpened():

            _read_t0 = time.time()

            if self.is_simulation:
                success, frame = self.cap.read()
            else:
                success, frame = _FRAME_POOL.submit(self.cap.read).result()

            _read_ms = (time.time() - _read_t0) * 1000
            self._diag['read_last_ms'] = round(_read_ms, 1)
            self._diag['read_max_ms']  = round(max(self._diag['read_max_ms'], _read_ms), 1)

            if not success or frame is None:
                if self.is_simulation:
                    print(f"🎬 [{self.cctv_name}] 시뮬레이션 종료")
                    self.stop()
                    break
                else:
                    self._diag['reconnect_count'] += 1
                    self._diag['reconnect_last_at'] = datetime.utcnow().isoformat()
                    if not self.reconnect(delay=3, max_retries=5):
                        time.sleep(10)
                    continue

            self._diag['last_frame_ok_at'] = datetime.utcnow().isoformat()

            # 전처리
            frame = cv2.resize(frame, (640, 360))
            shared.latest_frames[self.video_origin] = frame
            # with self.frame_lock:
            #     self.latest_frame = frame

            if self.flow.frame_w == 0:
                self.flow.init_grid(640, 360)
            st.frame_num += 1

            # ── 실제 fps 측정 + jump 임계값 동적 갱신 ────────────────────
            _now = time.time()
            _proc_fps_samples.append(_now - _last_frame_time)
            _last_frame_time = _now
            if len(_proc_fps_samples) > 30:
                _proc_fps_samples.pop(0)
            if len(_proc_fps_samples) >= 5:
                _avg   = sum(_proc_fps_samples) / len(_proc_fps_samples)
                _pfps  = 1.0 / max(_avg, 0.01)
                _scale = max(1.0, fps / max(_pfps, 1.0))
                _jump_thr_dynamic = min(
                    _base_jump_px * min(_scale, 5.0),
                    getattr(cfg, 'frame_skip_jump_px_max', 200.0)
                )

            # ── 카메라 전환 감지 (3-state) ────────────────────────────────
            _stability_required = int(getattr(cfg, 'stability_required_sec', 4.0) * fps)
            _stability_thr  = getattr(cfg, 'stability_diff_threshold', 8.0)
            _relearn_abort  = getattr(cfg, 'relearn_abort_diff', 15.0)

            if not st.is_learning and not self.is_simulation:
                if not st.relearning and not st.waiting_stable:
                    if self.switch.check(frame, st.frame_num, st.cooldown_until):
                        print(f"📷 [{self.cctv_name}] 카메라 전환 감지 → 안정 대기")
                        st.waiting_stable     = True
                        st.stable_since_frame = st.frame_num
                        self._track_direction.clear()

                elif st.waiting_stable:
                    self.switch.check(frame, st.frame_num, st.cooldown_until)
                    if self.switch.last_adj_diff > _stability_thr:
                        st.stable_since_frame = st.frame_num
                    elif st.frame_num - st.stable_since_frame >= _stability_required:
                        print(f"✅ [{self.cctv_name}] 안정 확인 → 재학습 시작")
                        st.waiting_stable = False
                        st.reset_for_relearn()
                        self.flow.reset()
                        self._ref_direction = None
                        _relearn_smooth_80 = _relearn_smooth_95 = False

                elif st.relearning:
                    self.switch.check(frame, st.frame_num, st.cooldown_until)
                    if self.switch.last_adj_diff > _relearn_abort:
                        print(f"⚠️ [{self.cctv_name}] 재학습 중 불안정 → 안정 대기 복귀")
                        st.relearning = False
                        st.waiting_stable     = True
                        st.stable_since_frame = st.frame_num
                        self.flow.reset()
                        _relearn_smooth_80 = _relearn_smooth_95 = False

            # ── 초기 학습 완료 처리 ───────────────────────────────────────
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
                    self.flow.apply_boundary_erosion()
                    self._compute_ref_direction()
                    _rd = self._ref_direction or (1.0, 0.0)
                    self.flow.build_directional_channels(_rd[0], _rd[1])
                    st.is_learning = False
                    print(f"✅ [{self.cctv_name}] 초기 학습 완료! frame={st.frame_num}")
                    self._save_cache(frame)

            # ── 재학습 완료 처리 ─────────────────────────────────────────
            if st.relearning:
                elapsed     = st.frame_num - st.relearn_start_frame
                max_relearn = int(cfg.relearn_frames * cfg.max_learning_extension)
                ratio       = elapsed / cfg.relearn_frames
                if not _relearn_smooth_80 and ratio >= 0.80:
                    self.flow.apply_spatial_smoothing(verbose=False)
                    _relearn_smooth_80 = True
                if not _relearn_smooth_95 and ratio >= 0.95:
                    self.flow.apply_spatial_smoothing(verbose=False)
                    _relearn_smooth_95 = True
                if elapsed >= cfg.relearn_frames or elapsed >= max_relearn:
                    self.flow.apply_spatial_smoothing(verbose=True)
                    self.flow.apply_boundary_erosion()
                    self._compute_ref_direction()
                    _rd = self._ref_direction or (1.0, 0.0)
                    self.flow.build_directional_channels(_rd[0], _rd[1])
                    st.relearning     = False
                    st.cooldown_until = st.frame_num + cfg.cooldown_frames
                    self.switch.set_reference(frame)
                    print(f"✅ [{self.cctv_name}] 재학습 완료!")
                    self._save_cache(frame)

            # ── YOLO 트래킹 ───────────────────────────────────────────────
            tracks     = _FRAME_POOL.submit(self.tracker.track, frame).result()
            active_ids = {t["id"] for t in tracks}

            for t in tracks:
                if t["id"] not in st.first_seen_frame:
                    st.first_seen_frame[t["id"]] = st.frame_num

            # ── 프레임 스킵 감지 ─────────────────────────────────────────
            _jump_thr   = _jump_thr_dynamic
            _jump_ratio = getattr(cfg, 'frame_skip_ratio', 0.5)
            _jc = _jt = 0
            for _t in tracks:
                _traj = st.trajectories.get(_t["id"])
                if _traj:
                    _d = ((_t["cx"] - _traj[-1][0])**2 + (_t["cy"] - _traj[-1][1])**2) ** 0.5
                    _jt += 1
                    if _d > _jump_thr:
                        _jc += 1
            _is_frame_skip = _jt >= 2 and _jc / _jt >= _jump_ratio
            if _is_frame_skip:
                if st.frame_num - _last_skip_log >= _SKIP_LOG_COOL:
                    print(f"[{self.cctv_name}] ⚠️ 프레임 스킵 ({_jc}/{_jt}) → 스킵")
                    _last_skip_log = st.frame_num
                _apply_frame_skip_reset(st, tracks, st.frame_num)

            # ── 세션 알림 상태 확인 ───────────────────────────────────────
            already_sent = shared.alert_sent_session.get(session_key, False) if session_key else False

            # ── 차량별 처리 ───────────────────────────────────────────────
            for t in tracks:
                tid          = t["id"]
                x1, y1, x2, y2 = t["x1"], t["y1"], t["x2"], t["y2"]
                cx, cy       = t["cx"], t["cy"]
                fx, fy       = cx, cy

                # 방향 분류
                if (not st.is_learning and not st.relearning and not st.waiting_stable
                        and self._ref_direction is not None):
                    traj_cur = st.trajectories[tid]
                    win = min(cfg.velocity_window, len(traj_cur))
                    if win >= 3:
                        ddx  = traj_cur[-1][0] - traj_cur[-win][0]
                        ddy  = traj_cur[-1][1] - traj_cur[-win][1]
                        dmag = np.sqrt(ddx**2 + ddy**2)
                        if dmag > 1.0:
                            ref_x, ref_y = self._ref_direction
                            cos_d = (ddx / dmag) * ref_x + (ddy / dmag) * ref_y
                            self._track_direction[tid] = 'a' if cos_d >= cfg.lane_cos_threshold else 'b'
                        else:
                            self._track_direction[tid] = self._classify_direction(fx, fy)
                    else:
                        self._track_direction[tid] = self._classify_direction(fx, fy)

                # ID 재매칭
                if not st.is_learning and not st.relearning and not st.waiting_stable:
                    self.idm.check_reappear(tid, cx, cy)

                # 단독 jump 체크
                _solo_jump = False
                if st.trajectories[tid]:
                    _prev = st.trajectories[tid][-1]
                    _solo_d = ((_fx := fx) - _prev[0])**2 + ((_fy := fy) - _prev[1])**2
                    if _solo_d ** 0.5 > _jump_thr * 1.5:
                        _solo_jump = True
                        _apply_solo_jump_reset(st, tid, (fx, fy), st.frame_num)

                # 궤적 갱신 (EMA 스무딩)
                age = st.frame_num - st.first_seen_frame.get(tid, st.frame_num)
                if age >= 3 and not _is_frame_skip and not _solo_jump:
                    if st.trajectories[tid]:
                        px, py = st.trajectories[tid][-1]
                        fx = 0.4 * fx + 0.6 * px
                        fy = 0.4 * fy + 0.6 * py
                    st.trajectories[tid].append((fx, fy))
                if len(st.trajectories[tid]) > cfg.trail_length:
                    st.trajectories[tid].pop(0)

                traj = st.trajectories[tid]
                is_wrong = False
                ndx = ndy = 0.0
                mag = 0.0

                # 속도 계산 (중앙값 벡터)
                if len(traj) >= cfg.velocity_window:
                    _w   = cfg.velocity_window
                    _si  = len(traj) - _w
                    _pfx = [traj[_si+i+1][0] - traj[_si+i][0] for i in range(_w-1)]
                    _pfy = [traj[_si+i+1][1] - traj[_si+i][1] for i in range(_w-1)]
                    vdx  = float(np.median(_pfx)) * (_w - 1)
                    vdy  = float(np.median(_pfy)) * (_w - 1)
                    mag  = np.sqrt(vdx**2 + vdy**2)

                    if mag > 1.0:
                        ndx, ndy = vdx / mag, vdy / mag
                        bh       = max(y2 - y1, cfg.min_bbox_h)
                        nm_move  = mag / bh

                        if nm_move > cfg.norm_learn_threshold:
                            if _is_frame_skip or _solo_jump:
                                pass
                            elif st.is_learning or st.relearning:
                                learn_min_mag = max(1.0, bh * cfg.norm_learn_threshold)
                                self.flow.learn_step(
                                    traj[-_w][0], traj[-_w][1], fx, fy, learn_min_mag,
                                    bbox=(x1, y1, x2, y2),
                                    traj_ndx=ndx, traj_ndy=ndy,
                                )
                            elif not st.waiting_stable and not already_sent:
                                # ✅ detector_modules judge 호출 (정교한 판정)
                                is_wrong, _, _ = self.judge.check(
                                    tid, traj, ndx, ndy, mag, cy,
                                    bbox_h=bh,
                                    track_dir=self._track_direction.get(tid),
                                )
                                if is_wrong and tid in st.wrong_way_ids:
                                    self.idm.assign_label(tid)
                else:
                    if tid in st.wrong_way_ids:
                        is_wrong = True

                # ── 역주행 신규 탐지 → 알림 ──────────────────────────────
                if tid in st.wrong_way_ids and tid not in self._wrongway_alerted and not already_sent:
                    self._wrongway_alerted.add(tid)
                    if session_key:
                        shared.alert_sent_session[session_key] = True
                    label = self.idm.get_display_label(tid) or str(tid)
                    self.alert_queue.put((frame.copy(), datetime.now(), tid))
                    print(f"🚨 [{self.cctv_name}] 역주행 탐지 ID:{tid} label:{label}")

                # ── 시각화 ────────────────────────────────────────────────
                color = (0, 0, 255) if (is_wrong or tid in st.wrong_way_ids) else (0, 255, 0)

                # 1. 바운딩 박스
                # cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)

                # 2. 화살표 표시 (추가된 부분)
                # ndx, ndy는 -1~1 사이의 정규화된 방향 벡터입니다.
                # mag(속도)가 어느 정도 있을 때만 화살표를 그립니다.
                if mag > 1.0:
                    arrow_length = 22  # 화살표 길이 (픽셀)
                    start_pt = (int(cx), int(cy))
                    end_pt = (int(cx + ndx * arrow_length), int(cy + ndy * arrow_length))
                    
                    # tipLength: 화살표 촉의 크기 비율
                    cv2.arrowedLine(frame, start_pt, end_pt, color, 2, tipLength=0.3)

                # 3. 라벨 텍스트
                label_text = self.idm.get_display_label(tid) or f"{tid}"
                cv2.putText(frame, label_text, (int(x1)+7, int(y1)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

            # ── 퇴장 차량 정리 ────────────────────────────────────────────
            gone = set(st.trajectories.keys()) - active_ids
            for g in gone:
                self._track_direction.pop(g, None)
                self._wrongway_alerted.discard(g)

            with self.frame_lock:
                self.latest_frame = frame

            time.sleep(0.01)

    # ────────────────────────────────────────────────────────────────────
    # reconnect 오버라이드
    # ────────────────────────────────────────────────────────────────────

    def reconnect(self, delay=3, max_retries=5):
        if not hasattr(self, 'cap') or self.cap is None:
            return False
        for i in range(max_retries):
            if not self.is_running:
                return False
            print(f"📡 [{self.cctv_name}] 재연결 시도 ({i+1}/{max_retries})...")
            try:
                self.cap.release()
                time.sleep(delay)
                self.cap = _FRAME_POOL.submit(_open_cap_ffmpeg, self.url).result()
                if self.cap.isOpened():
                    print(f"✅ [{self.cctv_name}] 재연결 성공")
                    return True
            except Exception as e:
                print(f"⚠️ [{self.cctv_name}] 재연결 오류: {e}")
        print(f"❌ [{self.cctv_name}] {max_retries}회 재연결 실패")
        return False

    def stop(self):
        super().stop()
        if self.cap is not None:
            if self.cap.isOpened():
                self.cap.release()
            self.cap = None
        print(f"🛑 [{self.cctv_name}] ReverseDetector 정지")