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

# ── 번호판 패턴 ────────────────────────────────────────────────────────────────
# 1. 지역명 포함: 한글1~2자 + 숫자2~3 + 한글1 + 숫자4  (예: 경기92바8588)
plate_pattern_region  = re.compile(r'^[가-힣]{1,2}\d{2,3}[가-힣]\d{4}$')
# 2. 숫자 시작 일반: 숫자2~3 + 한글1 + 숫자4           (예: 92바8588)
plate_pattern_numeric = re.compile(r'^\d{2,3}[가-힣]\d{4}$')
# 3. 노이즈 섞인 결과에서 숫자 시작 유효 부분 추출용
plate_pattern_extract = re.compile(r'\d{2,3}[가-힣]\d{4}')

_shared_ocr_model = None
_ocr_model_lock = threading.Lock()

# gevent 환경용 스레드풀
_ocr_executor = GThreadPoolExecutor(max_workers=1)

# ── 지역명 확인 누적 저장소 ────────────────────────────────────────────────────
# track_id → 지역명 문자열 (한 번이라도 명확히 지역명 포함 패턴이 나오면 기록)
_region_seen: dict[int, str] = {}
_region_lock = threading.Lock()


def get_shared_ocr_model():
    global _shared_ocr_model
    if _shared_ocr_model is None:
        with _ocr_model_lock:
            if _shared_ocr_model is None:
                print(f"🔍 [System] YOLO-OCR 엔진 최초 1회 로드 중... ({OCR_MODEL_PATH})")
                _shared_ocr_model = YOLO(OCR_MODEL_PATH, task='detect')
    return _shared_ocr_model


def _ocr_predict(model, img):
    return model.predict(img, conf=0.25, device='cpu', verbose=False)


def _parse_ocr_result(results, model_names: dict) -> str:
    """
    YOLO 탐지 결과 → 번호판 문자열 변환 (스마트 정렬)
    - 중심점(cx, cy)과 글자 높이(h)를 이용해 줄을 나눈 뒤 좌우 정렬
    """
    chars_data = []

    if results and len(results[0].boxes) > 0:
        for box in results[0].boxes:
            cls_id = int(box.cls[0].item())
            label = model_names[cls_id]
            if label in ('license_plate', 'plate'):
                continue

            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            h = y2 - y1
            chars_data.append({'label': label, 'cx': cx, 'cy': cy, 'h': h})

    if not chars_data:
        return ""

    # 스마트 정렬 로직
    chars_data.sort(key=lambda c: c['cy'])

    avg_h = sum(c['h'] for c in chars_data) / len(chars_data)
    y_gap_threshold = avg_h * 0.5

    lines = []
    current_line = [chars_data[0]]

    for char in chars_data[1:]:
        if char['cy'] - current_line[-1]['cy'] > y_gap_threshold:
            lines.append(current_line)
            current_line = [char]
        else:
            current_line.append(char)
    lines.append(current_line)

    final_text = ""
    for line in lines:
        line.sort(key=lambda c: c['cx'])
        for char in line:
            final_text += char['label']

    return final_text


def _normalize_plate(clean_text: str) -> tuple[str | None, str | None]:
    """
    clean_text를 유효한 번호판으로 정규화.

    반환: (numeric_part, region_prefix)
      - numeric_part : 투표에 쓸 숫자 시작 번호판  (예: '92바8588')
      - region_prefix: 지역명 한글 앞부분, 없으면 None (예: '경기')

    처리 순서:
      1. 지역명 포함 패턴 완전 일치 → 지역명 분리 후 반환
         예) '경기92바8588' → ('92바8588', '경기')
      2. 숫자 시작 패턴 완전 일치   → (그대로, None)
         예) '92바8588'   → ('92바8588', None)
      3. 둘 다 실패(노이즈 섞임)    → search로 숫자 시작 부분만 추출
         예) '경종기거92바8588' → ('92바8588', None)
      4. 추출도 실패               → (None, None)
    """
    if plate_pattern_region.match(clean_text):
        # 앞 한글(1~2자)과 나머지 분리
        m = re.match(r'^([가-힣]{1,2})(\d{2,3}[가-힣]\d{4})$', clean_text)
        if m:
            return m.group(2), m.group(1)   # ('92바8588', '경기')

    if plate_pattern_numeric.match(clean_text):
        return clean_text, None             # ('92바8588', None)

    # 노이즈 섞임 → 숫자 시작 부분만 추출
    m = plate_pattern_extract.search(clean_text)
    if m:
        return m.group(), None              # ('92바8588', None)

    return None, None


