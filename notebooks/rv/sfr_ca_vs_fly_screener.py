# %% [markdown]
# # SFR convexity adjustment vs USD SOFR butterflies — live screener
#
# The monitoring companion to `notebooks/backtests/convexity_rv/cavf_backtest`.
# One table per run: every CA structure (packs, CME bundles, outright ranks)
# against its declared butterflies, with the fair-value fits, the Ho-Lee
# implied-vol column, the carry proxy, and the positioning / CME–LCH-basis /
# open-interest enrichment — Citi's 13-column screen format, on our own data.
#
# **Read the backtest before trading anything on this screen.** The 515-cell
# pre-registered grid found NO variation of CA-vs-fly mean reversion that
# clears its own null once fills are executable (t+1) and IMM-roll label
# switches are excluded; the measured fair-value R²s below are the reason. This
# screen is a measurement instrument: where the CA sits, what would have to be
# true for a trade, and which published mechanism (dealer positioning, margin
# wedge) is currently loud.
#
# Two marks, never spliced: the **intraday** CA (minute tape + minute swap
# curve, provenance columns asserted) and the **17:00 settle** CA. A row says
# which one it is.

# %%
import nest_asyncio
nest_asyncio.apply()

import dataclasses
import datetime as dt
import json
import os
import pathlib
import sys
import zoneinfo

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path.cwd()
while not (REPO / "RVUtils").exists() and REPO != REPO.parent:
    REPO = REPO.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

import plotly.graph_objects as go
import plotly.io as pio
pio.renderers.default = "plotly_mimetype+notebook_connected"

from RVUtils.ConvexityRV import cavf_signals as S
from RVUtils.ConvexityRV import cavf_universe as U
from RVUtils.ConvexityRV import strat2_fly_universe as FU

DATA = REPO / "notebooks" / "data" / "convexity_rv"
CT = zoneinfo.ZoneInfo("America/Chicago")
pd.set_option("display.width", 240, "display.max_columns", 40)
print(f"repo {REPO}")

# %% [markdown]
# ## 1. CONFIG — every knob, and why it is set where it is

# %%
@dataclasses.dataclass(frozen=True)
class ScreenConfig:
    #: the intraday instant to attempt, CME's own zone. None = 14:00 CT on the
    #: most recent business day. The tape stamps a NAME, not an offset — a
    #: frozen offset is a silent half-year cache miss.
    intraday_instant: dt.datetime | None = None
    #: structures on the screen: the 14 tradeable + every outright rank.
    show_all_ranks: bool = True
    #: z windows, rows, matching the backtest's declared primaries.
    z_window: int = 252
    z_window_3m: int = 63
    #: fair-value fit window (levels, with intercept — family B's convention).
    fit_window: int = 252
    #: enrichment lags: TFF release lag is applied by the panel builder; the
    #: market-observable series get one business day.
    market_lag_bdays: int = 1
    #: allow the two 4-HTTP-call refreshes (CCP basis tail, CFTC year files).
    #: False = strictly offline from the panels and caches.
    allow_network_refresh: bool = False


CFG = ScreenConfig()
print(json.dumps({k: str(v) for k, v in dataclasses.asdict(CFG).items()}, indent=1))

# %% [markdown]
# ## 2. The history panels (the same artifacts the backtest certified)

# %%
ca_wide = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
ca_wide.index = pd.to_datetime(ca_wide.index)
cols = {c.split()[1]: c for c in ca_wide.columns}
ca_raw = {lab: ca_wide[c].dropna() for lab, c in cols.items()}
ROLLS = S.imm_roll_dates(ca_wide.index)
ca_spl = {lab: S.roll_splice(s, ROLLS) for lab, s in ca_raw.items()}

legs = pd.read_parquet(DATA / "cavf_fly_legs.parquet")
wide = FU.legs_wide(legs)
wide.index = pd.to_datetime(wide.index)
FLIES = {f.fly_id: f for f in U.tradeable_fly_specs()}
fly_hist = {fid: FU.fly_rate_series(wide, f, 0.5, 0.5).dropna()
            for fid, f in FLIES.items()}

