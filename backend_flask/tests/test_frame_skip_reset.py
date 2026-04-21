# tests/test_frame_skip_reset.py
# 교통 모니터링 팀 — 프레임 스킵·단독 점프 리셋 TDD 테스트
#
# 검증 목표:
#   1. 전역 프레임 스킵(50% 이상 차량 동시 점프) 발생 시
#      _apply_frame_skip_reset() 이 post_reconnect_frame 을 현재 프레임 번호로 설정하는가
#   2. 단독 차량 점프 발생 시
#      _apply_solo_jump_reset() 이 post_reconnect_frame 을 현재 프레임 번호로 설정하는가
#   3. 두 함수 모두 기존 기능(궤적 초기화, wrong_way_count 리셋, direction_change_frame 세트)을
#      그대로 수행하는가
#
# 실행: backend_flask/ 에서
#     pytest tests/test_frame_skip_reset.py -v
#
# [Red] 두 함수(_apply_frame_skip_reset, _apply_solo_jump_reset)가
#       monitoring_detector 에 정의되기 전까지는 ImportError 로 실패한다.

import os
import sys

# ── sys.path 설정 ─────────────────────────────────────────────────────────────
# monitoring_detector.py 와 detector_modules/ 를 모두 찾을 수 있어야 한다.
_HERE             = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR      = os.path.normpath(os.path.join(_HERE, '..'))
_MONITORING_DIR   = os.path.join(_BACKEND_DIR, 'modules', 'monitoring')
_DETECTOR_MODULES = os.path.join(_MONITORING_DIR, 'detector_modules')

for _p in (_BACKEND_DIR, _MONITORING_DIR, _DETECTOR_MODULES):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── 순수-Python 모듈만 미리 임포트 (numpy/cv2 없이 동작 가능한 모듈) ──────────
from detector_modules.state import DetectorState  # 상태 객체

# ── 테스트 대상 함수 임포트 ────────────────────────────────────────────────────
# [Red] 아직 이 함수들이 없으므로 ImportError 발생 → 테스트 실패
from modules.monitoring.monitoring_detector import (
    _apply_frame_skip_reset,   # 전역 프레임 스킵 리셋 헬퍼
    _apply_solo_jump_reset,    # 단독 차량 점프 리셋 헬퍼
)


# ─────────────────────────────────────────────────────────────────────────────
# 공통 픽스처 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _make_state(frame_num=100):
    """기본 DetectorState 인스턴스를 만들어 반환한다."""
    st = DetectorState()
    st.frame_num = frame_num  # 현재 프레임 번호 설정
    return st


def _make_tracks(positions):
    """(id, cx, cy) 리스트를 받아 track 딕셔너리 리스트로 변환한다.

    Args:
        positions: [(track_id, cx, cy), ...] 형식의 리스트
    Returns:
        [{"id": ..., "cx": ..., "cy": ...}, ...] 형식의 트랙 리스트
    """
    return [{"id": tid, "cx": cx, "cy": cy} for tid, cx, cy in positions]


