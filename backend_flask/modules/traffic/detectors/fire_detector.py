from multiprocessing import dummy

import cv2
import os
import time
import threading
from datetime import datetime
from ultralytics import YOLO
import numpy as np

from shared.discord_helper import send_discord_notification
from .base_detector import BaseDetector
import shared.state as shared

# ✅ .env의 USE_GPU=true/false 로 GPU/CPU 전환
_USE_GPU = os.getenv('USE_GPU', 'false').lower() == 'true'


# 전역 변수로 모델을 한 번만 저장할 공간 마련
_shared_fire_model = None
_model_lock = threading.Lock() # 스레드 동시 접근 방지

def get_shared_fire_model():
    global _shared_fire_model
    # 모델이 아직 로드되지 않았다면 최초 1회만 로드
    if _shared_fire_model is None:
        with _model_lock:
            if _shared_fire_model is None: # 더블 체크
                _DIR = os.path.dirname(os.path.abspath(__file__))
                if _USE_GPU:
                    _shared_fire_model = YOLO(os.path.join(_DIR, "detect_models/best_SB.pt")).to('cuda')
                    print("🚀 [System] FireDetector GPU 모델 최초 1회 로드 완료")
                else:
                    # 아까 발생했던 task 경고를 없애기 위해 task='detect' 추가
                    _shared_fire_model = YOLO(os.path.join(_DIR, "detect_models/best_SB_openvino_model"), task='detect')
                    print("🚀 [System] FireDetector CPU(OpenVINO) 모델 최초 1회 로드 완료")
    return _shared_fire_model

