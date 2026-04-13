# backend_flask/modules/monitoring/monitoring.py
# 교통 모니터링 팀 — Blueprint 라우트 + MonitoringDetector 관리

import os
import time
import gevent
from flask import Blueprint, jsonify, request, current_app, Response

from modules.traffic.detectors.manager import detector_manager
from modules.monitoring.monitoring_detector import MonitoringDetector
from modules.monitoring import its_helper

# 동시 AI 모니터링 카메라 최대 개수 (YOLO 모델 동시 로드 한계)
MAX_CONCURRENT_MONITORS = 3

monitoring_bp = Blueprint('monitoring', __name__)

# Overpass 백그라운드 fetch 중복 방지 (현재 요청 중인 road_key 집합)
_geo_fetching: set = set()

# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

def _monitoring_key(camera_id: str) -> str:
    """detector_manager 키 이름 규칙: monitoring_{camera_id}"""
    return f"monitoring_{camera_id}"


def _get_monitoring_detector(camera_id: str):
    """camera_id에 해당하는 활성 MonitoringDetector 인스턴스를 반환한다."""
    key = _monitoring_key(camera_id)
    with detector_manager._lock:
        det = detector_manager.active_detectors.get(key)
    return det if isinstance(det, MonitoringDetector) else None


# ── 라우트 ────────────────────────────────────────────────────────────────

@monitoring_bp.route('/health', methods=['GET'])
def health():
    """기존 헬스체크 엔드포인트 유지."""
    return jsonify({"status": "ok", "module": "monitoring"}), 200


@monitoring_bp.route('/start', methods=['POST'])
def start():
    """
    MonitoringDetector 시작 (이미 실행 중이면 재사용).

    Body (JSON):
        camera_id  str   필수 — 프론트엔드 식별자 (예: "cam_001")
        url        str   필수 — RTSP / HLS 스트림 URL
        lat        float 선택 (기본 37.5)
        lng        float 선택 (기본 127.0)
        location   str   선택 — 위치 설명

    Returns:
        200  {"status": "ok",      "camera_id": ..., "message": ...}
        400  {"status": "error",   "message": ...}
    """
    data      = request.get_json(silent=True) or {}
    camera_id = data.get('camera_id', '').strip()
    url       = data.get('url', '').strip()

    if not camera_id:
        return jsonify({"status": "error", "message": "camera_id 필요"}), 400
    if not url:
        return jsonify({"status": "error", "message": "url 필요"}), 400

    lat      = float(data.get('lat',  37.5))
    lng      = float(data.get('lng', 127.0))
    location = data.get('location', '')

    socketio = current_app.extensions['socketio']
    app_obj  = current_app._get_current_object()
    from models import db as db_inst

    unique_name = _monitoring_key(camera_id)
    det = detector_manager.get_or_create(
        unique_name,
        MonitoringDetector,
        url       = url,
        camera_id = camera_id,
        lat       = lat,
        lng       = lng,
        location  = location,
        socketio  = socketio,
        db        = db_inst,
        app       = app_obj,
    )

    already = det is not None
    return jsonify({
        "status":    "ok",
        "camera_id": camera_id,
        "message":   "이미 실행 중" if already else "MonitoringDetector 시작됨",
    }), 200


@monitoring_bp.route('/stop', methods=['POST'])
def stop():
    """
    MonitoringDetector 중지.

    Body (JSON):
        camera_id  str  필수

    Returns:
        200  {"status": "ok"}
        404  {"status": "not_found"}
    """
    data      = request.get_json(silent=True) or {}
    camera_id = data.get('camera_id', '').strip()
    if not camera_id:
        return jsonify({"status": "error", "message": "camera_id 필요"}), 400

    key = _monitoring_key(camera_id)
    with detector_manager._lock:
        det = detector_manager.active_detectors.pop(key, None)
        detector_manager.threads.pop(key, None)

    if det is None:
        return jsonify({"status": "not_found"}), 404

    det.stop()
    return jsonify({"status": "ok", "camera_id": camera_id}), 200


