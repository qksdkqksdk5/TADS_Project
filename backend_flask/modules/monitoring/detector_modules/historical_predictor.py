# 파일 경로: detector_modules/historical_predictor.py
# 역할: 시각별(hour × 5분 슬롯) 과거 jam_score를 메모리에 누적하고,
#        5분 후 정체 수준을 예측한다.
#
# 슬롯 구조:
#   하루 = 24h × 12슬롯/h = 288 슬롯 (slot_id = hour*12 + minute//5)
#   슬롯 데이터: { slot_id: [count, jam_sum] }
#     - count   : 이 슬롯에서 기록된 5분 창의 수
#     - jam_sum : 각 5분 창 중앙값의 합계
#
# 기록 흐름 (매 프레임 호출 → 5분 창 단위로 자동 집계):
#   record(jam_score) 호출 → 내부 버퍼 누적
#   슬롯 경계(매 5분) 도달 → 버퍼 중앙값 계산 → 메모리 슬롯 갱신 → 버퍼 초기화
#
# 예측:
#   predict(dt) → (dt + 5분) 슬롯의 평균값 → 레벨 + 신뢰도 반환
#   데이터 없으면 None → 패널에 "학습 중" 표시
#
# ※ 영속 저장은 나중에 DB 연동으로 구현한다.
#    현재는 메모리에만 보관하며 재시작 시 초기화된다.

from datetime import datetime, timedelta