def ocr_worker():
    """
    백그라운드 OCR 전담 스레드.

    투표 전략:
      - 투표 키는 항상 숫자 시작 번호판(numeric_part)으로 통일
        → '경기92바8588'과 '92바8588'이 같은 표로 카운팅됨
      - 지역명 포함 패턴이 한 번이라도 나오면 _region_seen[tid]에 기록
      - 최종 텍스트 결정:
          _region_seen에 기록된 tid → '경기' + '92바8588' = '경기92바8588'
          기록 없는 tid             → '92바8588' 그대로

    큐 출력: (tid, p_img, final_text)
      통과: final_text = 완성된 번호판 문자열
      탈락: (tid, None, None)
    """
    ocr_model = None
    print("🔍 YOLO-OCR 스레드 준비 완료 (지역명 분리 투표 모드)")

    while True:
        try:
            item = ocr_input_queue.get(timeout=1)
            if item is None:
                print("🔍 YOLO-OCR 스레드 종료")
                break

            ocr_model = get_shared_ocr_model()
            track_id, plate_img = item

            future = _ocr_executor.submit(_ocr_predict, ocr_model, plate_img)
            results = future.result()

            raw_text = _parse_ocr_result(results, ocr_model.names)

            # ── 텍스트 정제 (한글·숫자만) ──────────────────────────────
            clean_text = re.sub(r'[^가-힣0-9]', '', raw_text)

            # ── 필터 1: 한글 시작 2글자 체크 ──────────────────────────
            is_valid_hangul_start = True
            if clean_text and re.match(r'[가-힣]', clean_text[0]):
                if len(clean_text) < 2 or not re.match(r'[가-힣]', clean_text[1]):
                    is_valid_hangul_start = False

            # ── 필터 2: 길이 >= 6, 숫자 개수 >= 5 ─────────────────────
            has_min_length = len(clean_text) >= 6
            has_min_digits = len(re.findall(r'\d', clean_text)) >= 5

            # ── 필터 3: 번호판 패턴 정규화 ─────────────────────────────
            numeric_part, region_prefix = (None, None)
            if is_valid_hangul_start and has_min_length and has_min_digits:
                numeric_part, region_prefix = _normalize_plate(clean_text)

            # ── 지역명 기록 ─────────────────────────────────────────────
            if region_prefix:
                with _region_lock:
                    _region_seen[track_id] = region_prefix

            # ── 최종 텍스트 결정 ────────────────────────────────────────
            if numeric_part:
                with _region_lock:
                    saved_region = _region_seen.get(track_id)

                final_text = (saved_region + numeric_part) if saved_region else numeric_part

                print(f"   ㄴ ✅ [분석 통과] ID:{track_id} -> '{final_text}'"
                      + (f" (원본: '{clean_text}')" if final_text != clean_text else ""))
                ocr_result_queue.put((track_id, plate_img, final_text))
            else:
                if clean_text:
                    reasons = []
                    if not is_valid_hangul_start: reasons.append("한글시작규칙")
                    if not has_min_length:        reasons.append("길이미달")
                    if not has_min_digits:        reasons.append("숫자개수미달")
                    if is_valid_hangul_start and has_min_length and has_min_digits:
                        reasons.append("패턴불일치")
                    print(f"   ㄴ ❌ [필터 탈락] ID:{track_id} -> '{clean_text}' (사유: {', '.join(reasons)})")
                ocr_result_queue.put((track_id, None, None))

            ocr_input_queue.task_done()

        except Exception as e:
            import queue as q
            if isinstance(e, q.Empty):
                continue
            print(f"❌ YOLO-OCR 오류: {e}")
            continue


def clear_region_cache(track_id: int):
    """
    process_video.py 에서 track_id 종료 시 호출해 메모리 누수 방지.
    (선택적 — 호출 안 해도 동작에는 문제 없음)
    """
    with _region_lock:
        _region_seen.pop(track_id, None)


def run_ocr_once(img, ocr_instance=None) -> str:
    """
    reprocess 엔드포인트용 단발성 OCR
    """
    model = ocr_instance or get_shared_ocr_model()

    results = model.predict(img, conf=0.25, device='cpu', verbose=False)
    text = _parse_ocr_result(results, model.names)

    clean_text = re.sub(r'[^가-힣0-9]', '', text)
    numeric_part, region_prefix = _normalize_plate(clean_text)

    if numeric_part:
        return (region_prefix + numeric_part) if region_prefix else numeric_part

    return "인식 실패"