@monitoring_bp.route('/cameras', methods=['GET'])
def cameras():
    """
    현재 활성 MonitoringDetector 목록 반환.

    Returns:
        200  {"cameras": [{"camera_id": ..., "is_running": ..., "is_learning": ..., "level": ...}, ...]}
    """
    result = []
    with detector_manager._lock:
        for key, det in detector_manager.active_detectors.items():
            if not isinstance(det, MonitoringDetector):
                continue
            level = "N/A"
            if det.traffic_analyzer_a and det.traffic_analyzer_b:
                level = det._worst_level()
            result.append({
                "camera_id":  det.camera_id,
                "location":   det.location,
                "lat":        det.lat,
                "lng":        det.lng,
                "is_running": det.is_running,
                "is_learning": det.state.is_learning,
                "relearning":  det.state.relearning,
                "level":      level,
            })
    return jsonify({"cameras": result}), 200


@monitoring_bp.route('/debug/<camera_id>', methods=['GET'])
def debug(camera_id):
    """
    MonitoringDetector 내부 상태를 반환하는 디버그 API (Step 1).

    Returns:
        200  det.debug_info 딕셔너리
        404  {"status": "not_found"}
    """
    det = _get_monitoring_detector(camera_id)
    if det is None:
        return jsonify({"status": "not_found",
                        "message": f"camera_id={camera_id} 활성 감지기 없음"}), 404
    return jsonify(det.debug_info), 200


@monitoring_bp.route('/video_feed/<camera_id>', methods=['GET'])
def video_feed(camera_id):
    """
    MJPEG 영상 스트리밍.
    프론트: <img src="/api/monitoring/video_feed/{camera_id}">

    Returns:
        200  multipart/x-mixed-replace MJPEG 스트림
        404  감지기 없음
    """
    det = _get_monitoring_detector(camera_id)
    if det is None:
        return jsonify({"status": "not_found"}), 404
    return Response(
        det.generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
    )


@monitoring_bp.route('/tracks/<camera_id>', methods=['GET'])
def tracks(camera_id):
    """
    현재 프레임의 차량 바운딩박스 목록 반환 (프론트 폴링용).

    Returns:
        200  [{"id": 42, "x1": 100, "y1": 200, "x2": 180, "y2": 300,
               "nm": 0.03, "is_wrongway": false}, ...]
        200  []  (감지기 없거나 학습 중인 경우)
    """
    det = _get_monitoring_detector(camera_id)
    if det is None:
        return jsonify([]), 200
    with det.frame_lock:
        data = list(det.latest_tracks_info)
    return jsonify(data), 200


@monitoring_bp.route('/action', methods=['POST'])
def action():
    """
    관제사 대응 조치 기록 — DB 저장 + Discord 알림 + Socket.IO emit.

    Body (JSON):
        camera_id   str  필수
        action_type str  필수  (예: "VSL_DOWN_100_80", "VMS_SLOW")
        acted_by    str  선택  (관리자 이름, 기본 "관리자")

    Returns:
        200  {"status": "ok", "action_id": N}
        400  필수 파라미터 누락
    """
    data        = request.get_json(silent=True) or {}
    camera_id   = data.get('camera_id',   '').strip()
    action_type = data.get('action_type', '').strip()
    acted_by    = data.get('acted_by',    '관리자').strip()

    if not camera_id or not action_type:
        return jsonify({"status": "error", "message": "camera_id, action_type 필요"}), 400

    # ── DB 저장 ──────────────────────────────────────────────
    from models import db as db_inst, MonitoringAction
    record = MonitoringAction(
        camera_id   = camera_id,
        action_type = action_type,
        acted_by    = acted_by,
    )
    db_inst.session.add(record)
    db_inst.session.commit()
    print(f"💾 [{camera_id}] 조치 기록: {action_type} by {acted_by}")

    # ── Discord 알림 ─────────────────────────────────────────
    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if webhook_url:
        try:
            from shared.discord_helper import send_discord_notification
            det      = _get_monitoring_detector(camera_id)
            location = det.location if det else camera_id
            send_discord_notification(
                webhook_url,
                f"교통 대응: {action_type}",
                location,
                None,
            )
        except Exception as e:
            print(f"⚠️ Discord 알림 실패: {e}")

    # ── Socket.IO log_action emit ────────────────────────────
    try:
        socketio = current_app.extensions['socketio']
        socketio.emit('log_action', {
            'camera_id':   camera_id,
            'action_type': action_type,
            'acted_by':    acted_by,
            'action_at':   record.action_at.isoformat(),
        })
    except Exception as e:
        print(f"⚠️ log_action emit 실패: {e}")

    return jsonify({"status": "ok", "action_id": record.id}), 200


