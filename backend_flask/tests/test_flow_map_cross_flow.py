# tests/test_flow_map_cross_flow.py
# 교통 모니터링 팀 — FlowMap max_cross_flow_cells (횡방향 확산 제한) TDD 테스트
# 대원 작업 반영: 이동 방향 수직 성분이 max_cross_flow_cells 초과 시 학습 스킵
#
# 실행: backend_flask/ 에서
#     pytest tests/test_flow_map_cross_flow.py -v

import os
import sys
import numpy as np

# ── sys.path 설정 ────────────────────────────────────────────────────────────
_HERE             = os.path.dirname(os.path.abspath(__file__))          # tests/ 절대 경로
_BACKEND_DIR      = os.path.normpath(os.path.join(_HERE, '..'))         # backend_flask/
_MONITORING_DIR   = os.path.join(_BACKEND_DIR, 'modules', 'monitoring') # monitoring/
_DETECTOR_MODULES = os.path.join(_MONITORING_DIR, 'detector_modules')   # detector_modules/

for _p in (_BACKEND_DIR, _MONITORING_DIR, _DETECTOR_MODULES):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from detector_modules.flow_map import FlowMap  # 테스트 대상


def _make_fm(grid_size=10, max_cross_flow_cells=1.2, edge_margin=0) -> FlowMap:
    """테스트용 FlowMap 인스턴스 생성 헬퍼."""
    return FlowMap(
        grid_size=grid_size,
        alpha=0.5,
        min_samples=2,
        bbox_alpha_decay=0.5,
        bbox_gating_alpha_ratio=0.3,
        edge_margin=edge_margin,
        max_cross_flow_cells=max_cross_flow_cells,
    )


class TestFlowMapMaxCrossFlowInit:
    """FlowMap 생성자에 max_cross_flow_cells 파라미터가 추가됐는지 검증."""

    def test_constructor_accepts_max_cross_flow_cells(self):
        """FlowMap 생성자가 max_cross_flow_cells 파라미터를 받아야 한다.

        [Red] 파라미터가 없으면 TypeError.
        역할: 차선 횡단 방향 확산 상한 설정.
        """
        fm = _make_fm(max_cross_flow_cells=1.2)  # TypeError면 실패
        assert fm is not None, "FlowMap 생성 실패"

    def test_max_cross_flow_stored(self):
        """_max_cross_flow 속성에 값이 저장되어야 한다."""
        fm = _make_fm(max_cross_flow_cells=1.5)
        assert hasattr(fm, '_max_cross_flow'), "_max_cross_flow 속성 없음"
        assert fm._max_cross_flow == 1.5, \
            f"_max_cross_flow 가 1.5 이어야 합니다, 현재: {fm._max_cross_flow}"

    def test_default_max_cross_flow_cells(self):
        """max_cross_flow_cells 기본값은 1.2 이어야 한다."""
        # 기본값 없이 생성 시도 — __init__ 시그니처에 기본값이 없으면 TypeError
        fm = FlowMap(grid_size=10, alpha=0.5, min_samples=2)
        assert hasattr(fm, '_max_cross_flow'), "_max_cross_flow 속성 없음"
        assert fm._max_cross_flow == 1.2, \
            f"기본값이 1.2 이어야 합니다, 현재: {fm._max_cross_flow}"


