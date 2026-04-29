# backend_flask/modules/plate/state.py
# 공유 상태 관리 — 모든 스레드가 이 모듈을 통해 상태를 읽고 씀

import threading
import os

# --- [설정] ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, 'plate_openvino_model')
TEST_DIR = os.path.join(BASE_DIR, 'test')
SAVE_DIR = os.path.join(BASE_DIR, 'best_plates_golden')
os.makedirs(SAVE_DIR, exist_ok=True)
os.makedirs(TEST_DIR, exist_ok=True)

# 'paddle' 또는 'yolo' 로 전환
OCR_ENGINE = 'yolo'

ROI_TOP = 0.3
ROI_BOTTOM = 0.85
YOLO_IMG_SIZE = 640
DISPLAY_H = 720
DISPLAY_W = 1080
ASPECT_RATIO_MIN = 1.5
ASPECT_RATIO_MAX = 5.0
MAX_BOX_AREA_RATIO = 0.1
MIN_BOX_AREA_RATIO = 0.0003
VOTE_THRESHOLD = 4

# --- [검출 설정] ---
PAD          = 8      # 번호판 크롭 패딩
CONF         = 0.7    # YOLO 탐지 신뢰도 임계값
HISTORY_MAX  = 6      # 히스토리 최대 개수

# --- [공유 상태] ---
state = {
    'latest_frame': None,
    'plates': [],           # 현재 화면 표시용 (최근 5개)
    'all_results': [],      # 누적 인식 결과 전체
    'best_samples': {},
    'plate_history_ids': [],
    'plate_history_texts': {},
    'plate_votes': {},
    'first_valid_texts': {},
    'queued_ids': set(),
    'current_video': None,
    'stop_thread': False,
}
state_lock = threading.Lock()

# --- [스레드 시작 플래그] ---
is_started = False
is_started_lock = threading.Lock()