# ── ITS 연동 라우트 ───────────────────────────────────────────────────────────

@monitoring_bp.route('/its/cctv', methods=['GET'])
def its_cctv():
    """
    ITS CCTV 목록 반환 (고속도로 키 기준).

    Query:
        road  str  'gyeongbu' | 'gyeongin' | 'seohae' | ...  (기본 'gyeongbu')

    Returns:
        200  {
               "road": "gyeongbu",
               "label": "경부고속도로",
               "ic_list": ["판교JC", "수원신갈IC", ...],
               "cameras": [{camera_id, name, url, lat, lng, ic_name, direction}, ...]
             }
    """
    road = request.args.get('road', 'gyeongbu').strip()
    cfg  = its_helper.ROAD_CONFIG.get(road)
    if not cfg:
        return jsonify({"status": "error", "message": f"지원하지 않는 road: {road}"}), 400

    cameras = its_helper.get_cctv_list(road)
    ic_list = its_helper.get_ic_list(road)

    return jsonify({
        "road":    road,
        "label":   cfg['label'],
        "ic_list": ic_list,
        "cameras": cameras,
    }), 200


@monitoring_bp.route('/its/road_geo', methods=['GET'])
def its_road_geo():
    """
    도로 선형 GeoJSON 반환 (Overpass OSM 기반, 캐시).
    캐시 히트 시 즉시 반환. 캐시 미스 시 백그라운드 요청 후 빈 GeoJSON 반환
    (프론트는 다음 폴링 또는 재요청 시 데이터를 받는다).

    Query:
        road  str  'gyeongbu' | ...  (기본 'gyeongbu')

    Returns:
        200  GeoJSON FeatureCollection
    """
    import time as _time
    road = request.args.get('road', 'gyeongbu').strip()
    if road not in its_helper.ROAD_CONFIG:
        return jsonify({"status": "error", "message": f"지원하지 않는 road: {road}"}), 400

    # 캐시 히트 → 즉시 반환
    cached = its_helper._geo_cache.get(road)
    if cached and cached['expires'] > _time.time():
        return jsonify(cached['data']), 200

    # 캐시 미스 → 백그라운드에서 Overpass 요청 (중복 스폰 방지)
    if road not in _geo_fetching:
        _geo_fetching.add(road)
        def _fetch_bg():
            its_helper.get_road_geometry(road)
            _geo_fetching.discard(road)
        gevent.spawn(_fetch_bg)

    # 프론트엔드에 빈 GeoJSON 즉시 반환 (도로 선 없이 먼저 렌더)
    return jsonify({'type': 'FeatureCollection', 'features': []}), 200


def _try_start_camera(cam, socketio, app_obj, db_inst):
    """
    단일 카메라 MonitoringDetector 시작.
    이미 실행 중이면 False 반환.
    스레드가 죽은 dead detector는 자동 정리 후 재시작.
    """
    camera_id   = cam['camera_id']
    unique_name = _monitoring_key(camera_id)
    with detector_manager._lock:
        existing        = detector_manager.active_detectors.get(unique_name)
        existing_thread = detector_manager.threads.get(unique_name)

    if existing and isinstance(existing, MonitoringDetector):
        # 스레드가 살아있으면 진짜 실행 중 → 스킵
        if existing_thread and existing_thread.is_alive():
            return False
        # 스레드가 죽었으면 dead detector → 정리 후 재시작
        print(f"♻️  [{camera_id}] dead detector 정리 후 재시작")
        with detector_manager._lock:
            detector_manager.active_detectors.pop(unique_name, None)
            detector_manager.threads.pop(unique_name, None)

    detector_manager.get_or_create(
        unique_name,
        MonitoringDetector,
        url      = cam['url'],
        camera_id= camera_id,
        lat      = cam['lat'],
        lng      = cam['lng'],
        location = cam['name'],
        socketio = socketio,
        db       = db_inst,
        app      = app_obj,
    )
    print(f"🚦 ITS 모니터링 시작: {camera_id}")
    return True


