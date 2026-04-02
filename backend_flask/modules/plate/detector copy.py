# backend_flask/modules/plate/detector.py
# YOLO 번호판 영역 검출 + 프레임 처리 스레드

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
    ASPECT_RATIO_MIN, ASPECT_RATIO_MAX,
    MAX_BOX_AREA_RATIO, MIN_BOX_AREA_RATIO,
    VOTE_THRESHOLD,
)
# from .ocr_engine import ocr_input_queue, ocr_result_queue
from .yolo_ocr_engine import ocr_input_queue, ocr_result_queue
from .csv_manager import save_result, update_result

plate_pattern = re.compile(r'\d{2,3}[가-힣]\d{4}')

# 저장 폴더 명시적 생성 (state.py import 타이밍 문제 방지)
os.makedirs(SAVE_DIR, exist_ok=True)


def process_video():
    """
    YOLO 번호판 검출 + OCR 결과 수신 + 상태 업데이트 스레드
    - YOLO는 매 프레임 실행
    - OCR은 ocr_engine 스레드에 위임 (비동기)
    - 영상 1회 재생 후 종료
    """
    print("🚀 영상 처리 스레드 시작")
    model = YOLO(MODEL_PATH, task='detect')

    with state_lock:
        video_path = state['current_video']

    if not video_path or not os.path.exists(video_path):
        print(f"❌ 영상 파일 없음: {video_path}")
        return

    video_filename = os.path.basename(video_path)
    # 영상별 서브폴더 생성 (test06.mp4 → best_plates_golden/test06/)
    video_subfolder = os.path.splitext(video_filename)[0]
    video_save_dir = os.path.join(SAVE_DIR, video_subfolder)
    os.makedirs(video_save_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)

    # FPS 측정용 변수
    frame_count = 0
    fps_times = []
    fps_start = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            # 영상 종료 시 최종 FPS 출력
            if fps_times:
                avg_fps = 1 / (sum(fps_times) / len(fps_times))
                total_sec = time.time() - fps_start
                print(f"📊 [FPS 최종] 평균: {avg_fps:.1f} FPS | 총 {frame_count}프레임 | {total_sec:.1f}초")
            print("📹 [plate] 영상 재생 완료")
            break

        h_frame, w_frame = frame.shape[:2]
        frame_area = h_frame * w_frame
        frame_count += 1
        frame_t_start = time.time()

        try:
            results = model.track(
                source=frame, conf=0.2,
                persist=True, verbose=False,
                imgsz=YOLO_IMG_SIZE
            )
        except Exception as e:
            print(f"❌ YOLO 오류: {e}")
            time.sleep(0.1)
            continue

        annotated_frame = frame.copy()

        with state_lock:
            best_samples = dict(state['best_samples'])

        boxes = ids = confs = None
        if results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
            ids = results[0].boxes.id.cpu().numpy().astype(int)
            confs = results[0].boxes.conf.cpu().numpy()

            for box, track_id, conf in zip(boxes, ids, confs):
                x1, y1, x2, y2 = box
                is_fixed = best_samples.get(track_id, {}).get('is_fixed', False)
                color = (0, 255, 0) if is_fixed else (255, 100, 0)
                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 1)
                cv2.putText(annotated_frame, f"ID:{track_id} {conf:.2f}",
                            (x1, max(y1 - 5, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        # ROI 라인
        cv2.line(annotated_frame,
                 (0, int(h_frame * ROI_TOP)), (w_frame, int(h_frame * ROI_TOP)),
                 (0, 255, 255), 2)
        cv2.line(annotated_frame,
                 (0, int(h_frame * ROI_BOTTOM)), (w_frame, int(h_frame * ROI_BOTTOM)),
                 (0, 255, 255), 2)

        # OCR 결과 수신 및 상태 업데이트
        _process_ocr_results(video_filename, video_save_dir)

        # OCR 요청
        if boxes is not None:
            _request_ocr(boxes, ids, confs, frame, h_frame, w_frame, frame_area)

        # 프레임 + 상태 업데이트
        resized = cv2.resize(annotated_frame, (DISPLAY_W, DISPLAY_H))
        with state_lock:
            state['latest_frame'] = resized
            state['plates'] = _build_plates_payload()

        # FPS 측정 (100프레임마다 출력)
        elapsed = time.time() - frame_t_start
        fps_times.append(elapsed)
        if frame_count % 100 == 0:
            avg_fps = 1 / (sum(fps_times[-100:]) / min(len(fps_times), 100))
            print(f"📊 [FPS] {frame_count}프레임 | 최근 100프레임 평균: {avg_fps:.1f} FPS")

        time.sleep(0.03)

    cap.release()


def _process_ocr_results(video_filename, video_save_dir):
    """OCR 결과 큐에서 꺼내 상태 업데이트"""
    while not ocr_result_queue.empty():
        try:
            track_id, plate_img, detected_text = ocr_result_queue.get_nowait()
        except Exception:
            break

        with state_lock:
            state['queued_ids'].discard(track_id)
            match = plate_pattern.search(detected_text)
            is_valid = bool(match)
            if match:
                detected_text = match.group()  # ':' 등 쓰레기 문자 제거

            if is_valid:
                _handle_valid(track_id, plate_img, detected_text, video_filename, video_save_dir)
            else:
                _handle_invalid(track_id, detected_text)


def _handle_valid(track_id, plate_img, detected_text, video_filename, video_save_dir):
    """정규식 통과한 번호판 처리 (state_lock 안에서 호출)"""
    if track_id not in state['first_valid_texts']:
        state['first_valid_texts'][track_id] = detected_text
        img_filename = f"id_{track_id}_first.jpg"
        img_path = os.path.join(video_save_dir, img_filename)
        cv2.imwrite(img_path, plate_img)

        # img_url에 서브폴더 포함 (API에서 경로 일치)
        video_subfolder = os.path.basename(video_save_dir)
        img_url = f"/api/plate/image/{video_subfolder}/{img_filename}"

        save_result(
            plate_number=detected_text,
            img_path=img_url,  # 상대 URL로 저장
            video_filename=video_filename
        )

        state['all_results'].insert(0, {
            'id': int(track_id),
            'text': detected_text,
            'is_fixed': False,
            'detected_at': datetime.now().strftime('%H:%M:%S'),
            'img_url': img_url,
            'img_filename': f"{video_subfolder}/{img_filename}",
            'ground_truth': None,
            'is_correct': None,
            'preprocess': None,
            'retried_text': None,
            'video': video_filename,   # 영상 파일명
        })

    if track_id not in state['plate_votes']:
        state['plate_votes'][track_id] = []
    state['plate_votes'][track_id].append(detected_text)

    vote_counter = Counter(state['plate_votes'][track_id])
    best_text, best_count = vote_counter.most_common(1)[0]
    is_fixed = best_count >= VOTE_THRESHOLD

    if track_id not in state['best_samples'] or best_count > 1:
        # first img_url 기본값으로 설정
        video_subfolder = os.path.basename(video_save_dir)
        first_img_url = f"/api/plate/image/{video_subfolder}/id_{track_id}_first.jpg"

        state['best_samples'][track_id] = {
            'conf': 0.0,
            'is_fixed': is_fixed,
            'img_url': first_img_url,   # 실시간 탭에서 참조할 img_url
        }
        state['plate_history_texts'][track_id] = best_text

        if track_id in state['plate_history_ids']:
            state['plate_history_ids'].remove(track_id)
        state['plate_history_ids'].insert(0, track_id)

        if is_fixed:
            img_filename = f"id_{track_id}_fixed.jpg"
            img_path = os.path.join(video_save_dir, img_filename)
            fixed_img_url = f"/api/plate/image/{video_subfolder}/{img_filename}"
            cv2.imwrite(img_path, plate_img)

            # CSV 확정 여부 업데이트
            update_result(
                plate_number=best_text,
                video_filename=video_filename,
                is_fixed=True,
                img_path=fixed_img_url,
            )

            # fixed 확정 시 img_url을 fixed로 교체
            state['best_samples'][track_id]['img_url'] = fixed_img_url

            for r in state['all_results']:
                if r['id'] == int(track_id):
                    r['is_fixed'] = True
                    r['text'] = best_text
                    r['img_url'] = fixed_img_url       # 전체기록도 fixed로
                    r['img_filename'] = f"{video_subfolder}/{img_filename}"
                    break

        if len(state['plate_history_ids']) > 5:
            last_id = state['plate_history_ids'].pop()
            state['plate_votes'].pop(last_id, None)
            state['plate_history_texts'].pop(last_id, None)


def _handle_invalid(track_id, detected_text):
    """정규식 미통과 번호판 처리 (state_lock 안에서 호출)"""
    if track_id not in state['best_samples']:
        state['best_samples'][track_id] = {'conf': 0, 'is_fixed': False}
        state['plate_history_texts'][track_id] = detected_text
        if track_id in state['plate_history_ids']:
            state['plate_history_ids'].remove(track_id)
        state['plate_history_ids'].insert(0, track_id)
        if len(state['plate_history_ids']) > 5:
            last_id = state['plate_history_ids'].pop()
            state['plate_votes'].pop(last_id, None)
            state['plate_history_texts'].pop(last_id, None)


def _request_ocr(boxes, ids, confs, frame, h_frame, w_frame, frame_area):
    """필터링 통과한 번호판 이미지를 OCR 큐에 전달"""
    for box, track_id, conf in zip(boxes, ids, confs):
        with state_lock:
            if state['best_samples'].get(track_id, {}).get('is_fixed'):
                continue
            already_queued = track_id in state['queued_ids']

        x1, y1, x2, y2 = box
        w = x2 - x1
        h = y2 - y1
        if h == 0:
            continue
        if not (ASPECT_RATIO_MIN < w / h < ASPECT_RATIO_MAX):
            continue
        if not (MIN_BOX_AREA_RATIO < (w * h) / frame_area < MAX_BOX_AREA_RATIO):
            continue

        center_y = (y1 + y2) / 2
        if int(h_frame * ROI_TOP) < center_y < int(h_frame * ROI_BOTTOM):
            plate_img = frame[max(0, y1 - 10):min(h_frame, y2 + 10),
                              max(0, x1 - 10):min(w_frame, x2 + 10)]
            if plate_img.size > 0 and not already_queued and not ocr_input_queue.full():
                ocr_input_queue.put((track_id, plate_img.copy()))
                with state_lock:
                    state['queued_ids'].add(track_id)


def _build_plates_payload():
    """현재 화면용 최근 5개 번호판 데이터 생성 (state_lock 안에서 호출)"""
    result = []
    for t_id in state['plate_history_ids'][:5]:
        sample = state['best_samples'].get(t_id, {})
        is_fixed = sample.get('is_fixed', False)

        # img_url 우선순위: fixed > first > None
        img_url = sample.get('img_url')
        if not img_url and t_id in state['first_valid_texts']:
            # best_samples에 img_url 없으면 first로 fallback
            # (video_subfolder 정보가 없으므로 all_results에서 가져옴)
            found = next((r for r in state['all_results'] if r['id'] == int(t_id)), None)
            img_url = found.get('img_url') if found else None

        result.append({
            'id': int(t_id),
            # first_valid_texts 우선 → plate_history_texts → 인식 중...
            'text': state['first_valid_texts'].get(t_id)
                    or state['plate_history_texts'].get(t_id, '인식 중...'),
            'is_fixed': is_fixed,
            'vote_count': len(state['plate_votes'].get(t_id, [])),
            'img_url': img_url,
        })
    return result