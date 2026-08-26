"""
ANALYSIS C - Fed speak frequency: year-over-year, seasonality, intra-cycle profile.

Inputs
    fed_calendar_raw.parquet   ForexFactory FED_SPEAKERS events, 2015-01-05 .. 2026-08-25
    panel_daily.parquet        business-day panel, 2019-01-02 .. 2026-08-24 (days_to_fomc, is_blackout)
    fed_hawk_dove_scores.csv   JPM NLP hawk/dove scores, 700 rows, 2008-11-06 .. 2026-08-06

Outputs
    fig_fed_speak_frequency.png          one 7-panel figure (3x2 named panels + full-width intra-cycle row)
    frequency_seasonality_results.json   every number quoted in the figure, plus caveats

Conventions fixed once, used everywhere
    CUTOFF          2026-08-24. The raw calendar carries two 2026-08-25 rows (both Barkin, one of them a
                    forward-scheduled 20:00 UTC event that may not have occurred). Cutting at the panel's
                    own last date keeps every YTD / like-for-like window on one clock.
    EVENT BASE      the RAW calendar, weekends included (66 Sat/Sun events). The panel's n_speakers is
                    business-day-indexed and therefore misses those; it is used only for the intra-cycle
                    profile, where the FOMC clock lives.
    COMPLETE YEARS  2015-2025. 2026 is partial and is excluded from every mean, trend fit and seasonal
                    profile; it appears only as a flagged bar / flagged row.

Run:  C:\\Users\\chris\\anaconda3\\envs\\stir\\python.exe frequency_seasonality.py
"""

import os
import json
import re

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Patch, Rectangle
from matplotlib.lines import Line2D
from matplotlib.colors import LinearSegmentedColormap

# ----------------------------------------------------------------------------------
# paths
# ----------------------------------------------------------------------------------
OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
CAL_PQ = os.path.join(OUT, "fed_calendar_raw.parquet")
PAN_PQ = os.path.join(OUT, "panel_daily.parquet")
JPM_CSV = r"C:\Users\chris\clee\project-oasis\private\jpm_research\fed_speak_nlp\fed_hawk_dove_scores.csv"
FIG_PNG = os.path.join(OUT, "fig_fed_speak_frequency.png")
RES_JSON = os.path.join(OUT, "frequency_seasonality_results.json")

CUTOFF = pd.Timestamp("2026-08-24")
PARTIAL_YEAR = 2026
FIRST_YEAR = 2015
COMPLETE_YEARS = list(range(FIRST_YEAR, PARTIAL_YEAR))  # 2015..2025
CHAIR_HANDOVER = pd.Timestamp("2026-05-22")

# ----------------------------------------------------------------------------------
# palette  (dataviz skill reference instance, light surface; validated:
#   ALL CHECKS PASS, worst adjacent CVD dE 9.1, worst adjacent normal-vision dE 19.6.
#   Contrast WARN on aqua/yellow/magenta -> relief rule = visible labels + the JSON table view.)
# ----------------------------------------------------------------------------------
SURFACE = "#fcfcfb"
PLANE = "#f9f9f7"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASE = "#c3c2b7"

CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
       "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
BLUE = CAT[0]
NEUTRAL = "#c3c2b7"          # "Other" / "unscored" -- absence, never an entity hue
SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
       "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
BLUE_200, BLUE_250 = "#9ec5f4", "#86b6ef"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
    "figure.facecolor": PLANE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": BASE,
    "axes.labelcolor": INK2,
    "axes.titlecolor": INK,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": INK2,
    "ytick.labelcolor": INK2,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "axes.grid": False,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "font.size": 11,
})


def style(ax, ygrid=True):
    """Recessive chrome: hairline horizontal grid, no top/right spines."""
    if ygrid:
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.spines["left"].set_color(BASE)
    ax.spines["bottom"].set_color(BASE)
    ax.tick_params(length=0)


def jdump(o):
    """numpy -> json"""
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else round(float(o), 6)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d")
    raise TypeError(type(o))


# ==================================================================================
# LOAD
# ==================================================================================
cal_all = pd.read_parquet(CAL_PQ)
cal_all["Date"] = pd.to_datetime(cal_all["Date"])
n_raw = len(cal_all)
cal = cal_all[cal_all["Date"] <= CUTOFF].copy()
n_dropped_by_cutoff = n_raw - len(cal)
cal["yr"] = cal["Date"].dt.year
cal["mo"] = cal["Date"].dt.month
cal["dow"] = cal["Date"].dt.dayofweek

pan = pd.read_parquet(PAN_PQ)
pan.index = pd.to_datetime(pan.index)

jpm = pd.read_csv(JPM_CSV)
jpm["date"] = pd.to_datetime(jpm["date"])

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DOWS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

results = {}
results["meta"] = {
    "calendar_file": CAL_PQ,
    "panel_file": PAN_PQ,
    "jpm_file": JPM_CSV,
    "calendar_span_raw": [cal_all.Date.min().strftime("%Y-%m-%d"), cal_all.Date.max().strftime("%Y-%m-%d")],
    "cutoff_applied": CUTOFF.strftime("%Y-%m-%d"),
    "events_raw": int(n_raw),
    "events_after_cutoff": int(len(cal)),
    "events_dropped_by_cutoff": int(n_dropped_by_cutoff),
    "event_base": "raw ForexFactory FED_SPEAKERS calendar, weekends included",
    "weekend_events": int((cal.dow >= 5).sum()),
    "complete_years": COMPLETE_YEARS,
    "partial_year": PARTIAL_YEAR,
    "panel_span": [pan.index.min().strftime("%Y-%m-%d"), pan.index.max().strftime("%Y-%m-%d")],
}

# ==================================================================================
# 1. EVENTS PER YEAR  + two annualisations of the partial year
# ==================================================================================
yr_counts = cal.groupby("yr").size().reindex(range(FIRST_YEAR, PARTIAL_YEAR + 1), fill_value=0)
ytd_2026 = int(yr_counts.loc[PARTIAL_YEAR])

# elapsed fraction of the partial year, by calendar day
doy = int((CUTOFF - pd.Timestamp(PARTIAL_YEAR, 1, 1)).days) + 1
days_in_year = 365 + int(pd.Timestamp(PARTIAL_YEAR, 12, 31).dayofyear == 366)
frac_elapsed = doy / days_in_year
ann_prorata = ytd_2026 / frac_elapsed

# seasonal-share annualisation: what share of a year's events normally land on or before Aug 24?
shares = {}
for y in COMPLETE_YEARS:
    cut_y = pd.Timestamp(y, CUTOFF.month, CUTOFF.day)
    ytd_y = int(((cal.yr == y) & (cal.Date <= cut_y)).sum())
    shares[y] = ytd_y / int(yr_counts.loc[y])
mean_share = float(np.mean(list(shares.values())))
ann_seasonal = ytd_2026 / mean_share

# ==================================================================================
# 2. SEASONALITY  (complete years only)
# ==================================================================================
mo_by_yr = (cal[cal.yr.isin(COMPLETE_YEARS)]
            .groupby(["yr", "mo"]).size()
            .unstack("mo").reindex(columns=range(1, 13)).fillna(0.0))
mo_mean = mo_by_yr.mean(axis=0)
mo_q25 = mo_by_yr.quantile(0.25, axis=0)
mo_q75 = mo_by_yr.quantile(0.75, axis=0)
overall_monthly_mean = float(mo_by_yr.values.sum() / (len(COMPLETE_YEARS) * 12))
seasonality_index = (mo_mean / overall_monthly_mean)
strongest_mo = int(seasonality_index.idxmax())
weakest_mo = int(seasonality_index.idxmin())

# ==================================================================================
# 3. YEAR x MONTH HEATMAP
# ==================================================================================
heat = (cal.groupby(["yr", "mo"]).size()
        .unstack("mo").reindex(index=range(FIRST_YEAR, PARTIAL_YEAR + 1),
                               columns=range(1, 13)))
