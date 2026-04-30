# 파일 경로: detector_modules/fix_hist_direction.py
# 역할: hist_jam_a.csv ↔ hist_jam_b.csv 슬롯 데이터 교환 커맨드라인 유틸리티.
#        카메라가 설치 방향이 바뀌어 a/b 방향 이력이 뒤섞인 경우 수동으로 교환한다.
# 사용법:
#   python fix_hist_direction.py --path-a <csv_a> --path-b <csv_b> [--dry-run] [--threshold 0.20]

import argparse   # 커맨드라인 인수 파싱
import csv        # CSV 파일 읽기·쓰기
import os         # 파일 존재 여부·디렉터리 생성


# ======================================================================
# 내부 I/O 헬퍼
# ======================================================================

def _load_csv(path: str) -> dict:
    """CSV 파일을 로드하여 {slot_id: [count, jam_sum]} 딕셔너리로 반환한다.

    Args:
        path: CSV 파일 경로. 파일이 없으면 빈 딕셔너리를 반환한다.

    Returns:
        {slot_id: [count, jam_sum]} 딕셔너리.
        slot_id = hour * 12 + minute_start // 5 (0~287).
    """
    slots: dict = {}                                   # 결과 딕셔너리 초기화
    if not os.path.exists(path):                       # 파일 없으면 빈 상태 반환
        return slots
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)                     # 헤더 기반 파싱
        for row in reader:                             # 각 행 순회
            h   = int(row["hour"])                     # 시 (0~23)
            m   = int(row["minute_start"])             # 분 시작 (0,5,...,55)
            sid = h * 12 + m // 5                      # slot_id 계산 (0~287)
            slots[sid] = [int(row["count"]), float(row["jam_sum"])]  # 슬롯 데이터 저장
    return slots


def _save_csv(path: str, slots: dict) -> None:
    """슬롯 딕셔너리를 HistoricalPredictor 호환 포맷의 CSV로 저장한다.

    Args:
        path: 저장할 CSV 파일 경로.
        slots: {slot_id: [count, jam_sum]} 딕셔너리.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)  # 디렉터리 보장
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=("hour", "minute_start", "count", "jam_sum"))
        writer.writeheader()                           # 헤더 행 작성
        for sid in sorted(slots):                      # slot_id 오름차순으로 저장
            h   = sid // 12                            # slot_id → 시
            m   = (sid % 12) * 5                       # slot_id → 분 시작
            cnt, jsum = slots[sid]                     # count, jam_sum 추출
            writer.writerow({
                "hour":         h,                     # 시
                "minute_start": m,                     # 분 시작
                "count":        cnt,                   # 5분 창 수
                "jam_sum":      round(jsum, 6),        # jam_score 합계 (소수 6자리)
            })


# ======================================================================
# 공개 API — 테스트 및 외부 호출용
# ======================================================================

def swap_csvs(path_a: str, path_b: str, dry_run: bool = False) -> tuple[dict, dict]:
    """두 CSV 파일의 슬롯 데이터를 교환한다.

    Args:
        path_a: hist_jam_a.csv 경로.
        path_b: hist_jam_b.csv 경로.
        dry_run: True 이면 파일을 수정하지 않고 교환 전 데이터만 반환한다.

    Returns:
        (slots_a, slots_b) — 교환 **전** 각 파일의 슬롯 데이터.
        dry_run=False 이면 두 파일이 실제로 교환된다.
    """
    slots_a = _load_csv(path_a)                        # 원본 a 데이터 로드
    slots_b = _load_csv(path_b)                        # 원본 b 데이터 로드

    if not dry_run:                                    # 실제 교환 모드
        _save_csv(path_a, slots_b)                     # a 파일에 b 데이터 저장
        _save_csv(path_b, slots_a)                     # b 파일에 a 데이터 저장

    return slots_a, slots_b                            # 교환 전 원본 데이터 반환


# ======================================================================
# 커맨드라인 엔트리포인트
# ======================================================================

def main() -> None:
    """커맨드라인에서 hist_jam_a.csv ↔ hist_jam_b.csv 교환을 수행한다."""
    parser = argparse.ArgumentParser(
        description="hist_jam_a.csv ↔ hist_jam_b.csv 슬롯 데이터 교환 유틸리티"
    )
    parser.add_argument("--path-a",    required=True,       help="hist_jam_a.csv 경로")
    parser.add_argument("--path-b",    required=True,       help="hist_jam_b.csv 경로")
    parser.add_argument("--dry-run",   action="store_true", help="실제 변경 없이 교환 내용만 출력")
    parser.add_argument("--threshold", type=float,
                        default=0.0,
                        help="이 값 이상 차이 나는 슬롯만 표시 (기본: 0.0 = 전체)")
    args = parser.parse_args()

    # ── 두 파일의 슬롯 데이터 로드 ────────────────────────────────────
    slots_a = _load_csv(args.path_a)                   # a 슬롯 로드
    slots_b = _load_csv(args.path_b)                   # b 슬롯 로드

    # ── 슬롯별 차이 분석 및 출력 ──────────────────────────────────────
    all_sids = sorted(set(slots_a) | set(slots_b))     # 두 파일에 존재하는 모든 슬롯 ID
    flagged  = []                                      # 임계값 이상 차이 슬롯 목록
    for sid in all_sids:
        # 데이터 없는 슬롯은 0.0으로 처리
        avg_a = slots_a[sid][1] / max(slots_a[sid][0], 1) if sid in slots_a else 0.0
        avg_b = slots_b[sid][1] / max(slots_b[sid][0], 1) if sid in slots_b else 0.0
        diff  = abs(avg_a - avg_b)                     # 평균 jam_score 차이
        if diff >= args.threshold:                     # 임계값 이상이면 플래그
            flagged.append((sid, avg_a, avg_b, diff))

    print(f"▶ 분석: a={args.path_a} / b={args.path_b}")
    print(f"  threshold={args.threshold:.2f} 이상 차이 슬롯 수: {len(flagged)}")

    for sid, avg_a, avg_b, diff in flagged[:20]:       # 최대 20개만 출력 (스크롤 방지)
        h = sid // 12                                  # slot_id → 시
        m = (sid % 12) * 5                             # slot_id → 분
        print(f"  [{h:02d}:{m:02d}]  a={avg_a:.3f}  b={avg_b:.3f}  diff={diff:.3f}")

    if len(flagged) > 20:                              # 초과분 있으면 알림
        print(f"  ... 외 {len(flagged) - 20}개 슬롯 생략")

    if args.dry_run:                                   # dry-run 이면 여기서 종료
        print("\n[dry-run] 파일 변경 없음.")
        return

    # ── 실제 교환 ─────────────────────────────────────────────────────
    _save_csv(args.path_a, slots_b)                    # a 파일에 b 데이터 저장
    _save_csv(args.path_b, slots_a)                    # b 파일에 a 데이터 저장
    print(f"\n✅ 교환 완료: {args.path_a} ↔ {args.path_b}")


if __name__ == "__main__":
    main()  # 직접 실행 시 커맨드라인 모드 진입
