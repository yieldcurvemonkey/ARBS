"""Measure the borrowed grid's one forward-looking entry condition.

``fed_detachment_grid.run_cell`` reads the FORWARD return before deciding
whether to open::

    ret = r[i]
    if not np.isfinite(ret):
        i += 1
        continue

so whether a trade is taken at week ``i`` -- and the phase of every trade after
it, because the loop advances by one week instead of ``horizon`` -- depends on
whether a settle ``h`` weeks later turns out to exist. The loop guard
``while i + horizon < n`` already excludes the end-of-sample NaNs, so every NaN
it can actually hit is a data hole.

That is inherited rather than forked, and this module's own
``E.schedule_trades`` does NOT condition on it. This probe measures how big the
exposure is, splits the holes into the side that IS knowable at entry (no entry
settle) and the side that is not (no exit settle), and re-scores the grid with
only the structures that have zero unknowable holes -- which is the number a
reader needs before trusting a winner that happens to sit in an affected cell.

    <env>/python.exe notebooks/rv/_probe_expect_exit_holes.py
"""
from __future__ import annotations

import io
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(HERE), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_detachment_grid as GR  # noqa: E402
import fed_detachment_prices as PX  # noqa: E402
import fed_expected_sentiment as E  # noqa: E402
import fed_expected_sentiment_run as R  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)

cfg = E.PRIMARY
carrier = R.cost_carrier(cfg)

zc, _ = E.load_composite()
PX.seed_local_cache()
syms = PX.sr3_universe(pd.Timestamp("2018-05-07").date(),
                       pd.Timestamp("2026-08-24").date(), max_rank=4)
panel = PX.settle_panel(syms)
sessions = np.asarray(pd.DatetimeIndex(panel.index).values, dtype="datetime64[ns]")

bank = R.build_signal_bank(zc, cfg, readings=("level", "chg"), leads=E.LEADS_W,
                           horizons=E.HORIZONS_W)
support = R.common_support(bank)
support = support[(support >= pd.Timestamp("2018-05-07"))]
print(f"support: {len(support)} weeks {support.min().date()}..{support.max().date()}\n")

return_bank, diag = GR.build_return_bank(
    panel, support, carrier, horizons=E.HORIZONS_W,
    structures=R.SR3_STRUCTURES, entry_lag_sessions=cfg.entry_lag_sessions)

print("=" * 78)
print("1. where the return bank has holes, and which side they are on")
print("=" * 78)


def _fill(on, lag=1):
    cur = pd.Timestamp(on)
    for _ in range(lag):
        i = int(np.searchsorted(sessions, np.datetime64(cur), side="right"))
        if i >= len(sessions):
            return None
        cur = pd.Timestamp(sessions[i])
    return cur


rows = []
for name in R.SR3_STRUCTURES:
    ranks, weights, _n, _s = E.STRUCTURES[name]
    for h in E.HORIZONS_W:
        arr = return_bank[(name, int(h))]
        # only the weeks run_cell can actually reach
        reachable = np.arange(len(support) - int(h))
        holes = [i for i in reachable if not np.isfinite(arr[i])]
        entry_side = exit_side = expiry = other = 0
        for i in holes:
            e = _fill(support[i])
            x = _fill(support[i + int(h)])
            if e is None or x is None:
                other += 1
                continue
            sy = [PX.rank_symbol(e.date(), r) for r in ranks]
            exp = min(pd.Timestamp(PX.contract_window(t).end) for t in sy)
            if exp <= x:
                expiry += 1
                continue
            pe = E.D.structure_price(panel, sy, weights, e)
            pxx = E.D.structure_price(panel, sy, weights, x)
            if pe is None:
                entry_side += 1
            elif pxx is None:
                exit_side += 1
            else:
                other += 1
        rows.append({"structure": name, "horizon_w": int(h),
                     "reachable_weeks": len(reachable), "holes": len(holes),
                     "knowable_at_entry (no entry settle)": entry_side,
                     "NOT knowable (no exit settle)": exit_side,
                     "expiry guard": expiry, "other": other})
HOLES = pd.DataFrame(rows)
print(HOLES.to_string(index=False))

bad = HOLES.groupby("structure")["NOT knowable (no exit settle)"].sum()
print("\n  unknowable holes per structure, summed over horizons:")
print("   " + bad.to_string().replace("\n", "\n   "))
CLEAN = sorted(bad[bad == 0].index)
DIRTY = sorted(bad[bad > 0].index)
print(f"\n  CLEAN structures (zero exit-side holes): {CLEAN}")
print(f"  AFFECTED structures:                    {DIRTY}")

print("\n" + "=" * 78)
print("2. does it change the grid's answer?")
print("=" * 78)
keys_all = R.cell_keys(readings=("level", "chg"), leads=E.LEADS_W,
                       thresholds=E.THRESHOLDS, horizons=E.HORIZONS_W,
                       structures=R.SR3_STRUCTURES)
key_row, sig_keys = R.key_rows(keys_all, bank)
dmat = R.dmatrix(bank, sig_keys, support)
obs_all, best_all, per_all = GR.grid_statistic(dmat, keys_all, key_row,
                                               return_bank, carrier, min_trades=8)
k = keys_all[best_all]
print(f"  full grid ({len(keys_all)} cells): best {obs_all:.4f} at "
      f"{k[0]}/L{k[1]}/thr{k[2]}/h{k[3]}/{k[4]}")

if CLEAN:
    keys_clean = R.cell_keys(readings=("level", "chg"), leads=E.LEADS_W,
                             thresholds=E.THRESHOLDS, horizons=E.HORIZONS_W,
                             structures=CLEAN)
    kr_c, _ = R.key_rows(keys_clean, bank)
    obs_c, best_c, _ = GR.grid_statistic(dmat, keys_clean, kr_c, return_bank,
                                         carrier, min_trades=8)
    kc = keys_clean[best_c]
    print(f"  clean-only  ({len(keys_clean)} cells): best {obs_c:.4f} at "
          f"{kc[0]}/L{kc[1]}/thr{kc[2]}/h{kc[3]}/{kc[4]}")

    null_c = GR.rotation_null(dmat, keys_clean, kr_c, return_bank, carrier,
                              max_k=11, max_h=8, min_trades=8, draws=5000,
                              rng=cfg.rng(31))
    p_c = GR.rotation_pvalue(obs_c, null_c)
    print(f"  clean-only rotation null: median {null_c['q50']:.4f}  "
          f"q95 {null_c['q95']:.4f}  rotations {null_c['draws_used']}  "
          f"p = {p_c:.4f}")
    print(f"\n  VERDICT UNCHANGED: {p_c > 0.05 and obs_c < null_c['q50']}")
    print(f"  (best cell still below its own null median: {obs_c < null_c['q50']})")

print("\n" + "=" * 78)
print("3. the pre-registered cell is not affected")
print("=" * 78)
pr = HOLES[(HOLES["structure"] == cfg.structure) & (HOLES["horizon_w"] == cfg.horizon_w)]
print(pr.to_string(index=False))
print(f"\n  and it is priced by E.schedule_trades / E.price_trades, which do NOT")
print(f"  condition entry on the forward return at all: schedule_trades reads only")
print(f"  the signal, and price_trades drops an unpriceable trade AFTER the fact.")
