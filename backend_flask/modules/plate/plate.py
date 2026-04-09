# backend_flask/modules/plate/plate.py
# Blueprint + API 라우트만 담당
# 비즈니스 로직은 각 모듈에 위임

from flask import Blueprint, jsonify, Response, send_from_directory, request
import cv2
import numpy as np
import threading
import time
import os

from .state import state, state_lock, is_started, is_started_lock, TEST_DIR, SAVE_DIR
from .detector import process_video
from .preprocessor import apply as preprocess_apply, PREPROCESS_METHODS
from .db_manager import save_result, get_all_results, update_result, add_preprocess_result
from .state import OCR_ENGINE

if OCR_ENGINE == 'yolo':
    from .yolo_ocr_engine import ocr_worker, ocr_input_queue, run_ocr_once
else:
    from .ocr_engine import ocr_worker, ocr_input_queue, run_ocr_once

plate_bp = Blueprint('plate', __name__)

# 서버 시작 시 DB에서 전체기록 복원
def _restore_from_db():
    """서버 재시작 시 DB 데이터를 all_results에 복원"""
    rows = get_all_results()
    if not rows:
        return
    
    latest_data = {}

    # 인식 원본 행만 (전처리/정답 행 제외) — 중복 제거
    seen = set()
    restored = []
    base_rows = [r for r in rows if not r.get('전처리방법')]

    # 정답/전처리 결과를 번호판별로 인덱싱
    answered = {
        r.get('인식번호판'): {
            'ground_truth': r.get('정답번호판', ''),
            'is_correct': r.get('정오여부') == '정답',
        }
        for r in base_rows if r.get('정오여부') in ('정답', '오답')
    }
    preprocess_rows = [r for r in rows if r.get('전처리방법')]

    for r in reversed(base_rows):  # 오래된 것부터 → 최신이 앞에
        plate = r.get('인식번호판', '')
        vid   = os.path.basename(r.get('영상파일', ''))
        key   = f"{plate}_{vid}"
        if key in seen:
            continue
        seen.add(key)

        img_path = r.get('이미지경로', '')
        # 절대경로면 API URL로 변환
        if img_path and not img_path.startswith('/api'):
            basename = os.path.basename(img_path)
            img_path = f"/api/plate/image/{os.path.splitext(vid)[0]}/{basename}"

        # 전처리 결과 붙이기
        preps = [p for p in preprocess_rows
                 if p.get('인식번호판') == plate
                 and os.path.basename(p.get('영상파일', '')) == vid]
        preprocess_results = {
            p.get('전처리방법'): {
                'text':       p.get('보정후번호판', ''),
                'img_url':    f"/api/plate/image/{os.path.splitext(vid)[0]}/id_{p.get('전처리방법')}.jpg",
                'elapsed_ms': p.get('처리시간(ms)', ''),
                'correct':    bool(p.get('정답번호판') and
                                   p.get('보정후번호판') == p.get('정답번호판')),
            }
            for p in preps if p.get('전처리방법')
        }

        img_filename = '/'.join(img_path.split('/')[-2:]) if img_path else ''

        ans = answered.get(plate, {})
        restored.insert(0, {
            'id':                int(abs(hash(f"{plate}_{vid}")) % 100000),
            'text':              plate,
            'is_fixed':          r.get('확정여부') == '확정',
            'detected_at':       r.get('인식시각', '').split(' ')[-1],
            'img_url':           img_path,
            'img_filename':      img_filename,
            'ground_truth':      ans.get('ground_truth') or None,
            'is_correct':        ans.get('is_correct') if ans else None,
            'preprocess_results': preprocess_results,
            'video':             vid,
            'restored':          True,
        })

    with state_lock:
        state['all_results'] = restored
    print(f"📂 [plate] DB에서 {len(restored)}건 복원 완료")


# =====================
#      API 라우트
# =====================

@plate_bp.route('/health', methods=['GET'])
def health():
    # DB 연결 상태만 확인 (복원은 start에서만)
    try:
        from .db_manager import get_all_results
        results = get_all_results()
        return jsonify({"status": "ok", "module": "plate", "db_records": len(results)}), 200
    except Exception as e:
        return jsonify({"status": "error", "module": "plate", "error": str(e)}), 500


