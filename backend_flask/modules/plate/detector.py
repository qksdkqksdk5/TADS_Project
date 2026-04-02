import cv2
import re
import time
import os
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
from .csv_manager import delete_by_video, save_result, update_result
from .state import OCR_ENGINE

if OCR_ENGINE == 'yolo':
    from .yolo_ocr_engine import ocr_input_queue, ocr_result_queue
else:
    from .ocr_engine import ocr_input_queue, ocr_result_queue

plate_pattern = re.compile(r'^\d{2,3}[가-힣]\d{4}$')
os.makedirs(SAVE_DIR, exist_ok=True)



def process_video():
    print("🚀 영상 처리 스레드 시작")
    model = YOLO(MODEL_PATH, task='detect')

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

    # ✅ 영상 시작 시 기존 결과 초기화
    delete_by_video(video_filename)
    with state_lock:
        state['all_results'] = [
            r for r in state['all_results']
            if os.path.basename(str(r.get('video', ''))) != video_filename
        ]
    print(f"🗑️ [{video_filename}] state 초기화 완료")

    # 로컬 상태 관리 변수
    best_samples        = {}
    plate_history_ids   = []
    plate_history_imgs  = {}
    plate_history_texts = {}
    plate_votes         = {}
    queued_ids          = set()
    plate_img_urls      = {}
    saved_first         = set()
    saved_fixed         = set()
    
    # [추가] 분석 성능 및 신뢰도 추적용
    plate_confs         = {} 
    start_times         = {}

    cap = cv2.VideoCapture(video_path)
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frame_interval = 1.0 / video_fps
    
    frame_count = 0
    fps_buf     = []
    fps_start   = time.time()

    while True:
        with state_lock:
            if state.get('stop_thread', False): break

        ret, frame = cap.read()
        if not ret: break

        h_f, w_f    = frame.shape[:2]
        frame_count += 1
        t0          = time.time()

        results = model.track(source=frame, conf=CONF, persist=True, verbose=False, imgsz=YOLO_IMG_SIZE)
        annotated = frame.copy()

        if results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
            ids   = results[0].boxes.id.cpu().numpy().astype(int)
            confs = results[0].boxes.conf.cpu().numpy()

            for box, tid, conf in zip(boxes, ids, confs):
                x1, y1, x2, y2 = box
                is_fixed = best_samples.get(tid, {}).get('is_fixed', False)
                color = (0, 255, 0) if is_fixed else (255, 165, 0)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                
                center_y = (y1 + y2) / 2
                if int(h_f * ROI_TOP) < center_y < int(h_f * ROI_BOTTOM) and not is_fixed:
                    if tid not in queued_ids and not ocr_input_queue.full():
                        crop = frame[max(0,y1-PAD):min(h_f,y2+PAD), max(0,x1-PAD):min(w_f,x2+PAD)]
                        if crop.size > 0:
                            ocr_input_queue.put((tid, crop.copy()))
                            queued_ids.add(tid)
                            start_times[tid] = time.time() # 분석 시작 시간 기록
                            plate_confs[tid] = conf       # YOLO 탐지 신뢰도 기록

        # OCR 결과 처리
        while not ocr_result_queue.empty():
            try:
                tid, p_img, p_text = ocr_result_queue.get_nowait()
                queued_ids.discard(tid)
            except: break

            if plate_pattern.search(p_text):
                if tid not in plate_votes: plate_votes[tid] = []
                plate_votes[tid].append(p_text)

                voted_text, count = Counter(plate_votes[tid]).most_common(1)[0]
                is_now_fixed = count >= VOTE_THRESHOLD
                
                # 데이터 수집
                elapsed_ms = int((time.time() - start_times.get(tid, time.time())) * 1000)
                current_conf = plate_confs.get(tid, 0.0)

                best_samples[tid] = {'is_fixed': is_now_fixed}
                plate_history_texts[tid] = voted_text

                if tid in plate_history_ids: plate_history_ids.remove(tid)
                plate_history_ids.insert(0, tid)
                plate_history_imgs[tid] = cv2.resize(p_img, (400, 110))

                # [핵심] 저장 및 UI 동기화 함수 호출
                img_url = _save_and_sync_ui(
                    tid, p_img, voted_text, is_now_fixed,
                    video_filename, video_save_dir,
                    saved_first, saved_fixed,
                    conf=current_conf, vote_count=count, elapsed=elapsed_ms
                )
                if img_url: plate_img_urls[tid] = img_url

            if len(plate_history_ids) > HISTORY_MAX:
                old_id = plate_history_ids.pop()
                for d in [plate_history_imgs, plate_history_texts, plate_votes, plate_img_urls]:
                    d.pop(old_id, None)

        # 실시간 화면 업데이트
        resized = cv2.resize(annotated, (DISPLAY_W, DISPLAY_H))
        with state_lock:
            state['latest_frame'] = resized
            state['plates'] = [
                {
                    'id': int(t_id),
                    'text': plate_history_texts.get(t_id, '인식 중...'),
                    'is_fixed': best_samples.get(t_id, {}).get('is_fixed', False),
                    'vote_count': len(plate_votes.get(t_id, [])),
                    'img_url': plate_img_urls.get(t_id),
                } for t_id in plate_history_ids[:5]
            ]

        fps_buf.append(time.time() - t0)
        time.sleep(max(0.01, frame_interval - (time.time() - t0)))

    cap.release()

