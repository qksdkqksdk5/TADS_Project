import os
import cv2
from datetime import datetime
from flask import Blueprint, Response, request, jsonify, current_app
from models import db, DetectionResult, ManualResult
from modules.traffic.detectors.manager import detector_manager
from modules.traffic.detectors.fire_detector import FireDetector
import shared.state as shared

streaming_bp = Blueprint('streaming', __name__)

# ✅ YOLO 모델 로드 완전 제거 — FireDetector가 자체 보유


def _get_detector(video_type, socketio, app):
    """
    video_type → detector 매핑
    - 'webcam' : FireDetector(url=0, is_simulation=False, video_origin='webcam')
    - 'fire'   : FireDetector(url=mp4, is_simulation=True,  video_origin='fire')
    ITS CCTV는 its.py에서 직접 생성하므로 여기선 처리하지 않음
    """
    from models import db as db_inst, DetectionResult

    common = dict(socketio=socketio, db=db_inst, ResultModel=DetectionResult, app=app)

    if video_type == 'webcam':
        return detector_manager.get_or_create(
            'webcam_fire',
            FireDetector,
            url=0,                      # ✅ 웹캠
            lat=37.5413, lng=126.8381,
            is_simulation=False,        # ✅ 실제상황
            video_origin='webcam',      # ✅ 프론트 isSimulation 판별용
            **common
        )

    elif video_type == 'fire':
        # start_simulation 호출 시마다 새 영상 파일 + 좌표가 shared에 세팅됨
        file_name  = shared.current_video_file.get('fire', 'fire.mp4')
        video_path = os.path.join(os.getcwd(), "assets", file_name)

        detector_manager.stop('sim_fire')

        return detector_manager.get_or_create(
            'sim_fire',
            FireDetector,
            url=video_path,             # ✅ mp4 파일
            lat=shared.sim_coords["lat"], lng=shared.sim_coords["lng"],
            is_simulation=True,         # ✅ 시뮬레이션
            video_origin='fire',
            **common
        )

    return None

@streaming_bp.route('/api/stop_simulation', methods=['POST'])
def stop_simulation():
    detector_manager.stop('sim_fire')
    print("🛑 [시뮬] 탭 이탈로 인한 detector 정지")
    return jsonify({"status": "stopped"}), 200

@streaming_bp.route('/api/video_feed')
def video_feed():
    """프론트 URL 변경 없음 — 내부만 detector로 교체"""
    video_type = request.args.get('type', 'webcam')
    socketio   = current_app.extensions['socketio']
    app        = current_app._get_current_object()

    detector = _get_detector(video_type, socketio, app)

    if detector is None:
        return jsonify({"error": f"지원하지 않는 type: {video_type}"}), 400

    # BaseDetector.generate_frames() 그대로 사용 (스트리밍 로직 공통)
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