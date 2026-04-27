# backend_flask/modules/monitoring/its_helper.py
# ITS CCTV API + Overpass 도로 선형 API 호출 및 캐싱 헬퍼

import os
import json                  # 파일 캐시 직렬화/역직렬화
import time
import requests
from pathlib import Path     # 파일 캐시 경로 조작

# ── 상수 ──────────────────────────────────────────────────────────────────────

ITS_API_KEY  = os.getenv('ITS_API_KEY', '8fc75e2a3b1c413f8111579275a4a6fa')
ITS_CCTV_URL = 'https://openapi.its.go.kr:9443/cctvInfo'

# Overpass API 공개 미러 목록 — 앞에서부터 순서대로 시도하고 성공하면 즉시 사용
# overpass-api.de 가 느리거나 타임아웃 시 다음 미러로 자동 전환된다.
OVERPASS_ENDPOINTS = [
    'https://overpass-api.de/api/interpreter',           # 1순위: 공식 서버 (독일)
    'https://overpass.kumi.systems/api/interpreter',      # 2순위: kumi.systems EU 미러
    'https://overpass.openstreetmap.fr/api/interpreter',  # 3순위: OpenStreetMap 프랑스 미러
]

# 도로 선형 파일 캐시 저장 경로 (서버 재시작 후에도 데이터 유지)
# 경로: backend_flask/modules/monitoring/road_geo_cache/{road_key}.json
ROAD_GEO_CACHE_DIR = Path(__file__).parent / 'road_geo_cache'

# 고속도로별 좌표 범위 및 OSM 검색 키워드
ROAD_CONFIG = {
    'gyeongbu': {
        'label': '경부고속도로',
        'osm_name':  '경부고속도로',   # 하위 호환용 단일 이름 (get_road_geometry 내부 사용)
        'osm_names': ['경부고속도로'],  # Overpass 쿼리에 사용할 이름 목록 (지선 포함)
        'its_name_keywords': ['경부'],  # cctvname 필터
        'bounds': {'minX': 126.8, 'maxX': 129.2, 'minY': 35.0, 'maxY': 37.6},
        'type': 'ex',
    },
    'gyeongin': {
        'label': '경인고속도로',
        'osm_name':  '경인고속도로',
        # 제2경인고속도로(Route 110, 시흥·광명 경유)는 OSM에 별도 이름으로 등록됨
        # ITS 모니터링 카메라는 두 노선 모두 포함하므로 Overpass 쿼리도 두 이름 검색
        'osm_names': ['경인고속도로', '제2경인고속도로'],
        'its_name_keywords': ['경인'],
        'bounds': {'minX': 126.6, 'maxX': 127.1, 'minY': 37.3, 'maxY': 37.6},
        'type': 'ex',
    },
    'seohae': {
        'label': '서해안고속도로',
        'osm_name':  '서해안고속도로',
        'osm_names': ['서해안고속도로'],
        'its_name_keywords': ['서해안', '서해'],
        'bounds': {'minX': 126.2, 'maxX': 127.0, 'minY': 34.8, 'maxY': 37.6},
        'type': 'ex',
    },
    'jungang': {
        'label': '중앙고속도로',
        'osm_name':  '중앙고속도로',
        'osm_names': ['중앙고속도로'],
        'its_name_keywords': ['중앙'],
        'bounds': {'minX': 127.8, 'maxX': 129.2, 'minY': 35.5, 'maxY': 37.7},
        'type': 'ex',
    },
    'youngdong': {
        'label': '영동고속도로',
        'osm_name':  '영동고속도로',
        # ITS 영동 카메라: 영동고속도로(Route 50) 인천기점→판교→여주→원주→강릉
        # 광주원주고속도로(Route 52, "[제2영동선]" 표기) 구간은
        # patch_youngdong_route52.py 로 youngdong.json 에 별도 병합 (타임아웃 방지)
        'osm_names': ['영동고속도로'],
        'its_name_keywords': ['영동'],
        # minX=126.5: 인천기점(lng≈126.69) 포함
        # 제2영동선은 127.2~128.0E, 37.2~37.5N 범위 → 동일 bbox 안에 포함됨
        'bounds': {'minX': 126.5, 'maxX': 129.0, 'minY': 37.1, 'maxY': 37.9},
        'type': 'ex',
    },
}

# ── 메모리 캐시 ───────────────────────────────────────────────────────────────

