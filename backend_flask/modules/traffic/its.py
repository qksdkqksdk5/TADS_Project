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
ITS_API_KEY = os.getenv('ITS_API_KEY')

cached_cctv_list = []

@its_bp.route('/get_cctv_url', methods=['GET'])
def get_cctv_url():
    global cached_cctv_list
    
    # force 파라미터가 있으면 캐시를 무시하고 새로 API 호출 (URL 만료 대비)
    force_refresh = request.args.get('force') == 'true'
    
    if cached_cctv_list and not force_refresh:
        print("♻️ [캐시 데이터 반환] 기존 고정 CCTV 리스트를 사용합니다.")
        return jsonify({"success": True, "cctvData": cached_cctv_list})

    params = {
        'apiKey': ITS_API_KEY, 'type': 'ex', 'cctvType': '4',
        'minX': '126.8', 'maxX': '127.89',
        'minY': '36.8',  'maxY': '37.0', 'getType': 'json'
    }

    try:
        response = requests.get("https://openapi.its.go.kr:9443/cctvInfo", params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            cctv_list = data.get("response", {}).get("data", [])
            
            if cctv_list:
                # ✅ [인덱스 고정 전략] 하암육교(7), 안성(1), 서해주탑(12), 입장(15)
                target_indices = [7, 24, 12, 15]
                selected_cctvs = []
                
                for idx in target_indices:
                    # 인덱스 범위 안전성 체크
                    if idx < len(cctv_list):
                        selected_cctvs.append(cctv_list[idx])
                
                # 만약 위 인덱스가 부족하면 나머지는 랜덤으로 채움
                if len(selected_cctvs) < 4:
                    selected_cctvs += random.sample(cctv_list, 4 - len(selected_cctvs))

                cached_cctv_list = [{
                    "url": item['cctvurl'], 
                    "name": item['cctvname'],
                    "lat": float(item['coordy']), 
                    "lng": float(item['coordx'])
                } for item in selected_cctvs]
                
                print(f"📡 [API 신규 호출] 주요 지점 {len(cached_cctv_list)}개를 고정했습니다.")
                return jsonify({"success": True, "cctvData": cached_cctv_list})
                
        raise Exception("API 응답이 올바르지 않습니다.")
        
    except Exception as e:
        print(f"📡 ITS 연결 실패: {e}")
        # 실패 시 테스트 스트림은 그대로 유지
        test_url = "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"
        cached_cctv_list = [
            {"url": test_url, "name": f"테스트 채널 {i+1}", "lat": 37.5, "lng": 127.0}
            for i in range(4)
        ]
        return jsonify({"success": True, "cctvData": cached_cctv_list})

# @its_bp.route('/get_cctv_url', methods=['GET'])
# def get_cctv_url():
#     global cached_cctv_list
    
#     # 1. 이미 누군가(프론트)가 넣어준 데이터가 있다면 그걸 줍니다.
#     if cached_cctv_list:
#         print("♻️ [캐시 데이터 반환] 고정된 CCTV 리스트를 사용합니다.")
#         return jsonify({"success": True, "cctvData": cached_cctv_list})

#     # 2. 데이터가 없다면? 백엔드는 직접 구하러 가지 않고 "없다"고만 말합니다.
#     # 그럼 프론트엔드가 이 응답을 받고 직접 ITS API를 호출하게 됩니다.
#     print("ℹ️ [캐시 없음] 프론트엔드에게 직접 호출을 유도합니다.")
#     return jsonify({"success": False, "cctvData": []})


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


@its_bp.route('/start_detection', methods=['POST'])
def start_detection():
    data     = request.get_json()
    url      = data.get('url')
    name     = data.get('name', 'default')
    lat      = float(data.get('lat', 37.5))
    lng      = float(data.get('lng', 127.0))
    det_type = data.get('type', 'fire')

    socketio = current_app.extensions['socketio']
    app_obj  = current_app._get_current_object()
    from models import db as db_inst, DetectionResult, ReverseResult

    if det_type == 'fire':
        unique_name = f"{name}_fire"
        detector_manager.get_or_create(
            unique_name, FireDetector,
            url=url, lat=lat, lng=lng,
            socketio=socketio, db=db_inst,
            ResultModel=DetectionResult,
            app=app_obj
        )
        print(f"🔥 [{unique_name}] 화재 감지 시작")

    elif det_type == 'reverse':
        unique_name = f"{name}_reverse"
        detector_manager.get_or_create(
            unique_name, ReverseDetector,
            url=url, lat=lat, lng=lng,
            video_origin="realtime_its",
            socketio=socketio, db=db_inst,
            ResultModel=DetectionResult,
            ReverseModel=ReverseResult,
            conf=0.66,
            app=app_obj
        )
        print(f"🚗 [{unique_name}] 역주행 감지 시작")

    else:
        return jsonify({"status": "error", "message": "unknown detection type"}), 400

    return jsonify({"status": "ok"}), 200


# ✅ 감지 중지
@its_bp.route('/stop_detection', methods=['POST'])
def stop_detection():
    data     = request.get_json()
    name     = data.get('name', '')
    det_type = data.get('type', 'fire')
    key      = f"{name}_{det_type}"

    with detector_manager._lock:
        if key in detector_manager.active_detectors:
            try:
                detector_manager.active_detectors[key].stop()
                del detector_manager.active_detectors[key]
                del detector_manager.threads[key]
                print(f"⏹️ [{key}] 감지 중지")
                return jsonify({"status": "ok"}), 200
            except Exception as e:
                print(f"❌ [{key}] 감지 중지 실패: {e}")
                return jsonify({"status": "error", "message": str(e)}), 500

    # 감지기가 없는 건 정상 케이스 → 200
    return jsonify({"status": "not_found"}), 200

# @its_bp.route('/stop_detection', methods=['POST'])
# def stop_detection():
#     data = request.get_json()
#     name = data.get('name', '')
#     det_type = data.get('type', 'fire')
#     key = f"{name}_{det_type}"

#     with detector_manager._lock:
#         # ✅ del 대신 pop을 사용하여 키가 없어도 에러가 나지 않게 합니다.
#         detector = detector_manager.active_detectors.pop(key, None)
#         if detector:
#             detector.stop()
#             detector_manager.threads.pop(key, None) # 스레드 관리 딕셔너리에서도 제거
#             print(f"⏹️ [{key}] 감지 중지 완료")
#             return jsonify({"status": "ok"}), 200

#     return jsonify({"status": "not_found"}), 404


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

    with detector_manager._lock:
        # 🔥 핵심: 이미 active인 경우만 프레임 제공, 없으면 404
        detector = detector_manager.active_detectors.get(unique_name)

    if detector is None:
        return Response("감지기 없음", status=404)

    # URL 갱신만 해줌 (재생성 X)
    if hasattr(detector, 'url') and detector.url != url:
        detector.url = url
        if hasattr(detector, 'cap') and detector.cap is not None:
            detector.cap.release()

    return Response(detector.generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@its_bp.route('/fire_feed')
def fire_feed():
    url         = request.args.get('url')
    name        = request.args.get('name', 'fire_cctv')
    unique_name = f"{name}_fire"

    with detector_manager._lock:
        detector = detector_manager.active_detectors.get(unique_name)

    if detector is None:
        return Response("감지기 없음", status=404)

    # URL 토큰 갱신만 처리 (재생성 X)
    if hasattr(detector, 'url') and detector.url != url:
        detector.url = url
        if hasattr(detector, 'cap') and detector.cap is not None:
            detector.cap.release()

    return Response(detector.generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')