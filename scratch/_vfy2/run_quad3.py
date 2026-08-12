"""Run the reviewer's own `rev_up_quad3.py` unmodified, against either the
current module or the pre-fix HEAD one.

The script imports `SDRUtils.dealer_direction.upfront` by name and uses only
its public API, so swapping the implementation underneath it is enough -- the
reproduction itself is not edited, which is the point.
"""
from __future__ import annotations

import importlib
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ["ARBS_SUPABASE_ENABLED"] = "0"
os.chdir(ROOT)

which = sys.argv[1]
src_path = os.path.join(HERE, "head_upfront.py" if which == "head"
                        else "cur_upfront.py")

pkg = importlib.import_module("SDRUtils.dealer_direction")
mod = types.ModuleType("SDRUtils.dealer_direction.upfront")
mod.__file__ = src_path
mod.__package__ = "SDRUtils.dealer_direction"
sys.modules["SDRUtils.dealer_direction.upfront"] = mod
exec(compile(open(src_path, encoding="utf-8").read(), src_path, "exec"),
     mod.__dict__)
setattr(pkg, "upfront", mod)

print(f"########## {which.upper()} ({os.path.basename(src_path)}) ##########")
script = os.path.join(ROOT, "scratch", "rev_up_quad3.py")
g = {"__name__": "__main__", "__file__": script}
exec(compile(open(script, encoding="utf-8").read(), script, "exec"), g)