_cctv_cache   = {}   # { road_key: {'data': [...], 'expires': timestamp} }
_geo_cache    = {}   # { road_key: {'data': geojson, 'expires': timestamp} }
CCTV_TTL      = 60           # 60초 — ITS URL은 시간제한 토큰이므로 짧게 유지
GEO_TTL       = 86400 * 7   # 7일 (도로 선형은 거의 안 바뀜)


# ── IC 이름 파싱 ──────────────────────────────────────────────────────────────

def _parse_ic_name(cctvname: str) -> str:
    """
    cctvname에서 IC/JC/분기점 이름을 추출한다.
    예: "경부선 판교JC 상행 1"  →  "판교JC"
        "경부선_수원신갈IC_하행" →  "수원신갈IC"
    """
    name = cctvname.replace('_', ' ')
    tokens = name.split()
    for token in tokens:
        if any(k in token for k in ('IC', 'JC', '분기점', '요금소', '휴게소', 'TG')):
            return token
    # IC/JC 키워드 없으면 두 번째 토큰 반환 (도로명 다음 위치명)
    return tokens[1] if len(tokens) > 1 else cctvname


def _parse_direction(cctvname: str) -> str:
    name = cctvname.replace('_', ' ')
    if '상행' in name or '부산' in name:
        return '상행'
    if '하행' in name or '서울' in name:
        return '하행'
    return ''


# ── ITS CCTV 목록 조회 ────────────────────────────────────────────────────────

def get_cctv_list(road_key: str) -> list:
    """
    ITS API에서 CCTV 목록을 조회해 반환한다. 결과는 메모리 캐시된다.

    Returns:
        [
          {
            camera_id, name, url, lat, lng,
            ic_name, direction, road_key
          },
          ...
        ]
        위도 내림차순 정렬 (서울→부산 방향)
    """
    now = time.time()
    cached = _cctv_cache.get(road_key)
    if cached and cached['expires'] > now:
        return cached['data']

    cfg = ROAD_CONFIG.get(road_key)
    if not cfg:
        return []

    params = {
        'apiKey':   ITS_API_KEY,
        'type':     cfg['type'],
        'cctvType': '1',   # 1=실시간 스트리밍
        'minX':     cfg['bounds']['minX'],
        'maxX':     cfg['bounds']['maxX'],
        'minY':     cfg['bounds']['minY'],
        'maxY':     cfg['bounds']['maxY'],
        'getType':  'json',
    }

    try:
        resp = requests.get(ITS_CCTV_URL, params=params, timeout=10)
        resp.raise_for_status()
        raw_list = resp.json().get('response', {}).get('data', [])
    except Exception as e:
        print(f"⚠️ ITS API 오류 ({road_key}): {e}")
        return _cctv_cache.get(road_key, {}).get('data', [])   # 캐시 만료여도 반환

    keywords = cfg['its_name_keywords']
    result = []
    seen_ids = set()

    for item in raw_list:
        cname = item.get('cctvname', '')
        # 해당 도로 키워드 필터
        if not any(kw in cname for kw in keywords):
            continue

        url = item.get('cctvurl', '').strip()
        if not url:
            continue

        lat = float(item.get('coordy', 0))
        lng = float(item.get('coordx', 0))
        if lat == 0 or lng == 0:
            continue

        ic_name   = _parse_ic_name(cname)
        direction = _parse_direction(cname)

        # 고유 ID 생성 (cctvname 기반)
        camera_id = f"{road_key}_{cname.replace(' ', '_').replace('/', '_')}"
        if camera_id in seen_ids:
            continue
        seen_ids.add(camera_id)

        result.append({
            'camera_id': camera_id,
            'name':      cname,
            'url':       url,
            'lat':       lat,
            'lng':       lng,
            'ic_name':   ic_name,
            'direction': direction,
            'road_key':  road_key,
        })

    # 위도 내림차순 정렬 (서울(높은 위도) → 부산(낮은 위도))
    result.sort(key=lambda x: x['lat'], reverse=True)

    _cctv_cache[road_key] = {'data': result, 'expires': now + CCTV_TTL}
    return result


def get_ic_list(road_key: str) -> list:
    """
    CCTV 목록에서 IC 이름 목록을 중복 제거 후 순서대로 반환.
    (드롭다운용)
    """
    cameras = get_cctv_list(road_key)
    seen = set()
    ics  = []
    for cam in cameras:   # 이미 위도 내림차순 정렬됨
        ic = cam['ic_name']
        if ic not in seen:
            seen.add(ic)
            ics.append(ic)
    return ics


