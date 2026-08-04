"""Two tests the execution study needs before its numbers mean anything.

**TEST 1 -- is the execution-hour effect real, or 60 trades of noise?**
The unpaired comparison showed 0.88-1.83 bp/trade between the best and worst
execution hour. With ~65 trades per cell and a trade-level sd of order 10bp,
the standard error on a single cell is ~1.2bp -- so that spread is roughly one
standard error and proves nothing on its own.

But the comparison does not have to be unpaired. Every execution hour runs the
SAME structures, the SAME signal parameters and the SAME dates; only the
observation time differs. So the cells pair exactly, and a paired test on the
per-configuration differences removes almost all the variance that makes the
unpaired version useless. That is the test that decides whether execution
timing is worth anything.

**TEST 2 -- the mechanism check was swamped by drift.**
Conditional forward moves came out POSITIVE at both +2 sigma and -2 sigma, which
cannot both be reversion. The 2021-2026 sample has a large unconditional drift
in the fly level, and conditioning on an extreme does not remove it. The
reversion signal is the DIFFERENCE ``E[fwd | high] - E[fwd | low]`` -- negative
means reversion, positive means momentum -- and that is what gets reported here,
against the unconditional drift so the size of what was masking it is visible.

**TEST 3 (Study C) -- the FOMC bar.**
The whole kink thesis is about meetings, and the EOD lab could never see the
decision itself: it had one price per day, so a decision and the eight hours
around it were a single observation. The 12:00 CT bar spans 12:00-16:00 CT and
contains BOTH the 13:00 CT decision and the 14:00 CT settle. This measures what
the fly does in that bar versus an ordinary one, and whether it reverts after.

Run: conda run -n stir python notebooks/rv/_probe_intraday_paired_and_fomc.py
"""
import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

pd.set_option("display.width", 260, "display.max_columns", 40)

from RVUtils.MeanRev.meetings import fomc_decisions
from RVUtils.MeanRev.panel import add_strip_slots, enumerate_structures
from RVUtils.MeanRev.signals import zscore_signal

INTRA = REPO / "notebooks" / "data" / "stir_intraday"
MAX_SLOT, FRONT_LEG_MAX = 16, 4
SPACINGS = ((2, "6m"), (3, "9m"), (4, "12m"))
HOURS = (0, 4, 8, 12, 16, 20)


