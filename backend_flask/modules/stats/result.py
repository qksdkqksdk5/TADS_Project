from flask import Blueprint, jsonify, request
from models import db, DetectionResult, User
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import joinedload
import shared.state as shared


result_bp = Blueprint('result', __name__)

@result_bp.route('/api/pending_alerts', methods=['GET'])
def get_pending_alerts():
    try:
        unresolved_results = DetectionResult.query.options(
            joinedload(DetectionResult.fire_detail),
            joinedload(DetectionResult.reverse_detail),
            joinedload(DetectionResult.manual_detail),
            joinedload(DetectionResult.resolver)
        ).filter_by(is_resolved=False).order_by(DetectionResult.detected_at.desc()).all()
        
        pending_list = []
        for res in unresolved_results:
            image_path = None
            if res.event_type == 'fire' and res.fire_detail:
                image_path = res.fire_detail.image_path
            elif res.event_type == 'reverse' and res.reverse_detail:
                image_path = res.reverse_detail.image_path
            elif res.event_type == 'manual' and res.manual_detail:
                image_path = res.manual_detail.image_path

            pending_list.append({
                "id": res.id,
                "type": "화재 발생" if res.event_type == 'fire' else "역주행" if res.event_type == 'reverse' else "수동 기록",
                "address": res.address,
                "time": res.detected_at.strftime('%p %I:%M:%S'),
                "lat": res.latitude,
                "lng": res.longitude,
                "origin": res.event_type,
                "image_url": image_path,
                "resolved_by": res.resolved_by                
            })
            
        return jsonify(pending_list), 200
    except Exception as e:
        print(f"❌ [미조치 목록 로드 에러]: {e}")
        return jsonify({"error": str(e)}), 500


def _reset_session(result):
    """
    video_origin 기준으로 alert_sent_session 리셋
    
    session 관리 대상:
      video_origin = 'webcam'  → alert_sent_session['webcam'] 리셋 (실제 화재, 조치 후 재감지)
      video_origin = 'fire'    → 리셋 안 함 (시뮬, 버튼 누를 때만 리셋)
      video_origin = 'reverse' → 리셋 안 함 (시뮬, 버튼 누를 때만 리셋)
      video_origin = 'realtime_its' → 리셋 안 함 (ITS는 session 관리 없음)
      video_origin = None      → 리셋 안 함 (manual 등)
    """

    origin = result.video_origin  # ✅ DB에 저장된 video_origin 직접 사용

    # alert_sent_session에 있는 키이고 시뮬이 아닌 경우만 리셋
    # webcam만 해당 (fire/reverse는 시뮬이라 start_simulation에서 리셋)
    if origin and origin in shared.alert_sent_session and not result.is_simulation:
        shared.alert_sent_session[origin] = False
        print(f"🔄 [세션 리셋] {origin} 감지 세션 초기화 완료 (ID:{result.id})")


