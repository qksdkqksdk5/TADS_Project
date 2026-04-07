import os
import requests
import random
from dotenv import load_dotenv
from flask import Blueprint, jsonify, Response, request, current_app
from modules.traffic.detectors.manager import detector_manager
from modules.traffic.detectors.fire_detector import FireDetector
from modules.traffic.detectors.reverse_detector import ReverseDetector
import shared.state as shared

load_dotenv()

its_bp = Blueprint('its', __name__)
ITS_API_KEY = os.getenv('ITS_API_KEY', '22f088a782aa49f6a441b24c2b36d4ec')

cached_cctv_list = []

# @its_bp.route('/get_cctv_url', methods=['GET'])
# def get_cctv_url():
#     global cached_cctv_list
    
#     if cached_cctv_list:
#         print("♻️ [캐시 데이터 반환] 기존 CCTV 리스트를 사용합니다.")
#         return jsonify({"success": True, "cctvData": cached_cctv_list})

#     params = {
#         'apiKey': ITS_API_KEY, 'type': 'ex', 'cctvType': '1',
#         'minX': '126.8', 'maxX': '127.89',
#         'minY': '36.8',  'maxY': '37.0', 'getType': 'json'
#     }

#     try:
#         response = requests.get("https://openapi.its.go.kr:9443/cctvInfo", params=params, timeout=5)
#         if response.status_code == 200:
#             data      = response.json()
#             cctv_list = data.get("response", {}).get("data", [])
#             if cctv_list:
#                 random_cctvs     = random.sample(cctv_list, min(len(cctv_list), 4))
#                 cached_cctv_list = [{
#                     "url": item['cctvurl'], "name": item['cctvname'],
#                     "lat": float(item['coordy']), "lng": float(item['coordx'])
#                 } for item in random_cctvs]
#                 print(f"📡 [API 호출 성공] {len(cached_cctv_list)}개의 CCTV를 고정합니다.")
#                 return jsonify({"success": True, "cctvData": cached_cctv_list})
#         raise Exception("API 응답이 올바르지 않습니다.")
#     except Exception as e:
#         print(f"📡 ITS 연결 실패: {e}")
#         test_url         = "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"
#         cached_cctv_list = [
#             {"url": test_url, "name": f"테스트 채널 {i+1}", "lat": 37.5, "lng": 127.0}
#             for i in range(4)
#         ]
#         return jsonify({"success": True, "cctvData": cached_cctv_list})

@its_bp.route('/get_cctv_url', methods=['GET'])
def get_cctv_url():
    global cached_cctv_list
    
    # 1. 이미 누군가(프론트)가 넣어준 데이터가 있다면 그걸 줍니다.
    if cached_cctv_list:
        print("♻️ [캐시 데이터 반환] 고정된 CCTV 리스트를 사용합니다.")
        return jsonify({"success": True, "cctvData": cached_cctv_list})

    # 2. 데이터가 없다면? 백엔드는 직접 구하러 가지 않고 "없다"고만 말합니다.
    # 그럼 프론트엔드가 이 응답을 받고 직접 ITS API를 호출하게 됩니다.
    print("ℹ️ [캐시 없음] 프론트엔드에게 직접 호출을 유도합니다.")
    return jsonify({"success": False, "cctvData": []})


# ✅ 프론트에서 직접 ITS API 호출 후 백엔드 캐시에 저장
@its_bp.route('/set_cctv_list', methods=['POST'])
def set_cctv_list():
    global cached_cctv_list
    
    # ⭐ 이미 캐시가 존재하면 덮어쓰지 않고 즉시 반환 (새로고침 방지 핵심)
    if len(cached_cctv_list) > 0:
        return jsonify({"success": True, "message": "Already cached"})

    data = request.get_json()
    cached_cctv_list = data.get('cctvData', [])
    print(f"📡 [최초 캐시 저장] {len(cached_cctv_list)}개 CCTV 고정 완료")
    return jsonify({"success": True})


