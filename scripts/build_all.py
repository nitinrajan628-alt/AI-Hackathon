"""Convenience runner: build demo data, generate reports, validate.

    python scripts/build_all.py
"""
from __future__ import annotations

import subprocess
import sys
import os

HERE = os.path.dirname(__file__)


def main() -> int:
    for script in ("build_demo_data.py", "build_reports.py", "validate_data.py"):
        print(f"\n=== {script} ===")
        result = subprocess.run([sys.executable, os.path.join(HERE, script)])
        if result.returncode != 0:
            print(f"{script} failed; stopping.")
            return result.returncode
    print("\nBuild complete: data/reserve_review.db is packaged and validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