LAST = ca_wide.index.max()
print(f"CA {ca_wide.shape} to {LAST.date()}  |  legs {wide.shape}  |  "
      f"{len(FLIES)} flies  |  {len(ROLLS)} rolls")
assert (LAST - pd.Timestamp.now()).days > -8, (
    "the CA panel is more than a week stale — re-run "
    "notebooks/backtests/convexity_rv/_cavf_backfill_ca.py before screening")

# %% [markdown]
# ## 3. The live mark — intraday if the tape serves it, settle otherwise
#
# Per rank, loud: a colour whose strip depth is not warmed is REFUSED by name,
# never served shallower under a deeper name. `price_source` is asserted single
# — an intraday row and a settle row must never blend.

# %%
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from TB.IRSwapsTB import IRSwapsTB

tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False,
               use_ts_cache=False)

COLOURS = ["WHITES", "REDS", "GREENS", "BLUES", "GOLDS"]
if CFG.intraday_instant is not None:
    _instant = CFG.intraday_instant
else:
    _d = pd.Timestamp.now(tz=CT)
    # 14:00 CT on the most recent session whose 14:00 has already HAPPENED —
    # an instant in the future is a guaranteed miss dressed as a refusal.
    if _d.hour < 14:
        _d -= pd.Timedelta(days=1)
    while _d.weekday() >= 5:
        _d -= pd.Timedelta(days=1)
    _instant = dt.datetime(_d.year, _d.month, _d.day, 14, 0, tzinfo=CT)

from RVUtils.ConvexityRV import ca_intraday as CI


def _try_live(instant):
    """One colour per call, so a deep refusal cannot kill the servable front.

    The intraday API's refusal is per RANK by design — GOLDS needing depth 20
    on a depth-17 tape must not take WHITES/REDS/GREENS/BLUES down with it
    (the first committed run of this screener did exactly that with one
    batched call, and showed zero live rows on a session serving four).
    """
    rows, refs = {}, {}
    for colour in COLOURS:
        try:
            one = tb.sfr_cvx_adj_intraday([colour], [instant])
            CI.assert_single_price_source(one, CI.PRICE_SOURCE_INTRADAY)
            r = one.iloc[0]
            rows[colour] = {"ca_live_bp": float(r["cvx_adj_bp"]),
                            "mark": "intraday", "instant": str(r["timestamp"])}
        except Exception as exc:                              # noqa: BLE001
            refs[colour] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return rows, refs


live_rows, refused = _try_live(_instant)
if not live_rows and CFG.intraday_instant is None:
    # the default instant's session may simply not be warmed; fall back once
    # to the most recent session the depth warm is known to have covered
    _fallback = dt.datetime(2026, 8, 19, 14, 0, tzinfo=CT)
    print(f"no colour served at {_instant}; retrying the known-warmed "
          f"session {_fallback}")
    live_rows, refused = _try_live(_fallback)
    _instant = _fallback
print(f"intraday CA at {_instant}: served {sorted(live_rows)}")
for k, v in refused.items():
    print(f"  REFUSED {k}: {v}")

settle_ca = {lab: float(s.iloc[-1]) for lab, s in ca_raw.items()}
print(f"settle mark: {LAST.date()}")

# %% [markdown]
# ## 4. Enrichment — what the published mechanisms are doing now
#
# Dealer positioning (Citi/JPM's mechanism, release-lagged), the CME–LCH
# basis (the margin wedge, market-lagged), and whole-strip open interest.
# Provenance per column; a reader must be able to tell which source served it.

# %%
from BT.signals.cftc_positioning import (build_positioning_panel,
                                         fetch_cftc_financial_futures,
                                         positioning_zscore)

raw = fetch_cftc_financial_futures(
    cache_path=str(REPO / "BT" / "results" / "tfp_screener" / "cftc_raw.parquet"))
