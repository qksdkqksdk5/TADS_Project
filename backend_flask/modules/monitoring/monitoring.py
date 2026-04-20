# backend_flask/modules/monitoring/monitoring.py
# 교통 모니터링 팀 — Blueprint 라우트 + MonitoringDetector 관리

import os
import time
import gevent
from datetime import datetime, timezone  # diagnostics 엔드포인트의 시각 계산에 필요
from flask import Blueprint, jsonify, request, current_app, Response

from modules.traffic.detectors.manager import detector_manager
from modules.monitoring.monitoring_detector import MonitoringDetector, _FRAME_POOL
from modules.monitoring import its_helper

# 동시 AI 모니터링 카메라 최대 개수 (YOLO 모델 동시 로드 한계)
MAX_CONCURRENT_MONITORS = 3

monitoring_bp = Blueprint('monitoring', __name__)

# Overpass 백그라운드 fetch 중복 방지 (현재 요청 중인 road_key 집합)
_geo_fetching: set = set()

# 구간 큐 러너 greenlet 추적 (stop 시 kill용)
# key: (road, start_ic, end_ic) → gevent.Greenlet
_queue_greenlets: dict = {}

# ── 탭 이탈 시 일시정지 설정 ────────────────────────────────────────────────
# ┌─────────────────────────────────────────────────────────────────────────┐
# │  PERSIST_MODE = False  ← 기본값: 탭 이탈 시 AI 추론 자동 일시정지       │
# │  PERSIST_MODE = True   ← 탭 이동해도 AI 추론 계속 실행 (항상 유지 모드)  │
# └─────────────────────────────────────────────────────────────────────────┘
PERSIST_MODE: bool = False

# 현재 모니터링 탭을 열고 있는 소켓 SID 집합
# monitoring_join 이벤트 수신 시 추가, disconnect 시 제거
_monitoring_sids: set = set()


# ── 일괄 일시정지 / 재개 헬퍼 ────────────────────────────────────────────────

def _pause_all_monitoring():
    """
    현재 활성화된 모든 MonitoringDetector 를 일시정지한다.
    YOLO 추론/emit 루프만 멈추고 학습 완료 상태(모델 가중치)는 메모리에 유지된다.
    monitoring_ 접두사 키만 대상으로 하여 타 팀 감지기에는 영향을 주지 않는다.
    """
    with detector_manager._lock:
        # active_detectors 에서 MonitoringDetector 인스턴스만 추출
        targets = [
            det for key, det in detector_manager.active_detectors.items()
            if key.startswith('monitoring_') and isinstance(det, MonitoringDetector)
        ]
    for det in targets:
        det.pause()  # 각 감지기에 일시정지 신호 전달
    if targets:
        print(f"⏸️  [monitoring] {len(targets)}개 감지기 일시정지 완료")


def _resume_all_monitoring():
    """
    일시정지된 모든 MonitoringDetector 를 재개한다.
    학습 완료 상태가 그대로 유지된 채로 추론이 이어진다.
    monitoring_ 접두사 키만 대상으로 하여 타 팀 감지기에는 영향을 주지 않는다.
    """
    with detector_manager._lock:
        targets = [
            det for key, det in detector_manager.active_detectors.items()
            if key.startswith('monitoring_') and isinstance(det, MonitoringDetector)
        ]
    for det in targets:
        det.resume()  # 각 감지기에 재개 신호 전달
    if targets:
        print(f"▶️  [monitoring] {len(targets)}개 감지기 재개 완료")


# ── Socket.IO 이벤트 핸들러 등록 함수 ────────────────────────────────────────

