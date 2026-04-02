import random, os
from flask import Blueprint, request, jsonify, current_app
import shared.state as shared
from modules.traffic.detectors.manager import detector_manager

simulation_bp = Blueprint('simulation', __name__)

def get_random_video(video_type):
    assets_path = os.path.join(os.getcwd(), "assets")
    files = [f for f in os.listdir(assets_path) if f.startswith(video_type) and f.endswith(".mp4")]
    return random.choice(files) if files else f"{video_type}.mp4"

def get_random_seoul_coord():
    lat = round(random.uniform(37.4268, 37.7006), 6)
    lng = round(random.uniform(126.7644, 127.1812), 6)
    return lat, lng


@simulation_bp.route('/api/start_simulation', methods=['POST'])
def start_simulation():
    data = request.get_json()
    video_type = data.get('type')

    if video_type in shared.ANOMALY_DATA:
        lat, lng = get_random_seoul_coord()
        shared.sim_coords = {"lat": lat, "lng": lng}

        if video_type != "webcam":
            shared.current_video_file[video_type] = get_random_video(video_type)

        sim_key = f'sim_{video_type}'
        with detector_manager._lock:
            if sim_key in detector_manager.active_detectors:
                detector_manager.active_detectors[sim_key].stop()
                del detector_manager.active_detectors[sim_key]
                del detector_manager.threads[sim_key]
                print(f"🔄 [{sim_key}] 재시작을 위해 기존 detector 종료")

        shared.current_broadcast_type = video_type
        shared.alert_sent_session[video_type] = False

        socketio = current_app.extensions['socketio']
        socketio.emit('force_video_start', {"type": video_type, "lat": lat, "lng": lng})
        return jsonify({"status": "success"}), 200
    return jsonify({"status": "error"}), 400