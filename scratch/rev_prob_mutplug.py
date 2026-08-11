"""Load a MUTATED copy of dealer_direction.probability in place of the real one.

Review-only harness. Nothing in the worktree is edited: the mutant lives in
scratch/ and is bound into ``sys.modules`` before collection, so the test file's
``from SDRUtils.dealer_direction import probability as prob`` picks it up.

The harness itself is the thing most likely to be silently wrong -- if the
injection no-ops, every mutation "survives" and the review manufactures false
"this test cannot fail" findings. So it asserts the swap landed and prints the
mutant's own source line for the caller to eyeball.
"""
from __future__ import annotations

import importlib.util
import os
import sys


def pytest_configure(config):
    mut = os.environ["ARBS_MUT_PATH"]
    name = "SDRUtils.dealer_direction.probability"
    import SDRUtils.dealer_direction as pkg

    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, mut)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    setattr(pkg, "probability", m)

    loaded = sys.modules[name].__file__
    assert os.path.abspath(loaded) == os.path.abspath(mut), (loaded, mut)
    print(f"\n[mutplug] probability loaded from {loaded}", file=sys.stderr)
