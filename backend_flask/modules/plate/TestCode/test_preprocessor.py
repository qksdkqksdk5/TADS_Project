import pytest
import numpy as np
from modules.plate.preprocessor import apply, PREPROCESS_METHODS

# 가상의 BGR 이미지 생성 (100x200 크기, 3채널)
@pytest.fixture
def dummy_image():
    return np.random.randint(0, 256, (100, 200, 3), dtype=np.uint8)

# ① 지원하는 모든 전처리 기법이 정상 작동하는지 테스트
@pytest.mark.parametrize("method_dict", PREPROCESS_METHODS)
def test_apply_valid_methods(dummy_image, method_dict):
    method = method_dict['key']
    result = apply(dummy_image, method)
    
    # 결과가 None이 아니어야 함
    assert result is not None
    # 원본과 shape(높이, 너비, 채널)가 동일해야 함
    assert result.shape == dummy_image.shape
    # 결과가 numpy 배열이어야 함
    assert isinstance(result, np.ndarray)

# ② 존재하지 않는 전처리 키를 넣었을 때 방어 로직 테스트
def test_apply_invalid_method(dummy_image):
    result = apply(dummy_image, "unknown_magic")
    
    # 원본 이미지가 그대로 반환되어야 함
    np.testing.assert_array_equal(result, dummy_image)