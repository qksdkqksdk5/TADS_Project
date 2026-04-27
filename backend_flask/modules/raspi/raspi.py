import os
import time
import cv2
import socket
import pickle
import struct
import threading
import numpy as np
from flask import Blueprint, Response, jsonify, request
from ultralytics import YOLO
import uuid # 고유 세션 ID 생성용

# 모터 제어권 관리 변수
current_controller_id = None  # 현재 제어 중인 클라이언트 ID
last_control_time = 0         # 마지막 제어 시간 (타임아웃용)
CONTROL_TIMEOUT = 10          # 10초 동안 명령이 없으면 제어권 해제

# Flask Blueprint 설정
raspi_bp = Blueprint('raspi', __name__)

# --- [ 하드웨어 및 네트워크 설정 ] ---
# 💡 라즈베리 파이의 실제 개별 IP 주소를 입력하세요.
RASPI_IP = "192.168.219.155" 
PORT_MOTOR = 9997
PORT_VIDEO = 9998
PORT_THERMAL = 9999

# --- [ 전역 상태 관리 ] ---
model = None
model_lock = threading.Lock()
frame_lock = threading.Lock()

# 실시간 프레임 저장용 변수
raw_frame = None            # 라즈베리파이 원본 MJPEG
processed_rgb_frame = None  # YOLO + 180도 회전 완료본
processed_thermal_frame = None  # 컬러맵 입혀진 열화상 프레임
thermal_data = None         # MLX90640 센서 로우 데이터 (24x32)

# 제어 플래그
_stop_event = threading.Event()
_workers_started = False
detection_enabled = False

# --- [ 1. AI 모델 로드 ] ---
def load_model():
    global model
    with model_lock:
        if model is None:
            path = os.path.join(os.path.dirname(__file__), "best_SB.pt")
            if os.path.exists(path):
                model = YOLO(path)
                print("✅ [AI] YOLOv8 Model Loaded Successfully")
            else:
                print(f"⚠️ [AI] Model file not found at: {path}")

# --- [ 2. 열화상 데이터 렌더링 로직 ] ---
def process_thermal_logic():
    global processed_thermal_frame, thermal_data
    if thermal_data is None:
        return

    try:
        # 24x32 어레이 변환
        t_img = np.array(thermal_data).reshape(24, 32)
        
        # 💡 가시광선 카메라와 방향 일치 (상하좌우 반전 = 180도 회전)
        t_img = np.flipud(np.fliplr(t_img))
        
        # 정규화 및 컬러맵 (JET) 적용
        t_norm = cv2.normalize(t_img, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
        t_color = cv2.applyColorMap(t_norm, cv2.COLORMAP_JET)
        
        # 640x480 확대
        thermal_img = cv2.resize(t_color, (640, 480), interpolation=cv2.INTER_CUBIC)
        
        _, enc_thermal = cv2.imencode('.jpg', thermal_img)
        with frame_lock:
            processed_thermal_frame = enc_thermal.tobytes()
    except Exception as e:
        print(f"⚠️ [THERMAL LOGIC ERROR] {e}")

# --- [ 3. 라즈베리파이 스트림 수신 워커 ] ---
def stream_proxy_worker():
    global raw_frame, processed_rgb_frame, detection_enabled, model
    print("🎬 [VIDEO WORKER] Thread Started")
    
    while not _stop_event.is_set():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((RASPI_IP, PORT_VIDEO))
                print(f"✅ [VIDEO] Connected to Pi at {RASPI_IP}")
                
                byte_data = b''
                while not _stop_event.is_set():
                    chunk = s.recv(65536)
                    if not chunk: break
                    byte_data += chunk
                    
                    while True:
                        start = byte_data.find(b'\xff\xd8')
                        end = byte_data.find(b'\xff\xd9')
                        if start != -1 and end != -1 and end > start:
                            jpg = byte_data[start:end+2]
                            byte_data = byte_data[end+2:]
                            
                            with frame_lock:
                                raw_frame = jpg
                            
                            # 가시광선 후처리
                            nparr = np.frombuffer(jpg, np.uint8)
                            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            if img is not None:
                                img = cv2.rotate(img, cv2.ROTATE_180) # 180도 회전
                                
                                if detection_enabled and model:
                                    results = model(img, conf=0.5, verbose=False)
                                    for r in results:
                                        for box in r.boxes:
                                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                                            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                                
                                _, enc_rgb = cv2.imencode('.jpg', img)
                                with frame_lock:
                                    processed_rgb_frame = enc_rgb.tobytes()
                        else:
                            break
        except Exception as e:
            print(f"❌ [VIDEO PROXY ERROR] {e}")
            time.sleep(2)

# --- [ 4. 열화상 데이터 수신 워커 ] ---
def thermal_receiver_worker():
    global thermal_data
    print("🔥 [THERMAL WORKER] Thread Started")
    
    while not _stop_event.is_set():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10.0) # 클러스터 지연 고려
                s.connect((RASPI_IP, PORT_THERMAL))
                print(f"✅ [THERMAL] Connected to Pi at {RASPI_IP}")
                
                payload_size = struct.calcsize("Q")
                data = b""
                while not _stop_event.is_set():
                    while len(data) < payload_size:
                        packet = s.recv(4096)
                        if not packet: break
                        data += packet
                    
                    if len(data) < payload_size: break
                    
                    packed_msg_size = data[:payload_size]
                    data = data[payload_size:]
                    msg_size = struct.unpack("Q", packed_msg_size)[0]
                    
                    while len(data) < msg_size:
                        packet = s.recv(4096)
                        if not packet: break
                        data += packet
                    
                    try:
                        with frame_lock:
                            thermal_data = pickle.loads(data[:msg_size])
                        data = data[msg_size:]
                        process_thermal_logic() 
                    except Exception as pe:
                        print(f"⚠️ [THERMAL PICKLE ERROR] {pe}")
                        data = b"" 
        except Exception as e:
            print(f"❌ [THERMAL PROXY ERROR] {e}")
            time.sleep(2)

