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
# - [추가] 차선 재추정 요청
# ==========================================

from flask import Blueprint, jsonify, Response, request
from .service import TunnelLiveService

# ---------------------------------------------------------
# Blueprint 생성
# url_prefix="/api/tunnel" 이므로
# 실제 주소는 예:
#   /api/tunnel/health
#   /api/tunnel/status
#   /api/tunnel/lane/reestimate
# ---------------------------------------------------------
tunnel_bp = Blueprint("tunnel", __name__, url_prefix="/api/tunnel")

# ---------------------------------------------------------
# 서비스 객체 1회 생성
# routes에서는 이 service를 통해 상태 조회 / 선택 / 스트리밍 / 재추정 요청 수행
# ---------------------------------------------------------
service = TunnelLiveService()


@tunnel_bp.route("/health", methods=["GET"])
def health():
    """
    간단한 모듈 헬스 체크
    """
    return jsonify({
        "ok": True,
        "module": "tunnel"
    })


@tunnel_bp.route("/cctv-list", methods=["GET"])
def cctv_list():
    """
    현재 캐시된 CCTV 리스트 조회
    """
    data = service.get_cctv_list()
    return jsonify({
        "ok": True,
        "count": len(data),
        "items": data
    })


@tunnel_bp.route("/set-cctv-list", methods=["POST"])
def set_cctv_list():
    """
    프론트에서 전달한 CCTV 후보 리스트를 서비스에 저장
    body 예시:
    {
        "items": [
            {"name": "...", "url": "..."},
            ...
        ]
    }
    """
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
    """
    캐시된 CCTV 중 하나를 랜덤 선택
    """
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
    """
    현재 터널 분석 상태 조회
    주의:
    - service.get_status() 안에서
      lane_reestimate_status / lane_reestimate_frame_count 같은 값도 같이 넘겨주면
      프론트에서 '재추정 중 (n/50)' 표시 가능
    """
    return jsonify(service.get_status())


@tunnel_bp.route("/select-cctv", methods=["GET"])
def select_cctv():
    """
    이름으로 CCTV 선택
    예:
    /api/tunnel/select-cctv?name=광암터널2
    """
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
    """
    MJPEG 스트리밍 응답
    """
    return Response(
        service.generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )




# =========================================================
# [추가] 차선 재추정 요청
# =========================================================
@tunnel_bp.route("/lane/reestimate", methods=["POST"])
def lane_reestimate():
    """
    관제사가 버튼을 누르면 호출하는 API

    동작 목적:
    - 지금 시점부터 50프레임 동안 차선 재추정용 데이터를 수집하도록 요청
    - 실제 50프레임 수집과 재군집화는 service / lane_template 내부에서 진행

    service.py 안에 아래 메서드가 반드시 있어야 함:
        service.request_lane_reestimate()

    반환 예시:
    {
        "ok": True,
        "message": "차선 재추정 요청 접수",
        "frame_id": 1234,
        "window": 50
    }
    """

    try:
        result = service.request_lane_reestimate()
    except AttributeError:
        # service.py에 아직 메서드가 없을 때
        return jsonify({
            "ok": False,
            "message": "service.py에 request_lane_reestimate() 메서드가 없습니다."
        }), 500
    except Exception as e:
        return jsonify({
            "ok": False,
            "message": f"차선 재추정 요청 중 오류: {str(e)}"
        }), 500

    status_code = 200 if result.get("ok", False) else 400
    return jsonify(result), status_code

@tunnel_bp.route("/lane/save", methods=["POST"])
def lane_save():
    result = service.save_current_lane_memory()
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code