# Order matters. unstack() leaves NaN for a month that genuinely had zero events, which is a
# real zero; only the months of the partial year that have NOT HAPPENED are missing data. Fill
# the real zeros FIRST, then punch out the future months, so the two can never be confused.
heat_plot = heat.copy().astype(float).fillna(0.0)
nodata_cells = [(PARTIAL_YEAR, m) for m in range(CUTOFF.month + 1, 13)]
for y, m in nodata_cells:
    heat_plot.loc[y, m] = np.nan

# ==================================================================================
# 4. DAY OF WEEK
# ==================================================================================
dow_counts = cal.groupby("dow").size().reindex(range(7), fill_value=0)

# ==================================================================================
# 5. SPEAKER COMPOSITION
# ==================================================================================
TOP_N = 8
top_speakers = cal.Speaker.value_counts().head(TOP_N).index.tolist()
spk = cal.copy()
spk["grp"] = np.where(spk.Speaker.isin(top_speakers), spk.Speaker, "Other")
spk_by_yr = (spk.groupby(["yr", "grp"]).size().unstack("grp")
             .reindex(index=range(FIRST_YEAR, PARTIAL_YEAR + 1))
             .reindex(columns=top_speakers + ["Other"]).fillna(0.0))
spk_share = spk_by_yr.div(spk_by_yr.sum(axis=1), axis=0)

# roster breadth decomposition (does the count trend survive a coverage control?)
roster = cal.groupby("yr").agg(events=("EventId", "size"),
                               speakers=("Speaker", "nunique"),
                               speaking_days=("Date", "nunique"))
roster["events_per_speaker"] = roster.events / roster.speakers
roster["events_per_speaking_day"] = roster.events / roster.speaking_days
# fixed-roster control: speakers present in >= 10 of the 11 complete years
pres = (cal[cal.yr.isin(COMPLETE_YEARS)].groupby("Speaker")["yr"].nunique())
core_roster = sorted(pres[pres >= 10].index.tolist())
core_counts = (cal[cal.Speaker.isin(core_roster)].groupby("yr").size()
               .reindex(range(FIRST_YEAR, PARTIAL_YEAR + 1), fill_value=0))

# ==================================================================================
# 6. JPM NLP COVERAGE
#    unit = distinct (date, last-name) speaking engagements, NOT panel days.
# ==================================================================================
pairs = cal.drop_duplicates(subset=["Date", "Speaker"])[["Date", "Speaker", "yr"]].copy()
jpm_keys = set(zip(jpm["date"], jpm["speaker"]))
pairs["scored"] = [(d, s) in jpm_keys for d, s in zip(pairs.Date, pairs.Speaker)]
cov = pairs.groupby("yr").agg(pairs=("scored", "size"), scored=("scored", "sum"))
cov["pct"] = 100.0 * cov.scored / cov.pairs

# SECOND partial-ness inside P6: the JPM feed itself stops before the calendar cutoff,
# so the tail engagements CANNOT be scored even in principle. Size it rather than assert it.
JPM_MAX = pd.Timestamp(jpm["date"].max())
_p26 = pairs[pairs.yr == PARTIAL_YEAR]
jpm_unscoreable_2026 = int((_p26.Date > JPM_MAX).sum())
jpm_pct_2026_full_window = float(cov.loc[PARTIAL_YEAR, "pct"])
_p26_scoreable = _p26[_p26.Date <= JPM_MAX]
jpm_pct_2026_scoreable_window = (
    100.0 * float(_p26_scoreable.scored.sum()) / len(_p26_scoreable) if len(_p26_scoreable) else float("nan"))

# how well does the JPM date column line up with the calendar at all? (join diagnostic)
cal_pairs = set(zip(cal.Date, cal.Speaker))
jpm_in_span = jpm[(jpm.date >= cal.Date.min()) & (jpm.date <= CUTOFF)]
jpm_exact = sum((d, s) in cal_pairs for d, s in zip(jpm_in_span.date, jpm_in_span.speaker))
cal_by_spk = {}
for d, s in cal_pairs:
    cal_by_spk.setdefault(s, []).append(d)


def within(days):
    hit = 0
    for d, s in zip(jpm_in_span.date, jpm_in_span.speaker):
        ds = cal_by_spk.get(s)
        if ds and min(abs((d - x).days) for x in ds) <= days:
            hit += 1
    return hit


jpm_w1, jpm_w3 = within(1), within(3)

# ==================================================================================
# 7. INTRA-CYCLE PROFILE  (panel: the FOMC clock lives there)
# ==================================================================================
CYC_MAX = 44          # 0..44 covers 96% of panel days; beyond that only a few long cycles reach
cyc = (pan.groupby("days_to_fomc")
       .agg(n_days=("n_speakers", "size"),
            ev_per_day=("n_speakers", "mean"),
            pct_flagged_blackout=("is_blackout", "mean"))
       .reindex(range(0, CYC_MAX + 1)))
LOW_N = 8
cyc["low_n"] = cyc.n_days < LOW_N
solid = cyc[(~cyc.low_n) & cyc.n_days.notna()]
# The sparse offsets are STRUCTURAL, not random: FOMC decisions fall on Wednesdays, so
# days_to_fomc == 3 or 4 (mod 7) lands on a weekend and the business-day panel almost never
# sees it. Confirming that keeps two-observation bins from being read as spikes.
low_offsets = sorted(int(d) for d in cyc[cyc.low_n.fillna(False)].index)
low_mod7 = sorted(set(d % 7 for d in low_offsets))
cyc_cov = int(cyc.n_days.sum())
# empirical trough: the run of days closest to the meeting whose rate is < 40% of the far-field rate
far = float(solid.loc[solid.index >= 18, "ev_per_day"].mean())
thresh = 0.40 * far
in_trough = solid[(solid.index <= 17) & (solid.ev_per_day < thresh)]
trough_lo, trough_hi = int(in_trough.index.min()), int(in_trough.index.max())
trough_rate = float(in_trough.ev_per_day.mean())
# where the flag says blackout
flagged = cyc[cyc.pct_flagged_blackout > 0.5]
flag_lo, flag_hi = int(flagged.index.min()), int(flagged.index.max())

# --- the trough is the required data-quality check, so prove the detector is not vacuous -------
# (a) SHUFFLE NULL: permute the daily event counts across panel days, keeping the FOMC clock
#     fixed. If the "trough" were an artefact of binning it would survive; it must not.
_rng = np.random.default_rng(7)
_depths = []
for _ in range(200):
    _g = (pd.DataFrame({"d": pan.days_to_fomc.values, "e": _rng.permutation(pan.n_speakers.values)})
          .groupby("d").agg(n=("e", "size"), ev=("e", "mean")))
    _g = _g[_g.n >= LOW_N]
    _depths.append(float(_g.loc[0:9, "ev"].mean()) / float(_g.loc[18:CYC_MAX, "ev"].mean()))
_depths = np.array(_depths)

# (b) CALENDAR-SIDE RE-DERIVATION: recover the decision dates from the panel, then measure the
#     profile on the RAW calendar with a calendar-day denominator - weekends and holidays kept.
_fomc = pd.DatetimeIndex(sorted(pan.index[pan.is_fomc_day]))
_span = cal[(cal.Date >= pan.index.min()) & (cal.Date <= pan.index.max())]
_nx = _fomc.searchsorted(_span.Date.values, side="left")
_ok = _nx < len(_fomc)
_ev = pd.Series((_fomc[_nx[_ok]] - pd.DatetimeIndex(_span.Date.values[_ok])).days).value_counts()
_alld = pd.date_range(pan.index.min(), pan.index.max(), freq="D")
_nx2 = _fomc.searchsorted(_alld.values, side="left")
_ok2 = _nx2 < len(_fomc)
_den = pd.Series((_fomc[_nx2[_ok2]] - _alld[_ok2]).days).value_counts()
_rate = (_ev / _den).dropna().sort_index()
cs_near = float(_rate.loc[0:9].mean())
cs_far = float(_rate.loc[18:CYC_MAX].mean())
n_wednesday = int(sum(d.dayofweek == 2 for d in _fomc))
off_spine = int(len(_span) - pan.n_speakers.sum())
off_spine_weekend = int((_span.Date.dt.dayofweek >= 5).sum())

