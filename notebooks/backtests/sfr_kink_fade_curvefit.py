# %% [markdown]
# # SFR kink-fade — the curve-fit lead, swept properly
#
# **Follow-up to** `sfr_kink_fade_backtest.ipynb`, which found that the FOMC
# meeting calendar explains 1–6% of a butterfly's variance and that the *real*
# effect is smoothing: the residual of **any** smoother mean-reverts where the
# raw fly does not, and a plain **cubic spline in slot index** beat every meeting
# basis on grid median, positive-config share and Sharpe.
#
# That notebook found it as a *control*, so it never swept it. Three things were
# never tested together and are tested here:
#
# 1. **The standardisation.** A residual's zero is a fitted fair value, so
#    dividing by a trailing sd and **keeping that zero** (`scale_only_zscore`) is
#    a different signal from a full trailing z-score, which throws the model's
#    zero away and re-centres on a rolling mean. The pairing of `scale`
#    standardisation with the **`z0` exit** — "exit when the residual reaches
#    zero", i.e. *exit at fitted fair value* — is what produced the winning
#    configs, and it was never a grid axis.
# 2. **The spacing.** The prior labs only ever built 3m and 6m flies. A 6m fly
#    carries 2.9× the dispersion of a 3m fly for the *identical* four-contract
#    cost, which is the only lever found so far that moves the cost-to-move
#    ratio. 9m and 12m flies are now built and are tested here for the first
#    time.
# 3. **The functional form**, on the same footing as everything else rather than
#    fixed at whatever the last notebook used.
#
# The instrument is **chosen by the pond test**, not asserted: whichever spacing
# has the largest oracle bound net of the round trip gets the full treatment.

# %%
CONFIG = dict(
    spacings=("3m", "6m", "9m", "12m"),
    window="liquid16",                  # 2022+, the only honest 16-slot window
    long_window="front8",               # 2019+, regime-rich but thin at 9m/12m
    forms=("ns", "nss", "spline", "poly3"),
    grid_forms=("spline", "nss"),
    cost_bp=2.0,                        # 4 contracts x 2 sides x 0.25bp
    cost_curve=(0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 4.0),
    n_packages=100,
    windows=(60, 120, 250),
    standardisations=("scale", "z"),
    entry_zs=(1.5, 2.0, 2.5),
    exits=("z0", "t10", "t21", "t42"),
    directions=("fade", "momentum"),
    max_hold=63,
    lag=1,
    horizons=(5, 10, 21),
)
CONFIG

# %%
import sys
import time
from pathlib import Path

sys.path.append("../../")
sys.path.append(str(Path.cwd()))

import numpy as np
import pandas as pd

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from RVUtils.MeanRev import MRConfig
from RVUtils.MeanRev.signals import (
    curvefit_residual_signal, scale_only_zscore, zscore_signal,
)

import sfr_kink_fade_common as K

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 60)
plt.rcParams.update({"figure.dpi": 110, "axes.grid": True, "grid.alpha": 0.25})

T0 = time.time()
BASE = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=CONFIG["cost_bp"],
                max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])
print(f"taker round trip {CONFIG['cost_bp']}bp on the package "
      f"({CONFIG['n_packages']} packages = {4 * CONFIG['n_packages']:,} contracts "
      f"= ${25 * CONFIG['n_packages']:,}/bp)")
print(f"results -> {K.DATA_DIR}")

# %% [markdown]
# ## 1. Four spacings, one cost
#
# Every one of these is a `1/-2/1` package: **four contracts, 2.0bp round trip,
# $25 per bp of fly.** The only thing that changes with the spacing is how far
# the thing moves. That is the whole reason to look.

# %%
labs = {}
for sp in CONFIG["spacings"]:
    labs[sp] = K.load_lab(sp, CONFIG["window"])
    lv = labs[sp]["levels"]
    print(f"{sp:>4}: {lv.shape[1]:2d} flies x {lv.shape[0]} sessions   "
          f"{lv.index.min().date()} -> {lv.index.max().date()}")

