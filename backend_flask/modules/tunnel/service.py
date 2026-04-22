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
# ==========================================

import random
import threading
import cv2
import time

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
        }

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
        with self.lock:
            return dict(self.latest_status)

    def _update_status(self, data):
        with self.lock:
            self.latest_status.update(data)

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
                # 이유:
                # - lane_template에서 같은 터널의 memory(json)를 찾으려면
                #   현재 CCTV 이름이 필요함
                # - 이 값을 pipeline_adapter -> pipeline_core -> lane_template까지 넘김
                # --------------------------------------------------
                self.pipeline.current_cctv_name = selected_cctv["name"]

                annotated, result = self.pipeline.process_frame(frame, frame_id)

                result["cctv_name"] = selected_cctv["name"]
                result["cctv_url"] = selected_cctv["url"]

                self._update_status(result)

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