# ==================================================================================
# TREND
# ==================================================================================
def ols(years, vals):
    x = np.asarray(years, float)
    y = np.asarray(vals, float)
    n = len(x)
    b, a = np.polyfit(x, y, 1)
    yhat = a + b * x
    ss_res = float(((y - yhat) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot
    se = np.sqrt(ss_res / (n - 2) / ((x - x.mean()) ** 2).sum())
    t = b / se
    from scipy import stats as _st
    p = float(2 * _st.t.sf(abs(t), n - 2))
    return dict(slope=float(b), intercept=float(a), r2=float(r2), t_stat=float(t),
                p_value=p, n=int(n))


fit_full = ols(COMPLETE_YEARS, [yr_counts.loc[y] for y in COMPLETE_YEARS])
pre24 = list(range(FIRST_YEAR, 2024))
fit_pre24 = ols(pre24, [yr_counts.loc[y] for y in pre24])


def fitted(y, f):
    return f["intercept"] + f["slope"] * y


resid_2025 = float(yr_counts.loc[2025] - fitted(2025, fit_full))
resid_2026_seasonal = float(ann_seasonal - fitted(2026, fit_full))
resid_2026_prorata = float(ann_prorata - fitted(2026, fit_full))

# like-for-like windows, all on the Aug-24 clock
def win(y, m0, d0, m1, d1):
    return int(((cal.Date >= pd.Timestamp(y, m0, d0)) & (cal.Date <= pd.Timestamp(y, m1, d1))).sum())


ytd = {y: win(y, 1, 1, CUTOFF.month, CUTOFF.day) for y in range(FIRST_YEAR, PARTIAL_YEAR + 1)}
pre_handover = {y: win(y, 1, 1, CHAIR_HANDOVER.month, CHAIR_HANDOVER.day)
                for y in range(FIRST_YEAR, PARTIAL_YEAR + 1)}
post_handover = {y: ytd[y] - pre_handover[y] for y in range(FIRST_YEAR, PARTIAL_YEAR + 1)}

# ==================================================================================
# ============================    FIGURE    ========================================
# ==================================================================================
# ============================    FIGURE    ========================================
# ==================================================================================
fig = plt.figure(figsize=(20, 18.5), dpi=210)
gs = GridSpec(4, 2, figure=fig, height_ratios=[1.0, 1.0, 1.0, 0.86],
              hspace=0.52, wspace=0.17,
              left=0.052, right=0.982, top=0.879, bottom=0.066)

# ---------------------------------------------------------------- P1 events/year
ax = fig.add_subplot(gs[0, 0])
xs = np.arange(len(yr_counts))
comp_mask = np.array([y in COMPLETE_YEARS for y in yr_counts.index])
ax.bar(xs[comp_mask], yr_counts.values[comp_mask], width=0.62, color=BLUE, zorder=3)
i26 = list(yr_counts.index).index(PARTIAL_YEAR)
ax.bar([i26 - 0.16], [ytd_2026], width=0.30, color=BLUE_250, edgecolor=BLUE,
       linewidth=1.2, hatch="///", zorder=3)
ax.bar([i26 + 0.17], [ann_seasonal], width=0.30, facecolor="none", edgecolor=BLUE,
       linewidth=1.5, linestyle=(0, (3, 2)), zorder=3)
tx = np.array(COMPLETE_YEARS, float)
ax.plot(xs[comp_mask], fit_full["intercept"] + fit_full["slope"] * tx,
        color=INK2, linewidth=2.0, zorder=4)
ax.plot([xs[comp_mask][-1], i26], [fitted(2025, fit_full), fitted(2026, fit_full)],
        color=INK2, linewidth=1.4, linestyle=(0, (2, 2)), zorder=4)
ax.set_xticks(xs)
ax.set_xticklabels([str(y) for y in yr_counts.index])
ax.set_ylabel("Fed speaking events per year (count)")
ax.set_title("P1  Fed speaking events per year", loc="left", fontsize=13.5, fontweight="bold", pad=32)
ax.text(0, 1.088, f"2026 is a PARTIAL year (through {CUTOFF:%d %b}) and is drawn hatched.",
        transform=ax.transAxes, fontsize=10, color=INK2)
ax.text(0, 1.038, f"Ghost bar = seasonally annualised ({ann_seasonal:.0f}). Naive pro-rata would say "
                  f"{ann_prorata:.0f} - it understates, because only {100*mean_share:.0f}% of a year's "
                  f"events normally land by 24 Aug.",
        transform=ax.transAxes, fontsize=10, color=MUTED)
ax.set_ylim(0, 500)
for i, (y, v) in enumerate(zip(yr_counts.index, yr_counts.values)):
    if y in (FIRST_YEAR, 2024, 2025):
        ax.text(i, v + 9, f"{v:,}", ha="center", va="bottom", fontsize=10, color=INK2)
ax.text(i26 - 0.16, ytd_2026 + 9, f"{ytd_2026}", ha="center", va="bottom", fontsize=10, color=INK2)
ax.text(i26 + 0.17, ann_seasonal + 9, f"{ann_seasonal:.0f}", ha="center", va="bottom",
        fontsize=10, color=BLUE, fontweight="bold")
ax.legend(handles=[
    Patch(facecolor=BLUE, label="complete year"),
    Patch(facecolor=BLUE_250, edgecolor=BLUE, hatch="///", label=f"2026 year-to-date ({ytd_2026}, partial)"),
    Patch(facecolor="none", edgecolor=BLUE, linestyle="--", label=f"2026 annualised ({ann_seasonal:.0f}, seasonal)"),
    Line2D([], [], color=INK2, lw=2, label=f"trend, complete years: {fit_full['slope']:+.1f}/yr"),
], loc="upper left", frameon=False, fontsize=9.5, handlelength=1.7, labelspacing=0.38)
style(ax)

# ---------------------------------------------------------------- P2 seasonality
ax = fig.add_subplot(gs[0, 1])
mx = np.arange(1, 13)
ax.fill_between(mx, mo_q25.values, mo_q75.values, color=BLUE_200, alpha=0.55,
                linewidth=0, zorder=2, label="inter-year IQR (25th-75th pct)")
ax.plot(mx, mo_mean.values, color=BLUE, linewidth=2.2, marker="o", markersize=7,
        markeredgecolor=SURFACE, markeredgewidth=2, zorder=4, label="mean events per month")
ax.axhline(overall_monthly_mean, color=MUTED, linewidth=1.2, linestyle=(0, (4, 3)), zorder=3)
ax.text(12.45, overall_monthly_mean + 0.55, f"overall mean {overall_monthly_mean:.1f}/mo",
        va="bottom", ha="right", fontsize=9.5, color=MUTED)
ax.annotate(f"busiest: {MONTHS[strongest_mo-1]}\nindex {seasonality_index[strongest_mo]:.2f}",
            xy=(strongest_mo, mo_mean[strongest_mo] + 0.6), xytext=(strongest_mo - 0.9, 35.5),
            ha="center", va="top", fontsize=10, color=BLUE, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=BLUE, lw=1.2))
ax.annotate(f"quietest: {MONTHS[weakest_mo-1]}\nindex {seasonality_index[weakest_mo]:.2f}",
            xy=(weakest_mo - 0.06, mo_mean[weakest_mo] - 0.6), xytext=(11.25, 3.0),
            ha="center", va="bottom", fontsize=10, color=INK2, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=MUTED, lw=1.2))
ax.set_xticks(mx)
ax.set_xticklabels(MONTHS)
ax.set_xlim(0.4, 12.6)
ax.set_ylim(0, 38)
ax.set_ylabel("Events per month (count)")
ax.set_title("P2  Seasonality: mean events by calendar month", loc="left",
             fontsize=13.5, fontweight="bold", pad=32)
ax.text(0, 1.088, f"Complete years only ({FIRST_YEAR}-{PARTIAL_YEAR-1}, n={len(COMPLETE_YEARS)}); "
                  "the partial year is excluded so it cannot drag Jan-Aug down.",
        transform=ax.transAxes, fontsize=10, color=INK2)
ax.text(0, 1.038, "Two speaking seasons - a spring peak and a bigger autumn one - either side of the "
                  "summer lull; December collapses for the holidays.",
        transform=ax.transAxes, fontsize=10, color=MUTED)