def register_monitoring_socket_events(socketio):
    """
    app.py 에서 호출: monitoring 탭 진입/이탈 소켓 이벤트 핸들러를 등록한다.

    이벤트 흐름:
      프론트 탭 진입 → emit('monitoring_join') → 일시정지 감지기 재개
      프론트 탭 이탈 → 소켓 자동 해제 → disconnect 이벤트 → 마지막 클라이언트면 일시정지

    Parameters
    ----------
    socketio : flask_socketio.SocketIO
        app.py 에서 생성한 SocketIO 인스턴스
    """

    @socketio.on('monitoring_join')
    def on_monitoring_join():
        """
        프론트엔드 모니터링 탭 진입 시 수신.
        SID 를 _monitoring_sids 에 등록하고,
        이전에 일시정지된 감지기가 있으면 모두 재개한다.
        """
        from flask import request as req  # gevent 환경에서 request context 안전하게 접근
        sid = req.sid
        _monitoring_sids.add(sid)  # 이 소켓을 monitoring 클라이언트로 등록
        print(f"🟢 [monitoring] 탭 진입 SID={sid} (연결 수: {len(_monitoring_sids)})")
        # 일시정지 상태인 감지기가 있으면 재개
        _resume_all_monitoring()

    @socketio.on('disconnect')
    def on_monitoring_disconnect():
        """
        소켓 연결 해제 시 수신 (모든 소켓에 대해 발동).
        monitoring 탭 SID 가 아니면 즉시 반환하여 타 팀 소켓에 영향을 주지 않는다.
        마지막 monitoring 클라이언트가 끊어지고 PERSIST_MODE=False 이면 전체 일시정지.
        """
        from flask import request as req
        sid = req.sid

        # monitoring 탭 사용자가 아닌 소켓 disconnect → 아무것도 하지 않음
        if sid not in _monitoring_sids:
            return

        _monitoring_sids.discard(sid)  # SID 제거
        print(f"🔴 [monitoring] 탭 이탈 SID={sid} (남은 연결: {len(_monitoring_sids)})")

        # 마지막 클라이언트가 떠났고 PERSIST_MODE=False 이면 일시정지
        if not _monitoring_sids and not PERSIST_MODE:
            _pause_all_monitoring()

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


