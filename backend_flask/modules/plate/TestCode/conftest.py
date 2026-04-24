import pytest
import os
import sys

root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.append(root_path)

try:
    from app import app as flask_app 
except ImportError as e:
    print(f"❌ 임포트 실패: {e}")
    raise
from modules.plate.state import state, state_lock

@pytest.fixture
def app():
    # 애플리케이션 팩토리가 없다면 가져온 app 객체를 그대로 사용합니다.
    flask_app.config.update({"TESTING": True})
    yield flask_app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture(autouse=True)
def clean_state():
    """테스트마다 독립적인 환경을 위해 state 초기화"""
    with state_lock:
        state['all_results'] = []
        state['plates'] = []
        state['stop_thread'] = False
        # 필요한 다른 초기값들도 여기에 추가
    yield