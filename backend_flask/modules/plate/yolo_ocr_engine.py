import os

os.environ["OMP_NUM_THREADS"] = "2"
os.environ["OPENVINO_NUM_THREADS"] = "2"
os.environ["KMP_BLOCKTIME"] = "1"

import queue
import re
import threading
import time
import cv2
import numpy as np
from ultralytics import YOLO

ocr_input_queue = queue.Queue(maxsize=2)
ocr_result_queue = queue.Queue()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OCR_MODEL_PATH = os.path.join(BASE_DIR, 'ocr_openvino_model')

#review01
# ── 번호판 정규식 패턴 ────────────────────────────────────────────────────────
# 1. 영업용(노란색) 필수 패턴: 지역명2자 + 숫자2~3 + 한글1 + 숫자4
#    (지역명이 반드시 포함되어야 함)
RE_YELLOW_STRICT = re.compile(r'([가-힣]{2})(\d{2,3}[가-힣]\d{4})')

# 2. 일반용 패턴: 숫자2~3 + 한글1 + 숫자4
RE_WHITE_NORMAL = re.compile(r'(\d{2,3}[가-힣]\d{4})')

_shared_ocr_model = None
_ocr_model_lock = threading.Lock()

# ── 지역명 메모리 (ID별로 발견된 지역 저장) ──────────────────────────────────
_region_seen: dict[int, str] = {}
_region_lock = threading.Lock()

def get_shared_ocr_model():
    global _shared_ocr_model
    if _shared_ocr_model is None:
        with _ocr_model_lock:
            if _shared_ocr_model is None:
                print(f"🔍 [System] YOLO-OCR 엔진 최초 로드 중... ({OCR_MODEL_PATH})")
                _shared_ocr_model = YOLO(OCR_MODEL_PATH, task='detect')
    return _shared_ocr_model

# review02 - 색상 검출 함수
def detect_plate_color(plate_img):
    if plate_img is None or plate_img.size == 0:
        return "white"
        
    # 1. 전처리: 가우시안 블러 (노이즈 억제)
    blurred = cv2.GaussianBlur(plate_img, (5, 5), 0)
    
    # 2. BGR -> Lab 변환
    # L : 밝기 a : 녹색-빨강 b : 파랑-노랑
    lab = cv2.cvtColor(blurred, cv2.COLOR_BGR2Lab)
    
    # 3. Lab 범위 설정
    lower_lab = np.array([0, 0, 140]) 
    upper_lab = np.array([255, 137, 255])
    
    mask = cv2.inRange(lab, lower_lab, upper_lab)
    
    # 4. 모폴로지 연산 (작은 조명 노이즈 제거)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    # 5. 노란색 비율 계산
    yellow_pixels = cv2.countNonZero(mask)
    total_pixels = plate_img.shape[0] * plate_img.shape[1]
    yellow_ratio = (yellow_pixels / total_pixels) * 100
    
    # 15~20% 기준 (직접 튜닝한 결과에 따라 조정)
    return "yellow" if yellow_ratio > 17 else "white"

def _parse_ocr_result(results, model_names: dict) -> str:
    chars_data = []
    if results and len(results[0].boxes) > 0:
        for box in results[0].boxes:
            cls_id = int(box.cls[0].item())
            label = model_names[cls_id]
            if label in ('license_plate', 'plate'): continue
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            chars_data.append({'label': label, 'cx': (x1+x2)/2, 'cy': (y1+y2)/2, 'h': y2-y1})

    if not chars_data: return ""
    chars_data.sort(key=lambda c: c['cy'])
    avg_h = sum(c['h'] for c in chars_data) / len(chars_data)
    lines = []
    current_line = [chars_data[0]]
    for char in chars_data[1:]:
        if char['cy'] - current_line[-1]['cy'] > avg_h * 0.5:
            lines.append(current_line); current_line = [char]
        else: current_line.append(char)
    lines.append(current_line)

    final_text = ""
    for line in lines:
        line.sort(key=lambda c: c['cx'])
        for char in line: final_text += char['label']
    return final_text

