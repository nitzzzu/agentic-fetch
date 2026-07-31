#!/usr/bin/env python3
"""Gate 7: enforce the mutation-kill floor from mutmut's CI stats export.

Usage: check_mutation.py <mutants/mutmut-cicd-stats.json> <min_killed_pct>

The score counts every generated mutant: killed / total. Mutants with no
covering tests (`no_tests`) therefore count against the score — an
uncovered mutant is a missing test, not a tool quirk.
"""

import json
import sys


def main() -> int:
    path, min_pct = sys.argv[1], float(sys.argv[2])
    stats = json.load(open(path))
    total = stats["total"]
    killed = stats["killed"]
    if total == 0:
        print("FAIL: no mutants were generated — mutation scope is empty")
        return 1

    pct = 100.0 * killed / total
    print(
        f"mutation: {killed}/{total} killed = {pct:.1f}% (floor {min_pct}%), "
        f"{stats['survived']} survived, {stats['no_tests']} uncovered, "
        f"{stats['timeout']} timeout, {stats['suspicious']} suspicious"
    )
    if pct < min_pct:
        print(f"FAIL: mutation score {pct:.1f}% is below the {min_pct}% floor")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
