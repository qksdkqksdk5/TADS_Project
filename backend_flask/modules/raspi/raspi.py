import os
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(BASE_DIR, "best_SB.pt")

raspi_bp = Blueprint('raspi', __name__)

# --- [1. 설정 및 AI 모델] ---
RASPI_BACKEND_URL  = "http://192.168.219.155:5000"
RASPI_THERMAL_IP   = "192.168.219.155"
RASPI_THERMAL_PORT = 9999

# ✅ 서버 시작 시 즉시 로드하지 않음 — /start 호출 시 로드
model      = None
model_lock = threading.Lock()

def load_model_if_needed():
    global model
    with model_lock:
        if model is None:
            try:
                model = YOLO(model_path)
                print("[INFO] YOLOv8 model loaded.")
            except Exception as e:
                print(f"[ERROR] Model load failed: {e}")
                model = None

# 전역 상태 변수
detection_enabled = False
tracking_enabled  = False
processed_frame   = None
fire_detected     = False
thermal_data      = None
frame_lock        = threading.Lock()

# 워커 제어 플래그
_workers_started = False
_workers_lock    = threading.Lock()
_stop_event      = threading.Event()


# --- [2. 열화상 데이터 수신 스레드] ---
def thermal_receiver_worker():
    global thermal_data
    while not _stop_event.is_set():
        client_socket = None
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(2.0)
            client_socket.connect((RASPI_THERMAL_IP, RASPI_THERMAL_PORT))
            payload_size = struct.calcsize("Q")
            data = b""
            print(f"[THERMAL] Connected to {RASPI_THERMAL_IP}:{RASPI_THERMAL_PORT}")

            while not _stop_event.is_set():
                try:
                    while len(data) < payload_size:
                        packet = client_socket.recv(4096)
                        if not packet:
                            break
                        data += packet
                    if not data:
                        break

                    packed_msg_size = data[:payload_size]
                    data            = data[payload_size:]
                    msg_size        = struct.unpack("Q", packed_msg_size)[0]

                    while len(data) < msg_size:
                        data += client_socket.recv(4096)

                    frame_data   = data[:msg_size]
                    data         = data[msg_size:]
                    temp_thermal = pickle.loads(frame_data)
                    with frame_lock:
                        thermal_data = temp_thermal

                except socket.timeout:
                    continue

        except Exception as e:
            if not _stop_event.is_set():
                print(f"[THERMAL ERROR] {e}. 3초 후 재연결 시도...")
                time.sleep(3)
        finally:
            if client_socket:
                client_socket.close()

    print("[THERMAL] 워커 종료")


# --- [3. 모터 제어 로직] ---
def send_motor_command(gcode):
    try:
        url = f"{RASPI_BACKEND_URL}/api/raspi/control"
        requests.get(url, params={"cmd": gcode}, timeout=0.2)
    except:
        pass

def track_object(cx, cy):
    if not tracking_enabled: return
    error_x   = cx - 320
    error_y   = cy - 240
    threshold = 40
    step      = 2
    cmd_x, cmd_y = 0, 0
    if abs(error_x) > threshold:
        cmd_x = step if error_x > 0 else -step
    if abs(error_y) > threshold:
        cmd_y = -step if error_y > 0 else step
    if cmd_x != 0 or cmd_y != 0:
        gcode = f"G1 {f'X{cmd_x} ' if cmd_x != 0 else ''}{f'Y{cmd_y} ' if cmd_y != 0 else ''}F3500"
        send_motor_command(gcode)


