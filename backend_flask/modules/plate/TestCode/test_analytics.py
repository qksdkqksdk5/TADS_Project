import pytest
from modules.plate.analytics import get_analytics

# 테스트용 Mock 데이터 (db_manager.get_all_results 반환값 흉내)
@pytest.fixture
def mock_rows():
    return [
        # 원본 결과 1 (정답)
        {'인식번호판': '12가3456', '정답번호판': '12가3456', '정오여부': '정답', '영상파일': 'v1.mp4', '전처리방법': ''},
        # 원본 결과 2 (오답)
        {'인식번호판': '99나9999', '정답번호판': '88나8888', '정오여부': '오답', '영상파일': 'v1.mp4', '전처리방법': ''},
        # 전처리 결과 (성공)
        {'인식번호판': '12가3456', '보정후번호판': '12가3456', '정답번호판': '12가3456', '영상파일': 'v1.mp4', '전처리방법': 'clahe'},
        # 전처리 결과 (실패)
        {'인식번호판': '99나9999', '보정후번호판': '인식 실패', '정답번호판': '88나8888', '영상파일': 'v1.mp4', '전처리방법': 'clahe'}
    ]

def test_get_analytics_summary(mocker, mock_rows):
    # db_manager의 함수를 가짜로 대체
    mocker.patch('modules.plate.analytics.get_all_results', return_value=mock_rows)
    
    result = get_analytics()
    
    # 1. 요약 통계 검증
    assert result['total'] == 2
    assert result['answered'] == 2
    assert result['accuracy'] == 50.0  # 2개 중 1개 정답
    
    # 2. 전처리 통계 검증
    assert 'clahe' in result['preprocess_stats']
    assert result['preprocess_stats']['clahe']['success'] == 1
    assert result['preprocess_stats']['clahe']['fail'] == 1