prov = {}
enr = {}
for metric in ("dealer_net", "lev_net", "am_net"):
    p = build_positioning_panel(raw=raw, tenors=["SOFR3M"], metric=metric)
    s = p["SOFR3M"].dropna()
    z = positioning_zscore(p, window=52)["SOFR3M"].dropna()
    enr[metric] = float(s.iloc[-1])
    enr[f"{metric}_z"] = float(z.iloc[-1]) if len(z) else np.nan
    prov[metric] = (f"CFTC TFF SOFR-3M, weekly, release-lagged 3bd, "
                    f"last report visible {s.index[-1].date()}")

oi = raw[raw["Market_and_Exchange_Names"].str.contains("SOFR-3M|3-MONTH SOFR")]
oi_s = (oi.assign(date=pd.to_datetime(oi["Report_Date_as_YYYY-MM-DD"]))
        .groupby("date")["Open_Interest_All"].sum().sort_index())
enr["oi_strip"] = float(oi_s.iloc[-1])
enr["oi_strip_chg_4w"] = float(oi_s.iloc[-1] - oi_s.iloc[-5]) if len(oi_s) > 5 else np.nan
prov["oi_strip"] = "CFTC whole-strip Open_Interest_All (per-contract OI is survivorship-shaped)"

from MDP.IRClearingHouseBasisSwaps.ccp_basis_cache import (CCPBasisCacheMiss,
                                                           basis_panel)

# the warm span is clamped to the last date the wire actually served, so a
# request ending "today" can be legitimately cold on a Monday morning — step
# the end back through the last week rather than failing the screen.
bas = None
for back in range(0, 6):
    try:
        bas = basis_panel(dt.date(2021, 1, 4),
                          dt.date.today() - dt.timedelta(days=back),
                          tenors=("5y", "10y", "30y"),
                          allow_network=CFG.allow_network_refresh)
        break
    except CCPBasisCacheMiss:
        continue
assert bas is not None, (
    "the CCP basis cache is more than a week cold — warm it: "
    "CCPBasisCache().warm(<start>, <end>) costs 4 HTTP calls total")
for t in ("5y", "10y", "30y"):
    enr[f"ccp_{t}_bp"] = float(bas[t].iloc[-1])
    enr[f"ccp_{t}_chg20d_bp"] = float(bas[t].iloc[-1] - bas[t].iloc[-21])
prov["ccp"] = (f"gs_quant LCH−CME USD SOFR, last print {bas.index[-1].date()}, "
               f"lagged {CFG.market_lag_bdays}bd when used as a signal")

print(pd.Series(enr).round(3).to_string())
print("\nprovenance:")
for k, v in prov.items():
    print(f"  {k}: {v}")

# %% [markdown]
# ## 5. The screen
#
# One row per structure. z-scores on the roll-spliced series (the raw CM level
# is also shown — it is the display quantity, the spliced one is the tradeable
# one). The fair-value block reports the BEST fly by levels-R² out of the
# structure's declared six, with its residual z and the residual's half-life —
# and prints the R² so nobody mistakes a rank for a relationship.

# %%
def half_life_bd(resid: pd.Series) -> float:
    r = resid.dropna()
    if len(r) < 60:
        return np.nan
    x, y = r.shift(1).iloc[1:], r.diff().iloc[1:]
    b = float(np.polyfit(x, y, 1)[0])
    return float(-np.log(2) / b) if b < 0 else np.inf


rows = []
labels = ([s.label for s in U.STRUCTURES]
          + ([f"SFR{i}" for i in range(1, 21)
              if f"SFR{i}" not in {s.label for s in U.STRUCTURES}]
             if CFG.show_all_ranks else []))
