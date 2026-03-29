"""Test forward-starting fly P&L (the actual JPM RV backtest component flies).

The JPM RV universe uses forward flies like 1Yx1Y, 2Yx1Y, etc.
This test checks if forward flies diverge more than spot flies.
"""

import datetime
import numpy as np
import pandas as pd

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapStructure import IRSwapStructure, IRSwapStructureFunctionMap

CURVE = "USD-SOFR-1D"

print("Loading curves...")
mdp_rl = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
mdp_ql = IRSwapsMDP(source="ERIS_EOD_LIVE-QL_BASIC")

# Test with consecutive dates
test_pairs = [
    (datetime.date(2024, 3, 4), datetime.date(2024, 3, 5)),
    (datetime.date(2024, 6, 3), datetime.date(2024, 6, 4)),
    (datetime.date(2024, 9, 3), datetime.date(2024, 9, 4)),
    (datetime.date(2024, 12, 2), datetime.date(2024, 12, 3)),
]

# JPM RV style flies (gap_mm category)
fly_specs = [
    # (front, belly, back, category)
    ("1Y", "2Y", "3Y", "spot"),
    ("2Y", "5Y", "10Y", "spot"),
    ("3Y", "5Y", "7Y", "spot"),
    ("1Yx1Y", "1Yx2Y", "1Yx3Y", "fwd_1Y"),
    ("2Yx1Y", "2Yx2Y", "2Yx3Y", "fwd_2Y"),
    ("3Yx1Y", "3Yx2Y", "3Yx3Y", "fwd_3Y"),
]

print("Done.\n")

print("=" * 70)
print("FLY P&L comparison: RL vs QL across fly types and date pairs")
print("=" * 70)

results = []

for dt1, dt2 in test_pairs:
    print(f"\n  Date pair: {dt1} -> {dt2}")
    try:
        c_rl_1 = mdp_rl.get_data({"curve_name": CURVE, "timestamp": dt1})
        c_rl_2 = mdp_rl.get_data({"curve_name": CURVE, "timestamp": dt2})
        c_ql_1 = mdp_ql.get_data({"curve_name": CURVE, "timestamp": dt1})
        c_ql_2 = mdp_ql.get_data({"curve_name": CURVE, "timestamp": dt2})
    except Exception as e:
        print(f"    Skip: {e}")
        continue

    for front, belly, back, cat in fly_specs:
        try:
            struct_rl = IRSwapStructureFunctionMap(curve=c_rl_1)
            struct_ql = IRSwapStructureFunctionMap(curve=c_ql_1)

            pkg_rl, rw_rl = struct_rl.apply(
                IRSwapStructure.FLY,
                front_tenor=front, belly_tenor=belly, back_tenor=back,
                bpv=100_000,
            )
            pkg_ql, rw_ql = struct_ql.apply(
                IRSwapStructure.FLY,
                front_tenor=front, belly_tenor=belly, back_tenor=back,
                bpv=100_000,
            )

            # Entry
            res_rl_e = [c_rl_1.resolve_pricable(p, rw) for p, rw in zip(pkg_rl, rw_rl)]
            res_ql_e = [c_ql_1.resolve_pricable(p, rw) for p, rw in zip(pkg_ql, rw_ql)]
            npv_rl_e = sum(c_rl_1.npv(s) for s in res_rl_e)
            npv_ql_e = sum(c_ql_1.npv(s) for s in res_ql_e)

            # MTM
            res_rl_m = [c_rl_2.resolve_pricable(p, rw) for p, rw in zip(pkg_rl, rw_rl)]
            res_ql_m = [c_ql_2.resolve_pricable(p, rw) for p, rw in zip(pkg_ql, rw_ql)]
            npv_rl_m = sum(c_rl_2.npv(s) for s in res_rl_m)
            npv_ql_m = sum(c_ql_2.npv(s) for s in res_ql_m)

            pnl_rl = npv_rl_m - npv_rl_e
            pnl_ql = npv_ql_m - npv_ql_e

            ratio = pnl_rl / pnl_ql if abs(pnl_ql) > 1 else float("nan")
            results.append({
                "date": f"{dt1}",
                "fly": f"{front}/{belly}/{back}",
                "cat": cat,
                "pnl_rl": pnl_rl,
                "pnl_ql": pnl_ql,
                "ratio": ratio,
                "diff": pnl_rl - pnl_ql,
            })
            print(f"    {cat:>8s} {front}/{belly}/{back}: RL={pnl_rl:>12,.2f}  QL={pnl_ql:>12,.2f}  ratio={ratio:.4f}  diff={pnl_rl-pnl_ql:>10,.2f}")
        except Exception as e:
            print(f"    {cat:>8s} {front}/{belly}/{back}: Error: {e}")

if results:
    df = pd.DataFrame(results)
    print("\n" + "=" * 70)
    print("SUMMARY BY CATEGORY")
    print("=" * 70)
    for cat in df["cat"].unique():
        sub = df[df["cat"] == cat]
        corr = np.corrcoef(sub["pnl_rl"], sub["pnl_ql"])[0, 1] if len(sub) > 2 else float("nan")
        mean_ratio = sub["ratio"].dropna().mean()
        mean_diff = sub["diff"].abs().mean()
        print(f"\n  {cat}:")
        print(f"    Correlation: {corr:.4f}")
        print(f"    Mean ratio:  {mean_ratio:.4f}")
        print(f"    Mean |diff|: {mean_diff:,.2f}")

    print(f"\n  Overall:")
    corr = np.corrcoef(df["pnl_rl"], df["pnl_ql"])[0, 1]
    print(f"    Correlation: {corr:.4f}")
    print(f"    Mean ratio:  {df['ratio'].dropna().mean():.4f}")
    print(f"    Mean |diff|: {df['diff'].abs().mean():,.2f}")
