# backend_flask/modules/plate/ocr_engine.py

import queue
import re
from paddleocr import PaddleOCR

ocr_input_queue = queue.Queue(maxsize=2)  # ✅ 레퍼런스와 동일: 2
ocr_result_queue = queue.Queue()


def _init_ocr():
    return PaddleOCR(use_angle_cls=True, lang='korean',
                     show_log=False, ocr_version='PP-OCRv4')  # ✅ 레퍼런스와 동일


def ocr_worker():
    ocr_reader = None
    print("🔍 OCR 스레드 준비")

    while True:
        try:
            item = ocr_input_queue.get(timeout=1)
            if item is None:
                print("🔍 OCR 스레드 종료")
                break

            if ocr_reader is None:
                print("🔍 OCR 엔진 초기화 중...")
                ocr_reader = _init_ocr()
                print("🔍 OCR 엔진 초기화 완료")

            track_id, plate_img = item
            result = ocr_reader.ocr(plate_img, cls=True)  # ✅ 레퍼런스: cls=True

            detected_text = ""
            if result and result[0]:
                for line in result[0]:
                    detected_text += line[1][0]

            # ✅ 레퍼런스와 동일: 숫자/한글만 남김
            clean_text = re.sub(r'[^0-9가-힣]', '', detected_text)

            ocr_result_queue.put((track_id, plate_img, clean_text))
            ocr_input_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            print(f"❌ OCR 오류: {e}")
            continue


def run_ocr_once(img, ocr_instance=None):
    plate_pattern = re.compile(r'\d{2,3}[가-힣]\d{4}')
    reader = ocr_instance or _init_ocr()
    result = reader.ocr(img, cls=True)
    if result and result[0]:
        text = "".join(line[1][0] for line in result[0])
        clean_text = re.sub(r'[^0-9가-힣]', '', text)
        match = plate_pattern.search(clean_text)
        return match.group() if match else clean_text
    return "인식 실패"