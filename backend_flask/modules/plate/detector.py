import os

os.environ["OMP_NUM_THREADS"] = "2"
os.environ["OPENVINO_NUM_THREADS"] = "2"
os.environ["KMP_BLOCKTIME"] = "1"

import uuid
import queue
import threading
import cv2
import re
import time
from datetime import datetime
from collections import Counter
from ultralytics import YOLO

from .state import (
    state, state_lock,
    MODEL_PATH, SAVE_DIR,
    ROI_TOP, ROI_BOTTOM, YOLO_IMG_SIZE,
    DISPLAY_W, DISPLAY_H,
    VOTE_THRESHOLD,
    PAD, CONF, HISTORY_MAX,
)
from .db_manager import delete_by_video, save_result, update_result
from .state import OCR_ENGINE

if OCR_ENGINE == 'yolo':
    from .yolo_ocr_engine import ocr_input_queue, ocr_result_queue
else:
    from .ocr_engine import ocr_input_queue, ocr_result_queue

plate_pattern = re.compile(r'^([가-힣]{1,2})?\d{2,3}[가-힣]\d{4}$')
os.makedirs(SAVE_DIR, exist_ok=True)

_shared_alpr_model = None
_alpr_model_lock   = threading.Lock()

# ── IO 워커 ───────────────────────────────────────────────────────────────────
# 워커는 프로세스 종료 시까지 계속 살아있음 (영상 전환해도 재시작 안 함)
# 토큰이 다르면 이전 영상의 작업을 스킵 → 새 영상 DB에 섞이지 않음
io_queue             = queue.Queue(maxsize=200)
_current_video_token = None
_video_token_lock    = threading.Lock()

# review01
def _io_worker():
    print("👷 [IO Worker] 시작")
    while True:
        task = io_queue.get()
        if task is None:  # 프로세스 종료 시에만 보내는 신호
            print("👷 [IO Worker] 종료")
            io_queue.task_done()
            break
        try:
            img_path, plate_img, db_func, db_params, token = task

            # 토큰이 다르면 이전 영상 작업 → 스킵
            with _video_token_lock:
                valid = (token == _current_video_token)

            if not valid:
                print(f"⚠️ [IO Worker] 구버전 작업 스킵")
            else:
                os.makedirs(os.path.dirname(img_path), exist_ok=True)
                cv2.imwrite(img_path, plate_img)
                db_func(**db_params)

        except Exception as e:
            print(f"❌ [IO Worker] {e}")
        finally:
            io_queue.task_done()


# 프로세스 시작 시 1회만 실행
threading.Thread(target=_io_worker, daemon=True, name="IOWorker").start()


# ── ALPR 모델 ─────────────────────────────────────────────────────────────────
def get_shared_alpr_model():
    global _shared_alpr_model
    if _shared_alpr_model is None:
        with _alpr_model_lock:
            if _shared_alpr_model is None:
                print(f"📦 [System] ALPR YOLO 모델 최초 1회 로드 중... ({MODEL_PATH})")
                _shared_alpr_model = YOLO(MODEL_PATH, task='detect')
    return _shared_alpr_model


def _yolo_track(model, frame, conf, img_size):
    return model.track(
        source=frame, conf=conf,
        persist=True, verbose=False, imgsz=img_size
    )