class HistoricalPredictor:
    """시각 슬롯별 jam_score 이력 기반 5분 후 정체 수준 예측기.

    Parameters
    ----------
    smooth_threshold : float
        jam_score 이 값 미만 → SMOOTH.
    slow_threshold : float
        jam_score 이 값 미만 → SLOW, 이상 → JAM.
    min_conf_samples : int
        신뢰도 100%에 필요한 최소 5분 창 수. 기본값 14 (약 1시간 10분).
    """

    def __init__(
        self,
        smooth_threshold: float = 0.25,   # SMOOTH 상한 임계값
        slow_threshold: float   = 0.60,   # SLOW/JAM 경계 임계값
        min_conf_samples: int   = 14,     # 신뢰도 100%를 위한 최소 5분 창 수
    ):
        self._smooth_thr = smooth_threshold  # SMOOTH 판정 임계값
        self._slow_thr   = slow_threshold    # JAM 판정 임계값
        self._min_conf   = min_conf_samples  # 신뢰도 100% 기준 창 수

        # ── 슬롯 데이터: slot_id → [count, jam_sum] ──────────────────
        # slot_id = hour * 12 + minute // 5  (0 ~ 287)
        self._slots: dict[int, list] = {}

        # ── 현재 5분 창 버퍼 ──────────────────────────────────────────
        self._buf_slot: int    = -1   # 현재 누적 중인 슬롯 ID (-1 = 미초기화)
        self._buf_values: list = []   # 이 슬롯에서 수집된 jam_score 리스트

    # ==================== 슬롯 ID 계산 ====================

    @staticmethod
    def _to_slot_id(dt: datetime) -> int:
        """datetime → slot_id (0~287)."""
        return dt.hour * 12 + dt.minute // 5  # 시 × 12 + 분 // 5

    # ==================== 기록 ====================

    def record(self, jam_score: float, dt: datetime | None = None) -> None:
        """현재 프레임의 jam_score를 내부 버퍼에 추가한다.

        슬롯 경계(5분 경계)를 넘어가면 이전 버퍼의 중앙값을 메모리 슬롯에
        기록하고 새 버퍼를 시작한다. 매 프레임 호출하면 된다.
        grace period 내 프레임(재연결 직후)에서는 호출하지 않는다 (호출측 책임).
        """
        if dt is None:
            dt = datetime.now()  # 기본값: 현재 시각

        cur_slot = self._to_slot_id(dt)  # 현재 시각의 슬롯 ID

        # ── 슬롯 경계 → 이전 버퍼 flush ──────────────────────────────
        if cur_slot != self._buf_slot:
            if self._buf_values and self._buf_slot >= 0:
                self._flush_buffer()           # 이전 창 중앙값 저장
            self._buf_slot   = cur_slot        # 새 슬롯으로 전환
            self._buf_values = []              # 버퍼 초기화

        self._buf_values.append(float(jam_score))  # 현재 프레임 값 누적

    def _flush_buffer(self) -> None:
        """현재 버퍼의 중앙값을 메모리 슬롯에 누적한다."""
        if not self._buf_values:
            return  # 버퍼 비어있으면 생략

        # ── 중앙값 계산 ────────────────────────────────────────────────
        sorted_v = sorted(self._buf_values)
        n        = len(sorted_v)
        if n % 2 == 1:
            median = sorted_v[n // 2]                                  # 홀수: 정중앙
        else:
            median = (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2.0  # 짝수: 두 중앙값 평균

        # ── 슬롯 누적 (메모리에만 저장) ───────────────────────────────
        sid = self._buf_slot
        if sid not in self._slots:
            self._slots[sid] = [0, 0.0]  # 첫 기록이면 초기화
        self._slots[sid][0] += 1         # 창 수 +1
        self._slots[sid][1] += median    # jam_sum 누적

    # ==================== 예측 ====================

    def _slot_avg(self, sid: int) -> float:
        """슬롯 평균 jam_score 반환. 데이터 없으면 -1."""
        s = self._slots.get(sid)
        if s is None or s[0] == 0:
            return -1.0  # 데이터 없음 표시
        return s[1] / s[0]  # jam_sum / count = 평균

    def _slot_conf(self, sid: int) -> float:
        """슬롯 신뢰도 반환 (0~1). 데이터 없으면 0."""
        s = self._slots.get(sid)
        if s is None or s[0] == 0:
            return 0.0
        return min(s[0] / max(self._min_conf, 1), 1.0)  # count / min_conf_samples, 최대 1.0

    # ── 빈 슬롯 보간 (최대 탐색 범위: ±_INTERP_MAX_GAP 슬롯) ────────
    _INTERP_MAX_GAP: int = 12   # 60분 = 12슬롯 이내만 보간 (이 이상이면 신뢰 불가)

    def _interpolate(self, target_sid: int) -> tuple[float, float] | None:
        """target_sid가 비었을 때 양측 이웃 슬롯으로 선형 보간한다.

        Returns
        -------
        (avg_jam, confidence) | None
            보간 성공이면 (값, 신뢰도), 범위 내 데이터 없으면 None.
        """
        # ── 이전(prev) 슬롯 탐색 ──────────────────────────────────────
        prev_sid, prev_dist = None, 0
        for d in range(1, self._INTERP_MAX_GAP + 1):
            sid = (target_sid - d) % 288   # 자정 경계 순환
            if self._slot_avg(sid) >= 0:
                prev_sid, prev_dist = sid, d
                break

        # ── 이후(next) 슬롯 탐색 ──────────────────────────────────────
        next_sid, next_dist = None, 0
        for d in range(1, self._INTERP_MAX_GAP + 1):
            sid = (target_sid + d) % 288   # 자정 경계 순환
            if self._slot_avg(sid) >= 0:
                next_sid, next_dist = sid, d
                break

        if prev_sid is None and next_sid is None:
            return None   # 전체 데이터 없음 → 보간 불가

        # ── 한쪽만 있으면 그대로 사용 (최근접 이웃) ──────────────────
        if prev_sid is None:
            avg_jam   = self._slot_avg(next_sid)
            base_conf = self._slot_conf(next_sid)
            gap       = next_dist
        elif next_sid is None:
            avg_jam   = self._slot_avg(prev_sid)
            base_conf = self._slot_conf(prev_sid)
            gap       = prev_dist
        else:
            # ── 양측 선형 보간 ────────────────────────────────────────
            total     = prev_dist + next_dist              # 두 슬롯 간 전체 거리
            t         = prev_dist / total                  # 0=prev 위치, 1=next 위치
            avg_jam   = self._slot_avg(prev_sid) * (1.0 - t) + self._slot_avg(next_sid) * t
            base_conf = min(self._slot_conf(prev_sid), self._slot_conf(next_sid))
            gap       = total                              # 간격이 클수록 신뢰도 페널티

        # ── 간격 페널티: 간격 1슬롯→거의 그대로, 12슬롯→절반 ─────────
        gap_factor = max(0.0, 1.0 - gap / (self._INTERP_MAX_GAP * 2))
        conf = base_conf * gap_factor

        return float(avg_jam), float(conf)

    def predict(self, dt: datetime | None = None) -> list | None:
        """현재 시각 기준 5분 후 슬롯의 정체 수준을 예측한다.

        해당 슬롯에 데이터가 없으면 양측 이웃 슬롯으로 선형 보간한다.
        보간 범위(±60분) 내에도 데이터가 없으면 None ("학습 중" 표시).

        Returns
        -------
        list[dict] | None
            [{"horizon_sec": 300, "horizon_min": 5,
              "predicted_level": str, "confidence": float, "jam_score": float,
              "interpolated": bool}]
        """
        if dt is None:
            dt = datetime.now()

        future_dt  = dt + timedelta(minutes=5)    # 5분 후 시각
        target_sid = self._to_slot_id(future_dt)  # 대상 슬롯 ID

        slot = self._slots.get(target_sid)
        if slot is not None and slot[0] > 0:
            # ── 직접 데이터 있음 ───────────────────────────────────────
            avg_jam = slot[1] / slot[0]                              # 슬롯 평균
            conf    = min(slot[0] / max(self._min_conf, 1), 1.0)     # 신뢰도 계산
            interp  = False                                          # 보간 아님
        else:
            # ── 보간 시도 ──────────────────────────────────────────────
            result = self._interpolate(target_sid)
            if result is None:
                return None  # 학습 데이터 없음 → "학습 중" 표시
            avg_jam, conf = result
            interp = True   # 보간 결과

        level = self._jam_to_level(avg_jam)  # jam_score → 레벨 문자열

        return [{
            "horizon_sec":     300,                   # 예측 대상: 5분 후 (초 단위)
            "horizon_min":     5,                     # 예측 대상: 5분 후
            "predicted_level": level,                 # SMOOTH / SLOW / JAM
            "confidence":      round(conf, 4),        # 신뢰도 (0.0~1.0)
            "jam_score":       round(avg_jam, 4),     # 예측 jam_score
            "interpolated":    interp,                # 보간 여부
        }]

    # ==================== 내부 유틸 ====================

    def _jam_to_level(self, jam_score: float) -> str:
        """jam_score를 레벨 문자열로 변환한다."""
        if jam_score < self._smooth_thr:
            return "SMOOTH"   # 원활
        if jam_score < self._slow_thr:
            return "SLOW"     # 서행
        return "JAM"          # 정체

    # ==================== 진단 ====================

    def get_slot_count(self) -> int:
        """현재 메모리에 로드된 슬롯 수 (최대 288)."""
        return len(self._slots)

    def get_total_windows(self) -> int:
        """누적된 5분 창 수 합계."""
        return sum(v[0] for v in self._slots.values())
