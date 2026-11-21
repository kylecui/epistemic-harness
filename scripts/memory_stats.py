#!/usr/bin/env python3
"""Report memory reuse (G6): are persisted claims actually being used?

    python scripts/memory_stats.py            # read-only report
    python scripts/memory_stats.py --archive  # move stale candidates to l5_store/archive/

Hit ratio = gate runs whose claims cited at least one persisted memory id.
Archive candidates = L5 claims never cited and older than the retention window.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from mcp_server.memory_stats import archive, stats  # noqa: E402


def main() -> int:
    do_archive = "--archive" in sys.argv
    if do_archive:
        result = archive(REPO_ROOT)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    report = stats(REPO_ROOT)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
