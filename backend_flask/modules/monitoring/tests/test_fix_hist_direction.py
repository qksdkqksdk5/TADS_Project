# 파일 경로: modules/monitoring/tests/test_fix_hist_direction.py
# 역할: fix_hist_direction.py 의 동작을 검증한다.
#
# 검증 항목:
#   - _load_csv 가 슬롯 데이터를 올바르게 읽는지
#   - _load_csv 가 존재하지 않는 파일에서 빈 딕셔너리를 반환하는지
#   - _save_csv 가 CSV 포맷(컬럼·값)을 올바르게 쓰는지
#   - swap_csvs(dry_run=True) 가 파일을 변경하지 않는지
#   - swap_csvs(dry_run=False) 가 두 CSV 내용을 교환하는지

import sys
import os
import csv
from datetime import datetime, timedelta
from pathlib import Path

# ── 테스트 대상 모듈 경로 등록 ────────────────────────────────────────────
_MONITORING_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
_DM_DIR = os.path.join(_MONITORING_DIR, "detector_modules")  # detector_modules 경로

for _p in (_MONITORING_DIR, _DM_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fix_hist_direction import _load_csv, _save_csv, swap_csvs  # 테스트 대상


# ── 공용 픽스처 헬퍼 ─────────────────────────────────────────────────────

def _write_sample_csv(path: str, entries: list[tuple[int, int, int, float]]) -> None:
    """(hour, minute_start, count, jam_sum) 목록으로 샘플 CSV를 생성한다."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)  # 디렉터리 보장
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=("hour", "minute_start", "count", "jam_sum"))
        writer.writeheader()
        for hour, minute, count, jam_sum in entries:
            writer.writerow({
                "hour": hour,
                "minute_start": minute,
                "count": count,
                "jam_sum": round(jam_sum, 6),
            })


# ======================================================================
# _load_csv 검증
# ======================================================================

class TestLoadCsv:
    """_load_csv 의 기본 동작을 검증한다."""

    def test_유효한_CSV_슬롯_로드(self, tmp_path):
        """유효한 CSV에서 slot_id → [count, jam_sum] 딕셔너리를 올바르게 읽어야 한다."""
        path = str(tmp_path / "a.csv")
        _write_sample_csv(path, [(10, 0, 5, 2.50), (10, 5, 3, 1.80)])  # 두 슬롯
        result = _load_csv(path)
        assert 10 * 12 + 0 // 5 in result, "슬롯 [10:00]이 로드되지 않음"  # slot_id=120
        assert 10 * 12 + 5 // 5 in result, "슬롯 [10:05]이 로드되지 않음"  # slot_id=121
        assert result[120][0] == 5, "count 값 불일치"
        assert abs(result[120][1] - 2.50) < 1e-6, "jam_sum 값 불일치"

    def test_존재하지_않는_파일은_빈_딕셔너리(self, tmp_path):
        """존재하지 않는 파일 경로를 전달하면 빈 딕셔너리를 반환해야 한다."""
        result = _load_csv(str(tmp_path / "nonexistent.csv"))
        assert result == {}, "존재하지 않는 파일에서 빈 딕셔너리를 반환해야 함"

    def test_빈_CSV_파일은_빈_딕셔너리(self, tmp_path):
        """헤더만 있고 데이터가 없는 CSV 에서는 빈 딕셔너리를 반환해야 한다."""
        path = str(tmp_path / "empty.csv")
        _write_sample_csv(path, [])  # 헤더만 있는 빈 파일
        result = _load_csv(path)
        assert result == {}, "빈 CSV 에서 빈 딕셔너리를 반환해야 함"


# ======================================================================
# _save_csv 검증
# ======================================================================

class TestSaveCsv:
    """_save_csv 의 기본 동작을 검증한다."""

    def test_슬롯_딕셔너리를_올바른_CSV_포맷으로_저장(self, tmp_path):
        """슬롯 딕셔너리를 저장하면 HistoricalPredictor 포맷의 CSV가 생성되어야 한다."""
        path = str(tmp_path / "out.csv")
        slots = {120: [5, 2.50], 121: [3, 1.80]}  # {slot_id: [count, jam_sum]}
        _save_csv(path, slots)

        assert os.path.exists(path), "저장된 CSV 파일이 없음"
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2, f"행 수 불일치 — 예상 2, 실제 {len(rows)}"
        # 첫 번째 행 (slot_id=120 → hour=10, minute_start=0)
        assert rows[0]["hour"] == "10", "hour 값 불일치"
        assert rows[0]["minute_start"] == "0", "minute_start 값 불일치"
        assert rows[0]["count"] == "5", "count 값 불일치"

    def test_빈_슬롯_딕셔너리_저장(self, tmp_path):
        """슬롯이 없을 때 저장해도 헤더만 있는 유효한 CSV가 생성되어야 한다."""
        path = str(tmp_path / "empty_out.csv")
        _save_csv(path, {})
        assert os.path.exists(path), "빈 슬롯 저장 시 파일이 생성되어야 함"
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows == [], "빈 슬롯 저장 시 데이터 행이 없어야 함"


# ======================================================================
# swap_csvs 검증
# ======================================================================

class TestSwapCsvs:
    """swap_csvs 의 dry_run·실제 교환 동작을 검증한다."""

    def test_dry_run_True_이면_파일_변경_없음(self, tmp_path):
        """dry_run=True 이면 두 CSV 파일 내용이 변경되지 않아야 한다."""
        path_a = str(tmp_path / "a.csv")
        path_b = str(tmp_path / "b.csv")
        _write_sample_csv(path_a, [(10, 0, 5, 2.50)])   # a: 슬롯 [10:00]
        _write_sample_csv(path_b, [(11, 0, 3, 1.20)])   # b: 슬롯 [11:00]

        # dry_run=True 실행
        swap_csvs(path_a, path_b, dry_run=True)

        # 파일 내용이 그대로여야 함
        result_a = _load_csv(path_a)
        result_b = _load_csv(path_b)
        assert 120 in result_a, "dry_run 후 a의 슬롯 [10:00]이 사라짐"  # slot_id=120
        assert 132 in result_b, "dry_run 후 b의 슬롯 [11:00]이 사라짐"  # slot_id=132

    def test_dry_run_False_이면_슬롯_교환(self, tmp_path):
        """dry_run=False 이면 두 CSV 파일의 슬롯 데이터가 서로 교환되어야 한다."""
        path_a = str(tmp_path / "a.csv")
        path_b = str(tmp_path / "b.csv")
        _write_sample_csv(path_a, [(10, 0, 5, 2.50)])  # a: slot_id=120
        _write_sample_csv(path_b, [(11, 0, 3, 1.20)])  # b: slot_id=132

        swap_csvs(path_a, path_b, dry_run=False)

        # 교환 후: a에는 b의 슬롯(132)만, b에는 a의 슬롯(120)만 있어야 함
        result_a = _load_csv(path_a)
        result_b = _load_csv(path_b)
        assert 132 in result_a and 120 not in result_a, "교환 후 a에 b의 슬롯이 있어야 함"
        assert 120 in result_b and 132 not in result_b, "교환 후 b에 a의 슬롯이 있어야 함"

    def test_교환_후_슬롯_값_보존(self, tmp_path):
        """교환 후 각 슬롯의 count·jam_sum 값이 정확히 이동되어야 한다."""
        path_a = str(tmp_path / "a.csv")
        path_b = str(tmp_path / "b.csv")
        _write_sample_csv(path_a, [(10, 0, 7, 4.20)])  # a: count=7, jam_sum=4.20
        _write_sample_csv(path_b, [(10, 0, 2, 0.80)])  # b: count=2, jam_sum=0.80

        swap_csvs(path_a, path_b, dry_run=False)

        result_a = _load_csv(path_a)  # 교환 후 a에는 원래 b의 값
        result_b = _load_csv(path_b)  # 교환 후 b에는 원래 a의 값
        assert result_a[120][0] == 2, "교환 후 a의 count 값 불일치 (원래 b 값이어야 함)"
        assert abs(result_a[120][1] - 0.80) < 1e-6, "교환 후 a의 jam_sum 불일치"
        assert result_b[120][0] == 7, "교환 후 b의 count 값 불일치 (원래 a 값이어야 함)"
        assert abs(result_b[120][1] - 4.20) < 1e-6, "교환 후 b의 jam_sum 불일치"

    def test_빈_파일과_데이터_있는_파일_교환(self, tmp_path):
        """한 쪽이 빈 파일이어도 교환이 올바르게 동작해야 한다."""
        path_a = str(tmp_path / "a.csv")
        path_b = str(tmp_path / "b.csv")
        _write_sample_csv(path_a, [(10, 0, 5, 2.50)])  # a: 데이터 있음
        _write_sample_csv(path_b, [])                  # b: 비어 있음

        swap_csvs(path_a, path_b, dry_run=False)

        result_a = _load_csv(path_a)  # 교환 후 a는 비어야 함
        result_b = _load_csv(path_b)  # 교환 후 b에는 원래 a 데이터
        assert result_a == {}, "교환 후 a가 비어 있어야 함"
        assert 120 in result_b, "교환 후 b에 원래 a의 슬롯이 있어야 함"