# --- [ 5. Flask 라우팅 ] ---

@raspi_bp.route('/video_feed')
def video_feed():
    feed_type = request.args.get('type', 'normal')
    
    def gen():
        while not _stop_event.is_set():
            frame = None
            with frame_lock:
                if feed_type == 'thermal':
                    frame = processed_thermal_frame
                else:
                    frame = processed_rgb_frame if processed_rgb_frame else raw_frame
            
            # 💡 데이터 수신 전까지 Placeholder 송출로 브라우저 끊김 방지
            if frame is None:
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                text = "WAITING FOR THERMAL..." if feed_type == 'thermal' else "CONNECTING CAMERA..."
                cv2.putText(placeholder, text, (120, 240), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 150, 150), 2)
                _, enc = cv2.imencode('.jpg', placeholder)
                frame = enc.tobytes()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.05)
            
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

@raspi_bp.route('/start', methods=['POST'])
def start():
    global _workers_started
    if _workers_started:
        return jsonify({"status": "already_running"})
    
    _stop_event.clear()
    _workers_started = True
    
    threading.Thread(target=load_model, daemon=True).start()
    threading.Thread(target=thermal_receiver_worker, daemon=True).start()
    threading.Thread(target=stream_proxy_worker, daemon=True).start()
    
    print("🚀 [BACKEND] All Workers Launched")
    return jsonify({"status": "ok"})

@raspi_bp.route('/stop', methods=['POST'])
def stop():
    global _workers_started
    print("🛑 [BACKEND] Stop signal received")
    _stop_event.set()
    _workers_started = False
    return jsonify({"status": "ok"})

# [백엔드 raspi.py]
@raspi_bp.route('/control')
def control():
    global current_controller_id, last_control_time
    
    cmd = request.args.get('cmd')
    mode = request.args.get('mode')
    client_id = request.args.get('client_id') # 프론트에서 보낸 고유 ID
    
    current_time = time.time()
    
    # 1. 제어권 체크 (모터 명령 cmd가 있을 때만 체크)
    if cmd:
        # 제어권 타임아웃 확인 (오랫동안 명령 없으면 자동 해제)
        if current_controller_id and (current_time - last_control_time > CONTROL_TIMEOUT):
            current_controller_id = None
            print("🕒 [MOTOR] Control timeout. Permission released.")

        # 권한 검사
        if current_controller_id is None:
            # 아무도 제어 중이 아니면 권한 획득
            current_controller_id = client_id
            last_control_time = current_time
        elif current_controller_id != client_id:
            # 다른 사람이 제어 중이면 거절
            print(f"🚫 [MOTOR] Blocked request from {client_id}. Occupied by {current_controller_id}")
            return jsonify({
                "status": "error", 
                "message": "현재 다른 사용자가 모터를 제어 중입니다. 잠시 후 다시 시도하세요."
            }), 403 # Forbidden

        # 권한이 있는 경우 마지막 제어 시간 갱신
        last_control_time = current_time
        
        # 모터 명령 전송
        print(f"📡 [BACKEND] Executing G-Code: {cmd}")
        threading.Thread(target=send_motor_command, args=(cmd,), daemon=True).start()

    # AI 감지 모드 변경 (이건 여러 명이 동시에 해도 무관하므로 권한 체크 제외 가능)
    global detection_enabled
    if mode == 'detect_on': detection_enabled = True
    elif mode == 'detect_off': detection_enabled = False
        
    return jsonify({"status": "ok", "detect": detection_enabled})

def send_motor_command(gcode):
    try:
        # 💡 하드웨어 장애 대응: Y축 명령을 Z축으로 리매핑
        # G1 Y10 F3500 -> G1 Z10 F3500 으로 변경
        remapped_gcode = gcode.replace('Y', 'Z').replace('y', 'z')
        
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect((RASPI_IP, PORT_MOTOR))
            
            # 리매핑된 명령 전송
            full_cmd = remapped_gcode if remapped_gcode.endswith('\n') else remapped_gcode + '\n'
            s.sendall(full_cmd.encode())
            
            res = s.recv(1024)
            print(f"🔄 [REMAPPED] {gcode.strip()} -> {remapped_gcode.strip()}")
            print(f"🤖 [MOTOR] Response: {res.decode().strip()}")
    except Exception as e:
        print(f"❌ [MOTOR CONTROL ERROR] {e}")