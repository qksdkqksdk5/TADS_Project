# tests/conftest.py
# pytest 공통 세션 설정
#
# 목적:
#   test_cap_ffmpeg.py 는 모듈 레벨에서 'detector_modules.config' 등을 MagicMock 으로
#   sys.modules 에 setdefault 등록한다. conftest.py 는 테스트 파일 수집 전에 로드되므로,
#   여기서 순수 Python 모듈들을 먼저 sys.modules 에 올려두면 setdefault 가 덮지 않는다.
#
#   ※ 중요 제약: numpy / cv2 등 C 확장에 의존하는 패키지(judge, flow_map 등)는
#     여기서 import 하지 않는다.
#     이유: conftest 에서 numpy 를 load 하면 test_flow_map_cache.py 가
#           sys.modules.pop('numpy') 로 재로드할 때 구(舊) 객체 참조가 남아
#           numpy.linalg lazy-loading 에서 무한 재귀가 발생하기 때문이다.
#     judge 등 numpy 의존 모듈은 각 테스트 파일에서 직접 pop+reimport 패턴으로 처리한다.

import os    # 경로 계산
import sys   # sys.modules 접근

# ── detector_modules 경로 계산 ────────────────────────────────────────────────
_TESTS_DIR      = os.path.dirname(os.path.abspath(__file__))      # tests/ 절대 경로
_BACKEND_DIR    = os.path.normpath(os.path.join(_TESTS_DIR, '..'))  # backend_flask/
_MONITORING_DIR = os.path.join(_BACKEND_DIR, 'modules', 'monitoring')  # monitoring/
_DETECTOR_DIR   = os.path.join(_MONITORING_DIR, 'detector_modules')    # detector_modules/

# sys.path 에 없으면 앞에 삽입 (최우선 탐색 경로로 등록)
for _p in (_BACKEND_DIR, _MONITORING_DIR, _DETECTOR_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── 순수 Python 모듈만 sys.modules 에 선점 등록 ──────────────────────────────
# config.py 와 state.py 는 dataclass / collections 만 사용하는 순수 Python.
# 이 두 모듈을 먼저 등록해 두면 test_cap_ffmpeg.py 의 setdefault stub 이 무효화된다.
try:
    import detector_modules.config   # DetectorConfig: dataclass 전용, 외부 의존성 없음
    import detector_modules.state    # DetectorState: collections 전용, 외부 의존성 없음
except Exception:
    # 예외가 발생해도 다른 테스트에 영향을 주지 않도록 무시
    pass
