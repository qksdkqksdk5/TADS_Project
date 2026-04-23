# tests/test_congestion_judge_daewon.py
# 교통 모니터링 팀 — 대원 작업 반영 congestion_judge jam_score 수식 개편 TDD 테스트
# 변경 항목:
#   1) count_gate 분모: 8.0 → 10.0
#   2) occ_gate: 고정 공식 → count_ref/valid_cell_count 기반 동적 포화점
#   3) core 공식: 1.90*cds + 0.25*persist + 0.10*√dwell → 0.55*cds + 0.20*persist + 1.00*dwell
#
# 실행: backend_flask/ 에서
#     pytest tests/test_congestion_judge_daewon.py -v

import os
import sys
import math

# ── sys.path 설정 ────────────────────────────────────────────────────────────
_HERE             = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR      = os.path.normpath(os.path.join(_HERE, '..'))
_MONITORING_DIR   = os.path.join(_BACKEND_DIR, 'modules', 'monitoring')
_DETECTOR_MODULES = os.path.join(_MONITORING_DIR, 'detector_modules')

for _p in (_BACKEND_DIR, _MONITORING_DIR, _DETECTOR_MODULES):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from detector_modules.congestion_judge import compute_jam_score_fallback  # 테스트 대상


def _make_xt(
    cds=0.0, flow_occ=0.30, persist=0.0, dwell=0.0,
    known_cnt=10, occupied_cnt=5,
    count_ref=8.0, valid_cell_count=80,
) -> dict:
    """테스트용 feature 벡터 생성 헬퍼."""
    return {
        "cell_dwell_score":    cds,           # 셀 누적 점유 EMA
        "flow_occupancy":      flow_occ,      # 순간 점유율
        "cell_persistence":    persist,       # Jaccard 지속성
        "dwell_cell_ratio":    dwell,         # 체류 셀 비율
        "known_vehicle_count": known_cnt,     # 궤적 확인 차량 수
        "occupied_cell_count": occupied_cnt,  # 현재 점유 셀 수
        "count_ref":           count_ref,     # 기준 차량 수 (동적 occ_gate 계산)
        "valid_cell_count":    valid_cell_count,  # 유효 셀 수
    }


class TestCountGateDivisor:
    """count_gate 분모가 10.0으로 변경됐는지 검증.

    count_gate = clip((known_cnt - 2) / 10.0, 0.0, 1.0)
    known_cnt=12 → (12-2)/10.0=1.0 (포화)
    known_cnt=7  → (7-2)/10.0=0.5
    """

    def test_count_gate_saturates_at_12(self):
        """known_cnt=12 일 때 count_gate=1.0 으로 포화돼야 한다 (분모=10).

        [Red] 분모가 8.0이면 known_cnt=12 → (12-2)/8=1.25 → clip=1.0 (같은 결과)
        → 분모가 10.0인 경우 known_cnt=7 로 검증해야 한다.
        """
        # known_cnt=12, 분모=10: (12-2)/10=1.0 → scale_gate=1.0 (최대)
        x_t_12 = _make_xt(known_cnt=12, cds=0.5, dwell=0.5, flow_occ=0.30)
        # known_cnt=13, 분모=10: (13-2)/10=1.1 → clip=1.0 (포화)
        x_t_13 = _make_xt(known_cnt=13, cds=0.5, dwell=0.5, flow_occ=0.30)
        jam_12 = compute_jam_score_fallback(x_t_12)
        jam_13 = compute_jam_score_fallback(x_t_13)
        # 12대와 13대의 jam_score가 동일해야 함 (둘 다 count_gate 포화)
        assert abs(jam_12 - jam_13) < 1e-9, \
            f"known_cnt=12와 13의 jam_score가 달라요: {jam_12:.4f} vs {jam_13:.4f} — count_gate 포화점이 12가 아닙니다"

    def test_count_gate_half_at_7(self):
        """known_cnt=7 일 때 count_gate=0.5 이어야 한다 (분모=10).

        [Red] 분모가 8.0이면 (7-2)/8=0.625 (≠0.5) — 이 테스트로 분모 식별.
        """
        # known_cnt=7 → (7-2)/10=0.5; scale_gate = count_gate * occ_gate
        # occ_gate: flow_occ=0.30, count_ref=8.0, valid_cnt=80 → occ_range=8/80=0.10
        # occ_gate = clip((0.30-0.04)/0.10, 0,1) = clip(2.6, 0,1) = 1.0
        # scale_gate = 0.5 × 1.0 = 0.5
        x_t_7  = _make_xt(known_cnt=7,  cds=0.0, dwell=0.0, persist=0.0,
                           flow_occ=0.30, count_ref=8.0, valid_cell_count=80)
        x_t_12 = _make_xt(known_cnt=12, cds=0.0, dwell=0.0, persist=0.0,
                           flow_occ=0.30, count_ref=8.0, valid_cell_count=80)
        jam_7  = compute_jam_score_fallback(x_t_7)
        jam_12 = compute_jam_score_fallback(x_t_12)
        # cds=dwell=persist=0 → core=0 → jam = 0 * scale_gate + 0.12*√flow_occ
        # 기저 신호(0.12*√flow_occ)는 scale_gate 무관이므로 jam_7 ≈ jam_12 (기저 동일)
        # → scale_gate의 영향을 보려면 cds나 dwell이 있어야 함
        x_t_7_cds  = _make_xt(known_cnt=7,  cds=1.0, dwell=0.0, persist=0.0,
                               flow_occ=0.30, count_ref=8.0, valid_cell_count=80)
        x_t_12_cds = _make_xt(known_cnt=12, cds=1.0, dwell=0.0, persist=0.0,
                               flow_occ=0.30, count_ref=8.0, valid_cell_count=80)
        jam_7_cds  = compute_jam_score_fallback(x_t_7_cds)
        jam_12_cds = compute_jam_score_fallback(x_t_12_cds)
        # known_cnt=12(count_gate=1.0)의 절반이어야 함: ratio ≈ 0.5
        ratio = (jam_7_cds - 0.12 * math.sqrt(0.30)) / (jam_12_cds - 0.12 * math.sqrt(0.30))
        assert abs(ratio - 0.5) < 0.02, \
            f"count_gate(7대)/count_gate(12대) 비율이 0.5이어야 합니다, 현재: {ratio:.3f} — 분모가 10.0인지 확인"


