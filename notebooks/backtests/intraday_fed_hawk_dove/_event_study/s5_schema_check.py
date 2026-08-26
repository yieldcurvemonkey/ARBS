"""Assert both parquets carry exactly what the brief asked for, with the right
semantics - not just the right column names."""
from __future__ import annotations

import datetime
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

REQUIRED = ["event_id", "speech_ts", "date", "speaker", "role", "is_voter",
            "stance_score_exante", "stance_sign", "bucket", "contract_rank", "symbol",
            "offset_min", "price", "rate_bp", "d_rate_bp_from_baseline", "signed_d_bp",
            "is_overlapping", "days_to_fomc", "is_fomc_day", "is_cpi_day", "is_nfp_day",
            "is_placebo"]
OFFSETS = [-120, -90, -60, -45, -30, -20, -15, -10, -5, 0,
           5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300]

fails: list[str] = []


def chk(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


for name, want_placebo in (("event_paths.parquet", False),
                           ("placebo_paths.parquet", True)):
    fp = HERE / name
    print("=" * 74)
    print(name)
    if not fp.exists():
        chk(False, "file exists")
        continue
    d = pd.read_parquet(fp)
    print(f"  {len(d):,} rows, {d['event_id'].nunique()} events, "
          f"ranks {sorted(d['contract_rank'].unique())}")
    chk(all(c in d.columns for c in REQUIRED),
        f"all {len(REQUIRED)} required columns present"
        + ("" if all(c in d.columns for c in REQUIRED)
           else f" - MISSING {[c for c in REQUIRED if c not in d.columns]}"))
    chk(str(d["speech_ts"].dtype) == "datetime64[ns, America/New_York]",
        f"speech_ts is tz-aware NY (got {d['speech_ts'].dtype})")
    chk(isinstance(d["date"].iloc[0], datetime.date), "date is a datetime.date")
    chk(sorted(d["offset_min"].unique()) == OFFSETS, "offsets are exactly the 22 asked for")
    chk(bool((d["is_placebo"] == want_placebo).all()),
        f"is_placebo is uniformly {want_placebo}")
    chk(set(d["stance_sign"].unique()) <= {-1, 0, 1},
        f"stance_sign in {{-1,0,1}} (got {sorted(d['stance_sign'].unique())})")
    per = d.groupby(["event_id", "contract_rank"]).size()
    chk(bool((per == len(OFFSETS)).all()),
        f"every (event, rank) has exactly {len(OFFSETS)} rows")
    chk(not d.duplicated(["event_id", "contract_rank", "offset_min"]).any(),
        "no duplicate (event_id, rank, offset)")

    m = d[d["price"].notna()]
    chk(np.allclose(m["rate_bp"], (100 - m["price"]) * 100), "rate_bp == (100-price)*100")
    b = d[d["signed_d_bp"].notna()]
    chk(np.allclose(b["signed_d_bp"], b["d_rate_bp_from_baseline"] * b["stance_sign"]),
        "signed_d_bp == d_rate_bp_from_baseline * stance_sign")
    chk(bool((d.loc[d["stance_sign"] == 0, "signed_d_bp"].isna()).all()),
        "unsigned events carry NaN signed_d_bp, never 0")
    base = d[d["offset_min"] == -60]
    chk(bool(np.allclose(base["d_rate_bp_from_baseline"].dropna(), 0.0)),
        "d_rate_bp_from_baseline is exactly 0 at the -60 baseline")
    chk(bool((d["baseline_offset_min"] == -60).all()),
        "baseline_offset_min column states -60")
    # a price must never come from a bar labelled at or after its own timestamp.
    # Checked on EVERY labelled row, including the ones whose price was voided.
    q = d[d["bar_label_ts"].notna()]
    tq = q["speech_ts"] + pd.to_timedelta(q["offset_min"], unit="m")
    chk(bool((q["bar_label_ts"] < tq).all()),
        "every bar used is labelled STRICTLY BEFORE its offset timestamp (no lookahead)")
    # bar_label_ts is retained as a diagnostic even where the price was voided for
    # staleness, so the cap applies to PRICED rows - scoping this to all labelled
    # rows is what a first draft of this check got wrong.
    pr = d[d["price"].notna()]
    chk(bool((pr["stale_min"] <= 15.0 + 1e-9).all()),
        f"no PRICED row exceeds the 15-min staleness cap "
        f"(max priced stale {pr['stale_min'].max():g}; "
        f"{int((d['stale_min'] > 15).sum())} rows voided for staleness, all NaN-priced)")
    chk(bool(d.loc[d["stale_min"] > 15.0, "price"].isna().all()),
        "every row beyond the cap really is NaN-priced")
    if want_placebo:
        chk("parent_event_id" in d.columns, "placebo carries parent_event_id")
        chk(bool((~d["is_fomc_day"]).all()),
            "no placebo lands on an FOMC decision day")

    md = pq.read_schema(fp).metadata or {}
    for k in (b"bar_rule", b"baseline_offset_min", b"sign_convention", b"stale_cap_min"):
        chk(k in md, f"parquet metadata carries {k.decode()}")

print("=" * 74)
print("SCHEMA CHECK:", "PASS" if not fails else f"{len(fails)} FAILURES")
for f in fails:
    print("   -", f)
sys.exit(1 if fails else 0)
