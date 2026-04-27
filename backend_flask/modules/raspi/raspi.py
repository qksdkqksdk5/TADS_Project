import os
import re
import time
import cv2
import socket
import pickle
import struct
import threading
import numpy as np
from flask import Blueprint, Response, jsonify, request
from ultralytics import YOLO

_RE_X = re.compile(r'[Xx]([\d.-]+)')
_RE_Y = re.compile(r'[Yy]([\d.-]+)')

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
_video_thread = None
_thermal_thread = None
_model_thread = None
_patrol_thread = None
_track_thread = None
motor_lock = threading.Lock()
detection_enabled = False
fire_detected = False  # 화재 감지 상태
auto_tracking_enabled = False # 자동 추적 상태
last_track_time = 0    # 마지막 추적 명령 시간
max_temp = 0.0         # 현재 최대 온도
current_x = 0.0        # 백엔드 추적 X 좌표
current_y = 0.0        # 백엔드 추적 Y 좌표
frame_count = 0        # 프레임 스킵용 카운터
last_detections = []   # 성능 최적화를 위한 마지막 감지 결과 저장
patrol_enabled = False # 자율 감시 모드 활성화 여부
patrol_direction = 1   # 감시 방향 (1: 우, -1: 좌)

TILT_LIMIT_MIN = -1.8
TILT_LIMIT_MAX = 1.1

PATROL_STEP = 5
PATROL_SPEED = 1500
PATROL_RANGE = 50

# --- [ 1. AI 모델 로드 ] ---
def load_model():
    global model
    with model_lock:
        if model is None:
            # 사람 감지 및 일반 물체 추적을 위해 표준 모델 사용
            model = YOLO("yolov8n.pt")
            print("✅ [AI] YOLOv8 Nano Model Loaded (Person Detection Enabled)")

