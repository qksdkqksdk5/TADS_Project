# ==========================================
# 파일명: routes.py
# 위치: backend_flask/modules/tunnel/routes.py
# 역할:
# - health
# - CCTV 목록 조회
# - 랜덤 CCTV 선택
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
    data = service.refresh_cctv_list()
    return jsonify({
        "ok": True,
        "count": len(data),
        "items": data
    })


@tunnel_bp.route("/select-random", methods=["GET"])
def select_random():
    cctv = service.select_random_cctv()

    if not cctv:
        return jsonify({
            "ok": False,
            "message": "터널 CCTV 없음"
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