@monitoring_bp.route('/diagnostics', methods=['GET'])
def diagnostics():
    """
    모든 MonitoringDetector 의 실시간 진단 정보 반환.

    블랙아웃·스트림 타임아웃 원인 추적용 엔드포인트.
    브라우저에서 GET /api/monitoring/diagnostics 로 직접 조회 가능.

    응답 필드 해석:
        read_max_ms >= 29000  → FFMPEG 30초 타임아웃 발생 확인 (이벤트 루프 차단 위험)
        reconnect_count 큰 값 → 해당 카메라 스트림이 반복 끊김
        last_frame_age_s 큰 값 → 프레임 공급이 멈춘 카메라 (블랙아웃 원인 후보)
        is_paused = true       → 일시정지 상태 (탭 이탈)

    Returns:
        200  {
               "pool_maxsize": 16,
               "detectors": [
                 {
                   "camera_id": ...,
                   "is_running": ...,
                   "is_paused": ...,
                   "frame_num": ...,
                   "read_last_ms": ...,
                   "read_max_ms": ...,
                   "reconnect_count": ...,
                   "reconnect_last_at": ...,
                   "last_frame_ok_at": ...,
                   "last_frame_age_s": ...,   ← 마지막 정상 프레임 이후 경과 초
                 }, ...
               ]
             }
    """
    import time as _time

    result = []
    with detector_manager._lock:
        items = list(detector_manager.active_detectors.items())

    for key, det in items:
        if not isinstance(det, MonitoringDetector):
            continue  # 타 팀 감지기 제외

        diag = getattr(det, '_diag', {})

        # 마지막 정상 프레임 수신 이후 경과 시간 계산
        last_ok = diag.get('last_frame_ok_at')
        if last_ok:
            last_ok_dt = datetime.fromisoformat(last_ok)
            age_s = round((_time.time() - last_ok_dt.replace(tzinfo=timezone.utc).timestamp()), 1)
        else:
            age_s = None  # 아직 프레임 수신 전

        result.append({
            'camera_id':        det.camera_id,
            'location':         getattr(det, 'location', ''),
            'is_running':       det.is_running,
            'is_paused':        getattr(det, '_paused', False),
            'frame_num':        det.state.frame_num if det.state else 0,
            'read_last_ms':     diag.get('read_last_ms', 0),
            'read_max_ms':      diag.get('read_max_ms', 0),    # ← 29000+ 이면 타임아웃
            'reconnect_count':  diag.get('reconnect_count', 0),
            'reconnect_last_at': diag.get('reconnect_last_at'),
            'last_frame_ok_at': last_ok,
            'last_frame_age_s': age_s,  # ← 이 값이 큰 카메라가 블랙아웃 원인
        })

    # read_max_ms 내림차순 정렬 → 타임아웃 의심 카메라를 맨 위로
    result.sort(key=lambda x: x['read_max_ms'], reverse=True)

    return jsonify({
        'pool_maxsize': 16,             # _FRAME_POOL 최대 동시 스레드 수
        'detector_count': len(result),
        'detectors': result,
    }), 200


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
    도로 선형 GeoJSON 반환 (Overpass OSM 기반, 3단계 캐시).

    캐시 전략:
      1. 성공 메모리 캐시 히트 → 즉시 반환 (is_failure=True 캐시는 건너뜀)
      2. 캐시 미스 or 실패 캐시 → 백그라운드 greenlet으로 Overpass 요청
         (중복 스폰 방지: _geo_fetching 집합으로 관리)
      3. Overpass 성공 시 → road_geo_ready Socket.IO emit (프론트 즉시 갱신)

    프론트엔드는 이 엔드포인트 호출 후:
      - 이미 캐시된 데이터가 있으면 즉시 도로선 렌더링
      - 없으면 road_geo_ready 이벤트 수신 시 렌더링 (폴링 불필요)

    Query:
        road  str  'gyeongbu' | ...  (기본 'gyeongbu')

    Returns:
        200  GeoJSON FeatureCollection (성공 캐시 또는 빈 FeatureCollection)
    """
    import time as _time
    road = request.args.get('road', 'gyeongbu').strip()
    if road not in its_helper.ROAD_CONFIG:
        return jsonify({"status": "error", "message": f"지원하지 않는 road: {road}"}), 400

    # ── 성공 캐시 히트 → 즉시 반환 ────────────────────────────────────────
    # is_failure=True 인 실패 캐시는 여기서 건너뛰고 background retry로 진행
    # (기존 로직은 실패 캐시도 즉시 반환해 background fetch를 막았던 버그)
    cached = its_helper._geo_cache.get(road)
    if cached and cached['expires'] > _time.time() and not cached.get('is_failure'):
        return jsonify(cached['data']), 200

    # ── 캐시 미스 or 실패 캐시 → background greenlet 스폰 ─────────────────
    if road not in _geo_fetching:
        _geo_fetching.add(road)

        # request context 바깥(greenlet)에서 사용할 socketio 인스턴스를 미리 캡처
        # current_app.extensions['socketio']는 실제 SocketIO 객체이므로
        # 클로저로 캡처해도 greenlet 내에서 안전하게 emit 가능
        socketio = current_app.extensions['socketio']

        def _fetch_bg():
            """Overpass 요청 후 성공 시 road_geo_ready 이벤트 전파."""
            geo = its_helper.get_road_geometry(road)   # 파일/메모리/Overpass 3단계 시도
            _geo_fetching.discard(road)                 # 완료 후 fetching 플래그 해제
            if geo.get('features'):                     # 성공(features 있음) 시에만 emit
                # 모든 연결된 프론트엔드 클라이언트에 도로 선형 데이터 푸시
                # → 폴링 없이 즉시 지도에 도로선 반영
                socketio.emit('road_geo_ready', {
                    'road': road,   # 어느 도로인지 프론트가 구분할 수 있도록 포함
                    'geo':  geo,    # GeoJSON FeatureCollection 전체
                })
                print(f"📡 road_geo_ready emit ({road}): "
                      f"{len(geo['features'])}개 way → 모든 클라이언트")

        gevent.spawn(_fetch_bg)

    # ── 즉시 빈 GeoJSON 반환 ───────────────────────────────────────────────
    # 프론트엔드는 이것을 받아 지도 초기화를 진행하고,
    # road_geo_ready Socket.IO 이벤트를 수신하면 도로선을 추가 렌더링한다.
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

    # TTL(60초) 기반 캐시를 그대로 사용한다.
    # 강제 무효화는 프론트엔드가 보유한 세션 토큰과 다른 신규 토큰을 발급받게 되어
    # 오히려 스트림 열기 실패를 유발할 수 있으므로 제거한다.
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
    seg_key = (road, start_ic, end_ic)
    if queued_cams:
        # 이전 큐 러너가 있으면 kill 후 새로 시작
        old_g = _queue_greenlets.pop(seg_key, None)
        if old_g and not old_g.dead:
            old_g.kill()
        g = gevent.spawn(_segment_queue_runner, list(queued_cams), socketio, app_obj, db_inst)
        _queue_greenlets[seg_key] = g

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
        # ITS 공식 스트림 URL을 직접 열어 MJPEG 프록시로 중계하는 제너레이터
        cap = _cv2.VideoCapture(url)
        if not cap.isOpened():
            return  # 스트림 열기 실패 시 즉시 종료

        # 20fps 상한: 한 프레임 처리에 소요할 최소 간격 (초)
        _TARGET_INTERVAL = 1.0 / 20

        try:
            while True:
                # cap.read()는 C 레벨 블로킹 호출 → gevent 스레드풀에서 실행해
                # 이벤트 루프(소켓 하트비트·폴링 등)가 멈추지 않도록 한다
                ret, frame = _FRAME_POOL.apply(cap.read)

                if not ret:
                    # 프레임 읽기 실패 시 gevent.sleep으로 양보 (time.sleep은 greenlet 블로킹)
                    gevent.sleep(0.1)
                    continue

                # JPEG 인코딩 (품질 65 → 용량·속도 균형)
                _, jpeg = _cv2.imencode(
                    '.jpg', frame, [_cv2.IMWRITE_JPEG_QUALITY, 65]
                )

                # MJPEG multipart 경계 포맷으로 전송
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n'
                    + jpeg.tobytes()
                    + b'\r\n'
                )

                # 20fps 상한: gevent.sleep으로 다른 greenlet에 제어권 양보
                gevent.sleep(_TARGET_INTERVAL)
        finally:
            cap.release()  # 스트림 종료 시 반드시 캡처 해제

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

    # 해당 구간 큐 러너가 살아있으면 kill (재시작 방지)
    seg_key = (road, start_ic, end_ic)
    old_g = _queue_greenlets.pop(seg_key, None)
    if old_g and not old_g.dead:
        old_g.kill()
        print(f"⏹️ 구간 큐 러너 취소: {road} {start_ic}→{end_ic}")

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


# ── 스트림 URL 수동 탐침 API ─────────────────────────────────────────────────

@monitoring_bp.route('/its/probe_stream', methods=['GET'])
def its_probe_stream():
    """
    ITS CCTV 스트림 URL 을 HTTP 수준에서 탐침해 진단 결과를 반환한다.
    cv2.VideoCapture 가 실패하는 카메라의 원인을 파악할 때 사용한다.

    Query:
        url        str  선택 — 직접 탐침할 ITS URL
        camera_id  str  선택 — 캐시에서 URL 을 조회해 탐침 (url 대신 사용 가능)

    Returns:
        200  {
               url, http_status, content_type, stream_format,
               first_bytes_hex, first_bytes_ascii,
               diagnosis,         ← 케이스 설명 문자열
               [http_error]       ← HTTP 연결 실패 시만 포함
             }
        400  파라미터 없음
        403  허용되지 않은 도메인

    사용 예:
        GET /api/monitoring/its/probe_stream?url=http://cctvsec.ktict.co.kr/3035/...
        GET /api/monitoring/its/probe_stream?camera_id=gyeongbu_...노포교...
    """
    url       = request.args.get('url',       '').strip()
    camera_id = request.args.get('camera_id', '').strip()

    # camera_id 로 요청한 경우 캐시에서 URL 조회
    if camera_id and not url:
        # 모든 도로 캐시에서 camera_id 가 일치하는 항목 탐색
        for road_key in its_helper.ROAD_CONFIG:
            cameras = its_helper.get_cctv_list(road_key)
            for cam in cameras:
                if cam['camera_id'] == camera_id:
                    url = cam['url']
                    break
            if url:
                break

    if not url:
        return jsonify({"error": "url 또는 camera_id 파라미터 필요"}), 400

    # 보안: ITS 공식 도메인만 허용
    _ALLOWED = ('cctvsec.ktict.co.kr', 'openapi.its.go.kr', 'ktict.co.kr')
    if not any(d in url for d in _ALLOWED):
        return jsonify({"error": "허용되지 않은 도메인"}), 403

    # HTTP 탐침 실행
    probe = its_helper.probe_stream_url(url)

    # 탐침 결과를 케이스 진단 문자열로 변환
    if 'http_error' in probe:
        diagnosis = f"케이스 A: HTTP 접근 불가 — {probe['http_error']}"
    else:
        status = probe.get('http_status', 0)
        fmt    = probe.get('stream_format', 'unknown')
        if status in (401, 403):
            diagnosis = f"케이스 B: 인증 실패 / 토큰 만료 (HTTP {status})"
        elif status == 404:
            diagnosis = "케이스 B: 카메라 URL 없음 (HTTP 404)"
        elif status == 200 and fmt == 'm3u8':
            diagnosis = "케이스 C: HLS m3u8 확인 — FFMPEG 가 플레이리스트를 파싱해야 함"
        elif status == 200 and fmt == 'mpegts':
            diagnosis = "케이스 D: MPEG-TS 직접 스트림 확인 — cv2 백엔드 설정 문제 가능성"
        elif status == 200:
            diagnosis = f"케이스 D (포맷 미확인): HTTP 200 이지만 cv2 열기 실패 — 포맷: {fmt}"
        else:
            diagnosis = f"케이스 미확인: HTTP {status}"

    probe['diagnosis'] = diagnosis
    return jsonify(probe), 200


# ── 도로 전체 카메라 일괄 탐침 API ───────────────────────────────────────────

@monitoring_bp.route('/its/probe_batch', methods=['GET'])
def its_probe_batch():
    """
    특정 도로(또는 구간)의 전체 카메라를 한 번에 HTTP 탐침해
    stream_format 패턴과 카메라별 결과를 반환한다.

    단일 카메라가 아닌 여러 카메라에서 동일 현상이 반복될 때
    원인 패턴(토큰 만료 / HLS / MPEG-TS 등)을 빠르게 파악하기 위한 엔드포인트.

    Query:
        road      str  필수  'gyeongbu' | 'gyeongin' | 'seohae' | 'jungang' | 'youngdong'
        start_ic  str  선택  구간 시작 IC (생략 시 도로 전체 조회)
        end_ic    str  선택  구간 종료 IC (start_ic 와 함께 사용)

    Returns:
        200  {
               road:    str,
               total:   int,
               summary: { 'mpegts': N, 'm3u8': N, 'unknown': N, 'error': N },
               cameras: [
                 {
                   camera_id, name, url,
                   http_status, content_type, stream_format,
                   first_bytes_hex, first_bytes_ascii,
                   diagnosis,
                   [http_error]   ← 접속 실패 시만
                 },
                 ...
               ]
             }
        400  road 파라미터 없음 또는 잘못된 도로명
        404  해당 구간 카메라 없음

    사용 예:
        GET /api/monitoring/its/probe_batch?road=gyeongbu
        GET /api/monitoring/its/probe_batch?road=gyeongbu&start_ic=노포IC&end_ic=부산IC
    """
    road     = request.args.get('road',     '').strip()
    start_ic = request.args.get('start_ic', '').strip()
    end_ic   = request.args.get('end_ic',   '').strip()

    if not road:
        return jsonify({"error": "road 파라미터 필요"}), 400
    if road not in its_helper.ROAD_CONFIG:
        return jsonify({
            "error": f"알 수 없는 도로: '{road}'",
            "available": list(its_helper.ROAD_CONFIG.keys()),
        }), 400

    # 구간 지정 시 해당 구간만, 없으면 도로 전체 카메라 조회
    if start_ic and end_ic:
        cameras = its_helper.get_cameras_in_range(road, start_ic, end_ic)
    else:
        cameras = its_helper.get_cctv_list(road)

    if not cameras:
        return jsonify({"error": "해당 조건에 해당하는 카메라 없음"}), 404

    # 일괄 탐침 실행 (카메라 수에 따라 수 초 소요될 수 있음)
    result = its_helper.probe_batch(cameras)
    result['road'] = road   # 요청한 도로명도 응답에 포함

    return jsonify(result), 200