for lab in labels:
    raw_s, spl = ca_raw[lab], ca_spl[lab]
    z1y = (spl.iloc[-1] - spl.rolling(CFG.z_window).mean().iloc[-1]) / \
        spl.rolling(CFG.z_window).std(ddof=1).iloc[-1]
    z3m = (spl.iloc[-1] - spl.rolling(CFG.z_window_3m).mean().iloc[-1]) / \
        spl.rolling(CFG.z_window_3m).std(ddof=1).iloc[-1]
    row = {"structure": lab, "ca_bp": float(raw_s.iloc[-1]),
           "chg_1d_bp": float(spl.diff().iloc[-1]),
           "z_3m": float(z3m), "z_1y": float(z1y)}
    if lab in live_rows:
        row["ca_live_bp"] = live_rows[lab]["ca_live_bp"]
        row["live_minus_settle"] = row["ca_live_bp"] - row["ca_bp"]

    try:
        spec = U.structure_by_label(lab)
        best = None
        for f in U.flies_for(spec):
            fly = fly_hist[f.fly_id]
            both = pd.concat([spl.rename("ca"), fly.rename("fly")], axis=1).dropna()
            w = both.tail(CFG.fit_window)
            if len(w) < 120:
                continue
            r2 = float(w["ca"].corr(w["fly"]) ** 2)
            if best is None or r2 > best["fv_r2"]:
                beta = float(w["ca"].cov(w["fly"]) / w["fly"].var(ddof=1))
                alpha = float(w["ca"].mean() - beta * w["fly"].mean())
                resid = both["ca"] - alpha - beta * both["fly"]
                sd = float(resid.tail(CFG.fit_window).std(ddof=1))
                best = {"fv_fly": f.fly_id, "fv_r2": r2,
                        "fv_beta": beta,
                        "fv_resid_z": float(resid.iloc[-1] / sd) if sd > 0 else np.nan,
                        "fv_halflife_bd": half_life_bd(resid.tail(CFG.fit_window))}
        if best:
            row.update(best)
        # carry proxy: the screen's own 3m roll, (CA[r+3] − CA[r−1])/4
        r0, r1 = spec.ranks[0], spec.ranks[-1]
        if r0 >= 2 and f"SFR{r1}" in ca_raw and f"SFR{r0 - 1}" in ca_raw:
            row["roll_3m_bp"] = float(
                (ca_raw[f"SFR{r1}"].iloc[-1] - ca_raw[f"SFR{r0 - 1}"].iloc[-1]) / 4.0)
        # Ho-Lee inversion: implied bp/yr from the CA level
        t1s = [0.25 * (r + 1) for r in spec.ranks]
        m = float(np.mean([t * t for t in t1s]))
        ca_now = row["ca_bp"]
        row["implied_vol_bp"] = (float(np.sqrt(2 * ca_now / 1e4 / m) * 1e4)
                                 if ca_now > 0.1 else np.nan)
        rv = spl.diff().tail(CFG.z_window_3m).std(ddof=1) * np.sqrt(252)
        row["rlzd_vol_3m_bp"] = float(rv)
    except KeyError:
        pass
    rows.append(row)

SCREEN = pd.DataFrame(rows).set_index("structure")
for c in ("dealer_net_z", "ccp_5y_bp", "ccp_5y_chg20d_bp"):
    SCREEN[f"enr_{c}"] = enr.get(c, np.nan)
ORDER = ["ca_live_bp", "ca_bp", "live_minus_settle", "chg_1d_bp", "z_3m",
         "z_1y", "fv_fly", "fv_r2", "fv_beta", "fv_resid_z", "fv_halflife_bd",
         "roll_3m_bp", "implied_vol_bp", "rlzd_vol_3m_bp"]
SCREEN = SCREEN[[c for c in ORDER if c in SCREEN.columns]
                + [c for c in SCREEN.columns if c.startswith("enr_")]]
print(f"screen as of settle {LAST.date()}"
      + (f" + intraday {_instant}" if live_rows else " (settle only)"))
print(SCREEN.round(3).to_string())

# %%
flagged = SCREEN.loc[[s.label for s in U.STRUCTURES]].copy()
for m in ("z_1y", "fv_resid_z"):
    if m in flagged:
        top = flagged[m].abs().nlargest(3).index
        print(f"top 3 by |{m}|: {list(top)}  "
              f"({', '.join(f'{flagged.loc[t, m]:+.2f}' for t in top)})")