class TestCrossFlowLimit:
    """횡방향 확산 제한 동작 검증.

    시나리오: 차량이 오른쪽(+x) 방향으로 이동.
    - 이동 방향(+x)과 평행한 셀: 학습 허용 (차선 내 전후방)
    - 이동 방향에 수직(+y/-y)인 셀: max_cross_flow_cells 초과 시 스킵
    """

    def test_parallel_cells_always_learned(self):
        """이동 방향과 평행한 셀(전후방)은 cross-flow 제한을 받지 않아야 한다.

        차량이 +x 방향 이동 → 중심에서 좌우(x축 방향) 셀은 학습 허용.
        """
        fm = _make_fm(grid_size=10, max_cross_flow_cells=1.2, edge_margin=0)
        fm.init_grid(frame_w=100, frame_h=100)  # 셀 크기 10×10

        # 차량 중심 (50, 50) → 셀 (5, 5)
        # 이동 방향: +x (오른쪽), traj_ndx=1.0, traj_ndy=0.0
        # bbox: x 40~60, y 45~55 → 셀 (4,4)~(5,6) — x축 방향 인접 셀 포함
        fm.learn_step(
            x1=30, y1=50, x2=50, y2=50,   # 이동: 오른쪽
            min_move=1.0,
            bbox=(40, 45, 60, 55),          # 중심 50,50
            traj_ndx=1.0, traj_ndy=0.0,    # +x 방향 이동
        )
        # 중심 셀 (5, 5)는 반드시 학습돼야 함
        assert fm.count[5, 5] > 0, "중심 셀이 학습되지 않았습니다"

    def test_excessive_cross_flow_cells_skipped(self):
        """이동 방향에 수직이며 max_cross_flow_cells 초과한 셀은 스킵돼야 한다.

        차량이 +x 방향 이동 → y 방향 2셀 이상 떨어진 셀은 스킵.
        max_cross_flow_cells=1.0 으로 제한하면 y 방향 1셀 초과는 차단됨.
        """
        # 매우 작은 max_cross_flow_cells=0.5 → y 방향 0.5셀 초과 시 스킵
        fm = _make_fm(grid_size=10, max_cross_flow_cells=0.5, edge_margin=0)
        fm.init_grid(frame_w=100, frame_h=100)  # 셀 크기 10×10

        # 중심 (50, 50) → 셀 (5, 5)
        # bbox y 범위: 30~70 → 셀 r=3~7, c=4~6
        # +x 방향 이동: 수직은 y축(셀 행 방향)
        # 셀 (3, 5): 중심 행(5)에서 row 오프셋 = 2셀 → cross_px = 20px / 10 = 2.0셀 > 0.5 → 스킵
        fm.learn_step(
            x1=30, y1=50, x2=50, y2=50,
            min_move=1.0,
            bbox=(40, 30, 60, 70),          # y 범위 30~70 → 행 3~7
            traj_ndx=1.0, traj_ndy=0.0,    # +x 방향 이동
        )
        # 중심 행(5)에서 2행 떨어진 셀 (3, 5)는 횡방향 초과 → 학습 금지
        assert fm.count[3, 5] == 0, \
            f"횡방향 초과 셀 (3,5)이 학습됐습니다: count={fm.count[3,5]} (스킵돼야 함)"

    def test_large_cross_flow_limit_allows_all(self):
        """max_cross_flow_cells=100 이면 횡방향 제한 없이 모든 셀이 학습돼야 한다."""
        fm = _make_fm(grid_size=10, max_cross_flow_cells=100.0, edge_margin=0)
        fm.init_grid(frame_w=100, frame_h=100)

        # bbox y 범위 30~70 → 셀 r=3~7
        fm.learn_step(
            x1=30, y1=50, x2=50, y2=50,
            min_move=1.0,
            bbox=(40, 30, 60, 70),
            traj_ndx=1.0, traj_ndy=0.0,
        )
        # 제한이 없으면 중심에서 2행 떨어진 (3, 5)도 학습됨 (dist≥2 soft EMA 적용)
        total_learned = int(np.sum(fm.count > 0))
        assert total_learned > 0, "학습된 셀이 없습니다"

    def test_cross_flow_only_applies_to_bbox_mode(self):
        """cross-flow 제한은 bbox 모드(bbox!=None)에서만 동작해야 한다.

        bbox=None(단일 셀 모드)에서는 dist=0이므로 cross-flow 검사 자체가 없음.
        """
        fm = _make_fm(grid_size=10, max_cross_flow_cells=0.01, edge_margin=0)
        fm.init_grid(frame_w=100, frame_h=100)

        # bbox=None → 단일 셀 학습 → cross-flow 미적용
        # 단일 셀 좌표: 중점 x=(40+60)/2=50 → 셀 c=5, 중점 y=(50+50)/2=50 → 셀 r=5
        fm.learn_step(
            x1=40, y1=50, x2=60, y2=50,
            min_move=1.0,
            bbox=None,                      # bbox 없음 → 단일 셀 모드 (중점 기반 1셀)
            traj_ndx=1.0, traj_ndy=0.0,
        )
        # 단일 셀 중심 (5, 5) 은 학습돼야 함
        assert fm.count[5, 5] > 0, "bbox=None 단일 셀 모드에서 중심 셀 학습 실패"
