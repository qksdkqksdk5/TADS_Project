import pytest
from unittest.mock import patch, MagicMock
from modules.plate.state import state, state_lock

# 1. /verify API 테스트 (정답 입력 로직)
def test_verify_endpoint(client):
    # 가짜 데이터 먼저 주입
    with state_lock:
        state['all_results'] = [{
            'id': 'track_01',
            'text': '12가3456',
            'video': 'sample.mp4',
            'img_url': '/api/plate/image/sample/12가3456.jpg'
        }]

    # db_manager.update_result 함수가 호출되는지 확인하기 위해 mock 사용
    with patch('modules.plate.plate.update_result') as mock_update:
        payload = {
            "id": "track_01",
            "ground_truth": "12가3456"
        }
        response = client.post('/api/plate/verify', json=payload)
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['is_correct'] is True
        assert data['recognized'] == "12가3456"
        # DB 업데이트 함수가 한 번 호출되었는지 확인
        mock_update.assert_called_once()

# 2. /reprocess API 테스트 (전처리 후 재인식)
@patch('modules.plate.plate.run_ocr_once')
@patch('modules.plate.plate.preprocess_apply')
@patch('cv2.imread')
@patch('cv2.imwrite')
@patch('modules.plate.plate.add_preprocess_result')
def test_reprocess_endpoint(mock_add_db, mock_imwrite, mock_imread, mock_preprocess, mock_ocr, client):
    # 가짜 이미지 데이터와 OCR 결과 설정
    mock_imread.return_value = MagicMock()
    mock_preprocess.return_value = MagicMock()
    mock_ocr.return_value = "88나8888"
    
    with state_lock:
        state['all_results'] = [{
            'id': 'track_02',
            'text': '12가3456',
            'img_filename': 'sample.jpg',
            'video': 'test.mp4'
        }]

    # os.path.exists가 항상 True를 반환하도록 Mock (이미지가 있다고 가정)
    with patch('os.path.exists', return_value=True):
        payload = {"id": "track_02", "preprocess": "clahe"}
        response = client.post('/api/plate/reprocess', json=payload)
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['retried_text'] == "88나8888"
        assert 'clahe' in data['preprocess_results']