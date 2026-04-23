# tests/test_ref_direction.py
# 교통 모니터링 팀 — _compute_ref_direction 단일 최다 셀 알고리즘 검증
#
# 알고리즘: flow_map 전체 셀 중 count 가 가장 많은 단일 셀의 방향 벡터를
#           기준 방향(ref_direction)으로 채택한다.
#           (final_pj/src/detector.py 와 동일한 로직)
#
# 실행: backend_flask/ 에서
#     pytest tests/test_ref_direction.py -v

import os
import sys
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
# B. 단일 최다 셀 선택 — count 가 가장 많은 셀의 방향이 기준이 되어야 한다
# ═══════════════════════════════════════════════════════════════════════════════

class TestRefDirectionSingleMaxCell:
    """
    알고리즘 명세: flow_map 전체 셀 중 count 가 가장 높은 단일 셀의 방향을
    ref_direction 으로 채택한다. (final_pj/src/detector.py 와 동일)

    단일 셀 방식은 학습이 충분히 완료된 상태(1800프레임) 에서는
    가장 많이 관측된 차선 셀이 대다수 교통 흐름을 대표한다는 전제를 따른다.
    """

    def test_highest_count_cell_direction_is_used(self):
        """
        count 가 가장 높은 단일 셀(←, count=100) 의 방향이 ref_direction 이 되어야 한다.
        다른 셀들이 → 방향이라도 count 가 낮으면 무시된다.
        """
        det, _ = _make_minimal_detector()
        fm = _make_flow_grid(size=5)  # 5×5 = 25 셀

        # 나머지 9개 셀: → 방향, count=3 each (단일 최다보다 낮음)
        positions = [(r, c) for r in range(5) for c in range(5) if (r, c) != (0, 0)]
        for r, c in positions[:9]:
            fm.flow[r, c]  = (1.0, 0.0)   # → 방향
            fm.count[r, c] = 3

        # 셀 (0,0): ← 방향, count=100 — 단일 최다
        fm.flow[0, 0]  = (-1.0, 0.0)
        fm.count[0, 0] = 100

        det.flow = fm
        det._compute_ref_direction()

        vx, vy = det._ref_direction
        # 단일 최다 셀(←, count=100) 의 방향 → vx < 0
        assert vx < 0, (
            f"단일 최다 count 셀(←, count=100) 의 방향이 ref_direction 이어야 하는데 "
            f"vx={vx:.3f} 가 음수가 아닙니다"
        )

    def test_only_max_count_cell_matters_not_sum(self):
        """
        count 합산이 아니라 단일 최다 셀 기준임을 확인한다.
        (↓, count=50) 1개 vs (↑, count=5) 여러 개: 단일 최다 셀(↓)이 기준이어야 함.
        """
        det, _ = _make_minimal_detector()
        fm = _make_flow_grid(size=4)   # 4×4 = 16 셀

        # 셀 (1,1): ↓ 방향(vy>0), count=50 — 단일 최다
        fm.flow[1, 1]  = (0.0, 1.0)    # 화면 아래 (하행)
        fm.count[1, 1] = 50

        # 나머지 10개 셀: ↑ 방향(vy<0), count=5 each (합산 50이지만 단일은 5)
        positions = [(r, c) for r in range(4) for c in range(4) if (r, c) != (1, 1)]
        for r, c in positions[:10]:
            fm.flow[r, c]  = (0.0, -1.0)   # 화면 위 (상행)
            fm.count[r, c] = 5

        det.flow = fm
        det._compute_ref_direction()

        vx, vy = det._ref_direction
        # 단일 최다 셀(↓, count=50) → vy > 0
        assert vy > 0, (
            f"단일 최다 셀(↓, count=50) 이 기준이어야 하는데 "
            f"vy={vy:.3f} 가 양수가 아닙니다"
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
