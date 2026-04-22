# ==========================================
# 파일명: lane_template_V5_5.py
# 설명:
# V5_5 차선(군집) 추정 모듈
#
# [개선 목적]
# 1) 기존 "초기 100프레임 1회 bootstrap" 방식 제거
# 2) 중앙영역 차량 2대 이상 + 연속 N프레임 유지 시 bootstrap 시작
# 3) bootstrap 실패 시 cooldown 후 재시도 가능
# 4) bootstrap 성공 시 최종 대표 집단(current_template) 확정
# 5) 현재 프레임 차량은 최종 대표 집단 중 가장 가까운 차선에 임시 할당
# 6) 동일 CCTV(터널)면 과거 저장된 lane memory를 먼저 불러오기
#
# [핵심 아이디어]
# - 실시간 CCTV에서는 초반에 차량이 적으면 차선 추정이 실패할 수 있음
# - 그래서 "시작 후 100프레임"이 아니라
#   "중앙영역 차량 수 조건이 만족된 뒤" bootstrap을 시작해야 안정적임
# - 또한 같은 터널은 구조가 거의 같으므로, 한 번 저장한 차선 template를
#   다음 진입 때 재사용하면 더 안정적으로 동작함
# ==========================================

import os
import re
import json
import glob
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


class LaneTemplateEstimator:
    def __init__(self, output_dir=None):
        # -----------------------------
        # 상태
        # -----------------------------
        self.current_template = []          # 최종 대표 집단 목록
        self.template_confirmed = False
        self.phase = "WAITING"              # WAITING / BOOTSTRAP / CLUSTER_VIEW / MEMORY_LOAD

        # -----------------------------
        # 수집 메모리
        # -----------------------------
        self.track_models = {}              # tid -> fitted linear model
        self.track_fit_error = {}           # tid -> rmse
        self.track_stable_motion = {}       # tid -> 안정 이동 여부
        self.collected_track_ids = set()
        self.collected_track_points = {}    # tid -> [(x, y), ...]

        # -----------------------------
        # 디버그
        # -----------------------------
        self.last_debug = {
            "phase": "WAITING",
            "template_confirmed": False,
            "lane_count": 0,
            "template": [],
            "clusters_stage1": [],
            "clusters_stage2": [],
            "lane_map": {},
            "raw_lane_map": {},
            "memory_loaded": False,
            "memory_key": None,
        }

        # -----------------------------
        # 파라미터
        # -----------------------------
        # [기존] BOOTSTRAP_FRAMES = 100 방식은 제거
        # [신규] 중앙영역 차량 수 + 연속 프레임 조건으로 bootstrap 시작

        # 선형 피팅에 필요한 최소 포인트 수
        self.FIT_MIN_POINTS = 30

        # 안정 이동 여부 판단 기준
        self.MIN_TOTAL_MOTION = 35
        self.MAX_DY_JUMP = 40
        self.MAX_DX_JUMP = 60

        # 선형 피팅 품질 필터
        self.MAX_FIT_RMSE = 35.0

        # bootstrap 시작 조건
        self.CENTER_VEHICLE_COUNT_THR = 2       # 중앙영역 차량 2대 이상
        self.BOOTSTRAP_READY_FRAMES = 20        # 연속 20프레임 유지 시 bootstrap 시작

        # bootstrap 수집/실패 제어
        self.BOOTSTRAP_MAX_COLLECT_FRAMES = 120 # bootstrap 최대 수집 프레임
        self.MIN_BOOTSTRAP_TRACKS = 2           # 최소 안정 차량 수
        self.BOOTSTRAP_COOLDOWN_FRAMES = 60     # 실패 후 재시도 대기 프레임

        # 현재 bootstrap 상태
        self.bootstrap_ready_count = 0
        self.bootstrap_collect_frames = 0
        self.bootstrap_cooldown = 0

        # 중앙영역 비율
        self.CENTER_X1_RATIO = 0.25
        self.CENTER_X2_RATIO = 0.75
        self.CENTER_Y1_RATIO = 0.20
        self.CENTER_Y2_RATIO = 0.85

        # 1차 군집: 차량 궤적끼리
        self.LINEAR_CLUSTER_THR_STAGE1 = 0.12

        # 2차 군집: 1차 대표선끼리
        self.LINEAR_CLUSTER_THR_STAGE2 = 0.22

        # 그래프 저장 경로
        self.output_dir = output_dir or os.getcwd()
        os.makedirs(self.output_dir, exist_ok=True)

        # -----------------------------
        # lane memory 저장 경로
        # -----------------------------
        self.memory_dir = os.path.join(self.output_dir, "lane_memory")
        os.makedirs(self.memory_dir, exist_ok=True)

        # -----------------------------
        # 현재 CCTV 이름 관련 상태
        # -----------------------------
        self.current_cctv_name = None
        self.current_cctv_key = None

        # memory를 이미 한 번 조회했는지 여부
        # 같은 CCTV에서 매 프레임마다 load를 반복하지 않기 위해 사용
        self.memory_checked = False
        self.memory_loaded = False

    # =========================================================
    # 0) bootstrap 관련 상태 초기화
    # =========================================================
    def _reset_bootstrap_memory(self):
        """
        bootstrap 재시도 전 메모리 초기화
        - template_confirmed는 건드리지 않음
        - bootstrap 수집용 메모리만 비움
        """
        self.track_models = {}
        self.track_fit_error = {}
        self.track_stable_motion = {}
        self.collected_track_ids = set()
        self.collected_track_points = {}
        self.bootstrap_collect_frames = 0

    # =========================================================
    # 0-1) 전체 상태 초기화 (새 CCTV 진입 시 사용)
    # =========================================================
    def _reset_for_new_cctv(self):
        """
        새로운 CCTV 이름이 들어온 경우
        lane estimator 전체 상태를 새로 시작하기 위한 초기화
        """
        self.current_template = []
        self.template_confirmed = False
        self.phase = "WAITING"

        self.track_models = {}
        self.track_fit_error = {}
        self.track_stable_motion = {}
        self.collected_track_ids = set()
        self.collected_track_points = {}

        self.bootstrap_ready_count = 0
        self.bootstrap_collect_frames = 0
        self.bootstrap_cooldown = 0

        self.memory_checked = False
        self.memory_loaded = False

    # =========================================================
    # 0-2) 그래프 파일 정리
    # =========================================================
    def _cleanup_debug_graphs(self):
        """
        새 bootstrap 결과를 저장하기 전에
        이전 그래프 png를 자동 삭제
        """
        patterns = [
            "graph_v5_5_*.png",
            "graph_stage1_v5_5_*.png",
            "graph_stage2_v5_5_*.png",
        ]

        for pattern in patterns:
            for path in glob.glob(os.path.join(self.output_dir, pattern)):
                try:
                    os.remove(path)
                except Exception:
                    pass

    # =========================================================
    # 0-3) CCTV 이름 정규화
    # =========================================================
    def _normalize_cctv_name(self, cctv_name):
        """
        실시간 CCTV 이름을 파일 저장/검색용 키로 변환

        예:
        "[수원광명선] 광명 구봉산터널"
        -> "수원광명선_광명_구봉산터널"

        목적:
        - 파일명으로 안전하게 사용
        - DB key로도 나중에 재사용 가능
        """
        if not cctv_name:
            return None

        name = str(cctv_name).strip()

        # 대괄호/소괄호를 공백으로 치환
        name = name.replace("[", " ")
        name = name.replace("]", " ")
        name = name.replace("(", " ")
        name = name.replace(")", " ")

        # 파일명에 위험한 문자 제거
        name = re.sub(r'[\\/:*?"<>|]+', " ", name)

        # 여러 공백을 하나로 정리
        name = re.sub(r"\s+", " ", name).strip()

        # 공백은 _ 로 변환
        name = name.replace(" ", "_")

        return name if name else None

    # =========================================================
    # 0-4) memory 파일 경로 생성
    # =========================================================
    def _get_memory_path(self, cctv_name):
        """
        정규화된 CCTV 이름을 바탕으로 memory json 파일 경로 생성
        """
        memory_key = self._normalize_cctv_name(cctv_name)
        if not memory_key:
            return None, None

        path = os.path.join(self.memory_dir, f"{memory_key}.json")
        return memory_key, path

    # =========================================================
    # 0-5) lane memory 저장
    # =========================================================
    def save_lane_memory(self, cctv_name=None):
        """
        현재 확정된 current_template를 json으로 저장

        저장 내용:
        - cctv_name
        - memory_key
        - lane_count
        - centerlines(current_template)
        - saved_at
        """
        target_name = cctv_name or self.current_cctv_name
        if not target_name:
            print("⚠️ lane memory 저장 실패: CCTV 이름 없음")
            return None

        if not self.current_template:
            print("⚠️ lane memory 저장 실패: current_template 비어 있음")
            return None

        memory_key, save_path = self._get_memory_path(target_name)
        if not save_path:
            print("⚠️ lane memory 저장 실패: memory path 생성 실패")
            return None

        payload = {
            "cctv_name": target_name,
            "memory_key": memory_key,
            "lane_count": len(self.current_template),
            "centerlines": self.current_template,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print(f"💾 lane memory 저장 완료: {save_path}")
        return save_path

    # =========================================================
    # 0-6) lane memory 로드
    # =========================================================
    def load_lane_memory(self, cctv_name=None):
        """
        동일한 CCTV 이름의 저장된 차선 template가 있으면 불러오기

        성공 시:
        - current_template 세팅
        - template_confirmed = True
        - phase = "CLUSTER_VIEW"
        """
        target_name = cctv_name or self.current_cctv_name
        if not target_name:
            return False

        memory_key, load_path = self._get_memory_path(target_name)
        if not load_path or not os.path.exists(load_path):
            return False

        try:
            with open(load_path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            centerlines = payload.get("centerlines", [])
            if not isinstance(centerlines, list) or len(centerlines) == 0:
                return False

            self.current_template = centerlines
            self.template_confirmed = True
            self.phase = "CLUSTER_VIEW"

            self.memory_loaded = True
            self.memory_checked = True

            print(f"📂 저장된 lane memory 로드: {load_path}")
            return True

        except Exception as e:
            print(f"❌ lane memory 로드 실패: {e}")
            return False

    # =========================================================
    # 0-7) 수동 보정용 lane 제거 후 저장
    # =========================================================
    def remove_lane_and_save(self, lane_id_to_remove, cctv_name=None):
        """
        사람이 "lane 1은 차선 아님" 같은 수동 보정을 할 때 쓰는 함수

        예:
        remove_lane_and_save(1, "[수원광명선] 광명 구봉산터널")

        동작:
        1) current_template에서 해당 lane 제거
        2) lane_id를 다시 0,1,2...로 재정렬
        3) memory 저장
        """
        if not self.current_template:
            print("⚠️ lane 제거 실패: current_template 비어 있음")
            return False

        filtered = [lane for lane in self.current_template if lane.get("lane_id") != lane_id_to_remove]

        if len(filtered) == len(self.current_template):
            print(f"⚠️ lane 제거 실패: lane_id={lane_id_to_remove} 없음")
            return False

        reindexed = []
        for new_idx, lane in enumerate(filtered):
            lane_copy = dict(lane)
            lane_copy["lane_id"] = new_idx
            reindexed.append(lane_copy)

        self.current_template = reindexed
        self.template_confirmed = len(self.current_template) > 0
        self.phase = "CLUSTER_VIEW" if self.template_confirmed else "WAITING"

        self.save_lane_memory(cctv_name=cctv_name)
        print(f"🛠️ lane {lane_id_to_remove} 제거 후 memory 재저장 완료")
        return True

    # =========================================================
    # 1) 중앙영역 차량 수 계산
    # =========================================================
    def _count_center_tracks(self, track_points, frame_width, frame_height):
        """
        현재 프레임의 대표점(track_points)이
        중앙영역에 몇 대 있는지 계산

        [주의]
        - track_points는 보통 tid -> (x, y) 형태라고 가정
        - 여기서 x, y는 현재 프레임 차량 대표점(bottom-center 등)
        """
        cx1 = int(frame_width * self.CENTER_X1_RATIO)
        cx2 = int(frame_width * self.CENTER_X2_RATIO)
        cy1 = int(frame_height * self.CENTER_Y1_RATIO)
        cy2 = int(frame_height * self.CENTER_Y2_RATIO)

        count = 0

        for _, pt in track_points.items():
            x, y = pt
            if cx1 <= x <= cx2 and cy1 <= y <= cy2:
                count += 1

        return count

    # =========================================================
    # 2) 안정 이동 차량 판정
    # =========================================================
    def _is_stable_moving_track(self, pts):
        """
        최근 궤적이 충분히 길고, 급점프가 적고, 실제로 이동량이 있는지 검사
        """
        if len(pts) < self.FIT_MIN_POINTS:
            return False

        recent = pts[-self.FIT_MIN_POINTS:]

        total_motion = 0.0
        jump_bad = 0
        ys = []

        for i in range(1, len(recent)):
            x0, y0 = recent[i - 1]
            x1, y1 = recent[i]

            dx = x1 - x0
            dy = y1 - y0

            total_motion += np.sqrt(dx * dx + dy * dy)

            if abs(dy) > self.MAX_DY_JUMP or abs(dx) > self.MAX_DX_JUMP:
                jump_bad += 1

            ys.append(y1)

        y_span = (max(ys) - min(ys)) if ys else 0

        if total_motion < self.MIN_TOTAL_MOTION:
            return False
        if jump_bad > 3:
            return False
        if y_span < 25:
            return False

        return True

    # =========================================================
    # 3) 차량 궤적 선형 피팅
    #    x = a*y + b
    # =========================================================
    def _fit_trajectory_model(self, pts):
        """
        최근 궤적을 선형으로 피팅
        - 입력: 점 목록 [(x,y), ...]
        - 출력: 선형 모델, RMSE
        """
        recent = pts[-self.FIT_MIN_POINTS:]
        ys = np.array([p[1] for p in recent], dtype=np.float32)
        xs = np.array([p[0] for p in recent], dtype=np.float32)

        if len(np.unique(ys)) < 6:
            return None, 1e9

        try:
            lin_coef = np.polyfit(ys, xs, 1)
            lin_pred = np.polyval(lin_coef, ys)
            lin_rmse = float(np.sqrt(np.mean((xs - lin_pred) ** 2)))
        except Exception:
            return None, 1e9

        return {
            "type": "linear",
            "coef": lin_coef.astype(float).tolist()
        }, lin_rmse

    def _predict_x(self, model, y):
        """
        주어진 y에서 선형 모델의 x 위치 계산
        """
        if model is None:
            return None

        a, b = model["coef"]
        return a * y + b

    # =========================================================
    # 4) 모델 거리 계산
    # =========================================================
    def _coef_vector(self, model, frame_height):
        """
        선형 계수 벡터를 정규화된 형태로 변환
        """
        a, b = model["coef"]
        return np.array([a, b / max(frame_height, 1)], dtype=np.float32)

    def _model_distance(self, model1, model2, lane_y1, lane_y2, frame_height):
        """
        두 선형 궤적이 얼마나 비슷한지 계산
        - 계수 벡터 거리
        - ROI 여러 지점에서 x 차이
        """
        v1 = self._coef_vector(model1, frame_height)
        v2 = self._coef_vector(model2, frame_height)
        coef_dist = float(np.linalg.norm(v1 - v2))

        sample_ys = np.linspace(lane_y1, lane_y2, 5)
        diffs = []

        for y in sample_ys:
            x1 = self._predict_x(model1, y)
            x2 = self._predict_x(model2, y)
            diffs.append(abs(x1 - x2))

        shape_dist = float(np.mean(diffs)) / max(frame_height, 1)

        return coef_dist * 0.5 + shape_dist * 0.5

    # =========================================================
    # 5) 대표 모델 계산
    # =========================================================
    def _aggregate_models(self, models):
        """
        여러 선형 모델을 하나의 대표 모델로 통합
        중앙값(median) 사용
        """
        if not models:
            return None

        arr = np.array([m["coef"] for m in models], dtype=np.float32)
        coef = np.median(arr, axis=0).tolist()

        return {
            "type": "linear",
            "coef": coef
        }

    # =========================================================
    # 6) bootstrap 동안 안정 차량 궤적 수집
    # =========================================================
    def _collect_stable_models(self, track_history):
        """
        현재까지의 track_history에서
        안정적으로 움직이는 차량만 선형 모델로 수집
        """
        for tid, pts in track_history.items():
            stable = self._is_stable_moving_track(pts)
            self.track_stable_motion[tid] = stable

            if not stable:
                continue

            model, rmse = self._fit_trajectory_model(pts)
            if model is None:
                continue

            if rmse > self.MAX_FIT_RMSE:
                continue

            self.track_models[tid] = model
            self.track_fit_error[tid] = rmse
            self.collected_track_ids.add(tid)
            self.collected_track_points[tid] = list(pts)

    # =========================================================
    # 7) 1차 군집화
    # =========================================================
    def _cluster_track_models_stage1(self, lane_y1, lane_y2, frame_height):
        stable_models = [
            (tid, self.track_models[tid])
            for tid in sorted(self.collected_track_ids)
            if tid in self.track_models
        ]

        if not stable_models:
            return []

        clusters = []

        for tid, model in stable_models:
            assigned = False

            for cluster in clusters:
                dist = self._model_distance(
                    model,
                    cluster["rep_model"],
                    lane_y1,
                    lane_y2,
                    frame_height
                )

                if dist < self.LINEAR_CLUSTER_THR_STAGE1:
                    cluster["items"].append((tid, model))
                    cluster["rep_model"] = self._aggregate_models(
                        [m for _, m in cluster["items"]]
                    )
                    assigned = True
                    break

            if not assigned:
                clusters.append({
                    "cluster_id": len(clusters),
                    "rep_model": model,
                    "items": [(tid, model)]
                })

        return clusters

    # =========================================================
    # 8) 1차 군집 정보 정리
    # =========================================================
    def _extract_cluster_info_stage1(self, clusters, lane_y1, lane_y2):
        if not clusters:
            return []

        y_mid = (lane_y1 + lane_y2) / 2.0
        total_tracks = sum(len(c["items"]) for c in clusters)

        cluster_info = []
        for c in clusters:
            agg_model = self._aggregate_models([m for _, m in c["items"]])
            x_mid = self._predict_x(agg_model, y_mid)

            cluster_info.append({
                "cluster_id": c["cluster_id"],
                "rep_model": agg_model,
                "count": len(c["items"]),
                "ratio": len(c["items"]) / max(total_tracks, 1),
                "x_mid": x_mid,
                "member_ids": [tid for tid, _ in c["items"]],
            })

        cluster_info.sort(key=lambda x: x["x_mid"])
        return cluster_info

    # =========================================================
    # 9) 2차 군집화
    # =========================================================
    def _cluster_representatives_stage2(self, cluster_info_stage1, lane_y1, lane_y2, frame_height):
        """
        1차 군집 대표선들끼리 다시 거리 계산해서
        비슷한 흐름은 한 번 더 합친다.
        """
        if not cluster_info_stage1:
            return []

        clusters2 = []

        for c in cluster_info_stage1:
            model = c["rep_model"]
            assigned = False

            for cluster in clusters2:
                dist = self._model_distance(
                    model,
                    cluster["rep_model"],
                    lane_y1,
                    lane_y2,
                    frame_height
                )

                if dist < self.LINEAR_CLUSTER_THR_STAGE2:
                    cluster["items"].append(c)
                    cluster["rep_model"] = self._aggregate_models(
                        [item["rep_model"] for item in cluster["items"]]
                    )
                    assigned = True
                    break

            if not assigned:
                clusters2.append({
                    "cluster_id": len(clusters2),
                    "rep_model": model,
                    "items": [c]
                })

        return clusters2

    # =========================================================
    # 10) 2차 군집 결과 정리
    # =========================================================
    def _extract_cluster_info_stage2(self, clusters2, lane_y1, lane_y2):
        """
        2차 군집 결과를 최종 대표 집단으로 정리
        """
        if not clusters2:
            return []

        y_mid = (lane_y1 + lane_y2) / 2.0
        total_count = 0
        for c in clusters2:
            total_count += sum(item["count"] for item in c["items"])

        final_info = []
        for c in clusters2:
            agg_model = self._aggregate_models([item["rep_model"] for item in c["items"]])
            x_mid = self._predict_x(agg_model, y_mid)

            merged_count = sum(item["count"] for item in c["items"])

            merged_ids = []
            for item in c["items"]:
                merged_ids.extend(item["member_ids"])

            final_info.append({
                "cluster_id": c["cluster_id"],
                "rep_model": agg_model,
                "count": merged_count,
                "ratio": merged_count / max(total_count, 1),
                "x_mid": x_mid,
                "member_ids": merged_ids,
                "source_cluster_ids": [item["cluster_id"] for item in c["items"]],
            })

        final_info.sort(key=lambda x: x["x_mid"])
        return final_info

    # =========================================================
    # 11) bootstrap 결과 유효성 검사
    # =========================================================
    def _is_valid_bootstrap_result(self, final_cluster_info):
        """
        bootstrap 결과가 실제로 쓸 만한지 검사
        - 최종 차선 후보가 1개 이상 있어야 함
        - 안정 차량 수가 최소 기준 이상이어야 함
        """
        if len(final_cluster_info) < 1:
            return False

        if len(self.collected_track_ids) < self.MIN_BOOTSTRAP_TRACKS:
            return False

        return True

    # =========================================================
    # 12) 현재 차량을 가장 가까운 최종 대표 집단에 임시 할당
    # =========================================================
    def _assign_lane(self, point, template):
        if not template:
            return None

        x, y = point
        best_lane = None
        best_dist = 1e9

        for lane in template:
            model = lane["rep_model"]
            cx = self._predict_x(model, y)
            dist = abs(x - cx)

            if dist < best_dist:
                best_dist = dist
                best_lane = lane["lane_id"]

        return best_lane

    # =========================================================
    # 13) 그래프 저장
    # =========================================================
    def save_trajectory_plot(self, lane_y1, lane_y2, filename=None):
        """
        최종 대표 집단 그래프 저장
        """
        if not self.collected_track_points:
            return None

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"graph_v5_5_{timestamp}.png"

        save_path = os.path.join(self.output_dir, filename)

        plt.figure(figsize=(8, 6))

        for tid, pts in self.collected_track_points.items():
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            plt.plot(xs, ys, linewidth=1, alpha=0.6)
            plt.text(xs[-1], ys[-1], str(tid), fontsize=8)

        sample_ys = np.linspace(lane_y1, lane_y2, 50)

        for lane in self.current_template:
            model = lane["rep_model"]
            lane_id = lane["lane_id"]
            xs = [self._predict_x(model, y) for y in sample_ys]
            plt.plot(xs, sample_ys, linewidth=3, label=f"CLUSTER {lane_id}")

        plt.gca().invert_yaxis()
        plt.title("Vehicle Trajectories and Cluster Representatives")
        plt.xlabel("X")
        plt.ylabel("Y")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(save_path, dpi=150)
        plt.close()

        print("📊 그래프 저장:", save_path)
        return save_path

    def save_trajectory_plot_stage1(self, lane_y1, lane_y2, cluster_info_stage1, filename=None):
        """
        1차 군집화 결과 저장
        """
        if not self.collected_track_points:
            return None

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"graph_stage1_v5_5_{timestamp}.png"

        save_path = os.path.join(self.output_dir, filename)

        plt.figure(figsize=(8, 6))

        for tid, pts in self.collected_track_points.items():
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            plt.plot(xs, ys, linewidth=1, alpha=0.6)
            plt.text(xs[-1], ys[-1], str(tid), fontsize=8)

        sample_ys = np.linspace(lane_y1, lane_y2, 50)

        for c in cluster_info_stage1:
            model = c["rep_model"]
            cid = c["cluster_id"]
            xs = [self._predict_x(model, y) for y in sample_ys]
            plt.plot(xs, sample_ys, linewidth=3, label=f"STAGE1 {cid}")

        plt.gca().invert_yaxis()
        plt.title("Vehicle Trajectories and Stage1 Cluster Representatives")
        plt.xlabel("X")
        plt.ylabel("Y")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(save_path, dpi=150)
        plt.close()

        print("📊 1차 군집 그래프 저장:", save_path)
        return save_path

    def save_trajectory_plot_stage2(self, lane_y1, lane_y2, filename=None):
        """
        2차 군집화 결과 저장
        """
        if not self.collected_track_points:
            return None

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"graph_stage2_v5_5_{timestamp}.png"

        save_path = os.path.join(self.output_dir, filename)

        plt.figure(figsize=(8, 6))

        for tid, pts in self.collected_track_points.items():
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            plt.plot(xs, ys, linewidth=1, alpha=0.6)
            plt.text(xs[-1], ys[-1], str(tid), fontsize=8)

        sample_ys = np.linspace(lane_y1, lane_y2, 50)

        for lane in self.current_template:
            model = lane["rep_model"]
            lane_id = lane["lane_id"]
            xs = [self._predict_x(model, y) for y in sample_ys]
            plt.plot(xs, sample_ys, linewidth=3, label=f"STAGE2 {lane_id}")

        plt.gca().invert_yaxis()
        plt.title("Vehicle Trajectories and Stage2 Cluster Representatives")
        plt.xlabel("X")
        plt.ylabel("Y")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(save_path, dpi=150)
        plt.close()

        print("📊 2차 군집 그래프 저장:", save_path)
        return save_path

    # =========================================================
    # 14) 외부 호출 메인 함수
    # =========================================================
    def update(self, frame_id, analysis):
        track_history = analysis["track_history"]
        track_points = analysis["track_points"]
        frame_height = analysis["frame_height"]

        # -----------------------------------------------------
        # 현재 CCTV 이름 받기
        # analysis에 cctv_name이 들어오면 같은 터널 memory를 찾는 데 사용
        # -----------------------------------------------------
        incoming_cctv_name = analysis.get("cctv_name")

        # CCTV가 바뀌면 lane estimator 상태도 새로 시작
        if incoming_cctv_name and incoming_cctv_name != self.current_cctv_name:
            self.current_cctv_name = incoming_cctv_name
            self.current_cctv_key = self._normalize_cctv_name(incoming_cctv_name)
            self._reset_for_new_cctv()

        # -----------------------------------------------------
        # frame_width가 analysis에 있으면 사용
        # 없으면 실시간 환경 기본값(1280) 사용
        # -----------------------------------------------------
        frame_width = analysis.get("frame_width", 1280)

        # -----------------------------------------------------
        # 차선 추정은 ROI와 별도로 화면 전체 흐름을 보기 위해
        # 더 넓은 세로 범위를 사용
        # -----------------------------------------------------
        lane_y1 = int(frame_height * 0.20)
        lane_y2 = int(frame_height * 0.95)

        # -----------------------------------------------------
        # A) 저장된 memory가 있으면 bootstrap 전에 먼저 로드
        # 같은 CCTV에서는 한 번만 체크
        # -----------------------------------------------------
        if not self.memory_checked and not self.template_confirmed and self.current_cctv_name:
            self.memory_checked = True
            loaded = self.load_lane_memory(self.current_cctv_name)
            if loaded:
                self.phase = "MEMORY_LOAD"

        # -----------------------------------------------------
        # B) 이미 template가 확정된 경우
        # memory load 포함
        # 이후에는 bootstrap 안 하고 바로 차선 할당만 수행
        # -----------------------------------------------------
        if self.template_confirmed:
            if self.memory_loaded:
                self.phase = "MEMORY_LOAD"
            else:
                self.phase = "CLUSTER_VIEW"

            clusters_stage1_debug = []
            clusters_stage2_debug = []

        else:
            # -------------------------------------------------
            # C) bootstrap cooldown 감소
            # 실패 직후 바로 다시 시도하지 않도록 대기 프레임 사용
            # -------------------------------------------------
            if self.bootstrap_cooldown > 0:
                self.bootstrap_cooldown -= 1

            # -------------------------------------------------
            # D) 중앙영역 차량 수 계산
            # 중앙영역 차량 2대 이상이 연속으로 유지되어야
            # bootstrap 시작
            # -------------------------------------------------
            center_count = self._count_center_tracks(
                track_points,
                frame_width,
                frame_height
            )

            if self.bootstrap_cooldown == 0 and center_count >= self.CENTER_VEHICLE_COUNT_THR:
                self.bootstrap_ready_count += 1
            else:
                self.bootstrap_ready_count = 0

            # -------------------------------------------------
            # E) 아직 bootstrap 시작 전 대기 상태
            # -------------------------------------------------
            if self.bootstrap_collect_frames == 0 and self.bootstrap_ready_count < self.BOOTSTRAP_READY_FRAMES:
                self.phase = "WAITING"
                clusters_stage1_debug = []
                clusters_stage2_debug = []

            else:
                # ---------------------------------------------
                # F) bootstrap 시작 시점
                # 조건을 처음 만족한 순간 메모리 초기화 후 수집 시작
                # ---------------------------------------------
                if self.bootstrap_collect_frames == 0 and self.bootstrap_ready_count >= self.BOOTSTRAP_READY_FRAMES:
                    self._reset_bootstrap_memory()
                    self.phase = "BOOTSTRAP"

                # ---------------------------------------------
                # G) bootstrap 수집 진행
                # ---------------------------------------------
                self.phase = "BOOTSTRAP"
                self._collect_stable_models(track_history)
                self.bootstrap_collect_frames += 1

                # ---------------------------------------------
                # H) 현재까지 수집된 모델로 군집화 시도
                # ---------------------------------------------
                clusters_stage1 = self._cluster_track_models_stage1(
                    lane_y1,
                    lane_y2,
                    frame_height
                )
                cluster_info_stage1 = self._extract_cluster_info_stage1(
                    clusters_stage1,
                    lane_y1,
                    lane_y2
                )

                clusters_stage2 = self._cluster_representatives_stage2(
                    cluster_info_stage1,
                    lane_y1,
                    lane_y2,
                    frame_height
                )
                final_cluster_info = self._extract_cluster_info_stage2(
                    clusters_stage2,
                    lane_y1,
                    lane_y2
                )

                clusters_stage1_debug = cluster_info_stage1
                clusters_stage2_debug = final_cluster_info

                # ---------------------------------------------
                # I) bootstrap 성공 조건
                # 충분한 안정 차량/군집이 있으면 template 확정
                # ---------------------------------------------
                success = self._is_valid_bootstrap_result(final_cluster_info)

                if success:
                    self.current_template = []
                    for idx, c in enumerate(final_cluster_info):
                        self.current_template.append({
                            "lane_id": idx,
                            "cluster_id": c["cluster_id"],
                            "rep_model": c["rep_model"],
                            "x_mid": c["x_mid"],
                            "count": c["count"],
                            "ratio": c["ratio"],
                            "member_ids": c["member_ids"],
                            "source_cluster_ids": c["source_cluster_ids"],
                        })

                    self.template_confirmed = True
                    self.phase = "CLUSTER_VIEW"
                    self.memory_loaded = False

                    # 새 결과 저장 전 이전 그래프 삭제
                    self._cleanup_debug_graphs()

                    # 1차/2차 그래프 저장
                    self.save_trajectory_plot_stage1(
                        lane_y1=lane_y1,
                        lane_y2=lane_y2,
                        cluster_info_stage1=cluster_info_stage1
                    )
                    self.save_trajectory_plot_stage2(
                        lane_y1=lane_y1,
                        lane_y2=lane_y2
                    )

                    # 같은 CCTV 이름으로 lane memory 자동 저장
                    self.save_lane_memory(self.current_cctv_name)

                # ---------------------------------------------
                # J) bootstrap 실패 처리
                # 너무 오래 수집했는데도 template가 안 잡히면
                # cooldown 후 재시도 가능하게 만든다
                # ---------------------------------------------
                elif self.bootstrap_collect_frames >= self.BOOTSTRAP_MAX_COLLECT_FRAMES:
                    self.phase = "WAITING"
                    self.bootstrap_cooldown = self.BOOTSTRAP_COOLDOWN_FRAMES
                    self.bootstrap_ready_count = 0
                    self._reset_bootstrap_memory()
                    clusters_stage1_debug = []
                    clusters_stage2_debug = []

        # -----------------------------------------------------
        # K) 현재 최종 대표 집단 기준 임시 할당
        # template_confirmed가 False면 lane_id는 None이 될 수 있음
        # -----------------------------------------------------
        lane_map = {}
        raw_lane_map = {}

        for tid, pt in track_points.items():
            lane_id = self._assign_lane(pt, self.current_template)
            lane_map[tid] = lane_id
            raw_lane_map[tid] = lane_id

        result = {
            "lane_map": lane_map,
            "raw_lane_map": raw_lane_map,
            "lane_count": len(self.current_template),
            "centerlines": self.current_template,
            "lane_debug": {
                tid: {
                    "raw_lane": raw_lane_map.get(tid),
                    "stable_lane": lane_map.get(tid),
                } for tid in lane_map
            },
            "template_phase": self.phase,
            "template_confirmed": self.template_confirmed,
            "clusters_stage1": clusters_stage1_debug,
            "clusters_stage2": clusters_stage2_debug,
            "clusters": clusters_stage2_debug,
            "memory_loaded": self.memory_loaded,
            "memory_key": self.current_cctv_key,
        }

        self.last_debug = {
            "phase": self.phase,
            "template_confirmed": self.template_confirmed,
            "lane_count": len(self.current_template),
            "template": self.current_template,
            "clusters_stage1": clusters_stage1_debug,
            "clusters_stage2": clusters_stage2_debug,
            "lane_map": lane_map,
            "raw_lane_map": raw_lane_map,
            "memory_loaded": self.memory_loaded,
            "memory_key": self.current_cctv_key,
        }

        return result

    def get_debug_info(self):
        return self.last_debug