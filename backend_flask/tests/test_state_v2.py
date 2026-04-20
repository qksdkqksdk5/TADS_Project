# tests/test_state_v2.py
# 교통 모니터링 팀 — DetectorState v2 TDD 테스트
# 커밋 2 (117~122차) 추가된 상태 필드 검증
#
# 실행: backend_flask/ 에서
#     pytest tests/test_state_v2.py -v

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

from detector_modules.state import DetectorState  # 테스트 대상


class TestDetectorStateV2:
    """DetectorState 의 v2 신규 필드를 검증한다."""

    # ── post_reconnect_frame ─────────────────────────────────────────────────
    def test_post_reconnect_frame_exists(self):
        """DetectorState 에 post_reconnect_frame 필드가 있어야 한다.

        [Red] 필드가 없으면 AttributeError.
        역할: 카메라 freeze 재연결 감지 시 fast-track/확정을 일시 차단하는 기준 프레임.
        """
        st = DetectorState()
        assert hasattr(st, 'post_reconnect_frame'), \
            "post_reconnect_frame 필드가 없습니다"

    def test_post_reconnect_frame_initial_value(self):
        """post_reconnect_frame 초기값은 0 이어야 한다 (재연결 없음을 의미)."""
        st = DetectorState()
        assert st.post_reconnect_frame == 0, \
            f"초기값이 0이 아닙니다: {st.post_reconnect_frame}"

    # ── wrong_zone_confirmed ─────────────────────────────────────────────────
    def test_wrong_zone_confirmed_exists(self):
        """DetectorState 에 wrong_zone_confirmed 필드가 있어야 한다.

        [Red] 필드가 없으면 AttributeError.
        역할: 같은 grid cell에서 연속 역주행 확정 시 에코 오탐을 차단하는 쿨다운 맵.
        """
        st = DetectorState()
        assert hasattr(st, 'wrong_zone_confirmed'), \
            "wrong_zone_confirmed 필드가 없습니다"

    def test_wrong_zone_confirmed_initial_value(self):
        """wrong_zone_confirmed 초기값은 빈 딕셔너리여야 한다."""
        st = DetectorState()
        assert isinstance(st.wrong_zone_confirmed, dict), \
            "wrong_zone_confirmed 는 dict 여야 합니다"
        assert len(st.wrong_zone_confirmed) == 0, \
            "초기값이 비어있지 않습니다"

    def test_wrong_zone_confirmed_stores_frame(self):
        """wrong_zone_confirmed 에 (r,c) 키로 프레임 번호를 저장할 수 있어야 한다."""
        st = DetectorState()
        st.wrong_zone_confirmed[(3, 5)] = 120   # 셀 (3,5) 에서 120프레임에 확정
        assert st.wrong_zone_confirmed[(3, 5)] == 120


class TestDetectorStateResetV2:
    """reset_for_relearn() 이 새 필드도 올바르게 초기화하는지 검증한다."""

    def test_reset_clears_wrong_zone_confirmed(self):
        """reset_for_relearn() 후 wrong_zone_confirmed 가 비어야 한다.

        [Red] reset_for_relearn() 에 초기화 코드가 없으면 이전 값이 남음.
        """
        st = DetectorState()
        st.wrong_zone_confirmed[(2, 3)] = 500  # 데이터 삽입
        st.wrong_zone_confirmed[(4, 1)] = 600

        st.reset_for_relearn()

        assert len(st.wrong_zone_confirmed) == 0, \
            "reset_for_relearn() 후 wrong_zone_confirmed 가 비어있지 않습니다"

    def test_reset_sets_relearning_true(self):
        """reset_for_relearn() 후 relearning 이 True 여야 한다 (기존 동작 유지)."""
        st = DetectorState()
        st.reset_for_relearn()
        assert st.relearning is True

    def test_post_reconnect_frame_survives_reset(self):
        """post_reconnect_frame 은 reset_for_relearn() 과 무관하게 유지되어야 한다.

        근거: 재연결은 카메라 신호 레벨 이벤트 — 재학습 중에도 유효.
        """
        st = DetectorState()
        st.post_reconnect_frame = 300  # 300프레임에 재연결 감지됨

        st.reset_for_relearn()

        # post_reconnect_frame 은 reset 에서 변경하지 않음
        # (frame-level 이벤트이므로 재학습과 독립적)
        # 이 테스트는 '건드리지 않는다'는 계약을 문서화
        assert st.post_reconnect_frame == 300, \
            "post_reconnect_frame 이 reset_for_relearn() 에서 변경되면 안 됩니다"
