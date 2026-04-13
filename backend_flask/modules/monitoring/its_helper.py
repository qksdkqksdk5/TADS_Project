# backend_flask/modules/monitoring/its_helper.py
# ITS CCTV API + Overpass 도로 선형 API 호출 및 캐싱 헬퍼

import os
import time
import requests

# ── 상수 ──────────────────────────────────────────────────────────────────────

ITS_API_KEY = os.getenv('ITS_API_KEY', '8fc75e2a3b1c413f8111579275a4a6fa')
ITS_CCTV_URL = 'https://openapi.its.go.kr:9443/cctvInfo'
OVERPASS_URL = 'https://overpass-api.de/api/interpreter'

# 고속도로별 좌표 범위 및 OSM 검색 키워드
ROAD_CONFIG = {
    'gyeongbu': {
        'label': '경부고속도로',
        'osm_name': '경부고속도로',
        'its_name_keywords': ['경부'],   # cctvname 필터
        'bounds': {'minX': 126.8, 'maxX': 129.2, 'minY': 35.0, 'maxY': 37.6},
        'type': 'ex',   # ex=고속도로, ex+국도 등
    },
    'gyeongin': {
        'label': '경인고속도로',
        'osm_name': '경인고속도로',
        'its_name_keywords': ['경인'],
        'bounds': {'minX': 126.6, 'maxX': 127.1, 'minY': 37.3, 'maxY': 37.6},
        'type': 'ex',
    },
    'seohae': {
        'label': '서해안고속도로',
        'osm_name': '서해안고속도로',
        'its_name_keywords': ['서해안', '서해'],
        'bounds': {'minX': 126.2, 'maxX': 127.0, 'minY': 34.8, 'maxY': 37.6},
        'type': 'ex',
    },
    'jungang': {
        'label': '중앙고속도로',
        'osm_name': '중앙고속도로',
        'its_name_keywords': ['중앙'],
        'bounds': {'minX': 127.8, 'maxX': 129.2, 'minY': 35.5, 'maxY': 37.7},
        'type': 'ex',
    },
    'youngdong': {
        'label': '영동고속도로',
        'osm_name': '영동고속도로',
        'its_name_keywords': ['영동'],
        'bounds': {'minX': 126.8, 'maxX': 128.8, 'minY': 37.1, 'maxY': 37.7},
        'type': 'ex',
    },
}

# ── 메모리 캐시 ───────────────────────────────────────────────────────────────

_cctv_cache   = {}   # { road_key: {'data': [...], 'expires': timestamp} }
_geo_cache    = {}   # { road_key: {'data': geojson, 'expires': timestamp} }
CCTV_TTL      = 3600         # 1시간
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
    print(f"📡 ITS CCTV 캐시 갱신 ({road_key}): {len(result)}개")
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

def get_road_geometry(road_key: str) -> dict:
    """
    Overpass API에서 도로 선형 GeoJSON을 조회해 반환한다. 결과는 메모리 캐시된다.

    Returns:
        GeoJSON FeatureCollection (LineString features)
        {
          "type": "FeatureCollection",
          "features": [
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[lng, lat], ...]}}
          ]
        }
    """
    now = time.time()
    cached = _geo_cache.get(road_key)
    if cached and cached['expires'] > now:
        return cached['data']

    cfg = ROAD_CONFIG.get(road_key)
    if not cfg:
        return {'type': 'FeatureCollection', 'features': []}

    osm_name = cfg['osm_name']
    query = f"""
[out:json][timeout:30];
(
  way["name"="{osm_name}"]["highway"~"motorway|trunk|motorway_link"];
);
out geom;
"""
    try:
        resp = requests.post(OVERPASS_URL, data={'data': query}, timeout=35)
        resp.raise_for_status()
        elements = resp.json().get('elements', [])
    except Exception as e:
        print(f"⚠️ Overpass API 오류 ({road_key}): {e}")
        # 실패 결과도 1800초(30분) 캐시 → Overpass 504 재시도 폭풍 방지
        empty = {'type': 'FeatureCollection', 'features': []}
        _geo_cache[road_key] = {'data': empty, 'expires': now + 1800}
        return empty

    features = []
    for el in elements:
        if el.get('type') != 'way':
            continue
        geometry = el.get('geometry', [])
        if len(geometry) < 2:
            continue
        coords = [[pt['lon'], pt['lat']] for pt in geometry]
        features.append({
            'type': 'Feature',
            'properties': {'osm_id': el.get('id'), 'name': osm_name},
            'geometry': {'type': 'LineString', 'coordinates': coords},
        })

    geo = {'type': 'FeatureCollection', 'features': features}
    _geo_cache[road_key] = {'data': geo, 'expires': now + GEO_TTL}
    print(f"🗺️ Overpass 도로 선형 캐시 갱신 ({road_key}): {len(features)}개 way")
    return geo
