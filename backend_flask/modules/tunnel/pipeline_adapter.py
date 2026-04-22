# ==========================================
# 파일명: pipeline_adapter.py
# 위치: backend_flask/modules/tunnel/pipeline_adapter.py
# 역할:
# - YOLO + ByteTrack 수행
# - tunnel_main_V5_5 시각화 흐름을 웹용으로 반영
# - pipeline_V5_5/PipelineCore 연결
# - 프론트(status API)용 결과 정리
# - CCTV 변경 시 full reset 지원
# ==========================================

import os
import sys
import cv2
import traceback
from ultralytics import YOLO
import time
from collections import deque


class TunnelPipelineAdapter:
    def __init__(self):
        self.current_dir = os.path.dirname(os.path.abspath(__file__))

        # ------------------------------------------
        # 1) YOLO 모델 로드
        # ------------------------------------------
        self.model_path = os.path.join(self.current_dir, "models", "best.pt")
        self.model = YOLO(self.model_path)

        # ------------------------------------------
        # 2) 내부 파이프라인 경로 연결
        # ------------------------------------------
        pipeline_dir = os.path.join(self.current_dir, "pipeline_V5_5")
        if pipeline_dir not in sys.path:
            sys.path.append(pipeline_dir)

        # ------------------------------------------
        # 3) 실제 파이프라인 import
        # ------------------------------------------
        from pipeline_core_V5_5 import PipelineCore
        self.PipelineCore = PipelineCore

        self.pipeline = None
        self.frame_height = 720
        self.current_cctv_name = None

        self.last_result = {
            "state": "READY",
            "avg_speed": 0.0,
            "vehicle_count": 0,
            "accident": False,
            "lane_count": 0,
            "events": [],
            "frame_id": 0,
            "analysis": {},
        }

        self.track_first_seen = {}
        self.event_logs = deque(maxlen=10)
        self.prev_state_text = None
        self.prev_accident_flag = False
        self.prev_roi_fallback = None
        self.prev_template_confirmed = None

    # =========================================================
    # 1) CCTV 변경 시 full reset
    # =========================================================
    def reset_pipeline(self):
        print("♻️ TunnelPipelineAdapter full reset")

        # YOLO tracker 상태까지 완전히 초기화
        self.model = YOLO(self.model_path)

        # 내부 파이프라인도 완전 초기화
        self.pipeline = None
        self.frame_height = 720
        self.current_cctv_name = None

        self.last_result = {
            "state": "READY",
            "avg_speed": 0.0,
            "vehicle_count": 0,
            "accident": False,
            "lane_count": 0,
            "events": [],
            "frame_id": 0,
            "analysis": {},
        }

        self.track_first_seen = {}
        self.event_logs = deque(maxlen=10)
        self.prev_state_text = None
        self.prev_accident_flag = False
        self.prev_roi_fallback = None
        self.prev_template_confirmed = None

    # =========================================================
    # 2) 파이프라인 lazy init
    # =========================================================
    def _ensure_pipeline(self, frame):
        if self.pipeline is None:
            self.frame_height = frame.shape[0]

            lane_output_dir = os.path.join(self.current_dir, "outputs", "lane_debug")
            os.makedirs(lane_output_dir, exist_ok=True)

            self.pipeline = self.PipelineCore(
                frame_height=self.frame_height,
                lane_output_dir=lane_output_dir
            )

    # =========================================================
    # 3) YOLO + ByteTrack
    # =========================================================
    def _run_yolo_track(self, frame):
        yolo_results = self.model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=[0],
            conf=0.25,
            verbose=False
        )

        tracks = []

        if yolo_results and len(yolo_results) > 0:
            r = yolo_results[0]

            if r.boxes is not None and r.boxes.id is not None:
                boxes_xyxy = r.boxes.xyxy.cpu().numpy()
                ids = r.boxes.id.cpu().numpy().astype(int)

                for box, tid in zip(boxes_xyxy, ids):
                    x1, y1, x2, y2 = box.tolist()
                    tracks.append({
                        "id": int(tid),
                        "bbox": (int(x1), int(y1), int(x2), int(y2))
                    })

        return tracks

    # =========================================================
    # 4) 시각화 함수들
    # =========================================================
    def _draw_centerlines(self, frame, centerlines, lane_y1, lane_y2):
        for lane in centerlines:
            lane_id = lane.get("lane_id", -1)
            model = lane.get("rep_model", {})

            if not model:
                continue

            pts = []

            for y in range(int(lane_y1), int(lane_y2), 20):
                if model.get("type") == "linear":
                    coef = model.get("coef", [0, 0])
                    if len(coef) < 2:
                        continue
                    a, b = coef[:2]
                    x = a * y + b
                else:
                    coef = model.get("coef", [0, 0, 0])
                    if len(coef) < 3:
                        continue
                    a, b, c = coef[:3]
                    x = a * (y ** 2) + b * y + c

                pts.append((int(x), int(y)))

            for i in range(1, len(pts)):
                cv2.line(frame, pts[i - 1], pts[i], (255, 255, 0), 2)

            if pts:
                cv2.putText(
                    frame,
                    f"LANE {lane_id}",
                    pts[len(pts) // 2],
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 0),
                    2
                )

    def _draw_tracks(self, frame, tracks, merged_analysis):
        boxes = merged_analysis.get("boxes", {})
        speeds = merged_analysis.get("speeds", {})
        lane_map = merged_analysis.get("lane_map", {})
        raw_lane_map = merged_analysis.get("raw_lane_map", {})

        for t in tracks:
            tid = t["id"]

            bbox = boxes.get(tid, t.get("bbox"))
            if not bbox:
                continue

            x1, y1, x2, y2 = bbox
            speed = speeds.get(tid, 0.0)
            raw_lane = raw_lane_map.get(tid, None)
            lane = lane_map.get(tid, None)

            cv2.rectangle(
                frame,
                (int(x1), int(y1)),
                (int(x2), int(y2)),
                (0, 255, 0),
                2
            )

            text = f"ID:{tid} V:{speed:.1f} raw:{raw_lane} lane:{lane}"
            cv2.putText(
                frame,
                text,
                (int(x1), max(20, int(y1) - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                2
            )

    def _draw_roi_lines(self, frame, merged_analysis):
        h, w = frame.shape[:2]

        roi_y1 = merged_analysis.get("roi_y1")
        roi_y2 = merged_analysis.get("roi_y2")

        if roi_y1 is None:
            roi_y1 = merged_analysis.get("roi_raw_y1", int(h * 0.2))
        if roi_y2 is None:
            roi_y2 = merged_analysis.get("roi_raw_y2", int(h * 0.8))

        roi_y1 = int(roi_y1)
        roi_y2 = int(roi_y2)

        used_fallback = bool(
            merged_analysis.get("roi_used_fallback", False)
            or merged_analysis.get("roi_fallback", False)
        )

        color = (0, 255, 255) if used_fallback else (255, 0, 0)

        cv2.line(frame, (0, roi_y1), (w, roi_y1), color, 2)
        cv2.line(frame, (0, roi_y2), (w, roi_y2), color, 2)

        roi_text = f"ROI: {roi_y1}-{roi_y2}"
        if used_fallback:
            roi_text += " fallback"

        cv2.putText(
            frame,
            roi_text,
            (20, max(25, roi_y1 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2
        )

    def _draw_summary(self, frame, result, frame_id):
        merged = result.get("analysis", {})
        state_result = result.get("state", {})
        accident_result = result.get("accident", {})

        display_frame_id = frame_id
        vehicle_count = merged.get("vehicle_count", 0)

        if isinstance(state_result, dict):
            state_debug = state_result.get("debug", {})
            state_text = state_result.get("state", "UNKNOWN")
        else:
            state_debug = {}
            state_text = str(state_result)

        avg_speed = state_debug.get("buffer_avg_speed", 0.0)

        if isinstance(accident_result, dict):
            accident_flag = accident_result.get("accident", False)
            accident_text = "True" if accident_flag else "False"
        else:
            accident_text = str(accident_result)

        if state_text == "NORMAL":
            state_color = (0, 255, 0)
        elif state_text == "CONGESTION":
            state_color = (0, 165, 255)
        elif state_text == "JAM":
            state_color = (0, 0, 255)
        else:
            state_color = (255, 255, 255)

        accident_color = (0, 0, 255) if accident_text == "True" else (255, 255, 255)

        panel_x = 12
        panel_y = 12
        panel_w = 300
        row_h = 34
        header_h = 38
        panel_h = header_h + row_h * 5 + 12

        overlay = frame.copy()
        cv2.rectangle(
            overlay,
            (panel_x, panel_y),
            (panel_x + panel_w, panel_y + panel_h),
            (30, 30, 30),
            -1
        )
        alpha = 0.65
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

        cv2.rectangle(
            frame,
            (panel_x, panel_y),
            (panel_x + panel_w, panel_y + panel_h),
            (180, 180, 180),
            1
        )

        cv2.putText(
            frame,
            "SMART TUNNEL",
            (panel_x + 12, panel_y + 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72,
            (255, 255, 255),
            2
        )

        cv2.line(
            frame,
            (panel_x + 8, panel_y + header_h),
            (panel_x + panel_w - 8, panel_y + header_h),
            (120, 120, 120),
            1
        )

        rows = [
            ("Frame ID", str(display_frame_id), (255, 255, 255)),
            ("State", state_text, state_color),
            ("Vehicles", str(vehicle_count), (255, 255, 255)),
            ("Avg Speed", f"{float(avg_speed):.2f}", (255, 255, 255)),
            ("Accident", accident_text, accident_color),
        ]

        label_x = panel_x + 14
        value_x = panel_x + 155
        start_y = panel_y + header_h + 24

        for i, (label, value, value_color) in enumerate(rows):
            y = start_y + i * row_h

            if i > 0:
                line_y = y - 18
                cv2.line(
                    frame,
                    (panel_x + 10, line_y),
                    (panel_x + panel_w - 10, line_y),
                    (70, 70, 70),
                    1
                )

            cv2.putText(
                frame,
                label,
                (label_x, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.58,
                (210, 210, 210),
                2
            )

            cv2.putText(
                frame,
                value,
                (value_x, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.60,
                value_color,
                2
            )

    def _append_event_log(self, message):
        if not message:
            return

        timestamp = time.strftime("%H:%M:%S")
        log_text = f"[{timestamp}] {message}"

        # 완전 같은 메시지가 연속으로 쌓이지 않게만 방지
        if len(self.event_logs) == 0 or self.event_logs[-1] != log_text:
            self.event_logs.append(log_text)

    # =========================================================
    # 5) 프론트(status API)용 값 정리
    # =========================================================
    def _build_front_status(self, result, frame_id, tracks):
        merged = result.get("analysis", {})
        state_result = result.get("state", {})
        accident_result = result.get("accident", {})

        vehicle_count = merged.get("vehicle_count", 0)

        if isinstance(state_result, dict):
            state_text = state_result.get("state", "UNKNOWN")
            state_debug = state_result.get("debug", {})
            avg_speed = float(state_debug.get("buffer_avg_speed", 0.0))
        else:
            state_text = str(state_result)
            avg_speed = 0.0

        if isinstance(accident_result, dict):
            accident_flag = bool(accident_result.get("accident", False))
        elif isinstance(accident_result, bool):
            accident_flag = accident_result
        else:
            accident_flag = False

        lane_count = merged.get("lane_count", 0)

        speeds = merged.get("speeds", {})
        lane_map = merged.get("lane_map", {})
        raw_lane_map = merged.get("raw_lane_map", {})
        boxes = merged.get("boxes", {})

    # -----------------------------
    # 1) vehicles + dwell_times 생성
    # -----------------------------
        now_ts = time.time()
        current_ids = set()
        vehicles = []
        dwell_times = {}

        for t in tracks:
            tid = int(t["id"])
            current_ids.add(tid)

            if tid not in self.track_first_seen:
                self.track_first_seen[tid] = now_ts

            dwell_sec = round(now_ts - self.track_first_seen[tid], 2)
            dwell_times[str(tid)] = dwell_sec

            bbox = boxes.get(tid, t.get("bbox"))
            speed = float(speeds.get(tid, 0.0))
            lane = lane_map.get(tid, None)
            raw_lane = raw_lane_map.get(tid, None)

            vehicles.append({
                "id": tid,
                "speed": round(speed, 2),
                "lane": lane,
                "raw_lane": raw_lane,
                "dwell_time": dwell_sec,
                "bbox": bbox,
            })

    # 현재 화면에서 사라진 차량은 추적 시간 메모리에서 제거
        stale_ids = [tid for tid in list(self.track_first_seen.keys()) if tid not in current_ids]
        for tid in stale_ids:
            del self.track_first_seen[tid]

    # -----------------------------
    # 2) 이벤트 로그 생성
    # -----------------------------
        roi_fallback = bool(merged.get("roi_used_fallback", False))
        template_confirmed = bool(merged.get("template_confirmed", False))

        if self.prev_state_text is None:
            self.prev_state_text = state_text
        elif self.prev_state_text != state_text:
            self._append_event_log(f"상태 변경: {self.prev_state_text} → {state_text}")
            self.prev_state_text = state_text

        if (not self.prev_accident_flag) and accident_flag:
            self._append_event_log("사고 감지")
        self.prev_accident_flag = accident_flag

        if self.prev_roi_fallback is None:
            self.prev_roi_fallback = roi_fallback
        elif self.prev_roi_fallback != roi_fallback:
            if roi_fallback:
                self._append_event_log("ROI fallback 사용")
            else:
                self._append_event_log("ROI 자동설정 정상 복귀")
            self.prev_roi_fallback = roi_fallback

        if self.prev_template_confirmed is None:
            self.prev_template_confirmed = template_confirmed
        elif self.prev_template_confirmed != template_confirmed:
            if template_confirmed:
                self._append_event_log("차선 bootstrap 완료")
            else:
                self._append_event_log("차선 bootstrap 중")
            self.prev_template_confirmed = template_confirmed

    # -----------------------------
    # 3) 기존 events 유지
    # -----------------------------
        events = []
        if roi_fallback:
            events.append("ROI fallback 사용")
        if accident_flag:
            events.append("사고 감지")
        if not template_confirmed:
            events.append("차선 bootstrap 중")

        return {
            "state": state_text,
            "avg_speed": avg_speed,
            "vehicle_count": vehicle_count,
            "accident": accident_flag,
            "lane_count": lane_count,
            "events": events,
            "event_logs": list(self.event_logs),
            "vehicles": vehicles,
            "dwell_times": dwell_times,
            "frame_id": frame_id,
            "analysis": merged,
        }

    # =========================================================
    # 6) 메인 처리
    # =========================================================
    def process_frame(self, frame, frame_id):
        annotated = frame.copy()

        try:
            if self.pipeline is None:
                self._ensure_pipeline(frame)

            tracks = self._run_yolo_track(frame)

            if self.pipeline is None:
                self._ensure_pipeline(frame)

            if self.pipeline is None:
                ready_result = {
                    "state": "READY",
                    "avg_speed": 0.0,
                    "vehicle_count": 0,
                    "accident": False,
                    "lane_count": 0,
                    "events": ["pipeline initializing"],
                    "frame_id": frame_id,
                    "analysis": {},
                }
                self.last_result = ready_result
                return annotated, ready_result

            result = self.pipeline.process(frame_id, tracks, frame.shape[1], cctv_name=self.current_cctv_name)
            merged = result.get("analysis", {})

            lane_y1 = int(
                merged.get("roi_y1", merged.get("roi_raw_y1", frame.shape[0] * 0.20))
            )
            lane_y2 = int(
                merged.get("roi_y2", merged.get("roi_raw_y2", frame.shape[0] * 0.95))
            )

            # ROI는 샘플이 있거나 fallback이면 표시
            if merged.get("roi_sample_count", 0) > 0 or merged.get("roi_fixed", False):
                self._draw_roi_lines(annotated, merged)

            # 차선은 template_confirmed 이후에만 표시
            if merged.get("template_confirmed", False):
                self._draw_centerlines(
                    annotated,
                    merged.get("centerlines", []),
                    lane_y1,
                    lane_y2
                )

            self._draw_tracks(annotated, tracks, merged)
            # self._draw_summary(annotated, result, frame_id) # 화면 속 정보 패널 제거

            front_status = self._build_front_status(result, frame_id, tracks)
            self.last_result = front_status

            return annotated, front_status

        except Exception as e:
            print(f"❌ pipeline_adapter 처리 실패: {e}")
            traceback.print_exc()

            error_result = {
                "state": "ERROR",
                "avg_speed": 0.0,
                "vehicle_count": 0,
                "accident": False,
                "lane_count": 0,
                "events": [f"pipeline error: {e}"],
                "frame_id": frame_id,
                "analysis": {},
            }
            self.last_result = error_result

            return annotated, error_result