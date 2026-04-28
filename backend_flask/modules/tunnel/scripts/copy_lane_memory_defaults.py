"""
Copy verified lane memory JSON files from runtime_data/lane_memory to
lane_memory_defaults so they can be committed and shared with the team.

Usage:
    python backend_flask/modules/tunnel/scripts/copy_lane_memory_defaults.py
    python backend_flask/modules/tunnel/scripts/copy_lane_memory_defaults.py --overwrite
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


TUNNEL_DIR = Path(__file__).resolve().parents[1]
RUNTIME_LANE_MEMORY_DIR = TUNNEL_DIR / "runtime_data" / "lane_memory"
DEFAULT_LANE_MEMORY_DIR = TUNNEL_DIR / "lane_memory_defaults"


def copy_lane_memory_defaults(overwrite: bool = False) -> int:
    DEFAULT_LANE_MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    if not RUNTIME_LANE_MEMORY_DIR.exists():
        print(f"runtime lane memory directory not found: {RUNTIME_LANE_MEMORY_DIR}")
        return 0

    copied = 0
    skipped = 0

    for source_path in sorted(RUNTIME_LANE_MEMORY_DIR.glob("*.json")):
        target_path = DEFAULT_LANE_MEMORY_DIR / source_path.name

        if target_path.exists() and not overwrite:
            skipped += 1
            print(f"skip existing: {target_path}")
            continue

        shutil.copy2(source_path, target_path)
        copied += 1
        print(f"copied: {source_path} -> {target_path}")

    print(f"done: copied={copied}, skipped={skipped}")
    return copied


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="overwrite files that already exist in lane_memory_defaults",
    )
    args = parser.parse_args()
    copy_lane_memory_defaults(overwrite=args.overwrite)


if __name__ == "__main__":
    main()
