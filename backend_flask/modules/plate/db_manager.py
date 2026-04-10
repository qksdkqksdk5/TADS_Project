# backend_flask/modules/plate/db_manager.py
"""
번호판 인식 결과 관리 - DB 버전
CSV에서 SQLAlchemy로 마이그레이션 완료
백그라운드 스레드에서 DB 접근을 위해 app context 사용
"""

import re
import os
from datetime import datetime
from models import db, PlateResult, PlatePreprocessResult

# 백그라운드 스레드에서 DB 접근을 위한 앱 참조
_app = None

def init_app(app):
    """앱 초기화 - app.py에서 호출"""
    global _app
    _app = app


def _get_app_context():
    """앱 컨텍스트 반환 (없으면 에러)"""
    if not _app:
        raise RuntimeError("db_manager not initialized. Call init_app(app) first.")
    return _app.app_context()


def delete_by_video(video_filename: str):
    """특정 영상의 모든 결과 삭제 (영상 재실행 시 호출)"""
    try:
        with _get_app_context():
            vid = os.path.basename(str(video_filename))
            
            # 해당 영상의 모든 원본 결과와 전처리 결과 삭제
            results = PlateResult.query.filter_by(video_filename=vid).all()
            
            for result in results:
                # 전처리 결과는 cascade로 자동 삭제됨
                db.session.delete(result)
            
            db.session.commit()
            print(f"🗑️ [{vid}] 기존 결과 삭제 완료")
    except Exception as e:
        try:
            db.session.rollback()
        except:
            pass
        print(f"❌ DB 삭제 오류: {e}")


def save_result(plate_number, img_path, conf=None, vote_count=None,
                is_fixed=False, ground_truth=None, is_correct=None,
                preprocess=None, retried_text=None, elapsed_ms=None,
                video_filename=None):
    """
    번호판 인식 결과 저장 또는 업데이트
    
    같은 ID 숫자 + 영상 파일명, 또는 같은 번호판 + 영상 파일명이면 업데이트
    """
    try:
        with _get_app_context():
            vid = os.path.basename(str(video_filename)) if video_filename else ''
            
            # 이미지 경로에서 ID 숫자 추출 (예: id_0_img.jpg → 0)
            match = re.search(r'id_(\d+)_', img_path)
            current_id_num = match.group(1) if match else None
            clean_target_text = plate_number.replace(" ", "")
            
            # 기존 원본 결과(전처리 아님) 찾기
            existing = None
            
            # 1. ID 숫자 + 영상 파일명으로 찾기
            if current_id_num:
                for result in PlateResult.query.filter_by(video_filename=vid).all():
                    if not result.preprocess_results:  # 원본만 (전처리 결과가 부모인 경우는 제외)
                        match = re.search(r'id_(\d+)_', result.img_path or '')
                        if match and match.group(1) == current_id_num:
                            existing = result
                            break
            
            # 2. 번호판 + 영상 파일명으로 찾기
            if not existing:
                for result in PlateResult.query.filter_by(video_filename=vid).all():
                    if not result.preprocess_results:  # 원본만
                        if result.plate_number.replace(" ", "") == clean_target_text:
                            existing = result
                            break
            
            # 기존 결과가 있으면 업데이트
            if existing:
                was_fixed = existing.is_fixed
                existing_votes = existing.vote_count or 0
                new_votes = vote_count if vote_count is not None else 0
                
                # 다른 ID인데 확정된 결과면 업데이트 안 함
                if current_id_num:
                    match = re.search(r'id_(\d+)_', existing.img_path or '')
                    existing_id = match.group(1) if match else None
                    if current_id_num != existing_id and was_fixed:
                        db.session.commit()
                        return
                    
                    # 다른 ID인데 미확정이고, 새로운 투표수가 적으면 업데이트 안 함
                    if current_id_num != existing_id and not was_fixed and not is_fixed:
                        if existing_votes >= new_votes:
                            db.session.commit()
                            return
                
                # 업데이트
                existing.plate_number = plate_number
                existing.is_fixed = is_fixed or was_fixed
                if conf is not None:
                    existing.confidence = round(conf, 4)
                if vote_count is not None:
                    existing.vote_count = vote_count
                existing.detected_at = datetime.now()
                if is_fixed or not existing.img_path:
                    existing.img_path = img_path
            else:
                # 새로운 결과 생성
                new_result = PlateResult(
                    plate_number=plate_number,
                    ground_truth=ground_truth or None,
                    is_correct=is_correct,
                    confidence=round(conf, 4) if conf is not None else None,
                    vote_count=vote_count,
                    is_fixed=is_fixed,
                    img_path=img_path,
                    video_filename=vid,
                    detected_at=datetime.now()
                )
                db.session.add(new_result)
            
            db.session.commit()
    except Exception as e:
        try:
            db.session.rollback()
        except:
            pass
        print(f"❌ DB 저장 오류: {e}")