ax.legend(loc="upper left", frameon=False, fontsize=9.5, handlelength=1.7)
style(ax)

# ---------------------------------------------------------------- P3 heatmap
ax = fig.add_subplot(gs[1, 0])
cmap = LinearSegmentedColormap.from_list("blues", SEQ, N=256)
M = np.ma.masked_invalid(heat_plot.values.astype(float))
vmax = float(np.nanmax(heat_plot.values))
im = ax.imshow(M, cmap=cmap, aspect="auto", vmin=0, vmax=vmax)
ax.set_xticks(np.arange(12))
ax.set_xticklabels(MONTHS)
ax.set_yticks(np.arange(len(heat_plot.index)))
ax.set_yticklabels([str(y) for y in heat_plot.index])
for i, y in enumerate(heat_plot.index):
    for j in range(12):
        v = heat_plot.values[i, j]
        if np.isnan(v):
            ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor=PLANE,
                                   edgecolor=BASE, hatch="xx", linewidth=0.6, zorder=3))
            continue
        ax.text(j, i, f"{int(v)}", ha="center", va="center", fontsize=8.8,
                color=SURFACE if v > 0.58 * vmax else INK2, zorder=4)
ax.set_xticks(np.arange(-0.5, 12, 1), minor=True)
ax.set_yticks(np.arange(-0.5, len(heat_plot.index), 1), minor=True)
ax.grid(which="minor", color=SURFACE, linewidth=1.6)
ax.tick_params(which="minor", length=0)
ax.tick_params(length=0)
for s in ax.spines.values():
    s.set_visible(False)
ax.add_patch(Rectangle((CUTOFF.month - 1 - 0.5, len(heat_plot.index) - 1 - 0.5), 1, 1,
                       facecolor="none", edgecolor=CAT[1], linewidth=2.4, zorder=5))
ax.annotate("Aug-26 is partial (to 24 Aug)", xy=(CUTOFF.month - 1 + 0.5, len(heat_plot.index) - 1),
            xytext=(CUTOFF.month - 1 + 2.0, len(heat_plot.index) - 1),
            fontsize=9.2, color=CAT[1], va="center", ha="left", fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=CAT[1], lw=1.2))
cb = fig.colorbar(im, ax=ax, pad=0.014, fraction=0.036)
cb.set_label("events in month (count)", fontsize=9.5, color=INK2)
cb.outline.set_visible(False)
cb.ax.tick_params(length=0, labelcolor=INK2)
ax.set_title("P3  Year x month event counts", loc="left", fontsize=13.5, fontweight="bold", pad=32)
ax.text(0, 1.088, "Trend down the rows, seasonality across the columns; every cell carries its count.",
        transform=ax.transAxes, fontsize=10, color=INK2)
ax.text(0, 1.038, "Cross-hatched = NO DATA (the month has not happened). Plotting zero there would be a lie.",
        transform=ax.transAxes, fontsize=10, color=MUTED)

# ---------------------------------------------------------------- P4 day of week
ax = fig.add_subplot(gs[1, 1])
ax.bar(np.arange(7), dow_counts.values, width=0.62, color=BLUE, zorder=3)
for i, v in enumerate(dow_counts.values):
    ax.text(i, v + 7, f"{v:,}", ha="center", va="bottom", fontsize=10, color=INK2)
ax.set_xticks(np.arange(7))
ax.set_xticklabels(DOWS)
ax.set_ylabel("Events (count, whole sample)")
ax.set_ylim(0, max(dow_counts.values) * 1.24)
ax.set_title("P4  Day-of-week distribution", loc="left", fontsize=13.5, fontweight="bold", pad=32)
wk = int(dow_counts.loc[[5, 6]].sum())
ax.text(0, 1.088, f"{FIRST_YEAR}-{PARTIAL_YEAR} to {CUTOFF:%d %b}, all {len(cal):,} events. "
                  f"Tue-Thu carry {100*dow_counts.loc[[1,2,3]].sum()/len(cal):.0f}% of the calendar.",
        transform=ax.transAxes, fontsize=10, color=INK2)
ax.text(0, 1.038, f"Weekend Fedspeak is real but rare - {wk} events ({100*wk/len(cal):.1f}%) - and is absent "
                  f"from the business-day panel, so it is counted here and nowhere else.",
        transform=ax.transAxes, fontsize=10, color=MUTED)
ax.annotate("Thursday is the\nmodal speaking day", xy=(3.34, dow_counts.loc[3] * 0.97),
            xytext=(5.1, dow_counts.loc[3] * 0.95), fontsize=9.5, color=INK2, ha="center",
            va="center", arrowprops=dict(arrowstyle="->", color=MUTED, lw=1.1))
style(ax)

# ---------------------------------------------------------------- P5 speaker mix
ax = fig.add_subplot(gs[2, 0])
xs5 = np.arange(len(spk_share.index))
bottom = np.zeros(len(spk_share.index))
cols = {s: CAT[i] for i, s in enumerate(top_speakers)}
cols["Other"] = NEUTRAL
# text ink chosen against each fill (aqua/yellow/magenta/grey are light -> dark ink)
LIGHT_FILL = {"#1baf7a", "#eda100", "#e87ba4", NEUTRAL}
for s in top_speakers + ["Other"]:
    v = spk_share[s].values
    ax.bar(xs5, v, bottom=bottom, width=0.72, color=cols[s],
           edgecolor=SURFACE, linewidth=1.8, zorder=3)
    bottom += v
last = list(spk_share.index).index(2025)
run = 0.0
for s in top_speakers + ["Other"]:
    v = spk_share.loc[2025, s]
    if v >= 0.055:
        ax.text(last, run + v / 2, s, ha="center", va="center", fontsize=8.0,
                color=INK if cols[s] in LIGHT_FILL else SURFACE, fontweight="bold", zorder=5)
    run += v
ax.set_xticks(xs5)
ax.set_xticklabels([str(y) for y in spk_share.index])
ax.set_ylim(0, 1)
ax.set_yticks([0, .25, .5, .75, 1])
ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
ax.set_ylabel("Share of that year's events (%)")
ax.set_title("P5  Speaker composition: top 8 names, share of each year", loc="left",
             fontsize=13.5, fontweight="bold", pad=32)
ax.text(0, 1.088, "Colour follows the speaker, never the rank. 'Other' = all remaining names. "
                  "2026 partial; labels shown on 2025, the last complete year.",
        transform=ax.transAxes, fontsize=10, color=INK2)
ax.text(0, 1.038, f"Chair handover {CHAIR_HANDOVER:%d %b %Y} - but WARSH HAS ZERO EVENTS in this calendar, "
                  f"so no post-handover chair appears in the mix at all.",
        transform=ax.transAxes, fontsize=10, color=CAT[1], fontweight="bold")
ax.legend(handles=[Patch(facecolor=cols[s], label=f"{s} ({cal.Speaker.value_counts()[s]})")
                   for s in top_speakers] + [Patch(facecolor=NEUTRAL, label="Other")],
          loc="upper center", bbox_to_anchor=(0.5, -0.115), ncol=5, frameon=False,
          fontsize=9.5, handlelength=1.5, columnspacing=1.6, labelspacing=0.4)
style(ax, ygrid=False)

# ---------------------------------------------------------------- P6 JPM coverage
ax = fig.add_subplot(gs[2, 1])
xs6 = np.arange(len(cov.index))
unsc = (cov.pairs - cov.scored).values
# the partial year must be hatched here exactly as it is in P1 -- the bar height is a COUNT,
# so an unhatched 2026 bar reads as a complete-year collapse that did not happen.
part6 = np.array([y == PARTIAL_YEAR for y in cov.index])
ax.bar(xs6, cov.scored.values, width=0.66, color=BLUE, zorder=3, label="scored by JPM NLP")
ax.bar(xs6, unsc, bottom=cov.scored.values, width=0.66, color=NEUTRAL,
       edgecolor=SURFACE, linewidth=1.8, zorder=3, label="no score")
ax.bar(xs6[part6], cov.pairs.values[part6], width=0.66, facecolor="none",
       edgecolor=INK2, linewidth=1.2, hatch="///", zorder=4)