# ─────────────────────────────────────────────────────────────────────────────
# _apply_frame_skip_reset 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyFrameSkipReset:
    """전역 프레임 스킵 리셋 함수의 동작을 검증한다."""

    def test_sets_post_reconnect_frame(self):
        """프레임 스킵 리셋 후 post_reconnect_frame 이 현재 프레임 번호로 설정돼야 한다.

        [핵심 버그 수정]
        judge.py 의 _reconnect_guard 는 post_reconnect_frame > 0 일 때만 활성화된다.
        이 값이 설정되지 않으면, 프레임 스킵 후 새로 등장한 차량(ByteTrack 신규 ID)이
        direction_change_guard 보호 밖에 놓여 역주행 오탐이 발생한다.
        """
        st = _make_state(frame_num=150)
        tracks = _make_tracks([(1, 200, 300), (2, 400, 500)])

        # 두 차량 모두 이전 궤적이 있는 상태 (점프 대상)
        st.trajectories[1] = [(100, 100)]  # 이전 위치: (100, 100) → 현재 (200, 300) 로 점프
        st.trajectories[2] = [(100, 100)]  # 이전 위치: (100, 100) → 현재 (400, 500) 로 점프

        _apply_frame_skip_reset(st, tracks, frame_num=150)

        # post_reconnect_frame 이 현재 프레임(150)으로 설정됐는지 확인
        assert st.post_reconnect_frame == 150, (
            f"post_reconnect_frame 이 150 이어야 하지만 {st.post_reconnect_frame} 입니다. "
            "judge.py 의 reconnect_guard 가 작동하려면 이 값이 설정돼야 합니다."
        )

    def test_trajectories_reset_to_current_position(self):
        """프레임 스킵 리셋 후 모든 차량의 궤적이 현재 위치로 덮어써져야 한다.

        velocity 계산(traj[-velocity_window] → traj[-1])에서
        점프 전 좌표가 남아있으면 잘못된 방향 벡터가 계산된다.
        → 궤적 전체를 현재 위치로 채워 방향 기준점을 초기화한다.
        """
        st = _make_state(frame_num=100)
        # 차량 1: 기존 궤적 3점, 현재 위치로 점프
        st.trajectories[1] = [(10, 20), (15, 25), (20, 30)]
        tracks = _make_tracks([(1, 200, 300)])  # 현재 위치 (200, 300)

        _apply_frame_skip_reset(st, tracks, frame_num=100)

        # 궤적의 모든 점이 현재 위치 (200, 300) 으로 교체됐는지 확인
        assert all(p == (200, 300) for p in st.trajectories[1]), (
            f"궤적이 현재 위치로 초기화되지 않았습니다: {st.trajectories[1]}"
        )

    def test_wrong_way_count_reset(self):
        """프레임 스킵 리셋 후 wrong_way_count 가 0 으로 초기화돼야 한다."""
        st = _make_state(frame_num=100)
        st.wrong_way_count[1] = 15   # 이미 15회 의심 누적된 상태
        st.trajectories[1] = [(50, 50)]
        tracks = _make_tracks([(1, 200, 300)])

        _apply_frame_skip_reset(st, tracks, frame_num=100)

        assert st.wrong_way_count[1] == 0, (
            f"wrong_way_count 가 0 이어야 하지만 {st.wrong_way_count[1]} 입니다."
        )

    def test_direction_change_frame_set(self):
        """프레임 스킵 리셋 후 direction_change_frame 이 현재 프레임으로 설정돼야 한다.

        이 값이 설정돼야 judge.py 의 direction_change_guard 가 120프레임 동안 작동한다.
        (기존 ID를 가진 차량 보호용)
        """
        st = _make_state(frame_num=200)
        st.trajectories[1] = [(50, 50)]
        tracks = _make_tracks([(1, 300, 400)])

        _apply_frame_skip_reset(st, tracks, frame_num=200)

        assert st.direction_change_frame.get(1) == 200, (
            f"direction_change_frame[1] 이 200 이어야 하지만 "
            f"{st.direction_change_frame.get(1)} 입니다."
        )

    def test_last_velocity_cleared(self):
        """프레임 스킵 리셋 후 last_velocity 가 삭제돼야 한다.

        점프 전 방향 벡터가 남아있으면 dir_jump 필터가 오작동한다.
        """
        st = _make_state(frame_num=100)
        st.last_velocity[1] = (0.9, 0.1)   # 이전 방향 벡터 기록
        st.trajectories[1] = [(50, 50)]
        tracks = _make_tracks([(1, 200, 300)])

        _apply_frame_skip_reset(st, tracks, frame_num=100)

        assert 1 not in st.last_velocity, (
            "last_velocity 가 삭제되지 않았습니다."
        )

    def test_wrong_way_ids_discarded(self):
        """프레임 스킵 직전에 역주행으로 확정된 차량이 있으면 취소돼야 한다.

        스킵 직전 마지막 프레임에서 오탐이 확정됐을 경우를 되돌린다.
        """
        st = _make_state(frame_num=100)
        st.wrong_way_ids.add(1)   # 스킵 직전에 확정된 역주행 차량
        st.trajectories[1] = [(50, 50)]
        tracks = _make_tracks([(1, 200, 300)])

        _apply_frame_skip_reset(st, tracks, frame_num=100)

        assert 1 not in st.wrong_way_ids, (
            "wrong_way_ids 에서 해당 차량이 제거되지 않았습니다."
        )

    def test_multiple_tracks_all_reset(self):
        """여러 차량이 있을 때 모두 동시에 리셋돼야 한다."""
        st = _make_state(frame_num=100)
        for tid in [1, 2, 3]:
            st.trajectories[tid] = [(10, 10), (20, 20)]
            st.wrong_way_count[tid] = 5
            st.wrong_way_ids.add(tid)
        tracks = _make_tracks([(1, 100, 100), (2, 200, 200), (3, 300, 300)])

        _apply_frame_skip_reset(st, tracks, frame_num=100)

        # 세 차량 모두 초기화 확인
        for tid, cx, cy in [(1, 100, 100), (2, 200, 200), (3, 300, 300)]:
            assert all(p == (cx, cy) for p in st.trajectories[tid]), \
                f"ID {tid} 궤적이 초기화되지 않았습니다."
            assert st.wrong_way_count[tid] == 0, \
                f"ID {tid} wrong_way_count 가 0 이 아닙니다."
            assert tid not in st.wrong_way_ids, \
                f"ID {tid} 가 wrong_way_ids 에서 제거되지 않았습니다."


