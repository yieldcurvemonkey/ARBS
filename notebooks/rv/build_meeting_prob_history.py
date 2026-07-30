"""Daily ZQ-vs-SR3 meeting-probability history: ladder, tie-out, refit, channels.

Per (date, SR3 contract with >= 1 resolved meeting and a usable chain):
- the FedWatch ladder from cached ZQ settles (staleness-gated),
- the tie-out row (cross-contract base+spread constant test — the gate),
- the mantissa refit to listed OTM premiums + half-tick bootstrap sigmas,
- boundary digitals (the identified N-space CDF signal) and the channel class.

Writes monthly-checkpointed parts under ``--out-dir`` and merges:
``monitor.parquet`` (one row per date x contract), ``boundaries.parquet``
(one row per date x contract x boundary), ``tieout.parquet``.

Usage::

    conda run -n stir python notebooks/rv/build_meeting_prob_history.py \
        --start 2024-07-01 --end 2026-07-28 --out-dir notebooks/data/meeting_prob
"""
from __future__ import annotations

import argparse
import datetime
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from RVUtils.MeetingProb import (           # noqa: E402
    boundary_digitals, bootstrap_refit, channel_row, meeting_ladder,
    refit_lattice, select_quotes, split_meetings, zq_settle_panel,
)
from MDP.STIRFutures._sofr_option_contracts import (  # noqa: E402
    quarterly_reference_window,
)

#: the main tree holds the (gitignored) option panels; read-only
MAIN_DATA = Path("C:/Users/chris/clee/ARBS/notebooks/data/sfr_rv_lab")

_M = "FGHJKMNQUVXZ"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", type=datetime.date.fromisoformat, required=True)
    p.add_argument("--end", type=datetime.date.fromisoformat, required=True)
    p.add_argument("--out-dir", type=Path,
                   default=Path("notebooks/data/meeting_prob"))
    p.add_argument("--boot-n", type=int, default=25)
    p.add_argument("--min-oi", type=float, default=100.0)
    p.add_argument("--min-quotes", type=int, default=8)
    p.add_argument("--merge", action="store_true")
    return p.parse_args(argv)


def merge(out_dir: Path) -> None:
    parts = out_dir / "parts"
    for kind in ("monitor", "boundaries", "tieout"):
        files = sorted(parts.glob(f"{kind}_*.parquet"))
        frames = [pd.read_parquet(f) for f in files]
        frames = [f for f in frames if len(f)]
        if not frames:
            print(f"  {kind}: nothing to merge", flush=True)
            continue
        df = pd.concat(frames, ignore_index=True)
        df = df.sort_values([c for c in ("as_of", "symbol") if c in df.columns])
        df.to_parquet(out_dir / f"{kind}.parquet", index=False)
        print(f"  {kind}.parquet: {df.shape}", flush=True)


