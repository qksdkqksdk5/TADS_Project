# 파일 경로: modules/monitoring/normalize_hist.py
# 역할: hist_jam_*.csv 슬롯 count가 과도하게 누적됐을 때 압축한다.
#        각 슬롯의 평균(jam_sum/count)은 유지하면서 count를 max_count로 줄임.
#        서버 코드가 아닌 수동 실행 유틸이다.
#
# 사용 예시:
#   python normalize_hist.py                              → flow_maps/ 전체 탐색, max_count=7
#   python normalize_hist.py "flow_maps/gyeongbu_양재"
#   python normalize_hist.py "flow_maps/gyeongbu_양재" --max 14
#   python normalize_hist.py "flow_maps/gyeongbu_양재" --reset   → 슬롯 전체 삭제 후 새로 시작

import sys
import csv
from pathlib import Path


def normalize_csv(csv_path: Path, max_count: int, reset: bool) -> None:
    """단일 CSV 파일의 슬롯 count를 max_count로 압축한다.

    reset=True이면 파일을 삭제해 슬롯 전체를 초기화한다.
    평균 = jam_sum / count 를 유지한 채 count를 줄이므로 예측 정확도는 보존된다.
    """
    if not csv_path.exists():
        return  # 파일 없으면 생략

    if reset:
        csv_path.unlink()  # 파일 삭제 (초기화)
        print(f"🗑️  초기화: {csv_path}")
        return

    # CSV 전체 읽기
    rows = []
    try:
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception as e:
        print(f"⚠️  읽기 실패: {csv_path} — {e}")
        return

    if not rows:
        return  # 빈 파일이면 생략

    # count > max_count인 슬롯만 압축
    changed = 0
    for row in rows:
        cnt = int(row["count"])
        if cnt > max_count:
            avg = float(row["jam_sum"]) / cnt          # 평균 보존
            row["count"]   = str(max_count)             # count 압축
            row["jam_sum"] = str(round(avg * max_count, 6))  # jam_sum 재계산
            changed += 1

    # 압축 결과 저장
    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["hour", "minute_start", "count", "jam_sum"])
            writer.writeheader()
            writer.writerows(rows)
        total_slots = len(rows)
        print(f"✅ {csv_path.name}: {total_slots}슬롯 중 {changed}개 count 압축 (max={max_count})")
    except Exception as e:
        print(f"⚠️  저장 실패: {csv_path} — {e}")


def process_dir(directory: Path, max_count: int, reset: bool) -> bool:
    """디렉터리 내의 hist_jam_a.csv, hist_jam_b.csv 를 처리한다.

    두 파일 중 하나라도 있으면 True를 반환한다.
    """
    found = False
    for name in ("hist_jam_a.csv", "hist_jam_b.csv"):
        p = directory / name
        if p.exists():
            normalize_csv(p, max_count, reset)  # 각 파일 압축 처리
            found = True
    return found


if __name__ == "__main__":
    # 이 스크립트가 위치한 monitoring/ 폴더를 프로젝트 루트로 사용
    PROJECT_ROOT = Path(__file__).resolve().parent

    args = sys.argv[1:]
    reset     = "--reset" in args        # --reset 플래그 확인
    max_count = 7                         # 기본: 슬롯당 최대 7개 창 (약 1주일치)

    # --max N 파싱
    if "--max" in args:
        idx = args.index("--max")
        if idx + 1 < len(args):
            try:
                max_count = int(args[idx + 1])   # 사용자 지정 max_count
            except ValueError:
                pass  # 숫자가 아니면 기본값 사용

    # 경로 파싱 (--max, --reset 제외한 첫 번째 인자)
    path_args = [a for a in args if not a.startswith("--") and not a.lstrip("-").isdigit()]
    if path_args:
        target = Path(path_args[0])       # 사용자가 지정한 경로
    else:
        target = PROJECT_ROOT / "flow_maps"  # 기본: monitoring/flow_maps/ 전체

    # 지정 폴더 + 하위 1단계 폴더 처리 (camera_id별 하위 폴더 포함)
    if target.is_dir():
        candidates = [target] + [d for d in target.iterdir() if d.is_dir()]
    else:
        candidates = [target.parent]

    found = False
    for d in candidates:
        if process_dir(d, max_count, reset):
            found = True

    if not found:
        print("CSV 파일을 찾지 못했습니다.")
        print("사용법: python normalize_hist.py [폴더경로] [--max N] [--reset]")
