import os
import time
import cv2
import numpy as np
from ultralytics import YOLO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PT_MODEL_PATH = os.path.join(BASE_DIR, 'plate_best02.pt')
OPENVINO_MODEL_PATH = os.path.join(BASE_DIR, 'plate_openvino_model')

# 테스트할 모델 경로
models = {
    "YOLOv11n (.pt)": PT_MODEL_PATH,
    "YOLOv11n (OpenVINO)": OPENVINO_MODEL_PATH,
}

# 더미 프레임 (실제 영상 없어도 됨)
dummy_frame = np.random.randint(0, 255, (360, 640, 3), dtype=np.uint8)
NUM_RUNS = 100  # 100프레임 측정

for name, path in models.items():
    model = YOLO(path)
    
    # 워밍업
    for _ in range(5):
        model.predict(dummy_frame, imgsz=640, verbose=False)
    
    # 측정
    start = time.time()
    for _ in range(NUM_RUNS):
        model.predict(dummy_frame, imgsz=640, verbose=False)
    elapsed = time.time() - start
    
    fps = NUM_RUNS / elapsed
    ms  = (elapsed / NUM_RUNS) * 1000
    print(f"[{name}]")
    print(f"  평균 FPS : {fps:.1f}")
    print(f"  추론 시간: {ms:.1f}ms")
    print()