from flask import Blueprint, jsonify, Response, stream_with_context
from .service_V5_1 import tunnel_service
import time

tunnel_bp = Blueprint("tunnel", __name__)


@tunnel_bp.route("/status", methods=["GET"])
def get_status():
    return jsonify(tunnel_service.get_status())


@tunnel_bp.route("/start", methods=["POST"])
def start_tunnel():
    tunnel_service.start()
    return jsonify({
        "message": "tunnel service started",
        "running": True
    }), 200


@tunnel_bp.route("/stop", methods=["POST"])
def stop_tunnel():
    tunnel_service.stop()
    return jsonify({
        "message": "tunnel service stopped",
        "running": False
    }), 200


def generate_frames():
    while True:
        frame_bytes = tunnel_service.get_jpeg_frame()

        if frame_bytes is None:
            time.sleep(0.05)
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Cache-Control: no-cache\r\n\r\n" +
            frame_bytes +
            b"\r\n"
        )

        time.sleep(0.03)


@tunnel_bp.route("/video_feed", methods=["GET"])
def video_feed():
    return Response(
        stream_with_context(generate_frames()),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
        direct_passthrough=True,
    )