def _segment_queue_runner(pending_cams, socketio, app_obj, db_inst):
    """
    초기 배치 이후 남은 카메라를 큐로 관리하는 백그라운드 그린렛.
    학습 중인 카메라 수가 MAX_CONCURRENT_MONITORS 미만이 되면 다음 카메라를 순차 시작.
    """
    print(f"🗂️  ITS 큐 매니저 시작 — 대기 카메라: {len(pending_cams)}개")
    while pending_cams:
        with detector_manager._lock:
            learning_count = sum(
                1 for det in detector_manager.active_detectors.values()
                if isinstance(det, MonitoringDetector) and det.state.is_learning
            )

        free_slots = MAX_CONCURRENT_MONITORS - learning_count
        while free_slots > 0 and pending_cams:
            cam = pending_cams.pop(0)
            try:
                started = _try_start_camera(cam, socketio, app_obj, db_inst)
                if started:
                    free_slots -= 1
                    if pending_cams:
                        time.sleep(2)   # 순차 시작 딜레이 (monkey-patched → gevent.sleep)
            except Exception as e:
                print(f"⚠️ 큐 카메라 시작 실패 [{cam['camera_id']}]: {e}")

        if pending_cams:
            gevent.sleep(10)   # 10초 후 슬롯 재확인

    print(f"✅ ITS 구간 큐 처리 완료 — 모든 카메라 시작됨")


@monitoring_bp.route('/its/start_segment', methods=['POST'])
def its_start_segment():
    """
    IC 범위 내 CCTV 전체 MonitoringDetector 시작.
    MAX_CONCURRENT_MONITORS 초과분은 큐에 넣고 학습 슬롯이 열리면 자동 시작.

    Body (JSON):
        road      str  필수  'gyeongbu' | ...
        start_ic  str  필수  시작 IC 이름
        end_ic    str  필수  종료 IC 이름

    Returns:
        200  {"started": [...], "already_running": [...], "queued": [...], "count": N}
    """
    data     = request.get_json(silent=True) or {}
    road     = data.get('road',     '').strip()
    start_ic = data.get('start_ic', '').strip()
    end_ic   = data.get('end_ic',   '').strip()

    if not road or not start_ic or not end_ic:
        return jsonify({"status": "error", "message": "road, start_ic, end_ic 필요"}), 400

    cameras_in_range = its_helper.get_cameras_in_range(road, start_ic, end_ic)
    if not cameras_in_range:
        return jsonify({"status": "error", "message": "해당 범위 카메라 없음"}), 404

    socketio = current_app.extensions['socketio']
    app_obj  = current_app._get_current_object()
    from models import db as db_inst

    # 현재 학습 중인 MonitoringDetector 수
    with detector_manager._lock:
        learning_count = sum(
            1 for det in detector_manager.active_detectors.values()
            if isinstance(det, MonitoringDetector) and det.state.is_learning
        )

    started         = []
    already_running = []
    queued_cams     = []   # 슬롯 부족으로 큐에 들어간 카메라 config 목록

    for cam in cameras_in_range:
        camera_id   = cam['camera_id']
        unique_name = _monitoring_key(camera_id)

        with detector_manager._lock:
            existing = detector_manager.active_detectors.get(unique_name)
        if existing and isinstance(existing, MonitoringDetector):
            already_running.append(camera_id)
            continue

        # 학습 슬롯 여유 있으면 즉시 시작, 없으면 큐 대기
        if learning_count + len(started) < MAX_CONCURRENT_MONITORS:
            if started:
                time.sleep(2)
            try:
                _try_start_camera(cam, socketio, app_obj, db_inst)
                started.append(camera_id)
            except Exception as e:
                print(f"⚠️ MonitoringDetector 시작 실패 [{camera_id}]: {e}")
                queued_cams.append(cam)
        else:
            queued_cams.append(cam)

    # 큐에 남은 카메라를 백그라운드 그린렛이 자동 처리
    queued_ids = [c['camera_id'] for c in queued_cams]
    if queued_cams:
        gevent.spawn(_segment_queue_runner, list(queued_cams), socketio, app_obj, db_inst)

    msg_parts = []
    if started:         msg_parts.append(f"{len(started)}개 시작")
    if already_running: msg_parts.append(f"{len(already_running)}개 이미 실행 중")
    if queued_ids:      msg_parts.append(f"{len(queued_ids)}개 큐 대기 (학습 슬롯 확보 시 자동 시작)")

    return jsonify({
        "status":          "ok",
        "started":         started,
        "already_running": already_running,
        "queued":          queued_ids,
        "message":         " / ".join(msg_parts) if msg_parts else "변경 없음",
        "max_concurrent":  MAX_CONCURRENT_MONITORS,
        "count":           learning_count + len(started),
    }), 200


