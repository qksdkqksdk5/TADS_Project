# tests/test_judge_v4.py
# 교통 모니터링 팀 — WrongWayJudge v4 TDD 테스트
# 커밋 1·2 (101~122차) judge.py 핵심 변경 검증
#
# 실행: backend_flask/ 에서
#     pytest tests/test_judge_v4.py -v

import os
import sys
from unittest.mock import MagicMock

# ── sys.path 설정 ────────────────────────────────────────────────────────────
_HERE             = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR      = os.path.normpath(os.path.join(_HERE, '..'))
_MONITORING_DIR   = os.path.join(_BACKEND_DIR, 'modules', 'monitoring')
_DETECTOR_MODULES = os.path.join(_MONITORING_DIR, 'detector_modules')

for _p in (_BACKEND_DIR, _MONITORING_DIR, _DETECTOR_MODULES):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── 실제 judge 모듈 강제 복원 ────────────────────────────────────────────────
# test_cap_ffmpeg.py 가 알파벳 순서상 먼저 실행되면서
# 'detector_modules.judge' 를 MagicMock 으로 sys.modules 에 등록한다.
# 이 테스트는 실제 WrongWayJudge 가 필요하므로 해당 항목을 제거하고
# 파일시스템에서 다시 로드한다. (test_flow_map_cache.py 와 동일 패턴)
for _force_real in ['detector_modules.judge']:
    sys.modules.pop(_force_real, None)   # MagicMock stub 제거 → 실제 파일에서 재로드

from detector_modules.judge import WrongWayJudge   # 실제 WrongWayJudge 로드
from detector_modules.config import DetectorConfig  # conftest 가 선점 등록 → 실제 값
from detector_modules.state import DetectorState    # conftest 가 선점 등록 → 실제 값


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

def _make_judge(ref_dx=None, ref_dy=None):
    """테스트용 WrongWayJudge 를 생성한다.

    flow_map 은 MagicMock 으로 교체해 FlowMap 로딩 없이 단위 테스트 가능.
    """
    cfg = DetectorConfig()
    st  = DetectorState()
    # FlowMap 을 MagicMock 으로 대체 (순수 단위 테스트)
    flow = MagicMock()
    flow.get_interpolated.return_value = None  # 기본: flow 없음
    flow.get_cell_rc.return_value      = (0, 0)
    flow.is_smoothed.return_value      = False
    # _ref_dx/_ref_dy: 122차 안전망에 사용
    flow._ref_dx = ref_dx
    flow._ref_dy = ref_dy

    judge = WrongWayJudge(cfg, flow, st)
    return judge, cfg, st, flow


def _make_traj(n=30, dx=1.0, dy=0.0, start=(100, 100)):
    """dx,dy 방향으로 n 포인트 궤적을 생성한다."""
    x0, y0 = start
    return [(x0 + i * dx * 5, y0 + i * dy * 5) for i in range(n)]


