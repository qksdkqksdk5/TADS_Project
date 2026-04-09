import queue
import re
import os
import threading
from ultralytics import YOLO
from gevent.threadpool import ThreadPoolExecutor as GThreadPoolExecutor

ocr_input_queue = queue.Queue(maxsize=2)
ocr_result_queue = queue.Queue()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OCR_MODEL_PATH = os.path.join(BASE_DIR, 'ocr_openvino_model')

plate_pattern = re.compile(r'\d{2,3}[가-힣]\d{4}')

_shared_ocr_model = None
_ocr_model_lock = threading.Lock()

# lambda 대신 모듈 레벨 executor + 순수 함수 사용
_ocr_executor = GThreadPoolExecutor(max_workers=1)


def get_shared_ocr_model():
    global _shared_ocr_model
    if _shared_ocr_model is None:
        with _ocr_model_lock:
            if _shared_ocr_model is None:
                print(f"🔍 [System] YOLO-OCR 엔진 최초 1회 로드 중... ({OCR_MODEL_PATH})")
                _shared_ocr_model = YOLO(OCR_MODEL_PATH, task='detect')
    return _shared_ocr_model


def _ocr_predict(model, img):
    """
    gevent threadpool에서 실행되는 순수 함수.
    lambda 클로저를 쓰지 않아 Linux에서 _limbo KeyError가 발생하지 않음.
    """
    return model.predict(img, conf=0.25, device='cpu', verbose=False)


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

    detected_chars.sort(key=lambda c: (c[1] // 30, c[0]))
    return "".join(c[2] for c in detected_chars)


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

            ocr_model = get_shared_ocr_model()
            track_id, plate_img = item

            # lambda 없이 순수 함수 직접 전달
            future = _ocr_executor.submit(_ocr_predict, ocr_model, plate_img)
            results = future.result()

            detected_text = _parse_ocr_result(results, ocr_model.names)

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
    model = ocr_instance or get_shared_ocr_model()

    results = model.predict(img, conf=0.25, device='cpu', verbose=False)
    text = _parse_ocr_result(results, model.names)

    match = plate_pattern.search(text)
    return match.group() if match else (text if text else "인식 실패")