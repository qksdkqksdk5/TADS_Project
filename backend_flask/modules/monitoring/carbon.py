# backend_flask/modules/carbon/carbon.py
# 담당자: carbon 기능 개발

from flask import Blueprint, jsonify

carbon_bp = Blueprint('carbon', __name__)

@carbon_bp.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "module": "carbon"}), 200

# 여기에 API 라우트 추가하세요