print(f"\nmax fair-value R² anywhere on the screen: "
      f"{float(SCREEN['fv_r2'].max()):.3f}")
print("Read that number for what it is: a LEVELS fit over one trailing year,")
print("which two trending series produce for free. The tradability question is")
print("answered by the backtest's changes-based measurement (max ΔCA-on-Δfly")
print("R² 0.386 anywhere, deep peaks 0.24–0.33) and by the 515-cell grid that")
print("cleared nothing — see cavf_backtest. The residual z columns here are")
print("monitoring context, not entries.")

# %% [markdown]
# ## 6. The pictures

# %%
ranks = [f"SFR{i}" for i in range(1, 21)]
term = pd.Series({i: settle_ca[f"SFR{i}"] for i in range(1, 21)})
fig = go.Figure()
fig.add_trace(go.Scatter(x=term.index, y=term.to_numpy(), mode="lines+markers",
                         name=f"outright CA, {LAST.date()}"))
for lab, rank in (("WHITES", 2.5), ("REDS", 6.5), ("GREENS", 10.5),
                  ("BLUES", 14.5), ("GOLDS", 18.5)):
    fig.add_trace(go.Scatter(x=[rank], y=[settle_ca[lab]], mode="markers+text",
                             text=[lab], textposition="top center",
                             marker={"size": 10}, showlegend=False))
fig.update_layout(title="CA term structure by rank — outrights, packs marked",
                  xaxis_title="quarterly rank", yaxis_title="bp", height=420)
fig.show()

# %%
fig = go.Figure()
for lab in COLOURS:
    fig.add_trace(go.Scatter(x=ca_raw[lab].index, y=ca_raw[lab].to_numpy(),
                             name=lab, mode="lines"))
fig.update_layout(title="Pack CA history (raw CM level, 2021–)",
                  yaxis_title="bp", height=430,
                  legend={"orientation": "h", "y": -0.15})
fig.show()

# %%
fig = go.Figure()
fig.add_trace(go.Scatter(x=bas.index, y=bas["5y"], name="CCP basis 5y (LCH−CME)"))
fig.add_trace(go.Scatter(x=bas.index, y=bas["10y"], name="10y"))
fig.add_trace(go.Scatter(x=bas.index, y=bas["30y"], name="30y"))
fig.update_layout(title="CME–LCH basis, USD SOFR — the margin wedge",
                  yaxis_title="bp", height=380,
                  legend={"orientation": "h", "y": -0.2})
fig.show()

dealer = build_positioning_panel(raw=raw, tenors=["SOFR3M"], metric="dealer_net")
fig = go.Figure(go.Scatter(x=dealer.index, y=dealer["SOFR3M"],
                           name="dealer net, SOFR-3M"))
fig.update_layout(title="CFTC TFF dealer net — SOFR-3M (release-lagged)",
                  yaxis_title="contracts", height=360)
fig.show()

# %% [markdown]
# ## 7. What this screen does not know
#
# * **Bid/offer.** Every level is a settle or a minute mark, not a tradeable
#   two-way; the backtest's per-leg cost model (0.25bp futures package, 0.5bp
#   swap, 0.5bp per fly leg) is the floor a signal must clear, and none did.
# * **Whether the mean is the attractor.** The fair-value R²s printed above
#   are the measurement; a z off an R² of 0.1 is a number, not a signal.
# * **The venue of the matched swap.** The CA here is measured against one
#   curve; the LCH−CME wedge is displayed, not netted into the level (the
#   Fig-58 tie-out passes at ~1bp without a venue correction).
# * **Why the CA moved.** Per Huggins & Schaller the SR3 contract has no
#   Jensen convexity of its own — the level is financing/margin bias plus
#   positioning, which is what the enrichment columns are for.

# %%
tb.close()
print("done")