@plate_bp.route('/videos', methods=['GET'])
def get_videos():
    """test 폴더의 영상 파일 목록 반환"""
    try:
        files = [f for f in os.listdir(TEST_DIR)
                 if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))]
        return jsonify({"videos": sorted(files)}), 200
    except Exception as e:
        return jsonify({"videos": [], "error": str(e)}), 200


@plate_bp.route('/preprocess_methods', methods=['GET'])
def get_preprocess_methods():
    """지원하는 전처리 방법 목록 반환"""
    return jsonify({"methods": PREPROCESS_METHODS}), 200


# modules/plate/plate.py

@plate_bp.route('/start', methods=['POST'])
def start():
    """탭 진입 시 호출 — 영상 선택 후 스레드 시작"""
    global is_started
    import modules.plate.state as plate_state

    data = request.get_json() or {}
    video_filename = data.get('video')

    # 1. 기존 스레드 중지
    with state_lock:
        state['stop_thread'] = True
    
    time.sleep(0.3)

    # 2. 임시 데이터 및 전체 기록 리스트 완전 초기화
    with state_lock:
        state['plates'] = []
        state['plate_history_ids'] = []
        state['plate_history_texts'] = {}
        state['plate_votes'] = {}
        state['latest_frame'] = None
        
        # 이전 영상 찌꺼기가 남지 않게 무조건 비웁니다.
        state['all_results'] = [] 
        
        if video_filename:
            state['current_video'] = os.path.join(TEST_DIR, video_filename)
        
        state['stop_thread'] = False

    # 3. 🔥 핵심: 텅 빈 state['all_results']에 DB의 진짜 기록만 채워 넣습니다.
    # 주의: 데드락을 막기 위해 반드시 with state_lock 밖에서 호출해야 합니다.
    _restore_from_db()

    # 4. 스레드 재시작 (gevent 호환 방식)
    with plate_state.is_started_lock:
        try:
            from gevent import spawn
            # gevent spawn을 사용하여 스레드 생성
            spawn(ocr_worker)
            spawn(process_video)
            
            plate_state.is_started = True
            print(f"🔄 [plate] 영상 교체 및 DB 동기화 완료: {video_filename}")
        except Exception as e:
            print(f"❌ [plate] 스레드 시작 실패: {e}")
            plate_state.is_started = False
            return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "started"}), 200


@plate_bp.route('/stream')
def stream():
    """MJPEG 영상 스트리밍"""
    def generate():
        while True:
            with state_lock:
                frame = state['latest_frame']
            if frame is not None:
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' +
                           buffer.tobytes() + b'\r\n')
            time.sleep(0.03)

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')


@plate_bp.route('/plates', methods=['GET'])
def get_plates():
    """현재 화면 번호판 (최근 5개)"""
    with state_lock:
        return jsonify(state['plates']), 200


@plate_bp.route('/results', methods=['GET'])
def get_results():
    """누적 인식 결과 — 영상별 필터 지원"""
    video_filter = request.args.get('video', '')
    with state_lock:
        results = state['all_results']
        # 영상 목록 추출
        videos = sorted(set(
            r.get('video', '') for r in results if r.get('video')
        ))
        # 필터 적용
        if video_filter:
            results = [r for r in results if r.get('video') == video_filter]
    return jsonify({"results": results, "videos": videos}), 200


@plate_bp.route('/image/<path:filename>', methods=['GET'])
def plate_image(filename):
    """저장된 번호판 캡처 이미지 제공 (서브폴더 경로 지원)"""
    return send_from_directory(SAVE_DIR, filename)


@plate_bp.route('/verify', methods=['POST'])
def verify():
    """정답 입력 → 글자별 비교 후 상태 + CSV 업데이트"""
    data = request.get_json() or {}
    track_id = data.get('id')
    ground_truth = data.get('ground_truth', '').strip().replace(' ', '')

    if not track_id or not ground_truth:
        return jsonify({"error": "id, ground_truth 필요"}), 400

    with state_lock:
        result = next((r for r in state['all_results'] if r['id'] == track_id), None)
        if not result:
            return jsonify({"error": "결과 없음"}), 404

        recognized = result['text']
        is_correct = (recognized == ground_truth)

        # 글자별 비교
        char_diff = _compare_chars(recognized, ground_truth)

        result['ground_truth'] = ground_truth
        result['is_correct'] = is_correct
        result['char_diff'] = char_diff

    # 새 행 추가 대신 기존 행 업데이트
    video_filename = result.get('video', '') or os.path.basename(state.get('current_video', ''))
    update_result(
        plate_number=recognized,
        video_filename=video_filename,
        ground_truth=ground_truth,
        is_correct=is_correct,
    )

    return jsonify({
        "is_correct": is_correct,
        "char_diff": char_diff,
        "recognized": recognized,
        "ground_truth": ground_truth
    }), 200