def get_cameras_in_range(road_key: str, start_ic: str, end_ic: str) -> list:
    """
    start_ic ~ end_ic 사이의 CCTV 목록을 반환.
    CCTV 목록은 위도 내림차순(서울→부산)이므로,
    start_ic가 먼저 나오고 end_ic가 나중에 나온다고 가정한다.
    """
    cameras = get_cctv_list(road_key)
    ic_names = [c['ic_name'] for c in cameras]

    # start/end IC의 첫 번째 인덱스 탐색
    try:
        start_idx = next(i for i, c in enumerate(cameras) if c['ic_name'] == start_ic)
    except StopIteration:
        return []
    try:
        end_idx = next(i for i, c in enumerate(cameras) if c['ic_name'] == end_ic)
    except StopIteration:
        return []

    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx

    return cameras[start_idx: end_idx + 1]


# ── Overpass 도로 선형 조회 ───────────────────────────────────────────────────

def get_road_geo_cached(road_key: str) -> dict | None:
    """
    메모리·파일 캐시만 확인하고 즉시 반환한다. Overpass 호출은 하지 않는다.

    파일 캐시가 있으면 메모리에도 올려두고 GeoJSON을 반환한다.
    캐시가 없으면 None을 반환한다 (호출자가 백그라운드 fetch를 별도로 처리해야 함).
    """
    now = time.time()

    # 메모리 캐시 확인 (is_failure 캐시는 건너뜀)
    cached = _geo_cache.get(road_key)
    if cached and cached['expires'] > now and not cached.get('is_failure'):
        return cached['data']                           # 메모리 히트 → 즉시 반환

    # 파일 캐시 확인 (generate_road_geo_cache.py 로 생성된 파일)
    cache_file = ROAD_GEO_CACHE_DIR / f'{road_key}.json'
    if cache_file.exists():
        try:
            with cache_file.open('r', encoding='utf-8') as f:
                geo = json.load(f)                      # 파일 읽기
            if geo.get('features'):                     # 유효한 데이터인지 확인
                _geo_cache[road_key] = {                # 메모리 캐시에도 올려둠
                    'data': geo, 'expires': now + GEO_TTL
                }
                print(f"🗂️ 파일 캐시 로드 ({road_key}): {len(geo['features'])}개 way")
                return geo                              # 파일 히트 → 반환
        except Exception as e:
            print(f"⚠️ 파일 캐시 읽기 실패 ({road_key}): {e}")

    return None                                         # 캐시 없음 → None