class TestDynamicOccGate:
    """occ_gate 가 count_ref/valid_cell_count 기반 동적 포화점을 사용하는지 검증.

    _occ_gate_lo    = 0.04
    _occ_gate_range = max(0.05, count_ref / valid_cell_count)
    occ_gate        = clip((flow_occ - 0.04) / _occ_gate_range, 0.0, 1.0)
    """

    def test_occ_gate_saturates_at_count_ref_density(self):
        """flow_occ = count_ref/valid_cell_count + 0.04 이상이면 occ_gate=1.0 이어야 한다.

        valid_cnt=80, count_ref=8 → _occ_gate_range=0.10
        포화점: flow_occ = 0.04 + 0.10 = 0.14
        [Red] 고정 공식(+0.20)이면 0.14에서 포화되지 않음: (0.14-0.04)/0.20=0.5 ≠ 1.0
        """
        # flow_occ=0.15 (포화점 0.14 초과) → occ_gate=1.0 기대
        x_t_sat = _make_xt(known_cnt=12, cds=1.0, dwell=0.5, persist=0.0,
                            flow_occ=0.15, count_ref=8.0, valid_cell_count=80)
        # flow_occ=0.06 (포화점 미달) → occ_gate < 1.0 기대
        x_t_low = _make_xt(known_cnt=12, cds=1.0, dwell=0.5, persist=0.0,
                            flow_occ=0.06, count_ref=8.0, valid_cell_count=80)
        jam_sat = compute_jam_score_fallback(x_t_sat)
        jam_low = compute_jam_score_fallback(x_t_low)
        # 포화 상태(0.15)가 미달 상태(0.06)보다 높아야 함 (scale_gate 차이)
        assert jam_sat > jam_low, \
            f"동적 occ_gate: flow_occ=0.15(포화) jam={jam_sat:.4f} ≤ flow_occ=0.06 jam={jam_low:.4f} — 공식 확인"

    def test_occ_gate_lo_is_004(self):
        """occ_gate 하한이 0.04 이어야 한다 (0.06 에서 변경).

        flow_occ=0.05 > 0.04 이면 occ_gate > 0 → core 기여 발생.
        [Red] 하한이 0.06이면 flow_occ=0.05 에서 저규모 가드 반환.
        """
        # flow_occ=0.065 → 저규모 가드(flow_occ<0.06) 통과, occ_gate 계산
        # valid_cnt=80, count_ref=8 → _occ_gate_range=0.10
        # occ_gate = clip((0.065 - 0.04)/0.10, 0,1) = clip(0.25, 0,1) = 0.25 > 0
        x_t = _make_xt(known_cnt=10, occupied_cnt=5, cds=1.0, dwell=0.5, persist=0.0,
                        flow_occ=0.065, count_ref=8.0, valid_cell_count=80)
        jam = compute_jam_score_fallback(x_t)
        # 0.04 하한이면 occ_gate=0.25>0 → core 기여 → jam > 기저 신호
        base = 0.12 * math.sqrt(0.065)
        assert jam > base, \
            f"occ_gate_lo=0.04: flow_occ=0.065에서 jam={jam:.4f} > 기저({base:.4f}) 이어야 합니다"

    def test_dynamic_occ_gate_adapts_to_valid_cell_count(self):
        """valid_cell_count가 달라지면 occ_gate 포화점도 달라져야 한다.

        valid=40 → _occ_gate_range=8/40=0.20 → 포화점 flow_occ≈0.24
        valid=160 → _occ_gate_range=8/160=0.05 → 포화점 flow_occ≈0.09
        flow_occ=0.15 에서 valid=160이 valid=40보다 occ_gate 크다.
        """
        x_small = _make_xt(known_cnt=12, cds=1.0, dwell=0.5, persist=0.0,
                            flow_occ=0.15, count_ref=8.0, valid_cell_count=40)   # 범위=0.20 → 포화 미달
        x_large = _make_xt(known_cnt=12, cds=1.0, dwell=0.5, persist=0.0,
                            flow_occ=0.15, count_ref=8.0, valid_cell_count=160)  # 범위=0.05 → 포화
        jam_small = compute_jam_score_fallback(x_small)
        jam_large = compute_jam_score_fallback(x_large)
        assert jam_large > jam_small, \
            (f"valid=160(포화) jam={jam_large:.4f} ≤ valid=40(미달) jam={jam_small:.4f} — "
             "동적 occ_gate 가 valid_cell_count를 반영해야 합니다")


