# tests/test_emit_direction_label.py
# 교통 모니터링 팀 — _emit_traffic_update jam_up/jam_down 방향 매핑 검증
#
# 버그: _dir_label_a 가 "DOWN" 이어도 jam_up = jam_a 로 고정됨
#       → 상행/하행 정체 점수가 뒤바뀌어 표시됨
#
# 실행: backend_flask/ 에서
#     pytest tests/test_emit_direction_label.py -v

import os
import sys
from unittest.mock import MagicMock, call

# ── sys.path 설정 ────────────────────────────────────────────────────────────
_HERE        = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.normpath(os.path.join(_HERE, '..'))
_MONITORING_DIR = os.path.join(_BACKEND_DIR, 'modules', 'monitoring')
_DETECTOR_MODULES = os.path.join(_MONITORING_DIR, 'detector_modules')

for _p in (_BACKEND_DIR, _MONITORING_DIR, _DETECTOR_MODULES):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

def _make_traffic_analyzer_mock(jam_score: float, level: str = "SMOOTH"):
    """지정된 jam_score / level 을 반환하는 TrafficAnalyzer mock 을 만든다."""
    ta = MagicMock()                            # TrafficAnalyzer 전체 mock
    ta.get_jam_score.return_value     = jam_score      # jam_score 고정
    ta.get_congestion_level.return_value = level        # 레벨 고정
    ta._vehicle_count                 = 0              # 차량 수 0
    ta.get_affected_vehicles.return_value = 0          # 영향 차량 0
    ta.get_occupancy.return_value     = 0.0            # 점유율 0
    ta.get_avg_speed.return_value     = 50.0           # 속도 고정
    ta.get_duration_sec.return_value  = 0.0            # 지속 시간 0
    return ta


def _make_minimal_detector(dir_label_a: str, jam_a: float, jam_b: float):
    """
    _emit_traffic_update() 호출에 필요한 최소 속성을 가진
    MonitoringDetector 인스턴스처럼 동작하는 mock 객체를 생성한다.

    dir_label_a: "UP" 또는 "DOWN" — _compute_ref_direction() 이 설정하는 값
    jam_a      : traffic_analyzer_a 의 jam_score (방향 'a' 정체지수)
    jam_b      : traffic_analyzer_b 의 jam_score (방향 'b' 정체지수)
    """
    from detector_modules.config import DetectorConfig   # 실제 설정 객체
    from detector_modules.state  import DetectorState    # 실제 상태 객체

    det = MagicMock()                                    # MonitoringDetector 전체 mock

    # ── _emit_traffic_update() 에서 참조하는 속성 설정 ──
    det.socketio      = MagicMock()                      # emit 호출 캡처용
    det.cfg           = DetectorConfig()                 # 실제 설정값 사용
    det.state         = DetectorState()                  # 실제 상태 (학습 완료)
    det.state.is_learning  = False                       # 학습 완료 상태
    det.state.relearning   = False                       # 재보정 없음
    det.state.waiting_stable = False                     # 안정 대기 없음
    det.state.frame_num    = 1000                        # 충분히 학습된 상태

    det.camera_id     = "test_cam"                       # 테스트 카메라 ID
    det.lat           = 37.5                             # 위도
    det.lng           = 127.0                            # 경도
    det.location      = "테스트 위치"                    # 위치 설명

    det.traffic_analyzer_a = _make_traffic_analyzer_mock(jam_a)  # 방향 a 분석기
    det.traffic_analyzer_b = _make_traffic_analyzer_mock(jam_b)  # 방향 b 분석기

    # ── 방향 레이블 — _compute_ref_direction() 이 설정하는 값 ──
    det._dir_label_a  = dir_label_a                      # "UP" 또는 "DOWN"
    det._dir_label_b  = "DOWN" if dir_label_a == "UP" else "UP"

    det._prev_level   = "SMOOTH"                         # 이전 레벨 (전환 감지용)
    det.flow          = MagicMock()                      # flow_map mock
    det.flow.count    = MagicMock()                      # count 배열 mock

    return det


# ─────────────────────────────────────────────────────────────────────────────
# 실제 _emit_traffic_update() 메서드를 MonitoringDetector 클래스에서 비바인딩으로 호출
# ─────────────────────────────────────────────────────────────────────────────

def _call_emit(det):
    """MonitoringDetector._emit_traffic_update(det) 를 비바인딩으로 호출한다."""
    # monitoring_detector 모듈을 직접 로드해 메서드만 추출한다.
    # MonitoringDetector 의 __init__ 은 YOLO/cv2 를 로드하므로 클래스 인스턴스화 없이
    # 메서드만 언바운드 방식으로 실행한다.
    import importlib
    import importlib.util
    import numpy as np

    # monitoring_detector.py 를 spec-only 로 로드 → 클래스 객체 획득
    _md_path = os.path.join(_MONITORING_DIR, 'monitoring_detector.py')

    # 이미 sys.modules 에 있으면 재사용, 없으면 파일에서 직접 로드
    mod_name = 'monitoring_detector_test_only'
    if mod_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(mod_name, _md_path)
        mod  = importlib.util.module_from_spec(spec)
        # monitoring_detector 의 import 의존성(cv2, gevent 등) 을 mock 으로 채운다
        sys.modules.setdefault('cv2',     MagicMock())
        sys.modules.setdefault('gevent',  MagicMock())
        sys.modules.setdefault('gevent.threadpool', MagicMock())
        sys.modules.setdefault('flow_map_matcher',  MagicMock())
        sys.modules.setdefault('modules.traffic.detectors.base_detector',
                               type(sys)('base_detector'))
        # BaseDetector stub
        import types
        _base_mod = types.ModuleType('modules.traffic.detectors.base_detector')
        _base_mod.BaseDetector = object     # 최소 부모 클래스 — object 로 대체
        sys.modules['modules.traffic.detectors.base_detector'] = _base_mod

        try:
            spec.loader.exec_module(mod)
            sys.modules[mod_name] = mod
        except Exception as e:
            # import 실패 시 메서드를 직접 소스에서 추출할 수 없음 — skip
            import pytest
            pytest.skip(f"monitoring_detector 로드 실패 (환경 의존성 부족): {e}")

    mod = sys.modules[mod_name]
    # MonitoringDetector 클래스의 _emit_traffic_update 메서드를 추출해
    # det 객체에 바인딩하지 않고 첫 번째 인자로 전달한다 (언바운드 호출)
    fn = mod.MonitoringDetector._emit_traffic_update
    fn(det)