def get_road_geometry(road_key: str) -> dict:
    """
    도로 선형 GeoJSON을 반환한다. 3단계 캐시 전략을 사용한다.

    조회 우선순위:
      1. 메모리 캐시 (성공 캐시만) — 가장 빠름, 서버 재시작 시 유실
      2. 파일 캐시 — 서버 재시작 후에도 유지
      3. Overpass API (미러 순차 시도) — 네트워크 요청

    실패 캐시(is_failure=True)는 우선순위 1에서 건너뛰고 2→3 순서로 계속 시도한다.
    모든 미러 실패 시 is_failure=True 로 60초 캐시 → 재시도 폭풍 방지.

    Returns:
        GeoJSON FeatureCollection
        { "type": "FeatureCollection", "features": [LineString Feature, ...] }
    """
    now = time.time()

    # ── 1단계: 메모리 캐시 (성공한 결과만 즉시 반환) ──────────────────────────
    cached = _geo_cache.get(road_key)
    if cached and cached['expires'] > now and not cached.get('is_failure'):
        # is_failure 플래그가 없는 캐시만 즉시 반환
        # is_failure=True 이면 이 분기를 건너뛰고 파일/Overpass 재시도로 진행
        return cached['data']

    # ── 2단계: 파일 캐시 (서버 재시작 후에도 유지) ───────────────────────────
    cache_file = ROAD_GEO_CACHE_DIR / f'{road_key}.json'
    if cache_file.exists():
        try:
            with cache_file.open('r', encoding='utf-8') as f:
                geo = json.load(f)                          # JSON 파일 읽기
            if geo.get('features'):                         # 유효한 데이터인지 확인
                _geo_cache[road_key] = {                    # 메모리 캐시에도 적재
                    'data': geo, 'expires': now + GEO_TTL
                }
                print(f"🗂️ 도로 선형 파일 캐시 로드 ({road_key}): "
                      f"{len(geo['features'])}개 way")
                return geo                                   # 파일 캐시 히트 → 반환
        except Exception as e:
            print(f"⚠️ 파일 캐시 로드 실패 ({road_key}): {e}")
            # 파일 손상 시 3단계(Overpass)로 진행

    cfg = ROAD_CONFIG.get(road_key)
    if not cfg:
        return {'type': 'FeatureCollection', 'features': []}

    # osm_names: 지선까지 포함한 OSM 이름 목록 (없으면 osm_name 단일 항목으로 폴백)
    osm_names = cfg.get('osm_names') or [cfg['osm_name']]

    # Overpass 쿼리: 전역 bounds 를 모든 이름에 공통 적용 (넓은 범위로 가져온 뒤
    # 좌표 레벨 클리핑으로 원하는 구간만 남긴다 — way-level bbox 는 부정확함)
    osm_name_bounds = cfg.get('osm_name_bounds', {})    # 이름별 좌표 클리핑 범위
    global_bounds   = cfg.get('bounds')                  # Overpass 요청 범위 (넓게)

    if global_bounds:
        # Overpass way bbox 포맷: (minLat,minLon,maxLat,maxLon) = (minY,minX,maxY,maxX)
        global_bbox_str = (
            f'({global_bounds["minY"]},{global_bounds["minX"]}'
            f',{global_bounds["maxY"]},{global_bounds["maxX"]})'
        )
    else:
        global_bbox_str = ''

    name_lines = '\n'.join(
        f'  way["name"="{n}"]["highway"~"motorway|trunk|motorway_link"]{global_bbox_str};'
        for n in osm_names
    )

    query = f"""
[out:json][timeout:60];
(
{name_lines}
);
out geom;
"""

    # ── 3단계: Overpass 미러 순차 시도 ──────────────────────────────────────
    elements  = None    # 성공 시 elements 리스트 저장
    last_err  = None    # 마지막 실패 예외 (로그용)

    # 백엔드 서버 IP가 Overpass에서 거부(406/403)될 경우를 대비해
    # Overpass가 기대하는 헤더를 명시적으로 설정한다.
    # - User-Agent: 자동화 봇 차단 우회 (Overpass 측이 식별할 수 있도록 명시)
    # - Accept: application/json 명시 (406 Not Acceptable 방지)
    # - Content-Type: form 데이터 전송 방식 명시
    _overpass_headers = {
        'User-Agent':   'TADS-TrafficMonitor/1.0 (traffic monitoring; contact: tads@example.com)',
        'Accept':       'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = requests.post(
                endpoint,
                data={'data': query},
                headers=_overpass_headers,
                timeout=65,          # 미러당 65초 (쿼리 timeout:60 + 네트워크 여유 5초)
            )
            resp.raise_for_status()
            elements = resp.json().get('elements', [])
            break                    # 성공 → 루프 탈출, 나머지 미러 시도 생략
        except Exception as e:
            last_err = e
            print(f"⚠️ Overpass 오류 ({road_key}, {endpoint.split('/')[2]}): {e}")
            continue                 # 다음 미러로 전환

    # ── 모든 미러 실패 ─────────────────────────────────────────────────────
    if elements is None:
        print(f"❌ Overpass 전체 미러 실패 ({road_key}): {last_err}")
        empty = {'type': 'FeatureCollection', 'features': []}
        # is_failure=True: monitoring.py가 이 캐시를 보고 background retry를 허용
        # TTL 60초: 너무 짧으면 재시도 폭풍, 너무 길면 회복 지연 — 1분이 적정
        _geo_cache[road_key] = {
            'data': empty, 'expires': now + 60, 'is_failure': True
        }
        return empty

    # ── 성공: GeoJSON FeatureCollection 조립 (좌표 레벨 클리핑 포함) ───────────
    # Way 레벨 bbox 는 "way 가 bbox 에 걸치기만 해도 포함"하므로 경계를 넘는 구간이
    # 잘리지 않는다. 좌표 레벨 클리핑은 각 노드를 직접 필터해 정확히 잘라낸다.
    # 예: 수도권제1순환고속도로 북쪽 호(서울 상단)는 위도 37.48N 이상 → 클리핑으로 제거
    features = []
    for el in elements:
        if el.get('type') != 'way':    # way 타입만 처리 (node, relation 제외)
            continue
        geometry = el.get('geometry', [])
        if len(geometry) < 2:          # 좌표가 2개 미만이면 선분 불가 → 건너뜀
            continue

        el_name = el.get('tags', {}).get('name', '')   # 이 way 의 실제 OSM 이름
        clip_b  = osm_name_bounds.get(el_name)         # 이름별 좌표 클리핑 범위

        coords = [[pt['lon'], pt['lat']] for pt in geometry]  # [경도, 위도] 변환

        if clip_b:
            # ── All-or-nothing 방식 ────────────────────────────────────────────
            # 좌표를 부분적으로 잘라내면 bbox 경계에 걸친 way (북부 링 시작 구간)가
            # 짧은 토막으로 남아 여전히 그려진다.
            # 따라서 bbox 밖 노드가 하나라도 있는 way 는 통째로 버린다.
            # (남쪽 호는 모든 노드가 bbox 안에 있으므로 정상 포함됨)
            if any(
                c[0] < clip_b['minX'] or c[0] > clip_b['maxX'] or
                c[1] < clip_b['minY'] or c[1] > clip_b['maxY']
                for c in coords
            ):
                continue               # 이 way 통째로 버림 → 북부 링 제거

        if len(coords) < 2:            # 좌표가 2개 미만이면 선분 불가
            continue

        features.append({
            'type': 'Feature',
            'properties': {'osm_id': el.get('id'), 'name': el_name},
            'geometry': {'type': 'LineString', 'coordinates': coords},
        })

    geo = {'type': 'FeatureCollection', 'features': features}

    # 메모리 캐시 저장 (7일 TTL, is_failure 없음 = 성공 캐시)
    _geo_cache[road_key] = {'data': geo, 'expires': now + GEO_TTL}

    # ── 파일 캐시 저장 (서버 재시작 후 Overpass 불필요) ──────────────────────
    try:
        ROAD_GEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)  # 폴더 생성 (없을 경우)
        with cache_file.open('w', encoding='utf-8') as f:
            json.dump(geo, f, ensure_ascii=False)               # UTF-8 JSON 저장
        print(f"🗺️ 도로 선형 Overpass 성공 → 파일 저장 ({road_key}): "
              f"{len(features)}개 way → {cache_file.name}")
    except Exception as e:
        print(f"⚠️ 파일 캐시 저장 실패 ({road_key}): {e}")
        # 저장 실패해도 메모리 캐시는 유효하므로 계속 진행

    return geo


