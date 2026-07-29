"""Rolling-strip SFR option/futures panel builder for the SR3 RV lab.

Walks a *rolling live strip* (``resolve_strip_symbols(strip, as_of=d)`` per date)
so contracts are included exactly while they were listed, and writes three
panels per symbol under ``<out-dir>/parts`` (checkpointed — reruns skip warm
symbols):

``<sym>_quotes.parquet``
    as_of, symbol, right, strike_price, strike_rate, premium_bp, iv_bp,
    delta_abs, atm_offset_bps, oi, volume  — LISTED settle premiums, the object
    every signal and every P&L mark in the lab is computed on.
``<sym>_contracts.parquet``
    as_of, symbol, forward_rate/price, expiry_date, tte, SABR params, BL
    diagnostics (mean/median/mm_bp/fwd_resid_bp/pre_norm_mass/ghost_frac) and
    the quality flag.
``<sym>_cdf.parquet``
    as_of, symbol + the BL risk-neutral CDF resampled onto a fixed rate grid
    (float32) so downstream couplings never re-extract.

``--merge`` concatenates the parts into ``quotes.parquet`` / ``contracts.parquet``
/ ``cdf.parquet``.

Usage::

    conda run -n stir python notebooks/rv/build_sfr_rv_panels.py \
        --start 2024-07-01 --end 2026-07-27 --out-dir notebooks/data/sfr_rv_lab
"""
from __future__ import annotations

import argparse
import datetime
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from MDP.STIRFutures._sofr_option_contracts import sofr_option_last_trade_date
from RVUtils.ImpliedDistribution import SFRImpliedDistribution, resolve_strip_symbols

#: fixed rate grid (percent) the BL CDF is resampled onto
CDF_GRID = np.round(np.arange(0.0, 8.0 + 1e-9, 0.025), 4)
CDF_COLS = [f"q{v:.3f}" for v in CDF_GRID]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", type=datetime.date.fromisoformat, required=True)
    p.add_argument("--end", type=datetime.date.fromisoformat, required=True)
    p.add_argument("--strip", type=str, default="2y")
    p.add_argument("--symbols", type=str, default=None,
                   help="comma-separated override of the rolling-strip union")
    p.add_argument("--out-dir", type=Path, default=Path("notebooks/data/sfr_rv_lab"))
    p.add_argument("--source", type=str, default="BARCHART_STIRFO-QL")
    p.add_argument("--merge", action="store_true",
                   help="merge existing parts and exit")
    p.add_argument("--no-resume", action="store_true",
                   help="refetch symbols whose parts already exist")
    p.add_argument("--progress", type=Path, default=None)
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
def rolling_universe(strip: str, dates: List[datetime.date]) -> Dict[str, List[datetime.date]]:
    """{symbol: [dates it was in the live strip]} over the sample."""
    out: Dict[str, List[datetime.date]] = {}
    for d in dates:
        try:
            syms = resolve_strip_symbols(strip, as_of=d)
        except Exception:
            continue
        for s in syms:
            out.setdefault(s, []).append(d)
    return out


def tradeable_dates(symbol: str, dates: List[datetime.date]) -> List[datetime.date]:
    """Drop dates after the option's last trade date (expired-chain guard)."""
    try:
        ltd = sofr_option_last_trade_date(symbol)
    except Exception:
        ltd = None
    if ltd is None:
        return list(dates)
    return [d for d in dates if d <= ltd]


def fetch_smiles(mdp, symbol: str, dates: List[datetime.date]) -> Dict[datetime.date, object]:
    """Bulk smile fetch with the documented per-date fallback for sparse chains."""
    try:
        out = mdp.fetch_bulk_sabr_smile({
            "symbols": [symbol], "timestamps": list(dates),
            "strike_offsets_bps": "listed",
        })
        smiles = out.get(symbol, {}) or {}
        if smiles:
            return smiles
    except Exception as exc:
        print(f"    bulk failed ({type(exc).__name__}: {str(exc)[:90]}) -> per-date",
              flush=True)
    smiles = {}
    for d in dates:
        try:
            smiles[d] = mdp.fetch_sabr_smile({
                "symbol": symbol, "as_of": d, "strike_offsets_bps": "listed"})
        except Exception:
            continue
    return smiles


