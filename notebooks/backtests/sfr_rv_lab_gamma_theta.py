# %% [markdown]
# # SR3 RV Lab — Framework 3: vol vs realized (gamma / theta)
#
# **RV class: C — implied vs delivered on the same contract.**
#
# The only framework where the futures market and the options market disagree
# about something neither put-call parity nor the forward can pin: the *size* of
# the moves the future will actually make. The trade is an ATM straddle at a
# fixed listed strike, delta-hedged **daily on the futures settle** with the
# delta observed the previous close.
#
# Signals tested (all premium-native):
#
# * `IV - RV`: listed ATM normal vol minus trailing realized bp vol of the same
#   contract's own futures rate.
# * `always short`: the unconditional short-gamma benchmark. Every rule has to
#   beat this, not zero — the vol-selling literature's own finding is that the
#   unconditional short is hard to improve on.
# * `vol-return momentum`: sign of the trailing P&L of the always-short program
#   (self-referential; no external data).
#
# ### The trap this notebook has to avoid
#
# SR3 settles on **compounded SOFR over the reference quarter**. Once the quarter
# starts accruing, part of the settlement is already known, so the front
# contract's implied vol falls for a purely mechanical reason that has nothing to
# do with risk premium. Any IV-vs-RV signal that ranks contracts by vol level
# will find enormous fake alpha in the front contract. The cross-sectional work
# below is therefore run on contracts with **time to expiry above a floor**, and
# the time-to-expiry sensitivity is reported.

# %%
CONFIG = dict(
    rv_window=21,             # trailing realized-vol window (business days)
    min_tte=0.15,             # drop contracts inside ~8 weeks of expiry
    min_oi=100,
    contracts_per_leg=100,
    cost_bp=2.5,
    future_leg_bp=0.25,       # charged on every re-hedge, on the traded delta
    rehedge_bands=(0.0, 0.10, 0.25),
    mas=(1, 5, 10),
    zscore_windows=(60, 120),
    entry_zs=(1.0, 1.5, 2.0),
    exits=("t5", "t10", "t20"),
    directions=("fade", "momentum"),
)
CONFIG

# %%
import dataclasses
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append("../../")
sys.path.append(str(Path.cwd()))

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sfr_rv_lab_common import (
    LabConfig, config_from_row, cost_block, header_block, league_row, load_lab,
    run_framework, three_panel_equity,
)
from RVUtils.SFRRVLab import (
    Leg, Structure, add_event_distance, atm_premium_panel,
    constant_maturity_slots, realized_vol_bp, run_backtest,
)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

lab = load_lab()
quotes, contracts = lab["quotes"], lab["contracts"]

# %% [markdown]
# ## The ATM straddle panel and the mechanical-decay check

# %%
atm = atm_premium_panel(quotes, contracts)
atm = atm.merge(constant_maturity_slots(contracts)[
    ["as_of", "symbol", "tte", "cm_slot", "expiry_date"]],
    on=["as_of", "symbol"], how="left")
print(f"ATM straddle rows: {len(atm)}  symbols: {atm['symbol'].nunique()}")

rv = []
for sym, sub in contracts.sort_values("as_of").groupby("symbol"):
    s = sub.set_index("as_of")["forward_rate"]
    rv.append(pd.DataFrame({"as_of": s.index, "symbol": sym,
                            "rv_bp": realized_vol_bp(s, CONFIG["rv_window"])}))
rv = pd.concat(rv, ignore_index=True)
atm = atm.merge(rv, on=["as_of", "symbol"], how="left")
atm["vrp_bp"] = atm["atm_iv_bp"] - atm["rv_bp"]
atm = add_event_distance(atm)
print(atm.groupby("cm_slot")[["tte", "atm_iv_bp", "rv_bp", "vrp_bp"]]
      .median().round(2).to_string())

# %% [markdown]
# The mechanical decay is visible directly: ATM vol against time to expiry. The
# front contract's collapse is the accrued-fixings effect, not cheap options.

# %%
fig, axes = plt.subplots(1, 2, figsize=(13, 4))
for sym, sub in atm.groupby("symbol"):
    axes[0].plot(sub["tte"], sub["atm_iv_bp"], ".", ms=2, alpha=0.4, label=sym)
axes[0].set_xlabel("time to option expiry (years)")
axes[0].set_ylabel("listed ATM normal vol (bp)")
axes[0].set_title("ATM vol collapses into expiry — partly mechanical\n"
                  "(SR3 settles on an accruing quarterly average)", fontsize=10)
