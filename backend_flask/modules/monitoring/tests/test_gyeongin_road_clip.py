# 파일 경로: modules/monitoring/tests/test_gyeongin_road_clip.py
# 역할: 경인고속도로 도로 선형 클리핑 설정 검증 테스트
# 실행: pytest modules/monitoring/tests/test_gyeongin_road_clip.py -v

import sys
import pathlib

# its_helper 를 직접 임포트하기 위해 monitoring 모듈 루트를 sys.path 에 추가
_MONITORING_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(_MONITORING_DIR) not in sys.path:
    sys.path.insert(0, str(_MONITORING_DIR))

import its_helper


# ── 헬퍼: 클리핑 판별 함수 ────────────────────────────────────────────────────
def _is_outside_clip(coords: list, clip_b: dict) -> bool:
    """
    coords 중 clip_b 바깥에 있는 노드가 하나라도 있으면 True 를 반환한다.
    its_helper.get_road_geometry 의 all-or-nothing 클리핑과 동일한 로직.
    coords: [[경도, 위도], ...] 형태
    """
    return any(
        c[0] < clip_b['minX'] or c[0] > clip_b['maxX'] or
        c[1] < clip_b['minY'] or c[1] > clip_b['maxY']
        for c in coords
    )


# ── 1. 설정 존재 여부 검증 ─────────────────────────────────────────────────────

def test_gyeongin_config_has_osm_name_bounds():
    """경인고속도로 ROAD_CONFIG 에 osm_name_bounds 가 정의되어야 한다."""
    cfg = its_helper.ROAD_CONFIG.get('gyeongin', {})
    assert 'osm_name_bounds' in cfg, "gyeongin 에 osm_name_bounds 가 없다"


def test_gyeongin_osm_name_bounds_has_both_roads():
    """osm_name_bounds 에 경인고속도로와 제2경인고속도로 항목이 모두 있어야 한다."""
    bounds = its_helper.ROAD_CONFIG['gyeongin']['osm_name_bounds']
    assert '경인고속도로' in bounds, "경인고속도로 클리핑 범위 누락"
    assert '제2경인고속도로' in bounds, "제2경인고속도로 클리핑 범위 누락"


# ── 2. 경인고속도로 클리핑 검증 ──────────────────────────────────────────────

def test_경인고속도로_eastern_connector_is_clipped():
    """
    경인고속도로: 동쪽으로 벗어난 연결로 way(경도 127.0 포함)는 클리핑된다.
    실제 경인고속도로 본선은 ~126.83 에서 끝나므로 127.0 노드는 연결로다.
    """
    clip_b = its_helper.ROAD_CONFIG['gyeongin']['osm_name_bounds']['경인고속도로']
    # 서인천IC(126.70) → 서울외곽 연결로(127.0) 를 가로지르는 가상의 way
    bad_coords = [[126.70, 37.53], [127.00, 37.54]]
    assert _is_outside_clip(bad_coords, clip_b), \
        "경인고속도로: 동쪽 연결로가 클리핑되지 않았다"


def test_경인고속도로_main_road_is_kept():
    """
    경인고속도로: 실제 본선 구간(126.68~126.83, 37.52~37.53)은 유지된다.
    캐시 분석 결과 경인고속도로 최대 경도는 126.8349 였다.
    """
    clip_b = its_helper.ROAD_CONFIG['gyeongin']['osm_name_bounds']['경인고속도로']
    # 서인천IC ~ 신월IC 사이 본선 가상 노드
    good_coords = [[126.70, 37.52], [126.83, 37.53]]
    assert not _is_outside_clip(good_coords, clip_b), \
        "경인고속도로: 본선이 클리핑에서 잘못 제거되었다"


# ── 3. 제2경인고속도로 클리핑 검증 ───────────────────────────────────────────

def test_제2경인고속도로_eastern_connector_is_clipped():
    """
    제2경인고속도로: 서울외곽순환고속도로로 이어지는 동쪽 연결로(127.1 포함)는 클리핑된다.
    캐시 분석: 126.92 이후 갑자기 126.97~127.1 구간(40개 way)이 존재 → 연결로.
    """
    clip_b = its_helper.ROAD_CONFIG['gyeongin']['osm_name_bounds']['제2경인고속도로']
    # 광명JC → 서울외곽순환 연결로 가상 노드
    bad_coords = [[126.90, 37.41], [127.10, 37.43]]
    assert _is_outside_clip(bad_coords, clip_b), \
        "제2경인고속도로: 동쪽 연결로(127.1)가 클리핑되지 않았다"


def test_제2경인고속도로_main_road_is_kept():
    """
    제2경인고속도로: 본선 구간(126.63~126.92, 37.39~37.45)은 유지된다.
    캐시 분석: 126.92 이하는 175개 way 로 본선에 해당.
    """
    clip_b = its_helper.ROAD_CONFIG['gyeongin']['osm_name_bounds']['제2경인고속도로']
    # 인천기점 ~ 광명IC 사이 본선 가상 노드
    good_coords = [[126.65, 37.40], [126.92, 37.44]]
    assert not _is_outside_clip(good_coords, clip_b), \
        "제2경인고속도로: 본선이 클리핑에서 잘못 제거되었다"


def test_제2경인고속도로_boundary_gap_is_clipped():
    """
    제2경인고속도로: 126.92 ~ 126.96 사이 공백 구간은 연결로이므로 클리핑된다.
    캐시 분석에서 126.92 다음 bucket 이 126.97 로 뛰는 것이 확인됨.
    """
    clip_b = its_helper.ROAD_CONFIG['gyeongin']['osm_name_bounds']['제2경인고속도로']
    # 126.95 노드가 포함된 way → 클리핑 대상
    borderline_coords = [[126.80, 37.42], [126.95, 37.43]]
    assert _is_outside_clip(borderline_coords, clip_b), \
        "제2경인고속도로: 경계 연결로(126.95)가 클리핑되지 않았다"
