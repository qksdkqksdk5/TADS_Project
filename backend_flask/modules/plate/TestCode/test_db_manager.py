import pytest
from datetime import datetime
from app import app as flask_app # app.py의 팩토리 함수
from models import db, PlateResult
from modules.plate import db_manager

@pytest.fixture
def app_and_db():
    app = flask_app
    # Flask-SQLAlchemy의 기존 연결을 끊고 메모리 DB로 강제 교체
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False
    })
    
    with app.app_context():
        db.create_all()  # 메모리에 새 테이블 생성
        db_manager.init_app(app)
        yield app, db
        db.session.remove()
        db.drop_all()    # 테스트 종료 후 메모리 DB 파괴

# ① 신규 저장 및 중복 방지(Update) 테스트
def test_save_result_new_and_update(app_and_db):
    app, _db = app_and_db
    
    # 1. 최초 저장
    db_manager.save_result(
        plate_number="12가3456",
        img_path="/save/id_1_first.jpg",
        track_id=1,
        conf=0.85,
        video_filename="test.mp4"
    )
    
    with app.app_context():
        results = PlateResult.query.all()
        assert len(results) == 1
        assert results[0].plate_number == "12가3456"
        assert results[0].confidence == 0.85

    # 2. 동일한 track_id로 더 나은 결과(is_fixed=True)가 들어왔을 때 -> 업데이트 되어야 함 (행 개수 유지)
    db_manager.save_result(
        plate_number="12가3456",
        img_path="/save/id_1_fixed.jpg",
        track_id=1,
        conf=0.99,
        is_fixed=True,
        video_filename="test.mp4"
    )
    
    with app.app_context():
        results = PlateResult.query.all()
        assert len(results) == 1  # 2개가 되면 안 됨!
        assert results[0].is_fixed is True
        assert results[0].confidence == 0.99