r"""Block-4 panel build: IMM-dated swap legs, long-end forwards, and ATMF vol.

Everything the CA-vs-fly-v2 work trades against, on ONE curve build per date.

Why IMM-dated legs and not constant-maturity forward starts (the block-3
convention): a CA structure label is CONSTANT RANK -- at each quarterly IMM
roll it switches contracts and its level jumps.  A constant-maturity forward
fly does not roll, so pairing the two leaves the CA's roll jump unhedged, which
is exactly the artifact block 3 caught ("CM labels book the IMM-roll jump").
An ``IMM_k`` leg rolls on the SAME date as the CA it is paired with, so the two
jumps are commensurate -- and a blackout that flattens the book across the roll
removes both at once.

Leg panel, not fly panel: every fly at every weighting is then arithmetic on
the legs, so a weighting choice is never baked into the data.  The two fly
columns the user's notebook printed are fetched as well, purely as a tie-out.

Usage
-----
    python _p2_build_panel.py                 # full 2021-01-04 .. 2026-08-21
    python _p2_build_panel.py 2026-07-01 2026-07-31   # timing probe

Output
------
    notebooks/data/convexity_rv/p2_legs.parquet     wide, date-indexed
    notebooks/data/convexity_rv/p2_legs_meta.json   query -> column ledger
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP  # noqa: E402
from Query.Unified.UnifiedQuery import UnifiedQuery  # noqa: E402
from Query.Unified.registry import UnifiedStructure, UnifiedValue  # noqa: E402
from TB.IRSwapsTB import IRSwapsTB  # noqa: E402
from TB.IRSwaptionsTB import IRSwaptionsTB  # noqa: E402
from TB.TimeseriesBuilder import TimeseriesBuilder  # noqa: E402

CURVE = "USD-SOFR-1D"
DATA = REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------
#: IMM ranks worth a leg.  1/5/9/13/17 are the FRONT contracts of the five pack
#: colours (WHITES..GOLDS occupy ranks 1-4, 5-8, 9-12, 13-16, 17-20); 4/8/12/16/20
#: are the scored outright ranks; 2 is in the user's own notebook.
IMM_RANKS = (1, 2, 4, 5, 8, 9, 12, 13, 16, 17, 20)

#: Swap tenors measured FROM the IMM start.
IMM_TENORS = ("1y", "2y", "3y", "5y", "7y", "10y", "20y", "30y")

#: Spot par legs, for the constant-maturity comparison arm.
SPOT_TENORS = ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y")

#: Long-end forwards.  The user's regression uses 10y10y/20y10y; 10y10y/15y10y
#: is the tighter sibling.  Legs are fetched so any pair/fly is arithmetic.
LONGEND_LEGS = ("5Yx5Y", "10Yx10Y", "15Yx10Y", "20Yx5Y", "20Yx10Y", "25Yx5Y",
                "10Yx20Y", "20Yx20Y")

#: ATMF normal vol -- the third price of the same volatility, and the regressor
#: that turns a fly level into a vega.
VOL_SHORTHANDS = ("1Yx1Y", "2Yx1Y", "3Yx1Y", "4Yx1Y", "5Yx1Y",
                  "1Yx2Y", "3Yx2Y", "5Yx5Y", "10Yx10Y", "10Yx20Y")

#: Fetched verbatim so the user's printed OLS can be tied out on our panel.
TIEOUT_FLIES = ("IMM_1x2y/IMM_1x5y/IMM_1x10y",
                "IMM_2x2y/IMM_2x5y/IMM_2x10y")
TIEOUT_CURVES = ("10y10y/20y10y", "10y10y/15y10y")


def build_queries() -> list[UnifiedQuery]:
    qs: list[UnifiedQuery] = []
    for k in IMM_RANKS:
        for t in IMM_TENORS:
            qs.append(UnifiedQuery(curve=CURVE, tenor=f"IMM_{k}x{t}",
                                   value=UnifiedValue.IRS_RATE))
    for t in SPOT_TENORS:
        qs.append(UnifiedQuery(curve=CURVE, tenor=t, value=UnifiedValue.IRS_RATE))
    for t in LONGEND_LEGS:
        qs.append(UnifiedQuery(curve=CURVE, tenor=t, value=UnifiedValue.IRS_RATE))
    for t in TIEOUT_FLIES + TIEOUT_CURVES:
        qs.append(UnifiedQuery(curve=CURVE, tenor=t, value=UnifiedValue.IRS_RATE))
    for sh in VOL_SHORTHANDS:
        qs.append(UnifiedQuery(curve=CURVE, selector={"shorthand": sh, "strike": "ATMF"},
                               structure=UnifiedStructure.IRSWAPTION_STRADDLE,
                               value=UnifiedValue.IRSWAPTION_NVOL))
    return qs


def main() -> None:
    if len(sys.argv) >= 3:
        start = dt.date.fromisoformat(sys.argv[1])
        end = dt.date.fromisoformat(sys.argv[2])
        out = DATA / f"p2_legs_probe_{start:%Y%m%d}_{end:%Y%m%d}.parquet"
    else:
        start, end = dt.date(2021, 1, 4), dt.date(2026, 8, 21)
        out = DATA / "p2_legs.parquet"

    curve_mdp = IRSwapsMDP(source="citivelo_excel_rl")
    vol_mdp = IRSwaptionMDP(source="CITIVELO-RL", curve_source="citivelo_excel_rl",
                            request_defaults={"verify": False})
    tb_irs = IRSwapsTB(curve_mdp, show_tqdm=False)
    tb_vol = IRSwaptionsTB(vol_mdp, show_tqdm=False)

    queries = build_queries()
    print(f"{len(queries)} queries  {start}..{end}  -> {out.name}")

    frames: list[pd.DataFrame] = []
    t0 = time.time()
    for y in range(start.year, end.year + 1):
        a = max(start, dt.date(y, 1, 1))
        b = min(end, dt.date(y, 12, 31))
        if a > b:
            continue
        t1 = time.time()
        df = TimeseriesBuilder().get_timeseries(
            start=a, end=b, queries=queries, n_jobs=12,
            routers={"IRS": tb_irs, "IRSWAPTION": tb_vol},
        )
        df.index = pd.to_datetime(df.index)
        frames.append(df)
        dens = float(df.notna().mean().mean())
        print(f"  {y}: {df.shape[0]} dates x {df.shape[1]} cols  "
              f"density {dens:.4f}  ({time.time()-t1:.0f}s)")

    panel = pd.concat(frames).sort_index()
    panel = panel[~panel.index.duplicated(keep="last")]
    panel.to_parquet(out)

    meta = {"queries": len(queries), "start": str(start), "end": str(end),
            "columns": list(map(str, panel.columns)),
            "imm_ranks": list(IMM_RANKS), "imm_tenors": list(IMM_TENORS),
            "spot_tenors": list(SPOT_TENORS), "longend_legs": list(LONGEND_LEGS),
            "vol_shorthands": list(VOL_SHORTHANDS),
            "elapsed_s": round(time.time() - t0, 1)}
    (out.with_suffix(".meta.json")).write_text(json.dumps(meta, indent=1))

    print(f"\nwrote {out}  {panel.shape}  "
          f"{panel.index.min().date()}..{panel.index.max().date()}")
    nn = panel.notna().sum().sort_values()
    print("thinnest 12 columns:")
    print(nn.head(12).to_string())
    print(f"total {time.time()-t0:.0f}s")
    tb_irs.close()


if __name__ == "__main__":
    main()