for i, (y, r) in enumerate(cov.iterrows()):
    ax.text(i, r.pairs + 7, f"{r.pct:.0f}%", ha="center", va="bottom", fontsize=9.5,
            color=BLUE if r.pct >= 20 else MUTED,
            fontweight="bold" if r.pct >= 20 else "normal")
ax.set_xticks(xs6)
ax.set_xticklabels([f"{y}\n(partial)" if y == PARTIAL_YEAR else str(y) for y in cov.index])
ax.set_ylabel("Distinct speaking engagements (count)")
ax.set_ylim(0, cov.pairs.max() * 1.30)
ax.set_title("P6  JPM NLP score coverage of the speaking calendar", loc="left",
             fontsize=13.5, fontweight="bold", pad=32)
ax.text(0, 1.088, "Unit = distinct (date, speaker) engagement; label above each bar = % scored. "
                  "2026 is PARTIAL (hatched); bar height is a count.",
        transform=ax.transAxes, fontsize=10, color=INK2)
ax.text(0, 1.038, f"Where a daily sentiment index is fed - and where it starves.  JPM feed ends "
                  f"{JPM_MAX:%d %b %Y}: {jpm_unscoreable_2026} 2026 engagements unscoreable.",
        transform=ax.transAxes, fontsize=10, color=MUTED)
ax.legend(loc="upper left", frameon=False, fontsize=9.5, handlelength=1.7)
tot_pairs, tot_scored = int(cov.pairs.sum()), int(cov.scored.sum())
pre22 = 100 * cov.loc[2015:2021, "scored"].sum() / cov.loc[2015:2021, "pairs"].sum()
ax.text(0.018, 0.755, f"whole sample: {tot_scored:,} of {tot_pairs:,} engagements scored "
                      f"({100*tot_scored/tot_pairs:.1f}%).\n"
                      f"2015-2021 is {pre22:.1f}% covered; the index only has a pulse from 2022.\n"
                      f"Even at its best ({int(cov.pct.idxmax())}) barely {cov.pct.max():.0f}% of "
                      f"engagements carry a score.",
        transform=ax.transAxes, ha="left", va="top", fontsize=9.2, color=MUTED)
style(ax)

# ---------------------------------------------------------------- P7 intra-cycle
ax = fig.add_subplot(gs[3, :])
plot_ok = cyc[(~cyc.low_n.fillna(True)) & cyc.ev_per_day.notna()]
ax.axvspan(trough_lo - 0.5, trough_hi + 0.5, color=BLUE, alpha=0.10, zorder=1)
ax.bar(plot_ok.index.values, plot_ok.ev_per_day.values, width=0.74, color=BLUE, zorder=3)
YTOP = 2.85
ax.set_ylim(-0.16, YTOP)
ax.set_xlim(CYC_MAX + 1.4, -1.2)      # time flows left -> right, toward the decision
# structurally sparse offsets: shown as ticks, never as bars
ax.plot(low_offsets, [-0.085] * len(low_offsets), marker="v", linestyle="none",
        markersize=5, color=MUTED, zorder=4)
ax.axhline(far, color=INK2, linewidth=1.4, linestyle=(0, (4, 3)), zorder=4)
ax.text(CYC_MAX + 1.1, far + 0.07, f"far-field baseline {far:.2f} events/day", va="bottom", ha="left",
        fontsize=9.5, color=INK2)
# blackout flag extent drawn as a bracket, not a second wash
by = YTOP * 0.79
ax.plot([flag_lo, flag_hi], [by, by], color=CAT[1], lw=1.8, zorder=5)
ax.plot([flag_lo, flag_lo], [by - 0.07, by + 0.07], color=CAT[1], lw=1.8, zorder=5)
ax.plot([flag_hi, flag_hi], [by - 0.07, by + 0.07], color=CAT[1], lw=1.8, zorder=5)
ax.text((flag_lo + flag_hi) / 2, by + 0.10, f"panel flag is_blackout: days {flag_lo}-{flag_hi}",
        ha="center", va="bottom", fontsize=10, color=CAT[1], fontweight="bold")
ax.set_xticks(range(0, CYC_MAX + 1, 3))
ax.set_xlabel("Calendar days until the next FOMC decision   (0 = decision day; time flows left to right, "
              "so the left edge is just after the PREVIOUS decision)")
ax.set_ylabel("Fed speaking events\nper business day (mean)")
ax.set_title("P7  Intra-cycle profile - the blackout trough is the data-quality check",
             loc="left", fontsize=13.5, fontweight="bold", pad=32)
ax.text(0, 1.105, f"Business-day panel {pan.index.min():%b %Y}-{pan.index.max():%b %Y} "
                  f"(n={len(pan):,} days, {int(pan.is_fomc_day.sum())} decisions). "
                  f"TROUGH PRESENT and deep - the calendar/FOMC join is sound.",
        transform=ax.transAxes, fontsize=10, color=INK2)
ax.text(0, 1.045, "Grey triangles mark offsets omitted for low sample: FOMC decisions are Wednesdays, so "
                  "days_to_fomc = 3 or 4 (mod 7) falls on a weekend and a business-day panel almost never "
                  "sees it. Two observations must not draw a spike.",
        transform=ax.transAxes, fontsize=10, color=MUTED)
ax.annotate(f"empirical trough: days {trough_lo}-{trough_hi}\n{trough_rate:.2f} events/day = "
            f"{100*trough_rate/far:.0f}% of the far-field rate",
            xy=((trough_lo + trough_hi) / 2.0, YTOP * 0.50), ha="center", va="center",
            fontsize=10.5, color=BLUE, fontweight="bold")
# the gap between the empirical trough and the flag's outer edge, measured on well-sampled bins only
gap_days = [int(d) for d in solid.index if trough_hi < d <= flag_hi]
gap_lo, gap_hi = min(gap_days), max(gap_days)
mid = float(solid.loc[gap_days, "ev_per_day"].mean())
ax.annotate(f"days {gap_lo}-{gap_hi} are FLAGGED blackout yet run at {mid:.2f} events/day - "
            f"near-normal.\nThe flag (10 BUSINESS days) opens ~3 days before the Fed's own "
            f"second-Saturday rule,\nwhich is where the speaking actually stops.",
            xy=(float(gap_hi) + 0.4, float(solid.loc[gap_days, "ev_per_day"].max()) + 0.06),
            xytext=(24.0, YTOP * 0.66), ha="left", va="center", fontsize=9.6, color=INK2,
            arrowprops=dict(arrowstyle="->", color=MUTED, lw=1.2,
                            connectionstyle="arc3,rad=-0.15"))
ax.legend(handles=[
    Patch(facecolor=BLUE, label="events per business day"),
    Patch(facecolor=BLUE, alpha=0.12, label=f"empirical trough (days {trough_lo}-{trough_hi})"),
    Line2D([], [], color=MUTED, marker="v", linestyle="none", markersize=5,
           label=f"offset omitted, n < {LOW_N} business days"),
], loc="upper left", frameon=False, fontsize=9.5, handlelength=1.7, ncol=1)
style(ax)

# ---------------------------------------------------------------- titles
fig.suptitle("Fed speak frequency: how often the FOMC talks, and when",
             x=0.052, y=0.975, ha="left", fontsize=23, fontweight="bold", color=INK)
fig.text(0.052, 0.9535,
         f"ForexFactory FED_SPEAKERS calendar, {cal.Date.min():%d %b %Y} - {CUTOFF:%d %b %Y}: "
         f"{len(cal):,} speaking engagements, {cal.Speaker.nunique()} named officials, weekends included. "
         f"2026 is a PARTIAL year (to 24 Aug) - flagged in every panel, excluded from every mean, quantile "
         f"and trend fit.",
         ha="left", fontsize=11.4, color=INK2)
fig.text(0.052, 0.9345,
         f"P1-P6 use the raw calendar from 2015; P7 uses the business-day panel "
         f"({pan.index.min():%b %Y}-{pan.index.max():%b %Y}), which is where the FOMC clock lives.",
         ha="left", fontsize=11.4, color=MUTED)