rows = []
for sp, lab in labs.items():
    lv = lab["levels"]
    st = lab["struct"]
    d = lv.diff().stack()
    rows.append({
        "spacing": sp, "n_keys": lv.shape[1],
        "pooled_sd_bp": float(lv.stack().std()),
        "daily_sd_bp": float(d.std()),
        "sd_in_ticks": float(lv.stack().std() / 0.5),
        "iqr_bp": float(lv.stack().quantile(0.75) - lv.stack().quantile(0.25)),
        "pct_unchanged_day": float((d.abs() < 1e-9).mean()),
        "round_trip_bp": CONFIG["cost_bp"],
        "cost_in_daily_sd": CONFIG["cost_bp"] / float(d.std()),
    })
disp = pd.DataFrame(rows)
print("\nDISPERSION PER SPACING (all four cost exactly 2.0bp to trade)")
print(disp.round(3).to_string(index=False))
print("\n  `sd_in_ticks` is the honest lattice check: the SR3 settlement grid is")
print("  0.5bp, so a structure whose sd is a handful of ticks is a lattice, not a")
print("  price series. `cost_in_daily_sd` is how many days of typical movement")
print("  the round trip costs -- lower is better and it is the only number here")
print("  that a wider spacing can improve for free.")

# %% [markdown]
# ## 2. The curve fits
#
# Fit a smooth function of maturity to the 16-slot strip on each date and take
# each contract's deviation. The fit is **cross-sectional on that date only**, so
# it carries no time-series look-ahead by construction — no window, no burn-in.
#
# A butterfly is already a second difference along the strip and a smooth curve
# has small second differences by design, so the residual of a smooth fit is
# *almost* the fly again. The diagnostic measures exactly how much.

# %%
slot_panel = labs["3m"]["slot_panel"]
_RESID = {}


def resid_slots(form):
    """Per-slot residual panel, memoised. One fit per date, shared by every
    spacing -- the strip does not know how far apart a fly's legs are."""
    if form not in _RESID:
        t = time.time()
        # struct only supplies leg slots for the mapping; ask for the raw slot
        # residual by mapping onto the 3m frame and inverting is fragile, so the
        # panel is built directly here and combined per spacing below.
        from RVUtils.curve_fit_rv import _ns_yield, _nss_yield
        from scipy.interpolate import LSQUnivariateSpline
        from scipy.optimize import least_squares

        P = slot_panel.dropna(axis=1, how="all").sort_index()
        cols = list(P.columns)
        x = np.array([float(c) / 4.0 for c in cols])
        arr = P[cols].to_numpy(dtype=float)
        out = np.full(arr.shape, np.nan)
        warm = None
        for i in range(arr.shape[0]):
            y = arr[i]
            ok = np.isfinite(y)
            if ok.sum() < 6:
                continue
            xf, yf = x[ok], y[ok]
            try:
                if form in ("ns", "nss"):
                    fn = _ns_yield if form == "ns" else _nss_yield
                    cold = ([yf[-1], yf[0] - yf[-1], 0.0, 2.0] if form == "ns"
                            else [yf[-1], yf[0] - yf[-1], 0.0, 0.0, 2.0, 5.0])
                    p0 = warm if warm is not None and len(warm) == len(cold) else cold
                    with np.errstate(over="ignore", invalid="ignore"):
                        res = least_squares(lambda p: fn(xf, *p) - yf, p0, max_nfev=200)
                        if not res.success:
                            res = least_squares(lambda p: fn(xf, *p) - yf, cold,
                                                max_nfev=800)
                        warm = res.x if res.success else None
                        fit = fn(x, *res.x)
                elif form == "spline":
                    fit = LSQUnivariateSpline(xf, yf, t=np.quantile(xf, [0.33, 0.66]),
                                              k=3)(x)
                else:
                    fit = np.polyval(np.polyfit(xf, yf, 3), x)
            except Exception:
                continue
            out[i] = (y - fit) * 100.0          # bp
        _RESID[form] = pd.DataFrame(out, index=P.index, columns=cols)
        print(f"  built {form} slot residual in {time.time() - t:.1f}s")
    return _RESID[form]


def resid_fly(lab, form):
    from RVUtils.MeanRev.signals import structure_signal_from_slots

    L = lab["levels"]
    return structure_signal_from_slots(resid_slots(form), lab["struct"],
                                       scale=1.0).reindex(index=L.index,
                                                          columns=L.columns)


