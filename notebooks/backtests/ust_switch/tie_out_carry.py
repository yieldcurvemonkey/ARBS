"""Tie the carry model out against JPM's published per-CUSIP ``3m Carry``.

The specialness tie-out (``build_jpm_repo_panel.py``) proved the *input* -- that
``GC_modal - issue_repo`` reproduces JPM's ``3m Repo Special`` to 0.037bp. This proves the
*arithmetic that consumes it*. A correct specialness fed into a wrong carry formula is
still a wrong backtest, and the two failures look identical from the outside -- which is
not hypothetical here: the first formula tried scored corr 0.158 against this control and
would have shipped without it.

Method
------
JPM's carry report gives, per CUSIP per day: ``YTM``, ``Mod Dur``, ``PVBP``,
``3m Repo Special`` and ``3m Carry`` (bp of yield). It does not give a price -- but PVBP
and modified duration determine one:

    PVBP ($ per $1mm per bp) = ModDur x DirtyPrice/100 x 1e6 x 1e-4 = ModDur x DirtyPrice

so ``DirtyPrice = PVBP / ModDur``. (Checked on the degenerate row: ModDur 0.01, PVBP 1.0
=> price 100.00.) That closes the system without needing the bond panel, which only covers
ranks 0-3 and would restrict the test to the securities the study already trades -- the
opposite of what a control should do. This runs across JPM's WHOLE universe, ~348 issues
a day, most of which the study never touches.

Carry, in yield bp over a 3-month horizon:

    carry_bp = (y - r) x (h/360) / (ModDur - h/365) x 100

with ``r = GC - specialness``, i.e. exactly the quantity the switch engine consumes. The
denominator is the duration at the HORIZON: the bond is a quarter shorter by the time the
carry has accrued, and using spot duration instead costs corr 0.861 -> 0.312.

JPM's ``3m Carry`` is exactly ``3m Fwd YTM - Spot YTM``, verified row-by-row against the
issue-specific report (-15.4 vs -15.5, -15.7 vs -15.6, -16.1 vs -16.0), so this is a
comparison of like with like rather than of two things that merely correlate.

What agreement would and would not prove
----------------------------------------
Matching to a bp or two says the sign convention, the day-count pair (ACT/365 coupon vs
ACT/360 repo) and the price-to-yield conversion are all right. It does NOT validate the
specialness itself -- that was the other tie-out -- and it does not validate the DV01
bridge that turns a per-leg carry into a spread bp, which has no published control and is
checked instead by the hand-reconciliation in ``reconcile_one_trade.py``.
"""

from __future__ import annotations

import glob
import os
import pathlib
import sys

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
JPM_ROOT = pathlib.Path(
    os.getenv("JPM_RESEARCH_DIR", r"C:/Users/chris/clee/project-oasis/private/jpm_research")
)
CARRY_DS = JPM_ROOT / "data" / "treasury_carry_roll_and_relative_value_report_ds"
OUT = HERE / "_data" / "carry_tieout.parquet"

HORIZON_DAYS = 91.3125  # a quarter of 365.25


def load_carry_reports() -> pd.DataFrame:
    files = sorted(glob.glob(str(CARRY_DS / "*.parquet")))
    frames = []
    for f in files:
        d = pd.read_parquet(f)
        need = {"CUSIP", "Cpn", "YTM", "Mod Dur", "PVBP", "3m Repo Special", "3m Carry"}
        if not need.issubset(d.columns):
            continue
        frames.append(
            pd.DataFrame(
                {
                    "date": pd.Timestamp(pathlib.Path(f).stem),
                    "cusip": d["CUSIP"],
                    "cpn": pd.to_numeric(d["Cpn"], errors="coerce"),
                    "ytm": pd.to_numeric(d["YTM"], errors="coerce"),
                    "mod_dur": pd.to_numeric(d["Mod Dur"], errors="coerce"),
                    "pvbp": pd.to_numeric(d["PVBP"], errors="coerce"),
                    "special_bp": pd.to_numeric(d["3m Repo Special"], errors="coerce"),
                    "jpm_carry_bp": pd.to_numeric(d["3m Carry"], errors="coerce"),
                    "yrs_to_mat": pd.to_numeric(d.get("Yrs to Mat"), errors="coerce"),
                }
            )
        )
    if not frames:
        raise FileNotFoundError(f"no carry parquets under {CARRY_DS}")
    return pd.concat(frames, ignore_index=True)