# ── 스트림 URL 탐침 (진단용) ─────────────────────────────────────────────────

# MPEG-TS 스트림의 첫 바이트 (sync byte 0x47)
_MPEGTS_SYNC = b'\x47'
# HLS m3u8 플레이리스트의 시작 시그니처
_M3U8_MAGIC = b'#EXTM3U'


def _detect_format(first_bytes: bytes) -> str:
    """
    스트림 첫 바이트를 보고 포맷을 추정한다.
    ITS 스트림은 보통 MPEG-TS 또는 HLS(m3u8) 중 하나다.

    Returns:
        'mpegts'  — MPEG-TS sync byte(0x47) 로 시작하는 경우
        'm3u8'    — HLS 플레이리스트 (#EXTM3U) 로 시작하는 경우
        'unknown' — 그 외
    """
    if first_bytes and first_bytes[:1] == _MPEGTS_SYNC:
        return 'mpegts'   # MPEG-TS: cv2.VideoCapture 직접 열기 가능
    if first_bytes and first_bytes[:7] == _M3U8_MAGIC:
        return 'm3u8'     # HLS: FFMPEG가 플레이리스트를 파싱해 열어야 함
    return 'unknown'


def probe_stream_url(url: str) -> dict:
    """
    ITS CCTV 스트림 URL 을 HTTP GET 으로 탐침해 진단 정보를 반환한다.
    cv2.VideoCapture 가 실패한 이유를 파악하기 위해 사용한다.

    탐침 항목:
        url              — 입력 URL (그대로 반환)
        http_status      — HTTP 응답 코드 (200, 403, 404 …)
        content_type     — Content-Type 헤더 값
        content_length   — Content-Length 헤더 값 (없으면 '(없음)')
        server           — Server 헤더 값
        first_bytes_hex  — 응답 첫 16바이트 16진수 문자열
        first_bytes_ascii— 응답 첫 16바이트 ASCII 가시 문자열 (비가시 → '.')
        stream_format    — 'mpegts' | 'm3u8' | 'unknown'
        http_error       — HTTP 연결 실패 시 예외 메시지 (접속 성공 시 미포함)

    Returns:
        dict  위 항목들로 이루어진 진단 딕셔너리
    """
    result: dict = {'url': url}

    # ITS 스트리밍 서버는 브라우저 UA(Mozilla/5.0)를 403으로 막는다.
    # cv2.VideoCapture 가 내부적으로 쓰는 FFMPEG UA 를 그대로 사용해야
    # 실제 cv2 동작과 같은 조건으로 탐침할 수 있다.
    _FFMPEG_UA = 'Lavf/58.76.100'

    try:
        resp = requests.get(
            url,
            stream=True,     # 전체 다운로드 없이 헤더+첫 바이트만 읽음
            timeout=5,       # 5초 이내 응답 없으면 포기
            headers={'User-Agent': _FFMPEG_UA},
        )

        result['http_status']    = resp.status_code
        result['content_type']   = resp.headers.get('Content-Type',   '(없음)')
        result['content_length'] = resp.headers.get('Content-Length', '(없음)')
        result['server']         = resp.headers.get('Server',         '(없음)')

        # 첫 16바이트로 스트림 포맷 추정 (이후 바이트는 읽지 않아 대역폭 절약)
        first = next(resp.iter_content(chunk_size=16), b'')
        result['first_bytes_hex']   = first.hex()
        result['first_bytes_ascii'] = ''.join(
            chr(b) if 32 <= b < 127 else '.' for b in first
        )
        result['stream_format'] = _detect_format(first)

        resp.close()

    except Exception as exc:
        # 연결 자체가 실패한 경우 (타임아웃, DNS 실패, 접속 거부 등)
        result['http_error'] = str(exc)

    return result


