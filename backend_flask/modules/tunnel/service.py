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
# - [추가] 사고 이벤트 캡처/저장
# ==========================================

import os
import json
import random
import threading
import cv2
import time
from datetime import datetime

from .pipeline_adapter import TunnelPipelineAdapter


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

        # --------------------------------------------------
        # 최신 상태 캐시
        # 프론트 status API에서 그대로 내려갈 값들
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

            # [추가] 차선 재추정 상태
            "lane_reestimate_status": "idle",
            "lane_reestimate_frame_count": 0,
            "lane_reestimate_window": 50,

            # [추가] 최근 1분 누적 차량수 (없으면 0 유지)
            "minute_vehicle_count": 0,
        }

        # ==================================================
        # [추가] 사고 이벤트 저장 폴더
        # ==================================================
        self.event_root = os.path.join(os.path.dirname(__file__), "event_storage")
        self.event_snapshot_dir = os.path.join(self.event_root, "snapshots")
        self.event_log_dir = os.path.join(self.event_root, "logs")

        os.makedirs(self.event_snapshot_dir, exist_ok=True)
        os.makedirs(self.event_log_dir, exist_ok=True)

        # 최근 사고 이벤트 중복 저장 방지용
        self.last_saved_accident_frame = -999999
        self.accident_save_cooldown = 180   # 180프레임 내 중복 저장 방지

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

        # health 초기화
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
        """
        프론트 /api/tunnel/status 응답용
        """
        with self.lock:
            data = dict(self.latest_status)

        # 안전하게 기본값 보정
        data.setdefault("lane_reestimate_status", "idle")
        data.setdefault("lane_reestimate_frame_count", 0)
        data.setdefault("lane_reestimate_window", 50)
        data.setdefault("minute_vehicle_count", 0)

        return data

    def _update_status(self, data):
        """
        pipeline 결과나 service 내부 상태를 latest_status에 반영
        """
        with self.lock:
            self.latest_status.update(data)

            # 혹시 일부 키가 빠져 들어와도 기본값 유지
            self.latest_status.setdefault("lane_reestimate_status", "idle")
            self.latest_status.setdefault("lane_reestimate_frame_count", 0)
            self.latest_status.setdefault("lane_reestimate_window", 50)
            self.latest_status.setdefault("minute_vehicle_count", 0)

    # =========================================================
    # 2-1) 차선 재추정 요청
    # =========================================================
    def request_lane_reestimate(self):
        """
        관제사가 버튼을 누르면 routes.py에서 이 메서드를 호출한다.
        """
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
    # 2-2) [추가] 사고 이벤트 캡처/저장
    # =========================================================
    def _save_accident_event(self, frame, status_data):
        """
        사고 감지 시 현재 프레임(annotated)을 저장한다.

        저장 내용:
        1) jpg 스냅샷
        2) json 메타데이터

        주의:
        - 지금은 뼈대 단계이므로 파일 저장만 수행
        - 너무 자주 저장되지 않게 cooldown 적용
        """
        accident_flag = bool(status_data.get("accident", False))
        frame_id = int(status_data.get("frame_id", 0))

        if not accident_flag:
            return

        # 너무 자주 같은 사고를 저장하지 않게 방지
        if frame_id - self.last_saved_accident_frame < self.accident_save_cooldown:
            return

        self.last_saved_accident_frame = frame_id

        now = datetime.now()
        ts_compact = now.strftime("%Y%m%d_%H%M%S")
        ts_text = now.strftime("%Y-%m-%d %H:%M:%S")

        event_id = f"accident_{ts_compact}_{frame_id}"

        # 1) 이미지 저장
        image_path = os.path.join(self.event_snapshot_dir, f"{event_id}.jpg")
        cv2.imwrite(image_path, frame)

        # 2) 메타 저장
        payload = {
            "event_id": event_id,
            "timestamp": ts_text,
            "frame_id": frame_id,
            "type": "accident",
            "state": "pending",   # 이후 dismissed / confirmed 확장 가능
            "cctv_name": status_data.get("cctv_name", "-"),
            "cctv_url": status_data.get("cctv_url", ""),
            "avg_speed": float(status_data.get("avg_speed", 0.0)),
            "vehicle_count": int(status_data.get("vehicle_count", 0)),
            "lane_count": int(status_data.get("lane_count", 0)),
            "snapshot_path": image_path,
            "events": status_data.get("events", []),
        }

        json_path = os.path.join(self.event_log_dir, f"{event_id}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print(f"📸 사고 이벤트 저장 완료: {event_id}")

    # =========================================================
    # 2-3) [추가] 저장된 이벤트 목록 조회 뼈대
    # =========================================================
    def get_saved_event_list(self):
        """
        저장된 사고 json 목록을 최근순으로 반환
        """
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

            # 너무 빨리 제외하지 않게 10회 기준
            if fail_count < 10:
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

        # 기존 스트림 종료 유도
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
        })

        print(f"✅ 랜덤 선택 CCTV(캐시): {self.current_cctv['name']}")
        return self.current_cctv

    def select_cctv_by_name(self, name):
        keyword = (name or "").strip()
        if not keyword:
            return None

        # 1) 정확 일치 우선
        for cctv in self.cached_cctv_list:
            if keyword == cctv["name"]:
                self.current_cctv = cctv
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
                })

                print(f"✅ 정확 이름으로 선택 CCTV: {self.current_cctv['name']}")
                return self.current_cctv

        # 2) 부분 일치
        for cctv in self.cached_cctv_list:
            if keyword in cctv["name"]:
                self.current_cctv = cctv
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
                })

                print(f"✅ 부분 이름으로 선택 CCTV: {self.current_cctv['name']}")
                return self.current_cctv

        # 3) 공백 제거 후 부분 일치
        normalized_keyword = keyword.replace(" ", "")
        for cctv in self.cached_cctv_list:
            normalized_name = cctv["name"].replace(" ", "")
            if normalized_keyword in normalized_name:
                self.current_cctv = cctv
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
                })

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

        # open 자체를 조금 여유 있게 확인
        open_ok = False
        for _ in range(10):
            if cap.isOpened():
                open_ok = True
                break
            time.sleep(0.15)

        if not open_ok:
            print(f"❌ CCTV 연결 실패(open): {name}")
            self._mark_cctv_failure(cctv)
            cap.release()
            return None

        # 첫 프레임도 여러 번 시도
        frame_ok = False
        for _ in range(20):
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
        # 동시에 2개 이상 스트림이 돌지 않게 보호
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

        # 현재 스트림 세션 토큰 고정
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

                # --------------------------------------------------
                # 현재 선택된 CCTV 이름을 pipeline_adapter에 전달
                # --------------------------------------------------
                self.pipeline.current_cctv_name = selected_cctv["name"]

                annotated, result = self.pipeline.process_frame(frame, frame_id)

                # pipeline 결과에 현재 CCTV 정보 덧붙임
                result["cctv_name"] = selected_cctv["name"]
                result["cctv_url"] = selected_cctv["url"]

                # lane reestimate 기본값 보정
                if "lane_reestimate_status" not in result:
                    result["lane_reestimate_status"] = self.latest_status.get("lane_reestimate_status", "idle")

                if "lane_reestimate_frame_count" not in result:
                    result["lane_reestimate_frame_count"] = self.latest_status.get("lane_reestimate_frame_count", 0)

                if "lane_reestimate_window" not in result:
                    result["lane_reestimate_window"] = self.latest_status.get("lane_reestimate_window", 50)

                # minute_vehicle_count 기본값 보정
                if "minute_vehicle_count" not in result:
                    result["minute_vehicle_count"] = self.latest_status.get("minute_vehicle_count", 0)

                self._update_status(result)

                # --------------------------------------------------
                # [추가] 사고 감지 시 현재 annotated 프레임 저장
                # - annotated를 저장하면 박스/차선/상태가 그려진 화면 그대로 보관 가능
                # --------------------------------------------------
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