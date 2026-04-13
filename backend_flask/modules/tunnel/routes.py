# ==========================================
# 파일명: routes.py
# 위치: backend_flask/modules/tunnel/routes.py
# 역할:
# 1. ITS CCTV 목록 가져오기
# 2. CCTV 영상 스트리밍
# 3. YOLO 객체탐지 적용 후 웹으로 전송
# ==========================================

import requests
import xml.etree.ElementTree as ET
from flask import Blueprint, jsonify, Response
import cv2
from ultralytics import YOLO
import os
import time
from dotenv import load_dotenv

# ==========================================
# 🔧 Blueprint 설정
# ==========================================
tunnel_bp = Blueprint("tunnel", __name__)

print("🔥 CCTV routes loaded")


# ==========================================
# 🔧 1️⃣ 상태 API (프론트 테스트용)
# ==========================================
@tunnel_bp.route("/status")
def get_status():
    """
    👉 현재는 더미 데이터
    👉 나중에 pipeline_core 연결 예정
    """

    data = {
        "state": "CONGESTION",
        "avg_speed": 6.2,
        "vehicle_count": 8,
        "vehicles": [
            {"id": 1, "speed": 5.3},
            {"id": 2, "speed": 6.1}
        ],
        "dwell_times": {
            "1": 12,
            "2": 9
        },
        "events": [
            "[12:01] 급접근 감지"
        ]
    }

    return jsonify(data)


# ==========================================
# 🔧 2️⃣ ITS CCTV 목록 가져오기
# ==========================================
BASE_DIR = os.path.dirname(__file__)
load_dotenv(os.path.join(BASE_DIR, ".env"))

ITS_API_KEY = os.getenv('ITS_API_KEY', '8fc75e2a3b1c413f8111579275a4a6fa')


def get_cctv_list():
    """
    👉 ITS Open API 호출
    👉 터널 CCTV만 필터링
    """

    url = f"https://openapi.its.go.kr:9443/cctvInfo?apiKey={API_KEY}&type=ex&cctvType=1&minX=126.5&maxX=127.5&minY=37.0&maxY=38.0&getType=xml"

    response = requests.get(url)

    if response.status_code != 200:
        print("❌ API 호출 실패")
        return []

    # XML 파싱
    root = ET.fromstring(response.text)

    cctvs = []

    for cctv in root.findall(".//data"):
        name = cctv.find("cctvname").text
        stream_url = cctv.find("cctvurl").text

        # 👉 "터널" 포함된 CCTV만 필터링
        if "터널" in name:
            cctvs.append({
                "name": name,
                "url": stream_url
            })

    return cctvs


@tunnel_bp.route("/cctv-list")
def cctv_list():
    print("🔥 CCTV API 호출됨")
    return jsonify(get_cctv_list())


# ==========================================
# 🔧 3️⃣ YOLO + CCTV 스트리밍
# ==========================================

# 🔥 YOLO 모델 로드 (서버 시작 시 1번만 실행됨)
BASE_DIR = os.path.dirname(__file__)
MODEL_PATH = os.path.join(BASE_DIR, "models", "best.pt")

model = YOLO(MODEL_PATH)

def generate_frames():

    # CCTV주소 직접 입력 (광암터널 퇴계원 2 )
    CCTV_URL = "http://cctvsec.ktict.co.kr/8558/KSrxjYDGHtixpy78e4wH21YWQk9pwDzl+1Cqx0QFYpnj/hzM834Ncc4Rm7qddnFA8ACGV1yrCyOq6sNHw5I52ik2p7kq06C8XbjOh4f9lc4="
    print("🎥 CCTV 연결:", CCTV_URL)

    cap = cv2.VideoCapture(CCTV_URL)

    if not cap.isOpened():
        print("❌ 영상 열기 실패")
        return
    
    frame_count = 0    

    while True:
        success, frame = cap.read()
        if not success:
            print("❌ 프레임 못 가져옴")
            break

        # 🔥 크기 줄이기
        frame = cv2.resize(frame, (640, 360))

        # ==========================================
        # 🔥 YOLO 객체 탐지
        # ==========================================
        
        frame_count += 1
        
        # 🔥 YOLO 간헐 실행
        if frame_count % 3 == 0:
            results = model(frame)

        # ==========================================
        # 🔥 바운딩 박스 그리기
        # ==========================================
            for r in results:
                for box in r.boxes.xyxy:
                    x1, y1, x2, y2 = map(int, box)

                    cv2.rectangle(frame, (x1, y1), (x2, y2),
                                (0, 255, 0), 2)
                    
        # 🔥 FPS 제한
        time.sleep(0.05)

        # ==========================================
        # 🔥 프레임 → JPEG 변환 → 웹 전송
        # ==========================================
        _, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' +
               frame_bytes + b'\r\n')


# ==========================================
# 🔧 4️⃣ CCTV 선택 API
# ==========================================
@tunnel_bp.route("/select-cctv")
def select_cctv():
    """
    👉 첫 번째 터널 CCTV 자동 선택 (테스트용)
    👉 나중에 React에서 선택하도록 변경 가능
    """

    global CCTV_URL

    cctvs = get_cctv_list()

    if len(cctvs) == 0:
        print("❌ CCTV 없음")
        return

    CCTV_URL = cctvs[0]["url"]

    print("✅ 선택된 CCTV:", CCTV_URL)

    return jsonify({
        "message": "CCTV 선택 완료",
        "url": CCTV_URL
    })


# ==========================================
# 🔧 5️⃣ 영상 스트리밍 API
# ==========================================
@tunnel_bp.route("/video_feed")
def video_feed():
    """
    👉 React에서 이 URL을 img로 호출하면 영상 출력됨
    """

    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )