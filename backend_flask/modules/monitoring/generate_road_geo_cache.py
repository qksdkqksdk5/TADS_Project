"""
generate_road_geo_cache.py

모든 고속도로의 선형 GeoJSON을 Overpass API에서 한 번 받아
road_geo_cache/ 폴더에 저장하는 1회성 실행 스크립트.

저장 후 Flask 서버를 재시작하면 Overpass를 다시 호출하지 않고
파일에서 즉시 서빙하므로 지도에 도로선이 바로 나타난다.

사용법:
    # backend_flask/ 에서 실행 (monitoring 폴더로 이동할 필요 없음)
    python modules/monitoring/generate_road_geo_cache.py
"""

import json           # JSON 직렬화·파일 저장
import time           # 엔드포인트 간 대기 (레이트 리밋 방지)
import requests       # Overpass HTTP 요청
from pathlib import Path  # 파일 경로 조작

# ── 저장 경로 ──────────────────────────────────────────────────────────────────
# 이 스크립트 위치(monitoring/) 기준으로 road_geo_cache/ 생성
CACHE_DIR = Path(__file__).parent / 'road_geo_cache'
CACHE_DIR.mkdir(parents=True, exist_ok=True)  # 폴더 없으면 생성

# ── 도로 목록 ─────────────────────────────────────────────────────────────────
# its_helper.py 의 ROAD_CONFIG 와 동기화 유지
#
# osm_names : Overpass 에서 검색할 OSM name 태그 목록
# bounds    : Overpass 전역 bbox (minY,minX,maxY,maxX)
#             수도권제1순환고속도로처럼 링 전체를 한 바퀴 도는 도로를 포함할 때
#             서울 전체가 그려지는 문제를 방지하기 위해 반드시 지정한다.
ROAD_CONFIG = {
    'gyeongbu': {
        'osm_names': ['경부고속도로'],                  # 1번 (서울↔부산)
        'bounds':    {'minX': 126.8, 'maxX': 129.2, 'minY': 35.0, 'maxY': 37.6},
    },
    'gyeongin': {
        'osm_names': ['경인고속도로', '제2경인고속도로'],  # 120번·110번 (서울↔인천)
        'bounds':    {'minX': 126.6, 'maxX': 127.1, 'minY': 37.3, 'maxY': 37.6},
    },
    'seohae': {
        'osm_names': ['서해안고속도로'],                # 15번 (서해안 종단)
        'bounds':    {'minX': 126.2, 'maxX': 127.0, 'minY': 34.8, 'maxY': 37.6},
    },
    'jungang': {
        'osm_names': ['중앙고속도로'],                  # 35번 (춘천↔부산)
        'bounds':    {'minX': 127.8, 'maxX': 129.2, 'minY': 35.5, 'maxY': 37.7},
    },
    'youngdong': {
        # 영동고속도로(Route 50): 인천기점→판교→여주→원주→강릉
        # ※ 광주원주고속도로(Route 52)는 타임아웃 방지를 위해 별도 스크립트로 관리
        'osm_names': ['영동고속도로'],
        'bounds':    {'minX': 126.5, 'maxX': 129.0, 'minY': 37.1, 'maxY': 37.9},
    },
}

# ── Overpass 미러 목록 (앞에서부터 순서대로 시도) ─────────────────────────────
ENDPOINTS = [
    'https://overpass-api.de/api/interpreter',           # 공식 (독일)
    'https://overpass.kumi.systems/api/interpreter',     # kumi.systems EU 미러
    'https://overpass.openstreetmap.fr/api/interpreter', # OpenStreetMap 프랑스 미러
]

# ── Overpass 요청 헤더 ─────────────────────────────────────────────────────────
# User-Agent: 자동화 도구임을 명시해 차단 우회
HEADERS = {
    'User-Agent':   'TADS-CacheGenerator/1.0 (one-time setup; contact: tads@example.com)',
    'Accept':       'application/json',
    'Content-Type': 'application/x-www-form-urlencoded',
}


