"""Run the fast gate in bounded chunks, and report every chunk's exit code.

    <env>/python.exe scripts/perf/run_fast_gate_chunked.py [--chunks 6]

Why chunked: two whole-suite runs on this machine were killed mid-stream - one at
75%, one at 14% - with no traceback and no failure, while a second pytest from
another session was also on the box. A single 40-minute process that dies tells
you nothing; six 7-minute ones tell you exactly which files were covered and
which were not.

Prints one line per chunk and a final roll-up. Exit code is non-zero if ANY
chunk failed or died, so "it passed" cannot be claimed from a partial run.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKERS = "not slow and not network and not db"
SUMMARY = re.compile(r"^[=\s]*\d+ (passed|failed|error)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", type=int, default=6)
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args()

    files = sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))
    size = (len(files) + args.chunks - 1) // args.chunks
    groups = [files[i : i + size] for i in range(0, len(files), size)]

    env = dict(os.environ, ARBS_SUPABASE_ENABLED="0")
    results = []
    for i, group in enumerate(groups, 1):
        print(f"\n=== chunk {i}/{len(groups)}: {group[0]} .. {group[-1]} "
              f"({len(group)} files)", flush=True)
        proc = subprocess.run(
            [args.python, "-m", "pytest", *[f"tests/{f}" for f in group],
             "-m", MARKERS, "-q", "-p", "no:randomly", "-W", "ignore",
             "-p", "no:cacheprovider", "--no-header"],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
        )
        out = (proc.stdout or "").splitlines()
        summary = next((l for l in reversed(out) if SUMMARY.match(l.strip())), "")
        if not summary:
            summary = next((l for l in reversed(out) if l.strip()), "<no output>")
        print(f"    exit {proc.returncode}: {summary.strip()}", flush=True)
        if proc.returncode != 0:
            fails = [l for l in out if l.startswith("FAILED") or l.startswith("ERROR")]
            for line in fails[:25]:
                print(f"      {line}", flush=True)
            if not fails:
                print("      " + "\n      ".join((proc.stderr or "").splitlines()[-10:]),
                      flush=True)
        results.append((i, proc.returncode, summary.strip()))

    print("\n" + "=" * 70)
    bad = [r for r in results if r[1] != 0]
    for i, code, summary in results:
        print(f"chunk {i}: exit {code}  {summary}")
    print(f"\n{len(results) - len(bad)}/{len(results)} chunks green")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
