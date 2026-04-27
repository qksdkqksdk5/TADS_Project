"""
patch_youngdong_route52.py

youngdong.json에 광주원주고속도로(Route 52) 구간을 추가하는 보조 스크립트.
영동고속도로 전체 bbox로 조회하면 65초 타임아웃이 발생하므로,
광주~원주 구간만 좁은 bbox로 별도 조회 후 youngdong.json에 병합한다.

사용법:
    # backend_flask/ 에서 실행
    python modules/monitoring/patch_youngdong_route52.py
"""

import json          # JSON 파일 읽기/쓰기
import time          # 미러 간 대기
import requests      # Overpass HTTP 요청
from pathlib import Path  # 파일 경로 조작

# ── 경로 ────────────────────────────────────────────────────────────────────
CACHE_DIR  = Path(__file__).parent / 'road_geo_cache'  # youngdong.json 위치
OUTPUT     = CACHE_DIR / 'youngdong.json'              # 최종 저장 파일

# ── Overpass 미러 (앞에서부터 순서대로 시도) ──────────────────────────────
ENDPOINTS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://overpass.openstreetmap.fr/api/interpreter',
]

# ── 요청 헤더 ────────────────────────────────────────────────────────────
HEADERS = {
    'User-Agent':   'TADS-Route52Patch/1.0 (one-time patch; contact: tads@example.com)',
    'Accept':       'application/json',
    'Content-Type': 'application/x-www-form-urlencoded',
}

# ── Route 52 후보 이름 목록 (OSM 표기가 불명확하므로 여러 이름 시도) ─────
# 각 이름을 좁은 bbox(광주~원주 구간)로 독립적으로 조회
# 좁은 bbox → 빠른 응답 → 타임아웃 방지
ROUTE52_NAMES = [
    '광주원주고속도로',   # KOROADS 공식 이름
    '제2영동선',         # ITS/내비 표기 (구 명칭)
    '제2영동고속도로',   # 혹시 있을 수 있는 전체 이름 변형
]

# 광주JCT(127.22E,37.43N) ~ 원주JCT(127.97E,37.37N) 구간 bbox
# 실제 도로보다 넉넉하게 잡아 클리핑 없이 모든 way를 포함시킨다.
ROUTE52_BBOX = {
    'minX': 127.0, 'maxX': 128.2,
    'minY': 37.1,  'maxY': 37.6,
}


def fetch_name(name: str) -> list:
    """
    단일 OSM 이름을 좁은 bbox로 Overpass에서 조회해 GeoJSON Feature 목록을 반환한다.
    모든 미러 실패 시 빈 목록을 반환한다.
    """
    b = ROUTE52_BBOX
    bbox_str = f'({b["minY"]},{b["minX"]},{b["maxY"]},{b["maxX"]})'   # Overpass 포맷
    query = (
        f'[out:json][timeout:60];'
        f'(way["name"="{name}"]["highway"~"motorway|trunk|motorway_link"]{bbox_str};);'
        f'out geom;'
    )

    for endpoint in ENDPOINTS:                            # 미러 순차 시도
        host = endpoint.split('/')[2]
        try:
            print(f'  [{name}] → {host} 요청 중...')
            resp = requests.post(
                endpoint,
                data={'data': query},
                headers=HEADERS,
                timeout=70,                               # 쿼리 timeout:60 + 여유 10초
            )
            resp.raise_for_status()
            elements = resp.json().get('elements', [])

            # way만 추출해서 GeoJSON Feature로 변환
            features = []
            for el in elements:
                if el.get('type') != 'way':
                    continue
                geometry = el.get('geometry', [])
                if len(geometry) < 2:
                    continue
                coords = [[pt['lon'], pt['lat']] for pt in geometry]  # [경도, 위도]
                features.append({
                    'type': 'Feature',
                    'properties': {
                        'osm_id': el.get('id'),
                        'name': el.get('tags', {}).get('name', ''),
                    },
                    'geometry': {'type': 'LineString', 'coordinates': coords},
                })

            if features:
                print(f'  [{name}] ✅ {host} 성공 — {len(features)}개 way')
                return features                           # 성공 → 즉시 반환

            print(f'  [{name}] ⚠️ {host}: 응답 왔지만 결과 없음 (이름 불일치 가능)')
            break   # 결과 없으면 다른 미러도 같은 결과일 것 → 다음 이름으로 넘어감

        except requests.Timeout:
            print(f'  [{name}] ⏱️ {host}: 타임아웃 → 다음 미러 시도')
        except requests.HTTPError as e:
            print(f'  [{name}] ⚠️ {host}: HTTP {e.response.status_code} → 다음 미러 시도')
        except Exception as e:
            print(f'  [{name}] ⚠️ {host}: {type(e).__name__}: {e} → 다음 미러 시도')

        time.sleep(2)   # 미러 간 대기

    return []   # 모든 미러 실패 or 결과 없음


def main():
    print('=' * 60)
    print('youngdong.json Route 52 패치 스크립트')
    print('=' * 60)

    # ── 기존 youngdong.json 로드 ─────────────────────────────────────────
    if not OUTPUT.exists():
        print(f'❌ {OUTPUT} 가 없습니다. 먼저 generate_road_geo_cache.py 를 실행하세요.')
        return

    with OUTPUT.open('r', encoding='utf-8') as f:
        base_geo = json.load(f)                          # 기존 영동고속도로 GeoJSON

    existing_ids = {                                     # 중복 방지: 기존 osm_id 집합
        feat['properties']['osm_id']
        for feat in base_geo.get('features', [])
        if feat['properties'].get('osm_id')
    }
    print(f'기존 youngdong.json: {len(base_geo["features"])}개 way (영동고속도로)')

    # ── Route 52 후보 이름 순서대로 조회 ─────────────────────────────────
    new_features = []
    for name in ROUTE52_NAMES:
        found = fetch_name(name)
        # 중복 osm_id 제거 후 추가
        dedup = [
            f for f in found
            if f['properties']['osm_id'] not in existing_ids
        ]
        if dedup:
            print(f'  → {len(dedup)}개 추가 (중복 제거 후)')
            new_features.extend(dedup)
            existing_ids.update(f['properties']['osm_id'] for f in dedup)
        time.sleep(2)   # 이름 간 대기

    if not new_features:
        print('\n⚠️ Route 52 구간을 어느 이름으로도 찾지 못했습니다.')
        print('youngdong.json 는 변경하지 않습니다.')
        return

    # ── 병합 후 저장 ─────────────────────────────────────────────────────
    merged = base_geo['features'] + new_features         # 기존 + 신규 합치기
    merged_geo = {'type': 'FeatureCollection', 'features': merged}

    OUTPUT.write_text(
        json.dumps(merged_geo, ensure_ascii=False),      # 한국어 그대로 저장
        encoding='utf-8',
    )
    print(f'\n✅ 병합 완료: {len(merged)}개 way → {OUTPUT.name} 저장')
    print('Flask 서버를 재시작하면 광주JCT~원주JCT 구간이 지도에 표시됩니다.')
    print('=' * 60)


if __name__ == '__main__':
    main()