@monitoring_bp.route('/its/view_feed', methods=['GET'])
def its_view_feed():
    """
    ITS CCTV 보기 전용 MJPEG 프록시.
    브라우저에서 직접 ITS URL 접근 시 403이 발생하므로,
    백엔드가 OpenCV로 스트림을 열어 MJPEG로 변환해 제공한다.

    Query:
        camera_id  str  선택 — 이미 모니터링 중이면 해당 스트림 재사용
        url        str  선택 — 직접 ITS URL 지정 (camera_id 없을 때)

    Returns:
        200  multipart/x-mixed-replace MJPEG 스트림
        400  파라미터 없음
        403  허용되지 않은 URL
    """
    import cv2 as _cv2

    camera_id = request.args.get('camera_id', '').strip()
    url       = request.args.get('url', '').strip()

    # 이미 MonitoringDetector가 실행 중이면 해당 스트림 재사용 (자원 절약)
    if camera_id:
        det = _get_monitoring_detector(camera_id)
        if det is not None:
            return Response(
                det.generate_frames(),
                mimetype='multipart/x-mixed-replace; boundary=frame',
            )

    if not url:
        return jsonify({"error": "camera_id 또는 url 파라미터 필요"}), 400

    # 보안: ITS 공식 도메인만 허용
    _ALLOWED_DOMAINS = ('cctvsec.ktict.co.kr', 'openapi.its.go.kr', 'ktict.co.kr')
    if not any(d in url for d in _ALLOWED_DOMAINS):
        return jsonify({"error": "허용되지 않은 스트림 URL"}), 403

    def _generate_proxy():
        cap = _cv2.VideoCapture(url)
        if not cap.isOpened():
            return
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.1)
                    continue
                _, jpeg = _cv2.imencode(
                    '.jpg', frame, [_cv2.IMWRITE_JPEG_QUALITY, 65]
                )
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n'
                    + jpeg.tobytes()
                    + b'\r\n'
                )
        finally:
            cap.release()

    return Response(
        _generate_proxy(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
    )


@monitoring_bp.route('/its/stop_segment', methods=['POST'])
def its_stop_segment():
    """
    IC 범위 내 MonitoringDetector 전체 중지.

    Body (JSON):
        road      str  필수
        start_ic  str  필수
        end_ic    str  필수

    Returns:
        200  {"stopped": [...camera_ids], "not_found": [...]}
    """
    data     = request.get_json(silent=True) or {}
    road     = data.get('road',     '').strip()
    start_ic = data.get('start_ic', '').strip()
    end_ic   = data.get('end_ic',   '').strip()

    if not road or not start_ic or not end_ic:
        return jsonify({"status": "error", "message": "road, start_ic, end_ic 필요"}), 400

    cameras_in_range = its_helper.get_cameras_in_range(road, start_ic, end_ic)

    stopped   = []
    not_found = []

    for cam in cameras_in_range:
        camera_id   = cam['camera_id']
        unique_name = _monitoring_key(camera_id)

        with detector_manager._lock:
            det = detector_manager.active_detectors.pop(unique_name, None)
            detector_manager.threads.pop(unique_name, None)

        if det is None:
            not_found.append(camera_id)
        else:
            det.stop()
            stopped.append(camera_id)
            print(f"⏹️ ITS 구간 모니터링 중지: {camera_id}")

    return jsonify({
        "status":    "ok",
        "stopped":   stopped,
        "not_found": not_found,
    }), 200
