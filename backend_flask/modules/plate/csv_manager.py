# backend_flask/modules/plate/csv_manager.py
import csv
import re
import os
from datetime import datetime
from .state import BASE_DIR

CSV_PATH = os.path.join(BASE_DIR, 'plate_results.csv')

COLUMNS = [
    '인식번호판', '정답번호판', '정오여부',
    '신뢰도', '투표수', '확정여부',
    '전처리방법', '보정후번호판',
    '처리시간(ms)', '인식시각', '영상파일', '이미지경로'
]


def delete_by_video(video_filename: str):
    """특정 영상의 모든 결과 삭제 (영상 재실행 시 호출)"""
    if not os.path.exists(CSV_PATH):
        return

    vid = os.path.basename(str(video_filename))
    try:
        with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames or COLUMNS

        rows = [
            r for r in rows
            if os.path.basename(str(r.get('영상파일', ''))) != vid
        ]

        with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        print(f"🗑️ [{vid}] 기존 결과 삭제 완료")
    except Exception as e:
        print(f"❌ CSV 삭제 오류: {e}")


def save_result(plate_number, img_path, conf=None, vote_count=None,
                is_fixed=False, ground_truth=None, is_correct=None,
                preprocess=None, retried_text=None, elapsed_ms=None,
                video_filename=None):
    vid = os.path.basename(str(video_filename)) if video_filename else ''
    rows = []
    fieldnames = COLUMNS
    updated = False

    if os.path.exists(CSV_PATH):
        try:
            with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                fieldnames = reader.fieldnames or COLUMNS
        except Exception as e:
            print(f"CSV Read Error: {e}")

    match = re.search(r'id_(\d+)_', img_path)
    current_id_num = match.group(1) if match else None
    clean_target_text = plate_number.replace(" ", "")

    for row in rows:
        row_img   = row.get('이미지경로', '')
        row_text  = row.get('인식번호판', '').replace(" ", "")
        row_vid   = os.path.basename(str(row.get('영상파일', '')))
        row_prep  = row.get('전처리방법', '')

        row_match  = re.search(r'id_(\d+)_', row_img)
        row_id_num = row_match.group(1) if row_match else None

        is_original    = not row_prep or row_prep == ''
        # ✅ is_same_id: ID 숫자 + 영상 파일명 둘 다 일치해야 함
        is_same_id     = (current_id_num and current_id_num == row_id_num and row_vid == vid)
        is_same_vehicle = (row_text == clean_target_text and row_vid == vid)

        if is_original and (is_same_id or is_same_vehicle):
            was_fixed      = row.get('확정여부') == '확정'
            existing_votes = int(row.get('투표수', 0)) if row.get('투표수') else 0
            new_votes      = vote_count if vote_count is not None else 0

            if current_id_num != row_id_num and was_fixed:
                updated = True
                break

            if current_id_num != row_id_num and not was_fixed and not is_fixed:
                if existing_votes >= new_votes:
                    updated = True
                    break

            row['인식번호판'] = plate_number
            row['확정여부']   = '확정' if (is_fixed or was_fixed) else '미확정'
            row['신뢰도']     = round(conf, 4) if conf is not None else row.get('신뢰도', '')
            row['투표수']     = vote_count if vote_count is not None else row.get('투표수', '')

            if is_fixed or not row.get('이미지경로'):
                row['이미지경로'] = img_path

            row['인식시각'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            row['영상파일'] = vid
            updated = True
            break

    if not updated:
        new_row = {
            '인식번호판':   plate_number,
            '정답번호판':   ground_truth or '',
            '정오여부':    '정답' if is_correct is True else ('오답' if is_correct is False else '미입력'),
            '신뢰도':      round(conf, 4) if conf is not None else '',
            '투표수':      vote_count if vote_count is not None else '',
            '확정여부':    '확정' if is_fixed else '미확정',
            '전처리방법':   preprocess or '',
            '보정후번호판':  retried_text or '',
            '처리시간(ms)': elapsed_ms or '',
            '인식시각':    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '영상파일':    vid,
            '이미지경로':   img_path,
        }
        rows.append(new_row)

    with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def update_result(plate_number, video_filename, **kwargs):
    if not os.path.exists(CSV_PATH):
        return False

    vid = os.path.basename(str(video_filename)) if video_filename else ''

    target_img_path = kwargs.get('img_path', '')
    match = re.search(r'id_(\d+)_', target_img_path)
    target_id_num = match.group(1) if match else None

    try:
        with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames or COLUMNS
    except Exception:
        return False

    col_map = {
        'ground_truth': '정답번호판', 'is_correct': '정오여부', 'is_fixed': '확정여부',
        'img_path': '이미지경로', 'conf': '신뢰도', 'vote_count': '투표수', 'elapsed_ms': '처리시간(ms)'
    }

    updated = False
    for row in rows:
        row_img   = row.get('이미지경로', '')
        row_vid   = os.path.basename(str(row.get('영상파일', '')))
        row_match = re.search(r'id_(\d+)_', row_img)
        row_id_num = row_match.group(1) if row_match else None

        # ✅ ID 숫자 + 영상 파일명 둘 다 일치해야 업데이트
        if target_id_num and target_id_num == row_id_num and row_vid == vid:
            row['인식번호판'] = plate_number

            for key, val in kwargs.items():
                col = col_map.get(key, key)
                if col in row:
                    if key == 'is_correct':
                        val = '정답' if val is True else ('오답' if val is False else '미입력')
                    elif key == 'is_fixed':
                        val = '확정' if val else '미확정'
                    if key == 'img_path' and row.get('확정여부') == '확정' and 'first' in str(val):
                        continue
                    row[col] = val

            row['인식시각'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            updated = True
            break

    if updated:
        with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    return updated


def add_preprocess_result(plate_number, video_filename, preprocess, retried_text,
                          elapsed_ms=None, ground_truth=None, is_correct=None, img_path=''):
    vid = os.path.basename(str(video_filename)) if video_filename else ''

    if os.path.exists(CSV_PATH):
        try:
            with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                fieldnames = reader.fieldnames or COLUMNS

            updated = False
            for row in rows:
                if (row.get('인식번호판') == plate_number and
                        os.path.basename(str(row.get('영상파일', ''))) == vid and
                        row.get('전처리방법') == preprocess):
                    row['보정후번호판']  = retried_text
                    row['처리시간(ms)'] = elapsed_ms or ''
                    row['정오여부']     = '정답' if is_correct is True else ('오답' if is_correct is False else '미입력')
                    row['인식시각']     = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    updated = True
                    break

            if updated:
                with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                return
        except Exception:
            pass

    file_exists = os.path.exists(CSV_PATH)
    with open(CSV_PATH, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(COLUMNS)
        writer.writerow([
            plate_number, ground_truth or '',
            '정답' if is_correct is True else ('오답' if is_correct is False else '미입력'),
            '', '', '', preprocess, retried_text, elapsed_ms or '',
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            video_filename or '', img_path,
        ])


def get_all_results():
    if not os.path.exists(CSV_PATH):
        return []
    with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
        return [dict(row) for row in csv.DictReader(f)]