class TestCoreFormula:
    """core 공식이 0.55*cds + 0.20*persist + 1.00*dwell 로 변경됐는지 검증."""

    def _jam_with_scale1(self, cds=0.0, persist=0.0, dwell=0.0) -> float:
        """scale_gate=1.0 으로 고정해 core 공식만 검증하는 헬퍼.

        조건: known_cnt=12(count_gate=1.0), flow_occ=0.30 with valid=80,count_ref=8
        occ_gate = clip((0.30-0.04)/0.10, 0,1) = clip(2.6,0,1) = 1.0
        scale_gate = 1.0×1.0 = 1.0
        """
        x_t = _make_xt(
            known_cnt=12, occupied_cnt=8,
            cds=cds, persist=persist, dwell=dwell,
            flow_occ=0.30, count_ref=8.0, valid_cell_count=80,
        )
        return compute_jam_score_fallback(x_t)

    def test_cds_coefficient_is_055(self):
        """cds=1.0, persist=0, dwell=0 시 core=0.55 이어야 한다 (1.90 아님).

        [Red] 구 공식: core=1.90×1+0+0=1.90 → jam_with_scale1=1.90+기저 → clip=1.0
              신 공식: core=0.55×1+0+0=0.55 → jam_with_scale1 ≈ 0.55+기저 < 1.0
        """
        jam = self._jam_with_scale1(cds=1.0, persist=0.0, dwell=0.0)
        base = 0.12 * math.sqrt(0.30)
        expected_core = 0.55                              # scale_gate=1.0 → core=0.55
        expected_jam = min(expected_core + base, 1.0)    # clip
        assert abs(jam - expected_jam) < 0.01, \
            f"cds=1 시 jam={jam:.4f}, 기대={expected_jam:.4f} (core=0.55 기준)"

    def test_dwell_coefficient_is_100(self):
        """dwell=0.5, cds=0, persist=0 시 core=0.50 이어야 한다 (√dwell×0.10 아님).

        [Red] 구 공식: core=0.10×√0.5≈0.071 → jam≈0.071+기저
              신 공식: core=1.00×0.5=0.50  → jam≈0.50+기저
        """
        jam = self._jam_with_scale1(cds=0.0, persist=0.0, dwell=0.5)
        base = 0.12 * math.sqrt(0.30)
        expected_core = 1.00 * 0.5                       # 1.00×dwell
        expected_jam = min(expected_core + base, 1.0)
        assert abs(jam - expected_jam) < 0.01, \
            f"dwell=0.5 시 jam={jam:.4f}, 기대={expected_jam:.4f} (1.00×dwell 기준)"

    def test_persist_coefficient_is_020(self):
        """persist=1.0, cds=0, dwell=0 시 core=0.20 이어야 한다 (0.25 아님).

        [Red] 구 공식: core=0.25×1=0.25 → jam≈0.25+기저
              신 공식: core=0.20×1=0.20 → jam≈0.20+기저
        """
        jam = self._jam_with_scale1(cds=0.0, persist=1.0, dwell=0.0)
        base = 0.12 * math.sqrt(0.30)
        expected_core = 0.20 * 1.0                       # 0.20×persist
        expected_jam = min(expected_core + base, 1.0)
        assert abs(jam - expected_jam) < 0.01, \
            f"persist=1 시 jam={jam:.4f}, 기대={expected_jam:.4f} (0.20×persist 기준)"

    def test_dwell_signal_dominates_over_cds(self):
        """dwell=0.6 인 상황이 cds=0.6 보다 jam_score가 높아야 한다.

        신 공식: dwell×1.00 > cds×0.55 → dwell 주 신호로 승격 검증.
        [Red] 구 공식: cds×1.90 > dwell×0.10×√0.6 → cds가 지배 → 이 테스트 실패.
        """
        jam_dwell = self._jam_with_scale1(cds=0.0, persist=0.0, dwell=0.6)
        jam_cds   = self._jam_with_scale1(cds=0.6, persist=0.0, dwell=0.0)
        assert jam_dwell > jam_cds, \
            (f"dwell=0.6 jam={jam_dwell:.4f} ≤ cds=0.6 jam={jam_cds:.4f} — "
             "신 공식에서 dwell(×1.00)이 cds(×0.55)보다 커야 합니다")
