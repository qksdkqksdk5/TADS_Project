# backend_flask/modules/plate/analytics.py
# CSV 데이터 분석 로직 전담
# plate.py의 /analytics 라우트에서 호출

import os
from .db_manager import get_all_results


def get_analytics(video_filter='', status_filter='', search=''):
    """
    CSV 기반 분석 데이터 반환
    :param video_filter: 영상 파일명 필터
    :param status_filter: 정오여부 필터 (정답 / 오답 / 미입력)
    :param search: 번호판 텍스트 검색
    :return: 분석 결과 딕셔너리
    """
    rows = get_all_results()

    empty = {
        "total": 0, "answered": 0, "correct": 0, "accuracy": 0,
        "videos": [], "preprocess_stats": {}, "records": []
    }
    if not rows:
        return empty

    # 인식 원본 행 / 전처리 행 분리
    base_rows = [r for r in rows if not r.get('전처리방법')]
    preprocess_rows = [r for r in rows if r.get('전처리방법')]

    # 영상 목록
    videos = sorted(set(
        os.path.basename(r.get('영상파일', '')) for r in base_rows
        if r.get('영상파일')
    ))

    # 요약 통계
    answered = [r for r in base_rows if r.get('정오여부') in ('정답', '오답')]
    correct  = [r for r in answered if r.get('정오여부') == '정답']
    accuracy = round(len(correct) / len(answered) * 100, 1) if answered else 0

    # 전처리별 성공률
    preprocess_stats = _calc_preprocess_stats(preprocess_rows)

    # 필터 적용
    filtered = _apply_filters(base_rows, video_filter, status_filter, search)

    # 레코드 조립 (전처리 결과 붙이기)
    records = _build_records(filtered, preprocess_rows)

    return {
        "total":            len(base_rows),
        "answered":         len(answered),
        "correct":          len(correct),
        "accuracy":         accuracy,
        "videos":           videos,
        "preprocess_stats": preprocess_stats,
        "records":          records,
    }


def _calc_preprocess_stats(preprocess_rows):
    """전처리 방법별 성공/실패 통계"""
    stats = {}
    for r in preprocess_rows:
        method  = r.get('전처리방법', '')
        gt      = r.get('정답번호판', '')
        retried = r.get('보정후번호판', '')
        if not method:
            continue
        if method not in stats:
            stats[method] = {'total': 0, 'success': 0, 'fail': 0}
        stats[method]['total'] += 1
        if gt and retried == gt:
            stats[method]['success'] += 1
        elif retried == '인식 실패':
            stats[method]['fail'] += 1
    return stats


def _apply_filters(rows, video_filter, status_filter, search):
    """필터 조건 적용"""
    result = rows
    if video_filter:
        result = [r for r in result
                  if os.path.basename(r.get('영상파일', '')) == video_filter]
    if status_filter:
        result = [r for r in result if r.get('정오여부') == status_filter]
    if search:
        result = [r for r in result
                  if search in r.get('인식번호판', '')
                  or search in r.get('정답번호판', '')]
    return result


def _build_records(filtered, preprocess_rows):
    """레코드 리스트 조립 — 각 번호판에 전처리 결과 붙이기"""
    records = []
    for r in filtered:
        plate = r.get('인식번호판', '')
        vid   = os.path.basename(r.get('영상파일', ''))

        # 해당 번호판의 전처리 결과 수집
        preps = [
            p for p in preprocess_rows
            if p.get('인식번호판') == plate
            and os.path.basename(p.get('영상파일', '')) == vid
        ]
        prep_summary = {
            p.get('전처리방법'): {
                'result':     p.get('보정후번호판', ''),
                'correct':    bool(p.get('정답번호판') and
                                   p.get('보정후번호판') == p.get('정답번호판')),
                'elapsed_ms': p.get('처리시간(ms)', ''),
            }
            for p in preps if p.get('전처리방법')
        }
        records.append({
            'plate':        plate,
            'ground_truth': r.get('정답번호판', ''),
            'status':       r.get('정오여부', '미입력'),
            'video':        vid,
            'detected_at':  r.get('인식시각', ''),
            'img_path':     r.get('이미지경로', ''),
            'preprocess':   prep_summary,
        })
    return records