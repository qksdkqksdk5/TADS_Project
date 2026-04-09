# backend_flask/modules/monitoring/carbon.py
# 담당자: monitoring 기능 개발

from flask import Blueprint, jsonify

monitoring_bp = Blueprint('monitoring', __name__)

@monitoring_bp.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "module": "monitoring"}), 200

# 여기에 모니터링 관련 API 라우트 추가하세요