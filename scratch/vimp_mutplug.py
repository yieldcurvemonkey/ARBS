"""Bind a MUTATED copy of dealer_direction.imputation before collection.

Review-only. Nothing in the worktree is edited -- other agents are running
pytest against this tree concurrently, so the mutate-the-file-and-restore
battery the review used is not safe to repeat here. The mutant is written to
scratch/_vimp_mut/ and injected into ``sys.modules``, so the test file's
``from SDRUtils.dealer_direction import imputation as imp`` picks it up.

The harness is the thing most likely to be silently wrong: if the injection
no-ops, every mutant "survives" and the report is all false findings. So it
asserts the anchor was unique, that the swap landed, and that the loaded file
is the mutant.
"""
from __future__ import annotations

import json
import os
import sys

REAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "SDRUtils", "dealer_direction", "imputation.py")
NAME = "SDRUtils.dealer_direction.imputation"


def pytest_configure(config):
    old, new = json.loads(os.environ["ARBS_VIMP_MUT"])
    src = open(REAL, encoding="utf-8").read()
    if old:
        n = src.count(old)
        assert n == 1, f"anchor is not unique ({n} hits): {old!r}"
        src = src.replace(old, new)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vimp_mut",
                       "imputation.py")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(src)

    import SDRUtils.dealer_direction as pkg
    import importlib.util
    sys.modules.pop(NAME, None)
    spec = importlib.util.spec_from_file_location(NAME, out)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "SDRUtils.dealer_direction"
    sys.modules[NAME] = mod
    spec.loader.exec_module(mod)
    setattr(pkg, "imputation", mod)

    assert os.path.abspath(sys.modules[NAME].__file__) == os.path.abspath(out)
    if old:
        assert old not in open(mod.__file__, encoding="utf-8").read() or old == new
    print(f"\n[vimp] imputation loaded from {mod.__file__}", file=sys.stderr)
