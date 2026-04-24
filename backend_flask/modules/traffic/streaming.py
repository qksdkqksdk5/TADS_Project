import os
import cv2
from datetime import datetime
from flask import Blueprint, Response, request, jsonify, current_app
from matplotlib.pylab import rint
from models import db, DetectionResult, ManualResult
from modules.traffic.detectors.manager import detector_manager
from modules.traffic.detectors.fire_detector import FireDetector
from modules.traffic.detectors.reverse_detector import ReverseDetector
import shared.state as shared

streaming_bp = Blueprint('streaming', __name__)


def _get_detector(video_type, socketio, app):
    """
    video_type → detector 매핑
    - 'webcam'  : FireDetector(url=0, is_simulation=False)
    - 'fire'    : FireDetector(url=mp4, is_simulation=True)
    - 'reverse' : ReverseDetector(url=mp4, is_simulation=True)
    ITS CCTV는 its.py에서 직접 생성하므로 여기선 처리하지 않음
    """
    from models import db as db_inst, DetectionResult

    common = dict(socketio=socketio, db=db_inst, ResultModel=DetectionResult, app=app)

    if video_type == 'webcam':
        return detector_manager.get_or_create(
            'webcam_fire',
            FireDetector,
            url=0,
            lat=37.5413, lng=126.8381,
            is_simulation=False,
            video_origin='webcam',
            **common
        )

    elif video_type == 'fire':
        file_name  = shared.current_video_file.get('fire', 'fire.mp4')
        video_path = os.path.join(os.getcwd(), "assets", file_name)

        # 새 시뮬레이션 시작 전 기존 detector 정지
        detector_manager.stop('sim_fire')

        return detector_manager.get_or_create(
            'sim_fire',
            FireDetector,
            url=video_path,
            lat=shared.sim_coords["lat"], lng=shared.sim_coords["lng"],
            is_simulation=True,
            video_origin='fire',
            **common
        )

    elif video_type == 'reverse':
        file_name    = shared.current_video_file.get('reverse', 'reverse.mp4')
        video_path   = os.path.join(os.getcwd(), "assets", file_name)
        real_its_url = shared.CCTV_URLS.get('reverse', "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8")

        # 새 시뮬레이션 시작 전 기존 detector 정지
        detector_manager.stop('sim_reverse')

        return detector_manager.get_or_create(
            'sim_reverse',
            ReverseDetector,
            url=video_path,
            realtime_url=real_its_url,
            lat=shared.sim_coords["lat"], lng=shared.sim_coords["lng"],
            is_simulation=True,
            video_origin='reverse',
            **common
        )

    return None


@streaming_bp.route('/api/stop_simulation', methods=['POST'])
def stop_simulation():
    data       = request.get_json(silent=True) or {}
    video_type = data.get('type', 'fire')  # 'fire' 또는 'reverse'

    if video_type == 'fire':
        detector_manager.stop('sim_fire')
        print("🛑 [시뮬] fire detector 정지")
    elif video_type == 'reverse':
        detector_manager.stop('sim_reverse')
        print("🛑 [시뮬] reverse detector 정지")
    else:
        # type 미지정이면 둘 다 정지
        detector_manager.stop('sim_fire')
        detector_manager.stop('sim_reverse')
        print("🛑 [시뮬] 모든 시뮬레이션 detector 정지")

    return jsonify({"status": "stopped"}), 200


@streaming_bp.route('/api/video_feed')
def video_feed():
    video_type = request.args.get('type', 'webcam')
    socketio   = current_app.extensions['socketio']
    app        = current_app._get_current_object()
    detector = _get_detector(video_type, socketio, app)

    if detector is None:
        return jsonify({"error": f"지원하지 않는 type: {video_type}"}), 400

    return Response(
        detector.generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@streaming_bp.route('/api/capture_now', methods=['POST'])
def capture_now():
    try:
        data       = request.get_json()
        video_type = data.get('type', 'webcam')
        admin_name = data.get('adminName', '관리자')
        is_sim     = (video_type != 'webcam')

        if video_type == 'sim':
            video_type = shared.current_broadcast_type or next(iter(shared.latest_frames), 'webcam')

        frame = shared.latest_frames.get(video_type)

        if frame is None:
            return jsonify({"status": "error", "message": "영상을 찾을 수 없습니다."}), 400

        new_alert = DetectionResult(
            event_type='manual', address="관리자 수동 캡처 구역",
            latitude=shared.sim_coords["lat"], longitude=shared.sim_coords["lng"],
            is_resolved=True, feedback=True, resolved_at=datetime.now(),
            is_simulation=is_sim, video_origin=None, resolved_by=admin_name
        )
        db.session.add(new_alert)
        db.session.flush()

        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"manual_{new_alert.id}_{ts}.jpg"
        cv2.imwrite(os.path.join(shared.CAPTURE_DIR, filename), frame)

        manual_detail = ManualResult(
            result_id=new_alert.id,
            image_path=f"/static/captures/{filename}",
            memo="메모 없음"
        )
        db.session.add(manual_detail)
        db.session.commit()

        return jsonify({"status": "success", "db_id": new_alert.id, "image_url": manual_detail.image_path})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500


@streaming_bp.route('/api/update_capture_memo', methods=['POST'])
def update_capture_memo():
    try:
        data  = request.get_json()
        db_id = data.get('db_id')
        memo  = data.get('memo', '').strip()

        if not db_id:
            return jsonify({"status": "error", "message": "ID가 누락되었습니다."}), 400

        detail = ManualResult.query.filter_by(result_id=db_id).first()
        if detail:
            detail.memo = memo
            db.session.commit()
            return jsonify({"status": "success"}), 200
        return jsonify({"status": "error", "message": "기록을 찾을 수 없습니다."}), 404
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500