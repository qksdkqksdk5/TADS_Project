import threading
import time
import cv2
import numpy as np
import os


class TunnelV51Service:
    def __init__(self):
        self.lock = threading.Lock()

        self.running = False
        self.thread = None
        self.latest_frame = None
        self.cap = None

        base_dir = os.path.dirname(__file__)
        self.video_path = os.path.join(base_dir, "raw_video", "test_accident.mp4")

        self.latest_data = {
            "state": "NORMAL",
            "avg_speed": 0,
            "vehicle_count": 0,
            "vehicles": [],
            "dwell_times": {},
            "events": [],
            "accident": False,
            "accident_label": "NONE",
            "lane_count_estimated": 0,
            "frame_id": 0,
            "source_name": "idle"
        }

    def add_event(self, message):
        self.latest_data["events"].append(message)
        self.latest_data["events"] = self.latest_data["events"][-10:]

    def start(self):
        with self.lock:
            if self.running:
                self.add_event("[service] already running")
                return

            if not os.path.exists(self.video_path):
                self.add_event("[service] video file not found")
                return

            self.running = True
            self.latest_data["source_name"] = "test_accident.mp4"
            self.latest_data["frame_id"] = 0
            self.add_event("[service] started")

            self.cap = cv2.VideoCapture(self.video_path)

            self.thread = threading.Thread(target=self.run_loop, daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            if not self.running:
                self.add_event("[service] already stopped")
                return

            self.running = False
            self.latest_data["source_name"] = "stopped"
            self.add_event("[service] stopped")

            if self.cap is not None:
                self.cap.release()
                self.cap = None

            stopped_frame = np.zeros((360, 640, 3), dtype=np.uint8)
            cv2.putText(
                stopped_frame, "SMART TUNNEL V5_1", (20, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2
            )
            cv2.putText(
                stopped_frame, "service stopped", (20, 160),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 100, 255), 2
            )
            self.latest_frame = stopped_frame

    def run_loop(self):
        while True:
            with self.lock:
                if not self.running:
                    break
                cap = self.cap

            if cap is None:
                break

            success, frame = cap.read()

            if not success:
                with self.lock:
                    if self.cap is not None:
                        self.cap.release()
                    self.cap = cv2.VideoCapture(self.video_path)
                    cap = self.cap
                continue

            frame = cv2.resize(frame, (640, 360))

            with self.lock:
                self.latest_data["frame_id"] += 1
                frame_id = self.latest_data["frame_id"]
                state = self.latest_data["state"]
                source_name = self.latest_data["source_name"]

                # =========================
                # 더미 상태값 생성
                # =========================
                if frame_id < 80:
                    self.latest_data["state"] = "NORMAL"
                    self.latest_data["avg_speed"] = 12.4
                    self.latest_data["vehicle_count"] = 4
                    self.latest_data["vehicles"] = [
                        {"id": 1, "speed": 13.1},
                        {"id": 2, "speed": 12.5},
                        {"id": 3, "speed": 11.7},
                        {"id": 4, "speed": 12.3},
                    ]
                    self.latest_data["dwell_times"] = {
                        "1": 2.1,
                        "2": 2.8,
                        "3": 3.0,
                        "4": 2.4,
                    }
                    self.latest_data["accident"] = False
                    self.latest_data["accident_label"] = "NONE"
                    self.latest_data["lane_count_estimated"] = 2

                elif frame_id < 160:
                    self.latest_data["state"] = "CONGESTION"
                    self.latest_data["avg_speed"] = 6.8
                    self.latest_data["vehicle_count"] = 7
                    self.latest_data["vehicles"] = [
                        {"id": 1, "speed": 7.1},
                        {"id": 2, "speed": 6.5},
                        {"id": 3, "speed": 6.0},
                        {"id": 4, "speed": 7.4},
                        {"id": 5, "speed": 5.9},
                        {"id": 6, "speed": 6.3},
                        {"id": 7, "speed": 7.0},
                    ]
                    self.latest_data["dwell_times"] = {
                        "1": 6.2,
                        "2": 7.0,
                        "3": 8.5,
                        "4": 6.7,
                        "5": 9.3,
                        "6": 7.4,
                        "7": 8.1,
                    }
                    self.latest_data["accident"] = False
                    self.latest_data["accident_label"] = "NONE"
                    self.latest_data["lane_count_estimated"] = 2

                elif frame_id < 240:
                    self.latest_data["state"] = "JAM"
                    self.latest_data["avg_speed"] = 2.3
                    self.latest_data["vehicle_count"] = 10
                    self.latest_data["vehicles"] = [
                        {"id": 1, "speed": 2.1},
                        {"id": 2, "speed": 2.5},
                        {"id": 3, "speed": 1.8},
                        {"id": 4, "speed": 2.7},
                        {"id": 5, "speed": 2.0},
                        {"id": 6, "speed": 2.2},
                        {"id": 7, "speed": 1.9},
                        {"id": 8, "speed": 2.4},
                        {"id": 9, "speed": 2.1},
                        {"id": 10, "speed": 2.0},
                    ]
                    self.latest_data["dwell_times"] = {
                        "1": 12.1,
                        "2": 15.3,
                        "3": 18.4,
                        "4": 10.8,
                        "5": 14.7,
                        "6": 16.2,
                        "7": 19.5,
                        "8": 13.1,
                        "9": 17.0,
                        "10": 20.4,
                    }
                    self.latest_data["accident"] = False
                    self.latest_data["accident_label"] = "NONE"
                    self.latest_data["lane_count_estimated"] = 2

                else:
                    self.latest_data["state"] = "ACCIDENT"
                    self.latest_data["avg_speed"] = 0.8
                    self.latest_data["vehicle_count"] = 8
                    self.latest_data["vehicles"] = [
                        {"id": 1, "speed": 0.0},
                        {"id": 2, "speed": 0.5},
                        {"id": 3, "speed": 1.1},
                        {"id": 4, "speed": 0.7},
                        {"id": 5, "speed": 0.9},
                        {"id": 6, "speed": 0.2},
                        {"id": 7, "speed": 0.4},
                        {"id": 8, "speed": 0.0},
                    ]
                    self.latest_data["dwell_times"] = {
                        "1": 22.4,
                        "2": 25.0,
                        "3": 18.9,
                        "4": 27.1,
                        "5": 24.8,
                        "6": 31.2,
                        "7": 28.0,
                        "8": 35.6,
                    }
                    self.latest_data["accident"] = True
                    self.latest_data["accident_label"] = "ACCIDENT_SUSPECT"
                    self.latest_data["lane_count_estimated"] = 2

                    # 이벤트 로그는 너무 자주 쌓이지 않게 조건부로
                    if frame_id % 30 == 0:
                        self.add_event("[event] 사고 의심 감지")

                state = self.latest_data["state"]
            cv2.putText(
                frame, "SMART TUNNEL V5_1", (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2
            )
            cv2.putText(
                frame, f"frame_id: {frame_id}", (20, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
            )
            cv2.putText(
                frame, f"state: {state}", (20, 105),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
            )
            cv2.putText(
                frame, f"source: {source_name}", (20, 140),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 2
            )

            with self.lock:
                self.latest_frame = frame

            time.sleep(0.03)

    def get_status(self):
        with self.lock:
            return dict(self.latest_data)

    def get_jpeg_frame(self):
        with self.lock:
            if self.latest_frame is None:
                return None

            ok, buffer = cv2.imencode(".jpg", self.latest_frame)
            if not ok:
                return None

            return buffer.tobytes()


tunnel_service = TunnelV51Service()