@result_bp.route('/api/resolve_alert_db', methods=['POST'])
def resolve_alert_db():
    try:
        data          = request.json
        alert_id      = data.get('alertId')
        is_correct    = data.get('isCorrect')
        admin_name    = data.get('adminName', '').strip() if data.get('adminName') else 'Unknown'
        user_exists   = User.query.filter_by(name=admin_name).first()

        result = DetectionResult.query.get(alert_id)
        if result:
            result.is_resolved   = True
            result.resolved_at   = datetime.now()
            result.feedback      = True if is_correct == 1 else False
            result.resolved_by   = admin_name if user_exists else None

            if not user_exists:
                print(f"⚠️ [주의] 유저 '{admin_name}'가 DB에 없어 resolved_by를 비워둡니다.")

            db.session.commit()
            status_msg = "정탐" if result.feedback else "오탐"
            print(f"✅ [DB 업데이트 성공] ID {alert_id} 조치 완료 ({status_msg})")

            _reset_session(result)  # ✅ video_origin 기반 정확한 리셋

            return jsonify({"success": True, "feedback": status_msg}), 200
        else:
            return jsonify({"success": False, "message": "알림을 찾을 수 없습니다."}), 404
    except Exception as e:
        db.session.rollback()
        print(f"❌ [DB 업데이트 에러]: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@result_bp.route('/api/resolve_alerts_bulk', methods=['POST'])
def resolve_alerts_bulk():
    try:
        data          = request.json
        alert_ids     = data.get('alertIds', [])
        is_correct    = data.get('isCorrect', 1)
        admin_name    = data.get('adminName', 'Unknown')

        if not alert_ids:
            return jsonify({"success": False, "message": "조치할 ID가 없습니다."}), 400

        results = DetectionResult.query.filter(DetectionResult.id.in_(alert_ids)).all()

        now = datetime.now()
        for result in results:
            result.is_resolved   = True
            result.resolved_at   = now
            result.feedback      = True if is_correct == 1 else False
            result.resolved_by   = admin_name

        db.session.commit()

        for result in results:
            _reset_session(result)  # ✅ 각 레코드마다 video_origin 기반 리셋

        print(f"✅ [일괄 업데이트 성공] {len(results)}건 조치 완료 (by {admin_name})")
        return jsonify({"success": True, "count": len(results)}), 200

    except Exception as e:
        db.session.rollback()
        print(f"❌ [일괄 업데이트 에러]: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@result_bp.route('/api/stats/summary', methods=['GET'])
def get_stats_summary():
    try:
        mode = request.args.get('mode', 'real')

        if mode == 'sim':
            base_query = DetectionResult.query.filter_by(is_simulation=True)
        elif mode == 'all':
            base_query = DetectionResult.query
        else:
            base_query = DetectionResult.query.filter_by(is_simulation=False)

        total_resolved  = base_query.filter_by(is_resolved=True).count()
        correct_count   = base_query.filter_by(is_resolved=True, feedback=True).count()
        incorrect_count = base_query.filter_by(is_resolved=True, feedback=False).count()
        fire_count      = base_query.filter_by(event_type='fire').count()
        reverse_count   = base_query.filter_by(event_type='reverse').count()
        manual_count    = base_query.filter_by(event_type='manual').count()

        precision = round((correct_count / total_resolved) * 100, 1) if total_resolved > 0 else 0

        return jsonify({
            "current_mode": mode,
            "total": total_resolved,
            "correct": correct_count,
            "incorrect": incorrect_count,
            "precision": precision,
            "type_counts": {
                "fire": fire_count,
                "reverse": reverse_count,
                "manual": manual_count
            }
        }), 200

    except Exception as e:
        print(f"❌ [통계 데이터 로드 에러]: {e}")
        return jsonify({"error": str(e)}), 500

@result_bp.route('/api/stats/history', methods=['GET'])
def get_stats_history():
    try:
        target_date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        mode            = request.args.get('mode', 'all')

        query = DetectionResult.query.options(
            joinedload(DetectionResult.fire_detail),
            joinedload(DetectionResult.reverse_detail),
            joinedload(DetectionResult.manual_detail),
            joinedload(DetectionResult.resolver)
        ).filter(func.date(DetectionResult.detected_at) == target_date_str)

        if mode == 'real':
            query = query.filter_by(is_simulation=False)
        elif mode == 'sim':
            query = query.filter_by(is_simulation=True)

        results = query.order_by(DetectionResult.detected_at.desc()).all()

        history_list = []
        for res in results:
            image_path = None
            memo       = None

            if res.event_type == 'fire' and res.fire_detail:
                image_path = res.fire_detail.image_path
            elif res.event_type == 'reverse' and res.reverse_detail:
                image_path = res.reverse_detail.image_path
            elif res.event_type == 'manual' and res.manual_detail:
                image_path = res.manual_detail.image_path
                memo = res.manual_detail.memo

            history_list.append({
                "id": res.id,
                "type": res.event_type,
                "is_simulation": res.is_simulation,
                "address": res.address,
                "time": res.detected_at.strftime('%H:%M:%S'),
                "image_path": image_path,
                "memo": memo,
                "feedback": res.feedback,
                "resolved_by": res.resolved_by
            })

        return jsonify({"logs": history_list}), 200

    except Exception as e:
        print(f"❌ [이력 데이터 로드 에러]: {e}")
        return jsonify({"error": str(e)}), 500

@result_bp.route('/api/update_address', methods=['POST'])
def update_address():
    try:
        data         = request.json
        alert_id     = data.get('alertId')
        real_address = data.get('address')

        result = DetectionResult.query.get(alert_id)
        if result:
            result.address = real_address
            db.session.commit()
            print(f"📍 [주소 업데이트 성공] ID: {alert_id} -> {real_address}")
            return jsonify({"success": True}), 200
        else:
            return jsonify({"success": False, "message": "해당 알림 ID를 찾을 수 없습니다."}), 404

    except Exception as e:
        print(f"❌ [주소 업데이트 에러]: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@result_bp.route('/api/resolve_alert', methods=['POST'])
def resolve_alert():

    data       = request.get_json()
    video_type = data.get('type')

    if video_type in shared.alert_sent_session and shared.alert_sent_session[video_type] == True:
        shared.alert_sent_session[video_type] = False
        if video_type != "webcam":
            shared.current_broadcast_type = None
        return jsonify({"status": "success", "message": "Active session resolved"}), 200
    else:
        return jsonify({"status": "success", "message": "History record resolved"}), 200