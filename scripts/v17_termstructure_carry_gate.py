"""H17 gate — ATM vol term-structure roll-down carry (pre-registered H-V-17).

The house rule is oracle/pond gate FIRST. For a CARRY trade there is nothing to
take an oracle over: the harvest is not a forecast, it is what the surface pays
for holding. So this measures the REALIZED gross of the pre-registered rule
directly — which is a stricter gate than an oracle, because it needs no
"historical harvest is 10-30% of oracle" haircut afterwards.

Per (tail, adjacent expiry pair, horizon h), over NON-OVERLAPPING cycles:

    direction (day t only):  slide_i = v_t(E_i - h) - v_t(E_i)
                             +1 vega on the greater-slide leg, -1 on the other
    realized:  [v_{t+h}(E_A - h) - v_t(E_A)] - [v_{t+h}(E_B - h) - v_t(E_B)]

in ANNUAL VOL BP per unit vega — the unit CM-1's half-spreads are already quoted
in, so gross and cost are directly comparable with no conversion to get wrong.

Off-grid expiries (E - h) are total-variance interpolated: w(T) = v(T)^2 * T
linear in T, v = sqrt(w/T). Panel arithmetic, no planted-value test, stated
(ledger L-0042c).

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/v17_termstructure_carry_gate.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"

#: pre-registered TRADED universe (H-V-17): CM-1-printed cells only, 1M excluded
#: because it is CM-1's worst cell (0.71 annual bp).
#:
#: The MARKING grid is deliberately wider. An aged 3M option is a 2M option at
#: exit, and it has to be marked on the quote that exists for a 2M option — that
#: is a mark, not a trade, so 1M/2M belong on the grid while staying out of the
#: traded universe. The self-test caught this before any number existed: with the
#: grid restricted to the traded set, every aged front leg fell below the minimum
#: quoted expiry, `interp_vol` returned NaN, and every cycle was silently skipped.
TRADED_EXPIRIES = ["3M", "6M", "1Y", "2Y"]
MARK_EXPIRIES = ["1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y"]
#: A horizon cannot age the front leg past the shortest quoted expiry.
MIN_AGED_YRS = 1 / 12
PAIRS = [("3M", "6M"), ("6M", "1Y"), ("1Y", "2Y")]
TAILS = ["5Y", "10Y", "30Y"]
HORIZONS = [21, 63]

#: CM-1 measured near-close ATM straddle half-spreads, ANNUAL vol bp (L-0022).
#: Upper bounds, as recorded.
CM1_HALF = {"1M": 0.71, "2M": 0.38, "3M": 0.38, "6M": 0.25, "9M": 0.21,
            "1Y": 0.21, "18M": 0.23, "2Y": 0.23, "3Y": 0.17, "4Y": 0.17,
            "5Y": 0.17}
EXP_YRS = {"1M": 1 / 12, "2M": 2 / 12, "3M": 0.25, "6M": 0.5, "9M": 0.75,
           "1Y": 1.0, "18M": 1.5, "2Y": 2.0, "3Y": 3.0, "4Y": 4.0, "5Y": 5.0}
BD_YEAR = 252.0


def atm_panel(tail: str) -> pd.DataFrame:
    """date x expiry_yrs ATM vol (annual bp) for one tail, ascending expiry."""
    v = pd.read_parquet(DATA / "vol_panel.parquet",
                        columns=["date", "expiry", "tenor", "offset_bp", "vol_bp"])
    v = v[(v["tenor"] == tail) & (v["offset_bp"] == 0.0)
          & (v["expiry"].isin(MARK_EXPIRIES))]
    p = v.pivot_table(index="date", columns="expiry", values="vol_bp", aggfunc="last")
    p.index = pd.to_datetime(p.index)
    p = p.rename(columns=EXP_YRS)
    return p[sorted(p.columns)].sort_index()


def interp_vol(row: pd.Series, t_yrs: float) -> float:
    """Total-variance interpolation in expiry. NaN outside the quoted range."""
    s = row.dropna()
    if len(s) < 2 or t_yrs <= 0:
        return np.nan
    ts = s.index.to_numpy(dtype=float)
    if t_yrs < ts.min() or t_yrs > ts.max():
        return np.nan
    w = (s.to_numpy(dtype=float) ** 2) * ts
    return float(np.sqrt(np.interp(t_yrs, ts, w) / t_yrs))


def run_cell(panel: pd.DataFrame, e1: str, e2: str, h: int, phase: int = 0) -> dict:
    """Non-overlapping cycles of the pre-registered rule for one cell.

    ``phase`` is the offset at which the non-overlapping grid starts. **It is
    not a free parameter and must not be chosen.** A checker killed this gate's
    first published numbers for quoting phase 0 alone: the registration says
    "NON-OVERLAPPING cycles only" and pins no phase, so all ``h`` phases are
    equally the pre-registered statistic. Within-cell dispersion across phases
    is large (sd 0.233 at h=21, 0.640 at h=63), and at h=63 three or four of the
    63 phases cross the gate bar in four cells — i.e. the published OUTCOME was
    not invariant to an unregistered construction choice. ``run_cell_ensemble``
    below is the statistic of record; this function exists to serve it.
    """
    dates = list(panel.index)
    t1, t2 = EXP_YRS[e1], EXP_YRS[e2]
    dt = h / BD_YEAR
    if t1 - dt < MIN_AGED_YRS:
        return {"n_cycles": 0, "skipped": "horizon ages the front leg off the quoted grid"}
    gross, dirs, expected = [], [], []
    i = phase
    while i + h < len(dates):
        d0, d1 = dates[i], dates[i + h]
        r0, r1 = panel.loc[d0], panel.loc[d1]
        v0_1, v0_2 = interp_vol(r0, t1), interp_vol(r0, t2)
        # the aged marks, on the EXIT day's own surface
        v1_1, v1_2 = interp_vol(r1, t1 - dt), interp_vol(r1, t2 - dt)
        # the entry-day slide estimate that picks the direction (day-t data only)
        s1 = interp_vol(r0, t1 - dt) - v0_1
        s2 = interp_vol(r0, t2 - dt) - v0_2
        if not all(np.isfinite(x) for x in (v0_1, v0_2, v1_1, v1_2, s1, s2)):
            i += 1
            continue
        # +1 vega on the greater-slide leg, -1 on the other
        long_back = s2 > s1
        pnl_back = v1_2 - v0_2
        pnl_front = v1_1 - v0_1
        gross.append((pnl_back - pnl_front) if long_back else (pnl_front - pnl_back))
        dirs.append(1 if long_back else -1)
        # what the FROZEN surface would have paid, from day-t data only. The gap
        # to `gross` is what the market took back.
        expected.append(abs(s2 - s1))
        i += h
    if len(gross) < 5:
        return {"n_cycles": len(gross)}
    g, ex = np.array(gross), np.array(expected)
    rt = 2.0 * (CM1_HALF[e1] + CM1_HALF[e2])
    return {
        "n_cycles": int(len(g)),
        "median_expected_carry_bp": float(np.median(ex)),
        "expected_carry_over_rt": float(np.median(ex) / (2.0 * (CM1_HALF[e1] + CM1_HALF[e2]))),
        "median_gross_bp": float(np.median(g)),
        "mean_gross_bp": float(g.mean()),
        "sd_gross_bp": float(g.std(ddof=1)),
        "per_cycle_sharpe": float(g.mean() / g.std(ddof=1)) if g.std(ddof=1) else np.nan,
        "skew": float(pd.Series(g).skew()),
        "worst_cycle_bp": float(g.min()),
        "rt_bp": rt,
        "median_over_rt": float(np.median(g) / rt),
        "mean_over_rt": float(g.mean() / rt),
        "frac_clearing_rt": float((g > rt).mean()),
        "frac_long_back": float(np.mean(np.array(dirs) > 0)),
        "net_median_bp": float(np.median(g) - rt),
    }


def run_cell_ensemble(panel: pd.DataFrame, e1: str, e2: str, h: int) -> dict:
    """The construction-invariant statistic: median over ALL h cycle phases.

    Reports the phase dispersion alongside, because a point estimate whose
    phase sd is 0.640x RT carries almost no information and must not be quoted
    to three decimals as though it did.
    """
    runs = [run_cell(panel, e1, e2, h, phase=p) for p in range(h)]
    ok = [r for r in runs if r.get("n_cycles", 0) >= 5]
    if not ok:
        return runs[0] if runs else {"n_cycles": 0}
    med = np.array([r["median_over_rt"] for r in ok])
    exp = np.array([r["expected_carry_over_rt"] for r in ok])
    base = dict(ok[0])
    base.update({
        "n_phases": len(ok),
        "phase_median_over_rt": float(np.median(med)),
        "phase_sd_over_rt": float(med.std(ddof=1)) if len(med) > 1 else 0.0,
        "phase_min_over_rt": float(med.min()),
        "phase_max_over_rt": float(med.max()),
        "n_phases_clearing_rt": int((med > 1.0).mean() * len(med)),
        "phase_median_expected_carry_over_rt": float(np.median(exp)),
        "phase_sd_expected_carry_over_rt": float(exp.std(ddof=1)) if len(exp) > 1 else 0.0,
    })
    return base


def self_test() -> None:
    """Planted-value test — the thing L-0042(c) records the F-gates as lacking.

    Two synthetic surfaces whose answer is known before the code runs:

    * **flat and frozen** — a term structure that is constant in expiry and never
      moves has no slide anywhere, so every cycle must return EXACTLY 0.0. A gate
      that manufactures carry out of interpolation would fail here.
    * **sloped and frozen** — total variance linear in T with a known slope, held
      frozen. Then the realized P&L is exactly the difference of the two legs'
      roll-downs, which is computed here independently of ``run_cell`` and
      compared. This is the number the whole gate is built to measure, so if the
      two disagree the gate is measuring something else.
    """
    dates = pd.bdate_range("2020-01-01", periods=400)
    ts = np.array([EXP_YRS[e] for e in MARK_EXPIRIES])

    flat = pd.DataFrame(np.full((len(dates), len(ts)), 80.0),
                        index=dates, columns=ts)
    r = run_cell(flat, "3M", "1Y", 21)
    assert abs(r["mean_gross_bp"]) < 1e-9 and abs(r["median_gross_bp"]) < 1e-9, \
        f"flat frozen surface must pay exactly zero, got {r['mean_gross_bp']}"

    # total variance w(T) = a + b*T  ->  v(T) = sqrt((a + b*T)/T), frozen in time
    a, b = 400.0, 6400.0
    curve = np.sqrt((a + b * ts) / ts)
    sloped = pd.DataFrame(np.tile(curve, (len(dates), 1)), index=dates, columns=ts)
    h, dt = 21, 21 / BD_YEAR
    t1, t2 = EXP_YRS["3M"], EXP_YRS["1Y"]
    v = lambda T: float(np.sqrt((a + b * T) / T))          # noqa: E731
    slide1, slide2 = v(t1 - dt) - v(t1), v(t2 - dt) - v(t2)
    expected = (slide2 - slide1) if slide2 > slide1 else (slide1 - slide2)
    r = run_cell(sloped, "3M", "1Y", h)
    assert abs(r["mean_gross_bp"] - expected) < 1e-6, \
        f"frozen sloped surface: expected {expected:+.6f}, got {r['mean_gross_bp']:+.6f}"
    assert r["sd_gross_bp"] < 1e-9, "a frozen surface cannot produce dispersion"
    print(f"SELF-TEST 1/2 PASS: flat surface pays 0.000; frozen sloped surface pays "
          f"{expected:+.4f} bp/cycle and the gate agrees to 1e-6 "
          f"(slides {slide1:+.4f} / {slide2:+.4f})")

    # ---- the test the first version was MISSING -------------------------
    # Both surfaces above are FROZEN, so the exit-day row equals the entry-day
    # row and the test is structurally blind to reading the aged marks off the
    # WRONG DAY. A checker demonstrated this with a surgical mutant (aged marks
    # read off the entry day): it returns byte-identical +4.145403 on BOTH
    # frozen surfaces. A MOVING surface is required to pin the time indexing.
    #
    # Total variance stays linear in T at every t (so the interpolation remains
    # exact and the closed form below is not an approximation); only the LEVEL
    # moves, by a factor f(t) applied to vol.
    def f(t: int) -> float:
        return 1.0 + 0.25 * np.sin(t / 13.0)

    moving = pd.DataFrame(
        np.outer([f(t) for t in range(len(dates))], curve), index=dates, columns=ts)
    for pair, hh in (("3M", 21), ("6M", 63), ("1Y", 21)):
        e_lo, e_hi = ("3M", "6M") if pair == "3M" else (
            ("6M", "1Y") if pair == "6M" else ("1Y", "2Y"))
        tl, th = EXP_YRS[e_lo], EXP_YRS[e_hi]
        d = hh / BD_YEAR
        want = []
        i = 0
        while i + hh < len(dates):
            f0, f1 = f(i), f(i + hh)
            # slides are frozen-surface (day-i) quantities -> direction is
            # unchanged by a pure level factor, so it is the frozen sign
            s_lo = f0 * (v(tl - d) - v(tl))
            s_hi = f0 * (v(th - d) - v(th))
            pnl_hi = f1 * v(th - d) - f0 * v(th)
            pnl_lo = f1 * v(tl - d) - f0 * v(tl)
            want.append((pnl_hi - pnl_lo) if s_hi > s_lo else (pnl_lo - pnl_hi))
            i += hh
        got = run_cell(moving, e_lo, e_hi, hh)
        err = abs(got["mean_gross_bp"] - float(np.mean(want)))
        assert err < 1e-9, (
            f"moving surface {e_lo}-{e_hi} h={hh}: closed form "
            f"{np.mean(want):+.8f} vs gate {got['mean_gross_bp']:+.8f} (err {err:.2e})")
    print("SELF-TEST 2/2 PASS: on a MOVING surface the gate reproduces the closed "
          "form to <1e-9 on 3M-6M h21, 6M-1Y h63 and 1Y-2Y h21 — which pins the "
          "time indexing the frozen tests cannot see.")


def main() -> None:
    self_test()
    rows = []
    for tail in TAILS:
        panel = atm_panel(tail)
        print(f"{tail}: {panel.shape[0]} days, expiries {list(panel.columns)}", flush=True)
        for e1, e2 in PAIRS:
            for h in HORIZONS:
                r = run_cell_ensemble(panel, e1, e2, h)
                r.update({"tail": tail, "pair": f"{e1}-{e2}", "h": h})
                rows.append(r)
                if r.get("n_cycles", 0) >= 5:
                    print(f"  {tail} {e1}-{e2} h={h:3d}: n={r['n_cycles']:3d} "
                          f"median {r['median_gross_bp']:+7.3f} vs RT {r['rt_bp']:.2f} "
                          f"({r['median_over_rt']:+.2f}x)  mean {r['mean_gross_bp']:+7.3f} "
                          f"({r['mean_over_rt']:+.2f}x)  SR {r['per_cycle_sharpe']:+.3f} "
                          f"skew {r['skew']:+.2f} worst {r['worst_cycle_bp']:+.2f} "
                          f"long-back {r['frac_long_back']:.0%} | "
                          f"PHASE-MEDIAN {r['phase_median_over_rt']:+.2f}x "
                          f"(sd {r['phase_sd_over_rt']:.2f}, range "
                          f"{r['phase_min_over_rt']:+.2f}..{r['phase_max_over_rt']:+.2f}, "
                          f"{r['n_phases_clearing_rt']}/{r['n_phases']} phases clear 1x) | "
                          f"frozen-surface carry {r['median_expected_carry_bp']:+.3f} "
                          f"({r['expected_carry_over_rt']:+.2f}x RT)", flush=True)
                else:
                    print(f"  {tail} {e1}-{e2} h={h}: too few cycles", flush=True)
    df = pd.DataFrame(rows)
    df.to_parquet(DATA / "v17_termstructure_gate.parquet")
    ok = df[df["n_cycles"] >= 5]
    verdict = {
        "hypothesis": "H-V-17 ATM vol term-structure roll-down carry",
        "n_cells": int(len(ok)),
        "PHASE-INVARIANT (statistic of record)": {
            "best_cell_phase_median_over_rt": float(ok["phase_median_over_rt"].max()),
            "median_across_cells": float(ok["phase_median_over_rt"].median()),
            "n_cells_above_rt": int((ok["phase_median_over_rt"] > 1.0).sum()),
            "n_cells_negative": int((ok["phase_median_over_rt"] < 0).sum()),
            "max_within_cell_phase_sd": float(ok["phase_sd_over_rt"].max()),
        },
        "phase0_only_DEPRECATED_see_V-V-17B": {
            "best_median_over_rt": float(ok["median_over_rt"].max()),
            "median_across_cells": float(ok["median_over_rt"].median()),
            "n_cells_above_rt": int((ok["median_over_rt"] > 1.0).sum()),
        },
        "n_cells_mean_above_rt": int((ok["mean_over_rt"] > 1.0).sum()),
        "gate_bar": "median realized gross per cycle > 1x RT in at least one pair",
        "median_expected_carry_over_rt": float(ok["expected_carry_over_rt"].median()),
        "n_cells_expected_carry_above_rt": int((ok["expected_carry_over_rt"] > 1.0).sum()),
        "gate_pass": bool((ok["phase_median_over_rt"] > 1.0).any()),
    }
    (DATA / "v17_termstructure_gate.json").write_text(json.dumps(verdict, indent=1))
    print("\n" + json.dumps(verdict, indent=1))


if __name__ == "__main__":
    main()
