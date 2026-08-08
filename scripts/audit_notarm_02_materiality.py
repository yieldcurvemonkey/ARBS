"""AUDIT (refute-probe) 2: does the negative-notional package change ANY reported number?

Runs the notional arm three ways with every other convention imported from s3_f7_gate:
  A) as committed (negative carried through)
  B) sign-guarded (abs() on the parsed notional -> the "fix" the claim implies)
  C) dropped (the offending package removed entirely)
and diffs every cell. Also runs the COUNT arm (the committed primary) under A/B/C, which
should be bit-identical by construction since count never reads notional.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys

import numpy as np
import pandas as pd

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import s3_f7_gate as g  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)

OUT = g.OUT
HORIZONS = g.HORIZONS

par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
par.index = pd.to_datetime(par.index)
pkg0 = pd.read_parquet(OUT / "f7_packages.parquet")
pkg0["file_date"] = pd.to_datetime(pkg0["file_date"])
uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
dg_all = pd.read_parquet(OUT / "f7_extract_diag.parquet")
file_dates = pd.to_datetime(dg_all["file_date"])
common = par.index.intersection(pd.DatetimeIndex(file_dates))
print(f"sample: {len(common)} file-days {common.min().date()}..{common.max().date()}")

BAD = pkg0["notional_sum"] < 0
bad_row = pkg0[BAD].iloc[0]
BAD_DATE = bad_row["file_date"]
print(f"\noffending package: {BAD_DATE.date()} sig={bad_row['signature']} "
      f"sum={bad_row['notional_sum']:,.0f}")
print(f"is {BAD_DATE.date()} in the gate SAMPLE (par-grid day with an SDR file)? "
      f"{BAD_DATE in common}")

# how big is 5-10's notional on that day, with and without?
sub = pkg0[pkg0["signature"] == "5-10"]
day = sub[sub["file_date"] == BAD_DATE]
print(f"\n5-10 packages on {BAD_DATE.date()}: {len(day)}; "
      f"notional_sum total = {day['notional_sum'].sum():,.0f}")
print(f"  without the negative package: {day.loc[~(day['notional_sum'] < 0), 'notional_sum'].sum():,.0f}")
print(f"  with abs() sign guard:        "
      f"{(day['notional_sum'].abs() * 0 + day['notional_sum'].where(day['notional_sum'] > 0, 70_000_000)).sum():,.0f}"
      f"   (note: abs of the SUM is not the same as summing abs legs)")

# variants ------------------------------------------------------------------
pkg_A = pkg0.copy()                                     # as committed
pkg_B = pkg0.copy()
pkg_B.loc[BAD, "notional_sum"] = 410_000_000.0          # |-240M| + |170M| = sign-guarded legs
pkg_C = pkg0[~BAD].copy()                               # dropped


def run_arm(pkg, mode):
    rows, panels = [], {}
    for sig in uni:
        x = g.structure_series(par, sig).reindex(common).dropna()
        s = pkg[pkg["signature"] == sig]
        flow = (s.groupby("file_date").size() if mode == "count"
                else s.groupby("file_date")["notional_sum"].sum())
        flow = flow.reindex(x.index, fill_value=0).astype(float)
        z = g.zscore(x, g.Z_WIN)
        shock = g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q)
        persistent = (z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1))) \
            & (z.shift(1).abs() >= g.Z_ENTRY)
        rt = g.round_trips(sig)
        panels[sig] = dict(x=x, z=z, persistent=persistent, shock=shock, flow=flow)
        for h in HORIZONS:
            base = dict(signature=sig, h=h, **rt)
            for book, mask in (("all", persistent), ("shock", persistent & shock),
                               ("noshock", persistent & ~shock)):
                rows.append({**base, "book": book,
                             **g.stats(g.episodes(x, z, mask, h), rt["rt_cm2"])})
    res = pd.DataFrame(rows)
    piv = res.pivot_table(index=["signature", "h"], columns="book",
                          values=["n", "gross_med", "net_mean_1x", "abs_move_med"])
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    piv["incr_gross_vs_all"] = (piv["gross_med_shock"] - piv["gross_med_all"]).round(3)
    piv["incr_gross_vs_noshock"] = (piv["gross_med_shock"] - piv["gross_med_noshock"]).round(3)
    return res, piv.reset_index(), panels


def headline(piv):
    return {h: {
        "median_incr_vs_all": float(piv[piv["h"] == h]["incr_gross_vs_all"].median()),
        "median_incr_vs_noshock": float(piv[piv["h"] == h]["incr_gross_vs_noshock"].median()),
        "median_shock_net_1x": float(piv[piv["h"] == h]["net_mean_1x_shock"].median()),
        "n_positive": int((piv[piv["h"] == h]["incr_gross_vs_noshock"] > 0).sum()),
    } for h in HORIZONS}


# --- harness validation: count arm must reproduce the committed headline -----
res_c, piv_c, pan_c = run_arm(pkg_A, "count")
committed = json.loads((OUT / "f7_gate_verdict.json").read_text())["headline"]
hc = headline(piv_c)
ok = all(abs(hc[h][k] - float(committed[str(h)][k.replace("n_positive", "n_positive_incr")]))
         < 1e-9 for h in HORIZONS
         for k in ("median_incr_vs_all", "median_incr_vs_noshock",
                   "median_shock_net_1x", "n_positive"))
print(f"\nHARNESS VALIDATION: count arm reproduces committed headline exactly: {ok}")
print("  committed:", {h: committed[str(h)]["median_incr_vs_noshock"] for h in HORIZONS})
print("  mine     :", {h: hc[h]["median_incr_vs_noshock"] for h in HORIZONS})
if not ok:
    raise SystemExit("harness invalid")

# --- the three notional variants --------------------------------------------
out = {}
pivs, pans = {}, {}
for tag, pk in (("A_as_committed", pkg_A), ("B_sign_guarded", pkg_B), ("C_dropped", pkg_C)):
    r, p, pan = run_arm(pk, "notional")
    pivs[tag], pans[tag] = p, pan
    out[tag] = headline(p)
    print(f"\n=== NOTIONAL arm [{tag}] ===")
    for h in HORIZONS:
        print(f"  h={h:>2}  median incr vs noshock {out[tag][h]['median_incr_vs_noshock']:+.4f}bp"
              f"  vs all {out[tag][h]['median_incr_vs_all']:+.4f}bp"
              f"  positive {out[tag][h]['n_positive']}/10"
              f"  median shock net@1x {out[tag][h]['median_shock_net_1x']:+.4f}bp")

print("\n=== DIFF: does the sign guard / drop move ANY headline digit? ===")
for h in HORIZONS:
    for k in ("median_incr_vs_noshock", "median_incr_vs_all", "median_shock_net_1x", "n_positive"):
        a, b, c = out["A_as_committed"][h][k], out["B_sign_guarded"][h][k], out["C_dropped"][h][k]
        flag = "" if (a == b == c) else "   <<< MOVED"
        print(f"  h={h:>2} {k:<24} A={a!r:>22} B={b!r:>22} C={c!r:>22}{flag}")

print("\n=== full per-cell frame equality (all 10 sigs x 3 horizons, every column) ===")
for tag in ("B_sign_guarded", "C_dropped"):
    same = pivs["A_as_committed"].equals(pivs[tag])
    print(f"  A vs {tag}: identical = {same}")
    if not same:
        d = pivs["A_as_committed"].compare(pivs[tag])
        print(d.to_string())

print("\n=== shock-day set for 5-10 under each variant (did the flag on the bad day flip?) ===")
for tag in ("A_as_committed", "B_sign_guarded", "C_dropped"):
    sh = pans[tag]["5-10"]["shock"]
    fl = pans[tag]["5-10"]["flow"]
    val = fl.get(BAD_DATE, np.nan)
    print(f"  [{tag}] n_shock={int(sh.sum())}  flow on {BAD_DATE.date()} = {val:,.0f}  "
          f"shock_on_bad_day={bool(sh.get(BAD_DATE, False))}")
for tag in ("B_sign_guarded", "C_dropped"):
    a = pans["A_as_committed"]["5-10"]["shock"]
    b = pans[tag]["5-10"]["shock"]
    diff = a.index[(a != b)]
    print(f"  A vs {tag}: shock-flag differs on {len(diff)} days {list(diff.date)[:10]}")
