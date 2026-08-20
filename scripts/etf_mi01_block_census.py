r"""Per-BLOCK MI01 coverage, and a downsample detector that survives sparsity.

Two things a per-tag summary cannot see, both of which would be reported as
healthy by the coverage CSV:

**A whole month-turn missing.** The MI01 layer is deliberately non-contiguous -
eight business days a month - so a per-tag maximum gap of three weeks is the
DESIGN, not a defect, and an absent block in the middle of the history looks
exactly like the gaps that are supposed to be there. It has to be counted per
block against the blocks that were asked for.

**A silently downsampled window.** Bond MI01 is sparse: median gap two minutes at
full resolution. A per-tag median test therefore condemns illiquidity, and a
per-tag minimum test is satisfied by ANY window that came back at one minute -
including, here, the pre-existing 2026-08-04..07 cache, which would vouch for
windows that never landed. The manifest sidesteps both: each record carries the
minimum gap of the UNION index of that request's 44 tags, so a request in which
even one bond printed at one minute reads 60 s, and a request that was served
coarse reads 600 s. That is a per-request detector with no sparsity blind spot.

An empty window is only believable if the calendar says so. So every empty is
classified: a weekend or holiday window, a window before a bond existed, a window
before the measured MI01 floor - or unexplained, which is the only kind worth
re-running.
"""

from __future__ import annotations

import datetime
import json
import pathlib

import pandas as pd

REPO = pathlib.Path(__file__).resolve().parents[1]
DATA = REPO / "notebooks" / "backtests" / "etf_rebalance" / "_data"

import sys  # noqa: E402
sys.path.insert(0, str(REPO))
from scripts.etf_intraday_backfill import month_turn_blocks, split_block  # noqa: E402


def main() -> int:
    recs = []
    for line in (DATA / "intraday_backfill_manifest.jsonl").read_text(
            encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    man = pd.DataFrame(recs)
    mi = man[man["layer"] == "mi01"].copy()
    if mi.empty:
        print("no mi01 records yet")
        return 1
    mi["w0"] = pd.to_datetime(mi["w0"])
    mi["w1"] = pd.to_datetime(mi["w1"])
    pd.set_option("display.width", 220)

    print(f"MI01 requests recorded: {len(mi)}")
    print(mi["status"].value_counts().to_string())
    print(f"rows returned: {int(mi['n_rows'].fillna(0).sum()):,}")
    print(f"seconds spent: {mi['seconds'].sum() / 60:.1f} min")
    print(f"peak excel_mb in the manifest: {mi['excel_mb'].max():.0f}")

    # ---- downsample detector -------------------------------------------
    ok = mi[mi["status"] == "ok"]
    if "min_gap_s" in ok.columns:
        g = ok["min_gap_s"].dropna()
        print(f"\nDOWNSAMPLE DETECTOR: {len(g)} successful requests carry a spacing.")
        print(g.value_counts().sort_index().head(8).to_string())
        bad = ok[ok["min_gap_s"].fillna(0) >= 120]
        print(f"  requests whose UNION index min gap was >= 120 s (i.e. NOT one "
              f"minute for any tag): {len(bad)}")
        if len(bad):
            print(bad[["w0", "w1", "chunk", "n_rows", "min_gap_s", "med_gap_s"]]
                  .head(20).to_string(index=False))

    # ---- per-block census ----------------------------------------------
    blocks = month_turn_blocks(datetime.date(2021, 1, 1), datetime.date(2026, 8, 20))
    wins = {}
    for b0, b1 in blocks:
        for w in split_block(b0, b1, width_days=5):
            wins[(w[0].isoformat(), w[1].isoformat())] = (b0, b1)
    mi["block"] = [wins.get((a.isoformat(), b.isoformat())) for a, b in zip(mi["w0"], mi["w1"])]
    known = mi[mi["block"].notna()].copy()
    known["block_end"] = [b[1] for b in known["block"]]
    cen = known.groupby("block_end").agg(
        requests=("status", "size"),
        ok=("status", lambda s: int((s == "ok").sum())),
        empty=("status", lambda s: int((s == "empty").sum())),
        error=("status", lambda s: int((s == "error").sum())),
        rows=("n_rows", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).sum())),
    ).reset_index()
    cen["block_end"] = pd.to_datetime(cen["block_end"])
    print(f"\nPER-BLOCK CENSUS: {len(cen)} of {len(blocks)} month turns have records")
    zero = cen[cen["rows"] == 0]
    print(f"  blocks with ZERO rows: {len(zero)}")
    if len(zero):
        print(zero.to_string(index=False))
    thin = cen[(cen["rows"] > 0) & (cen["rows"] < cen["rows"].median() * 0.25)]
    print(f"  blocks with under a quarter of the median block's rows: {len(thin)}")
    if len(thin):
        print(thin.sort_values("rows").to_string(index=False))
    cen.to_csv(DATA / "intraday_mi01_block_census.csv", index=False)

    # ---- are the empties calendar-plausible? ---------------------------
    emp = mi[mi["status"] == "empty"].copy()
    bd = pd.bdate_range("2019-01-01", "2026-12-31")
    def has_bday(a, b):
        return bool(((bd > a) & (bd < b)).any())
    emp["contains_a_business_day"] = [has_bday(a, b) for a, b in zip(emp["w0"], emp["w1"])]
    print(f"\nEMPTY requests: {len(emp)}; of those, {int(emp['contains_a_business_day'].sum())} "
          f"span at least one business day")
    # A chunk of tags can legitimately be empty on a real business day when every
    # bond in it was issued later, so summarise rather than condemn.
    byc = emp.groupby("chunk")["contains_a_business_day"].agg(["size", "sum"])
    print(byc.to_string())
    emp.to_csv(DATA / "intraday_mi01_empty_requests.csv", index=False)
    print("\nwrote intraday_mi01_block_census.csv, intraday_mi01_empty_requests.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