def ocr_worker():
    """ 백그라운드 OCR 전담 스레드 (프로젝트 통합 버전) """
    print("🔍 YOLO-OCR 스레드 준비 완료 [색상인식 + 지능형 필터 모드]")
    ocr_model = get_shared_ocr_model()

    while True:
        try:
            item = ocr_input_queue.get(timeout=1)
            if item is None: break

            track_id, plate_img = item

            # review03 - 색상 인식 → OCR → 패턴 매칭 → 결과 전달 (메모리 활용 포함)
            # 1. 색상 먼저 파악
            color_type = detect_plate_color(plate_img)

            # 2. OCR 예측
            results = ocr_model.predict(plate_img, conf=0.7, imgsz=640, verbose=False, device='cpu')

            if len(results) > 0 and len(results[0].boxes) > 0:
                conf_scores = results[0].boxes.conf.cpu().numpy() # 각 글자의 점수들
                avg_conf = conf_scores.mean() # 전체 글자의 평균 점수
                min_conf = conf_scores.min()  # 가장 낮은 점수의 글자 점수
                print(f" 🔍 [OCR Score] ID:{track_id} | 평균: {avg_conf:.4f} | 최저: {min_conf:.4f}")

            raw_text = _parse_ocr_result(results, ocr_model.names)

            # 3. 텍스트 정제 (한글·숫자만)
            clean_text = re.sub(r'[^가-힣0-9]', '', raw_text)
            
            final_text = None

            # 4. 색상별 맞춤형 로직 적용
            if color_type == "yellow":
                # 노란색: 지역명이 포함된 엄격한 패턴 탐색
                match = RE_YELLOW_STRICT.search(clean_text)
                if match:
                    region_part = match.group(1)
                    number_part = match.group(2)
                    final_text = region_part + number_part
                    
                    with _region_lock:
                        _region_seen[track_id] = region_part
                    print(f"   ㄴ ✅ [영업용 완벽 통과] ID:{track_id} -> '{final_text}'")
                else:
                    # 지역명을 못 찾았을 경우
                    num_match = RE_WHITE_NORMAL.search(clean_text)
                    if num_match:
                        number_only = num_match.group(1)
                        with _region_lock:
                            if track_id in _region_seen:
                                # 이미 저장된 지역명이 있다면 결합
                                final_text = _region_seen[track_id] + number_only
                                print(f"   ㄴ ✅ [영업용 복원] ID:{track_id} -> '{final_text}' (메모리 참조)")
                            else:
                                # 지역명이 아예 처음이라면 숫자만이라도 전송
                                final_text = number_only 
                                print(f"   ㄴ ⚠️ [영업용 지역명 미발견] ID:{track_id} -> '{final_text}' (숫자만 우선 송출)")
            
            else:
                # 흰색/기타: 일반적인 번호판 패턴 탐색
                match = RE_WHITE_NORMAL.search(clean_text)
                if match:
                    final_text = match.group(1)
                    print(f"   ㄴ ✅ [일반 통과] ID:{track_id} -> '{final_text}'")

            # 5. 결과 전달
            if final_text:
                ocr_result_queue.put((track_id, plate_img, final_text))
            else:
                if clean_text:
                    print(f"   ㄴ ❌ [필터 탈락] ID:{track_id} -> '{clean_text}' (사유: 패턴불일치)")
                ocr_result_queue.put((track_id, None, None))

            time.sleep(0.001)
            ocr_input_queue.task_done()

        except Exception as e:
            if "Empty" in str(type(e)): continue
            print(f"❌ YOLO-OCR 오류: {e}")
            continue

def clear_region_cache(track_id: int):
    """ 트래킹 종료 시 호출하여 메모리 관리 """
    with _region_lock:
        _region_seen.pop(track_id, None)

def run_ocr_once(img, ocr_instance=None) -> str:
    """ 단발성 리프로세싱용 """
    model = ocr_instance or get_shared_ocr_model()
    # 색상 확인 (리프로세싱 시에도 색상 기준 적용)
    color = detect_plate_color(img)
    results = model.predict(img, conf=0.25, device='cpu', verbose=False)
    text = _parse_ocr_result(results, model.names)
    clean = re.sub(r'[^가-힣0-9]', '', text)
    
    if color == "yellow":
        match = RE_YELLOW_STRICT.search(clean)
    else:
        match = RE_WHITE_NORMAL.search(clean)
        
    return match.group(0) if match else "인식 실패"
