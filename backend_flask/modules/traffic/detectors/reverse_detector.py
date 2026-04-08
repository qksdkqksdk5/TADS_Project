import cv2
import numpy as np
import os
import time
import threading
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from ultralytics import YOLO

from .base_detector import BaseDetector
from .reverse_modules.config import DetectorConfig
from .reverse_modules.tracker import YoloTracker
from .reverse_modules.flow_map import FlowMap
from .reverse_modules.judge import WrongWayJudge
from .reverse_modules.bbox_stabilizer import BBoxStabilizer
from .reverse_modules.id_manager import IDManager
from .reverse_modules.camera_switch import CameraSwitchDetector
from shared.discord_helper import send_discord_notification
import shared.state as shared
from modules.traffic.detectors.manager import detector_manager

# ✅ .env의 USE_GPU=true/false 로 GPU/CPU 전환
_USE_GPU = os.getenv('USE_GPU', 'false').lower() == 'true'

# 시뮬레이션용과 실전용 모델을 따로 담을 딕셔너리 마련
_shared_reverse_models = {}
_reverse_model_lock = threading.Lock()

def get_shared_reverse_model(is_simulation):
    global _shared_reverse_models
    
    # 딕셔너리에 저장할 키값 설정 ('sim' 또는 'real')
    model_key = 'sim' if is_simulation else 'real'
    
    # 해당 키의 모델이 아직 없다면 최초 1회 로드
    if model_key not in _shared_reverse_models:
        with _reverse_model_lock:
            if model_key not in _shared_reverse_models: # 더블 체크
                _DIR = os.path.dirname(os.path.abspath(__file__))
                
                if _USE_GPU:
                    if is_simulation:
                        model_path = os.path.join(_DIR, "detect_models/best_DW_sim.pt")
                    else:
                        model_path = os.path.join(_DIR, "detect_models/best_DW.pt")
                    print(f"🚀 [System] Reverse GPU 모델({model_key}) 최초 1회 로드 완료")
                    _shared_reverse_models[model_key] = YOLO(model_path).to('cuda')
                    
                else:
                    if is_simulation:
                        model_path = os.path.join(_DIR, "detect_models/best_DW_sim_openvino_model")
                    else:
                        model_path = os.path.join(_DIR, "detect_models/best_DW_v2.pt")
                    print(f"🚀 [System] Reverse CPU 모델({model_key}) 최초 1회 로드 완료")
                    # task='detect' 추가로 경고 메시지 방지
                    _shared_reverse_models[model_key] = YOLO(model_path, task='detect')
                    
    return _shared_reverse_models[model_key]

class State:
    def __init__(self):
        self.frame_num           = 0
        self.frame_w             = 0
        self.frame_h             = 0
        self.video_fps           = 30.0
        self.is_learning         = False
        self.relearning          = False
        self.relearn_start_frame = 0
        self.cooldown_until      = 0
        self.trajectories        = defaultdict(list)
        self.wrong_way_count     = defaultdict(int)
        self.wrong_way_ids       = set()
        self.last_cos_values     = defaultdict(list)
        self.wrong_way_last_pos  = {}
        self.display_id_map      = {}
        self.next_wrong_way_label = 1
        self.first_seen_frame    = {}
        self.first_suspect_frame = {}
        self.detection_stats     = {}
        self._stale_counter      = defaultdict(int)
        self.alerted_ids         = set()

    def reset_for_relearn(self):
        print("🔄 카메라 전환 감지 → 재학습 시작")
        self.wrong_way_ids.clear()
        self.wrong_way_count.clear()
        self.wrong_way_last_pos.clear()
        self.display_id_map.clear()
        self.trajectories.clear()
        self.last_cos_values.clear()
        self._stale_counter.clear()
        self.alerted_ids.clear()
        self.relearning          = True
        self.relearn_start_frame = self.frame_num


def discord_task(url, location, image_path):
    from shared.discord_helper import send_discord_notification
    send_discord_notification(
        url,
        event_type="역주행",
        location=location,
        image_path=image_path
    )