axes[0].axvline(CONFIG["min_tte"], color="red", ls="--", lw=1)
axes[0].grid(alpha=0.25)
axes[1].plot(atm.groupby("as_of")["vrp_bp"].median(), lw=1.2)
axes[1].axhline(0, color="grey", lw=0.8)
axes[1].set_title("cross-sectional median IV - trailing RV (bp)", fontsize=10)
axes[1].grid(alpha=0.25)
fig.autofmt_xdate()
fig.tight_layout()
plt.show()

# %%
panel = atm[atm["tte"] >= CONFIG["min_tte"]].copy()
panel = panel.dropna(subset=["vrp_bp"])
print(f"after the time-to-expiry floor: {len(panel)} rows, "
      f"{panel['symbol'].nunique()} symbols")
print(f"median VRP {panel['vrp_bp'].median():+.1f}bp   "
      f"share IV>RV {(panel['vrp_bp'] > 0).mean():.1%}")

# %% [markdown]
# ## The tradeable package
#
# One ATM straddle per contract at the listed strike fixed on the execution
# date, delta-hedged daily by the engine. `direction=+1` is LONG the straddle
# (long gamma, paying theta); `fade` on a rich IV-minus-RV signal therefore sells
# gamma, which is the direction the literature says carries the premium.

# %%
STRIKE = panel.set_index(["symbol", "as_of"])["atm_strike"].sort_index()


def builder(key, exec_date, direction):
    try:
        k = float(STRIKE.loc[(key, exec_date)])
    except (KeyError, TypeError):
        return None
    return Structure((Leg("option", key, 1.0, "C", k),
                      Leg("option", key, 1.0, "P", k)),
                     label=f"straddle {key}@{k:g}")


BASE = LabConfig(lag=1, round_trip_cost_bp=CONFIG["cost_bp"],
                 contracts_per_leg=CONFIG["contracts_per_leg"],
                 delta_hedge="daily", future_leg_bp=CONFIG["future_leg_bp"],
                 rehedge_band=0.0)

sig_vrp = panel.rename(columns={"symbol": "key"})[
    ["key", "as_of", "vrp_bp", "tte", "days_to_fomc"]].copy()
sig_vrp["signal"] = sig_vrp["vrp_bp"]
sig_vrp["gate"] = True

GRID = {"direction": list(CONFIG["directions"]), "ma": list(CONFIG["mas"]),
        "zscore_window": list(CONFIG["zscore_windows"]),
        "entry_min_zscore": list(CONFIG["entry_zs"]),
        "exit_style": list(CONFIG["exits"])}
PARAMS = ["direction", "ma", "zscore_window", "entry_min_zscore", "exit_style"]

# %% [markdown]
# ## Benchmark first: the unconditional short-gamma program
#
# Sell every contract's ATM straddle every N days, delta-hedge daily, hold to the
# horizon. No signal at all. This is the number every rule below must beat.

# %%
def _always(direction: int, hold: str = "t20", every: int = 5) -> pd.DataFrame:
    s = sig_vrp.copy()
    s["signal"] = 1.0 if direction < 0 else -1.0     # constant -> |z| is undefined
    return s


bench_rows = []
for hold in ("t5", "t10", "t20"):
    for d in ("short", "long"):
        s = sig_vrp.copy()
        # a constant signal has no z-score, so drive entries off a trivially
        # always-true rule: alternate the signal so |z| is large every bar
        s["signal"] = np.tile([1.0, -1.0], len(s))[:len(s)]
        cfg = dataclasses.replace(
            BASE, ma=1, zscore_window=20, zscore_min_periods=10,
            entry_min_zscore=0.5, exit_style=hold, entry_every=5,
            direction="fade" if d == "short" else "momentum")
        r = run_backtest(cfg, signals=s, book=lab["book"], builder=builder)
        bench_rows.append({"side": d, "hold": hold, **{
            k: r.metrics[k] for k in ("n_trades", "hit_rate", "avg_net_bp",
                                      "total_net_bp", "total_net_usd", "sharpe",
                                      "max_dd_bp")}})
bench = pd.DataFrame(bench_rows).round(3)
print("UNCONDITIONAL GAMMA PROGRAM (delta-hedged daily, no signal)")
print(bench.to_string(index=False))
print("\nA positive 'short' row is the variance risk premium net of hedging "
      "costs; every signal below must beat it, not zero.")