# ═══════════════════════════════════════════════════════════════════════════════
# A. _dir_label_a = "UP" 이면 jam_up = jam_a, jam_down = jam_b
# ═══════════════════════════════════════════════════════════════════════════════

class TestJamDirectionLabelUp:
    """_dir_label_a == "UP" 일 때 jam_up 은 jam_a 여야 한다."""

    def test_jam_up_equals_jam_a_when_label_a_is_up(self):
        """
        [Green] _dir_label_a="UP" → jam_up = jam_a (현재도 올바름).
        이 테스트는 수정 후에도 기존 동작이 유지되는지 회귀 검증용.
        """
        det = _make_minimal_detector(dir_label_a="UP", jam_a=0.80, jam_b=0.10)
        _call_emit(det)

        # socketio.emit('traffic_update', payload) 의 payload 캡처
        emit_calls = det.socketio.emit.call_args_list
        # 'traffic_update' 이벤트 호출 찾기
        tu_call = next((c for c in emit_calls if c.args[0] == 'traffic_update'), None)
        assert tu_call is not None, "traffic_update 이벤트가 emit 되지 않았습니다"

        payload = tu_call.args[1]

        # _dir_label_a="UP" → 방향 a 가 상행 → jam_up = jam_a
        assert payload['jam_up']   == round(0.80, 3), \
            f"jam_up={payload['jam_up']} 는 0.80 이어야 합니다 (dir_label_a=UP)"
        assert payload['jam_down'] == round(0.10, 3), \
            f"jam_down={payload['jam_down']} 는 0.10 이어야 합니다 (dir_label_a=UP)"


# ═══════════════════════════════════════════════════════════════════════════════
# B. _dir_label_a = "DOWN" 이면 jam_up = jam_b, jam_down = jam_a
# ═══════════════════════════════════════════════════════════════════════════════

class TestJamDirectionLabelDown:
    """_dir_label_a == "DOWN" 일 때 jam_up 과 jam_down 이 교환되어야 한다.

    [Red] 현재 구현은 항상 jam_up=jam_a, jam_down=jam_b 로 고정됨.
          _dir_label_a="DOWN" 인 경우에도 교환하지 않아 상행/하행 역전 버그 발생.
    """

    def test_jam_up_equals_jam_b_when_label_a_is_down(self):
        """
        [Red] _dir_label_a="DOWN" → 방향 a 가 실제로 하행
             → jam_up = jam_b (방향 b = 상행), jam_down = jam_a (방향 a = 하행)
        """
        # 상행(방향b)이 정체(0.85), 하행(방향a)이 원활(0.05)인 시나리오
        det = _make_minimal_detector(dir_label_a="DOWN", jam_a=0.05, jam_b=0.85)
        _call_emit(det)

        emit_calls = det.socketio.emit.call_args_list
        tu_call    = next((c for c in emit_calls if c.args[0] == 'traffic_update'), None)
        assert tu_call is not None, "traffic_update 이벤트가 emit 되지 않았습니다"

        payload = tu_call.args[1]

        # _dir_label_a="DOWN" → jam_up 은 방향b(상행)의 점수여야 한다
        assert payload['jam_up'] == round(0.85, 3), (
            f"[Red] _dir_label_a=DOWN 인데 jam_up={payload['jam_up']} 가 "
            f"0.85(방향b=상행)가 아닙니다 — 방향 레이블 매핑 누락"
        )
        assert payload['jam_down'] == round(0.05, 3), (
            f"[Red] _dir_label_a=DOWN 인데 jam_down={payload['jam_down']} 가 "
            f"0.05(방향a=하행)가 아닙니다 — 방향 레이블 매핑 누락"
        )

    def test_jam_down_equals_jam_a_when_label_a_is_down(self):
        """
        [Red] 하행(방향a)이 정체인 경우 jam_down 에 정확히 반영되어야 한다.
        """
        # 하행(방향a) 정체(0.90), 상행(방향b) 원활(0.05)
        det = _make_minimal_detector(dir_label_a="DOWN", jam_a=0.90, jam_b=0.05)
        _call_emit(det)

        emit_calls = det.socketio.emit.call_args_list
        tu_call    = next((c for c in emit_calls if c.args[0] == 'traffic_update'), None)
        assert tu_call is not None

        payload = tu_call.args[1]

        # _dir_label_a="DOWN" → jam_down 은 방향a(하행) 점수여야 함
        assert payload['jam_down'] == round(0.90, 3), (
            f"[Red] jam_down={payload['jam_down']} 가 0.90(방향a=하행) 이어야 합니다"
        )
        assert payload['jam_up'] == round(0.05, 3), (
            f"[Red] jam_up={payload['jam_up']} 가 0.05(방향b=상행) 이어야 합니다"
        )