def probe_batch(cameras: list) -> dict:
    """
    카메라 목록 전체를 순서대로 HTTP 탐침해 결과를 집계한다.
    단일 카메라 탐침(probe_stream_url)을 반복 호출하고,
    stream_format 별로 카운트를 집계해 패턴 파악을 돕는다.

    Args:
        cameras: [{'camera_id': str, 'name': str, 'url': str, ...}, ...]
                 get_cctv_list() 또는 get_cameras_in_range() 반환값과 동일한 구조

    Returns:
        {
          'total':   int,             — 탐침한 카메라 수
          'summary': {format: count}  — 포맷별 집계 (mpegts/m3u8/unknown/error)
          'cameras': [                — 카메라별 상세 결과
            {
              'camera_id':     str,
              'name':          str,
              'url':           str,
              'http_status':   int,    (HTTP 실패 시 없음)
              'content_type':  str,    (HTTP 실패 시 없음)
              'stream_format': str,    (HTTP 실패 시 'error')
              'first_bytes_hex': str,  (HTTP 실패 시 없음)
              'diagnosis':     str,
              'http_error':    str,    (접속 실패 시만 포함)
            },
            ...
          ]
        }
    """
    summary: dict = {}   # stream_format → 카운트
    cam_results   = []   # 카메라별 탐침 결과 목록

    for cam in cameras:
        url   = cam.get('url', '')
        probe = probe_stream_url(url)   # HTTP 탐침 실행

        # HTTP 접속 실패 시 포맷을 'error' 로 분류
        fmt = 'error' if 'http_error' in probe else probe.get('stream_format', 'unknown')

        # 포맷별 집계
        summary[fmt] = summary.get(fmt, 0) + 1

        # 카메라 ID / 이름을 탐침 결과에 병합해 한 눈에 볼 수 있게 한다
        entry = {
            'camera_id': cam.get('camera_id', ''),
            'name':      cam.get('name',      ''),
            'url':       url,
        }
        entry.update(probe)                   # http_status, content_type 등 탐침 결과 전부 포함
        entry['stream_format'] = fmt          # 'error' 오버라이드 반영
        cam_results.append(entry)

    return {
        'total':   len(cameras),   # 탐침 대상 총 카메라 수
        'summary': summary,        # 포맷 패턴 집계
        'cameras': cam_results,    # 카메라별 상세 결과
    }