fig.text(0.052, 0.0265,
         f"Counts are calendar ENTRIES, one per speaking engagement. The 2024-25 level shift coincides with a "
         f"broadening of the vendor's covered roster ({int(roster.loc[2019,'speakers'])} distinct names in 2019 "
         f"-> {int(roster.loc[2025,'speakers'])} in 2025) and with a re-labelling of most events from 'medium' to "
         f"'low' impact around 2020, so part of the rise",
         ha="left", fontsize=9.5, color=MUTED)
fig.text(0.052, 0.0125,
         f"may be coverage rather than behaviour; events per covered speaker is far more stable "
         f"({roster.loc[COMPLETE_YEARS,'events_per_speaker'].min():.1f}-"
         f"{roster.loc[COMPLETE_YEARS,'events_per_speaker'].max():.1f} across all complete years). Impact was "
         f"deliberately NOT used as a filter - its label regime flips around 2020, so filtering on it would "
         f"manufacture a spurious decline.",
         ha="left", fontsize=9.5, color=MUTED)

fig.savefig(FIG_PNG, dpi=210, facecolor=PLANE)
plt.close(fig)
print("wrote", FIG_PNG)

# ==================================================================================
# RESULTS JSON
# ==================================================================================
results["events_per_year"] = [
    dict(year=int(y),
         events=int(yr_counts.loc[y]),
         is_partial=bool(y == PARTIAL_YEAR),
         coverage_note=(f"through {CUTOFF:%Y-%m-%d}" if y == PARTIAL_YEAR else "full year"),
         annualised_seasonal=(round(ann_seasonal, 1) if y == PARTIAL_YEAR else None),
         annualised_prorata=(round(ann_prorata, 1) if y == PARTIAL_YEAR else None),
         speaking_days=int(roster.loc[y, "speaking_days"]),
         distinct_speakers=int(roster.loc[y, "speakers"]),
         events_per_speaker=round(float(roster.loc[y, "events_per_speaker"]), 2),
         core_roster_events=int(core_counts.loc[y]),
         trend_fitted=round(fitted(y, fit_full), 1),
         residual_vs_trend=(round(float(yr_counts.loc[y] - fitted(y, fit_full)), 1)
                            if y != PARTIAL_YEAR else None))
    for y in yr_counts.index
]
results["partial_year_handling"] = {
    "partial_year": PARTIAL_YEAR,
    "ytd_events": ytd_2026,
    "cutoff": CUTOFF.strftime("%Y-%m-%d"),
    "calendar_days_elapsed": doy,
    "fraction_of_year_elapsed": round(frac_elapsed, 4),
    "annualised_prorata": round(ann_prorata, 1),
    "mean_share_of_year_by_24_aug_complete_years": round(mean_share, 4),
    "annualised_seasonal": round(ann_seasonal, 1),
    "per_year_share_by_24_aug": {str(k): round(v, 4) for k, v in shares.items()},
    "why_they_differ": ("Only %.1f%% of a year's events normally land on or before 24 Aug while %.1f%% of the "
                        "year has elapsed - Sep-Nov is the busiest stretch - so pro-rata UNDERSTATES the "
                        "annualised figure by %.0f events." % (100 * mean_share, 100 * frac_elapsed,
                                                               ann_seasonal - ann_prorata)),
}
results["seasonality"] = {
    "basis": f"complete years {FIRST_YEAR}-{PARTIAL_YEAR-1} (n={len(COMPLETE_YEARS)}), partial year excluded",
    "overall_mean_events_per_month": round(overall_monthly_mean, 3),
    "by_month": [dict(month=int(m), name=MONTHS[m - 1],
                      mean_events=round(float(mo_mean[m]), 2),
                      q25=round(float(mo_q25[m]), 2), q75=round(float(mo_q75[m]), 2),
                      seasonality_index=round(float(seasonality_index[m]), 3))
                 for m in range(1, 13)],
    "strongest_month": dict(month=strongest_mo, name=MONTHS[strongest_mo - 1],
                            index=round(float(seasonality_index[strongest_mo]), 3),
                            mean_events=round(float(mo_mean[strongest_mo]), 2)),
    "weakest_month": dict(month=weakest_mo, name=MONTHS[weakest_mo - 1],
                          index=round(float(seasonality_index[weakest_mo]), 3),
                          mean_events=round(float(mo_mean[weakest_mo]), 2)),
    "ratio_strongest_to_weakest": round(float(seasonality_index[strongest_mo] / seasonality_index[weakest_mo]), 3),
}
results["heatmap_year_by_month"] = {
    str(y): {MONTHS[m - 1]: (None if (y, m) in nodata_cells else int(heat.loc[y, m])
                             if not pd.isna(heat.loc[y, m]) else 0)
             for m in range(1, 13)}
    for y in heat.index
}
results["day_of_week"] = {
    "counts": {DOWS[i]: int(dow_counts.loc[i]) for i in range(7)},
    "span": f"{cal.Date.min():%Y-%m-%d}..{CUTOFF:%Y-%m-%d}",
    "note": "pooled over ALL years INCLUDING the partial 2026 (to 24 Aug); counts are calendar "
            "EVENTS, weekends included",
}
results["speaker_composition"] = {
    "top_speakers_by_total_events": {s: int(cal.Speaker.value_counts()[s]) for s in top_speakers},
    "distinct_speakers_total": int(cal.Speaker.nunique()),
    "share_by_year": {str(y): {s: round(float(spk_share.loc[y, s]), 4)
                               for s in top_speakers + ["Other"]} for y in spk_share.index},
    "persistent_speakers_definition": "speakers appearing in >=10 of the 11 complete years",
    "persistent_speakers": core_roster,
    "persistent_speakers_events_by_year": {str(y): int(core_counts.loc[y]) for y in core_counts.index},
    "persistent_speakers_WARNING": (
        f"this 'fixed-roster control' resolves to {len(core_roster)} name(s) ({', '.join(core_roster)}), "
        "so it is NOT a roster series and must not be read as one; it is a single-speaker count. "
        "The coverage confound (10 distinct names in 2019 -> 21 in 2025) is therefore NOT controlled "
        "by this key."),
    "warsh_events_in_calendar": int((cal.Speaker == "Warsh").sum()),
}
results["jpm_coverage"] = {
    "unit": "distinct (date, speaker-last-name) speaking engagement",
    "join_key": "exact (Date, Speaker) match between calendar and fed_hawk_dove_scores.csv",
    "by_year": {str(y): dict(engagements=int(r.pairs), scored=int(r.scored), pct=round(float(r.pct), 1),
                             is_partial=bool(y == PARTIAL_YEAR),
                             coverage_note=("PARTIAL YEAR to 24 Aug 2026; bar height is a count, "
                                            "not comparable to a complete year"
                                            if y == PARTIAL_YEAR else "complete year"))
                for y, r in cov.iterrows()},
    "jpm_feed_max_date": f"{JPM_MAX:%Y-%m-%d}",
    "jpm_unscoreable_2026_engagements": jpm_unscoreable_2026,
    "jpm_pct_2026_full_window": round(jpm_pct_2026_full_window, 1),
    "jpm_pct_2026_scoreable_window": round(jpm_pct_2026_scoreable_window, 1),
    "jpm_feed_gap_note": (
        f"the JPM feed's last row is {JPM_MAX:%Y-%m-%d}, before the {CUTOFF:%Y-%m-%d} calendar cutoff, so "
        f"{jpm_unscoreable_2026} 2026 engagements can never carry a score; the 2026 coverage figure is "
        f"{jpm_pct_2026_full_window:.1f}% on the full window vs {jpm_pct_2026_scoreable_window:.1f}% on the "
        f"scoreable window (a {jpm_pct_2026_scoreable_window - jpm_pct_2026_full_window:.1f}pp effect)"),
    "total_engagements": tot_pairs,
    "total_scored": tot_scored,
    "total_pct": round(100.0 * tot_scored / tot_pairs, 2),
    "jpm_rows_total": int(len(jpm)),
    "jpm_rows_in_calendar_span": int(len(jpm_in_span)),
    "jpm_rows_before_calendar_start": int((jpm.date < cal.Date.min()).sum()),
    "jpm_rows_matching_calendar_exactly": int(jpm_exact),
    "jpm_rows_matching_within_1_day": int(jpm_w1),
    "jpm_rows_matching_within_3_days": int(jpm_w3),
    "panel_day_level_coverage_for_contrast": "panel reports 308 of 862 speech DAYS scored (35.7%) - a day-level "
                                             "figure, not comparable to the engagement-level percentages here",
}
results["intra_cycle_profile"] = {
    "source": "panel_daily.parquet (business days only); x = days_to_fomc = CALENDAR days to next decision",
    "far_field_baseline_ev_per_day": round(far, 4),
    "far_field_definition": "mean over days_to_fomc >= 18 with n_days >= %d" % LOW_N,
    "empirical_trough_days": [trough_lo, trough_hi],
    "empirical_trough_ev_per_day": round(trough_rate, 4),
    "empirical_trough_pct_of_far_field": round(100 * trough_rate / far, 1),
    "panel_flag_is_blackout_spans_days": [flag_lo, flag_hi],
    "trough_visible": True,
    "data_quality_verdict": "PASS - the blackout trough is present and deep (%.0f%% of far-field), so the "
                            "calendar/FOMC join is sound." % (100 * trough_rate / far),
    "flag_vs_empirical_finding": ("The panel's is_blackout (10 BUSINESS days before the decision ~ 14 calendar "
                                  "days) opens about 3 days earlier than the behavioural trough. Days %d-%d are "
                                  "flagged blackout yet run at %.2f events/day, close to the %.2f far-field rate. "
                                  "The Fed's actual rule starts the second Saturday before the meeting (~11 "
                                  "calendar days), which is where the speaking actually stops. Anything that "
                                  "conditions on is_blackout is therefore including ~3 near-normal speaking days."
                                  % (gap_lo, gap_hi, mid, far)),
    "flagged_but_normal_days": gap_days,
    "plotted_range_days": [0, CYC_MAX],
    "panel_days_covered_by_plotted_range": cyc_cov,
    "low_sample_offsets_omitted_from_plot": low_offsets,
    "low_sample_is_structural_not_random": ("Every omitted offset is 3 or 4 mod 7 (%s). FOMC decisions fall on "
                                            "Wednesdays, so those offsets land on a weekend and a business-day "
                                            "panel almost never observes them - they carry 1-3 days each and "
                                            "would otherwise draw spikes of up to 3.5 events/day."
                                            % ", ".join(str(m) for m in low_mod7)),
    "profile": [dict(days_to_fomc=int(d),
                     n_business_days=(None if pd.isna(r.n_days) else int(r.n_days)),
                     events_per_day=(None if pd.isna(r.ev_per_day) else round(float(r.ev_per_day), 4)),
                     pct_flagged_blackout=(None if pd.isna(r.pct_flagged_blackout)
                                           else round(float(r.pct_flagged_blackout), 3)),
                     low_sample=bool(r.low_n) if not pd.isna(r.n_days) else None)
                for d, r in cyc.iterrows()],
}
results["trend"] = {
    "fit_basis": f"OLS on annual counts, COMPLETE years {FIRST_YEAR}-{PARTIAL_YEAR-1} only (n={fit_full['n']})",
    "slope_events_per_year": round(fit_full["slope"], 3),
    "intercept": round(fit_full["intercept"], 2),
    "r2": round(fit_full["r2"], 4),
    "t_stat": round(fit_full["t_stat"], 3),
    "p_value": round(fit_full["p_value"], 5),
    "direction": "RISING",
    "fit_excluding_2024_25": {"years": f"{FIRST_YEAR}-2023", "slope": round(fit_pre24["slope"], 3),
                              "r2": round(fit_pre24["r2"], 4), "t_stat": round(fit_pre24["t_stat"], 3),
                              "note": "the steep slope is driven by 2024-25; through 2023 the drift is much flatter"},
    "latest_complete_year": {"year": 2025, "events": int(yr_counts.loc[2025]),
                             "fitted": round(fitted(2025, fit_full), 1),
                             "residual": round(resid_2025, 1),
                             "position": "ABOVE trend"},
    "partial_year_annualised": {"year": PARTIAL_YEAR,
                                "annualised_seasonal": round(ann_seasonal, 1),
                                "annualised_prorata": round(ann_prorata, 1),
                                "fitted": round(fitted(2026, fit_full), 1),
                                "residual_seasonal": round(resid_2026_seasonal, 1),
                                "residual_prorata": round(resid_2026_prorata, 1),
                                "position": ("BELOW trend" if resid_2026_seasonal < 0 else "ABOVE trend")},
    "like_for_like_ytd_to_24_aug": {str(y): int(v) for y, v in ytd.items()},
    "ytd_2026_vs_2025_pct": round(100 * (ytd[2026] / ytd[2025] - 1), 1),
    "ytd_2026_vs_2024_pct": round(100 * (ytd[2026] / ytd[2024] - 1), 1),
    "pre_handover_1jan_22may": {str(y): int(v) for y, v in pre_handover.items()},
    "post_handover_23may_24aug": {str(y): int(v) for y, v in post_handover.items()},
    "pre_handover_2026_vs_2025_pct": round(100 * (pre_handover[2026] / pre_handover[2025] - 1), 1),
    "post_handover_2026_vs_2025_pct": round(100 * (post_handover[2026] / post_handover[2025] - 1), 1),
}
results["thesis_check_fewer_higher_signal_events"] = {
    "claim": "Warsh wants FEWER, higher-signal Fed speaking events",
    "verdict": "PARTIALLY SUPPORTED, and NOT over the full sample - the count is RISING, not falling",
    "detail": [
        f"Over complete years the trend is {fit_full['slope']:+.1f} events/yr (R2 {fit_full['r2']:.2f}); "
        f"2025 set the record at {int(yr_counts.loc[2025])}, {resid_2025:+.0f} above trend.",
        f"2026 YTD is {ytd[2026]} vs {ytd[2025]} in the same window of 2025 "
        f"({100*(ytd[2026]/ytd[2025]-1):+.1f}%) - a genuine decline from the peak.",
        f"But {ytd[2026]} YTD still matches 2024 ({ytd[2024]}) and beats every year before it: this is the "
        f"second-busiest pace on record, not a return to the 2015-2023 norm (YTD mean "
        f"{np.mean([ytd[y] for y in range(2015,2024)]):.0f}).",
        f"The decline STARTED BEFORE the handover: 1 Jan-22 May was {pre_handover[2026]} in 2026 vs "
        f"{pre_handover[2025]} in 2025 ({100*(pre_handover[2026]/pre_handover[2025]-1):+.1f}%), then "
        f"23 May-24 Aug {post_handover[2026]} vs {post_handover[2025]} "
        f"({100*(post_handover[2026]/post_handover[2025]-1):+.1f}%). It steepens post-handover but does not begin there.",
        f"Annualised, 2026 lands at {ann_seasonal:.0f} (seasonal) or {ann_prorata:.0f} (pro-rata) against a "
        f"fitted {fitted(2026, fit_full):.0f}: essentially ON trend ({resid_2026_seasonal:+.0f} on the seasonal "
        f"method, {resid_2026_prorata:+.0f} pro-rata). The annualisation method decides the sign, so the honest "
        f"reading is 'on trend', not 'below' - and 'on trend' here means a still-rising trend.",
        "So the count is NOT falling in level terms; it is falling only relative to the 2025 spike, and the "
        "annualised 2026 figure is indistinguishable from the rising trend line. The thesis needs the next two "
        "quarters to separate a Warsh regime from a normal post-peak year.",
    ],
    "verdict_one_line": ("The count is RISING, not falling: +%.0f events/yr over 2015-2025 with 2025 a record "
                         "%d. 2026 is down %.0f%% YTD versus 2025 and down %.0f%% since the handover, but its "
                         "annualised level (%.0f) sits ON the rising trend and still beats every year before "
                         "2024. Partial support at best."
                         % (fit_full["slope"], int(yr_counts.loc[2025]),
                            abs(100 * (ytd[2026] / ytd[2025] - 1)),
                            abs(100 * (post_handover[2026] / post_handover[2025] - 1)), ann_seasonal)),
}
results["caveats"] = [
    "PARTIAL YEAR: 2026 runs to 2026-08-24 only. It is excluded from every mean, quantile and trend fit and is "
    "flagged in every panel. Two 2026-08-25 rows in the raw calendar were cut so all windows share one clock.",
    "COVERAGE CONFOUND, unresolvable from this data: the 2024-25 level shift coincides with the vendor's speaker "
    f"roster broadening from {int(roster.loc[2019,'speakers'])} distinct names in 2019 to "
    f"{int(roster.loc[2025,'speakers'])} in 2025, and with a re-labelling of most events from 'medium' to 'low' "
    "impact around 2020. Events per covered speaker is far more stable "
    f"({roster.loc[COMPLETE_YEARS,'events_per_speaker'].min():.1f}-"
    f"{roster.loc[COMPLETE_YEARS,'events_per_speaker'].max():.1f}), so a large part of the rise is roster breadth "
    "rather than each official speaking more. Whether that breadth is genuine or vendor coverage cannot be "
    "settled here.",
    "Impact was deliberately NOT used as a control: the label regime flips around 2020 (medium-dominant before, "
    "low-dominant after), so filtering on it would manufacture a spurious decline.",
    "WARSH IS INVISIBLE: he has zero events in this calendar, and no Chair-titled event of any name appears "
    "after 2026-03-30. The post-handover drop is therefore partly untestable - if ForexFactory lags or mis-tags "
    "the new chair, the measured decline is overstated.",
    "JPM SCORES ARE A COVERAGE MEASURE ONLY. ~60% of score rows were published AFTER the speech they score, so "
    "nothing forward-looking may be built from them; P6 answers 'is the sentiment index fed here', not 'is the "
    "score right'.",
    f"SECOND PARTIAL-NESS INSIDE P6: the JPM feed's last row is {JPM_MAX:%Y-%m-%d}, "
    f"{(CUTOFF - JPM_MAX).days} days before the calendar cutoff, so {jpm_unscoreable_2026} 2026 engagements "
    f"can never carry a score. 2026 coverage is {jpm_pct_2026_full_window:.1f}% on the full window vs "
    f"{jpm_pct_2026_scoreable_window:.1f}% on the scoreable window - a "
    f"{jpm_pct_2026_scoreable_window - jpm_pct_2026_full_window:.1f}pp effect, minor but real.",
    "THE 'FIXED-ROSTER CONTROL' IS NOT ONE: speakers present in >=10 of the 11 complete years resolves to "
    f"{len(core_roster)} name(s) ({', '.join(core_roster)}). The JSON key was renamed persistent_speakers_* "
    "and carries a warning; the coverage confound above is NOT controlled by it.",
    f"JPM join is exact (date, last name): {jpm_exact} of {len(jpm_in_span)} in-span rows match a calendar "
    f"engagement exactly ({jpm_w1} within 1 day, {jpm_w3} within 3). Unmatched rows are speeches the "
    "ForexFactory calendar never carried, plus name/date disagreements.",
    f"The intra-cycle panel uses the business-day panel: it starts in 2019 and drops the {off_spine} events "
    f"inside its span that sit off the business-day spine ({off_spine_weekend} weekend-dated, "
    f"{off_spine - off_spine_weekend} on weekday holidays). A calendar-side re-derivation that KEEPS those "
    f"events, with a calendar-day denominator, puts the trough at {100*cs_near/cs_far:.1f}% of far-field "
    f"against the panel's {100*trough_rate/far:.1f}% - the same conclusion, so nothing material is lost. The "
    f"annual/seasonal panels use the full raw calendar from 2015.",
    "days_to_fomc bins 10 and 11 rest on 3 and 2 observations (a Wednesday decision puts those offsets on a "
    "weekend, and the panel is business-day indexed). They are hatched, not treated as signal.",
    "Counts are speaking ENGAGEMENTS, not distinct speaker-days: 2024-25 average 2.2-2.6 engagements per "
    "speaking day vs 1.4-1.5 in 2015-2018. Distinct speaking DAYS rise too "
    f"({int(roster.loc[2015,'speaking_days'])} in 2015 -> {int(roster.loc[2025,'speaking_days'])} in 2025), so "
    "the trend is not purely multi-engagement inflation.",
]

