# ==========================================
# 파일명: service.py
# 위치: backend_flask/modules/tunnel/service.py
# 역할:
# - 프론트에서 받은 CCTV 후보 리스트 캐시
# - 캐시된 리스트 기반 랜덤 선택 / 이름 선택
# - CCTV 변경 시 이전 스트림 종료 + 파이프라인 reset
# - 연결 가능한 CCTV health 관리
# - 영상 스트리밍
# - 최신 상태 저장
# - 단일 스트림 보호
# - lane_template 수동 재추정 요청 연결
# - 사고 이벤트 캡처/저장
# - 환기 대응 위험도 계산 / 상태 포함
# ==========================================

import os
import json
import random
import threading
import cv2
import time
from datetime import datetime

from .pipeline_adapter import TunnelPipelineAdapter
from .ventilation_risk import VentilationRiskManager
from .ventilation_bridge import build_ventilation_result


class TunnelLiveService:
    def __init__(self):
        self.lock = threading.Lock()

        # 프론트가 넘겨준 CCTV 후보 리스트
        self.cached_cctv_list = []

        self.current_cctv = None
        self.pipeline = TunnelPipelineAdapter()
        self.active_cctv_name = None

        # CCTV 변경 시 이전 스트림 종료용 토큰
        self.stream_token = 0

        # 단일 스트림 보호용
        self.stream_lock = threading.Lock()
        self.stream_active = False

        # CCTV 연결 상태 관리
        self.cctv_health = {}

        # ==================================================
        # 환기 대응 매니저
        # ==================================================
        self.ventilation_manager = VentilationRiskManager(fps=10)

        # 설정 확정값
        self.ventilation_manager.capacity_per_lane = 10
        self.ventilation_manager.weight_clip_min = 0.8
        self.ventilation_manager.weight_clip_max = 1.5
        self.ventilation_manager.accident_state_bonus = 0.15
        self.ventilation_manager.free_flow_speed = 8.0
        self.ventilation_manager.max_dwell_time = 60.0

        # 차선 수별 기준 승용차 bbox
        self.ventilation_manager.set_bbox_ref(2, 3500.0)
        self.ventilation_manager.set_bbox_ref(3, 2600.0)
        self.ventilation_manager.set_bbox_ref(4, 2000.0)

        # 필요 시 500m 환산 활성화
        # self.ventilation_manager.enable_tunnel_scaling(True, default_roi_est_length=50.0)

        # --------------------------------------------------
        # 최신 상태 캐시
        # --------------------------------------------------
        self.latest_status = {
            "state": "READY",
            "avg_speed": 0.0,
            "vehicle_count": 0,
            "accident": False,
            "lane_count": 0,
            "events": [],
            "frame_id": 0,
            "cctv_name": "-",
            "cctv_url": "",

            "lane_reestimate_status": "idle",
            "lane_reestimate_frame_count": 0,
            "lane_reestimate_window": 50,

            "minute_vehicle_count": 0,

            "ventilation": {
                "risk_score_base": 0.0,
                "risk_score_final": 0.0,
                "risk_level": "NORMAL",
                "alarm": False,
                "message": "공기질 상태 정상",
                "vehicle_count_roi": 0,
                "weighted_vehicle_count": 0.0,
                "traffic_density": 0.0,
                "avg_dwell_time_roi": 0.0,
            }
        }

        # ==================================================
        # 사고 이벤트 저장 폴더
        # ==================================================
        self.event_root = os.path.join(os.path.dirname(__file__), "event_storage")
        self.event_snapshot_dir = os.path.join(self.event_root, "snapshots")
        self.event_log_dir = os.path.join(self.event_root, "logs")

        os.makedirs(self.event_snapshot_dir, exist_ok=True)
        os.makedirs(self.event_log_dir, exist_ok=True)

        self.last_saved_accident_frame = -999999
        self.accident_save_cooldown = 180

    # =========================================================
    # 1) CCTV 목록 관리
    # =========================================================
    def get_cctv_list(self):
        return self.cached_cctv_list

    def refresh_cctv_list(self):
        return self.cached_cctv_list

    def set_cctv_list(self, cctv_list):
        if not isinstance(cctv_list, list):
            return False

        cleaned = []
        for item in cctv_list:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()

            if not name or not url:
                continue

            cleaned.append({
                "name": name,
                "url": url
            })

        if not cleaned:
            return False

        self.cached_cctv_list = cleaned

        self.cctv_health = {}
        for cctv in self.cached_cctv_list:
            self.cctv_health[cctv["url"]] = {
                "ok": None,
                "fail_count": 0,
            }

        print(f"📡 [최초 캐시 저장] {len(self.cached_cctv_list)}개 CCTV 고정 완료")
        return True

    # =========================================================
    # 2) 상태 업데이트
    # =========================================================
    def get_status(self):
        with self.lock:
            data = dict(self.latest_status)

        data.setdefault("lane_reestimate_status", "idle")
        data.setdefault("lane_reestimate_frame_count", 0)
        data.setdefault("lane_reestimate_window", 50)
        data.setdefault("minute_vehicle_count", 0)
        data.setdefault("ventilation", {
            "risk_score_base": 0.0,
            "risk_score_final": 0.0,
            "risk_level": "NORMAL",
            "alarm": False,
            "message": "공기질 상태 정상",
        })

        return data

    def _update_status(self, data):
        with self.lock:
            self.latest_status.update(data)

            self.latest_status.setdefault("lane_reestimate_status", "idle")
            self.latest_status.setdefault("lane_reestimate_frame_count", 0)
            self.latest_status.setdefault("lane_reestimate_window", 50)
            self.latest_status.setdefault("minute_vehicle_count", 0)
            self.latest_status.setdefault("ventilation", {
                "risk_score_base": 0.0,
                "risk_score_final": 0.0,
                "risk_level": "NORMAL",
                "alarm": False,
                "message": "공기질 상태 정상",
            })

    # =========================================================
    # 2-1) 차선 재추정 요청
    # =========================================================
    def request_lane_reestimate(self):
        frame_id = self.latest_status.get("frame_id", 0)

        lane_template = None

        if hasattr(self.pipeline, "get_lane_template"):
            lane_template = self.pipeline.get_lane_template()

        if lane_template is None:
            return {
                "ok": False,
                "message": "lane_template 객체를 찾지 못했습니다."
            }

        if not hasattr(lane_template, "request_reestimate"):
            return {
                "ok": False,
                "message": "lane_template에 request_reestimate() 메서드가 없습니다."
            }

        lane_template.request_reestimate(frame_id=frame_id)

        self._update_status({
            "lane_reestimate_status": "reestimating",
            "lane_reestimate_frame_count": 0,
            "lane_reestimate_window": 50,
            "events": [f"차선 재추정 요청 접수 (frame={frame_id})"]
        })

        print(f"🔄 service 차선 재추정 요청 완료: frame_id={frame_id}")

        return {
            "ok": True,
            "message": "차선 재추정 요청 접수",
            "frame_id": frame_id,
            "window": 50
        }

    def save_current_lane_memory(self):
        lane_template = None

        if hasattr(self.pipeline, "get_lane_template"):
            lane_template = self.pipeline.get_lane_template()

        if lane_template is None:
            return {
                "ok": False,
                "message": "lane_estimator 객체를 찾지 못했습니다."
            }

        if not hasattr(lane_template, "save_lane_memory"):
            return {
                "ok": False,
                "message": "save_lane_memory() 메서드가 없습니다."
            }

        cctv_name = self.latest_status.get("cctv_name", "")
        save_path = lane_template.save_lane_memory(cctv_name=cctv_name)

        if not save_path:
            return {
                "ok": False,
                "message": "차선 저장 실패"
            }

        self._update_status({
            "events": [f"차선 저장 완료: {cctv_name}"]
        })

        return {
            "ok": True,
            "message": "현재 차선 저장 완료",
            "path": save_path
        }

    # =========================================================
    # 2-2) 사고 이벤트 캡처/저장
    # =========================================================
    def _save_accident_event(self, frame, status_data):
        accident_flag = bool(status_data.get("accident", False))
        frame_id = int(status_data.get("frame_id", 0))

        if not accident_flag:
            return

        if frame_id - self.last_saved_accident_frame < self.accident_save_cooldown:
            return

        self.last_saved_accident_frame = frame_id

        now = datetime.now()
        ts_compact = now.strftime("%Y%m%d_%H%M%S")
        ts_text = now.strftime("%Y-%m-%d %H:%M:%S")

        event_id = f"accident_{ts_compact}_{frame_id}"

        image_path = os.path.join(self.event_snapshot_dir, f"{event_id}.jpg")
        cv2.imwrite(image_path, frame)

        payload = {
            "event_id": event_id,
            "timestamp": ts_text,
            "frame_id": frame_id,
            "type": "accident",
            "state": "pending",
            "cctv_name": status_data.get("cctv_name", "-"),
            "cctv_url": status_data.get("cctv_url", ""),
            "avg_speed": float(status_data.get("avg_speed", 0.0)),
            "vehicle_count": int(status_data.get("vehicle_count", 0)),
            "lane_count": int(status_data.get("lane_count", 0)),
            "snapshot_path": image_path,
            "events": status_data.get("events", []),
            "ventilation": status_data.get("ventilation", {}),
        }

        json_path = os.path.join(self.event_log_dir, f"{event_id}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print(f"📸 사고 이벤트 저장 완료: {event_id}")

    # =========================================================
    # 2-3) 저장된 이벤트 목록 조회
    # =========================================================
    def get_saved_event_list(self):
        items = []

        if not os.path.exists(self.event_log_dir):
            return items

        for name in os.listdir(self.event_log_dir):
            if not name.endswith(".json"):
                continue

            path = os.path.join(self.event_log_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    items.append(data)
            except Exception:
                continue

        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items

    # =========================================================
    # 3) health 관리
    # =========================================================
    def _mark_cctv_success(self, cctv):
        url = cctv["url"]
        if url not in self.cctv_health:
            self.cctv_health[url] = {"ok": True, "fail_count": 0}
            return

        self.cctv_health[url]["ok"] = True
        self.cctv_health[url]["fail_count"] = 0

    def _mark_cctv_failure(self, cctv):
        url = cctv["url"]
        if url not in self.cctv_health:
            self.cctv_health[url] = {"ok": False, "fail_count": 1}
            return

        self.cctv_health[url]["ok"] = False
        self.cctv_health[url]["fail_count"] += 1

    def _get_healthy_candidates(self):
        healthy = []

        for cctv in self.cached_cctv_list:
            url = cctv["url"]
            health = self.cctv_health.get(url, {})
            fail_count = health.get("fail_count", 0)

            if fail_count < 10:  #ITS 스트림이 흔들리는 환경이면 나중에 10 → 15 정도로 완화
                healthy.append(cctv)

        return healthy

    # =========================================================
    # 4) CCTV 선택
    # =========================================================
    def select_random_cctv(self):
        candidates = self._get_healthy_candidates()

        if not candidates:
            print("⚠️ 건강한 CCTV 후보 없음 → 전체 캐시 리스트 사용")
            candidates = self.cached_cctv_list

        if not candidates:
            return None

        self.current_cctv = random.choice(candidates)
        self.active_cctv_name = None

        self.stream_active = False
        self.stream_token += 1

        self._update_status({
            "state": "READY",
            "avg_speed": 0.0,
            "vehicle_count": 0,
            "accident": False,
            "lane_count": 0,
            "events": ["CCTV 변경됨 - 분석 초기화 중"],
            "frame_id": 0,
            "cctv_name": self.current_cctv["name"],
            "cctv_url": self.current_cctv["url"],
            "lane_reestimate_status": "idle",
            "lane_reestimate_frame_count": 0,
            "lane_reestimate_window": 50,
            "minute_vehicle_count": 0,
            "ventilation": {
                "risk_score_base": 0.0,
                "risk_score_final": 0.0,
                "risk_level": "NORMAL",
                "alarm": False,
                "message": "공기질 상태 정상",
                "vehicle_count_roi": 0,
                "weighted_vehicle_count": 0.0,
                "traffic_density": 0.0,
                "avg_dwell_time_roi": 0.0,
            }
        })

        print(f"✅ 랜덤 선택 CCTV(캐시): {self.current_cctv['name']}")
        return self.current_cctv

    def select_cctv_by_name(self, name):
        keyword = (name or "").strip()
        if not keyword:
            return None

        def _reset_selected(cctv):
            self.current_cctv = cctv
            self.active_cctv_name = None
            self.stream_active = False
            self.stream_token += 1

            self.ventilation_manager.vehicle_entry_memory.clear()
            self.ventilation_manager.current_level = "NORMAL"
            self.ventilation_manager.pending_level = "NORMAL"
            self.ventilation_manager.pending_count = 0
            self.ventilation_manager.release_count = 0

            self._update_status({
                "state": "READY",
                "avg_speed": 0.0,
                "vehicle_count": 0,
                "accident": False,
                "lane_count": 0,
                "events": ["CCTV 변경됨 - 분석 초기화 중"],
                "frame_id": 0,
                "cctv_name": self.current_cctv["name"],
                "cctv_url": self.current_cctv["url"],
                "lane_reestimate_status": "idle",
                "lane_reestimate_frame_count": 0,
                "lane_reestimate_window": 50,
                "minute_vehicle_count": 0,
                "ventilation": {
                    "risk_score_base": 0.0,
                    "risk_score_final": 0.0,
                    "risk_level": "NORMAL",
                    "alarm": False,
                    "message": "공기질 상태 정상",
                    "vehicle_count_roi": 0,
                    "weighted_vehicle_count": 0.0,
                    "traffic_density": 0.0,
                    "avg_dwell_time_roi": 0.0,
                }
            })

        for cctv in self.cached_cctv_list:
            if keyword == cctv["name"]:
                _reset_selected(cctv)
                print(f"✅ 정확 이름으로 선택 CCTV: {self.current_cctv['name']}")
                return self.current_cctv

        for cctv in self.cached_cctv_list:
            if keyword in cctv["name"]:
                _reset_selected(cctv)
                print(f"✅ 부분 이름으로 선택 CCTV: {self.current_cctv['name']}")
                return self.current_cctv

        normalized_keyword = keyword.replace(" ", "")
        for cctv in self.cached_cctv_list:
            normalized_name = cctv["name"].replace(" ", "")
            if normalized_keyword in normalized_name:
                _reset_selected(cctv)
                print(f"✅ 정규화 이름으로 선택 CCTV: {self.current_cctv['name']}")
                return self.current_cctv

        return None

    # =========================================================
    # 5) CCTV 열기 테스트
    # =========================================================
    def _try_open_cctv(self, cctv):
        name = cctv["name"]
        url = cctv["url"]

        print(f"🎥 CCTV 연결 시도: {name}")
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)

    # --------------------------------------------------
    # 1) open 확인: 기존보다 더 길게 대기
    # --------------------------------------------------
        open_ok = False
        for _ in range(20):   # 기존 10 -> 20
            if cap.isOpened():
                open_ok = True
                break
            time.sleep(0.15)

        if not open_ok:
            print(f"❌ CCTV 연결 실패(open): {name}")
            self._mark_cctv_failure(cctv)
            cap.release()
            return None

    # --------------------------------------------------
    # 2) 첫 프레임 확인: 기존보다 더 길게 대기
    # --------------------------------------------------
        frame_ok = False
        for _ in range(40):   # 기존 20 -> 40
            ok, frame = cap.read()
            if ok and frame is not None:
                frame_ok = True
                break
            time.sleep(0.1)

        if not frame_ok:
            print(f"❌ CCTV 연결 실패(first frame): {name}")
            self._mark_cctv_failure(cctv)
            cap.release()
            return None

        print(f"✅ CCTV 연결 성공: {name}")
        self._mark_cctv_success(cctv)
        return cap

    # =========================================================
    # 6) 랜덤 열기
    # =========================================================
    def _open_stream_with_retry(self, tried_urls=None, max_retry=5):
        if tried_urls is None:
            tried_urls = set()

        candidates = self._get_healthy_candidates()

        if not candidates:
            print("⚠️ 건강한 CCTV 후보 없음 → 전체 캐시 리스트 사용")
            candidates = self.cached_cctv_list

        if not candidates:
            print("❌ 캐시된 CCTV 목록 비어있음")
            return None, None

        candidates = [c for c in candidates if c["url"] not in tried_urls]
        random.shuffle(candidates)

        retry_count = 0

        for cctv in candidates:
            if retry_count >= max_retry:
                break

            tried_urls.add(cctv["url"])

            cap = self._try_open_cctv(cctv)
            if cap is not None:
                self.current_cctv = cctv
                return cap, cctv

            retry_count += 1

        return None, None

    # =========================================================
    # 7) 스트리밍
    # =========================================================
    def generate_frames(self):
        if not self.stream_lock.acquire(blocking=False):
            print("⚠️ 기존 스트림 실행 중 → 새 요청 거절")
            self._update_status({
                "state": "READY",
                "events": ["기존 스트림 종료 후 다시 시도"],
            })
            return

        self.stream_active = True
        tried_urls = set()
        cap = None
        my_token = self.stream_token

        try:
            if self.current_cctv is not None:
                selected_cctv = self.current_cctv
                print(f"🎯 선택된 CCTV 우선 사용: {selected_cctv['name']}")
                cap = self._try_open_cctv(selected_cctv)

                if cap is None:
                    print(f"❌ 선택된 CCTV 열기 실패: {selected_cctv['name']}")
                    self._update_status({
                        "state": "ERROR",
                        "events": [f"선택한 CCTV 연결 실패: {selected_cctv['name']}"],
                        "cctv_name": selected_cctv["name"],
                        "cctv_url": selected_cctv["url"],
                    })
                    return
            else:
                selected_cctv = None

            if cap is None or selected_cctv is None:
                cap, selected_cctv = self._open_stream_with_retry(
                    tried_urls=tried_urls,
                    max_retry=5
                )

            if selected_cctv is not None:
                if self.active_cctv_name != selected_cctv["name"]:
                    self.pipeline.reset_pipeline()
                    self.active_cctv_name = selected_cctv["name"]

                    self.ventilation_manager.vehicle_entry_memory.clear()
                    self.ventilation_manager.current_level = "NORMAL"
                    self.ventilation_manager.pending_level = "NORMAL"
                    self.ventilation_manager.pending_count = 0
                    self.ventilation_manager.release_count = 0

                    print(f"♻️ 스트림 시작 시 reset 완료: {self.active_cctv_name}")

            if cap is None or selected_cctv is None:
                self._update_status({
                    "state": "ERROR",
                    "events": ["실시간 CCTV 연결 실패"],
                    "cctv_name": "-",
                    "cctv_url": "",
                })
                return

            frame_id = 0
            fail_count = 0

            self._update_status({
                "cctv_name": selected_cctv["name"],
                "cctv_url": selected_cctv["url"],
                "events": [f"{selected_cctv['name']} 연결 완료"],
            })

            while True:
                if my_token != self.stream_token:
                    print("🛑 새 CCTV 선택됨 → 이전 스트림 종료")
                    break

                if not self.stream_active:
                    print("🛑 stream_active=False → 스트림 종료")
                    break

                ok, frame = cap.read()

                if not ok or frame is None:
                    fail_count += 1
                    print(f"❌ 프레임 읽기 실패 ({fail_count})")

                    if fail_count >= 20:
                        print("⚠️ 스트림 재연결 시도")
                        cap.release()
                        cap = None

                        if self.current_cctv is not None:
                            print(f"🔁 현재 CCTV 재연결 시도: {self.current_cctv['name']}")
                            cap = self._try_open_cctv(self.current_cctv)

                            if cap is not None:
                                selected_cctv = self.current_cctv
                                fail_count = 0

                                if self.active_cctv_name != selected_cctv["name"]:
                                    self.pipeline.reset_pipeline()
                                    self.active_cctv_name = selected_cctv["name"]

                                    self.ventilation_manager.vehicle_entry_memory.clear()
                                    self.ventilation_manager.current_level = "NORMAL"
                                    self.ventilation_manager.pending_level = "NORMAL"
                                    self.ventilation_manager.pending_count = 0
                                    self.ventilation_manager.release_count = 0

                                    print(f"♻️ 재연결 후 reset 완료: {self.active_cctv_name}")

                                self._update_status({
                                    "cctv_name": selected_cctv["name"],
                                    "cctv_url": selected_cctv["url"],
                                    "events": [f"{selected_cctv['name']} 재연결 완료"],
                                })
                                continue

                            print(f"❌ 현재 CCTV 재연결 실패: {self.current_cctv['name']}")

                        self._update_status({
                            "state": "ERROR",
                            "events": ["선택한 CCTV 재연결 실패"],
                            "cctv_name": self.current_cctv["name"] if self.current_cctv else "-",
                            "cctv_url": self.current_cctv["url"] if self.current_cctv else "",
                        })
                        break

                    continue

                fail_count = 0
                frame_id += 1

                self.pipeline.current_cctv_name = selected_cctv["name"]

                annotated, result = self.pipeline.process_frame(frame, frame_id)

                if result is None:
                    result = {}

                result["cctv_name"] = selected_cctv["name"]
                result["cctv_url"] = selected_cctv["url"]

                if "lane_reestimate_status" not in result:
                    result["lane_reestimate_status"] = self.latest_status.get("lane_reestimate_status", "idle")

                if "lane_reestimate_frame_count" not in result:
                    result["lane_reestimate_frame_count"] = self.latest_status.get("lane_reestimate_frame_count", 0)

                if "lane_reestimate_window" not in result:
                    result["lane_reestimate_window"] = self.latest_status.get("lane_reestimate_window", 50)

                if "minute_vehicle_count" not in result:
                    result["minute_vehicle_count"] = self.latest_status.get("minute_vehicle_count", 0)

                result["ventilation"] = build_ventilation_result(
                    result=result,
                    ventilation_manager=self.ventilation_manager
                )

                self._update_status(result)

                self._save_accident_event(annotated, result)

                ok, buffer = cv2.imencode(".jpg", annotated)
                if not ok:
                    continue

                frame_bytes = buffer.tobytes()

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" +
                    frame_bytes +
                    b"\r\n"
                )

        except GeneratorExit:
            print("🛑 스트리밍 종료 요청")
        except Exception as e:
            print(f"❌ 스트리밍 중 오류: {e}")
            self._update_status({
                "state": "ERROR",
                "events": [f"stream error: {e}"],
            })
        finally:
            self.stream_active = False

            if cap is not None:
                cap.release()

            if self.stream_lock.locked():
                self.stream_lock.release()

            print("🛑 CCTV 스트리밍 종료")
        
            # =========================================================
    # 8) 스트림 명시 종료
    # =========================================================
    def stop_stream(self):
        self.stream_active = False
        self.stream_token += 1

        # 현재 스트림만 끊고, 상태는 READY로 갱신
        self._update_status({
            "state": "READY",
            "events": ["스트림 종료"],
            "lane_reestimate_status": "idle",
            "lane_reestimate_frame_count": 0,
            "lane_reestimate_window": 50,
        })

        print("🛑 [API] 사용자의 요청으로 터널 스트림 종료")
        return {
            "ok": True,
            "message": "스트림 종료 완료"
        }

    # =========================================================
    # 9) 랜덤 CCTV로 새 시작 준비
    # - 기존 스트림 종료
    # - current_cctv 새로 선택
    # - 이후 프론트가 /video-feed 다시 호출하면 새 시작
    # =========================================================
    def restart_with_random_cctv(self):
        # 기존 스트림 완전 종료
        self.stream_active = False
        self.stream_token += 1

        # 이전 선택을 끊고 새 랜덤 선택
        selected = self.select_random_cctv()

        if not selected:
            return {
                "ok": False,
                "message": "새로 선택할 CCTV가 없습니다."
            }

        print(f"🔄 [API] 새 랜덤 CCTV 재시작 준비 완료: {selected['name']}")
        return {
            "ok": True,
            "message": "새 랜덤 CCTV 재시작 준비 완료",
            "cctv": selected
        }