# ✅ 감지 시작 — 스트리밍 없이 백그라운드 감지만
@its_bp.route('/start_detection', methods=['POST'])
def start_detection():
    data     = request.get_json()
    url      = data.get('url')
    name     = data.get('name', 'default')
    lat      = float(data.get('lat', 37.5))
    lng      = float(data.get('lng', 127.0))
    det_type = data.get('type', 'reverse')  # 'reverse' or 'fire'

    socketio = current_app.extensions['socketio']
    app_obj  = current_app._get_current_object()
    from models import db as db_inst, DetectionResult, ReverseResult

    if det_type == 'reverse':
        unique_name = f"{name}_reverse"
        detector_manager.get_or_create(
            unique_name, ReverseDetector,
            url=url, lat=lat, lng=lng,
            video_origin="realtime_its",
            socketio=socketio, db=db_inst,
            ResultModel=DetectionResult,
            ReverseModel=ReverseResult,
            app=app_obj
        )
        print(f"🔴 [{unique_name}] 역주행 감지 시작")

    elif det_type == 'fire':
        unique_name = f"{name}_fire"
        detector_manager.get_or_create(
            unique_name, FireDetector,
            url=url, lat=lat, lng=lng,
            socketio=socketio, db=db_inst,
            ResultModel=DetectionResult,
            app=app_obj
        )
        print(f"🔥 [{unique_name}] 화재 감지 시작")

    return jsonify({"status": "ok"}), 200


# # ✅ 감지 중지
# @its_bp.route('/stop_detection', methods=['POST'])
# def stop_detection():
#     data     = request.get_json()
#     name     = data.get('name', '')
#     det_type = data.get('type', 'reverse')
#     key      = f"{name}_{det_type}"

#     with detector_manager._lock:
#         if key in detector_manager.active_detectors:
#             detector_manager.active_detectors[key].stop()
#             del detector_manager.active_detectors[key]
#             del detector_manager.threads[key]
#             print(f"⏹️ [{key}] 감지 중지")
#             return jsonify({"status": "ok"}), 200

#     return jsonify({"status": "not_found"}), 404

@its_bp.route('/stop_detection', methods=['POST'])
def stop_detection():
    data = request.get_json()
    name = data.get('name', '')
    det_type = data.get('type', 'reverse')
    key = f"{name}_{det_type}"

    with detector_manager._lock:
        # ✅ del 대신 pop을 사용하여 키가 없어도 에러가 나지 않게 합니다.
        detector = detector_manager.active_detectors.pop(key, None)
        if detector:
            detector.stop()
            detector_manager.threads.pop(key, None) # 스레드 관리 딕셔너리에서도 제거
            print(f"⏹️ [{key}] 감지 중지 완료")
            return jsonify({"status": "ok"}), 200

    return jsonify({"status": "not_found"}), 404


# ✅ 감지 상태 확인
@its_bp.route('/detection_status', methods=['GET'])
def detection_status():
    with detector_manager._lock:
        active = [
            name for name in detector_manager.active_detectors.keys()
            if not name.startswith('sim_')      # 시뮬 제외
            and not name.startswith('webcam_')  # 웹캠 제외
        ]
    return jsonify({"active": active}), 200


# 기존 스트리밍 라우트 유지 (하위 호환)
@its_bp.route('/video_feed')
def video_feed():
    url      = request.args.get('url')
    name     = request.args.get('name', 'default')
    lat      = float(request.args.get('lat', 37.5))
    lng      = float(request.args.get('lng', 127.0))
    conf_val = float(request.args.get('conf', 0.66))

    unique_name = f"{name}_reverse"
    socketio    = current_app.extensions['socketio']
    app_obj     = current_app._get_current_object()
    from models import db as db_inst, DetectionResult, ReverseResult

    detector = detector_manager.get_or_create(
        unique_name, ReverseDetector,
        url=url, lat=lat, lng=lng,
        video_origin="realtime_its",
        socketio=socketio, db=db_inst,
        ResultModel=DetectionResult,
        ReverseModel=ReverseResult,
        conf=conf_val, app=app_obj
    )
    return Response(detector.generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@its_bp.route('/fire_feed')
def fire_feed():
    url         = request.args.get('url')
    name        = request.args.get('name', 'fire_cctv')
    lat         = float(request.args.get('lat', 37.5))
    lng         = float(request.args.get('lng', 127.0))
    unique_name = f"{name}_fire"
    socketio    = current_app.extensions['socketio']
    app_obj     = current_app._get_current_object()
    from models import db as db_inst, DetectionResult

    detector = detector_manager.get_or_create(
        unique_name, FireDetector,
        url=url, lat=lat, lng=lng,
        socketio=socketio, db=db_inst,
        ResultModel=DetectionResult, app=app_obj
    )
    return Response(detector.generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')