# ── 메인 영상 처리 ────────────────────────────────────────────────────────────
def process_video():
    global _current_video_token

    # review02
    # ✅ 새 토큰 발급 → 이전 영상의 큐 작업 자동 무효화
    my_token = str(uuid.uuid4())
    with _video_token_lock:
        _current_video_token = my_token
    print(f"🚀 영상 처리 스레드 시작 (token={my_token[:8]})")

    model = get_shared_alpr_model()

    with state_lock:
        video_path = state['current_video']
        state['stop_thread'] = False

    if not video_path or not os.path.exists(video_path):
        print(f"❌ 영상 파일 없음: {video_path}")
        return

    video_filename  = os.path.basename(video_path)
    video_subfolder = os.path.splitext(video_filename)[0]
    video_save_dir  = os.path.join(SAVE_DIR, video_subfolder)
    os.makedirs(video_save_dir, exist_ok=True)

    delete_by_video(video_filename)
    with state_lock:
        state['plates'] = []
        state['all_results'] = [
            r for r in state['all_results']
            if os.path.basename(str(r.get('video', ''))) != video_filename
        ]
    print(f"🗑️ [{video_filename}] state 초기화 완료")

    best_samples        = {}
    plate_history_ids   = []
    plate_history_imgs  = {}
    plate_history_texts = {}
    plate_votes         = {}
    queued_ids          = set()
    plate_img_urls      = {}
    saved_first         = set()
    saved_fixed         = set()
    plate_confs         = {}
    start_times         = {}

    cap            = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
    video_fps      = cap.get(cv2.CAP_PROP_FPS) or 30
    frame_interval = 1.0 / video_fps
    frame_count    = 0
    fps_buf        = []

    try:
        while True:
            with state_lock:
                if state.get('stop_thread', False): break

            ret, frame = cap.read()
            if not ret: break

            h_f, w_f    = frame.shape[:2]
            frame_count += 1
            t0          = time.time()

            #review03 - YOLO 모델 추론 → 트래킹 결과에서 ROI 내에 있는 ID만 OCR 입력 큐에 등록
            results   = model.track(frame, conf=CONF, imgsz=YOLO_IMG_SIZE, persist=True, verbose=False, device='cpu')
            annotated = frame.copy()

            if results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
                ids   = results[0].boxes.id.cpu().numpy().astype(int)
                confs = results[0].boxes.conf.cpu().numpy()

                for box, tid, conf in zip(boxes, ids, confs):
                    x1, y1, x2, y2 = box
                    is_fixed = best_samples.get(tid, {}).get('is_fixed', False)
                    color    = (0, 255, 0) if is_fixed else (255, 165, 0)
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                    center_y = (y1 + y2) / 2
                    #review04 - ROI 내에 있고, 아직 큐에 등록 안 된 ID만 → OCR 입력 큐에 등록
                    if int(h_f * ROI_TOP) < center_y < int(h_f * ROI_BOTTOM) and not is_fixed:
                        if tid not in queued_ids and not ocr_input_queue.full():
                            crop = frame[max(0,y1-PAD):min(h_f,y2+PAD), max(0,x1-PAD):min(w_f,x2+PAD)]
                            if crop.size > 0:
                                ocr_input_queue.put((tid, crop.copy()))
                                queued_ids.add(tid)
                                start_times[tid] = time.time()
                                plate_confs[tid]  = conf

            while not ocr_result_queue.empty():
                try:
                    tid, p_img, p_text = ocr_result_queue.get_nowait()
                    queued_ids.discard(tid)
                except:
                    break

                if p_text is None or p_img is None:
                    continue
                if plate_pattern.match(p_text):
                    if tid not in plate_votes: plate_votes[tid] = []
                    #review05 - 같은 ID에 대한 텍스트가 여러 번 나온 결과가 임계값을 넘으면 → 확정으로 간주
                    plate_votes[tid].append(p_text)
                    vote_counter      = Counter(plate_votes[tid])
                    voted_text, count = vote_counter.most_common(1)[0]
                    is_now_fixed      = count >= VOTE_THRESHOLD
                    candidates        = [{'text': k, 'count': v} for k, v in vote_counter.most_common()]
                    elapsed_ms        = int((time.time() - start_times.get(tid, time.time())) * 1000)
                    current_conf      = plate_confs.get(tid, 0.0)

                    best_samples[tid]        = {'is_fixed': is_now_fixed}
                    plate_history_texts[tid] = voted_text

                    if tid in plate_history_ids: plate_history_ids.remove(tid)
                    plate_history_ids.insert(0, tid)
                    plate_history_imgs[tid] = cv2.resize(p_img, (400, 110))

                    img_url = _save_and_sync_ui(
                        tid, p_img, voted_text, is_now_fixed,
                        video_filename, video_save_dir,
                        saved_first, saved_fixed,
                        conf=current_conf, vote_count=count, elapsed=elapsed_ms,
                        operator_name=state.get('operator_name'),
                        candidates=candidates,
                        token=my_token,
                    )
                    if img_url: plate_img_urls[tid] = img_url

            resized = cv2.resize(annotated, (DISPLAY_W, DISPLAY_H))
            with state_lock:
                state['latest_frame'] = resized
                state['plates'] = [
                    {
                        'id':         int(t_id),
                        'text':       plate_history_texts.get(t_id, '인식 중...'),
                        'is_fixed':   best_samples.get(t_id, {}).get('is_fixed', False),
                        'vote_count': len(plate_votes.get(t_id, [])),
                        'img_url':    plate_img_urls.get(t_id),
                    } for t_id in plate_history_ids
                ]

            fps_buf.append(time.time() - t0)
            time.sleep(max(0.01, frame_interval - (time.time() - t0)))

    finally:
        cap.release()
        # ✅ 워커는 죽이지 않음 — 다음 영상에서도 계속 사용
        ocr_input_queue.put(None)
        print(f"🏁 [plate] process_video 종료 (token={my_token[:8]})")