@plate_bp.route('/reprocess', methods=['POST'])
def reprocess():
    """전처리 옵션 적용 후 재인식 — 누적 방식 (방법별 결과 모두 저장)"""
    data = request.get_json() or {}
    track_id = data.get('id')
    preprocess = data.get('preprocess', 'clahe')

    if not track_id:
        return jsonify({"error": "id 필요"}), 400

    with state_lock:
        result = next((r for r in state['all_results'] if r['id'] == track_id), None)
        if not result:
            return jsonify({"error": "결과 없음"}), 404
        img_filename = result.get('img_filename', '')

    img_path = os.path.join(SAVE_DIR, img_filename)
    if not os.path.exists(img_path):
        return jsonify({"error": "이미지 없음"}), 404

    # 전처리 적용
    img = cv2.imread(img_path)
    processed = preprocess_apply(img, preprocess)

    # 전처리 이미지를 원본과 같은 서브폴더에 저장
    img_dir = os.path.dirname(img_filename)  # test06 or ''
    proc_basename = f"id_{track_id}_proc_{preprocess}.jpg"
    proc_filename = os.path.join(img_dir, proc_basename) if img_dir else proc_basename
    proc_path = os.path.join(SAVE_DIR, proc_filename)
    cv2.imwrite(proc_path, processed)

    # OCR 재인식
    try:
        start_t = time.time()
        retried_text = run_ocr_once(processed)
        elapsed_ms = round((time.time() - start_t) * 1000, 1)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    ground_truth = result.get('ground_truth')
    retry_correct = (retried_text == ground_truth) if ground_truth else None

    # --- 누적 방식: preprocess_results 딕셔너리에 방법별로 저장 ---
    with state_lock:
        if 'preprocess_results' not in result:
            result['preprocess_results'] = {}

        result['preprocess_results'][preprocess] = {
            'text': retried_text,
            'img_url': f"/api/plate/image/{proc_filename}",
            'elapsed_ms': elapsed_ms,
            'correct': retry_correct,
        }

    video_filename = result.get('video', '') or os.path.basename(state.get('current_video', ''))
    add_preprocess_result(
        plate_number=result['text'],
        video_filename=video_filename,
        preprocess=preprocess,
        retried_text=retried_text,
        elapsed_ms=elapsed_ms,
        ground_truth=ground_truth,
        is_correct=retry_correct,
        img_path=f"/api/plate/image/{proc_filename}",
    )

    return jsonify({
        "preprocess": preprocess,
        "retried_text": retried_text,
        "proc_img_url": f"/api/plate/image/{proc_filename}",
        "elapsed_ms": elapsed_ms,
        "retry_correct": retry_correct,
        "preprocess_results": result.get('preprocess_results', {}),
    }), 200


def _compare_chars(recognized: str, ground_truth: str) -> list:
    """글자별 정오 비교 결과 생성"""
    max_len = max(len(recognized), len(ground_truth))
    return [
        {
            'recognized': recognized[i] if i < len(recognized) else '_',
            'ground_truth': ground_truth[i] if i < len(ground_truth) else '_',
            'correct': (recognized[i] if i < len(recognized) else '_') ==
                       (ground_truth[i] if i < len(ground_truth) else '_')
        }
        for i in range(max_len)
    ]


@plate_bp.route('/analytics', methods=['GET'])
def analytics():
    """CSV 기반 분석 데이터 반환 — 로직은 analytics.py에 위임"""
    from .analytics import get_analytics
    result = get_analytics(
        video_filter  = request.args.get('video', ''),
        status_filter = request.args.get('status', ''),
        search        = request.args.get('search', '').strip(),
    )
    return jsonify(result), 200