# --- [4. AI 처리 로직] ---
def process_ai_logic(jpg_data):
    global processed_frame, fire_detected, detection_enabled, thermal_data

    display_img = np.zeros((480, 640, 3), dtype=np.uint8)

    if thermal_data is not None:
        try:
            t_img   = np.array(thermal_data).reshape(24, 32)
            t_norm  = cv2.normalize(t_img, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
            t_color = cv2.applyColorMap(t_norm, cv2.COLORMAP_JET)
            display_img = cv2.resize(t_color, (640, 480), interpolation=cv2.INTER_CUBIC)
        except Exception as e:
            print(f"[THERMAL ERROR] {e}")

    if detection_enabled and model is not None:
        results      = model(display_img, imgsz=320, stream=True, conf=0.5, verbose=False)
        current_fire = False
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                label = model.names[int(box.cls[0])].lower()
                color = (0, 0, 255) if 'fire' in label else (0, 255, 0)
                if 'fire' in label: current_fire = True
                cv2.rectangle(display_img, (x1, y1), (x2, y2), color, 2)
                cv2.putText(display_img, f"{label}", (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        fire_detected = current_fire

    enc_success, enc_buffer = cv2.imencode('.jpg', display_img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if enc_success:
        with frame_lock:
            processed_frame = enc_buffer.tobytes()


# --- [5. 스트림 수신 워커] ---
def stream_proxy_worker():
    stream_url = f"{RASPI_BACKEND_URL}/video_feed"
    print(f"[INFO] Connecting to Raspi Stream: {stream_url}")
    while not _stop_event.is_set():
        try:
            response  = requests.get(stream_url, stream=True, timeout=5)
            byte_data = b''
            for chunk in response.iter_content(chunk_size=16384):
                if _stop_event.is_set():
                    return
                if not chunk:
                    break
                byte_data += chunk
                while True:
                    start = byte_data.find(b'\xff\xd8')
                    end   = byte_data.find(b'\xff\xd9')
                    if start != -1 and end != -1 and end > start:
                        jpg       = byte_data[start:end + 2]
                        byte_data = byte_data[end + 2:]
                        process_ai_logic(jpg)
                    else:
                        break
        except Exception as e:
            if not _stop_event.is_set():
                time.sleep(2)

    print("[STREAM] 워커 종료")


# --- [6. API 엔드포인트] ---

@raspi_bp.route('/start', methods=['POST'])
def start_workers():
    global _workers_started
    with _workers_lock:
        _stop_event.clear()
        if not _workers_started:
            # ✅ 탭 진입 시점에 모델 로드 (백그라운드로 — 서버 응답 블로킹 방지)
            threading.Thread(target=load_model_if_needed, daemon=True).start()
            threading.Thread(target=thermal_receiver_worker, daemon=True).start()
            threading.Thread(target=stream_proxy_worker,    daemon=True).start()
            _workers_started = True
            print("🚀 [raspi] 워커 스레드 시작")
    return jsonify({"status": "ok"}), 200


@raspi_bp.route('/stop', methods=['POST'])
def stop_workers():
    global _workers_started, model
    with _workers_lock:
        _stop_event.set()
        _workers_started = False
        # ✅ 탭 이탈 시 모델도 메모리에서 해제
        with model_lock:
            model = None
        print("🛑 [raspi] 워커 스레드 정지 + 모델 해제")
    return jsonify({"status": "stopped"}), 200


@raspi_bp.route('/video_feed')
def video_feed():
    def generate():
        while True:
            with frame_lock:
                if processed_frame:
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                           + processed_frame + b'\r\n')
            time.sleep(0.04)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')


@raspi_bp.route('/control')
def control():
    global tracking_enabled, detection_enabled, fire_detected
    mode = request.args.get('mode')
    if mode == 'detect_on':
        detection_enabled = True
    elif mode == 'detect_off':
        detection_enabled = False
        fire_detected     = False
    elif mode == 'auto_on':
        tracking_enabled = True
    elif mode == 'auto_off':
        tracking_enabled = False

    cmd = request.args.get('cmd')
    if cmd: send_motor_command(cmd)

    return jsonify({
        "status":     "ok",
        "detect":     detection_enabled,
        "auto":       tracking_enabled,
        "fire_alert": fire_detected
    })


@raspi_bp.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "module": "raspi"}), 200