def fetch_road_geo(
    osm_names: list[str],
    bounds: dict | None = None,
    osm_name_bounds: dict | None = None,
    osm_query_bounds: dict | None = None,
) -> dict | None:
    """
    하나 이상의 OSM 이름을 union으로 조회해 GeoJSON으로 변환한다.

    bbox 두 단계 전략:
      1. osm_query_bounds: 이름별 Overpass 쿼리 bbox (큰 노선을 분리해 타임아웃 방지)
         → 없으면 global bounds 사용
      2. osm_name_bounds: 이름별 좌표 레벨 클리핑 (조회 후 원하지 않는 way 제거)
         → all-or-nothing: bbox 밖 노드가 하나라도 있으면 way 통째로 버림
    미러를 순서대로 시도하고 성공하면 즉시 반환.
    모든 미러 실패 시 None 반환.
    """
    _clip_bounds   = osm_name_bounds  or {}  # 조회 후 좌표 클리핑용 (all-or-nothing)
    _query_bounds  = osm_query_bounds or {}  # Overpass 쿼리 시 이름별 bbox

    # 이름마다 적합한 쿼리 bbox 결정 → union으로 합쳐 한 번의 요청으로 처리
    # timeout:60 → 서버 측 처리 제한 (Python timeout=65 과 맞춤)
    name_lines = ''
    for n in osm_names:
        b = _query_bounds.get(n) or bounds   # 이름별 bbox → global bounds 순 폴백
        if b:
            bbox_str = f'({b["minY"]},{b["minX"]},{b["maxY"]},{b["maxX"]})'
        else:
            bbox_str = ''
        name_lines += f'way["name"="{n}"]["highway"~"motorway|trunk|motorway_link"]{bbox_str};'

    query = f'[out:json][timeout:60];({name_lines});out geom;'  # geom = body+geometry (tags 포함)

    for endpoint in ENDPOINTS:                       # 미러 순차 시도
        host = endpoint.split('/')[2]               # 로그용 호스트명 추출
        try:
            print(f'  → {host} 요청 중...')
            resp = requests.post(
                endpoint,
                data={'data': query},               # POST body로 쿼리 전송
                headers=HEADERS,
                timeout=65,                          # Python 소켓 타임아웃 (쿼리 timeout:60 + 여유 5s)
            )
            resp.raise_for_status()                 # HTTP 4xx/5xx → 예외 발생

            elements = resp.json().get('elements', [])  # Overpass 결과 파싱

            # ── 좌표 레벨 클리핑 ────────────────────────────────────────────────
            # Overpass는 way bbox가 쿼리 bbox와 겹치면 way 전체를 반환한다.
            # 즉, maxY=37.48 bbox를 줘도 37.55N 까지 올라가는 way가 포함될 수 있다.
            # 따라서 way 단위 필터 대신 좌표 하나하나를 클리핑 bbox 안에 있는 것만 남긴다.
            features = []
            for el in elements:
                if el.get('type') != 'way':         # way 타입만 처리
                    continue
                geometry = el.get('geometry', [])
                if len(geometry) < 2:               # 좌표가 2개 미만이면 선을 그을 수 없음
                    continue

                # OSM tags에서 이름을 꺼낸다 (ex. '수도권제1순환고속도로')
                el_name = el.get('tags', {}).get('name', '')
                # 이 이름에 대한 클리핑 bbox가 있는지 확인
                clip_b  = _clip_bounds.get(el_name)

                # Overpass는 [lat, lon] 순서 → GeoJSON은 [lon, lat] 순서로 변환
                coords = [[pt['lon'], pt['lat']] for pt in geometry]

                if clip_b:
                    # ── All-or-nothing 방식 ────────────────────────────────────
                    # 좌표를 부분적으로 잘라내면 북부 링의 시작 구간(인천→부천 토막)이
                    # 남아 지도에 잘못된 선이 그려진다.
                    # bbox 밖 노드가 하나라도 있는 way 는 통째로 버린다.
                    # (제2영동선 남쪽 호는 모든 노드가 bbox 안 → 정상 포함)
                    if any(
                        c[0] < clip_b['minX'] or c[0] > clip_b['maxX'] or
                        c[1] < clip_b['minY'] or c[1] > clip_b['maxY']
                        for c in coords
                    ):
                        continue               # 이 way 통째로 버림

                if len(coords) < 2:            # 좌표 2개 미만이면 선분 불가 → 버림
                    continue

                features.append({
                    'type': 'Feature',
                    'properties': {
                        'osm_id': el.get('id'),     # OSM way ID 보존
                        'name':   el_name,          # 도로 이름 보존 (디버깅용)
                    },
                    'geometry': {
                        'type': 'LineString',
                        'coordinates': coords,
                    },
                })

            if features:                            # 유효한 데이터가 있으면 반환
                print(f'  ✅ {host} 성공 — {len(features)}개 way')
                return {'type': 'FeatureCollection', 'features': features}

            print(f'  ⚠️ {host}: 응답은 왔지만 유효한 way 없음')

        except requests.Timeout:
            print(f'  ⏱️ {host}: 타임아웃 (65초 초과) → 다음 미러 시도')
        except requests.HTTPError as e:
            print(f'  ⚠️ {host}: HTTP 오류 {e.response.status_code} → 다음 미러 시도')
        except Exception as e:
            print(f'  ⚠️ {host}: {type(e).__name__}: {e} → 다음 미러 시도')

        time.sleep(2)                               # 미러 간 짧은 대기 (레이트 리밋 분산)

    return None                                     # 모든 미러 실패


