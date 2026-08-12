"""The specific Fed Funds failure F-20 found on the OLD curve: per-MEETING bias.

The MIX23 build did not merely have a level offset on Fed Funds - its meeting
steps were in the wrong places, so the sign of (printed - mid) flipped between
adjacent meetings: ``FOMC_APR26`` +1.32 bp / 82.4% above mid against
``FOMC_JUL26`` -0.68 bp / 18.1% above. An aggregate median near zero can hide
exactly that, by averaging two opposite biases, so the aggregate result in dd14
is not on its own an all-clear for meeting-dated Fed Funds prints.

This re-cuts the dd14 sample by ``fomc_meeting_label`` and by
``special_tenor_type``. No new pricing: the same 215 marks, grouped differently.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from scipy import stats

from dd_measure import connect, describe, read_sql
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

pd.set_option("display.width", 260)


def main() -> None:
    out = pd.read_csv("C:/Users/chris/clee/ARBS-dd/scratch/out_ff_bias.csv")
    ids = [str(t) for t in out["trade_id"]]
    conn = connect()
    tags = read_sql(conn, f"""
        SELECT trade_id, special_tenor_type, fomc_meeting_label, is_fomc_dated,
               is_off_date, tenor_label
        FROM {LEGS_TABLE} WHERE trade_id = ANY(%(ids)s)""", {"ids": ids})
    conn.close()
    out["trade_id"] = out["trade_id"].astype(str)
    tags["trade_id"] = tags["trade_id"].astype(str)
    d = out.merge(tags, on="trade_id", how="left")
    ok = d.dropna(subset=["diff_bp"])

    print(f"n with a mid = {len(ok)}")
    print("\n=== by special_tenor_type ===")
    for k, g in ok.groupby(ok["special_tenor_type"].fillna("<none>")):
        describe(g["diff_bp"], str(k))

    print("\n=== FOMC-dated vs not ===")
    for k, g in ok.groupby(ok["is_fomc_dated"].fillna(False)):
        describe(g["diff_bp"], f"is_fomc_dated={k}")

    print("\n=== by FOMC meeting label (the cut where the old curve flipped sign) ===")
    lab = ok["fomc_meeting_label"].fillna("<none>")
    counts = lab.value_counts()
    shown = 0
    meds = []
    for k in counts.index:
        g = ok[lab == k]
        if k == "<none>":
            continue
        if len(g) >= 5:
            describe(g["diff_bp"], str(k))
            meds.append(g["diff_bp"].median())
            shown += 1
    if shown == 0:
        print(f"  no meeting bucket reaches n=5. bucket sizes: "
              f"{counts.drop('<none>', errors='ignore').head(12).to_dict()}")
    else:
        m = np.array(meds)
        print(f"\n  {shown} meeting buckets with n>=5: medians span "
              f"{m.min():+.3f} .. {m.max():+.3f} bp, "
              f"{int((m > 0).sum())} positive / {int((m < 0).sum())} negative")
        print("  (F-20 on the OLD curve: FOMC_APR26 +1.32 vs FOMC_JUL26 -0.68, "
              "82.4% vs 18.1% above mid)")

    print("\n=== all meeting-dated prints pooled ===")
    pooled = ok[lab != "<none>"]["diff_bp"]
    if len(pooled) >= 10:
        describe(pooled, "meeting-dated")
        x = pooled.to_numpy()
        rng = np.random.default_rng(20260811)
        boot = np.median(rng.choice(x, size=(25_000, len(x)), replace=True), axis=1)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        print(f"  bootstrap 95% CI on the median: [{lo:+.4f}, {hi:+.4f}] bp -> "
              f"{'INCLUDES zero' if lo <= 0 <= hi else 'EXCLUDES ZERO'}")
        n_pos = int((x > 0).sum())
        print(f"  sign test {n_pos}/{len(x)} above mid, p = "
              f"{stats.binomtest(n_pos, len(x), 0.5).pvalue:.4f}")

    print("\n=== off-date vs on-date ===")
    for k, g in ok.groupby(ok["is_off_date"].fillna(False)):
        describe(g["diff_bp"], f"is_off_date={k}")


if __name__ == "__main__":
    main()
