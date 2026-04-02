# backend_flask/modules/plate/preprocessor.py
# 번호판 이미지 전처리 함수 모음
# 각 방법은 독립적으로 동작하며 BGR 이미지를 입력받아 BGR 이미지를 반환

import cv2
import numpy as np

# 지원하는 전처리 방법 목록 (프론트에 그대로 전달)
PREPROCESS_METHODS = [
    {'key': 'clahe',   'label': 'CLAHE',     'desc': '조명 불균일 보정 (야간/역광)'},
    {'key': 'sharpen', 'label': '샤프닝',     'desc': '흐릿한 번호판 윤곽 강화'},
    {'key': 'denoise', 'label': '노이즈 제거', 'desc': '저해상도 영상 노이즈 제거'},
    {'key': 'morph',   'label': '모폴로지',   'desc': '끊어진 글자 획 연결'},
]


def apply(img: np.ndarray, method: str) -> np.ndarray:
    """
    전처리 방법 적용
    :param img: BGR 입력 이미지
    :param method: 전처리 키 (clahe / sharpen / denoise / morph)
    :return: 전처리된 BGR 이미지
    """
    handlers = {
        'clahe':   _clahe,
        'sharpen': _sharpen,
        'denoise': _denoise,
        'morph':   _morph,
    }
    fn = handlers.get(method)
    if fn is None:
        print(f"⚠️ 알 수 없는 전처리 방법: {method}, 원본 반환")
        return img
    return fn(img)


def _clahe(img: np.ndarray) -> np.ndarray:
    """
    CLAHE (Contrast Limited Adaptive Histogram Equalization)
    - 조명 불균일, 야간, 역광 번호판에 효과적
    - 전체 히스토그램 평활화와 달리 국소 영역별로 대비를 조정
    - LAB 색공간의 L 채널에만 적용해 색상 왜곡 방지
    """
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    lab = cv2.merge([l, a, b])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _sharpen(img: np.ndarray) -> np.ndarray:
    """
    언샤프 마스킹 샤프닝
    - 흐릿하거나 모션 블러가 있는 번호판 글자 윤곽 강화
    - 단순 커널 샤프닝보다 자연스러운 결과
    - 원본과 블러의 차이를 이용해 엣지 강조
    """
    blurred = cv2.GaussianBlur(img, (0, 0), 3)
    return cv2.addWeighted(img, 1.5, blurred, -0.5, 0)


def _denoise(img: np.ndarray) -> np.ndarray:
    """
    Non-Local Means 노이즈 제거
    - 저해상도 CCTV 영상의 그레인 노이즈 제거
    - 엣지는 보존하면서 평탄한 영역의 노이즈만 제거
    - 처리 시간이 다소 걸림 (가장 무거운 전처리)
    """
    return cv2.fastNlMeansDenoisingColored(
        img, None,
        h=10, hColor=10,
        templateWindowSize=7,
        searchWindowSize=21
    )


def _morph(img: np.ndarray) -> np.ndarray:
    """
    모폴로지 클로징 (팽창 → 침식)
    - 끊어지거나 번진 글자 획을 연결
    - 빗물, 오염 등으로 인한 번호판 글자 손상에 효과적
    - 그레이스케일 변환 후 처리 → BGR로 복원
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    closed = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    return cv2.cvtColor(closed, cv2.COLOR_GRAY2BGR)