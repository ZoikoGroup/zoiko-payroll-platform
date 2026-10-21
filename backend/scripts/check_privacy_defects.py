"""
scripts/check_privacy_defects.py
--------------------------------
ZP-PRIV F06 release gate: exits 1 when the privacy defect register
(docs/privacy/defect_register.csv) has an open critical privacy defect or an
open exception against a P0 control. Read-only and idempotent.

    python -m scripts.check_privacy_defects [--register PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.security.assurance import DEFECTS_PATH, open_blocking_defects  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--register", type=Path, default=DEFECTS_PATH)
    args = parser.parse_args(argv)
    blocking = open_blocking_defects(args.register)
    if blocking:
        for item in blocking:
            print(f"BLOCKING  {item['id']}: {item['reason']}")
        print(f"FAIL: {len(blocking)} open critical privacy defect(s) / P0 exception(s)")
        return 1
    print("OK: no open critical privacy defect and no open P0 exception")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