def main(argv=None) -> int:
    a = parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    if a.merge:
        merge(a.out_dir)
        return 0
    parts = a.out_dir / "parts"
    parts.mkdir(exist_ok=True)

    from SDRUtils.analytics.fomc import load_fomc_schedule
    fomc = load_fomc_schedule("USD-SOFR-1D")

    zq_syms = [f"ZQ{c}{y}" for y in (23, 24, 25, 26, 27) for c in _M]
    zq = zq_settle_panel(zq_syms)
    print(f"ZQ panel {zq.shape}: {zq.index.min().date()} -> {zq.index.max().date()}",
          flush=True)

    quotes = pd.read_parquet(MAIN_DATA / "quotes.parquet")
    quotes["as_of"] = pd.to_datetime(quotes["as_of"])
    contracts = pd.read_parquet(MAIN_DATA / "contracts.parquet")
    contracts["as_of"] = pd.to_datetime(contracts["as_of"])
    fwd = contracts.set_index(["as_of", "symbol"])["forward_rate"]

    dates = sorted(d for d in contracts["as_of"].unique()
                   if a.start <= pd.Timestamp(d).date() <= a.end)
    print(f"{len(dates)} panel dates in range", flush=True)

    qday = {k: v for k, v in quotes.groupby(["as_of", "symbol"], sort=False)}

    month_rows: dict = {}
    t_all = time.time()
    for di, ts in enumerate(dates):
        d = pd.Timestamp(ts).date()
        mkey = f"{d:%Y%m}"
        done_flag = parts / f"monitor_{mkey}.parquet"
        if done_flag.exists() and mkey not in month_rows:
            continue                        # month already checkpointed
        ladder = meeting_ladder(d, zq, fomc)
        if not ladder:
            continue
        bucket = month_rows.setdefault(mkey, {"monitor": [], "boundaries": [],
                                              "tieout": []})

        # --- tie-out rows (all non-accruing contracts) ---
        day_syms = contracts[contracts["as_of"] == pd.Timestamp(ts)]["symbol"]
        for sym in day_syms:
            try:
                S, E = quarterly_reference_window(sym)
            except Exception:
                continue
            if S <= d:
                continue
            total = (E - S).days
            disp = 0.0
            for m in ladder:
                if m.effective <= d or m.effective >= E:
                    continue
                w = 1.0 if m.effective <= S else (E - m.effective).days / total
                disp += m.jump_bp * w
            f = fwd.get((pd.Timestamp(ts), sym))
            if f is None or not np.isfinite(f):
                continue
            bucket["tieout"].append({
                "as_of": pd.Timestamp(ts), "symbol": sym,
                "sr3_fwd": float(f), "zq_disp_bp": disp,
                "base_plus_spread_bp": float(f) * 100 - disp,
                "any_stale": any(m.stale for m in ladder
                                 if d < m.effective < E),
            })

        # --- refit rows (contracts with resolved meetings + usable chain) ---
        for sym in day_syms:
            cm = split_meetings(d, sym, ladder)
            if cm is None or cm.n_resolved == 0:
                continue
            f = fwd.get((pd.Timestamp(ts), sym))
            if f is None or not np.isfinite(f):
                continue
            dq = qday.get((pd.Timestamp(ts), sym))
            if dq is None or dq.empty:
                continue
            sel = select_quotes(dq, float(f), min_oi=a.min_oi)
            if len(sel) < max(a.min_quotes, cm.n_resolved + 3):
                continue
            fit = refit_lattice(cm, float(f), sel)
            if fit is None:
                continue
            boot = bootstrap_refit(cm, float(f), sel, n=a.boot_n)
            # channel measurement is against the STRICT ZQ-null tree: baseline
            # smear = unresolved outcome std composed with a small spread/drift
            # allowance, never the fitted width (which would hide the premium)
            base_smear = float(np.sqrt(cm.unresolved_var_bp2 + 3.0 ** 2))
            bd = boundary_digitals(cm, float(f), dq, smear_bp=base_smear,
                                   tol=0.10)
            row = channel_row(cm, fit, boot, bd)
            row["forward_rate"] = float(f)
            row["days_to_expiry"] = (cm.expiry - d).days
            bucket["monitor"].append(row)
            if len(bd):
                b = bd.copy()
                b.insert(0, "as_of", pd.Timestamp(ts))
                b.insert(1, "symbol", sym)
                b["smear_bp"] = base_smear
                b["fit_smear_bp"] = fit.smear_bp
                b["saturated"] = fit.saturated
                bucket["boundaries"].append(b)

        # checkpoint at month end
        nxt = dates[di + 1] if di + 1 < len(dates) else None
        if nxt is None or f"{pd.Timestamp(nxt).date():%Y%m}" != mkey:
            for kind in ("monitor", "tieout"):
                rows = bucket[kind]
                pd.DataFrame(rows).to_parquet(parts / f"{kind}_{mkey}.parquet",
                                              index=False)
            bds = bucket["boundaries"]
            (pd.concat(bds, ignore_index=True) if bds else pd.DataFrame()
             ).to_parquet(parts / f"boundaries_{mkey}.parquet", index=False)
            print(f"[{di + 1}/{len(dates)}] {mkey}: "
                  f"{len(bucket['monitor'])} monitor rows, "
                  f"{len(bucket['tieout'])} tieout rows "
                  f"({time.time() - t_all:.0f}s)", flush=True)
            month_rows.pop(mkey)

    merge(a.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
