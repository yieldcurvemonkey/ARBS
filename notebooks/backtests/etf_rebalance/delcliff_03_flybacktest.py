"""Step 3: the tradeable version. DV01-neutral butterfly, SHORT the crossing bond
(belly), LONG two neighbour wings, sized DV01-neutral. Entry before the nominal
crossing month-end, exit swept out to +120 business days given the step-1 finding that
the flow (whatever drives it) is not resolved within +/-60bd of the nominal date.

Direction: the event study (delcliff_02) found the belly's yield rises (cheapens)
relative to its local curve neighbourhood after crossing -- so SHORT belly / LONG wings
is the economically motivated side. The sign is left to fall out of the mechanical P&L
computation below, not asserted.

Wings are excluded if they are within 6 months of their OWN crossing, so a wing does not
carry the same event the belly is being traded on.
"""
from __future__ import annotations

import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

from RVUtils.ETFRebalance import bond_panel as BP
from RVUtils.ETFRebalance import costs as C

OUT = BP.panel_dir()

ENTRY_OFFSETS = [-40, -30, -20, -10, -5]
EXIT_OFFSETS = [0, 10, 20, 30, 45, 60, 90, 120]
WING_TTM_BAND = (10.0, 35.0)   # candidate universe for wings
OWN_EVENT_EXCLUDE_DAYS = 100   # calendar days; a wing within this of its own crossing is dropped


