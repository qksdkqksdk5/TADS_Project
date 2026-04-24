import pytest
import numpy as np
import cv2
from modules.plate.yolo_ocr_engine import detect_plate_color, RE_YELLOW_STRICT, RE_WHITE_NORMAL

# ① 색상 검출 테스트 (Mock 이미지 생성)
def test_detect_plate_color():
    # 가짜 흰색 이미지 (전부 하얀색)
    white_img = np.full((100, 300, 3), 255, dtype=np.uint8)
    assert detect_plate_color(white_img) == "white"
    
    # 가짜 노란색 이미지 (HSV에서 노란색 영역에 해당하는 값으로 채움)
    yellow_img = np.full((100, 300, 3), (30, 150, 200), dtype=np.uint8) 
    assert detect_plate_color(yellow_img) == "yellow"

# ② 정규식 복합 테스트
@pytest.mark.parametrize("text, color, expected", [
    ("서울12가3456", "yellow", "서울12가3456"), # 영업용 정상
    ("12가3456", "white", "12가3456"),       # 일반용 정상
    ("가나다12345", "white", None),           # 패턴 불일치
    ("경기77바9999", "yellow", "경기77바9999"), # 영업용 지역명 포함
])
def test_regex_filtering(text, color, expected):
    if color == "yellow":
        match = RE_YELLOW_STRICT.search(text)
    else:
        match = RE_WHITE_NORMAL.search(text)
    
    result = match.group(0) if match else None
    assert result == expected