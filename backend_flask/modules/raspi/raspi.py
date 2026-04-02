import time
import cv2
import numpy as np
import requests
import threading
import socket
import pickle
import struct
from flask import Blueprint, Response, jsonify, request
from ultralytics import YOLO

raspi_bp = Blueprint('raspi', __name__)

# --- [1. 설정 및 AI 모델] ---
RASPI_BACKEND_URL = "http://192.168.219.155:5000"
RASPI_THERMAL_IP = "192.168.219.155"
RASPI_THERMAL_PORT = 9999

try:
    model = YOLO('best.pt')
    print("[INFO] YOLOv8 model loaded.")
except Exception as e:
    print(f"[ERROR] Model load failed: {e}")
    model = None

# 전역 상태 변수
detection_enabled = False
tracking_enabled = False
processed_frame = None
fire_detected = False
thermal_data = None  # 최신 열화상 Raw 데이터를 저장할 변수
frame_lock = threading.Lock()

# --- [2. 열화상 데이터 수신 스레드 (추가)] ---
def thermal_receiver_worker():
    """라즈베리파이 9999 포트에서 열화상 데이터를 받아오는 전용 워커"""
    global thermal_data
    while True:
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((RASPI_THERMAL_IP, RASPI_THERMAL_PORT))
            payload_size = struct.calcsize("Q")
            data = b""
            print(f"[THERMAL] Connected to {RASPI_THERMAL_IP}:{RASPI_THERMAL_PORT}")

            while True:
                # 1. 메시지 크기(Header) 수신
                while len(data) < payload_size:
                    packet = client_socket.recv(4096)
                    if not packet: break
                    data += packet
                if not data: break

                packed_msg_size = data[:payload_size]
                data = data[payload_size:]
                msg_size = struct.unpack("Q", packed_msg_size)[0]

                # 2. 실제 프레임 데이터(Body) 수신
                while len(data) < msg_size:
                    data += client_socket.recv(4096)
                
                frame_data = data[:msg_size]
                data = data[msg_size:]
                
                # 3. 데이터 복원 및 전역 변수 업데이트
                temp_thermal = pickle.loads(frame_data)
                with frame_lock:
                    thermal_data = temp_thermal

        except Exception as e:
            print(f"[THERMAL ERROR] {e}. 3초 후 재연결 시도...")
            time.sleep(3)
        finally:
            client_socket.close()

# 열화상 수신 스레드 시작
threading.Thread(target=thermal_receiver_worker, daemon=True).start()

# --- [3. 모터 제어 로직 (기존 유지)] ---
def send_motor_command(gcode):
    try:
        url = f"{RASPI_BACKEND_URL}/api/raspi/control"
        requests.get(url, params={"cmd": gcode}, timeout=0.2)
    except: pass

def track_object(cx, cy):
    if not tracking_enabled: return
    error_x = cx - 320
    error_y = cy - 240
    threshold = 40
    step = 2
    cmd_x, cmd_y = 0, 0
    if abs(error_x) > threshold:
        cmd_x = step if error_x > 0 else -step
    if abs(error_y) > threshold:
        cmd_y = -step if error_y > 0 else step
    if cmd_x != 0 or cmd_y != 0:
        gcode = f"G1 {f'X{cmd_x} ' if cmd_x != 0 else ''}{f'Y{cmd_y} ' if cmd_y != 0 else ''}F3500"
        send_motor_command(gcode)

# modules/raspi/raspi.py 내 해당 함수 수정

def process_ai_logic(jpg_data):
    global processed_frame, fire_detected, detection_enabled, thermal_data
    
    # --- [수정 포인트 1: 일반 영상 사용 안 함] ---
    # nparr = np.frombuffer(jpg_data, np.uint8) # 이 줄은 분석용으로만 쓰거나 필요없으면 제거
    # img = cv2.imdecode(nparr, cv2.IMREAD_COLOR) 
    
    # --- [수정 포인트 2: 순수 검정 배경 생성 (640x480)] ---
    display_img = np.zeros((480, 640, 3), dtype=np.uint8)

    # --- [수정 포인트 3: 열화상 데이터만 입히기] ---
    if thermal_data is not None:
        try:
            # 24x32 Raw 데이터를 넘파이 배열로 변환
            t_img = np.array(thermal_data).reshape(24, 32)
            # 정규화 (0~255)
            t_norm = cv2.normalize(t_img, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
            # 컬러맵 적용 (업로드하신 사진과 같은 색감은 COLORMAP_JET 입니다)
            t_color = cv2.applyColorMap(t_norm, cv2.COLORMAP_JET)
            # 부드러운 화질을 위해 보간법(CUBIC)을 사용하여 640x480으로 확대
            display_img = cv2.resize(t_color, (640, 480), interpolation=cv2.INTER_CUBIC)
        except Exception as e:
            print(f"[THERMAL ERROR] {e}")

    # YOLO 분석 (열화상 화면에서 객체 감지)
    if detection_enabled and model is not None:
        results = model(display_img, imgsz=320, stream=True, conf=0.5, verbose=False)
        current_fire = False
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                label = model.names[int(box.cls[0])].lower()
                
                color = (0, 0, 255) if 'fire' in label else (0, 255, 0)
                if 'fire' in label: current_fire = True
                
                # 열화상 화면 위에 박스 그리기
                cv2.rectangle(display_img, (x1, y1), (x2, y2), color, 2)
                cv2.putText(display_img, f"{label}", (x1, y1-10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        fire_detected = current_fire

    # 최종 결과 전송 (이제 순수 열화상 이미지가 전송됨)
    enc_success, enc_buffer = cv2.imencode('.jpg', display_img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if enc_success:
        with frame_lock:
            processed_frame = enc_buffer.tobytes()
            
# --- [5. 스트림 수신 워커 (기존 유지)] ---
def stream_proxy_worker():
    stream_url = f"{RASPI_BACKEND_URL}/video_feed"
    print(f"[INFO] Connecting to Raspi Stream: {stream_url}")
    while True:
        try:
            response = requests.get(stream_url, stream=True, timeout=None)
            byte_data = b''
            for chunk in response.iter_content(chunk_size=16384):
                if not chunk: break
                byte_data += chunk
                while True:
                    start = byte_data.find(b'\xff\xd8')
                    end = byte_data.find(b'\xff\xd9')
                    if start != -1 and end != -1 and end > start:
                        jpg = byte_data[start:end+2]
                        byte_data = byte_data[end+2:]
                        process_ai_logic(jpg)
                    else: break
        except Exception as e:
            time.sleep(2)

threading.Thread(target=stream_proxy_worker, daemon=True).start()

# --- [6. API 엔드포인트] ---
@raspi_bp.route('/video_feed')
def video_feed():
    def generate():
        while True:
            with frame_lock:
                if processed_frame:
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + processed_frame + b'\r\n')
            time.sleep(0.04)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@raspi_bp.route('/control')
def control():
    global tracking_enabled, detection_enabled, fire_detected
    mode = request.args.get('mode')
    if mode == 'detect_on': detection_enabled = True
    elif mode == 'detect_off': 
        detection_enabled = False
        fire_detected = False
    elif mode == 'auto_on': tracking_enabled = True
    elif mode == 'auto_off': tracking_enabled = False

    cmd = request.args.get('cmd')
    if cmd: send_motor_command(cmd)

    return jsonify({
        "status": "ok", "detect": detection_enabled,
        "auto": tracking_enabled, "fire_alert": fire_detected
    })