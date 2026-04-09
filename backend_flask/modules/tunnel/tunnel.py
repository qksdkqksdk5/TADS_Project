# backend_flask/modules/tunnel/carbon.py
# 담당자: tunnel 기능 개발

from flask import Blueprint, jsonify

tunnel_bp = Blueprint('tunnel', __name__)

@tunnel_bp.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "module": "tunnel"}), 200

# 여기에 터널 관련 API 라우트 추가하세요