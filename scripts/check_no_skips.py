#!/usr/bin/env python3
"""Gate 5 helper: fail if the junit report contains skipped tests.

Usage: check_no_skips.py <junit.xml>
"""

import sys
import xml.etree.ElementTree as ET


def main() -> int:
    root = ET.parse(sys.argv[1]).getroot()
    suites = root.iter("testsuite")
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    if skipped:
        print(f"FAIL: {skipped} scenario(s) were skipped — all scenarios must run")
        return 1
    print("no skipped scenarios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
