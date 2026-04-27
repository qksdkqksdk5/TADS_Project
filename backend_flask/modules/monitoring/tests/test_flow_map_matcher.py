# 파일 경로: modules/monitoring/tests/test_flow_map_matcher.py
# 역할: flow_map_matcher.py 의 점수 함수 및 임계값 변경사항을 검증한다.
#
# 132차 변경 사항:
#   - _score_edge_structure(), _score_spatial_hist() 신규 함수
#   - score_frames() 가중치 변경 + CLAHE 정규화 추가
#   - find_best_snapshot() min_score 기본값 0.35 → 0.25
#
# 133차 변경 사항:
#   - save_flow_snapshot() — dir_label_a 파라미터 추가 + meta JSON 저장
#   - load_snapshot_meta() — npy 경로로 메타 JSON 읽기 (없으면 {})
#   - _road_prefix() — 카메라 ID 끝 숫자 제거 → 도로 그룹 접두어 반환
#   - FlowMapMatcher._candidates() — road_prefix 파라미터로 같은 도로 그룹만 탐색
#   - FlowMapMatcher.find_best() — exclude_dir에서 접두어 자동 추출

import sys
import os
import inspect
import numpy as np
import pytest

# ── 테스트 대상 모듈 경로 등록 ────────────────────────────────────────────
_MONITORING_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
_DETECTOR_MODULES_DIR = os.path.join(_MONITORING_DIR, "detector_modules")
for _p in (_MONITORING_DIR, _DETECTOR_MODULES_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from detector_modules.flow_map_matcher import (
    _score_edge_structure,
    _score_spatial_hist,
    _road_prefix,         # 133차: 도로 그룹 접두어 추출
    score_frames,
    find_best_snapshot,
    save_flow_snapshot,
    load_snapshot_meta,
    FlowMapMatcher,       # 133차: 도로 그룹 필터링 테스트용
)


# ── 공용 이미지 픽스처 ────────────────────────────────────────────────────

@pytest.fixture
def solid_gray_128():
    """128×128 단색(128) 그레이스케일 배열 — 엣지 없음."""
    return np.full((128, 128), 128, dtype=np.uint8)


@pytest.fixture
def solid_white_128():
    """128×128 단색(255) 그레이스케일 배열 — 전혀 다른 밝기."""
    return np.full((128, 128), 255, dtype=np.uint8)


@pytest.fixture
def bgr_same():
    """동일한 BGR 프레임 쌍 — 유사도 1.0에 가까워야 한다."""
    np.random.seed(42)
    # 실제 도로처럼 보이도록 다양한 픽셀값 혼합
    img = np.random.randint(50, 200, (240, 320, 3), dtype=np.uint8)
    return img, img.copy()


@pytest.fixture
def bgr_different():
    """완전히 다른 BGR 프레임 쌍 — 유사도 낮아야 한다."""
    np.random.seed(0)
    img_a = np.random.randint(0, 80, (240, 320, 3), dtype=np.uint8)    # 어두운 이미지
    np.random.seed(99)
    img_b = np.random.randint(180, 255, (240, 320, 3), dtype=np.uint8) # 밝은 이미지
    return img_a, img_b


# ── _score_edge_structure 테스트 ─────────────────────────────────────────

class TestScoreEdgeStructure:
    """_score_edge_structure(): 엣지 밀도 공간 분포 비교 점수 검증."""

    def test_동일이미지_점수_높음(self, solid_gray_128):
        """동일한 이미지 비교 시 점수가 0.8 이상이어야 한다."""
        score = _score_edge_structure(solid_gray_128, solid_gray_128)
        assert score >= 0.8, f"동일 이미지 점수가 너무 낮음: {score:.3f}"

    def test_반환값_0에서1_사이(self):
        """점수 반환값이 항상 0~1 범위 내에 있어야 한다."""
        np.random.seed(7)
        img_a = np.random.randint(0, 255, (128, 128), dtype=np.uint8)
        np.random.seed(13)
        img_b = np.random.randint(0, 255, (128, 128), dtype=np.uint8)
        score = _score_edge_structure(img_a, img_b)
        assert 0.0 <= score <= 1.0, f"범위 초과: {score}"

    def test_빈배열_방어처리(self):
        """0×0 배열 입력 시 0.0을 반환해야 한다 (크래시 방지)."""
        empty = np.zeros((0, 0), dtype=np.uint8)
        score = _score_edge_structure(empty, empty)
        assert score == 0.0


# ── _score_spatial_hist 테스트 ───────────────────────────────────────────

class TestScoreSpatialHist:
    """_score_spatial_hist(): 공간 분할 히스토그램 점수 검증."""

    def test_동일이미지_점수_높음(self, solid_gray_128):
        """동일한 이미지 비교 시 점수가 0.8 이상이어야 한다."""
        score = _score_spatial_hist(solid_gray_128, solid_gray_128)
        assert score >= 0.8, f"동일 이미지 점수가 너무 낮음: {score:.3f}"

    def test_밝기_극단_이미지_낮은점수(self, solid_gray_128, solid_white_128):
        """완전히 다른 밝기의 이미지 비교 시 점수가 0.6 미만이어야 한다."""
        score = _score_spatial_hist(solid_gray_128, solid_white_128)
        assert score < 0.6, f"다른 이미지 점수가 너무 높음: {score:.3f}"

    def test_반환값_0에서1_사이(self):
        """반환값이 0~1 범위 내에 있어야 한다."""
        np.random.seed(5)
        img_a = np.random.randint(0, 255, (128, 128), dtype=np.uint8)
        np.random.seed(8)
        img_b = np.random.randint(0, 255, (128, 128), dtype=np.uint8)
        score = _score_spatial_hist(img_a, img_b)
        assert 0.0 <= score <= 1.0, f"범위 초과: {score}"


# ── score_frames 테스트 ──────────────────────────────────────────────────

class TestScoreFrames:
    """score_frames(): 132차 가중치·CLAHE 변경 후 통합 점수 검증."""

    def test_동일프레임_점수_높음(self, bgr_same):
        """동일한 BGR 프레임 비교 시 점수가 0.7 이상이어야 한다."""
        frame_a, frame_b = bgr_same
        score = score_frames(frame_a, frame_b)
        assert score >= 0.7, f"동일 프레임 점수가 너무 낮음: {score:.3f}"

    def test_반환값_0에서1_사이(self, bgr_same, bgr_different):
        """모든 입력에 대해 반환값이 0~1 범위 내에 있어야 한다."""
        for frame_a, frame_b in [bgr_same, bgr_different]:
            score = score_frames(frame_a, frame_b)
            assert 0.0 <= score <= 1.0, f"범위 초과: {score}"

    def test_가중치_합_1(self):
        """현재 score_frames 가중치(0.35+0.35+0.20+0.10)의 합이 1.0이어야 한다.
        소스 코드를 직접 파싱하지 않고 완전 동일 이미지로 상한 유효성만 검증한다."""
        # 완전히 동일한 단색 이미지로 최대 점수가 1.0 이하인지 확인
        img = np.full((128, 128, 3), 100, dtype=np.uint8)
        score = score_frames(img, img)
        assert score <= 1.0, f"가중치 합 초과 의심: {score}"


# ── find_best_snapshot 임계값 테스트 ─────────────────────────────────────

class TestFindBestSnapshotThreshold:
    """find_best_snapshot() 기본 min_score가 0.25인지 검증한다."""

    def test_기본_min_score_0_25(self):
        """find_best_snapshot 함수 시그니처의 min_score 기본값이 0.25여야 한다."""
        sig = inspect.signature(find_best_snapshot)
        default = sig.parameters["min_score"].default
        assert default == 0.25, (
            f"min_score 기본값이 0.25가 아님: {default}\n"
            "132차 변경사항(0.35→0.25)이 적용됐는지 확인하세요."
        )


# ── save_flow_snapshot / load_snapshot_meta 테스트 (133차) ───────────────

class TestSaveFlowSnapshotMeta:
    """save_flow_snapshot()의 dir_label_a 저장과 load_snapshot_meta() 읽기를 검증한다."""

    def test_dir_label_a_파라미터_존재(self):
        """save_flow_snapshot 시그니처에 dir_label_a 파라미터가 있어야 한다."""
        sig = inspect.signature(save_flow_snapshot)
        assert "dir_label_a" in sig.parameters, (
            "save_flow_snapshot에 dir_label_a 파라미터 없음 — 133차 변경사항 미적용"
        )

    def test_dir_label_a_기본값_빈문자열(self):
        """dir_label_a 파라미터의 기본값이 빈 문자열('')이어야 한다."""
        sig = inspect.signature(save_flow_snapshot)
        default = sig.parameters["dir_label_a"].default
        assert default == "", f"dir_label_a 기본값이 빈 문자열이 아님: {repr(default)}"

    def test_메타_저장_후_로드(self, tmp_path):
        """save_flow_snapshot()으로 저장한 dir_label_a를 load_snapshot_meta()로 읽을 수 있어야 한다."""
        import json

        # 더미 FlowMap 객체 (save()만 구현)
        class _DummyFlowMap:
            def save(self, path):
                np.save(path, np.zeros((5, 5)))  # 더미 npy 저장

        frame   = np.zeros((64, 64, 3), dtype=np.uint8)  # 검정 프레임
        flow    = _DummyFlowMap()
        save_dir = tmp_path / "cam_test"

        # UP 레이블로 저장
        ok = save_flow_snapshot(frame, flow, save_dir, dir_label_a="UP")
        assert ok, "save_flow_snapshot() 반환값이 False — 저장 실패"

        # npy 파일 경로 찾기
        npy_files = list(save_dir.glob("flow_map_????????_??????.npy"))
        assert len(npy_files) == 1, f"npy 파일이 정확히 1개여야 함: {npy_files}"
        npy_path = npy_files[0]

        # 메타 로드
        meta = load_snapshot_meta(npy_path)
        assert meta.get("dir_label_a") == "UP", (
            f"저장한 dir_label_a='UP'이 메타에서 읽히지 않음: {meta}"
        )

    def test_메타_없으면_빈딕셔너리(self, tmp_path):
        """대응 meta JSON이 없는 npy 경로를 load_snapshot_meta()에 넘기면 빈 dict를 반환해야 한다."""
        npy_path = tmp_path / "flow_map_20240101_120000.npy"
        npy_path.write_bytes(b"")  # 파일은 있지만 메타는 없음
        meta = load_snapshot_meta(npy_path)
        assert meta == {}, f"메타 없을 때 빈 dict가 아님: {meta}"

    def test_dir_label_a_down_저장(self, tmp_path):
        """dir_label_a='DOWN'도 올바르게 저장·로드되어야 한다."""

        class _DummyFlowMap:
            def save(self, path):
                np.save(path, np.zeros((5, 5)))

        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        ok = save_flow_snapshot(frame, _DummyFlowMap(), tmp_path, dir_label_a="DOWN")
        assert ok

        npy_path = next(tmp_path.glob("flow_map_*.npy"))
        meta = load_snapshot_meta(npy_path)
        assert meta.get("dir_label_a") == "DOWN"


# ── _road_prefix 단위 테스트 (133차) ────────────────────────────────────────

class TestRoadPrefix:
    """_road_prefix(): 카메라 ID 끝 숫자 제거 후 도로 접두어 반환 검증."""

    def test_끝_숫자_제거(self):
        """'달래내2' → '달래내': 끝 숫자를 제거해야 한다."""
        assert _road_prefix("달래내2") == "달래내"

    def test_여러_자리_숫자_제거(self):
        """'경부고속도로12' → '경부고속도로': 여러 자리 숫자도 모두 제거해야 한다."""
        assert _road_prefix("경부고속도로12") == "경부고속도로"

    def test_숫자_없으면_원본_반환(self):
        """숫자가 없는 '달래내' 그대로 반환해야 한다."""
        assert _road_prefix("달래내") == "달래내"

    def test_숫자만_있으면_원본_반환(self):
        """'123'처럼 숫자만 있으면 빈 문자열 방지를 위해 원본 반환해야 한다."""
        assert _road_prefix("123") == "123"

    def test_영문_카메라id(self):
        """'cam3' → 'cam': 영문 카메라 ID도 끝 숫자 제거가 동작해야 한다."""
        assert _road_prefix("cam3") == "cam"


# ── FlowMapMatcher 도로 그룹 필터링 테스트 (133차) ──────────────────────────

def _make_camera_folder(root, cam_id: str, with_files: bool = True):
    """테스트용 가짜 카메라 폴더(flow_map.npy + ref_frame.jpg)를 생성한다."""
    folder = root / cam_id
    folder.mkdir(parents=True, exist_ok=True)
    if with_files:
        # 1×1 흑백 더미 jpg 생성 (cv2 없이 순수 bytes)
        dummy_img = np.zeros((32, 32, 3), dtype=np.uint8)
        ok, buf = __import__('cv2').imencode(".jpg", dummy_img)
        (folder / "ref_frame.jpg").write_bytes(buf.tobytes() if ok else b"")
        # 더미 npy 저장
        np.save(str(folder / "flow_map.npy"), np.zeros((3, 3)))
    return folder


class TestFlowMapMatcherRoadGroupFilter:
    """FlowMapMatcher._candidates()가 도로 접두어로 탐색 범위를 제한하는지 검증한다."""

    def test_같은_도로_그룹만_후보에_포함(self, tmp_path):
        """달래내1·달래내3은 후보에 들어가고, 경부고속도로1은 제외되어야 한다."""
        # 폴더 구성: 달래내1, 달래내3, 경부고속도로1
        _make_camera_folder(tmp_path, "달래내1")
        _make_camera_folder(tmp_path, "달래내3")
        _make_camera_folder(tmp_path, "경부고속도로1")

        matcher    = FlowMapMatcher(tmp_path)
        candidates = matcher._candidates(road_prefix="달래내")

        # 후보 폴더 이름 목록
        names = [d.name for d, _ in candidates]
        assert "달래내1"      in names, "달래내1이 후보에 없음"
        assert "달래내3"      in names, "달래내3이 후보에 없음"
        assert "경부고속도로1" not in names, "타 도로(경부고속도로1)가 후보에 포함됨 — 필터 오작동"

    def test_접두어_없으면_전체_후보(self, tmp_path):
        """road_prefix='' 이면 모든 폴더가 후보에 포함되어야 한다."""
        _make_camera_folder(tmp_path, "달래내1")
        _make_camera_folder(tmp_path, "경부고속도로1")

        matcher    = FlowMapMatcher(tmp_path)
        candidates = matcher._candidates(road_prefix="")  # 필터 없음

        names = [d.name for d, _ in candidates]
        assert "달래내1"      in names
        assert "경부고속도로1" in names

    def test_파일없는_폴더는_후보_제외(self, tmp_path):
        """flow_map.npy 또는 ref_frame.jpg가 없는 폴더는 후보에서 제외되어야 한다."""
        _make_camera_folder(tmp_path, "달래내1", with_files=True)   # 유효
        _make_camera_folder(tmp_path, "달래내2", with_files=False)  # 파일 없음

        matcher    = FlowMapMatcher(tmp_path)
        candidates = matcher._candidates(road_prefix="달래내")

        names = [d.name for d, _ in candidates]
        assert "달래내1" in names,  "유효 폴더(달래내1)가 후보에서 빠짐"
        assert "달래내2" not in names, "파일 없는 달래내2가 후보에 포함됨"

    def test_find_best_exclude_dir로_접두어_자동_추출(self, tmp_path):
        """find_best()가 exclude_dir='달래내2'로 호출될 때 '달래내' 접두어를 자동 추출해
        타 도로 폴더(경부고속도로1)를 탐색하지 않아야 한다 (후보 없음 → None 반환).
        """
        # 달래내2(자기자신), 경부고속도로1(타도로) 폴더만 존재
        _make_camera_folder(tmp_path, "달래내2")       # exclude_dir (자기 자신)
        _make_camera_folder(tmp_path, "경부고속도로1")  # 타 도로 — 탐색 제외 대상

        matcher     = FlowMapMatcher(tmp_path, min_score=0.0)  # min_score=0 → 매칭 기준 없음
        exclude_dir = tmp_path / "달래내2"
        current     = np.zeros((32, 32, 3), dtype=np.uint8)   # 더미 프레임

        best_dir, score = matcher.find_best(current, exclude_dir=exclude_dir)

        # 달래내 접두어를 공유하는 폴더가 달래내2(자기자신) 뿐이므로 후보 없음
        assert best_dir is None, (
            f"타 도로(경부고속도로1)가 매칭 후보로 선택됨 — 도로 그룹 필터 미적용: {best_dir}"
        )