# --- [ 2. 열화상 데이터 렌더링 로직 ] ---
def process_thermal_logic():
    global processed_thermal_frame, thermal_data, fire_detected, max_temp
    if thermal_data is None:
        return

    try:
        # 24x32 어레이 변환
        t_img = np.array(thermal_data).reshape(24, 32)
        
        # 🔥 화재 감지 및 온도 업데이트
        max_temp = float(np.max(t_img))
        fire_detected = bool(max_temp > 60.0)
        
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
                                
                                h, w = img.shape[:2]
                                center_x, center_y = w // 2, h // 2
                                
                                global frame_count, last_detections, last_track_time

                                if (detection_enabled or auto_tracking_enabled) and model:
                                    if frame_count % 3 == 0:
                                        results = model.predict(img, conf=0.4, imgsz=320, verbose=False)
                                        last_detections = []
                                        for r in results:
                                            for box in r.boxes:
                                                cls = int(box.cls[0])
                                                x1, y1, x2, y2 = map(int, box.xyxy[0])
                                                last_detections.append((x1, y1, x2, y2, cls))

                                    frame_count += 1
                                    target_box = None

                                    for box_info in last_detections:
                                        x1, y1, x2, y2, cls = box_info
                                        color = (255, 0, 0) if cls == 0 else (0, 255, 0)
                                        label = "PERSON" if cls == 0 else model.names[cls]
                                        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
                                        cv2.putText(img, label, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                                        if cls == 0 and target_box is None:
                                            target_box = (x1, y1, x2, y2)

                                    if target_box is None and last_detections:
                                        target_box = last_detections[0][:4]

                                    if auto_tracking_enabled and target_box:
                                        now = time.time()
                                        if now - last_track_time > 0.4:
                                            tx1, ty1, tx2, ty2 = target_box
                                            bcx, bcy = (tx1 + tx2) // 2, (ty1 + ty2) // 2
                                            dx = bcx - center_x
                                            dy = bcy - center_y
                                            cmd_x, cmd_y = 0, 0
                                            if abs(dx) > 50:
                                                cmd_x = 5 if dx < 0 else -5
                                            if abs(dy) > 40:
                                                new_y = current_y + (-0.1 if dy > 0 else 0.1)
                                                if TILT_LIMIT_MIN <= new_y <= TILT_LIMIT_MAX:
                                                    cmd_y = -0.1 if dy > 0 else 0.1
                                            if cmd_x != 0 or cmd_y != 0:
                                                gcode = f"G1 {f'X{cmd_x} ' if cmd_x != 0 else ''}{f'Y{cmd_y} ' if cmd_y != 0 else ''}F1500"
                                                # 이전 추적 스레드가 끝난 경우에만 새 스레드 시작
                                                global _track_thread
                                                if _track_thread is None or not _track_thread.is_alive():
                                                    _track_thread = threading.Thread(target=send_motor_command, args=(gcode,), daemon=True)
                                                    _track_thread.start()
                                                last_track_time = now

                                # 온도를 영상 상단에 항상 표시
                                temp_color = (0, 0, 255) if max_temp > 60 else (0, 255, 0)
                                cv2.putText(img, f"TEMP: {max_temp:.1f} C", (20, 40), 
                                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, temp_color, 2)
                                
                                if fire_detected:
                                    cv2.putText(img, "!!! FIRE DETECTED !!!", (w//2-150, h-40), 
                                                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 3)
                                
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

# --- [ 5. 자율 감시(Patrol) 워커 ] ---
def patrol_worker():
    global patrol_enabled, patrol_direction, current_x
    print("🛡️ [PATROL WORKER] Thread Started")
    
    while not _stop_event.is_set():
        if patrol_enabled:
            if auto_tracking_enabled and len(last_detections) > 0:
                time.sleep(1.0)
                continue

            try:
                step = PATROL_STEP * patrol_direction

                if current_x + step > PATROL_RANGE:
                    patrol_direction = -1
                    step = -PATROL_STEP
                elif current_x + step < -PATROL_RANGE:
                    patrol_direction = 1
                    step = PATROL_STEP

                gcode = f"G1 X{step} F{PATROL_SPEED}"
                print(f"🛡️ [PATROL EXEC] Cmd: {gcode}, Current X: {current_x}, Dir: {patrol_direction}")
                ok = send_motor_command(gcode)
                if not ok:
                    print("⚠️ [PATROL] Motor command failed, retrying in 3s...")
                    time.sleep(3.0)
                    continue

                time.sleep(1.5)
            except Exception as e:
                print(f"❌ [PATROL ERROR] {e}")
                time.sleep(2.0)
        else:
            time.sleep(1.0)

def ensure_workers_alive():
    global _workers_started, _video_thread, _thermal_thread, _model_thread, _patrol_thread
    
    # 워커가 한 번도 시작되지 않았거나, 필수 스레드가 죽었는지 체크
    need_restart = not _workers_started
    if not need_restart:
        video_alive = _video_thread and _video_thread.is_alive()
        thermal_alive = _thermal_thread and _thermal_thread.is_alive()
        patrol_alive = _patrol_thread and _patrol_thread.is_alive()
        if not (video_alive and thermal_alive and patrol_alive):
            need_restart = True
            
    if need_restart:
        print("🔄 [BACKEND] Re-initializing Workers...")
        _stop_event.clear()
        _workers_started = True
        
        if _model_thread is None or not _model_thread.is_alive():
            _model_thread = threading.Thread(target=load_model, daemon=True)
            _model_thread.start()
            
        if _thermal_thread is None or not _thermal_thread.is_alive():
            _thermal_thread = threading.Thread(target=thermal_receiver_worker, daemon=True)
            _thermal_thread.start()
            
        if _video_thread is None or not _video_thread.is_alive():
            _video_thread = threading.Thread(target=stream_proxy_worker, daemon=True)
            _video_thread.start()
            
        if _patrol_thread is None or not _patrol_thread.is_alive():
            _patrol_thread = threading.Thread(target=patrol_worker, daemon=True)
            _patrol_thread.start()

# --- [ 6. Flask 라우팅 ] ---

@raspi_bp.route('/video_feed')
def video_feed():
    feed_type = request.args.get('type', 'normal')
    
    text = "WAITING FOR THERMAL..." if feed_type == 'thermal' else "CONNECTING CAMERA..."
    _ph = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(_ph, text, (120, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 150, 150), 2)
    _, _ph_enc = cv2.imencode('.jpg', _ph)
    placeholder_bytes = _ph_enc.tobytes()

    def gen():
        while not _stop_event.is_set():
            frame = None
            with frame_lock:
                if feed_type == 'thermal':
                    frame = processed_thermal_frame
                else:
                    frame = processed_rgb_frame if processed_rgb_frame else raw_frame

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + (frame or placeholder_bytes) + b'\r\n')
            time.sleep(0.05)
            
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

@raspi_bp.route('/start', methods=['POST'])
def start():
    ensure_workers_alive()
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
    # 명령 처리 전 워커 상태 강제 확인 및 복구
    ensure_workers_alive()
    
    global current_controller_id, last_control_time
    
    cmd = request.args.get('cmd')
    mode = request.args.get('mode')
    
    if mode:
        print(f"📡 [CONTROL] Received Mode Change: {mode}")
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

    # 모드 변경 (AI 감지 / 자동 추적 / 자율 감시)
    global detection_enabled, auto_tracking_enabled, patrol_enabled
    if mode == 'detect_on': detection_enabled = True
    elif mode == 'detect_off': detection_enabled = False
    elif mode == 'auto_on': auto_tracking_enabled = True
    elif mode == 'auto_off': auto_tracking_enabled = False
    elif mode == 'patrol_on': patrol_enabled = True
    elif mode == 'patrol_off': patrol_enabled = False
        
    return jsonify({
        "status": "ok", 
        "detect": detection_enabled,
        "fire": fire_detected,
        "auto": auto_tracking_enabled,
        "patrol": patrol_enabled,
        "max_temp": max_temp,
        "x": round(current_x, 2),
        "y": round(current_y, 2)
    })

def update_internal_coords(gcode):
    global current_x, current_y
    if "G92" in gcode:
        current_x = 0.0
        current_y = 0.0
        return
    x_match = _RE_X.search(gcode)
    y_match = _RE_Y.search(gcode)
    if x_match:
        current_x += float(x_match.group(1))
    if y_match:
        current_y += float(y_match.group(1))

def send_motor_command(gcode):
    with motor_lock:
        try:
            remapped_gcode = gcode.replace('Y', 'Z').replace('y', 'z')

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((RASPI_IP, PORT_MOTOR))

                full_cmd = remapped_gcode if remapped_gcode.endswith('\n') else remapped_gcode + '\n'
                s.sendall(full_cmd.encode())

                res = s.recv(1024)
                # 소켓 전송 성공 후에만 좌표 업데이트
                update_internal_coords(gcode)
                print(f"🔄 [REMAPPED] {gcode.strip()} -> {remapped_gcode.strip()}")
                print(f"🤖 [MOTOR] Response: {res.decode().strip()}")
                return True
        except Exception as e:
            print(f"❌ [MOTOR CONTROL ERROR] {e}")
            return False

@raspi_bp.route('/ping')
def ping():
    results = {}
    for name, port in [("motor", PORT_MOTOR), ("video", PORT_VIDEO), ("thermal", PORT_THERMAL)]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((RASPI_IP, port))
            results[name] = "ok"
        except Exception as e:
            results[name] = str(e)

    return jsonify({
        "raspi_ip": RASPI_IP,
        "ports": results,
        "patrol_enabled": patrol_enabled,
        "patrol_thread_alive": bool(_patrol_thread and _patrol_thread.is_alive()),
        "motor_lock_locked": motor_lock.locked(),
    })