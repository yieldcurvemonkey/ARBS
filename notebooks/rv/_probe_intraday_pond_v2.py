"""The intraday pond, with three defects from the first pass fixed.

**Defect 1 -- the front-slot filter was not front, and not comparable.**
``enumerate_structures`` sets ``cm_slot`` to the **belly** (``panel.py:118``), so
for spacing ``s`` it ranges ``1+s .. max_slot-s``. Filtering ``cm_slot <= 4``
therefore kept front legs 1-3 at 3m, 1-2 at 6m, only slot 1 at 9m, and NOTHING
at 12m -- a different slice per spacing, silently narrowing, and empty at the
widest. The front leg is ``cm_slot - spacing``, so that is what gets filtered.

**Defect 2 -- the panels cover different regimes.** The intraday panel starts
2021-01 (Barchart's 240-min retention); the EOD panel starts 2018-01. The
intraday window is dominated by the 2022-23 hiking cycle and excludes the quiet
2018-19 and ZIRP 2020 stretches, which is why every EOD-vs-intraday ratio came
out at a suspiciously constant 1.32. Everything comparative here is therefore
run on the COMMON window.

**Defect 3 -- the bounce correction assumed normality.** ``E|X| = 0.798*sd``
holds for a Gaussian; this data has 34% exactly-unchanged bars at the front slot
and fat tails, so the conversion inflated the corrected number ABOVE the raw one
-- the correction made the opportunity look bigger, which is the wrong
direction and the tell that it was wrong. Applied here as a scale factor on the
measured mean absolute move instead, which is distribution-free:

    E|move|_true = E|move|_obs * sqrt(max(var_obs - var_noise, 0) / var_obs)

with ``var_noise = 2*(roll/2)^2`` from Roll's effective spread. The observed
non-normality is reported alongside so the choice is visible rather than
implicit.

Run: conda run -n stir python notebooks/rv/_probe_intraday_pond_v2.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

pd.set_option("display.width", 260, "display.max_columns", 40)

from RVUtils.MeanRev.panel import add_strip_slots, enumerate_structures

INTRA = REPO / "notebooks" / "data" / "stir_intraday"
EOD = REPO / "notebooks" / "data" / "sfr_fly_meanrev"
FLY_COST_BP = 2.0
MAX_SLOT = 16
FRONT_LEG_MAX = 4
BARS_PER_DAY = 6
SPACINGS = ((1, "3m"), (2, "6m"), (3, "9m"), (4, "12m"))
HORIZONS = ((1, "4h"), (2, "8h"), (3, "12h"), (6, "1d"), (12, "2d"),
            (30, "5d"), (126, "21d"))


def wide_of(st, spacing, *, front_only):
    if front_only:
        st = st[st["cm_slot"] - spacing <= FRONT_LEG_MAX]
    return st.pivot_table(index="as_of", columns="key", values="value",
                          aggfunc="first").sort_index()


def roll_spread(w):
    """Roll's effective spread from the pooled lag-1 autocovariance of bar moves."""
    d = w.diff()
    a = d.stack(future_stack=True).rename("r")
    b = d.shift(1).stack(future_stack=True).rename("l")
    p = pd.concat([a, b], axis=1).dropna()
    if len(p) < 100:
        return 0.0
    cov = float(np.cov(p["r"], p["l"])[0, 1])
    return 2.0 * np.sqrt(-cov) if cov < 0 else 0.0