# ─────────────────────────────────────────────────────────────────────────────
# _apply_solo_jump_reset 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestApplySoloJumpReset:
    """단독 차량 점프 리셋 함수의 동작을 검증한다."""

    def test_sets_post_reconnect_frame(self):
        """단독 차량 점프 리셋 후 post_reconnect_frame 이 현재 프레임 번호로 설정돼야 한다.

        [버그 수정]
        단독 점프는 ByteTrack 이 해당 차량 ID 를 잃고 재할당하는 신호다.
        이후 새로 등장하는 ID 도 reconnect_guard 로 보호돼야 오탐을 막을 수 있다.
        """
        st = _make_state(frame_num=80)
        st.trajectories[5] = [(10, 10), (20, 20), (30, 30)]  # 기존 궤적

        cur_pos = (200, 300)  # 단독 점프 후 현재 위치
        _apply_solo_jump_reset(st, tid=5, cur_pos=cur_pos, frame_num=80)

        assert st.post_reconnect_frame == 80, (
            f"post_reconnect_frame 이 80 이어야 하지만 {st.post_reconnect_frame} 입니다."
        )

    def test_trajectory_reset_to_current_position(self):
        """단독 점프 리셋 후 해당 차량의 궤적이 현재 위치로 초기화돼야 한다."""
        st = _make_state(frame_num=80)
        st.trajectories[5] = [(10, 10), (20, 20), (30, 30)]

        cur_pos = (200, 300)
        _apply_solo_jump_reset(st, tid=5, cur_pos=cur_pos, frame_num=80)

        assert all(p == (200, 300) for p in st.trajectories[5]), (
            f"궤적이 현재 위치로 초기화되지 않았습니다: {st.trajectories[5]}"
        )

    def test_wrong_way_count_reset(self):
        """단독 점프 리셋 후 해당 차량의 wrong_way_count 가 0 이어야 한다."""
        st = _make_state(frame_num=80)
        st.wrong_way_count[5] = 18   # 임계값(20) 직전까지 쌓인 상태
        st.trajectories[5] = [(10, 10)]

        _apply_solo_jump_reset(st, tid=5, cur_pos=(200, 300), frame_num=80)

        assert st.wrong_way_count[5] == 0, (
            f"wrong_way_count 가 0 이어야 하지만 {st.wrong_way_count[5]} 입니다."
        )

    def test_direction_change_frame_set(self):
        """단독 점프 리셋 후 direction_change_frame 이 현재 프레임으로 설정돼야 한다."""
        st = _make_state(frame_num=80)
        st.trajectories[5] = [(10, 10)]

        _apply_solo_jump_reset(st, tid=5, cur_pos=(200, 300), frame_num=80)

        assert st.direction_change_frame.get(5) == 80, (
            f"direction_change_frame[5] 이 80 이어야 하지만 "
            f"{st.direction_change_frame.get(5)} 입니다."
        )

    def test_last_velocity_cleared(self):
        """단독 점프 리셋 후 해당 차량의 last_velocity 가 삭제돼야 한다."""
        st = _make_state(frame_num=80)
        st.last_velocity[5] = (0.7, 0.3)
        st.trajectories[5] = [(10, 10)]

        _apply_solo_jump_reset(st, tid=5, cur_pos=(200, 300), frame_num=80)

        assert 5 not in st.last_velocity, "last_velocity 가 삭제되지 않았습니다."

    def test_wrong_way_ids_discarded(self):
        """단독 점프 리셋 후 해당 차량이 wrong_way_ids 에서 제거돼야 한다."""
        st = _make_state(frame_num=80)
        st.wrong_way_ids.add(5)
        st.trajectories[5] = [(10, 10)]

        _apply_solo_jump_reset(st, tid=5, cur_pos=(200, 300), frame_num=80)

        assert 5 not in st.wrong_way_ids, "wrong_way_ids 에서 제거되지 않았습니다."

    def test_only_target_vehicle_affected(self):
        """단독 점프 리셋은 지정된 차량만 영향을 주고 다른 차량은 건드리지 않아야 한다."""
        st = _make_state(frame_num=80)
        # 두 차량 설정
        st.trajectories[5] = [(10, 10)]
        st.wrong_way_count[5] = 10
        st.trajectories[7] = [(50, 50), (60, 60)]  # 다른 차량
        st.wrong_way_count[7] = 8                   # 다른 차량의 카운트

        _apply_solo_jump_reset(st, tid=5, cur_pos=(200, 300), frame_num=80)

        # 차량 7은 영향을 받지 않아야 함
        assert st.wrong_way_count[7] == 8, \
            "다른 차량(ID=7)의 wrong_way_count 가 변경됐습니다."
        assert st.trajectories[7] == [(50, 50), (60, 60)], \
            "다른 차량(ID=7)의 궤적이 변경됐습니다."
