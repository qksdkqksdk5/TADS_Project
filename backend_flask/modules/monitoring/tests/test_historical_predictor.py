# 파일 경로: modules/monitoring/tests/test_historical_predictor.py
# 역할: historical_predictor.py 의 132차 변경사항을 검증한다.
#
# 검증 항목:
#   - predict() 반환값이 최대 3개 원소(1h/2h/3h) 리스트인지
#   - min_window_sec 미만 버퍼는 flush 스킵되는지
#   - CSV 저장·로드 영속성 동작 확인
#   - swap_slots_with() 가 양쪽 CSV를 저장하는지

import sys
import os
import csv
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# ── 테스트 대상 모듈 경로 등록 ────────────────────────────────────────────
_MONITORING_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
_DETECTOR_MODULES_DIR = os.path.join(_MONITORING_DIR, "detector_modules")
for _p in (_MONITORING_DIR, _DETECTOR_MODULES_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from detector_modules.historical_predictor import HistoricalPredictor


# ── 공용 픽스처 헬퍼 ──────────────────────────────────────────────────────

def _make_predictor(tmp_path: str, suffix: str = "a",
                    min_window_sec: float = 0.0) -> HistoricalPredictor:
    """테스트용 HistoricalPredictor 인스턴스를 생성한다.

    tmp_path: 임시 디렉터리 경로 (문자열)
    suffix:   CSV 파일명 구분자 (hist_jam_{suffix}.csv)
    min_window_sec: 버퍼 최소 시간 커버리지 (0.0 = 검사 없음)
    """
    csv_path = os.path.join(tmp_path, f"hist_jam_{suffix}.csv")
    return HistoricalPredictor(
        csv_path=csv_path,
        min_window_sec=min_window_sec,
    )


def _fill_slot(predictor: HistoricalPredictor, target_dt: datetime,
               jam_score: float = 0.5, n: int = 3) -> None:
    """target_dt 슬롯(5분 창)에 데이터를 n번 채운다.

    각 5분 창마다 슬롯을 변경해야 flush가 일어나므로,
    target_dt 슬롯에 기록 후 다음 슬롯으로 이동해 flush를 유발한다.
    """
    for i in range(n):
        # 슬롯을 채울 시각: target_dt 슬롯 안의 여러 시각
        dt = target_dt.replace(second=i * 10)
        predictor.record(jam_score, dt=dt)
    # 다음 슬롯으로 넘어가 현재 슬롯 flush 강제 유발
    next_slot_dt = target_dt + timedelta(minutes=5)
    predictor.record(jam_score, dt=next_slot_dt)


# ── predict() 3-horizon 반환 검증 ─────────────────────────────────────────

class TestPredictHorizon:
    """predict()가 1h·2h·3h 3개 원소 리스트를 반환하는지 검증한다."""

    def test_데이터_없으면_None_반환(self, tmp_path):
        """슬롯 데이터가 전혀 없으면 predict()는 None을 반환해야 한다."""
        pred = _make_predictor(str(tmp_path))
        result = pred.predict()
        assert result is None, f"데이터 없을 때 None 아님: {result}"

    def test_1h_슬롯만_있을때_1h_결과_포함(self, tmp_path):
        """1h 슬롯에 데이터 있을 때 반환 리스트에 horizon_min=60 원소가 있어야 한다.

        NOTE: 2h 슬롯은 1h 슬롯으로부터 보간(거리=12슬롯=_INTERP_MAX_GAP 경계)될 수 있어
        결과 원소 수가 1이상이 된다. 정확한 원소 수 대신 1h horizon 포함 여부를 검증한다.
        """
        pred = _make_predictor(str(tmp_path))
        now = datetime.now()
        # 1h 후 슬롯에 데이터 채우기
        target_1h = now + timedelta(hours=1)
        _fill_slot(pred, target_1h, jam_score=0.3)
        result = pred.predict(dt=now)
        assert result is not None, "데이터 있는데 None 반환"
        assert len(result) >= 1, f"결과 리스트 비어있음: {result}"
        horizons = {r["horizon_min"] for r in result}
        assert 60 in horizons, f"1h(60분) 결과가 없음: {horizons}"

    def test_모든_슬롯_있을때_3개_반환(self, tmp_path):
        """1h/2h/3h 슬롯 모두 데이터 있을 때 결과 리스트가 3개여야 한다."""
        pred = _make_predictor(str(tmp_path))
        now = datetime(2025, 6, 1, 10, 0, 0)  # 기준 시각 고정
        # 1h/2h/3h 슬롯에 각각 데이터 채우기
        for hours in (1, 2, 3):
            _fill_slot(pred, now + timedelta(hours=hours), jam_score=0.4)
        result = pred.predict(dt=now)
        assert result is not None
        assert len(result) == 3, f"원소 수 불일치: {len(result)}"
        horizons = {r["horizon_min"] for r in result}
        assert horizons == {60, 120, 180}, f"horizon_min 집합 불일치: {horizons}"

    def test_반환_딕셔너리_키_포함(self, tmp_path):
        """반환 원소 딕셔너리에 필수 키가 모두 있어야 한다."""
        pred = _make_predictor(str(tmp_path))
        now = datetime(2025, 6, 1, 10, 0, 0)
        _fill_slot(pred, now + timedelta(hours=1), jam_score=0.5)
        result = pred.predict(dt=now)
        assert result is not None
        required_keys = {"horizon_sec", "horizon_min", "predicted_level",
                         "confidence", "jam_score", "interpolated"}
        for key in required_keys:
            assert key in result[0], f"필수 키 누락: {key}"

    def test_horizon_sec_는_horizon_min_x60(self, tmp_path):
        """horizon_sec = horizon_min × 60 관계가 성립해야 한다."""
        pred = _make_predictor(str(tmp_path))
        now = datetime(2025, 6, 1, 10, 0, 0)
        for h in (1, 2, 3):
            _fill_slot(pred, now + timedelta(hours=h), jam_score=0.3)
        result = pred.predict(dt=now)
        for r in result:
            assert r["horizon_sec"] == r["horizon_min"] * 60, (
                f"horizon_sec != horizon_min*60: {r}"
            )


# ── min_window_sec 버퍼 스킵 검증 ────────────────────────────────────────

class TestMinWindowSec:
    """min_window_sec 미만 버퍼는 flush 스킵되는지 검증한다."""

    def test_짧은_버퍼_스킵(self, tmp_path):
        """record 시각 간격이 min_window_sec 미만이면 슬롯에 저장되지 않는다."""
        # min_window_sec=150 → 2분30초 미만 버퍼는 무시
        pred = _make_predictor(str(tmp_path), min_window_sec=150.0)
        base = datetime(2025, 6, 1, 10, 0, 0)
        # 30초짜리 버퍼 (150초 미만)
        pred.record(0.5, dt=base)
        pred.record(0.5, dt=base + timedelta(seconds=30))
        # 슬롯 경계를 넘어 flush 강제 유발
        pred.record(0.5, dt=base + timedelta(minutes=5))
        # 슬롯 데이터가 없어야 한다
        result = pred.predict(dt=base)
        assert result is None or len(result) == 0, (
            "짧은 버퍼가 flush 스킵되지 않고 저장됨"
        )

    def test_충분한_버퍼_저장됨(self, tmp_path):
        """record 시각 간격이 min_window_sec 이상이면 정상 저장돼야 한다."""
        pred = _make_predictor(str(tmp_path), min_window_sec=10.0)
        base = datetime(2025, 6, 1, 10, 0, 0)
        # 30초짜리 버퍼 (10초 이상)
        pred.record(0.7, dt=base)
        pred.record(0.7, dt=base + timedelta(seconds=30))
        pred.record(0.5, dt=base + timedelta(minutes=5))  # flush 유발
        # 슬롯에 데이터가 저장돼야 한다
        assert pred.get_total_windows() >= 1, "충분한 버퍼인데 저장 안 됨"


# ── CSV 저장·로드 검증 ────────────────────────────────────────────────────

class TestCsvPersistence:
    """HistoricalPredictor 가 CSV에 슬롯 데이터를 저장·재로드하는지 검증한다."""

    def test_슬롯_데이터_저장_후_재로드(self, tmp_path):
        """슬롯 데이터를 채운 뒤 새 인스턴스를 만들면 같은 슬롯 수가 로드돼야 한다."""
        csv_path = str(tmp_path / "hist_jam_test.csv")
        now = datetime(2025, 6, 1, 10, 0, 0)

        # 첫 인스턴스에서 데이터 채우기
        pred1 = HistoricalPredictor(csv_path=csv_path, min_window_sec=0.0)
        for h in (1, 2):
            _fill_slot(pred1, now + timedelta(hours=h), jam_score=0.4)

        # 새 인스턴스로 재로드
        pred2 = HistoricalPredictor(csv_path=csv_path, min_window_sec=0.0)
        assert pred2.get_slot_count() >= 2, (
            f"재로드 후 슬롯 수 부족: {pred2.get_slot_count()}"
        )

    def test_CSV_파일_컬럼_구조(self, tmp_path):
        """생성된 CSV 파일이 올바른 컬럼(hour, minute_start, count, jam_sum)을 가져야 한다."""
        csv_path = str(tmp_path / "hist_jam_col.csv")
        now = datetime(2025, 6, 1, 10, 0, 0)
        pred = HistoricalPredictor(csv_path=csv_path, min_window_sec=0.0)
        _fill_slot(pred, now + timedelta(hours=1), jam_score=0.5)

        assert os.path.exists(csv_path), "CSV 파일이 생성되지 않음"
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            expected = {"hour", "minute_start", "count", "jam_sum"}
            actual   = set(reader.fieldnames or [])
            assert actual == expected, f"컬럼 불일치: {actual}"


# ── swap_slots_with() 검증 ────────────────────────────────────────────────

class TestSwapSlotsWith:
    """swap_slots_with()가 슬롯을 교환하고 양쪽 CSV를 저장하는지 검증한다."""

    def test_슬롯_교환_후_양쪽_저장(self, tmp_path):
        """swap_slots_with() 호출 후 두 CSV 파일이 모두 존재해야 한다."""
        csv_a = str(tmp_path / "hist_jam_a.csv")
        csv_b = str(tmp_path / "hist_jam_b.csv")
        now = datetime(2025, 6, 1, 10, 0, 0)

        pred_a = HistoricalPredictor(csv_path=csv_a, min_window_sec=0.0)
        pred_b = HistoricalPredictor(csv_path=csv_b, min_window_sec=0.0)

        # pred_a 슬롯에만 데이터 채우기
        _fill_slot(pred_a, now + timedelta(hours=1), jam_score=0.8)
        before_a = pred_a.get_slot_count()  # 데이터 있음
        before_b = pred_b.get_slot_count()  # 데이터 없음 (0)

        # 교환 실행
        pred_a.swap_slots_with(pred_b)

        # 교환 후: pred_a는 비어야 하고, pred_b는 데이터 있어야 함
        assert pred_a.get_slot_count() == before_b, "swap 후 pred_a 슬롯 수 불일치"
        assert pred_b.get_slot_count() == before_a, "swap 후 pred_b 슬롯 수 불일치"

        # 양쪽 CSV 파일이 모두 생성(저장)됐는지 확인
        assert os.path.exists(csv_a), "swap 후 pred_a CSV 파일 없음"
        assert os.path.exists(csv_b), "swap 후 pred_b CSV 파일 없음"
