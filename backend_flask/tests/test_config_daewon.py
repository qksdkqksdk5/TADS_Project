# tests/test_config_daewon.py
# 교통 모니터링 팀 — 대원 작업 반영 파라미터 TDD 테스트
# 변경 항목: max_cross_flow_cells 신규, gru_seq_len/gru_predict_horizons_sec/
#            gru_retrain_interval_sec 수정, smooth_jam_threshold 수정
#
# 실행: backend_flask/ 에서
#     pytest tests/test_config_daewon.py -v

import os
import sys

# ── sys.path 설정 ────────────────────────────────────────────────────────────
_HERE             = os.path.dirname(os.path.abspath(__file__))          # tests/ 절대 경로
_BACKEND_DIR      = os.path.normpath(os.path.join(_HERE, '..'))         # backend_flask/
_MONITORING_DIR   = os.path.join(_BACKEND_DIR, 'modules', 'monitoring') # monitoring/
_DETECTOR_MODULES = os.path.join(_MONITORING_DIR, 'detector_modules')   # detector_modules/

for _p in (_BACKEND_DIR, _MONITORING_DIR, _DETECTOR_MODULES):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from detector_modules.config import DetectorConfig  # 테스트 대상


class TestMaxCrossFlowCells:
    """max_cross_flow_cells 신규 파라미터 검증 (차선 횡단 방향 확산 제한)."""

    def test_max_cross_flow_cells_exists(self):
        """max_cross_flow_cells 파라미터가 존재해야 한다.

        [Red] 파라미터가 없으면 AttributeError.
        역할: 차량 이동 방향 기준 수직 방향(차선 횡단) 확산을 1.2셀 이내로 제한.
        bbox_learn_w_ratio(bbox 폭 기반)와 달리 이동 각도 기반이므로 곡선 구간 적응.
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'max_cross_flow_cells'), \
            "max_cross_flow_cells 파라미터가 없습니다 — config.py에 추가 필요"

    def test_max_cross_flow_cells_value(self):
        """max_cross_flow_cells 기본값이 1.2 이어야 한다.

        1.2 = 수직 방향 1셀 + 약간의 여유 (대각선 허용).
        이동 방향 평행(전후방)은 무제한 → 차선 내 커버리지 유지.
        """
        cfg = DetectorConfig()
        assert cfg.max_cross_flow_cells == 1.2, \
            f"max_cross_flow_cells 가 1.2 이어야 합니다, 현재: {cfg.max_cross_flow_cells}"


class TestGruSeqLen:
    """gru_seq_len 수정값 검증 (30 → 90)."""

    def test_gru_seq_len_updated(self):
        """gru_seq_len 이 90 이어야 한다 (30 → 90).

        이유: 5분 예측에 5초(30f) 창은 부족 → 15초(90f) 창으로 확대.
        GRU 입력 시퀀스가 길수록 장기 정체 패턴 인식 향상.
        """
        cfg = DetectorConfig()
        assert cfg.gru_seq_len == 90, \
            f"gru_seq_len 이 90 이어야 합니다, 현재: {cfg.gru_seq_len}"


class TestGruPredictHorizons:
    """gru_predict_horizons_sec 단순화 검증 (1·3·5분 → 5분 단일)."""

    def test_gru_predict_horizons_sec_simplified(self):
        """gru_predict_horizons_sec 가 (300,) 이어야 한다.

        이유: 1·3·5분 멀티헤드 → 5분 단일 예측으로 단순화.
        멀티헤드 학습 시 레이블 부족으로 인한 헤드별 불균형 문제 해소.
        """
        cfg = DetectorConfig()
        assert cfg.gru_predict_horizons_sec == (300,), \
            f"gru_predict_horizons_sec 가 (300,) 이어야 합니다, 현재: {cfg.gru_predict_horizons_sec}"

    def test_gru_predict_horizons_sec_single_element(self):
        """gru_predict_horizons_sec 가 원소 1개짜리 튜플이어야 한다."""
        cfg = DetectorConfig()
        assert len(cfg.gru_predict_horizons_sec) == 1, \
            f"gru_predict_horizons_sec 는 원소 1개여야 합니다, 현재: {len(cfg.gru_predict_horizons_sec)}개"


class TestGruRetrainInterval:
    """gru_retrain_interval_sec 수정값 검증 (3600 → 1200)."""

    def test_gru_retrain_interval_sec_updated(self):
        """gru_retrain_interval_sec 가 1200.0 이어야 한다 (3600 → 1200).

        이유: 재학습 주기 단축 → JAM 패턴 빠른 반영 (1시간 → 20분).
        """
        cfg = DetectorConfig()
        assert cfg.gru_retrain_interval_sec == 1200.0, \
            f"gru_retrain_interval_sec 가 1200.0 이어야 합니다, 현재: {cfg.gru_retrain_interval_sec}"


class TestSmoothJamThreshold:
    """smooth_jam_threshold 수정값 검증 (0.25 → 0.30)."""

    def test_smooth_jam_threshold_updated(self):
        """smooth_jam_threshold 가 0.30 이어야 한다 (0.25 → 0.30).

        이유: dwell 가중치 승격(주 신호) 후 jam_score 분포가 상향 이동.
        임계값도 함께 올려 SMOOTH 판정 과대 방지.
        """
        cfg = DetectorConfig()
        assert cfg.smooth_jam_threshold == 0.30, \
            f"smooth_jam_threshold 가 0.30 이어야 합니다, 현재: {cfg.smooth_jam_threshold}"

    def test_slow_jam_threshold_unchanged(self):
        """slow_jam_threshold 는 0.60 으로 유지되어야 한다.

        JAM 임계값: 0.55 → 0.60 (smooth와 함께 상향).
        현재 config 값 0.60 이 이미 반영된 값.
        """
        cfg = DetectorConfig()
        assert cfg.slow_jam_threshold == 0.60, \
            f"slow_jam_threshold 가 0.60 이어야 합니다, 현재: {cfg.slow_jam_threshold}"
