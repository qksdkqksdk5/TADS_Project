# tests/test_config_v4.py
# 교통 모니터링 팀 — DetectorConfig v4 파라미터 TDD 테스트
# 커밋 1·2 (101~122차) 신규 파라미터 및 수정값 검증
#
# 실행: backend_flask/ 에서
#     pytest tests/test_config_v4.py -v

import os
import sys

# ── sys.path 설정 ────────────────────────────────────────────────────────────
_HERE             = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR      = os.path.normpath(os.path.join(_HERE, '..'))
_MONITORING_DIR   = os.path.join(_BACKEND_DIR, 'modules', 'monitoring')
_DETECTOR_MODULES = os.path.join(_MONITORING_DIR, 'detector_modules')

for _p in (_BACKEND_DIR, _MONITORING_DIR, _DETECTOR_MODULES):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from detector_modules.config import DetectorConfig  # 테스트 대상


class TestConfigFastTrack:
    """고신뢰 즉시 확정(fast-track) 관련 파라미터 검증."""

    def test_fast_confirm_ratio_exists(self):
        """fast_confirm_ratio 파라미터가 있어야 한다.

        [Red] 파라미터가 없으면 AttributeError.
        역할: 투표 역방향 비율이 이 값 이상이면 즉시 확정 (fast-track 발동 조건).
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'fast_confirm_ratio'), "fast_confirm_ratio 가 없습니다"
        assert cfg.fast_confirm_ratio == 0.95

    def test_fast_confirm_speed_exists(self):
        """fast_confirm_speed 파라미터가 있어야 한다.

        역할: nm_speed 가 이 값 이상이어야 fast-track 적용 (서행 오탐 방지).
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'fast_confirm_speed'), "fast_confirm_speed 가 없습니다"
        assert cfg.fast_confirm_speed == 0.20

    def test_fast_confirm_min_age_exists(self):
        """fast_confirm_min_age 파라미터가 있어야 한다.

        역할: 트랙 나이가 이 값 이상이어야 fast-track 적용 (새 씬 오탐 방지).
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'fast_confirm_min_age'), "fast_confirm_min_age 가 없습니다"
        assert cfg.fast_confirm_min_age == 45

    def test_post_slow_guard_frames_exists(self):
        """post_slow_guard_frames 파라미터가 있어야 한다.

        역할: 서행→가속 직후 fast-track 오탐 방지 최소 의심 유지 프레임.
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'post_slow_guard_frames'), "post_slow_guard_frames 가 없습니다"
        assert cfg.post_slow_guard_frames == 30


class TestConfigNeighborGuard:
    """이웃 차량 방향 일치 가드 파라미터 검증."""

    def test_neighbor_guard_min_total_exists(self):
        """neighbor_guard_min_total 파라미터가 있어야 한다.

        역할: 이웃 가드 발동 최소 같은분류 차량 수 — 이 미만이면 가드 비적용.
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'neighbor_guard_min_total'), \
            "neighbor_guard_min_total 가 없습니다"
        assert cfg.neighbor_guard_min_total == 2

    def test_neighbor_guard_agree_exists(self):
        """neighbor_guard_agree 파라미터가 있어야 한다.

        역할: 이 수 이상의 이웃이 같은 방향이면 오탐으로 취소.
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'neighbor_guard_agree'), "neighbor_guard_agree 가 없습니다"
        assert cfg.neighbor_guard_agree == 1


