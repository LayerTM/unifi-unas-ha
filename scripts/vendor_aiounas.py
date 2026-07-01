#!/usr/bin/env python3
"""Vendor the aiounas client into the integration so it ships with HACS.

`src/aiounas` is the source of truth. This copies it into the integration
package as `custom_components/unifi_unas_rest/aiounas/`, so the integration has
no external (PyPI) dependency — Home Assistant already ships aiohttp + yarl.

CI runs this and fails if the vendored copy has drifted from the source
(`git diff --exit-code` after running it).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "aiounas"
DST = ROOT / "custom_components" / "unifi_unas_rest" / "aiounas"


def main() -> int:
    if not SRC.is_dir():
        print(f"source not found: {SRC}", file=sys.stderr)
        return 1
    if DST.exists():
        shutil.rmtree(DST)
    # cli.py / mcp bring in optional deps (typer, mcp) the HA integration must not
    # require — exclude them from the vendored copy.
    shutil.copytree(
        SRC, DST, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "cli.py", "mcp*")
    )
    print(f"vendored {SRC} -> {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