def main() -> int:
    panel = pd.read_parquet(INTRA / "contracts.parquet")
    panel["as_of"] = pd.to_datetime(panel["as_of"])
    slots = add_strip_slots(panel[~panel["accruing"]].copy())
    t0 = slots["as_of"].min()
    print(f"intraday panel starts {t0}", flush=True)

    # ------------------------------------------------------------------ fix 1
    print("\n" + "=" * 112)
    print("FIX 1 -- front-leg filter (cm_slot is the BELLY)")
    print("=" * 112, flush=True)
    intr = {}
    for sp, tag in SPACINGS:
        st = enumerate_structures(slots, spacing=sp, max_slot=MAX_SLOT)
        w_all = wide_of(st, sp, front_only=False)
        w_fr = wide_of(st, sp, front_only=True)
        intr[tag] = (w_all, w_fr)
        old = st[st["cm_slot"] <= 4]["key"].nunique()
        print(f"  {tag:>3}: belly slots {st['cm_slot'].min()}-{st['cm_slot'].max()}"
              f" | front legs 1-{FRONT_LEG_MAX} -> {w_fr.shape[1]:>4} keys"
              f"   (old cm_slot<=4 filter gave {old:>4})", flush=True)

    # ------------------------------------------------------------------ fix 2
    print("\n" + "=" * 112)
    print("FIX 2 -- EOD reconciliation on the COMMON window")
    print("=" * 112, flush=True)
    rows = []
    for sp, tag in SPACINGS:
        f = EOD / f"structures_{3*sp}m.parquet"
        if not f.exists():
            continue
        st = pd.read_parquet(f)
        st["as_of"] = pd.to_datetime(st["as_of"])
        w_full = st.pivot_table(index="as_of", columns="key", values="value",
                                aggfunc="first").sort_index()
        w_cut = w_full[w_full.index >= t0]
        wi = intr[tag][0]
        m_full = (w_full.shift(-21) - w_full).stack(future_stack=True).dropna()
        m_cut = (w_cut.shift(-21) - w_cut).stack(future_stack=True).dropna()
        mi = (wi.shift(-126) - wi).stack(future_stack=True).dropna()
        rows.append({
            "spacing": tag,
            "eod_2018on_h21": float(m_full.abs().mean()),
            "eod_2021on_h21": float(m_cut.abs().mean()),
            "intraday_h21": float(mi.abs().mean()),
            "ratio_vs_2018": float(mi.abs().mean()) / float(m_full.abs().mean()),
            "ratio_vs_2021": float(mi.abs().mean()) / float(m_cut.abs().mean()),
            "eod_sd_2021on": float(w_cut.stack(future_stack=True).std()),
            "intraday_sd": float(wi.stack(future_stack=True).std()),
        })
    rec = pd.DataFrame(rows)
    print(rec.round(3).to_string(index=False), flush=True)
    print("""
  ratio_vs_2021 near 1.0 confirms the panels are the same object and the earlier
  1.32 was the REGIME, not the data. If it is still off, the intraday panel is
  measuring something else and nothing downstream survives.""", flush=True)
    rec.to_csv(INTRA / "reconciliation_common_window.csv", index=False)

    # ------------------------------------------------------------------ fix 3
    print("\n" + "=" * 112)
    print("FIX 3 -- how non-normal is this? (why 0.798*sd is not usable)")
    print("=" * 112, flush=True)
    nn = []
    for sp, tag in SPACINGS:
        for scope, w in (("all", intr[tag][0]), ("front", intr[tag][1])):
            d = w.diff().stack(future_stack=True).dropna()
            nn.append({"spacing": tag, "scope": scope, "n": len(d),
                       "sd": float(d.std()),
                       "mean_abs": float(d.abs().mean()),
                       "mean_abs_over_sd": float(d.abs().mean() / d.std()),
                       "gaussian_would_be": 0.798,
                       "pct_exactly_zero": float((d.abs() < 1e-12).mean()),
                       "kurtosis": float(d.kurtosis())})
    nnd = pd.DataFrame(nn)
    print(nnd.round(3).to_string(index=False), flush=True)

    print("\n" + "=" * 112)
    print("THE POND -- bounce-corrected, front legs 1-4, common regime")
    print("=" * 112, flush=True)
    out = []
    for sp, tag in SPACINGS:
        for scope, w in (("all", intr[tag][0]), ("front", intr[tag][1])):
            roll = roll_spread(w)
            var_noise = 2.0 * (roll / 2.0) ** 2
            for h, lbl in HORIZONS:
                m = (w.shift(-h) - w).stack(future_stack=True).dropna()
                if len(m) < 200:
                    continue
                raw = float(m.abs().mean())
                var_obs = float(m.std()) ** 2
                shrink = np.sqrt(max(var_obs - var_noise, 0.0) / var_obs) if var_obs > 0 else 0.0
                out.append({"spacing": tag, "scope": scope, "horizon": lbl,
                            "n": len(m), "roll_bp": roll,
                            "absmove_raw": raw,
                            "absmove_debounced": raw * shrink,
                            "oracle_raw": raw - FLY_COST_BP,
                            "oracle_debounced": raw * shrink - FLY_COST_BP,
                            "p_beat_cost": float((m.abs() > FLY_COST_BP).mean())})
    ora = pd.DataFrame(out)
    for scope in ("all", "front"):
        sub = ora[ora["scope"] == scope]
        order = [l for _, l in HORIZONS if l in set(sub["horizon"])]
        print(f"\n  [{scope}]  ORACLE NET of {FLY_COST_BP}bp, bounce-corrected:")
        print(sub.pivot_table(index="horizon", columns="spacing",
                              values="oracle_debounced", aggfunc="first")
              .reindex(order)[[t for _, t in SPACINGS]].round(3).to_string())
    print("\n  Roll effective spread (bp):")
    print(ora.groupby(["spacing", "scope"])["roll_bp"].first().round(3).to_string())
    ora.to_csv(INTRA / "pond_v2.csv", index=False)

    print("\n" + "=" * 112)
    print("VERDICT ON THE INTRADAY HOLDING PERIOD")
    print("=" * 112, flush=True)
    sub = ora[ora["horizon"].isin(["4h", "8h", "12h"])]
    print(f"  best sub-daily oracle, raw             {sub['oracle_raw'].max():+.3f} bp")
    print(f"  best sub-daily oracle, bounce-corrected {sub['oracle_debounced'].max():+.3f} bp")
    b = sub.loc[sub["oracle_debounced"].idxmax()]
    print(f"    (at {b['spacing']} / {b['scope']} / {b['horizon']})")
    d1 = ora[(ora["horizon"] == "1d")]
    print(f"  best 1-day oracle, bounce-corrected     {d1['oracle_debounced'].max():+.3f} bp")
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