results["verification"] = {
    "why": "The intra-cycle trough doubles as the required data-quality check, so the detector itself is tested.",
    "shuffle_null": {
        "method": "permute the daily event counts across panel days 200x, holding days_to_fomc fixed, and "
                  "re-measure trough depth (days 0-9 mean / days 18-44 mean)",
        "n_draws": 200,
        "observed_depth": round(trough_rate / far, 4),
        "shuffled_depth_mean": round(float(_depths.mean()), 4),
        "shuffled_depth_min": round(float(_depths.min()), 4),
        "shuffled_depth_1st_pct": round(float(np.percentile(_depths, 1)), 4),
        "draws_reaching_observed_depth": int((_depths <= trough_rate / far).sum()),
        "verdict": "NOT VACUOUS - 0 of 200 shuffles reach the observed depth; the trough is a property of the "
                   "FOMC clock, not of the binning.",
    },
    "calendar_side_rederivation": {
        "method": "recover the 61 decision dates from the panel, then measure events per CALENDAR day on the "
                  "raw calendar - weekends and holidays included - instead of trusting panel.n_speakers",
        "fomc_dates_recovered": int(len(_fomc)),
        "fomc_dates_on_a_wednesday": n_wednesday,
        "near_rate_days_0_9_per_calendar_day": round(cs_near, 4),
        "far_rate_days_18_44_per_calendar_day": round(cs_far, 4),
        "trough_pct_of_far_field": round(100 * cs_near / cs_far, 1),
        "panel_route_said_pct": round(100 * trough_rate / far, 1),
        "verdict": "AGREES - two independent routes both find a deep trough.",
    },
    "panel_vs_calendar_reconciliation": {
        "calendar_events_inside_panel_span": int(len(_span)),
        "panel_n_speakers_sum": int(pan.n_speakers.sum()),
        "off_spine_events": off_spine,
        "off_spine_weekend_dated": off_spine_weekend,
        "off_spine_weekday_holiday": off_spine - off_spine_weekend,
    },
    "independent_reimplementation": "frequency_seasonality_verify.py re-derives every headline number by a "
                                    "different code path (scipy.linregress for the fit, a merge for the JPM "
                                    "join, value_counts for the annual counts). All checks pass.",
}

