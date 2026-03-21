#!/usr/bin/env python
"""Compatibility wrapper for STIRF live-service mode."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.stirf_curve_service as _service
from scripts.stirf_curve_service import *  # noqa: F401,F403


def main(argv: Sequence[str] | None = None) -> int:
    arg_list = list(argv) if argv is not None else list(sys.argv[1:])
    return _service.main(["live-service", *arg_list])


if __name__ == "__main__":
    raise SystemExit(main())
