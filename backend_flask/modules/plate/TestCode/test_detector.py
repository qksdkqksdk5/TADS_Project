import pytest
from unittest.mock import MagicMock, patch
from modules.plate.detector import plate_pattern, _save_and_sync_ui
from modules.plate.state import state, state_lock

# ① 번호판 정규식 테스트
@pytest.mark.parametrize("plate_text, expected", [
    ("12가3456", True),
    ("123가3456", True),
    ("서울12가3456", True),
    ("12가345", False),  # 숫자 부족
    ("ABC1234", False),  # 한글 없음
])
def test_plate_pattern(plate_text, expected):
    assert bool(plate_pattern.match(plate_text)) == expected

# ② UI 동기화 및 상태 업데이트 로직 테스트
def test_save_and_sync_ui_logic(client):
    with state_lock:
        state['all_results'] = []
    
    # 가짜 파라미터 설정
    track_id = 99
    plate_img = MagicMock() # 실제 이미지 대신 Mock 사용
    clean_text = "55무5555"
    
    with patch('modules.plate.detector.io_queue.put') as mock_io_put:
        # 함수 실행
        url = _save_and_sync_ui(
            track_id=track_id,
            plate_img=plate_img,
            clean_text=clean_text,
            is_fixed=True,
            video_filename="test_vid.mp4",
            video_save_dir="SAVE_DIR/test_vid",
            saved_first=set(),
            saved_fixed=set(),
            conf=0.9,
            vote_count=5,
            elapsed=100,
            token="test_token"
        )
        
        # 검증 1: 결과 리스트에 추가되었는지
        assert len(state['all_results']) == 1
        assert state['all_results'][0]['text'] == "55무5555"
        assert state['all_results'][0]['is_fixed'] is True
        
        # 검증 2: IO 워커 큐에 작업이 들어갔는지
        assert mock_io_put.called
        # 첫 번째 인자(img_path)가 올바른지 확인
        args, _ = mock_io_put.call_args
        # args는 (img_path, data_dict, token) 형태의 튜플임
        actual_path = str(args[0]) # 명시적으로 첫 번째 인자를 꺼내 문자열 변환
        
        assert "id_99_fixed.jpg" in actual_path.replace("\\", "/")