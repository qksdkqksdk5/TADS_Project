# 파일 경로: modules/monitoring/tests/test_congestion_judge.py
# 역할: CongestionJudge + compute_jam_score_fallback 단위 테스트
# 실행: pytest modules/monitoring/tests/test_congestion_judge.py -v
# TC  : CJ-01 ~ CJ-11

import sys
import pathlib

# detector_modules 경로를 sys.path에 추가한다.
_MONITOR_DIR  = pathlib.Path(__file__).resolve().parent.parent
_MODULES_DIR  = _MONITOR_DIR / "detector_modules"
for _p in (_MONITOR_DIR, _MODULES_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest
from congestion_judge import CongestionJudge, compute_jam_score_fallback


# ======================================================================
# Mock 설정 클래스
# ======================================================================

class _MockCfg:
    """테스트용 DetectorConfig 대역 — CongestionJudge 관련 파라미터만 포함."""
    smooth_jam_threshold      = 0.30   # SMOOTH 상한 임계값
    slow_jam_threshold        = 0.60   # SLOW 상한 / JAM 하한 임계값
    congestion_hysteresis_sec = 15.0   # 레벨 전환 유지 시간 (초)
    jam_ema_alpha_up          = 0.15   # 악화(상승) 방향 EMA 속도
    jam_ema_alpha_down        = 0.04   # 호전(하강) 방향 EMA 속도
    initial_confirm_sec       = 5.0    # 초기 확정 구간 (초)
    initial_hysteresis_sec    = 2.0    # 초기 히스테리시스 (초)


def _make_judge(fps: float = 6.0) -> CongestionJudge:
    """테스트용 CongestionJudge 인스턴스를 생성하고 baseline을 설정한다."""
    j = CongestionJudge(_MockCfg(), fps=fps)
    j.set_baseline()
    return j


# ======================================================================
# feature 벡터 헬퍼
# ======================================================================

def _smooth_xt() -> dict:
    """원활 시나리오: cds 낮음, dwell=0, flow_occ 낮음.
    예상 jam_score < 0.30 (SMOOTH).
    """
    return {
        "cell_dwell_score":    0.05,
        "flow_occupancy":      0.08,
        "cell_persistence":    0.0,
        "dwell_cell_ratio":    0.0,
        "known_vehicle_count": 5,
        "occupied_cell_count": 4,
        "count_ref":           8.0,
        "valid_cell_count":    75,
    }


def _jam_xt() -> dict:
    """정체 시나리오: dwell 높음, cds 높음, flow_occ 충분.
    예상 jam_score >= 0.60 (JAM).
    """
    return {
        "cell_dwell_score":    0.65,
        "flow_occupancy":      0.22,
        "cell_persistence":    0.80,
        "dwell_cell_ratio":    0.08,
        "known_vehicle_count": 18,
        "occupied_cell_count": 15,
        "count_ref":           8.0,
        "valid_cell_count":    75,
    }


def _highway_flowing_xt() -> dict:
    """고속도로 원활 시나리오: 차량 많고 cds 높지만 dwell=0.
    → 체류 차량 없음 → 진짜 정체 아님 → jam_score < 0.60.
    """
    return {
        "cell_dwell_score":    0.70,
        "flow_occupancy":      0.25,
        "cell_persistence":    0.30,
        "dwell_cell_ratio":    0.0,   # 체류 차량 없음
        "known_vehicle_count": 15,
        "occupied_cell_count": 12,
        "count_ref":           8.0,
        "valid_cell_count":    75,
    }


# ======================================================================
# CJ-01: compute_jam_score_fallback 반환값 범위 0.0~1.0
# ======================================================================

def test_cj01_jam_score_range():
    """compute_jam_score_fallback 반환값은 항상 0.0~1.0 범위여야 한다."""
    for x_t in [_smooth_xt(), _jam_xt(), _highway_flowing_xt()]:
        score = compute_jam_score_fallback(x_t)
        assert 0.0 <= score <= 1.0, f"범위 초과: {score:.4f}"


# ======================================================================
# CJ-02: 저규모 가드 — known_vehicle_count <= 2 → jam_score <= 0.10
# ======================================================================

def test_cj02_low_vehicle_guard():
    """known_vehicle_count=1이면 저규모 가드 적용 → jam_score <= 0.10."""
    x_t = dict(_jam_xt())
    x_t["known_vehicle_count"] = 1   # 극소 차량
    score = compute_jam_score_fallback(x_t)
    assert score <= 0.10, f"저규모 가드 위반: jam_score={score:.4f}"


# ======================================================================
# CJ-03: 저규모 가드 — flow_occupancy < 0.06 → jam_score <= 0.10
# ======================================================================

def test_cj03_low_flow_occ_guard():
    """flow_occupancy < 0.06이면 저규모 가드 적용 → jam_score <= 0.10."""
    x_t = dict(_jam_xt())
    x_t["flow_occupancy"] = 0.03   # 거의 빈 도로
    score = compute_jam_score_fallback(x_t)
    assert score <= 0.10, f"low_occ 가드 위반: jam_score={score:.4f}"


# ======================================================================
# CJ-04: 원활 시나리오 → jam_score < 0.30
# ======================================================================

def test_cj04_smooth_scenario():
    """원활 시나리오: jam_score < 0.30 (SMOOTH 판정 기준)."""
    score = compute_jam_score_fallback(_smooth_xt())
    assert score < 0.30, f"원활인데 jam_score={score:.4f} >= 0.30"


# ======================================================================
# CJ-05: 정체 시나리오 → jam_score >= 0.60
# ======================================================================

def test_cj05_jam_scenario():
    """정체 시나리오(dwell 높음): jam_score >= 0.60 (JAM 판정 기준)."""
    score = compute_jam_score_fallback(_jam_xt())
    assert score >= 0.60, f"정체인데 jam_score={score:.4f} < 0.60"


# ======================================================================
# CJ-06: 고속도로 빠른 통과 — dwell=0이면 cds 높아도 JAM 아님
# ======================================================================

def test_cj06_highway_no_dwell_not_jam():
    """dwell_cell_ratio=0(체류 없음)이면 cds 높아도 jam_score < 0.60."""
    score = compute_jam_score_fallback(_highway_flowing_xt())
    assert score < 0.60, f"dwell=0 고속도로인데 jam_score={score:.4f} >= 0.60 (오탐)"


# ======================================================================
# CJ-07: dynamic occ_gate — valid_cell_count 변화 시 포화점 이동
# ======================================================================

def test_cj07_dynamic_occ_gate_saturation():
    """count_ref/valid_cell_count로 occ_gate 포화점이 결정된다."""
    base = {
        "cell_dwell_score":    0.50,
        "flow_occupancy":      0.20,
        "cell_persistence":    0.30,
        "dwell_cell_ratio":    0.06,
        "known_vehicle_count": 14,
        "occupied_cell_count": 10,
        "count_ref":           8.0,
        "valid_cell_count":    75,
    }
    score_v75  = compute_jam_score_fallback(dict(base))
    base2 = dict(base)
    base2["valid_cell_count"] = 400
    score_v400 = compute_jam_score_fallback(base2)

    assert score_v75  > 0.0, f"valid=75 결과 0: {score_v75}"
    assert score_v400 > 0.0, f"valid=400 결과 0: {score_v400}"


# ======================================================================
# CJ-08: update() → (level, jam_score) 튜플 반환
# ======================================================================

def test_cj08_update_returns_valid_tuple():
    """update()는 (level: str, jam_score: float) 튜플을 반환해야 한다."""
    judge  = _make_judge()
    result = judge.update(_smooth_xt(), frame_num=1)

    assert isinstance(result, tuple), "update() 반환 타입은 tuple"
    level, score = result
    assert level in ("SMOOTH", "SLOW", "JAM"), f"유효하지 않은 level: {level}"
    assert isinstance(score, float), "jam_score는 float"
    assert 0.0 <= score <= 1.0, f"jam_score 범위 초과: {score:.4f}"


# ======================================================================
# CJ-09: 히스테리시스 — JAM 진입 후 즉시 SMOOTH 입력해도 JAM 유지
# ======================================================================

def test_cj09_hysteresis_keeps_jam():
    """JAM 진입 후 즉시 SMOOTH 입력해도 히스테리시스 프레임 동안 JAM 유지."""
    fps   = 6.0
    judge = CongestionJudge(_MockCfg(), fps=fps)
    judge.set_baseline()
    hysteresis_frames = int(15.0 * fps)   # 90프레임

    # Phase 1: JAM 상태 진입
    for f in range(1, hysteresis_frames + 2):
        level, _ = judge.update(dict(_jam_xt()), frame_num=f)
    assert level == "JAM", f"JAM 진입 실패: level={level}"

    # Phase 2: 즉시 SMOOTH 입력 → 히스테리시스 내에서 JAM 유지
    base    = hysteresis_frames + 2
    check_n = hysteresis_frames - 2
    for f in range(base, base + check_n):
        level, _ = judge.update(dict(_smooth_xt()), frame_num=f)
    assert level == "JAM", (
        f"히스테리시스 {hysteresis_frames}프레임 이내에서 JAM 유지 실패: level={level}"
    )


# ======================================================================
# CJ-10: 비대칭 EMA — 악화(상승) 방향이 호전(하강) 방향보다 빠름
# ======================================================================

def test_cj10_asymmetric_ema():
    """alpha_up > alpha_down이므로 악화 방향 EMA 변화가 호전 방향보다 크다."""
    fps = 6.0

    # 악화 방향: 0.0 → 1.0
    j_up = CongestionJudge(_MockCfg(), fps=fps)
    j_up.set_baseline()
    _, score_a = j_up.apply_level(0.0, frame_num=1)
    _, score_b = j_up.apply_level(1.0, frame_num=2)
    delta_up   = score_b - score_a

    # 호전 방향: 1.0 → 0.0
    j_dn = CongestionJudge(_MockCfg(), fps=fps)
    j_dn.set_baseline()
    for _f in range(1, 60):
        j_dn.apply_level(1.0, frame_num=_f)
    _, score_c = j_dn.apply_level(1.0, frame_num=60)
    _, score_d = j_dn.apply_level(0.0, frame_num=61)
    delta_down = score_c - score_d

    assert delta_up > delta_down, (
        f"비대칭 EMA 실패: 악화 delta={delta_up:.4f}, 호전 delta={delta_down:.4f}"
    )


# ======================================================================
# CJ-11: update() 100회 반복 호출 — 예외 없음
# ======================================================================

def test_cj11_repeated_update_no_exception():
    """update() 100회 연속 호출해도 예외 없이 정상 동작."""
    judge = _make_judge()
    for f in range(1, 101):
        try:
            level, score = judge.update(_smooth_xt(), frame_num=f)
            assert level in ("SMOOTH", "SLOW", "JAM")
            assert 0.0 <= score <= 1.0
        except Exception as e:
            pytest.fail(f"frame {f}에서 예외 발생: {e}")