def _cdf_row(bl) -> Optional[np.ndarray]:
    grid = np.asarray(bl.strike_grid_rate, dtype=float)
    cdf = np.asarray(bl.rnd_cumulative, dtype=float)
    if grid.size < 4 or not np.all(np.diff(grid) > 0):
        return None
    return np.interp(CDF_GRID, grid, cdf, left=0.0, right=float(cdf[-1])).astype(np.float32)


def _moments(bl) -> Dict[str, float]:
    """mean/median/std/skew of the BL RND from its (grid, CDF) pair."""
    g = np.asarray(bl.strike_grid_rate, dtype=float)
    c = np.asarray(bl.rnd_cumulative, dtype=float)
    total = float(c[-1])
    if total <= 0:
        return {}
    trapezoid = getattr(np, "trapezoid", np.trapz)
    mean = float((g[-1] * c[-1] - trapezoid(c, g)) / total)
    med = float(np.interp(0.5 * total, c, g))
    pdf = np.diff(c) / np.diff(g)
    mid = 0.5 * (g[1:] + g[:-1])
    w = np.diff(c)
    w = w / w.sum() if w.sum() > 0 else w
    var = float(np.sum(w * (mid - mean) ** 2))
    sd = float(np.sqrt(var)) if var > 0 else np.nan
    skew = (float(np.sum(w * (mid - mean) ** 3) / sd ** 3)
            if sd and np.isfinite(sd) and sd > 0 else np.nan)
    mode = float(mid[int(np.argmax(pdf))]) if pdf.size else np.nan
    return {"mean_rate": mean, "median_rate": med, "mode_rate": mode,
            "std_rate": sd, "skew_rnd": skew}


def process_symbol(mdp, dist, symbol: str, dates: List[datetime.date],
                   parts: Path) -> Dict[str, int]:
    smiles = fetch_smiles(mdp, symbol, dates)
    q_rows, c_rows, cdf_rows, cdf_idx = [], [], [], []
    for d, smile in sorted(smiles.items()):
        try:
            pr = smile.params
        except Exception:
            continue
        oi_tot = 0.0
        n_pts = 0
        for p in smile.points:
            if p.market_price is None:
                continue
            q_rows.append({
                "as_of": pd.Timestamp(d), "symbol": symbol, "right": p.right,
                "strike_price": float(p.strike_price),
                "strike_rate": float(p.strike_rate),
                "premium_bp": float(p.market_price) * 100.0,
                "iv_bp": float(p.iv_normal_bps),
                "delta_abs": float(p.delta_abs),
                "atm_offset_bps": float(p.atm_offset_bps),
                "oi": float(p.open_interest or 0.0),
                "volume": float(p.volume or 0.0),
            })
            oi_tot += float(p.open_interest or 0.0)
            n_pts += 1
        row = {
            "as_of": pd.Timestamp(d), "symbol": symbol,
            "forward_rate": float(pr.forward_rate),
            "forward_price": float(pr.forward_price),
            "expiry_date": pd.Timestamp(pr.expiry_date),
            "tte": float(pr.time_to_expiry),
            "sabr_alpha": float(pr.alpha), "sabr_rho": float(pr.rho),
            "sabr_nu": float(pr.nu), "sabr_beta": float(pr.beta),
            "sabr_rmse": float(pr.calibration_rmse) if pr.calibration_rmse else np.nan,
            "n_quotes": n_pts, "oi_total": oi_tot,
        }
        try:
            snap = dist.extract(smile)
            bl = snap.bl_result
        except Exception:
            bl = None
        if bl is not None:
            row.update(_moments(bl))
            row["fwd_resid_bp"] = float(getattr(bl, "forward_residual_bp", np.nan) or np.nan)
            row["pre_norm_mass"] = float(getattr(bl, "pre_normalization_mass", np.nan) or np.nan)
            row["ghost_frac"] = float(getattr(bl, "ghost_mass_fraction", 0.0) or 0.0)
            row["n_warnings"] = len(getattr(bl, "warnings", ()) or ())
            arr = _cdf_row(bl)
            if arr is not None:
                cdf_rows.append(arr)
                cdf_idx.append((pd.Timestamp(d), symbol))
        if "mean_rate" in row:
            row["mm_bp"] = (row["mean_rate"] - row["median_rate"]) * 100.0
        c_rows.append(row)

    parts.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(q_rows).to_parquet(parts / f"{symbol}_quotes.parquet", index=False)
    pd.DataFrame(c_rows).to_parquet(parts / f"{symbol}_contracts.parquet", index=False)
    if cdf_rows:
        cdf = pd.DataFrame(np.vstack(cdf_rows), columns=CDF_COLS)
        cdf.insert(0, "symbol", [s for _, s in cdf_idx])
        cdf.insert(0, "as_of", [t for t, _ in cdf_idx])
        cdf.to_parquet(parts / f"{symbol}_cdf.parquet", index=False)
    else:
        pd.DataFrame(columns=["as_of", "symbol"] + CDF_COLS).to_parquet(
            parts / f"{symbol}_cdf.parquet", index=False)
    return {"dates": len(c_rows), "quotes": len(q_rows), "cdf": len(cdf_rows)}


