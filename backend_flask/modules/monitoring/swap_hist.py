# 파일 경로: modules/monitoring/swap_hist.py
# 역할: hist_jam_a.csv ↔ hist_jam_b.csv 를 교환한다.
#        장면 전환 후 Up/Down 예측이 뒤집힌 경우 1회 실행하면 복구된다.
#        서버 코드가 아닌 수동 실행 유틸이다.
#
# 사용 예시:
#   python swap_hist.py                              → flow_maps/ 전체 탐색
#   python swap_hist.py "flow_maps/gyeongbu_양재"   → 특정 카메라 폴더만 처리

import sys
import shutil
from pathlib import Path


def swap_hist(directory: Path) -> None:
    """hist_jam_a.csv ↔ hist_jam_b.csv 파일을 교환한다.

    두 파일이 모두 있으면 내용을 교환한다.
    한 파일만 있으면 이름만 변경한다.
    Windows에서는 rename이 덮어쓰기를 지원하지 않으므로 shutil.copy2를 사용한다.
    """
    a = directory / "hist_jam_a.csv"  # A방향 CSV 파일 경로
    b = directory / "hist_jam_b.csv"  # B방향 CSV 파일 경로

    if not a.exists() and not b.exists():
        print(f"[오류] {directory} 에 hist_jam_a.csv / hist_jam_b.csv 없음")
        return

    tmp = directory / "_hist_jam_tmp.csv"  # 임시 파일 (교환 중간 단계)

    if a.exists() and b.exists():
        # 두 파일 모두 있음 → 내용 교환
        shutil.copy2(str(a), str(tmp))   # a → tmp (백업)
        shutil.copy2(str(b), str(a))     # b → a
        shutil.copy2(str(tmp), str(b))   # tmp → b
        tmp.unlink()                     # 임시 파일 삭제
        print(f"✅ 교환 완료: {a.name} ↔ {b.name}  ({directory})")
    elif a.exists() and not b.exists():
        # a만 있음 → b로 이름 변경
        shutil.copy2(str(a), str(b))
        a.unlink()
        print(f"✅ {a.name} → {b.name} 이름 변경 완료  ({directory})")
    elif b.exists() and not a.exists():
        # b만 있음 → a로 이름 변경
        shutil.copy2(str(b), str(a))
        b.unlink()
        print(f"✅ {b.name} → {a.name} 이름 변경 완료  ({directory})")


if __name__ == "__main__":
    # 이 스크립트가 위치한 monitoring/ 폴더를 프로젝트 루트로 사용
    PROJECT_ROOT = Path(__file__).resolve().parent

    if len(sys.argv) > 1:
        target = Path(sys.argv[1])         # 사용자 지정 경로
    else:
        target = PROJECT_ROOT / "flow_maps"  # 기본: monitoring/flow_maps/ 전체

    # 지정 폴더 + 하위 1단계 폴더 처리 (camera_id별 하위 폴더 포함)
    if target.is_dir():
        candidates = [target] + [d for d in target.iterdir() if d.is_dir()]
    else:
        candidates = [target.parent]

    found = False
    for d in candidates:
        # hist_jam_a.csv 또는 hist_jam_b.csv 가 있는 폴더만 처리
        if (d / "hist_jam_a.csv").exists() or (d / "hist_jam_b.csv").exists():
            swap_hist(d)
            found = True

    if not found:
        print("교환할 CSV 파일을 찾지 못했습니다.")
        print("사용법: python swap_hist.py [폴더경로]")
