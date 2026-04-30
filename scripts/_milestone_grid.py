"""Drive the cached-only grid against whatever sparse-listed pickles
have landed so far, dump the comparison table, and emit a markdown
snapshot suitable for appending to the SFR Convex Screener report.

Used at every 25-pickle milestone during the re-prime to keep the
report fresh as the cache grows.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

CACHE_ROOT = REPO_ROOT / "data" / "screener_results" / "sfr_convex_screener_backtest_cache"
GRID_ROOT = REPO_ROOT / "data" / "screener_results" / "sfr_convex_screener_backtest_grid"


def _list_cached_dates(hash_prefix: str) -> list[datetime.date]:
    out: list[datetime.date] = []
    for p in sorted(CACHE_ROOT.glob(f"*_{hash_prefix}.pkl")):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})_", p.name)
        if m:
            out.append(datetime.date.fromisoformat(m.group(1)))
    return sorted(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hash", default="ae57a6143fe6",
                   help="Cache hash prefix to enumerate. Default = listed + (HGC, PC).")
    p.add_argument("--end", default="2026-04-28")
    args = p.parse_args()

    dates = _list_cached_dates(args.hash)
    if not dates:
        print(f"No pickles for hash {args.hash} — skipping grid.")
        return 0
    start = dates[0]
    end = datetime.date.fromisoformat(args.end)
    print(f"## milestone snapshot — listed_cache={len(dates)} | window {start} -> {end}")

    # 1) wipe per-config artefacts so the new grid replaces stale results
    grid_dir = GRID_ROOT
    if grid_dir.exists():
        for f in grid_dir.rglob("*"):
            if f.is_file():
                f.unlink()

    # 2) drive the cached-only grid
    cmd = [
        "conda", "run", "--no-capture-output", "-n", "stir", "python", "-u",
        str(REPO_ROOT / "scripts" / "run_screener_backtest_cached_only.py"),
        "--start", start.isoformat(), "--end", end.isoformat(),
    ]
    print(f"\n$ {' '.join(cmd)}\n")
    rc = subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode
    if rc != 0:
        print(f"[!] cached-only grid exited rc={rc}")
        return rc

    # 3) read grid_summary.json for the table
    summary_path = grid_dir / "grid_summary.json"
    if not summary_path.exists():
        print("[!] grid_summary.json missing — grid run produced no output")
        return 1
    with summary_path.open() as fh:
        summary = json.load(fh)

    print(f"\n### Cache evolution snapshot — listed_cache = {len(dates)}, window {start} -> {end}\n")
    print("| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |")
    print("|---|---|---|---|---|---|---|---|---|")
    for name, s in summary.items():
        print(
            f"| `{name}` | {s.get('n_trades', 0)} | {s.get('n_unrealized_open', 0)} | "
            f"{float(s.get('sharpe', float('nan'))):.2f} | "
            f"{float(s.get('max_drawdown', 0)):,.0f} | {float(s.get('final_mtm', 0)):,.0f} | "
            f"{float(s.get('win_rate', float('nan'))):.2%} | "
            f"{float(s.get('avg_holding_days', float('nan'))):.1f} | "
            f"{float(s.get('elapsed_s', 0)):.1f} |"
        )

    print(
        f"\nFirst cached date: {start.isoformat()}; "
        f"last cached date: {dates[-1].isoformat()}; "
        f"contiguous? {len(dates) == (dates[-1] - dates[0]).days + 1}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