class FireDetector(BaseDetector):
    def __init__(self, cctv_name, url, lat=37.5, lng=127.0,
                 socketio=None, db=None, ResultModel=None, app=None,
                 is_simulation=False,
                 video_origin="realtime_its"):
        super().__init__(cctv_name, url, app=app, socketio=socketio, db=db, ResultModel=ResultModel)

        self.url = url
        self.cap = None
        self.lat           = lat
        self.lng           = lng
        self.is_simulation = is_simulation
        if is_simulation:
            self.video_origin = video_origin
        else:
            self.video_origin = f"{video_origin}_{cctv_name}"

        self.model = get_shared_fire_model()
        print(f"💻 [{cctv_name}] FireDetector 준비 완료 (공유 모델 사용)")

        dummy = np.zeros((320, 320, 3), dtype=np.uint8)
        self.model.predict(dummy, imgsz=320, verbose=False)

        self._class_names       = self.model.names
        self.FIRE_THRESHOLD     = 0.10
        self.SMOKE_THRESHOLD    = 0.25
        self.CONF_THRESHOLD     = 0.10
        self.CONSECUTIVE_FRAMES = 10

        self._consecutive_count = 0
        self._alarm_active      = False

        # if url == 0 or url == "0":
        #     self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        #     self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        #     self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        #     self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # else:
        #     self.cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        #     self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.is_alerting = False

    def _apply_class_threshold(self, results):
        boxes      = results[0].boxes
        detections = []

        for box in boxes:
            cls_id   = int(box.cls[0])
            conf     = float(box.conf[0])
            cls_name = self._class_names.get(cls_id, f"unknown_{cls_id}")

            if cls_name == "fire":
                threshold = self.FIRE_THRESHOLD
            elif cls_name == "smoke":
                threshold = self.SMOKE_THRESHOLD
            else:
                threshold = self.CONF_THRESHOLD

            if conf >= threshold:
                b = box.xyxy[0].cpu().numpy() if _USE_GPU else box.xyxy[0].numpy()
                detections.append({
                    "class": cls_name,
                    "conf":  round(conf, 4),
                    "bbox":  [int(b[0]), int(b[1]), int(b[2]), int(b[3])]
                })

        return detections

    def _check_consecutive(self, detected):
        if detected:
            self._consecutive_count += 1
        else:
            self._consecutive_count = 0
            self._alarm_active      = False

        if self._consecutive_count >= self.CONSECUTIVE_FRAMES:
            if not self._alarm_active:
                self._alarm_active = True
                return True
        return False

    def _reset_consecutive(self):
        self._consecutive_count = 0
        self._alarm_active      = False

    def process_alert(self, data):
        frame, alert_time = data
        try:
            with self.app.app_context():
                new_alert = self.ResultModel(
                    event_type="fire",
                    address=self.cctv_name,
                    latitude=self.lat,
                    longitude=self.lng,
                    detected_at=alert_time,
                    is_simulation=self.is_simulation,
                    video_origin=self.video_origin,
                    is_resolved=False
                )
                self.db.session.add(new_alert)
                self.db.session.flush()

                # ts        = alert_time.strftime("%Y%m%d_%H%M%S")
                # filename  = f"fire_{new_alert.id}_{ts}.jpg"
                # save_path = os.path.join(self.app.root_path, "static", "captures")
                # os.makedirs(save_path, exist_ok=True)
                # cv2.imwrite(os.path.join(save_path, filename), frame)

                # 2. 이미지 파일 저장 (디스코드 전송을 위해 전체 경로가 필요함)
                ts = alert_time.strftime("%Y%m%d_%H%M%S")
                filename = f"fire_{new_alert.id}_{ts}.jpg"
                save_dir = os.path.join(self.app.root_path, "static", "captures")
                os.makedirs(save_dir, exist_ok=True)
                
                full_image_path = os.path.join(save_dir, filename) # 실제 서버 파일 경로
                cv2.imwrite(full_image_path, frame)

                from models import FireResult
                fire_detail = FireResult(
                    result_id=new_alert.id,
                    image_path=f"/static/captures/{filename}",
                    fire_severity="중간"
                )
                self.db.session.add(fire_detail)
                self.db.session.commit()

                # MY_DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1486171062763917493/iXzgoMLR0--lCf3YsPRyTXgan40UNS_WXnKstiwPfAGxk5bjihwFiyTWqAaHEMVWseqk"
                MY_DISCORD_WEBHOOK_URL = ""
                
                send_discord_notification(
                    MY_DISCORD_WEBHOOK_URL,
                    event_type="🔥 화재 발생",
                    location=self.cctv_name,
                    image_path=full_image_path
                )

                if self.socketio:
                    self.socketio.emit('anomaly_detected', {
                        "alert_id":     new_alert.id,
                        "type":         "화재",
                        "address":      self.cctv_name,
                        "lat":          float(self.lat),
                        "lng":          float(self.lng),
                        "video_origin": self.video_origin,
                        "is_simulation": self.is_simulation,
                        "image_url":    f"/static/captures/{filename}"
                    })
                print(f"🔥 [화재 알람 완료] {self.cctv_name} - ID:{new_alert.id}")

        except Exception as e:
            self.db.session.rollback()
            print(f"❌ 화재 비동기 저장 에러: {e}")

    def run(self):

        # ✅ [추가] 실제 분석 스레드 내부에서 VideoCapture를 생성합니다.
        if self.url == 0 or self.url == "0":
            self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        else:
            # 💡 환경변수 OPENCV_FFMPEG_THREADS=1과 함께 작동하여 충돌을 방지합니다.
            self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)


        session_key = self.video_origin if self.video_origin in shared.alert_sent_session else None
        mode_str    = "GPU" if _USE_GPU else "CPU(OpenVINO)"

        print(f"🔥 [{self.cctv_name}] 분석 시작 {mode_str} (is_simulation={self.is_simulation})")
        self._reset_consecutive()

        while self.is_running and self.cap.isOpened():
            success, frame = self.cap.read()
            if not success:
                if self.is_simulation:
                    print(f"🏁 [{self.cctv_name}] 시뮬레이션 영상 종료")
                    time.sleep(1)
                    self.stop()
                    break  # ← continue 대신 break
                else:
                    reconnected = self.reconnect(delay=3, max_retries=5)
                    if not reconnected:
                        time.sleep(10)
                    continue

            shared.latest_frames[self.video_origin] = frame

            # ✅ GPU/CPU 추론 옵션 분기
            predict_kwargs = {
                "conf":    self.CONF_THRESHOLD,
                "imgsz":   320,
                "verbose": False,
            }
            if _USE_GPU:
                predict_kwargs["device"] = 0
                predict_kwargs["half"]   = True

            results    = self.model.predict(frame, **predict_kwargs)
            detections = self._apply_class_threshold(results)
            fire_found = len(detections) > 0

            if fire_found:
                for d in detections:
                    x1, y1, x2, y2 = d["bbox"]
                    label = f"{d['class']} {d['conf']:.2f}"
                    color = (0, 0, 255) if d["class"] == "fire" else (0, 128, 255)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, label, (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            already_sent = shared.alert_sent_session.get(session_key, False) if session_key else False

            if session_key and not already_sent and self.is_alerting:
                self.is_alerting = False
                self._reset_consecutive()

            new_alarm = self._check_consecutive(fire_found)

            if new_alarm and not self.is_alerting and not already_sent:
                self.is_alerting = True
                if session_key:
                    shared.alert_sent_session[session_key] = True
                self.alert_queue.put((frame.copy(), datetime.now()))
                print(f"🔥 [{self.cctv_name}] {self.CONSECUTIVE_FRAMES}프레임 연속 감지 → 알람 발동")

            elif not fire_found:
                self.is_alerting = False

            with self.frame_lock:
                self.latest_frame = frame

            time.sleep(0.1)

    def stop(self):
        super().stop()
        # ✅ [수정] self.cap이 존재할 때만 닫기 작업을 수행합니다.
        if self.cap is not None:
            if self.cap.isOpened():
                self.cap.release()
            self.cap = None # 깔끔하게 비워줍니다.