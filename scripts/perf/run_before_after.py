"""Before/after, back to back, driving two worktrees with one bench script.

    <env>/python.exe scripts/perf/run_before_after.py --ref <main-worktree> --perf <this-worktree>

Python rather than shell on purpose: git's ``autocrlf`` rewrites ``.sh`` files
on checkout, and a ``\\`` line continuation followed by CRLF escapes the CR
instead of continuing the line, so the script dies with an unmatched quote at a
line that looks fine.

BEFORE and AFTER are interleaved per bench rather than run as two blocks. This
machine is shared, so it is the ratio that survives variable load.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BENCH = "scripts/perf/citivelo_read_path_bench.py"

#: (bench, n) run on BOTH sides.
PAIRED = [("single", 200), ("bulk", 200), ("pricing", 200), ("timeseries", 841), ("eod", 200)]

#: The raw store API, identical on both sides - the diagnosis, not the result.
BEFORE_ONLY = [("components", 100)]

#: The new path's stages, plus the things measured to decide NOT to change them.
AFTER_ONLY = [("components_cached", 200), ("read_strategy", 60), ("swaptions", 40)]

#: Run on AFTER with the opt-in fixings shortcut enabled.
AFTER_OPT_IN = [("pricing", 200), ("timeseries", 841)]

KEEP = re.compile(r"^(\[|    \w)")


def run(py: str, cwd: Path, bench: str, n: int, label: str, env_extra: dict | None = None) -> None:
    print(f"\n--- {label} :: {bench} n={n}", flush=True)
    env = dict(os.environ, ARBS_SUPABASE_ENABLED="0")
    env.update(env_extra or {})
    proc = subprocess.run(
        [py, "-W", "ignore", BENCH, "--bench", bench, "-n", str(n)],
        cwd=str(cwd), env=env, capture_output=True, text=True,
    )
    for line in (proc.stdout or "").splitlines():
        if KEEP.match(line):
            print(line, flush=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-8:])
        print(f"    !! exit {proc.returncode}\n{tail}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--ref", required=True, help="worktree at main")
    ap.add_argument("--perf", required=True, help="this branch's worktree")
    args = ap.parse_args()

    ref, perf = Path(args.ref), Path(args.perf)
    # The reference worktree is at main and has no bench script. Both sides must
    # run the SAME driver; only the code under test differs.
    (ref / "scripts" / "perf").mkdir(parents=True, exist_ok=True)
    shutil.copy2(perf / BENCH, ref / BENCH)

    for bench, n in PAIRED:
        run(args.python, ref, bench, n, "BEFORE")
        run(args.python, perf, bench, n, "AFTER ")

    for bench, n in BEFORE_ONLY:
        run(args.python, ref, bench, n, "BEFORE")

    for bench, n in AFTER_ONLY:
        run(args.python, perf, bench, n, "AFTER ")

    for bench, n in AFTER_OPT_IN:
        run(args.python, perf, bench, n, "AFTER+OPT",
            env_extra={"ARBS_RL_OMIT_UNUSED_FIXINGS": "1"})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