def main():
    """
    모든 도로를 순서대로 가져와 파일로 저장한다.
    이미 저장된 파일이 있으면 건너뛴다 (--force 옵션으로 덮어쓰기 가능).
    """
    import sys
    force = '--force' in sys.argv                   # --force 플래그: 기존 파일도 덮어쓰기

    print('=' * 60)
    print('TADS 도로 선형 캐시 생성 스크립트')
    print(f'저장 경로: {CACHE_DIR}')
    print('=' * 60)

    success_count = 0   # 성공한 도로 수
    skip_count    = 0   # 건너뛴 도로 수
    fail_count    = 0   # 실패한 도로 수

    for i, (road_key, cfg) in enumerate(ROAD_CONFIG.items()):
        osm_names        = cfg['osm_names']                  # OSM 검색 이름 목록
        bounds           = cfg.get('bounds')                # 도로 전체 범위 bbox (폴백)
        osm_name_bounds  = cfg.get('osm_name_bounds')       # 이름별 좌표 클리핑 bbox
        osm_query_bounds = cfg.get('osm_query_bounds')      # 이름별 Overpass 쿼리 bbox
        cache_file  = CACHE_DIR / f'{road_key}.json'        # 저장할 파일 경로
        label       = ' + '.join(osm_names)                 # 로그용 이름 (지선 포함)

        print(f'\n[{i + 1}/{len(ROAD_CONFIG)}] {label} ({road_key})')

        # 이미 파일이 있으면 건너뜀 (--force 아닐 때)
        if cache_file.exists() and not force:
            print(f'  ✅ 이미 존재 → 건너뜀 (덮어쓰려면 --force 옵션 사용)')
            skip_count += 1
            continue

        # Overpass에서 GeoJSON 가져오기
        geo = fetch_road_geo(osm_names, bounds, osm_name_bounds, osm_query_bounds)

        if geo:
            # JSON 파일로 저장 (한국어 유니코드 그대로 저장, 들여쓰기 없음 = 용량 최소화)
            cache_file.write_text(
                json.dumps(geo, ensure_ascii=False),
                encoding='utf-8',
            )
            print(f'  💾 저장 완료: {cache_file.name} ({len(geo["features"])}개 way)')
            success_count += 1
        else:
            print(f'  ❌ 모든 미러 실패 — 이 도로는 건너뜀')
            fail_count += 1

        # 도로 간 3초 대기 — Overpass 레이트 리밋 방지
        # (마지막 도로는 대기 불필요)
        if i < len(ROAD_CONFIG) - 1:
            print('  ⏳ 3초 대기 중 (레이트 리밋 방지)...')
            time.sleep(3)

    # ── 결과 요약 ────────────────────────────────────────────────────────────
    print('\n' + '=' * 60)
    print(f'완료  성공: {success_count}  건너뜀: {skip_count}  실패: {fail_count}')
    if success_count + skip_count == len(ROAD_CONFIG):
        print('✅ 모든 도로 준비됨 — Flask 서버를 재시작하면 즉시 적용됩니다.')
    elif fail_count > 0:
        print('⚠️  일부 도로 실패. 잠시 후 다시 실행하거나 --force 옵션을 사용하세요.')
    print('=' * 60)


if __name__ == '__main__':
    main()