def update_result(plate_number, video_filename, **kwargs):
    """
    기존 결과 업데이트 (정답, 정오여부, 확정 등)
    
    img_path가 있으면 그것을 기준으로 매칭
    """
    try:
        with _get_app_context():
            vid = os.path.basename(str(video_filename)) if video_filename else ''
            target_img_path = kwargs.get('img_path', '')
            
            # 이미지 경로에서 ID 숫자 추출
            match = re.search(r'id_(\d+)_', target_img_path)
            target_id_num = match.group(1) if match else None
            
            if not target_id_num:
                return False
            
            # 매칭 조건: ID 숫자 + 영상 파일명
            for result in PlateResult.query.filter_by(video_filename=vid).all():
                if not result.preprocess_results:  # 원본만
                    match = re.search(r'id_(\d+)_', result.img_path or '')
                    if match and match.group(1) == target_id_num:
                        # 필드 업데이트
                        result.plate_number = plate_number
                        
                        if 'ground_truth' in kwargs:
                            result.ground_truth = kwargs['ground_truth']
                        if 'is_correct' in kwargs:
                            result.is_correct = kwargs['is_correct']
                        if 'is_fixed' in kwargs:
                            result.is_fixed = kwargs['is_fixed']
                        if 'confidence' in kwargs and kwargs['confidence'] is not None:
                            result.confidence = kwargs['confidence']
                        if 'vote_count' in kwargs:
                            result.vote_count = kwargs['vote_count']
                        if 'img_path' in kwargs and result.is_fixed != True:
                            result.img_path = kwargs['img_path']
                        
                        result.updated_at = datetime.now()
                        db.session.commit()
                        return True
            
            return False
    except Exception as e:
        try:
            db.session.rollback()
        except:
            pass
        print(f"❌ DB 업데이트 오류: {e}")
        return False


def add_preprocess_result(plate_number, video_filename, preprocess, corrected_text,
                          elapsed_ms=None, ground_truth=None, is_correct=None, img_path=''):
    """
    전처리 결과 추가 또는 업데이트
    
    같은 preprocess_method가 있으면 업데이트, 없으면 새로 추가
    """
    try:
        with _get_app_context():
            vid = os.path.basename(str(video_filename)) if video_filename else ''
            
            # 원본 결과 찾기 (전처리 방법이 없는 원본 결과)
            original = PlateResult.query.filter_by(
                plate_number=plate_number,
                video_filename=vid
            ).first()
            
            if not original:
                # 원본 결과가 없으면 먼저 생성
                original = PlateResult(
                    plate_number=plate_number,
                    video_filename=vid,
                    detected_at=datetime.now()
                )
                db.session.add(original)
                db.session.flush()  # ID 생성을 위해 flush
            
            # 기존 전처리 결과 확인
            existing_preprocess = PlatePreprocessResult.query.filter_by(
                result_id=original.id,
                preprocess_method=preprocess
            ).first()
            
            if existing_preprocess:
                # 업데이트
                existing_preprocess.corrected_text = corrected_text
                if elapsed_ms is not None:
                    existing_preprocess.elapsed_ms = elapsed_ms
                if ground_truth is not None:
                    existing_preprocess.ground_truth = ground_truth
                if is_correct is not None:
                    existing_preprocess.is_correct = is_correct
                if img_path:
                    existing_preprocess.img_path = img_path
                existing_preprocess.updated_at = datetime.now()
            else:
                # 새로 추가
                new_preprocess = PlatePreprocessResult(
                    result_id=original.id,
                    preprocess_method=preprocess,
                    corrected_text=corrected_text,
                    elapsed_ms=elapsed_ms,
                    ground_truth=ground_truth,
                    is_correct=is_correct,
                    img_path=img_path
                )
                db.session.add(new_preprocess)
            
            db.session.commit()
    except Exception as e:
        try:
            db.session.rollback()
        except:
            pass
        print(f"❌ DB 전처리 결과 추가 오류: {e}")


def get_all_results():
    """
    모든 원본 결과 조회 (전처리 결과는 각 원본에 포함)
    
    CSV 형식과의 호환성을 위해 딕셔너리 리스트 반환
    """
    try:
        with _get_app_context():
            results = []
            
            # 모든 원본 결과와 전처리 결과 조회
            for plate_result in PlateResult.query.all():
                # 원본 결과
                result_dict = {
                    'id': plate_result.id,
                    'result_id': plate_result.id,
                    '인식번호판': plate_result.plate_number,
                    '정답번호판': plate_result.ground_truth or '',
                    '정오여부': (
                        '정답' if plate_result.is_correct is True
                        else ('오답' if plate_result.is_correct is False else '미입력')
                    ),
                    '신뢰도': plate_result.confidence or '',
                    '투표수': plate_result.vote_count or '',
                    '확정여부': '확정' if plate_result.is_fixed else '미확정',
                    '전처리방법': '',
                    '보정후번호판': '',
                    '처리시간(ms)': '',
                    '인식시각': plate_result.detected_at.strftime('%Y-%m-%d %H:%M:%S'),
                    '영상파일': plate_result.video_filename or '',
                    '이미지경로': plate_result.img_path or '',
                }
                results.append(result_dict)
                
                # 전처리 결과들
                for preprocess in plate_result.preprocess_results:
                    preprocess_dict = {
                        'id': preprocess.id,
                        '인식번호판': plate_result.plate_number,
                        '정답번호판': preprocess.ground_truth or '',
                        '정오여부': (
                            '정답' if preprocess.is_correct is True
                            else ('오답' if preprocess.is_correct is False else '미입력')
                        ),
                        '신뢰도': '',
                        '투표수': '',
                        '확정여부': '',
                        '전처리방법': preprocess.preprocess_method,
                        '보정후번호판': preprocess.corrected_text,
                        '처리시간(ms)': preprocess.elapsed_ms or '',
                        '인식시각': preprocess.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
                        '영상파일': plate_result.video_filename or '',
                        '이미지경로': preprocess.img_path or '',
                    }
                    results.append(preprocess_dict)
            
            return results
    except Exception as e:
        print(f"❌ DB 조회 오류: {e}")
        return []