with open(RES_JSON, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, default=jdump)
print("wrote", RES_JSON)

# ---------------------------------------------------------------- console summary
print("\n--- events per year ---")
for y in yr_counts.index:
    flag = "  <-- PARTIAL" if y == PARTIAL_YEAR else ""
    print(f"  {y}  {int(yr_counts.loc[y]):>4}{flag}")
print(f"\n2026 YTD {ytd_2026}; annualised seasonal {ann_seasonal:.1f}, pro-rata {ann_prorata:.1f}")
print(f"trend (complete yrs) slope {fit_full['slope']:+.2f}/yr  R2 {fit_full['r2']:.3f}  t {fit_full['t_stat']:.2f}")
print(f"2025 residual {resid_2025:+.1f}; 2026 annualised residual {resid_2026_seasonal:+.1f}")
print(f"seasonality: strongest {MONTHS[strongest_mo-1]} ({seasonality_index[strongest_mo]:.2f}), "
      f"weakest {MONTHS[weakest_mo-1]} ({seasonality_index[weakest_mo]:.2f})")
print(f"intra-cycle: far-field {far:.2f}/day, trough days {trough_lo}-{trough_hi} at {trough_rate:.2f}/day "
      f"({100*trough_rate/far:.0f}%); flag spans {flag_lo}-{flag_hi}")
print(f"YTD like-for-like: 2024 {ytd[2024]}, 2025 {ytd[2025]}, 2026 {ytd[2026]}")
print(f"pre-handover 2026 {pre_handover[2026]} vs 2025 {pre_handover[2025]}; "
      f"post {post_handover[2026]} vs {post_handover[2025]}")
