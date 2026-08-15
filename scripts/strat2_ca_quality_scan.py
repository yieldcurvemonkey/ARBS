"""Every pack-day 2019-2023, with the convexity adjustment taken apart.

    C:/Users/chris/anaconda3/envs/stir/python.exe scripts/strat2_ca_quality_scan.py [workers]

Answers one question -- *are we computing the SOFR pack convexity adjustment
correctly?* -- by never computing it only one way. For each (date, pack) the
scan prices the same window through four independent routes and writes all of
them, so the notebook can compare rather than trust:

``pack_rate_futures``     mean of ``100 - SR3 settle``, the observable
``pack_rate_synthetic``   mean of ``USD-SOFR-1D``'s own IMM x IMM forwards --
                          the ZERO-CONVEXITY CONTROL. Those forwards come off
                          the same discount curve the swap leg is priced on, so
                          substituting them must return ``CA ~ 0``. Whatever it
                          returns instead is our own convention error, measured
                          with no external reference.
``pack_rate_q12``         the same forwards off ``USD-SOFR-1D-Q12STIRT``, a
                          curve bootstrapped *from the futures* -- an
                          independent cross-source read on the settles.
``swap_rate_qq`` /        the matched-maturity 1y forward swap at Citi's stated
``swap_rate_annual``      quarterly/quarterly frequency and at the ``usd_irs``
                          spec default (annual). The difference is the
                          compounding bias test.

Also written per row, because the scan found that the first four correctness
tests are all blind to it: ``n_nodes_inside`` / ``segment_days`` /
``fwd_spread_bp``. A discount curve with no node inside the pack window carries
one constant interpolated forward across it, which makes ``CA_synthetic``
identically zero however wrong the swap leg is. The control has to be read
together with the curvature it was given to see.

Output: ``notebooks/data/convexity_rv/strat2_ca_quality.parquet``.

Date universe is ``strat2.local_cached_dates`` -- dates whose FULL 13-contract
SR3 strip is already in the local diskcache. Enumerating first is not an
optimisation: the SR3 store is demand-driven and a cold contract costs about a
minute, so building over ``bdate_range`` would be a multi-hour job that mostly
fails. Skips are counted by reason and written to a sidecar JSON, which makes
the effective window an observable instead of an assumption.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime as dt
import json
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

OUT = _REPO / "notebooks" / "data" / "convexity_rv"
PARQUET = OUT / "strat2_ca_quality.parquet"
SIDECAR = OUT / "strat2_ca_quality_skips.json"

#: The swap curve the adjustment is measured against, and the futures-bootstrapped
#: cross-check. The second lives on a different MDP source and is allowed to fail
#: per date -- it is a corroborating witness, not an input.
CURVE = "USD-SOFR-1D"
SWAP_SOURCE = "CITIVELO_EXCEL"
CURVE_Q12 = "USD-SOFR-1D-Q12STIRT"
Q12_SOURCE = "BARCHART_STIRF-RL"

#: Full-sample window. 2024+ is out of daily reach: the SR3 diskcache collapses
#: to 1-2 dates a year after 2023-09 for the deep contracts.
START = dt.date(2019, 1, 2)
END = dt.date(2023, 12, 31)

#: 13 contracts => pack windows 1..10 (Whites through the pack starting at the
#: 10th quarterly, ~2.5y out). Citi's SOFR table is windows 5..17; windows 11+
#: need 20 contracts and the deferred settles are not in the local store daily.
N_CONTRACTS = 13


def _worker_init() -> None:
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    import logging

    logging.disable(logging.WARNING)
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))


def _chunk(days) -> dict:
    """One chunk of dates -> rows + a skip tally. Runs in a worker process."""
    _worker_init()

    import RVUtils.ConvexityRV.ca_diagnostics as CAD
    import RVUtils.ConvexityRV.strat2_sofr_convexity as S2
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
    from RVUtils.ConvexityRV.curve_ops import matched_forward_swap_rate
    from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp
    from RVUtils.ConvexityRV.packs import quarterly_imm_sequence

    cfg = S2.Strat2Config(n_contracts=N_CONTRACTS, start=START, end=END)
    swaps = IRSwapsMDP(source=SWAP_SOURCE)
    q12s = IRSwapsMDP(source=Q12_SOURCE)
    futs = STIRFutureMDP(source=cfg.futures_source)

    rows = []
    skips = {"no_futures": 0, "curve_missing": 0, "curve_ref_mismatch": 0,
             "q12_missing": 0, "error": 0, "ok": 0}

    for d in days:
        try:
            seq = quarterly_imm_sequence(d, cfg.n_contracts)
            syms = [S2.futures_symbol(y, m, cfg.futures_root) for y, m in seq]
            snap = futs.get_data({"symbols": syms, "timestamp": d})
            prices = {}
            for (y, m), s in zip(seq, syms):
                v = snap.get(s)
                if not v:
                    continue
                try:
                    p = float(v[0].price())
                except Exception:                                  # noqa: BLE001
                    continue
                if np.isfinite(p):
                    prices[(y, m)] = p
            if len(prices) < cfg.n_contracts:
                skips["no_futures"] += 1
                continue

            try:
                pricer = swaps.get_pricer({"curve_name": CURVE, "timestamp": d,
                                           "offline": True})
            except Exception:                                      # noqa: BLE001
                skips["curve_missing"] += 1
                continue
            ref = pricer.reference_date()
            ref = ref.date() if hasattr(ref, "date") else ref
            if ref != d:
                # The store serves the previous close on a holiday. Marking a
                # stale curve against live settles manufactures a CA move.
                skips["curve_ref_mismatch"] += 1
                continue

            nodes = CAD.curve_nodes(pricer)
            fwd = CAD.imm_forward_map(pricer, seq)

            fwd_q12 = None
            try:
                pq = q12s.get_pricer({"curve_name": CURVE_Q12, "timestamp": d,
                                      "offline": True})
                rq = pq.reference_date()
                rq = rq.date() if hasattr(rq, "date") else rq
                if rq == d:
                    fwd_q12 = CAD.imm_forward_map(pq, seq)
                    q12_nodes = CAD.curve_nodes(pq)
                else:
                    skips["q12_missing"] += 1
            except Exception:                                      # noqa: BLE001
                skips["q12_missing"] += 1
            if fwd_q12 is None:
                q12_nodes = []

            for spec in S2.pack_windows(d, cfg):
                cts = spec.contracts
                pack_fut = float(np.mean([100.0 - prices[k] for k in cts]))
                syn_fwds = [fwd[k] for k in cts]
                pack_syn = float(np.mean(syn_fwds))
                s_qq = matched_forward_swap_rate(pricer, spec.swap_start, spec.swap_end)
                s_an = matched_forward_swap_rate(pricer, spec.swap_start, spec.swap_end,
                                                 frequency=None, leg2_frequency=None)
                ca_obs = (pack_fut - s_qq) * 100.0
                ca_syn = (pack_syn - s_qq) * 100.0
                ca_ann = (pack_fut - s_an) * 100.0
                t1s = list(spec.t1s)
                res = CAD.window_resolution(nodes, spec.swap_start, spec.swap_end)

                if fwd_q12 is not None:
                    q12_fwds = [fwd_q12[k] for k in cts]
                    pack_q12 = float(np.mean(q12_fwds))
                    q12_res = CAD.window_resolution(q12_nodes, spec.swap_start,
                                                    spec.swap_end)
                    n_q12_inside = q12_res["n_nodes_inside"]
                else:
                    pack_q12 = float("nan")
                    n_q12_inside = float("nan")

                rows.append({
                    "date": pd.Timestamp(d),
                    "rank": spec.rank,
                    "pack": spec.label,
                    "colour": spec.colour,
                    "swap_start": spec.swap_start,
                    "swap_end": spec.swap_end,
                    # --- the four independent reads of the same window
                    "pack_rate_futures": pack_fut,
                    "pack_rate_synthetic": pack_syn,
                    "pack_rate_q12": pack_q12,
                    "swap_rate_qq": s_qq,
                    "swap_rate_annual": s_an,
                    # --- the adjustment, decomposed
                    "ca_observed_bp": ca_obs,
                    "ca_synthetic_bp": ca_syn,
                    "ca_clean_bp": ca_obs - ca_syn,
                    "ca_annual_bp": ca_ann,
                    "ca_q12_bp": (pack_q12 - s_qq) * 100.0,
                    "annual_qq_gap_bp": (s_an - s_qq) * 100.0,
                    "futures_vs_q12_bp": (pack_fut - pack_q12) * 100.0,
                    # --- Ho-Lee inputs and inversions
                    "t1_first": t1s[0],
                    "t1_last": t1s[-1],
                    "t_mid": float(np.mean(t1s)),
                    "time_weight": spec.time_weight,
                    "implied_vol_bp": implied_vol_from_ca_bp(ca_obs, t1s),
                    "implied_vol_clean_bp": implied_vol_from_ca_bp(ca_obs - ca_syn, t1s),
                    "dsigma_dca": CAD.vol_sensitivity_bp_per_bp(ca_obs, t1s),
                    # --- how much the control was allowed to see, and what it
                    #     should return: the annuity-weighting term is a known
                    #     second-order effect, so predict it rather than
                    #     lumping it into "residual".
                    "fwd_spread_bp": CAD.control_power_bp(syn_fwds),
                    "fwd_slope_bp": (syn_fwds[-1] - syn_fwds[0]) * 100.0,
                    "ca_synthetic_pred_bp": CAD.annuity_weight_residual_bp(syn_fwds, s_qq),
                    "n_curve_nodes": res["n_nodes"],
                    "n_nodes_inside": res["n_nodes_inside"],
                    "segment_days": res["segment_days"],
                    "node_spans_window": res["spans_window"],
                    "n_q12_nodes_inside": n_q12_inside,
                })
            skips["ok"] += 1
        except Exception:                                          # noqa: BLE001
            skips["error"] += 1
            continue

    return {"rows": rows, "skips": skips}


def build(workers: int = 6) -> pd.DataFrame:
    import RVUtils.ConvexityRV.strat2_sofr_convexity as S2

    cfg = S2.Strat2Config(n_contracts=N_CONTRACTS, start=START, end=END)
    t0 = time.time()
    days = S2.local_cached_dates(cfg)
    print(f"date universe: {len(days)} cached full-strip dates "
          f"{days[0]}..{days[-1]} ({time.time() - t0:.0f}s)", flush=True)

    size = max(10, len(days) // (workers * 4))
    chunks = [days[i:i + size] for i in range(0, len(days), size)]
    print(f"scan: {len(chunks)} chunks x ~{size} dates, {workers} workers", flush=True)

    rows, skips = [], {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_chunk, c): k for k, c in enumerate(chunks)}
        done = 0
        for f in as_completed(futures):
            r = f.result()
            rows.extend(r["rows"])
            for k, v in r["skips"].items():
                skips[k] = skips.get(k, 0) + v
            done += 1
            print(f"  chunk {done}/{len(chunks)} "
                  f"({len(rows)} rows, {time.time() - t0:.0f}s)", flush=True)

    df = pd.DataFrame(rows).sort_values(["date", "rank"]).reset_index(drop=True)

    # Quality flags travel WITH the panel rather than being re-derived by every
    # consumer -- a filter that lives in one notebook is a filter the next
    # reader does not apply.
    import RVUtils.ConvexityRV.ca_diagnostics as CAD

    df = CAD.flag_quality(df, ca_col="ca_observed_bp", syn_col="ca_synthetic_bp",
                          vol_col="implied_vol_bp", t1_col="t1_first")
    #: the fifth flag, which flag_quality cannot know about: the swap leg is an
    #: interpolation across a node-free window, so CA_synthetic is zero by
    #: construction and the whole row is unverifiable.
    df["flag_no_control_power"] = df["fwd_spread_bp"] < 1.0
    df["survive"] = df["ok"] & ~df["flag_no_control_power"]

    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PARQUET)
    SIDECAR.write_text(json.dumps(
        {"skips": skips, "n_rows": int(len(df)),
         "n_dates": int(df["date"].nunique()) if len(df) else 0,
         "date_min": str(df["date"].min()) if len(df) else None,
         "date_max": str(df["date"].max()) if len(df) else None,
         "universe": len(days),
         "flags": {c: int(df[c].sum()) for c in df.columns
                   if c.startswith("flag_") or c in ("ok", "survive")}}, indent=2))
    print(f"\n{len(df)} rows x {df['date'].nunique()} dates -> {PARQUET} "
          f"({time.time() - t0:.0f}s)")
    print(f"skips: {skips}")
    return df


if __name__ == "__main__":
    build(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