# %% [markdown]
# ## Signal 1 — IV minus trailing realized vol

# %%
out_vrp = run_framework(
    "3. Gamma/theta (IV-RV)", signals=sig_vrp, book=lab["book"], builder=builder,
    base=BASE, grid_spec=GRID, params=PARAMS, cls="C",
    note=f"ATM straddle, daily delta hedge, tte>={CONFIG['min_tte']}y, "
         f"RV window {CONFIG['rv_window']}d")

# %% [markdown]
# ## Re-hedge band sensitivity
#
# The literature's claim is that P&L net of costs is maximised at a *modest*
# delta band rather than hedging every day. SR3's futures leg is cheap, so the
# optimum should be tighter here — this measures it instead of assuming it.

# %%
band_rows = []
for band in CONFIG["rehedge_bands"]:
    cfg = dataclasses.replace(out_vrp["config"], rehedge_band=band)
    r = run_backtest(cfg, signals=sig_vrp, book=lab["book"], builder=builder)
    band_rows.append({"rehedge_band": band, **{
        k: r.metrics[k] for k in ("n_trades", "hit_rate", "avg_net_bp",
                                  "total_net_bp", "total_net_usd", "sharpe",
                                  "max_dd_bp")}})
print(pd.DataFrame(band_rows).round(3).to_string(index=False))

# %% [markdown]
# ## Signal 2 — vol-return momentum (self-referential, no external data)
#
# Take the daily P&L of the always-short program, and go long gamma when its
# trailing return is negative. The highest-information-ratio single signal in the
# systematic vol literature; here it is rebuilt from this sample's own P&L.

# %%
short_cfg = dataclasses.replace(BASE, ma=1, zscore_window=20,
                                zscore_min_periods=10, entry_min_zscore=0.5,
                                exit_style="t20", entry_every=5, direction="fade")
s_alt = sig_vrp.copy()
s_alt["signal"] = np.tile([1.0, -1.0], len(s_alt))[:len(s_alt)]
short_res = run_backtest(short_cfg, signals=s_alt, book=lab["book"],
                         builder=builder)
short_daily = short_res.daily_bp.reindex(
    pd.DatetimeIndex(sorted(sig_vrp["as_of"].unique()))).fillna(0.0)
trail = short_daily.rolling(21, min_periods=10).sum()
print(f"always-short daily P&L: {len(short_daily)} days, "
      f"total {short_daily.sum():+.1f}bp")

sig_mom = sig_vrp.copy()
sig_mom["signal"] = sig_mom["as_of"].map(trail)
sig_mom = sig_mom.dropna(subset=["signal"])
out_mom = run_framework(
    "3b. Vol-return momentum", signals=sig_mom, book=lab["book"], builder=builder,
    base=BASE, grid_spec=GRID, params=PARAMS, cls="C",
    note="signal = trailing 21d P&L of the always-short gamma program")

# %% [markdown]
# ## Signal 3 — cross-sectional vol carry
#
# Rank contracts by VRP within each date and trade the extremes against each
# other. Removing the date mean strips out the common vol factor, which is what
# makes this the highest-power test in the set.

# %%
sig_xs = sig_vrp.copy()
sig_xs["signal"] = sig_xs.groupby("as_of")["vrp_bp"].transform(
    lambda s: s - s.mean())
out_xs = run_framework(
    "3c. Cross-sectional vol carry", signals=sig_xs, book=lab["book"],
    builder=builder, base=BASE, grid_spec=GRID, params=PARAMS, cls="C",
    note="VRP demeaned across contracts each date")

# %% [markdown]
# ## Benchmark row for the league table

# %%
best_bench = bench.sort_values("total_net_bp", ascending=False).iloc[0]
cfg_b = dataclasses.replace(
    BASE, ma=1, zscore_window=20, zscore_min_periods=10, entry_min_zscore=0.5,
    exit_style=best_bench["hold"], entry_every=5,
    direction="fade" if best_bench["side"] == "short" else "momentum")
res_b = run_backtest(cfg_b, signals=s_alt, book=lab["book"], builder=builder)
header_block("3d. Unconditional gamma program", res_b, grid=None)
league_row("3d. Unconditional gamma (benchmark)", best_bench["side"], res_b,
           grid=None, cls="C",
           note="no signal — the number every vol rule must beat")
