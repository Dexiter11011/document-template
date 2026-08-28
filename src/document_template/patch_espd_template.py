#!/usr/bin/env python3
"""One-time patch: demo literals in templates/espd.docx → placeholders."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from .espd_vars import patch_espd_template  # noqa: E402


def main() -> int:
    path = ROOT / "templates" / "espd.docx"
    if not path.is_file():
        raise SystemExit(f"missing {path}")
    ok = patch_espd_template(path)
    print("patched" if ok else "already patched", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