def nw_t(x, lags=5):
    """Newey-West t-stat of a mean, so overlapping cells are not over-trusted."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 5:
        return np.nan
    e = x - x.mean()
    g0 = float(e @ e / n)
    v = g0
    for L in range(1, min(lags, n - 1) + 1):
        g = float(e[L:] @ e[:-L] / n)
        v += 2.0 * (1.0 - L / (lags + 1.0)) * g
    return float(x.mean() / np.sqrt(max(v, 1e-18) / n))


def main() -> int:
    ex = pd.read_csv(INTRA / "execution_timing.csv")

    # ------------------------------------------------------------------ test 1
    print("=" * 112)
    print("TEST 1 -- EXECUTION HOUR, PAIRED BY CONFIGURATION")
    print("=" * 112, flush=True)
    key = ["spacing", "window", "entry_z"]
    wide = ex.pivot_table(index=key, columns="hour_ct", values="avg_net_bp")
    wide = wide.dropna()
    print(f"  {len(wide)} configurations present at all {wide.shape[1]} hours\n")
    base = 12          # the bar containing the 15:00 ET settle = the EOD control
    rows = []
    for h in wide.columns:
        if h == base:
            continue
        d = (wide[h] - wide[base]).to_numpy()
        rows.append({"hour_ct": h, "n_configs": len(d),
                     "mean_diff_bp": float(np.mean(d)),
                     "median_diff_bp": float(np.median(d)),
                     "pct_better": float(np.mean(d > 0)),
                     "t_paired": float(np.mean(d) / (np.std(d, ddof=1) / np.sqrt(len(d))))
                     if len(d) > 2 else np.nan,
                     "nw_t": nw_t(d)})
    pr = pd.DataFrame(rows)
    print("  each row: (that hour) MINUS (12:00 CT, the EOD-equivalent bar)")
    print(pr.round(3).to_string(index=False), flush=True)
    print("""
  A paired t of |t| < 2 means the hour is indistinguishable from executing at
  the settle. Note these configurations overlap heavily (same dates, nested
  windows), so even the paired t is optimistic -- treat it as an upper bound on
  the evidence.""", flush=True)
    pr.to_csv(INTRA / "execution_paired.csv", index=False)

    # ------------------------------------------------------------------ test 2
    panel = pd.read_parquet(INTRA / "contracts.parquet")
    panel["as_of"] = pd.to_datetime(panel["as_of"])
    panel = panel[~panel["accruing"]]

    print("\n" + "=" * 112)
    print("TEST 2 -- REVERSION vs DRIFT, de-meaned")
    print("=" * 112, flush=True)
    rows = []
    for hour in HOURS:
        d = panel[panel["bar_hour_ct"] == hour].copy()
        d["as_of"] = d["as_of"].dt.normalize()
        d = d.drop_duplicates(subset=["as_of", "code"], keep="last")
        slots = add_strip_slots(d)
        for sp, tag in SPACINGS:
            st = enumerate_structures(slots, spacing=sp, max_slot=MAX_SLOT)
            st = st[st["cm_slot"] - sp <= FRONT_LEG_MAX]
            lv = st.pivot_table(index="as_of", columns="key", values="value",
                                aggfunc="first").sort_index()
            if lv.shape[1] == 0:
                continue
            z = zscore_signal(lv, window=63).stack(future_stack=True)
            f = (lv.shift(-1) - lv).stack(future_stack=True)
            j = pd.concat([z.rename("z"), f.rename("f")], axis=1).dropna()
            hi, lo = j["z"] > 2.0, j["z"] < -2.0
            rows.append({
                "hour_ct": hour, "spacing": tag,
                "uncond_drift": float(j["f"].mean()),
                "fwd_hi": float(j.loc[hi, "f"].mean()),
                "fwd_lo": float(j.loc[lo, "f"].mean()),
                "hi_minus_lo": float(j.loc[hi, "f"].mean() - j.loc[lo, "f"].mean()),
                "n_hi": int(hi.sum()), "n_lo": int(lo.sum()),
            })
    dd = pd.DataFrame(rows)
    print(dd.round(4).to_string(index=False), flush=True)
    print("""
  hi_minus_lo NEGATIVE = reversion, POSITIVE = momentum. The unconditional drift
  column is what made the raw conditional means both positive and useless.""",
          flush=True)
    piv = dd.pivot_table(index="hour_ct", columns="spacing", values="hi_minus_lo")
    print("\n  hi_minus_lo by hour and spacing:")
    print(piv.round(3).to_string(), flush=True)
    dd.to_csv(INTRA / "reversion_demeaned.csv", index=False)

    # ------------------------------------------------------------------ test 3
    print("\n" + "=" * 112)
    print("TEST 3 (STUDY C) -- THE FOMC BAR, which the EOD lab could not see")
    print("=" * 112, flush=True)
    meets = set(fomc_decisions(datetime.date(2021, 1, 1), datetime.date(2026, 12, 31)))
    print(f"  {len(meets)} decisions in the intraday window", flush=True)
    rows = []
    for sp, tag in SPACINGS:
        slots_all = add_strip_slots(panel.copy())
        st = enumerate_structures(slots_all, spacing=sp, max_slot=MAX_SLOT)
        st = st[st["cm_slot"] - sp <= FRONT_LEG_MAX]
        lv = st.pivot_table(index="as_of", columns="key", values="value",
                            aggfunc="first").sort_index()
        mv = lv.diff()
        idx = mv.index
        is_dec_bar = np.array([(t.date() in meets) and t.hour == 12 for t in idx])
        is_next = np.roll(is_dec_bar, 1)
        is_next[0] = False
        ordinary = ~(is_dec_bar | is_next)
        st_dec = mv[is_dec_bar].stack(future_stack=True).dropna()
        st_nxt = mv[is_next].stack(future_stack=True).dropna()
        st_ord = mv[ordinary].stack(future_stack=True).dropna()
        # Does the decision-bar move REVERT in the very next bar? Pair each
        # decision bar with the bar that follows it, on the same key, so the
        # correlation is computed on matched observations rather than on two
        # separately-pooled samples.
        pos = {t: i for i, t in enumerate(idx)}
        dec_t = [t for t in idx[is_dec_bar] if pos[t] + 1 < len(idx)]
        nxt_t = [idx[pos[t] + 1] for t in dec_t]
        A = mv.loc[dec_t].reset_index(drop=True)
        B = mv.loc[nxt_t].reset_index(drop=True)
        pair = pd.concat([A.stack(future_stack=True).rename("dec"),
                          B.stack(future_stack=True).rename("nxt")],
                         axis=1).dropna()
        rev_corr = float(pair["dec"].corr(pair["nxt"])) if len(pair) > 30 else np.nan
        rows.append({
            "spacing": tag,
            "n_decision_bars": int(len(st_dec)),
            "decision_bar_abs_move": float(st_dec.abs().mean()),
            "ordinary_bar_abs_move": float(st_ord.abs().mean()),
            "ratio": float(st_dec.abs().mean() / st_ord.abs().mean()),
            "next_bar_abs_move": float(st_nxt.abs().mean()),
            "decision_bar_sd": float(st_dec.std()),
            "ordinary_bar_sd": float(st_ord.std()),
            "next_bar_corr": rev_corr,
            "n_pairs": int(len(pair)),
        })
    fo = pd.DataFrame(rows)
    print(fo.round(3).to_string(index=False), flush=True)
    print("""
  The 12:00 CT bar on a decision day contains the 13:00 CT announcement. If the
  ratio is near 1.0 the FOMC does not move the fly any more than an ordinary
  afternoon does -- which would be the intraday version of the EOD lab's finding
  that the meeting calendar explains 1-6% of a fly's variance.""", flush=True)
    fo.to_csv(INTRA / "fomc_bar.csv", index=False)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