def main():
    panel = BP.load()
    panel = panel[~panel["yield_gate_fail"]].copy()
    panel_dates = np.array(sorted(panel["date"].unique()))
    idx_of = {d: i for i, d in enumerate(panel_dates)}

    del20 = pd.read_csv(OUT / "delcliff_deletion_calendar_20y.csv", parse_dates=["event_date"])
    del20 = del20[del20["usable_window"]].copy()
    own_events = del20.groupby("cusip")["event_date"].apply(list).to_dict()

    ytm = panel.pivot_table(index="date", columns="cusip", values="ytm").reindex(panel_dates)
    dur = panel.pivot_table(index="date", columns="cusip", values="mod_dur").reindex(panel_dates)
    ttm = panel.pivot_table(index="date", columns="cusip", values="ttm").reindex(panel_dates)
    sprd = panel.pivot_table(index="date", columns="cusip", values="spread_price_bp").reindex(panel_dates)

    cost_model = C.CostModel(basis="measured")

    def pick_wings(date_idx: int, belly: str):
        row_ttm = ttm.iloc[date_idx]
        row_dur = dur.iloc[date_idx]
        if belly not in row_ttm.index or not np.isfinite(row_ttm[belly]):
            return None
        belly_ttm = row_ttm[belly]
        cands = row_ttm[(row_ttm >= WING_TTM_BAND[0]) & (row_ttm <= WING_TTM_BAND[1])].dropna()
        cands = cands.drop(index=belly, errors="ignore")
        d = panel_dates[date_idx]
        good = []
        for c in cands.index:
            evs = own_events.get(c, [])
            if any(abs((pd.Timestamp(d) - e).days) <= OWN_EVENT_EXCLUDE_DAYS for e in evs):
                continue
            good.append(c)
        if len(good) < 2:
            return None
        db = row_dur.get(belly)
        if not np.isfinite(db):
            return None
        # Bracket the belly in DURATION, not ttm: coupon dispersion means the
        # ttm-nearest neighbour is not always the duration-nearest one, and a wing
        # picked on ttm alone can land on the wrong side of the belly's duration --
        # producing a NEGATIVE wing weight, i.e. a short wing masquerading as a long
        # one. Bracketing on duration guarantees w1, w2 in [0, 1] whenever both sides
        # exist.
        below = [c for c in good if np.isfinite(row_dur.get(c)) and row_dur[c] < db]
        above = [c for c in good if np.isfinite(row_dur.get(c)) and row_dur[c] > db]
        if not below or not above:
            return None
        w_lo = min(below, key=lambda c: db - row_dur[c])
        w_hi = min(above, key=lambda c: row_dur[c] - db)
        d1, d2 = row_dur.get(w_lo), row_dur.get(w_hi)
        if not (np.isfinite(d1) and np.isfinite(d2)) or d2 <= d1:
            return None
        w1 = (d2 - db) / (d2 - d1)
        w2 = (db - d1) / (d2 - d1)
        return w_lo, w_hi, w1, w2

    rows = []
    n_events = 0
    for r in del20.itertuples():
        ed = r.event_date
        later = panel_dates[panel_dates >= np.datetime64(ed)]
        if len(later) == 0:
            continue
        i0 = idx_of[later[0]]
        n_events += 1
        for e_off in ENTRY_OFFSETS:
            i_entry = i0 + e_off
            if i_entry < 0 or i_entry >= len(panel_dates):
                continue
            wings = pick_wings(i_entry, r.cusip)
            if wings is None:
                continue
            w_lo, w_hi, w1, w2 = wings
            y_belly_e = ytm.iloc[i_entry].get(r.cusip)
            y_lo_e = ytm.iloc[i_entry].get(w_lo)
            y_hi_e = ytm.iloc[i_entry].get(w_hi)
            if not all(np.isfinite(x) for x in (y_belly_e, y_lo_e, y_hi_e)):
                continue

            for x_off in EXIT_OFFSETS:
                i_exit = i0 + x_off
                if i_exit <= i_entry or i_exit >= len(panel_dates):
                    continue
                y_belly_x = ytm.iloc[i_exit].get(r.cusip)
                y_lo_x = ytm.iloc[i_exit].get(w_lo)
                y_hi_x = ytm.iloc[i_exit].get(w_hi)
                if not all(np.isfinite(x) for x in (y_belly_x, y_lo_x, y_hi_x)):
                    continue

                d_belly = (y_belly_x - y_belly_e) * 100.0
                d_lo = (y_lo_x - y_lo_e) * 100.0
                d_hi = (y_hi_x - y_hi_e) * 100.0
                gross_bp = d_belly - w1 * d_lo - w2 * d_hi   # short belly, long wings

                legs = pd.DataFrame({
                    "cusip": [r.cusip, w_lo, w_hi],
                    "date": [panel_dates[i_exit]] * 3,
                    "spread_price_bp": [sprd.iloc[i_exit].get(r.cusip),
                                        sprd.iloc[i_exit].get(w_lo),
                                        sprd.iloc[i_exit].get(w_hi)],
                    "mod_dur": [dur.iloc[i_exit].get(r.cusip), dur.iloc[i_exit].get(w_lo),
                               dur.iloc[i_exit].get(w_hi)],
                    "ttm": [ttm.iloc[i_exit].get(r.cusip), ttm.iloc[i_exit].get(w_lo),
                           ttm.iloc[i_exit].get(w_hi)],
                })
                weights = pd.Series([1.0, w1, w2], index=legs.index)
                cost_bp = float(cost_model.package_round_trip_yield_bp(legs, weights))

                rows.append({
                    "cusip": r.cusip, "event_date": ed, "entry_off": e_off, "exit_off": x_off,
                    "w_lo": w_lo, "w_hi": w_hi, "w1": w1, "w2": w2,
                    "gross_bp": gross_bp, "cost_bp": cost_bp, "net_bp": gross_bp - cost_bp,
                })

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "delcliff_fly_backtest_trades.csv", index=False)
    print(f"events: {n_events}, trades computed: {len(df)}", flush=True)

    grid = df.groupby(["entry_off", "exit_off"]).agg(
        n=("net_bp", "count"),
        gross_mean=("gross_bp", "mean"), gross_median=("gross_bp", "median"),
        cost_mean=("cost_bp", "mean"),
        net_mean=("net_bp", "mean"), net_median=("net_bp", "median"),
        hit_rate=("net_bp", lambda s: (s > 0).mean()),
    ).reset_index()
    grid["breakeven_mult"] = grid["gross_mean"] / grid["cost_mean"]
    grid.to_csv(OUT / "delcliff_fly_backtest_grid.csv", index=False)

    print(f"\ngrid cells evaluated: {len(grid)}", flush=True)
    print(grid.sort_values("net_mean", ascending=False).to_string(index=False), flush=True)

    print("\ngrid median net_bp across all cells:", grid["net_mean"].median(), flush=True)
    best = grid.sort_values("net_mean", ascending=False).iloc[0]
    print(f"\nbest cell: entry={best['entry_off']}bd exit={best['exit_off']}bd  "
          f"gross={best['gross_mean']:.3f}bp cost={best['cost_mean']:.3f}bp "
          f"net={best['net_mean']:.3f}bp hit={best['hit_rate']*100:.0f}% "
          f"breakeven_mult={best['breakeven_mult']:.2f} n={best['n']}", flush=True)


if __name__ == "__main__":
    main()