rows = []
for form in CONFIG["forms"]:
    for sp, lab in labs.items():
        r = resid_fly(lab, form)
        lv = lab["levels"]
        corr = pd.Series({c: lv[c].corr(r[c]) for c in lv.columns})
        rows.append({"form": form, "spacing": sp,
                     "resid_sd_bp": float(r.stack().std()),
                     "raw_sd_bp": float(lv.stack().std()),
                     "resid_share_of_sd": float(r.stack().std() / lv.stack().std()),
                     "median_corr_with_raw": float(corr.median())})
fits = pd.DataFrame(rows)
print("\nRESIDUAL vs RAW FLY, per form and spacing")
print(fits.round(3).to_string(index=False))
print("\n  median_corr_with_raw near 1.0 would mean the 'curve residual' IS the")
print("  fly and this whole framework collapses into a z-score notebook.")
fits.to_csv(K.DATA_DIR / "curvefit_forms.csv", index=False)

# %%
d = slot_panel.dropna().index[-1]
y = slot_panel.loc[d].dropna()
x = np.array([int(c) for c in y.index])
fig, axes = plt.subplots(1, 2, figsize=(14, 4))
axes[0].plot(x, y.to_numpy(), "o-", color="black", lw=1.4, ms=5, label="SR3 settles")
for form in CONFIG["forms"]:
    r = resid_slots(form)
    axes[0].plot(x, y.to_numpy() - r.loc[d, x].to_numpy() / 100.0, lw=1.1,
                 alpha=0.85, label=form)
    axes[1].plot(x, r.loc[d, x].to_numpy(), "o-", lw=1.0, ms=3, label=form)
axes[0].set_xlabel("strip slot")
axes[0].set_ylabel("rate (%)")
axes[0].set_title(f"strip and fits, {pd.Timestamp(d).date()}", fontsize=10)
axes[0].legend(fontsize=8)
axes[1].axhline(0, color="grey", lw=0.8)
axes[1].set_xlabel("strip slot")
axes[1].set_ylabel("residual (bp)")
axes[1].set_title("per-contract residual", fontsize=10)
axes[1].legend(fontsize=8)
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 3. The pond test picks the instrument
#
# Before any grid: on the days each signal fires, how far does the structure
# actually move? `oracle_net_bp` is what a trader with perfect foresight of the
# **direction** would capture net of the 2.0bp round trip — a ceiling no signal
# work can exceed. A spacing whose ceiling is negative cannot be rescued by a
# better kink definition, and the 3m fly is exactly that.

# %%
PRIMARY_FORM = "spline"
ponds = []
for sp, lab in labs.items():
    lv = lab["levels"]
    r = resid_fly(lab, PRIMARY_FORM)
    sig = {
        f"{sp} raw z": zscore_signal(lv, window=120),
        f"{sp} spline resid (scale)": scale_only_zscore(r, window=120),
        f"{sp} spline resid (z)": zscore_signal(r, window=120),
    }
    t = K.selectivity_table(lv, sig, entry_z=2.0, gate=lab["gate"],
                            horizons=CONFIG["horizons"],
                            round_trip_bp=CONFIG["cost_bp"])
    t.insert(0, "spacing", sp)
    ponds.append(t)
pond = pd.concat(ponds, ignore_index=True)
pond.to_csv(K.DATA_DIR / "curvefit_pond.csv", index=False)
print("POND TEST across spacings (entry |z| >= 2.0, round trip 2.0bp)")
print(pond[pond["horizon"] == 21].round(3).to_string(index=False))

# %%
h = 21
best_by_spacing = (pond[(pond["horizon"] == h) & (pond["signal"] != "unconditional")]
                   .groupby("spacing")["oracle_net_bp"].max().sort_values(ascending=False))
print(f"\nbest oracle_net_bp at h={h} by spacing (bp per trade, net of 2.0bp):")
print(best_by_spacing.round(3).to_string())
PRIMARY = str(best_by_spacing.index[0])
print(f"\n  -> PRIMARY SPACING CHOSEN BY MEASUREMENT: {PRIMARY}")
print(f"     ({best_by_spacing.iloc[0]:+.2f}bp of headroom against a 2.0bp round trip)")
viable = [s for s in best_by_spacing.index if best_by_spacing[s] > 0]
print(f"     spacings whose oracle clears the round trip at all: {viable}")

