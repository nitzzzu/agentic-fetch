#!/usr/bin/env python3
"""Gate 6: enforce line and branch coverage floors from coverage.json.

Usage: check_coverage.py <coverage.json> <line_min_pct> <branch_min_pct>
"""

import json
import sys


def main() -> int:
    path, line_min, branch_min = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    totals = json.load(open(path))["totals"]
    line_pct = 100.0 * totals["covered_lines"] / totals["num_statements"]
    branch_pct = 100.0 * totals["covered_branches"] / totals["num_branches"]

    print(
        f"coverage: {line_pct:.1f}% line (floor {line_min}%), "
        f"{branch_pct:.1f}% branch (floor {branch_min}%)"
    )

    ok = True
    if line_pct < line_min:
        print(f"FAIL: line coverage {line_pct:.1f}% is below the {line_min}% floor")
        ok = False
    if branch_pct < branch_min:
        print(
            f"FAIL: branch coverage {branch_pct:.1f}% is below the {branch_min}% floor"
        )
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