def merge(out_dir: Path) -> None:
    parts = out_dir / "parts"
    for kind in ("quotes", "contracts", "cdf"):
        files = sorted(parts.glob(f"*_{kind}.parquet"))
        frames = [pd.read_parquet(f) for f in files]
        frames = [f for f in frames if not f.empty]
        if not frames:
            print(f"  {kind}: nothing to merge", flush=True)
            continue
        df = pd.concat(frames, ignore_index=True)
        sort_cols = ([c for c in ("symbol", "as_of", "right", "strike_price")
                      if c in df.columns])
        df = df.sort_values(sort_cols).reset_index(drop=True)
        df.to_parquet(out_dir / f"{kind}.parquet", index=False)
        print(f"  {kind}.parquet: {df.shape} from {len(files)} parts", flush=True)


def main(argv=None) -> int:
    a = parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    if a.merge:
        merge(a.out_dir)
        return 0

    dates = [d.date() for d in pd.bdate_range(a.start, a.end)]
    if a.symbols:
        universe = {s: dates for s in a.symbols.split(",")}
    else:
        universe = rolling_universe(a.strip, dates)
    # warm-first ordering: latest expiry last-traded contracts are already cached
    order = sorted(universe, key=lambda s: (sofr_option_last_trade_date(s)
                                            or datetime.date(1900, 1, 1)), reverse=True)
    prog = a.progress or (a.out_dir / "backfill_progress.txt")
    parts = a.out_dir / "parts"
    print(f"universe ({len(order)}): {order}", flush=True)
    print(f"{len(dates)} business days {dates[0]} .. {dates[-1]}", flush=True)

    mdp = STIRFutureOptionMDP(source=a.source)
    dist = SFRImpliedDistribution(anchor_wings=True)
    t_all = time.time()
    with open(prog, "a", encoding="utf-8") as fh:
        fh.write(f"=== start {datetime.datetime.now().isoformat()} "
                 f"{len(order)} symbols ===\n")
        fh.flush()
        for i, sym in enumerate(order, 1):
            done = all((parts / f"{sym}_{k}.parquet").exists()
                       for k in ("quotes", "contracts", "cdf"))
            if done and not a.no_resume:
                print(f"[{i}/{len(order)}] {sym}: cached, skip", flush=True)
                fh.write(f"{sym} SKIP cached\n")
                fh.flush()
                continue
            d_sym = tradeable_dates(sym, universe[sym])
            if not d_sym:
                fh.write(f"{sym} SKIP no tradeable dates\n")
                fh.flush()
                continue
            t0 = time.time()
            print(f"[{i}/{len(order)}] {sym}: {len(d_sym)} dates "
                  f"{d_sym[0]}..{d_sym[-1]}", flush=True)
            try:
                stats = process_symbol(mdp, dist, sym, d_sym, parts)
                msg = (f"{sym} OK dates={stats['dates']} quotes={stats['quotes']} "
                       f"cdf={stats['cdf']} {time.time() - t0:.0f}s")
            except Exception as exc:
                msg = f"{sym} FAIL {type(exc).__name__}: {str(exc)[:150]}"
                traceback.print_exc()
            print("  " + msg, flush=True)
            fh.write(msg + "\n")
            fh.flush()
        fh.write(f"=== done in {time.time() - t_all:.0f}s ===\n")
    print(f"\nall symbols in {time.time() - t_all:.0f}s; merging", flush=True)
    merge(a.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