def _save_and_sync_ui(track_id, plate_img, clean_text, is_fixed,
                    video_filename, video_save_dir,
                    saved_first: set, saved_fixed: set,
                    conf, vote_count, elapsed) -> str | None:

    video_subfolder = os.path.basename(video_save_dir)

    if len(clean_text) > 8:
        is_fixed = False

    suffix = "fixed" if is_fixed else "first"
    img_filename = f"id_{track_id}_{suffix}.jpg"
    rel_img_path = f"{video_subfolder}/{img_filename}"
    img_path = os.path.join(SAVE_DIR, rel_img_path)
    current_img_url = f"/api/plate/image/{rel_img_path}"

    os.makedirs(os.path.dirname(img_path), exist_ok=True)
    cv2.imwrite(img_path, plate_img)

    data_payload = {
        'id':          int(track_id),
        'text':        clean_text,
        'is_fixed':    is_fixed,
        'detected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'img_url':     current_img_url,
        'img_filename': rel_img_path,
        'video':       video_filename,
        'conf':        round(float(conf), 4),
        'vote_count':  vote_count,
        'elapsed_ms':  elapsed,
        'ground_truth': None,
        'is_correct':   None,
        'preprocess_results': {},
    }

    with state_lock:
        vid_name = os.path.basename(str(video_filename))

        # 1. ID + 영상 둘 다 일치하는 것 먼저 검색
        existing_idx = next(
            (i for i, r in enumerate(state['all_results'])
             if os.path.basename(str(r.get('video', ''))) == vid_name
             and r['id'] == int(track_id)),
            None
        )

        # 2. ID로 못 찾으면 텍스트 + 영상으로 검색
        if existing_idx is None:
            existing_idx = next(
                (i for i, r in enumerate(state['all_results'])
                 if os.path.basename(str(r.get('video', ''))) == vid_name
                 and r['text'].replace(" ", "") == clean_text.replace(" ", "")),
                None
            )

        if existing_idx is not None:
            existing = state['all_results'][existing_idx]

            if existing.get('is_fixed') and not is_fixed:
                return current_img_url

            # ✅ ID 다른데 (다른 영상 아닌) 같은 영상 내 다른 track_id인 경우만 투표수 비교
            if existing['id'] != int(track_id):
                if existing.get('vote_count', 0) >= vote_count:
                    return current_img_url

            data_payload['ground_truth']       = existing.get('ground_truth')
            data_payload['is_correct']         = existing.get('is_correct')
            data_payload['preprocess_results'] = existing.get('preprocess_results', {})
            state['all_results'][existing_idx].update(data_payload)

        else:
            state['all_results'].insert(0, data_payload)
            saved_first.add(track_id)
            if len(state['all_results']) > 100:
                state['all_results'].pop()

    # CSV 저장
    save_result(
        plate_number=clean_text,
        video_filename=video_filename,
        conf=conf,
        vote_count=vote_count,
        is_fixed=is_fixed,
        img_path=current_img_url,
        elapsed_ms=elapsed
    )

    return current_img_url