class TestConfigZoneCooldown:
    """구역 확정 쿨다운 파라미터 검증."""

    def test_wrong_zone_cooldown_frames_exists(self):
        """wrong_zone_cooldown_frames 파라미터가 있어야 한다.

        역할: 같은 grid cell 에서 이 프레임 이내 연속 확정은 에코 오탐으로 차단.
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'wrong_zone_cooldown_frames'), \
            "wrong_zone_cooldown_frames 가 없습니다"
        assert cfg.wrong_zone_cooldown_frames == 900


class TestConfigBboxLearning:
    """bbox 풋프린트 학습 관련 파라미터 검증."""

    def test_bbox_contra_threshold_exists(self):
        """bbox_contra_threshold 파라미터가 있어야 한다.

        역할: 반대방향 bbox 방문 횟수 임계값 — 3→8 (bbox 확장 후 과잉 침식 방지).
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'bbox_contra_threshold'), \
            "bbox_contra_threshold 가 없습니다"
        assert cfg.bbox_contra_threshold == 8

    def test_bbox_alpha_decay_exists(self):
        """bbox_alpha_decay 파라미터가 있어야 한다.

        역할: bbox 중심에서 멀어질수록 alpha 를 감쇠 (중앙점 우선 학습).
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'bbox_alpha_decay'), "bbox_alpha_decay 가 없습니다"
        assert cfg.bbox_alpha_decay == 0.5

    def test_bbox_gating_alpha_ratio_exists(self):
        """bbox_gating_alpha_ratio 파라미터가 있어야 한다.

        역할: 감쇠 비율 이 값 미만이면 방향 게이팅·count 증가 비적용.
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'bbox_gating_alpha_ratio'), \
            "bbox_gating_alpha_ratio 가 없습니다"
        assert cfg.bbox_gating_alpha_ratio == 0.3

    def test_flow_map_edge_margin_exists(self):
        """flow_map_edge_margin 파라미터가 있어야 한다.

        역할: 그리드 외곽 N줄은 학습하지 않음 (가장자리 오염 방지).
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'flow_map_edge_margin'), "flow_map_edge_margin 가 없습니다"
        assert cfg.flow_map_edge_margin == 1

    def test_bbox_learn_w_ratio_exists(self):
        """bbox_learn_w_ratio 파라미터가 있어야 한다.

        역할: 학습 bbox 반폭을 bbox_h × 이 값으로 제한 (중앙선 침범 방지).
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'bbox_learn_w_ratio'), "bbox_learn_w_ratio 가 없습니다"
        assert cfg.bbox_learn_w_ratio == 0.8


class TestConfigUpdatedValues:
    """기존 파라미터 수정값 검증."""

    def test_wrong_count_threshold_updated(self):
        """wrong_count_threshold 가 20 이어야 한다 (25 → 20).

        이유: fast-track 경로 추가로 일반 경로 보수적 유지 필요성 감소.
        """
        cfg = DetectorConfig()
        assert cfg.wrong_count_threshold == 20, \
            f"wrong_count_threshold 가 20 이어야 합니다, 현재: {cfg.wrong_count_threshold}"

    def test_min_wrongway_track_age_updated(self):
        """min_wrongway_track_age 가 20 이어야 한다 (45 → 20).

        이유: 빠른 역주행 차량 age gate 병목 해소.
        """
        cfg = DetectorConfig()
        assert cfg.min_wrongway_track_age == 20, \
            f"min_wrongway_track_age 가 20 이어야 합니다, 현재: {cfg.min_wrongway_track_age}"

    def test_gru_blend_ratio_zero(self):
        """gru_blend_ratio 가 0.0 이어야 한다 (0.20 → 0.0).

        이유: 클래스 불균형·레이블 오염 해결 전까지 GRU 비활성화.
        """
        cfg = DetectorConfig()
        assert cfg.gru_blend_ratio == 0.0, \
            f"gru_blend_ratio 가 0.0 이어야 합니다, 현재: {cfg.gru_blend_ratio}"

    def test_min_freeze_frames_exists(self):
        """min_freeze_frames 파라미터가 있어야 한다.

        역할: 이 이상 정지 프레임이 연속되면 freeze 로 확정.
        """
        cfg = DetectorConfig()
        assert hasattr(cfg, 'min_freeze_frames'), "min_freeze_frames 가 없습니다"
        assert cfg.min_freeze_frames == 10