# %% [markdown]
# ## 4. The sweep that was never run
#
# `standardise` is a grid axis for the first time, so "keep the fitted model's
# zero" versus "re-centre on a trailing mean" is a measurement rather than a
# choice — and `exit_style='z0'` means different things under the two. Under
# `scale` it is *exit at fitted fair value*; under `z` it is *exit at the
# trailing mean of the residual*.

# %%
GRID = {"form": CONFIG["grid_forms"], "window": CONFIG["windows"],
        "standardise": CONFIG["standardisations"], "entry_z": CONFIG["entry_zs"],
        "exit_style": CONFIG["exits"], "direction": CONFIG["directions"]}
PARAMS = ["form", "window", "standardise", "entry_z", "exit_style", "direction"]
EXITS = ("z0", "band", "t5", "t10", "t21", "t42")

lab_p = labs[PRIMARY]


def cf_sig(L, form, window, standardise):
    r = resid_fly(lab_p, form).reindex(index=L.index, columns=L.columns)
    return (scale_only_zscore(r, window=window) if standardise == "scale"
            else zscore_signal(r, window=window))


out_main = K.run_family(f"C1. curve-fit residual ({PRIMARY}, {CONFIG['window']})",
                        lab=lab_p, signal_fn=cf_sig, grid_spec=GRID, params=PARAMS,
                        base=BASE, cls="curvefit",
                        note="standardisation swept: model's zero vs trailing mean",
                        exits=EXITS)

# %% [markdown]
# ### 4a. Does keeping the model's zero actually matter?

# %%
g = out_main["grid"]
std_split = (g.groupby("standardise")
             .agg(n_configs=("total_net_bp", "size"),
                  median_net_bp=("total_net_bp", "median"),
                  pct_positive=("total_net_bp", lambda s: float((s > 0).mean())),
                  best_net_bp=("total_net_bp", "max"),
                  median_trades=("n_trades", "median")))
print("STANDARDISATION (the axis this notebook exists to test)")
print(std_split.round(3).to_string())

pair = (g.groupby(["standardise", "exit_style"])["total_net_bp"]
        .median().unstack().round(1))
print("\nmedian net bp by standardisation x exit -- the pairing under test is "
      "(scale, z0) = 'exit at fitted fair value':")
print(pair.to_string())
best_cell = pair.stack().idxmax()
print(f"\n  best cell: standardise={best_cell[0]}, exit={best_cell[1]} "
      f"({pair.loc[best_cell[0], best_cell[1]]:+.1f}bp median)")
std_split.to_csv(K.DATA_DIR / "curvefit_standardisation.csv")

# %% [markdown]
# ## 5. Every spacing, same grid
#
# League rows so the four spacings rank against each other and against the
# meeting-residual rows from the main kink notebook.

# %%
for sp in CONFIG["spacings"]:
    if sp == PRIMARY:
        continue
    lab_s = labs[sp]

    def cf_sig_s(L, form, window, standardise, _lab=lab_s):
        r = resid_fly(_lab, form).reindex(index=L.index, columns=L.columns)
        return (scale_only_zscore(r, window=window) if standardise == "scale"
                else zscore_signal(r, window=window))

    K.run_family(f"C1{sp}. curve-fit residual ({sp}, {CONFIG['window']})",
                 lab=lab_s, signal_fn=cf_sig_s, grid_spec=GRID, params=PARAMS,
                 base=BASE, cls="curvefit", note=f"{sp} spacing, same grid",
                 exits=EXITS)

# %% [markdown]
# ## 6. The long window
#
# `front8` starts in 2019 and buys a full policy cycle, but it restricts the back
# leg to slot 8 — which at 12m spacing leaves nothing. Whichever spacings survive
# that restriction are run; the rest are reported as unavailable rather than
# quietly skipped.

