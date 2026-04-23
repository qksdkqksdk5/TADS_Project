# tests/test_feature_extractor_count_ref.py
# 교통 모니터링 팀 — feature_extractor count_ref 추가 TDD 테스트
# 대원 작업 반영: congestion_judge.py의 동적 occ_gate 계산에 필요한
#                count_ref를 feature vector에 포함
#
# 실행: backend_flask/ 에서
#     pytest tests/test_feature_extractor_count_ref.py -v

import os
import sys
import numpy as np

# ── sys.path 설정 ────────────────────────────────────────────────────────────
_HERE             = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR      = os.path.normpath(os.path.join(_HERE, '..'))
_MONITORING_DIR   = os.path.join(_BACKEND_DIR, 'modules', 'monitoring')
_DETECTOR_MODULES = os.path.join(_MONITORING_DIR, 'detector_modules')

for _p in (_BACKEND_DIR, _MONITORING_DIR, _DETECTOR_MODULES):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from detector_modules.feature_extractor import FeatureExtractor  # 테스트 대상
from detector_modules.flow_map import FlowMap                     # FlowMap 의존
from detector_modules.config import DetectorConfig                # 설정
from detector_modules.state import DetectorState                  # State 의존


def _make_fe(count_ref: float = 8.0) -> tuple:
    """테스트용 FeatureExtractor + FlowMap 인스턴스 생성 헬퍼."""
    cfg = DetectorConfig()
    cfg.count_ref = count_ref          # 기준 차량 수 설정
    fm = FlowMap(
        grid_size=cfg.grid_size,
        alpha=cfg.alpha,
        min_samples=cfg.min_samples,
    )
    fm.init_grid(frame_w=640, frame_h=480)  # 일반적인 해상도 초기화
    state = DetectorState()                 # FeatureExtractor에 필요한 런타임 상태
    fe = FeatureExtractor(cfg=cfg, state=state, fps=30.0)
    fe.set_ready()  # compute()가 None을 반환하지 않도록 준비 완료 상태로 전환
    return fe, fm


class TestCountRefInFeatureVector:
    """count_ref 값이 feature vector에 포함되는지 검증."""

    def test_count_ref_key_exists(self):
        """extract() 결과 dict에 'count_ref' 키가 있어야 한다.

        [Red] count_ref 가 feature vector에 없으면 KeyError.
        역할: congestion_judge.py 의 동적 occ_gate = count_ref/valid_cell_count
              계산에 필요 — feature vector 없이는 기본값(8.0)만 사용됨.
        """
        fe, fm = _make_fe(count_ref=8.0)
        # extract()는 차량 정보 없이 호출 가능 (빈 상태 허용)
        x_t = fe.compute(
            tracks=[],               # 추적 차량 없음
            speeds={},               # 속도 없음
            flow_map=fm,             # flow_map 참조
            frame_num=0,             # 프레임 번호
        )
        assert 'count_ref' in x_t, \
            f"feature vector에 'count_ref' 키가 없습니다. 현재 키: {list(x_t.keys())}"

    def test_count_ref_value_matches_config(self):
        """feature vector의 count_ref 값이 config.count_ref와 일치해야 한다."""
        fe, fm = _make_fe(count_ref=12.0)  # 기본값 아닌 값으로 테스트
        x_t = fe.compute(
            tracks=[], speeds={}, flow_map=fm, frame_num=0,
        )
        assert x_t['count_ref'] == 12.0, \
            f"count_ref 가 12.0 이어야 합니다, 현재: {x_t['count_ref']}"

    def test_count_ref_default_value(self):
        """count_ref 기본값이 8.0 이어야 한다 (config 기본값과 일치)."""
        cfg = DetectorConfig()
        assert cfg.count_ref == 8.0, \
            f"config.count_ref 기본값이 8.0 이어야 합니다, 현재: {cfg.count_ref}"

        fe, fm = _make_fe(count_ref=8.0)
        x_t = fe.compute(
            tracks=[], speeds={}, flow_map=fm, frame_num=0,
        )
        assert x_t['count_ref'] == 8.0, \
            f"feature vector count_ref 기본값이 8.0 이어야 합니다, 현재: {x_t['count_ref']}"

    def test_count_ref_is_float(self):
        """count_ref 값이 float 타입이어야 한다 (congestion_judge 연산 호환)."""
        fe, fm = _make_fe(count_ref=10.0)
        x_t = fe.compute(
            tracks=[], speeds={}, flow_map=fm, frame_num=0,
        )
        assert isinstance(x_t['count_ref'], float), \
            f"count_ref 가 float 이어야 합니다, 현재 타입: {type(x_t['count_ref'])}"
