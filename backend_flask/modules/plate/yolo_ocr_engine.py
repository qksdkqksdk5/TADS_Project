# backend_flask/modules/plate/ocr_engine.py
# YOLO 커스텀 모델 기반 문자 인식 전담 스레드

import queue
import re
import os
from ultralytics import YOLO

# --- [스레드 간 통신 큐] --- (detector.py와 인터페이스 동일 유지)
ocr_input_queue = queue.Queue(maxsize=2)   # 레퍼런스: OCR_QUEUE_SIZE = 2
ocr_result_queue = queue.Queue()           # OCR → 메인: (track_id, plate_img, text)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OCR_MODEL_PATH = os.path.join(BASE_DIR, 'yolo_ocr_best04.pt')

plate_pattern = re.compile(r'\d{2,3}[가-힣]\d{4}')


def _parse_ocr_result(results, model_names: dict) -> str:
    """
    YOLO 탐지 결과 → 번호판 문자열 변환
    - 'license_plate', 'plate' 클래스는 제외
    - Y좌표 30px 단위 묶음 후 X좌표 정렬 (2줄 번호판 대응)
    """
    detected_chars = []

    if results and len(results[0].boxes) > 0:
        for box in results[0].boxes:
            cls_id = int(box.cls[0].item())
            label = model_names[cls_id]
            if label in ('license_plate', 'plate'):
                continue
            x = box.xyxy[0][0].item()
            y = box.xyxy[0][1].item()
            detected_chars.append((x, y, label))

    if not detected_chars:
        return ""

    # Y 30px 묶음 → X 정렬 (레퍼런스 코드와 동일 로직)
    detected_chars.sort(key=lambda c: (c[1] // 30, c[0]))
    return "".join(c[2] for c in detected_chars)


def _init_ocr() -> YOLO:
    return YOLO(OCR_MODEL_PATH)


def ocr_worker():
    """
    백그라운드 OCR 전담 스레드
    - 첫 이미지 수신 시 지연 초기화 (서버 시작 블로킹 방지)
    - None 수신 시 종료
    """
    ocr_model = None
    print("🔍 YOLO-OCR 스레드 준비")

    while True:
        try:
            item = ocr_input_queue.get(timeout=1)
            if item is None:
                print("🔍 YOLO-OCR 스레드 종료")
                break

            # 첫 이미지 들어올 때 초기화
            if ocr_model is None:
                print("🔍 YOLO-OCR 엔진 초기화 중...")
                ocr_model = _init_ocr()
                print("🔍 YOLO-OCR 엔진 초기화 완료")

            track_id, plate_img = item

            results = ocr_model.predict(
                plate_img,
                conf=0.25,
                device='cpu',   # GPU 있으면 'cuda:0'으로 변경
                verbose=False,
            )

            detected_text = _parse_ocr_result(results, ocr_model.names)

            # 4글자 미만은 노이즈로 간주 (레퍼런스 코드 기준 유지)
            if len(detected_text) < 7:
                detected_text = "인식 중..."

            ocr_result_queue.put((track_id, plate_img, detected_text))
            ocr_input_queue.task_done()

        except Exception as e:
            import queue as q
            if isinstance(e, q.Empty):
                continue
            print(f"❌ YOLO-OCR 오류: {e}")
            continue


def run_ocr_once(img, ocr_instance=None) -> str:
    """
    reprocess 엔드포인트용 단발성 OCR
    plate.py의 /reprocess 라우트에서 호출
    """
    model = ocr_instance or _init_ocr()
    results = model.predict(img, conf=0.25, device='cpu', verbose=False)
    text = _parse_ocr_result(results, model.names)

    match = plate_pattern.search(text)
    return match.group() if match else (text if text else "인식 실패")