# %%
for sp in CONFIG["spacings"]:
    try:
        lab_l = K.load_lab(sp, CONFIG["long_window"])
    except Exception as exc:
        print(f"{sp}: cannot load {CONFIG['long_window']} ({exc})")
        continue
    n_keys = lab_l["levels"].shape[1]
    if n_keys < 3:
        print(f"{sp}: only {n_keys} keys on {CONFIG['long_window']} "
              f"(back leg must sit inside slot 8) -- NOT RUN")
        continue

    def cf_sig_l(L, form, window, standardise, _lab=lab_l):
        from RVUtils.MeanRev.signals import structure_signal_from_slots

        r = structure_signal_from_slots(resid_slots(form), _lab["struct"],
                                        scale=1.0).reindex(index=L.index,
                                                           columns=L.columns)
        return (scale_only_zscore(r, window=window) if standardise == "scale"
                else zscore_signal(r, window=window))

    print(f"\n{sp}: {n_keys} keys on {CONFIG['long_window']}")
    K.run_family(f"C1L{sp}. curve-fit residual ({sp}, {CONFIG['long_window']}, 2019+)",
                 lab=lab_l, signal_fn=cf_sig_l, grid_spec=GRID, params=PARAMS,
                 base=BASE, cls="curvefit", note="regime-rich window", exits=EXITS)

# %% [markdown]
# ## 7. Verdict

# %%
league = pd.read_csv(K.DATA_DIR / "league_table.csv")
cf = league[league["class"] == "curvefit"]
show = ["framework", "variant", "structure", "window", "n_trades", "hit_rate",
        "avg_net_bp", "total_gross_bp", "total_net_bp", "grid_median_net_bp",
        "dsr_prob", "nonoverlap_sharpe", "verdict"]
print(f"CURVE-FIT ROWS ({len(cf)} of {len(league)} in the kink lab's league table)\n")
print(cf.sort_values("total_net_bp", ascending=False)[
    [c for c in show if c in cf.columns]].round(3).to_string(index=False))
league.sort_values("total_net_bp", ascending=False).to_csv(
    K.DATA_DIR / "league_table_sorted.csv", index=False)

# %%
print("verdict distribution, curve-fit rows only:")
print(cf["verdict"].value_counts().to_string())
n = len(cf)
print(f"""
  rows net positive GROSS            {int((cf['total_gross_bp'] > 0).sum())} / {n}
  rows net positive at taker (2.0bp) {int((cf['net_bp_taker'] > 0).sum())} / {n}
  rows with a positive GRID MEDIAN   {int((cf['grid_median_net_bp'] > 0).sum())} / {n}
  median DSR probability             {cf['dsr_prob'].median():.4f}
  ALIVE                              {int((cf['verdict'] == 'ALIVE').sum())}""")

# %%
best_sp = best_by_spacing
print("=" * 92)
print("WHAT THIS NOTEBOOK MEASURED")
print("=" * 92)
_best = cf.loc[cf["total_net_bp"].idxmax()] if len(cf) else None
print(f"""
1. WIDER SPACINGS ARE THE ONLY FREE LUNCH ON THE COST RATIO.
   All four structures are the same 4 contracts and the same 2.0bp round trip.
   Pooled dispersion runs {disp.set_index('spacing')['pooled_sd_bp'].min():.1f}bp to {disp.set_index('spacing')['pooled_sd_bp'].max():.1f}bp across them, and the round trip
   costs {disp.set_index('spacing')['cost_in_daily_sd'].max():.2f} days of typical movement at the tightest spacing against
   {disp.set_index('spacing')['cost_in_daily_sd'].min():.2f} at the widest.

2. THE POND PICKED {PRIMARY}. Best oracle headroom at h=21, net of the round trip:
{best_sp.round(2).to_string()}
   Spacings that clear the round trip at all with perfect direction-calling:
   {viable}.

3. THE STANDARDISATION AXIS -- the thing this notebook exists to test.
   median net bp: {' / '.join(f"{k}={v:+.1f}" for k, v in std_split['median_net_bp'].items())}
   best cell (standardise x exit): {best_cell[0]} x {best_cell[1]}
   Keeping the fitted model's zero is {'BETTER' if std_split['median_net_bp'].idxmax() == 'scale' else 'NOT better'} than re-centring on a
   trailing mean on the median config.

4. VERDICT: {int((cf['verdict'] == 'ALIVE').sum())} of {n} curve-fit rows ALIVE, {int((cf['grid_median_net_bp'] > 0).sum())} with a positive grid median.""")
if _best is not None:
    print(f"""   Best row: {_best['framework']} / {_best['variant']}
   {_best['total_net_bp']:+.1f}bp net at taker over {int(_best['n_trades'])} trades, grid median
   {_best['grid_median_net_bp']:+.1f}bp, DSR p = {_best['dsr_prob']:.3f} -> {_best['verdict']}.""")
print(f"\ntotal runtime {time.time() - T0:.0f}s")