class ReverseDetector(BaseDetector):
    def __init__(self, cctv_name, url, lat=37.5, lng=127.0,
                 socketio=None, db=None, ResultModel=None, ReverseModel=None,
                 conf=None, app=None,
                 is_simulation=False,
                 realtime_url=None,
                 video_origin="realtime_its"):
        super().__init__(cctv_name, url, app=app, socketio=socketio, db=db, ResultModel=ResultModel)

        self.realtime_url = realtime_url if realtime_url else url
        self.original_url = url
        self.lat           = lat
        self.lng           = lng
        self.ReverseModel  = ReverseModel
        self.is_simulation = is_simulation
        self.video_origin = f"{video_origin}_{cctv_name}"

        conf_val = float(os.getenv('CONFIDENCE_THRESHOLD') or conf or 0.66)
        self.cfg = DetectorConfig(conf=conf_val)
        self.st  = State()

        _DIR = os.path.dirname(os.path.abspath(__file__))

        self.model = get_shared_reverse_model(self.is_simulation)
        mode_str = "시뮬레이션" if self.is_simulation else "실제 CCTV"
        print(f"💻 [{cctv_name}] ReverseDetector 준비 완료 ({mode_str} 공유 모델 사용)")

        if url == 0 or url == "0":
            self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        else:
            self.cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.tracker         = YoloTracker(self.model, conf=self.cfg.conf, use_gpu=_USE_GPU)
        self.flow_map        = FlowMap(grid_size=self.cfg.grid_size, alpha=self.cfg.alpha, min_samples=self.cfg.min_samples)
        self.judge           = WrongWayJudge(self.cfg, self.flow_map, self.st)
        self.stabilizer      = BBoxStabilizer(alpha=0.5)
        self.id_manager      = IDManager(self.cfg, self.flow_map, self.st)
        self.camera_detector = CameraSwitchDetector(self.cfg)

        safe_name       = cctv_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        self.save_dir   = "learned_models"
        os.makedirs(self.save_dir, exist_ok=True)
        self.model_file = Path(self.save_dir) / f"flow_{safe_name}.npy"

        self.load_flow_map()

    def load_flow_map(self):
        if self.flow_map.load(self.model_file):
            self.st.is_learning = False
            print(f"✅ [{self.cctv_name}] 학습 모델 로드 완료")
        else:
            self.st.is_learning = not self.is_simulation # 시뮬레이션은 자동학습 안함
            print(f"⚠️ [{self.cctv_name}] flow_map 없음")

    def save_flow_map(self):
        self.flow_map.save(self.model_file)

    def process_alert(self, data):
        frame, alert_time, track_id = data
        try:
            with self.app.app_context():
                new_alert = self.ResultModel(
                    event_type="reverse",
                    address=self.cctv_name,
                    latitude=self.lat, longitude=self.lng,
                    detected_at=alert_time,
                    is_simulation=self.is_simulation,
                    video_origin=self.video_origin,
                    is_resolved=False
                )
                self.db.session.add(new_alert)
                self.db.session.flush()

                # ts        = alert_time.strftime("%Y%m%d_%H%M%S")
                # filename  = f"reverse_{new_alert.id}_{ts}.jpg"
                # save_path = os.path.join(self.app.root_path, "static", "captures")
                # os.makedirs(save_path, exist_ok=True)
                # cv2.imwrite(os.path.join(save_path, filename), frame)

                ts = alert_time.strftime("%Y%m%d_%H%M%S")
                filename = f"fire_{new_alert.id}_{ts}.jpg"
                save_dir = os.path.join(self.app.root_path, "static", "captures")
                os.makedirs(save_dir, exist_ok=True)
                
                full_image_path = os.path.join(save_dir, filename) # 실제 서버 파일 경로
                cv2.imwrite(full_image_path, frame)

                from models import ReverseResult
                reverse_detail = ReverseResult(
                    result_id=new_alert.id,
                    image_path=f"/static/captures/{filename}",
                    vehicle_info=f"ID:{track_id} 탐지"
                )
                self.db.session.add(reverse_detail)
                self.db.session.commit()

                # MY_DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1486171062763917493/iXzgoMLR0--lCf3YsPRyTXgan40UNS_WXnKstiwPfAGxk5bjihwFiyTWqAaHEMVWseqk"
                MY_DISCORD_WEBHOOK_URL = ""

                import threading
                threading.Thread(
                    target=discord_task, 
                    args=(MY_DISCORD_WEBHOOK_URL, self.cctv_name, full_image_path),
                    daemon=True
                ).start()

                if self.socketio:
                    self.socketio.emit('anomaly_detected', {
                        "alert_id": new_alert.id, "type": "역주행",
                        "address": self.cctv_name,
                        "lat": float(self.lat), "lng": float(self.lng),
                        "video_origin": self.video_origin,
                        "is_simulation": self.is_simulation,
                        "image_url": f"/static/captures/{filename}"
                    })
                print(f"🚨 [역주행 알람 완료] {self.cctv_name} - ID:{track_id}")
        except Exception as e:
            self.db.session.rollback()
            print(f"❌ 역주행 비동기 저장 에러: {e}")

    def _detect_bytetrack_reset(self, active_ids, st):
        if not active_ids:
            return

        current_max = max(st.first_seen_frame.keys()) if st.first_seen_frame else 0
        new_ids = [tid for tid in active_ids if tid not in st.first_seen_frame]

        # ID 리셋 조건: 신규 ID가 들어왔는데 번호가 너무 낮아진 경우 (ByteTrack 초기화 징후)
        if new_ids and current_max > 50 and min(new_ids) < 10:
            
            # 1. 공통 데이터 청소 (이건 시뮬레이션이든 아니든 해야 꼬이지 않음)
            st.trajectories.clear()
            st.wrong_way_count.clear()
            st.wrong_way_ids.clear()
            st.wrong_way_last_pos.clear()
            st._stale_counter.clear()
            st.first_seen_frame.clear()
            st.first_suspect_frame.clear()
            st.alerted_ids.clear()
            self.stabilizer.smoothed.clear()

            # 2. 핵심 분기 처리
            if self.is_simulation:
                # ✅ 시뮬레이션이면 절대로 st.is_learning을 True로 바꾸지 않음!
                # 기존에 로드된 .npy(flow_map)를 끝까지 믿고 가야 함
                print(f"🔄 [{self.cctv_name}] 시뮬레이션 중 ID 리셋 감지: 데이터만 초기화 후 기존 모델로 계속 탐지")
            else:
                # ✅ 실제 CCTV일 때만 재학습 모드 허용
                print(f"🔄 [{self.cctv_name}] 실제 CCTV 리셋 감지: 재학습(Learning Mode)으로 전환합니다.")
                st.is_learning = True 
                st.frame_num = 0  
                self.flow_map.reset()

    def switch_mode(self, is_simulation, video_path=None, npy_path=None, recovery_url=None):
        # 1. 기존 리소스 해제
        if self.cap and self.cap.isOpened():
            self.cap.release()
        
        # 2. 상태 객체 '완전' 재생성
        self.st = State() 
        self.is_simulation = is_simulation
        
        # 3. [핵심] 하위 모듈들이 새로운 State 객체를 바라보도록 재생성/업데이트
        # 이 부분이 빠지면 id_manager 등이 옛날 데이터를 참조해서 꼬입니다.
        self.tracker = YoloTracker(self.model, conf=self.cfg.conf, use_gpu=_USE_GPU)
        self.judge = WrongWayJudge(self.cfg, self.flow_map, self.st)
        self.id_manager = IDManager(self.cfg, self.flow_map, self.st)
        self.stabilizer.smoothed.clear()

        # 4. URL 결정
        target_url = video_path if is_simulation else (recovery_url if recovery_url else self.original_url)
        print(f"🔄 [Mode Switch] {'Simulation' if is_simulation else 'Realtime'} 모드로 전환: {target_url}")
        
        # 5. 캡처 객체 생성
        if is_simulation:
            self.cap = cv2.VideoCapture(target_url, cv2.CAP_FFMPEG)
        else:
            self.cap = cv2.VideoCapture(target_url, cv2.CAP_FFMPEG)
            self.load_flow_map()
            self.st.cooldown_until = 150 # 복구 후 약 5초간 안정화 대기

    def run(self):
        session_key = self.video_origin if self.video_origin in shared.alert_sent_session else None
        cfg, st = self.cfg, self.st
        frame_count = 0
        mode_str = "GPU" if _USE_GPU else "CPU(OpenVINO)"
        input_fps = self.cap.get(cv2.CAP_PROP_FPS)
        if input_fps < 1 or input_fps > 60:
            input_fps = 20.0 
        
        frame_delay = 1.0 / input_fps
        print(f"🚗 [{self.cctv_name}] 분석 시작 (Target FPS: {input_fps})")

        try:
            while self.is_running:
                start_time = time.time()

                success, frame = self.cap.read()

                if not self.is_simulation:
                    self.cap.grab()

                if not success or frame is None:
                    if self.is_simulation:
                        print(f"🎬 [{self.cctv_name}] 시뮬레이션 종료 → 스레드를 정지합니다.")
                        self.is_running = False # 루프 탈출
                        break 
                    else:
                        # 실시간 모드일 때만 재연결 시도
                        if not self.reconnect():
                            time.sleep(5)
                        continue

                # 1. 전처리 및 업데이트
                frame = cv2.resize(frame, (640, 360))
                frame_count += 1

                if frame_count % 2 != 0:
                    shared.latest_frames[self.video_origin] = frame
                    with self.frame_lock:
                        self.latest_frame = frame
                    self._sync_fps(start_time, frame_delay) # 여기서도 똑같은 시간만큼 대기!
                    continue

                shared.latest_frames[self.video_origin] = frame
                with self.frame_lock:
                    self.latest_frame = frame

                # CPU 모드 프레임 스킵 (실시간 전용)
                # if not _USE_GPU and frame_count % 2 != 0 and not self.is_simulation:
                #     self.cap.grab()
                #     time.sleep(0.01)
                #     continue

                # 2. 분석 초기화
                h, w = frame.shape[:2]
                if self.flow_map.frame_w == 0:
                    st.frame_w, st.frame_h = w, h
                    self.flow_map.init_grid(w, h)
                st.frame_num += 1

                # 3. 카메라 이동 감지
                if not st.is_learning and not st.relearning:
                    if self.camera_detector.check(frame, st.frame_num, st.cooldown_until):
                        st.reset_for_relearn()
                        self.flow_map.reset()

                # 4. 학습 처리
                if st.is_learning and st.frame_num >= cfg.learning_frames:
                    self.flow_map.apply_spatial_smoothing()
                    self.flow_map.save(self.model_file)
                    st.is_learning = False
                    print(f"✅ [{self.cctv_name}] 학습 완료")

                # 5. 트래킹 및 판단
                tracks = self.tracker.track(frame)
                active_ids = {t["id"] for t in tracks}
                
                if not st.is_learning:
                    self._detect_bytetrack_reset(active_ids, st)

                already_sent = shared.alert_sent_session.get(session_key, False) if session_key else False
                pending_alert_id = None

                for t in tracks:
                    tid = t["id"]
                    if tid not in st.first_seen_frame: st.first_seen_frame[tid] = st.frame_num
                    
                    raw_bbox = (t["x1"], t["y1"], t["x2"], t["y2"])
                    x1, y1, x2, y2, cx, cy = self.stabilizer.stabilize(tid, raw_bbox, st.frame_num)

                    if not st.is_learning and not st.relearning:
                        self.id_manager.check_reappear(tid, cx, cy)

                    st.trajectories[tid].append((cx, cy))
                    if len(st.trajectories[tid]) > cfg.trail_length: st.trajectories[tid].pop(0)

                    traj = st.trajectories[tid]
                    is_wrong = False

                    if len(traj) >= cfg.velocity_window:
                        vdx = traj[-1][0] - traj[-cfg.velocity_window][0]
                        vdy = traj[-1][1] - traj[-cfg.velocity_window][1]
                        mag = np.sqrt(vdx**2 + vdy**2)
                        
                        if mag > cfg.min_move_distance:
                            ndx, ndy = vdx / mag, vdy / mag
                            if st.is_learning or st.relearning:
                                self.flow_map.learn_step(traj[-cfg.velocity_window][0], traj[-cfg.velocity_window][1], cx, cy, cfg.min_move_distance)
                            else:
                                # ✅ 추가: 쿨타임(모드 전환 직후) 중에는 카메라 전환 감지가 배경을 확인할 수 있도록 역주행 판단(judge)을 스킵
                                if st.frame_num < st.cooldown_until:
                                    pass # 판단 보류
                                else:
                                    is_wrong, _, _ = self.judge.check(tid, traj, ndx, ndy, mag, cy)
                                    if cfg.enable_online_flow_update and not is_wrong and not self.is_simulation:
                                        self.flow_map.learn_step(traj[-cfg.velocity_window][0], traj[-cfg.velocity_window][1], cx, cy, cfg.min_move_distance)

                                if is_wrong and tid in st.wrong_way_ids:
                                    self.id_manager.assign_label(tid)
                                    if tid not in st.alerted_ids and not already_sent:
                                        st.alerted_ids.add(tid)
                                        if session_key: shared.alert_sent_session[session_key] = True
                                        pending_alert_id = tid
                    elif tid in st.wrong_way_ids:
                        is_wrong = True

                    # 시각화
                    color = (0, 0, 255) if (is_wrong or tid in st.wrong_way_ids) else (0, 255, 0)
                    cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                    cv2.putText(frame, self.id_manager.get_display_label(tid) or f"ID:{tid}", 
                                (int(x1), int(y1) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                if pending_alert_id is not None:
                    self.alert_queue.put((frame.copy(), datetime.now(), pending_alert_id))

                if st.frame_num % 30 == 0:
                    self.id_manager.cleanup(active_ids)
                    self.stabilizer.cleanup(active_ids)
                
                self._sync_fps(start_time, frame_delay)

        except Exception as e:
            import traceback
            traceback.print_exc()

    # ✅ FPS 동기화를 위한 헬퍼 메서드 추가
    def _sync_fps(self, start_time, frame_delay):
        elapsed = time.time() - start_time
        wait_time = frame_delay - elapsed
        if wait_time > 0:
            time.sleep(wait_time)
        else:
            time.sleep(0.001) # 최소한의 휴식으로 CPU 과열 방지

    def stop(self):
        super().stop()
        if self.cap.isOpened(): self.cap.release()