def attach_gc(df: pd.DataFrame) -> pd.DataFrame:
    """Day-level 3m GC from the issue-specific panel built by build_jpm_repo_panel.py."""
    panel = pd.read_parquet(HERE / "_data" / "jpm_issue_repo_panel.parquet")
    panel["date"] = pd.to_datetime(panel["date"])
    gc = panel.groupby("date")["gc_3m"].first().rename("gc_pct").reset_index()
    return df.merge(gc, on="date", how="left")


def compute(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["dirty_price"] = out["pvbp"] / out["mod_dur"].replace(0.0, np.nan)
    out["repo_pct"] = out["gc_pct"] - out["special_bp"] / 100.0

    # Carry in YIELD space: (y - r) * dt / D. NOT (coupon - financing)/D -- see the module
    # docstring in RVUtils/USTSwitch/carry.py. The cash form was tried first and scored
    # corr 0.158 here, because it is blind to pull-to-par on off-par coupons.
    #
    # The duration is the one at the HORIZON, not at spot. Using spot duration drops the
    # correlation from 0.861 to 0.312 -- by far the largest single term after the space
    # itself, because the bond is a quarter shorter by the time the carry has accrued.
    out["dur_horizon"] = out["mod_dur"] - HORIZON_DAYS / 365.0
    out["my_carry_bp"] = (
        (out["ytm"] - out["repo_pct"]) * 100.0 * (HORIZON_DAYS / 360.0)
        / out["dur_horizon"].where(out["dur_horizon"] > 0.05)
    )
    out["err_bp"] = out["my_carry_bp"] - out["jpm_carry_bp"]
    return out


def report(m: pd.DataFrame) -> None:
    # Very short bonds have a near-zero modified duration in the denominator, so a
    # rounding error in PVBP explodes. Excluded and counted rather than silently kept.
    ok = m[(m["mod_dur"] > 0.5) & m["jpm_carry_bp"].notna() & m["my_carry_bp"].notna()
           & (m["dirty_price"].between(50, 200))]
    print(f"rows total {len(m):,}  usable {len(ok):,} "
          f"(dropped {len(m) - len(ok):,}: ModDur<=0.25y, unusable price, or no published carry)")
    if ok.empty:
        return
    e = ok["err_bp"]
    print(f"days                  : {ok['date'].nunique()}  "
          f"{ok['date'].min().date()} .. {ok['date'].max().date()}")
    print(f"JPM carry mean        : {ok['jpm_carry_bp'].mean():+8.3f} bp")
    print(f"my  carry mean        : {ok['my_carry_bp'].mean():+8.3f} bp")
    print(f"mean error            : {e.mean():+8.3f} bp")
    print(f"median abs error      : {e.abs().median():8.3f} bp")
    print(f"p95 abs error         : {e.abs().quantile(0.95):8.3f} bp")
    print(f"corr                  : {ok['my_carry_bp'].corr(ok['jpm_carry_bp']):8.4f}")
    print(f"R^2 (regression)      : {ok['my_carry_bp'].corr(ok['jpm_carry_bp'])**2:8.4f}")

    print("\nby maturity bucket:")
    ok = ok.copy()
    ok["bucket"] = pd.cut(ok["yrs_to_mat"], [0, 2, 3, 5, 7, 10, 20, 40],
                          labels=["0-2", "2-3", "3-5", "5-7", "7-10", "10-20", "20-40"])
    g = ok.groupby("bucket", observed=True).agg(
        n=("err_bp", "size"), jpm=("jpm_carry_bp", "mean"), mine=("my_carry_bp", "mean"),
        mean_err=("err_bp", "mean"), mae=("err_bp", lambda x: x.abs().mean()),
        corr=("err_bp", lambda x: np.nan),
    )
    corrs = ok.groupby("bucket", observed=True).apply(
        lambda d: d["my_carry_bp"].corr(d["jpm_carry_bp"]), include_groups=False
    )
    g["corr"] = corrs
    print(g.round(3).to_string())

    print("\nSPECIAL issues only (the rows the switch actually pays for):")
    sp = ok[ok["special_bp"] > 0.5]
    if len(sp):
        print(f"  n={len(sp):,}  mean err {sp['err_bp'].mean():+.3f}  "
              f"mae {sp['err_bp'].abs().mean():.3f}  "
              f"corr {sp['my_carry_bp'].corr(sp['jpm_carry_bp']):.4f}")


def main() -> int:
    df = load_carry_reports()
    df = attach_gc(df)
    m = compute(df)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    m.to_parquet(OUT, index=False)
    print("=== CARRY TIE-OUT: my coupon-minus-financing vs JPM published '3m Carry' ===")
    report(m)
    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