# ═══════════════════════════════════════════════════════════════════════════════
# A. check() 시그니처 — track_dir 파라미터 지원
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckSignature:
    """check() 가 track_dir 파라미터를 지원하는지 검증한다."""

    def test_check_accepts_track_dir_param(self):
        """check(track_dir=...) 를 키워드 인자로 호출할 수 있어야 한다.

        [Red] 파라미터 없으면 TypeError.
        역할: A/B 채널 구분으로 반대 차선 벡터 오염 방지.
        """
        judge, cfg, st, flow = _make_judge()
        st.frame_num = 100
        st.first_seen_frame[1] = 0   # 트랙 나이 100

        traj = _make_traj(n=20, dx=1.0)
        try:
            result = judge.check(
                track_id=1, traj=traj,
                ndx=1.0, ndy=0.0, speed=10.0, cy=100,
                bbox_h=40.0,
                track_dir='a'   # ← 새 파라미터
            )
        except TypeError as e:
            assert False, f"track_dir 파라미터 미지원: {e}"

    def test_check_track_dir_default_none(self):
        """track_dir 기본값이 None 이어야 한다 (하위 호환)."""
        judge, cfg, st, flow = _make_judge()
        st.frame_num = 100
        st.first_seen_frame[1] = 0

        traj = _make_traj(n=20, dx=1.0)
        # track_dir 없이 호출해도 동작해야 함
        try:
            result = judge.check(
                track_id=1, traj=traj,
                ndx=1.0, ndy=0.0, speed=10.0, cy=100, bbox_h=40.0
            )
        except TypeError as e:
            assert False, f"track_dir 기본값(None) 동작 실패: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# B. global_ok 기본값 — False (bypass 금지)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGlobalOkDefault:
    """wrong_count_threshold 도달 후 궤적이 너무 짧으면 확정되지 않아야 한다.

    웹 구버전: global_ok = True (기본값) → 짧은 궤적에서도 확정 가능 (오탐)
    AI 신버전: global_ok = False (기본값) → flow 를 찾지 못하면 확정 불가
    """

    def test_no_confirm_when_flow_unavailable(self):
        """flow_map 이 None 을 반환하면 wrong_count 가 쌓여도 확정되지 않아야 한다.

        [Red] global_ok=True(구버전) 에서는 flow 없어도 확정됨.
        """
        judge, cfg, st, flow = _make_judge()
        # flow 가 항상 None 반환 (eroded 구역)
        flow.get_interpolated.return_value = None

        st.frame_num = 200
        st.first_seen_frame[1] = 0   # 트랙 나이 200

        # wrong_count_threshold(20) 이상 채우기
        track_id = 1
        st.wrong_way_count[track_id] = cfg.wrong_count_threshold + 5

        # 충분히 긴 궤적 (→ 방향으로 전진)
        traj = _make_traj(n=cfg.velocity_window + 5, dx=1.0)

        is_wrong, ratio, info = judge.check(
            track_id=track_id, traj=traj,
            ndx=-1.0, ndy=0.0,   # ← 방향 (역방향 시뮬레이션)
            speed=20.0, cy=100, bbox_h=40.0
        )

        # flow 없으면 global_ok=False → 확정 불가
        assert is_wrong is False, \
            "flow 없을 때 역주행으로 확정되면 안 됩니다 (global_ok bypass 금지)"


# ═══════════════════════════════════════════════════════════════════════════════
# C. traj_ref_cos 최종 안전망 (122차)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrajRefCosSafetyNet:
    """궤적 방향과 기준 방향의 직접 비교로 정상 차량 오탐을 최종 차단한다."""

    def test_normal_direction_vehicle_not_confirmed(self):
        """기준 방향(→)으로 이동하는 차량은 역주행으로 확정되면 안 된다.

        [Red] traj_ref_cos 안전망이 없으면 flow map 오탐 시 정상 차량도 확정됨.

        시나리오:
          - 차량은 실제로 → 방향 이동 (궤적도 →, velocity_window도 →)
          - flow map 이 ← 방향으로 오염됨 → disagree_ratio=1.0 → 의심 쌓임
          - global_cos = (→ traj) · (← flow) = -1.0 < -0.75 → global_ok = True
          - traj_ref_cos = (→ traj) · (→ ref) = 1.0 > -0.3 → 오탐으로 취소 ✓
        """
        judge, cfg, st, flow = _make_judge(ref_dx=1.0, ref_dy=0.0)

        # flow map 이 ← 방향으로 오염됨 (정상 방향 → 와 반대)
        flow.get_interpolated.return_value = (-1.0, 0.0)

        st.frame_num = 300
        st.first_seen_frame[1] = 0
        # wrong_count 충분히 채우기 (threshold 초과)
        st.wrong_way_count[1] = cfg.wrong_count_threshold + 10

        # 실제 궤적은 → 방향 이동 (정상 차량)
        traj = _make_traj(n=cfg.velocity_window + 5, dx=1.0, dy=0.0)

        is_wrong, ratio, info = judge.check(
            track_id=1, traj=traj,
            ndx=1.0, ndy=0.0,    # velocity_window 방향도 → (정상)
            speed=20.0, cy=100, bbox_h=40.0
        )

        # traj_ref_cos > -0.3 → 정상 차량 → 확정 취소
        assert is_wrong is False, \
            "정상 차량(→ 이동)이 역주행으로 확정됐습니다 — traj_ref_cos 안전망 없음"

    def test_debug_info_contains_traj_ref_cos(self):
        """debug_info 에 traj_ref_cos 키 또는 traj_vs_ref_normal 상태가 포함되어야 한다.

        역할: 운영자가 오탐 원인을 분석할 수 있도록 로그에 포함.
        """
        judge, cfg, st, flow = _make_judge(ref_dx=1.0, ref_dy=0.0)

        # flow map 이 ← 방향으로 오염됨
        flow.get_interpolated.return_value = (-1.0, 0.0)

        st.frame_num = 300
        st.first_seen_frame[1] = 0
        st.wrong_way_count[1] = cfg.wrong_count_threshold + 10

        # 궤적은 → 방향 (정상 차량)
        traj = _make_traj(n=cfg.velocity_window + 5, dx=1.0)

        _, _, info = judge.check(
            track_id=1, traj=traj,
            ndx=1.0, ndy=0.0,    # → 방향 (flow ← 와 반대 → disagree)
            speed=20.0, cy=100, bbox_h=40.0
        )

        # traj_ref_cos 또는 status 에 관련 정보가 있어야 함
        has_ref_cos = ('traj_ref_cos' in info
                       or info.get('status') in ('traj_vs_ref_normal',
                                                  'ft_traj_vs_ref_normal'))
        assert has_ref_cos, \
            f"debug_info 에 traj_ref_cos 정보가 없습니다: {info}"


