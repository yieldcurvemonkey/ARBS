"""Build the compact per-fund risk-ladder series the interactive explorer reads.

What this produces is DESCRIPTIVE, not a signal: for every fund, every date and every
constant-maturity 3-month bucket, what the fund holds against what its index holds. No
``exec_lag`` is applied, because lagging a description would misstate it -- the same
reasoning as ``_build_fund_cache.py``.

Four decisions here change what the reader sees, so they are recorded rather than left
in the code to be re-derived:

* **Weekly, last observation in each ISO week.** Daily would be ~2,500 columns per fund
  against roughly 500 pixels of heatmap, so the browser would downsample it anyway --
  but by dropping whatever fell on the wrong pixel, which silently hides month-end
  reconstitutions. Taking the last file of each week is a stated rule and keeps every
  month-end (the last week of a month always ends on or after it).
* **The z-score is per (fund, bucket) against that bucket's OWN history**, expanding and
  strictly backward-looking with a 52-week minimum. That is the quantity the original
  thesis was stated in -- "olds5 is underweight relative to where it has been" -- so the
  explorer has to show it. Backward-looking because a full-sample z would let the reader
  see a dislocation defined partly by data that had not happened yet.
* **Buckets count UP from the fund's deletion boundary**, per ``HP.bucket_index``, so
  bucket 0 is always the last three months before the index must sell, on every date and
  in every fund. That makes the six ladders comparable at the bottom edge, which is the
  only edge they share.
* **Index weights use publicly held outstanding (ex-SOMA)**, the ICE rule. The Fed holds
  a median 17.8% of an issue, so including SOMA would measure the fund against a
  benchmark no index provider uses and no fund tracks.

Emits ``_data/ladder_explorer.json``: quantised integers, nulls where a bucket had no
index weight on that date.
"""
from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                      "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                "..", "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.ETFHoldings.universe import spec  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "_data")

#: Coupon funds only. GOVZ is a STRIPS fund (``prices_from_fedinvest=False``) whose
#: legs the FedInvest panel does not price, so a ladder for it would be built on a
#: benchmark of whatever fraction happened to price -- worse than not showing it.
FUNDS = ["TLT", "TLH", "IEF", "IEI", "SHY", "GOVT"]

WIDTH_Y = 0.25
MIN_HIST_WEEKS = 52


def weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Last observation in each ISO week. See the module docstring for why weekly."""
    d = df.copy()
    d["_wk"] = d["date"].dt.to_period("W").dt.end_time.dt.normalize()
    last = d.groupby("_wk")["date"].transform("max")
    return d[d["date"].eq(last)].drop(columns="_wk")


def expanding_z(wide: pd.DataFrame) -> pd.DataFrame:
    """Backward-looking z of each column against its own past. NaN until MIN_HIST_WEEKS.

    ``shift(1)`` before the expanding moments on purpose: a z that includes today
    compares an observation with a mean it is itself inside, which shrinks every extreme
    exactly when the reader is looking for one.
    """
    prev = wide.shift(1)
    mu = prev.expanding(min_periods=MIN_HIST_WEEKS).mean()
    sd = prev.expanding(min_periods=MIN_HIST_WEEKS).std(ddof=0)
    return (wide - mu) / sd.replace(0.0, np.nan)


def q(series_2d: pd.DataFrame, scale: float) -> list:
    """Quantise to ints, keeping NaN as null so 'no index weight' stays distinguishable
    from 'zero index weight' -- they mean different things and one is a hole."""
    a = series_2d.to_numpy(dtype="float64")
    out = []
    for row in a:
        out.append([None if not np.isfinite(v) else int(round(v * scale)) for v in row])
    return out


def main() -> None:
    t0 = time.time()
    panel = BP.load()
    floats = FP.load()
    panel = FP.asof_join(panel, floats)
    # ``benchmark_weights`` filters on ``priced``; ``HP.build`` does not set it. Without
    # this the index includes bonds the panel could not price and every active weight is
    # measured against the wrong benchmark.
    panel["priced"] = panel["ytm"].notna() & ~panel["yield_gate_fail"].fillna(True)
    print(f"panel {len(panel):,} rows  {time.time() - t0:.1f}s", flush=True)

    joined_all = HP.build(FUNDS, panel=panel, floats=floats)
    print(f"joined {len(joined_all):,} rows  {time.time() - t0:.1f}s", flush=True)

    # ttm reaches the active frame from the HOLDINGS side of the outer join only, so an
    # index member the fund does NOT hold -- the most underweight name on the board, and
    # the row the outer join exists to keep -- arrives with ttm = NaN and is then dropped
    # by every step that keys on ttm. Recovered from the panel, which has it for all.
    ttm_ref = panel[["date", "cusip", "ttm"]].rename(columns={"ttm": "_ttm_panel"})

    out = {"generated": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
           "width_y": WIDTH_Y, "min_hist_weeks": MIN_HIST_WEEKS, "funds": {}}

    for tk in FUNDS:
        sp = spec(tk)
        jt = joined_all[joined_all["ticker"].eq(tk)]
        if jt.empty:
            print(f"{tk}: no rows, skipped", flush=True)
            continue

        entry = None
        # Both weighting bases, because the question was posed in terms of "DV01 or
        # notional weightings" and they are not the same ladder: DV01 share pushes weight
        # up the curve relative to market value, so a bucket can be overweight on one
        # basis and underweight on the other. Showing one basis alone would answer half
        # the question and look like it had answered all of it.
        for basis in ("dv01", "mv"):
            act = HP.with_active_weight(jt, panel, sp, outstanding="ex_soma",
                                        weight_basis=basis)
            act = act.merge(ttm_ref, on=["date", "cusip"], how="left")
            act["ttm"] = act["ttm"].fillna(act["_ttm_panel"])
            act = act.drop(columns="_ttm_panel")
            act = act[act["ttm"].notna()]

            # Clip to dates the fund actually has a holdings file for. The outer join in
            # ``with_active_weight`` is against the INDEX, which exists on every panel
            # date back to 2015-06-05 -- so without this the four funds whose scrape
            # starts in 2018 carry two and a half years of phantom history in which they
            # hold nothing and therefore read as 100% underweight in every bucket. That
            # is the most visually dramatic thing on the chart and it is an artefact of
            # the join, not a position. Measured: 586 weeks before this clip against 554
            # (TLT/TLH) and 452 (the rest) after.
            have = set(pd.to_datetime(jt["date"]).unique())
            act = act[act["date"].isin(have)]

            lad = weekly(HP.ladder(act, sp, width_y=WIDTH_Y))
            if lad.empty:
                print(f"{tk}/{basis}: empty ladder, skipped", flush=True)
                continue
            lad["bucket"] = lad["bucket"].astype("int64")

            if entry is None:
                # A bucket the index never carries weight in is not a rung of this
                # ladder; it is a maturity the Treasury does not have on issue inside
                # the fund's band. Fixed once, on the first basis, so both bases share
                # one axis and the heatmaps stay comparable when the reader toggles.
                keep = lad.groupby("bucket")["w_i"].max()
                buckets = sorted(int(b) for b in keep[keep.fillna(0) > 0].index)
                sub = lad[lad["bucket"].isin(buckets)]
                n_held = sub.pivot(index="date", columns="bucket",
                                   values="n_held").reindex(columns=buckets)
                ttm_mid = sub.pivot(index="date", columns="bucket",
                                    values="ttm_mid").reindex(columns=buckets)
                entry = {
                    "name": sp.name,
                    "band": [sp.band_low, None if sp.band_high is None
                             or sp.band_high > 1e6 else sp.band_high],
                    "dates": [d.strftime("%Y-%m-%d") for d in n_held.index],
                    "buckets": buckets,
                    # median ttm per bucket over the sample, so the rung axis can also
                    # be read in years
                    "bucket_ttm": [None if not np.isfinite(v) else round(float(v), 2)
                                   for v in ttm_mid.median(axis=0).to_numpy()],
                    "n_held": q(n_held, 1),
                    "bases": {},
                }

            sub = lad[lad["bucket"].isin(entry["buckets"])]
            w_f = sub.pivot(index="date", columns="bucket",
                            values="w_f").reindex(columns=entry["buckets"])
            w_i = sub.pivot(index="date", columns="bucket",
                            values="w_i").reindex(columns=entry["buckets"])
            # w_f is NaN where the fund holds nothing in the bucket, which is a real
            # zero -- it holds none of it. w_i NaN is a hole (no index weight) and must
            # stay NaN, so the subtraction propagates it.
            active = w_f.fillna(0.0) - w_i
            # What the ladder does NOT show, made explicit rather than dropped.
            # Buckets are kept only where the index carries weight, so any fund holding
            # outside the index band -- overwhelmingly a bond that has crossed the
            # deletion boundary and has not been sold yet -- falls off the axis. Index
            # weight sums to 100.0% by construction; fund weight does not, and the gap
            # ran from 0.4% (TLT, DV01) to 7.7% (TLH, market value). Silently dropping
            # that would make every active weight on the chart slightly too negative
            # with no way for the reader to see why, so it is published as a series.
            off_index = (1.0 - w_f.fillna(0.0).sum(axis=1)).clip(lower=0.0)
            entry["bases"][basis] = {
                "off_index_bp": [None if not np.isfinite(v) else int(round(v * 1e4 * 10))
                                 for v in off_index.to_numpy(dtype="float64")],
                "active_bp": q(active * 1e4, 10),   # 0.1bp units
                "w_f_bp": q(w_f * 1e4, 10),
                "w_i_bp": q(w_i * 1e4, 10),
                "z": q(expanding_z(active), 100),   # 0.01 z units
            }

        if entry is None:
            continue
        out["funds"][tk] = entry
        print(f"{tk}: {len(entry['dates'])} weeks x {len(entry['buckets'])} buckets, "
              f"{len(entry['bases'])} bases  {time.time() - t0:.1f}s", flush=True)

    path = os.path.join(DATA, "ladder_explorer.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"wrote {path}  {os.path.getsize(path) / 1e6:.2f} MB  {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
