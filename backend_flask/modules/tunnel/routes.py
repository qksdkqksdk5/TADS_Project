from flask import Blueprint, jsonify

tunnel_bp = Blueprint("tunnel", __name__)

@tunnel_bp.route("/status")
def get_status():

    # 🔥 지금은 테스트용 (나중에 pipeline 연결)
    data = {
        "state": "CONGESTION",
        "avg_speed": 6.2,
        "vehicle_count": 8,
        "vehicles": [
            {"id": 1, "speed": 5.3},
            {"id": 2, "speed": 6.1}
        ],
        "dwell_times": {
            "1": 12,
            "2": 9
        },
        "events": [
            "[12:01] 급접근 감지"
        ]
    }

    return jsonify(data)