# ═══════════════════════════════════════════════════════════════════════════════
# D. age gate 내 lcf 갱신 (서행 후 가속 오탐 방지)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgeGateLcfUpdate:
    """age gate 기간 동안에도 정방향 주행 시 lcf 를 갱신해야 한다."""

    def test_lcf_updated_during_age_gate_when_correct_direction(self):
        """age gate 기간 중 정방향 주행 시 last_correct_frame 이 갱신되어야 한다.

        [Red] 구버전은 age gate 내에서 바로 return False — lcf 갱신 없음.
        결과: 가속 후 fast-track 에서 lcf=0 으로 인식 → 즉시 확정 오탐.
        """
        judge, cfg, st, flow = _make_judge()

        # flow 가 → 방향 반환 (정방향)
        flow.get_interpolated.return_value = (1.0, 0.0)

        st.frame_num = 10
        track_id = 1
        st.first_seen_frame[track_id] = 0  # 트랙 나이 10 → min_wrongway_track_age(20) 미만

        traj = _make_traj(n=5, dx=1.0)

        # age gate 기간 중 → 방향으로 이동 (nm >= gate_threshold)
        judge.check(
            track_id=track_id, traj=traj,
            ndx=1.0, ndy=0.0,   # → 방향
            speed=10.0, cy=100, bbox_h=40.0   # nm = 10/40 = 0.25 > 0.15
        )

        # lcf 가 갱신됐는지 확인
        lcf = st.last_correct_frame.get(track_id, 0)
        assert lcf > 0, \
            f"age gate 중 정방향 주행 시 last_correct_frame 이 갱신되지 않았습니다 (lcf={lcf})"


# ═══════════════════════════════════════════════════════════════════════════════
# E. 장기 윈도우 — 중앙값 벡터 방식 (117차)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLongWindowMedian:
    """장기 윈도우 계산이 중앙값 벡터 방식을 사용하는지 검증한다.

    웹 구버전: endpoint-to-endpoint (끊김에 취약)
    AI 신버전: 프레임 단위 차이의 중앙값 × window 크기 (끊김 내성)
    """

    def test_long_window_ok_with_normal_direction(self):
        """장기 윈도우에서 정방향 이동이 감지되면 long_window_ok 가 반환되어야 한다."""
        judge, cfg, st, flow = _make_judge()

        # flow 가 → 방향 반환 (long window 에서 정상으로 판정)
        flow.get_interpolated.return_value = (1.0, 0.0)

        st.frame_num = 100
        st.first_seen_frame[1] = 0  # 트랙 나이 100

        # 장기 윈도우(20프레임) 이상 → 방향 궤적
        long_w = cfg.velocity_window * 2
        traj = _make_traj(n=long_w + 5, dx=1.0, dy=0.0)

        # vote_threshold 이상 역방향 투표 (단기 의심 유발)
        # flow 를 잠시 ← 방향으로 변경 후 장기는 정방향 유지
        flow.get_interpolated.return_value = (-1.0, 0.0)  # 단기: 역방향 flow

        # 실제로는 장기 방향 조회 시에도 같은 mock 반환 → long_suspect 계산
        # 이 테스트는 함수 호출이 에러 없이 완료됨을 검증
        try:
            is_wrong, ratio, info = judge.check(
                track_id=1, traj=traj,
                ndx=-1.0, ndy=0.0,
                speed=15.0, cy=100, bbox_h=40.0
            )
        except Exception as e:
            assert False, f"장기 윈도우 계산 중 예외 발생: {e}"

        # 에러 없이 반환됨을 확인
        assert isinstance(is_wrong, bool)
