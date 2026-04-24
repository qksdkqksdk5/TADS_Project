import cv2
import time
import threading
from queue import Queue

class BaseDetector:
    def __init__(self, cctv_name, url, app=None, socketio=None, db=None, ResultModel=None):
        self.cctv_name = cctv_name
        self.url = url
        self.app = app
        self.socketio = socketio
        self.db = db
        self.ResultModel = ResultModel
        
        self.is_running = True
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.alert_queue = Queue()
        
        self.start_alert_worker()

    def start_alert_worker(self):
        def worker():
            while self.is_running:
                if not self.alert_queue.empty():
                    data = self.alert_queue.get()
                    try:
                        # ✅ 핵심 수정: self.app이 있다면 컨텍스트를 수동으로 열어줌
                        if self.app:
                            with self.app.app_context():
                                self.process_alert(data)
                        else:
                            # 앱 객체가 없을 경우를 대비한 예외 처리
                            self.process_alert(data)
                    except Exception as e:
                        print(f"❌ [Worker Error] {self.cctv_name}: {e}")
                time.sleep(0.1)
        
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def reconnect(self, delay=3, max_retries=5):
        """
        ✅ ITS CCTV 연결 끊김 시 자동 재연결
        - cap은 자식 클래스에 있으므로 hasattr로 확인
        - 재연결 성공하면 True, 실패하면 False 반환
        """
        if not hasattr(self, 'cap'):
            return False

        for i in range(max_retries):
            if not self.is_running:
                return False

            print(f"📡 [{self.cctv_name}] 재연결 시도 ({i+1}/{max_retries})...")
            try:
                self.cap.release()
                time.sleep(delay)
                self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                if self.cap.isOpened():
                    print(f"✅ [{self.cctv_name}] 재연결 성공")
                    return True
            except Exception as e:
                print(f"⚠️ [{self.cctv_name}] 재연결 중 오류: {e}")

        print(f"❌ [{self.cctv_name}] {max_retries}회 재연결 실패 — 대기 후 재시도 예정")
        return False

    def generate_frames(self):
        last_frame = None
        
        while self.is_running:
            with self.frame_lock:
                frame = self.latest_frame.copy() if self.latest_frame is not None else None

            if frame is not None:
                if last_frame is None or last_frame is not frame:
                    last_frame = frame
                    ret, buffer = cv2.imencode(
                        ".jpg", last_frame, [cv2.IMWRITE_JPEG_QUALITY, 60]
                    )
                    if not ret:
                        continue
                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' +
                        buffer.tobytes() +
                        b'\r\n'
                    )

            time.sleep(0.03)

    def process_alert(self, data):
        raise NotImplementedError("자식 클래스에서 process_alert를 반드시 구현해야 합니다.")

    def stop(self):
        self.is_running = False
        # ✅ 추가: cap 객체가 있다면 안전하게 릴리즈
        if hasattr(self, 'cap') and self.cap is not None:
            self.cap.release()
            print(f"📹 [{self.cctv_name}] VideoCapture 해제 완료")
        print(f"🛑 [{self.cctv_name}] 분석 프로세스 종료")