# tests/test_ref_direction.py
# 교통 모니터링 팀 — _compute_ref_direction 다수결 알고리즘 검증
#
# 버그: 현재 구현은 count 최다 단일 셀의 방향을 기준으로 사용한다.
#       최다 셀이 우연히 소수 방향(예: 하행)에 속하면 기준 방향이 역전됨.
#
# 수정 목표: 모든 유효 셀에 대해 count-가중 다수결 투표로 기준 방향을 결정한다.
#
# 실행: backend_flask/ 에서
#     pytest tests/test_ref_direction.py -v

import os
import sys
import math
from unittest.mock import MagicMock

# ── sys.path 설정 ────────────────────────────────────────────────────────────
_HERE           = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR    = os.path.normpath(os.path.join(_HERE, '..'))
_MONITORING_DIR = os.path.join(_BACKEND_DIR, 'modules', 'monitoring')
_DETECTOR_DIR   = os.path.join(_MONITORING_DIR, 'detector_modules')

for _p in (_BACKEND_DIR, _MONITORING_DIR, _DETECTOR_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

import numpy as np


def _make_flow_grid(size=15):
    """
    (size×size×2) flow 배열과 (size×size) count 배열을 가진 FlowMap mock 을 반환한다.
    flow[r,c] = (vx, vy), count[r,c] = 샘플 수
    """
    fm = MagicMock()
    fm.grid_size = size
    fm.flow  = np.zeros((size, size, 2), dtype=np.float32)  # 방향 벡터
    fm.count = np.zeros((size, size),    dtype=np.int32)     # 샘플 수
    return fm


def _make_minimal_detector():
    """_compute_ref_direction() 호출에 필요한 최소 속성을 가진 객체를 반환한다."""
    import importlib, importlib.util, types

    mod_name = 'monitoring_detector_test_only'
    if mod_name not in sys.modules:
        _md_path = os.path.join(_MONITORING_DIR, 'monitoring_detector.py')
        spec = importlib.util.spec_from_file_location(mod_name, _md_path)
        mod  = importlib.util.module_from_spec(spec)
        # 의존성 mock 처리
        for stub in ('cv2', 'gevent', 'gevent.threadpool', 'flow_map_matcher'):
            sys.modules.setdefault(stub, MagicMock())
        _base_mod = types.ModuleType('modules.traffic.detectors.base_detector')
        _base_mod.BaseDetector = object
        sys.modules['modules.traffic.detectors.base_detector'] = _base_mod
        try:
            spec.loader.exec_module(mod)
            sys.modules[mod_name] = mod
        except Exception as e:
            import pytest
            pytest.skip(f"monitoring_detector 로드 실패: {e}")

    mod = sys.modules[mod_name]
    det = MagicMock()
    det._ref_direction = None
    det._dir_label_a   = "상행"
    det._dir_label_b   = "하행"
    # _compute_ref_direction 을 실제 메서드로 바인딩
    det._compute_ref_direction = lambda: \
        mod.MonitoringDetector._compute_ref_direction(det)
    return det, mod


# ═══════════════════════════════════════════════════════════════════════════════
# A. 단순 단방향 도로 — 모든 셀이 동일 방향을 가리킬 때
# ═══════════════════════════════════════════════════════════════════════════════

class TestRefDirectionUnidirectional:
    """모든 셀이 같은 방향 → 기준 방향이 그 방향을 가리켜야 한다."""

    def test_all_cells_right_gives_ref_right(self):
        """(→) 방향 셀만 있으면 _ref_direction 은 (→) 이어야 한다."""
        det, _ = _make_minimal_detector()
        fm = _make_flow_grid()
        # 모든 셀에 → 방향 벡터와 count 부여
        for r in range(fm.grid_size):
            for c in range(fm.grid_size):
                fm.flow[r, c] = (1.0, 0.0)
                fm.count[r, c] = 10
        det.flow = fm

        det._compute_ref_direction()

        vx, vy = det._ref_direction
        # 기준 방향의 x 성분 > 0 (→ 방향)
        assert vx > 0.9, f"(→) 셀만 있을 때 ref_direction.x={vx:.3f} 가 0.9 이상이어야 합니다"
        assert abs(vy) < 0.2, f"y 성분={vy:.3f} 는 거의 0 이어야 합니다"


# ═══════════════════════════════════════════════════════════════════════════════
# B. 양방향 도로 — 최다 셀이 소수 방향일 때 (핵심 버그 시나리오)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRefDirectionBidirectionalBias:
    """
    최다 count 셀이 소수 방향에 있을 때 다수결로 올바른 기준 방향이 결정되어야 한다.

    시나리오:
      - 셀 1개: ← 방향, count=1000  (최다 count — 현재 구현이 이 셀을 선택)
      - 셀 8개: → 방향, count=10 each (총 80 count — 다수를 차지하는 방향)
      → 현재 구현: _ref_direction = ← (버그)
      → 수정 후:   _ref_direction = → (다수결로 교정)
    """

    def test_majority_right_wins_over_single_high_count_left_cell(self):
        """
        [Red] 최다 count 단일 셀(←)보다 다수 셀(→) 의 합산 count 가 크면
              _ref_direction 은 → 이어야 한다.

        현재 구현: count 최다 셀 = ← 단일 셀 → _ref_direction = ← (잘못됨)
        수정 후:   다수결 → ← count 합(1000) vs → count 합(80)... 아, 이 경우엔 ← 가 이긴다.

        올바른 시나리오:
          - 셀 1개: ← 방향, count=5  (최다 count 이지만 소수)
          - 셀 9개: → 방향, count=3 each (총 27 count — 다수 방향)
          → 현재 구현: _ref_direction = ← (5짜리가 최다라 선택됨)
          → 수정 후:   → (→ 총 count 27 > ← 총 count 5)
        """
        det, _ = _make_minimal_detector()
        fm = _make_flow_grid(size=5)  # 5×5 = 25 셀

        # 셀 (0,0): ← 방향, count=5 (단일 최다)
        fm.flow[0, 0]  = (-1.0, 0.0)
        fm.count[0, 0] = 5

        # 나머지 9개 셀: → 방향, count=3 each (총 count=27 > 5)
        positions = [(r, c) for r in range(5) for c in range(5) if (r, c) != (0, 0)]
        for r, c in positions[:9]:
            fm.flow[r, c]  = (1.0, 0.0)
            fm.count[r, c] = 3

        det.flow = fm
        det._compute_ref_direction()

        vx, vy = det._ref_direction
        # [Red] 현재 구현은 count=5인 ← 셀을 선택 → vx < 0 (버그)
        # [Green] 수정 후에는 → 다수결 → vx > 0
        assert vx > 0, (
            f"[Red] 최다count 단일셀(←, count=5) 보다 다수셀(→, 총count=27)이 많은데 "
            f"_ref_direction.x={vx:.3f} 가 음수입니다 — 다수결 없이 단일 셀 선택"
        )

    def test_majority_up_wins_over_single_high_count_down_cell(self):
        """
        [Red] 수직 방향 도로: 최다 count 단일 셀(↓)보다 다수 셀(↑) 이 올바른 기준.

        상행(↑, vy < 0)이 실제 다수인데 최다 count 셀이 하행(↓) 에 있으면
        현재 구현은 _dir_label_a="UP"으로 잘못 설정한다.
        """
        det, _ = _make_minimal_detector()
        fm = _make_flow_grid(size=5)

        # 셀 (2,2): ↓ 방향(vy>0 = 화면 아래), count=8 (단일 최다)
        fm.flow[2, 2]  = (0.0,  1.0)   # 하행 (화면 아래 = vy 양수)
        fm.count[2, 2] = 8

        # 셀 12개: ↑ 방향(vy<0 = 화면 위), count=2 each (총 count=24 > 8)
        positions = [(r, c) for r in range(5) for c in range(5) if (r, c) != (2, 2)]
        for r, c in positions[:12]:
            fm.flow[r, c]  = (0.0, -1.0)   # 상행 (화면 위)
            fm.count[r, c] = 2

        det.flow = fm
        det._compute_ref_direction()

        vx, vy = det._ref_direction
        # 수정 후: 다수결 ↑ 방향 → vy < 0
        assert vy < 0, (
            f"[Red] 다수셀(↑, vy<0, 총count=24) 이 많은데 "
            f"_ref_direction.y={vy:.3f} 가 음수가 아닙니다 — 단일 최다 셀(↓) 선택"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# C. _dir_label_a / _dir_label_b 할당 일관성
# ═══════════════════════════════════════════════════════════════════════════════

class TestDirLabelAssignment:
    """_ref_direction 결정 후 _dir_label_a/b 가 올바르게 설정되어야 한다."""

    def test_dir_label_a_up_when_ref_vy_negative(self):
        """기준 방향이 ↑ (vy < 0) 이면 _dir_label_a = 'UP' 이어야 한다."""
        det, _ = _make_minimal_detector()
        fm = _make_flow_grid(size=3)
        # 모든 셀: ↑ 방향 (vy = -1)
        for r in range(3):
            for c in range(3):
                fm.flow[r, c]  = (0.0, -1.0)
                fm.count[r, c] = 5
        det.flow = fm
        det._compute_ref_direction()

        assert det._dir_label_a == "UP",   \
            f"vy<0 기준 방향에서 _dir_label_a='{det._dir_label_a}' 는 'UP' 이어야 합니다"
        assert det._dir_label_b == "DOWN", \
            f"_dir_label_b='{det._dir_label_b}' 는 'DOWN' 이어야 합니다"

    def test_dir_label_a_down_when_ref_vy_positive(self):
        """기준 방향이 ↓ (vy ≥ 0) 이면 _dir_label_a = 'DOWN' 이어야 한다."""
        det, _ = _make_minimal_detector()
        fm = _make_flow_grid(size=3)
        # 모든 셀: ↓ 방향 (vy = +1)
        for r in range(3):
            for c in range(3):
                fm.flow[r, c]  = (0.0, 1.0)
                fm.count[r, c] = 5
        det.flow = fm
        det._compute_ref_direction()

        assert det._dir_label_a == "DOWN", \
            f"vy≥0 기준 방향에서 _dir_label_a='{det._dir_label_a}' 는 'DOWN' 이어야 합니다"
        assert det._dir_label_b == "UP",   \
            f"_dir_label_b='{det._dir_label_b}' 는 'UP' 이어야 합니다"
