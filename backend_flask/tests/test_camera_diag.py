# test_camera_diag.py
# 특정 카메라 URL을 cv2로 열어 FFMPEG 에러만 뽑아내는 단독 진단 스크립트.
# Flask 서버 없이 단독 실행 가능.
# 사용법: python test_camera_diag.py

import os
import sys
import ctypes
import tempfile
import requests

# ── 테스트할 카메라 키워드 ─────────────────────────────────────────────────────
# Flask에서 성공하는 대룡과 실패하는 노포교·부산영업소를 함께 테스트한다.
# 대룡은 위도가 높아 카메라 목록에서 항상 먼저 열리므로, 동시 연결 테스트의
# "먼저 열리는 카메라" 역할을 한다.
TARGET_KEYWORDS = ['대룡', '노포교', '부산영업소']

# ── ITS API 설정 ───────────────────────────────────────────────────────────────
ITS_API_KEY = '8fc75e2a3b1c413f8111579275a4a6fa'
ITS_CCTV_URL = 'https://openapi.its.go.kr:9443/cctvInfo'


def fetch_urls(keywords):
    """ITS API에서 신선한 URL을 가져온다."""
    params = {
        'apiKey':   ITS_API_KEY,
        'type':     'ex',
        'cctvType': '1',
        'minX': 126.8, 'maxX': 129.2,
        'minY': 35.0,  'maxY': 37.6,
        'getType':  'json',
    }
    try:
        resp = requests.get(ITS_CCTV_URL, params=params, timeout=10)
        items = resp.json().get('response', {}).get('data', [])
    except Exception as e:
        print(f"ITS API 오류: {e}")
        return []

    results = []
    for item in items:
        name = item.get('cctvname', '')
        url  = item.get('cctvurl',  '').strip()
        if not url:
            continue
        for kw in keywords:
            if kw in name:
                results.append({'name': name, 'url': url})
                break
    return results


def capture_ffmpeg_stderr(fn):
    """
    fn() 실행 중 C 레벨 stderr(FFMPEG 로그)를 파일로 캡처해 문자열로 반환한다.
    Python의 sys.stderr 리디렉션으로는 C 확장의 출력을 잡을 수 없어
    OS 파일 디스크립터 수준에서 직접 교체한다.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.log', mode='w')
    tmp_path = tmp.name
    tmp.close()

    # stderr FD(2)를 임시 파일로 교체
    tmp_fd  = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    old_fd  = os.dup(2)
    os.dup2(tmp_fd, 2)
    os.close(tmp_fd)

    try:
        result = fn()
    finally:
        # stderr 복구
        os.dup2(old_fd, 2)
        os.close(old_fd)

    # 캡처된 내용 읽기
    with open(tmp_path, 'r', errors='replace') as f:
        log = f.read()
    os.unlink(tmp_path)
    return result, log


def test_camera(name, url):
    """카메라 URL을 cv2로 열고 FFMPEG 출력을 캡처해 출력한다."""
    import cv2

    print(f"\n{'='*60}")
    print(f"카메라: {name}")
    print(f"URL   : {url[:80]}...")
    print(f"{'='*60}")

    # FFMPEG 로그 레벨을 최대로 올려 에러 메시지 확보
    os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'   # ERROR만 출력 (DEBUG 아님)

    def _open():
        cap = cv2.VideoCapture(url)
        opened = cap.isOpened()
        if opened:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            return True, f"{w}×{h}"
        cap.release()
        return False, ""

    (opened, size), ffmpeg_log = capture_ffmpeg_stderr(_open)

    if opened:
        print(f"✅ 성공: {size} 스트림 열림")
    else:
        print(f"❌ 실패: cv2.VideoCapture 열기 불가")

    # FFMPEG 에러 로그 출력 (빈 줄·중복 제거)
    lines = [l.strip() for l in ffmpeg_log.splitlines() if l.strip()]
    if lines:
        print("\n── FFMPEG 출력 ──────────────────────────────────────")
        for line in lines:
            print(f"  {line}")
    else:
        print("\n── FFMPEG 출력 없음 (에러 메시지가 억제됨) ──────────")
        print("  → 아래 명령어로 다시 실행하면 더 자세한 로그를 볼 수 있습니다:")
        print("    set OPENCV_FFMPEG_CAPTURE_OPTIONS=loglevel;48")
        print("    python test_camera_diag.py")


def test_concurrent(cameras):
    """
    Flask 시나리오 시뮬레이션: 이전 카메라를 닫지 않고 다음 카메라를 순차 열기.
    ITS 서버가 동시 연결 수를 제한하는지 확인한다.

    주의: os.dup2() stderr 캡처를 사용하지 않는다.
    캡처 도중 FFMPEG DLL 재초기화 간섭이 발생해 결과가 오염되기 때문이다.
    대신 cv2.VideoCapture를 직접 호출하고 결과만 확인한다.
    FFMPEG 콘솔 출력은 그대로 터미널에 나타난다.
    """
    import cv2

    print(f"\n{'='*60}")
    print("【동시 연결 테스트】 — Flask 시나리오 재현")
    print("이전 카메라 연결을 닫지 않고 다음 카메라를 엽니다.")
    print("(FFMPEG 로그가 이 아래에 바로 출력됩니다)")
    print(f"{'='*60}")

    open_caps = []   # 열어둔 VideoCapture 목록 (닫지 않고 유지)

    for cam in cameras:
        name = cam['name']
        url  = cam['url']
        held = len(open_caps)   # 현재 열려 있는 연결 수

        print(f"\n[{name}] 열기 시도 — 현재 열려 있는 연결: {held}개")
        print(f"  URL: {url[:70]}...")

        # stderr 캡처 없이 직접 열기 (FFMPEG 로그가 터미널에 바로 출력됨)
        cap = cv2.VideoCapture(url)

        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"  ✅ 성공: {w}×{h}")
            open_caps.append(cap)   # 열어둔 채 목록에 추가
        else:
            print(f"  ❌ 실패 (동시 연결 {held}개 유지 상태에서 실패)")
            cap.release()

    # 테스트 종료 후 모든 연결 닫기
    print(f"\n모든 연결 해제 중 ({len(open_caps)}개)...")
    for cap in open_caps:
        cap.release()
    print("완료")


if __name__ == '__main__':
    print("ITS API에서 신선한 URL 조회 중...")
    cameras = fetch_urls(TARGET_KEYWORDS)

    if not cameras:
        print(f"카메라를 찾지 못했습니다: {TARGET_KEYWORDS}")
        sys.exit(1)

    print(f"테스트 대상: {len(cameras)}대")

    # ── 테스트 1: 순차 열기/닫기 (기존 테스트) ──────────────────────────────
    print(f"\n{'='*60}")
    print("【테스트 1】 순차 열기/닫기 — 카메라마다 열고 즉시 닫음")
    print(f"{'='*60}")
    for cam in cameras:
        test_camera(cam['name'], cam['url'])

    # ── 테스트 2: 동시 연결 (Flask 시나리오) ─────────────────────────────────
    # URL을 새로 가져온다 (테스트 1에서 URL이 만료됐을 수 있으므로)
    print(f"\n\nURL 재조회 중 (신선한 토큰 확보)...")
    cameras2 = fetch_urls(TARGET_KEYWORDS)
    if cameras2:
        test_concurrent(cameras2)
    else:
        print("URL 재조회 실패 — 동시 연결 테스트 건너뜀")

    print(f"\n{'='*60}")
    print("진단 완료")
