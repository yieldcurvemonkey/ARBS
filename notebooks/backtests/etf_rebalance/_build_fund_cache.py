"""Build the one cache the "what the fund actually does" figure family reads.

Everything here is DESCRIPTIVE: what TLT holds against what its index holds. No
``exec_lag`` is applied anywhere, because none of these figures is a tradeable signal --
they are a description of a portfolio, and lagging a description would misstate it.

Writes to ``_data/``:
  fundfig_active_TLT.parquet   per (date, cusip) active weight / ownership / ttm
  fundfig_ladder_TLT.parquet   per (date, bucket) fund vs index weight
  fundfig_flow_TLT.parquet     per date share count, flow flag, basket decomposition
"""
from __future__ import annotations

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


def main() -> None:
    t0 = time.time()
    panel = BP.load()
    floats = FP.load()
    panel = FP.asof_join(panel, floats)
    # ``benchmark_weights`` filters on ``priced``, which ``engine.prepare_universe``
    # sets and ``HP.build`` does not. Without this the index weights quietly include
    # bonds the panel could not price, and every active weight is measured against a
    # benchmark that is not the one the study used.
    panel["priced"] = panel["ytm"].notna() & ~panel["yield_gate_fail"].fillna(True)
    print(f"panel {len(panel):,} rows  {time.time()-t0:.1f}s")

    joined = HP.build(["TLT", "TLH"], panel=panel, floats=floats)
    print(f"joined {len(joined):,} rows  {time.time()-t0:.1f}s")

    # ``benchmark_weights`` returns no ``ttm``: ttm reaches the active frame from the
    # HOLDINGS side of the outer join only. So an index member the fund does NOT hold --
    # the single most underweight name on the board, and the row the outer join exists to
    # keep -- arrives with ttm = NaN, and every downstream step that keys on ttm
    # (``HP.ladder`` via ``bucket_index``; ``prepare_universe``'s band filter, where
    # ``between`` returns False on NaN) drops it again. Measured on TLT: 25,153 rows, a
    # MEDIAN of 10.0% of index weight and 8 bonds per date, up to 27.8% / 15 bonds.
    # Recovered here from the panel, which carries ttm for all 25,153 and agrees to
    # 0.0 wherever both exist.
    ttm_ref = panel[["date", "cusip", "ttm", "age", "rank"]].rename(
        columns={"ttm": "_ttm_p", "age": "_age_p", "rank": "_rank_p"})

    def _fill_ttm(act: pd.DataFrame) -> pd.DataFrame:
        n_before = int(act["ttm"].isna().sum())
        a = act.merge(ttm_ref, on=["date", "cusip"], how="left")
        for c, src in (("ttm", "_ttm_p"), ("age", "_age_p"), ("rank", "_rank_p")):
            if c in a.columns:
                a[c] = a[c].fillna(a[src])
        a["ttm_recovered"] = act["ttm"].isna().values & a["ttm"].notna().values
        print(f"    ttm NaN {n_before:,} -> {int(a['ttm'].isna().sum()):,} "
              f"({int(a['ttm_recovered'].sum()):,} recovered from the panel)")
        return a.drop(columns=["_ttm_p", "_age_p", "_rank_p"])

    for tkr in ("TLT", "TLH"):
        sp = spec(tkr)
        act = HP.with_active_weight(joined, panel, sp, outstanding="ex_soma",
                                    weight_basis="dv01")
        act = _fill_ttm(act)
        keep = ["date", "cusip", "ttm", "ttm_recovered", "par", "mv", "dv01", "w_f", "w_i", "active_w",
                "ownership", "held", "in_index", "free_float", "outstanding_amt",
                "soma_holdings", "shares_out", "maturity_date", "cpn", "age", "rank"]
        keep = [c for c in keep if c in act.columns]
        act[keep].to_parquet(os.path.join(DATA, f"fundfig_active_{tkr}.parquet"))
        lad = HP.ladder(act, sp, width_y=0.25, weight_basis="dv01")
        lad.to_parquet(os.path.join(DATA, f"fundfig_ladder_{tkr}.parquet"))
        print(f"{tkr}: active {len(act):,}  ladder {len(lad):,} "
              f"buckets {lad['bucket'].min()}..{lad['bucket'].max()}  {time.time()-t0:.1f}s")

    # ------------------------------------------------------------------ flow / basket
    h = HP.load_holdings(["TLT", "TLH"])
    # The raw tidy holdings, kept as a file because the shed-path and basket figures need
    # par per (ticker, date, cusip) without the panel join.
    h.to_parquet(os.path.join(DATA, "raw_holdings_TLT_TLH.parquet"))
    flow = HP.flag_flow_days(h, threshold=0.02)
    flow.to_parquet(os.path.join(DATA, "fundfig_flow_TLT_TLH.parquet"))
    print(f"flow {len(flow):,} rows; flow days "
          f"{flow.groupby('ticker')['is_flow_day'].sum().to_dict()}  {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