# ── UI 동기화 + IO 큐 등록 ────────────────────────────────────────────────────
def _save_and_sync_ui(track_id, plate_img, clean_text, is_fixed,
                      video_filename, video_save_dir,
                      saved_first: set, saved_fixed: set,
                      conf, vote_count, elapsed,
                      operator_name=None, candidates=None,
                      token=None) -> str | None:

    video_subfolder = os.path.basename(video_save_dir)
    if len(clean_text) > 10: is_fixed = False

    suffix          = "fixed" if is_fixed else "first"
    img_filename    = f"id_{track_id}_{suffix}.jpg"
    rel_img_path    = f"{video_subfolder}/{img_filename}"
    img_path        = os.path.join(SAVE_DIR, rel_img_path)
    current_img_url = f"/api/plate/image/{rel_img_path}"

    data_payload = {
        'id':                int(track_id),
        'text':              clean_text,
        'is_fixed':          is_fixed,
        'detected_at':       datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'img_url':           current_img_url,
        'img_filename':      rel_img_path,
        'video':             video_filename,
        'conf':              round(float(conf), 4),
        'vote_count':        vote_count,
        'elapsed_ms':        elapsed,
        'preprocess_results': {},
    }

    with state_lock:
        vid_name  = os.path.basename(str(video_filename))
        norm_text = clean_text.replace(" ", "")

        existing_idx = next(
            (i for i, r in enumerate(state['all_results'])
             if os.path.basename(str(r.get('video', ''))) == vid_name
             and r['text'].replace(" ", "") == norm_text),
            None
        )
        if existing_idx is None:
            existing_idx = next(
                (i for i, r in enumerate(state['all_results'])
                 if os.path.basename(str(r.get('video', ''))) == vid_name
                 and r['id'] == int(track_id)),
                None
            )

        if existing_idx is not None:
            existing = state['all_results'][existing_idx]

            # 확정 데이터를 미확정이 덮어쓰지 못하게 방어
            if existing.get('is_fixed') and not is_fixed:
                return current_img_url

            state['all_results'][existing_idx].update(data_payload)

            db_params = {
                'plate_number':   clean_text,
                'video_filename': video_filename,
                'conf':           conf,
                'vote_count':     vote_count,
                'is_fixed':       is_fixed,
                'img_path':       current_img_url,
            }
            io_queue.put((img_path, plate_img.copy(), update_result, db_params, token))

        else:
            state['all_results'].insert(0, data_payload)
            saved_first.add(track_id)

            db_params = {
                'plate_number':   clean_text,
                'video_filename': video_filename,
                'conf':           conf,
                'vote_count':     vote_count,
                'is_fixed':       is_fixed,
                'img_path':       current_img_url,
                'elapsed_ms':     elapsed,
                'operator_name':  operator_name,
            }
            io_queue.put((img_path, plate_img.copy(), save_result, db_params, token))

            if len(state['all_results']) > 100:
                state['all_results'].pop()

    return current_img_url