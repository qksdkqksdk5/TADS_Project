# ==========================================
# 파일명: routes.py
# 위치: backend_flask/modules/tunnel/routes.py
# 역할:
# - health
# - 캐시된 CCTV 목록 조회
# - 프론트에서 CCTV 후보 리스트 저장
# - 랜덤 CCTV 선택
# - 이름으로 CCTV 선택
# - 상태 조회
# - 실시간 영상 스트리밍
# ==========================================

from flask import Blueprint, jsonify, Response, request
from .service import TunnelLiveService

tunnel_bp = Blueprint("tunnel", __name__, url_prefix="/api/tunnel")

service = TunnelLiveService()


@tunnel_bp.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "module": "tunnel"
    })


@tunnel_bp.route("/cctv-list", methods=["GET"])
def cctv_list():
    data = service.get_cctv_list()
    return jsonify({
        "ok": True,
        "count": len(data),
        "items": data
    })


@tunnel_bp.route("/set-cctv-list", methods=["POST"])
def set_cctv_list():
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])

    ok = service.set_cctv_list(items)
    if not ok:
        return jsonify({
            "ok": False,
            "message": "유효한 CCTV 리스트가 아닙니다."
        }), 400

    return jsonify({
        "ok": True,
        "message": "CCTV 리스트 저장 완료",
        "count": len(service.get_cctv_list())
    })


@tunnel_bp.route("/select-random", methods=["GET"])
def select_random():
    cctv = service.select_random_cctv()

    if not cctv:
        return jsonify({
            "ok": False,
            "message": "캐시된 터널 CCTV 없음"
        }), 404

    return jsonify({
        "ok": True,
        "message": "랜덤 CCTV 선택 완료",
        "cctv": cctv
    })


@tunnel_bp.route("/status", methods=["GET"])
def status():
    return jsonify(service.get_status())


@tunnel_bp.route("/select-cctv", methods=["GET"])
def select_cctv():
    name = request.args.get("name", "").strip()

    if not name:
        return jsonify({
            "ok": False,
            "message": "name 파라미터가 필요합니다."
        }), 400

    cctv = service.select_cctv_by_name(name)

    if not cctv:
        return jsonify({
            "ok": False,
            "message": f"'{name}' 에 해당하는 CCTV를 찾지 못했습니다."
        }), 404

    return jsonify({
        "ok": True,
        "message": "CCTV 선택 완료",
        "cctv": cctv
    })


@tunnel_bp.route("/video-feed", methods=["GET"])
def video_feed():
    return Response(
        service.generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )