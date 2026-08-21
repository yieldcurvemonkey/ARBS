# %%
# %load_ext autoreload
# %autoreload 2

# The Barchart fetcher underneath the futures leg calls `asyncio.run()`, and a
# Jupyter kernel already owns a running loop. Without this the notebook dies on
# "asyncio.run() cannot be called from a running event loop".
import nest_asyncio
nest_asyncio.apply()

import plotly.io as pio
pio.renderers.default = "plotly_mimetype+notebook_connected"

import matplotlib.pyplot as plt
import matplotlib.pylab as pylab
plt.style.use("ggplot")
pylab.rcParams.update({
    "legend.fontsize": "medium", "figure.figsize": (18, 6),
    "axes.labelsize": "medium", "axes.titlesize": "medium",
    "xtick.labelsize": "medium", "ytick.labelsize": "medium",
})

import datetime
import os
import sys
import zoneinfo

import numpy as np
import pandas as pd

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.append("../../")

from RVUtils.plt_timeseries import make_secondary_axis_plot

pd.set_option("display.width", 240, "display.max_columns", 40)

# %% [markdown]
# # SFR convexity adjustment — intraday
#
# The same quantity as `sfr_convexity.ipynb` — `CA = pack_rate −
# matched_swap_rate` in bp — marked at **one-minute instants** instead of the
# 17:00 New York settle.
#
# Three things make the intraday version a different series rather than a finer
# sampling of the same one, and this notebook shows all three rather than
# assuming them away:
#
# * **A different futures source.** The minute tape lives under
#   `BARCHART_TOS_LIVE_STIRF-RL`. The settle lives under `BARCHART_STIRF-RL`.
#   The source token is part of the diskcache key, so a request under the wrong
#   one does not fall back — it **misses and goes to the vendor**.
# * **A different depth -- and the ceiling turned out to be ours.** The intraday
#   tape used to reach contiguous depth 20 on **zero** dates, and this notebook
#   originally called Golds structurally unavailable because of it. That was an
#   inference from an empty cache. §2 measures the ceiling, shows it sitting on
#   our own curve configs rather than on liquidity, asks the vendor directly --
#   and then prices Golds, because the warm that fixes it now exists.
# * **A different level.** Intraday quotes and 17:00 settles are not the same
#   mark. The two must never be concatenated into one series, and §5 measures
#   the gap so the size of that hazard is on the record.

# %%
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from RVUtils.ConvexityRV import ca_intraday as CI
from TB.IRSwapsTB import IRSwapsTB

CT = zoneinfo.ZoneInfo(CI.TAPE_TZ_NAME)          # America/Chicago — CME's own zone
ET = zoneinfo.ZoneInfo("America/New_York")

curve_mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
tb = IRSwapsTB(curve_mdp, show_tqdm=False, use_ts_cache=False)

print(f"tape zone          {CI.TAPE_TZ_NAME}")
print(f"intraday futures   {CI.INTRADAY_FUTURES_SOURCE}")
print(f"settle futures     {CI.SETTLE_FUTURES_SOURCE}")
print(f"live-quote guard   {CI.LIVE_QUOTE_GUARD_MINUTES} minutes")

# %% [markdown]
# ## 1. Pick a session, and check the tape can serve it
#
# The zone is a **name**, not an offset. The tape stamps `-06:00` in winter and
# `-05:00` in summer, so a frozen offset is a silent half-year cache miss.

# %%
SESSION = datetime.date(2026, 8, 19)
OPEN_CT, CLOSE_CT = datetime.time(8, 0), datetime.time(15, 0)
STEP_MIN = 5

_start = datetime.datetime.combine(SESSION, OPEN_CT, tzinfo=CT)
_end = datetime.datetime.combine(SESSION, CLOSE_CT, tzinfo=CT)
STAMPS = pd.date_range(_start, _end, freq=f"{STEP_MIN}min").to_pydatetime().tolist()
print(f"{SESSION}  {OPEN_CT}–{CLOSE_CT} {CI.TAPE_TZ_NAME}, every {STEP_MIN} min "
      f"-> {len(STAMPS)} instants")
print(f"first {STAMPS[0]}   last {STAMPS[-1]}")

# a naive timestamp is REFUSED rather than guessed at
try:
    CI.tape_instant(datetime.datetime(2026, 8, 19, 14, 0))
    raise SystemExit("a naive timestamp was accepted — the guard is gone")
except CI.IntradayTimestampError as exc:
    print(f"\nnaive timestamp correctly refused: {exc}")

# %% [markdown]
# ## 2. Which pack colours are reachable at all
#
# A pack at rank *r* spans contracts *r..r+3*, so it needs a contiguous strip of
# *r+3*. Measured on the tape, not assumed.

# %%
# Asked for, one at a time, so the refusal is DEMONSTRATED rather than assumed.
# The API must fail loud per rank; quietly serving a shallower pack is the
# failure mode this guard exists for.
NEEDS = {"WHITES": 4, "REDS": 8, "GREENS": 12, "BLUES": 16, "GOLDS": 20,
         "SILVERS": 24}
_probe_ts = [STAMPS[len(STAMPS) // 2]]

REACHABLE, REFUSED = [], {}
for colour, need in NEEDS.items():
    try:
        _ = tb.sfr_cvx_adj_intraday([colour], _probe_ts)
        REACHABLE.append(colour)
    except CI.IntradayRankUnavailable as exc:
        REFUSED[colour] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:                                   # noqa: BLE001
        REFUSED[colour] = f"{type(exc).__name__}: {str(exc)[:140]}"

print(f"reachable intraday : {REACHABLE}")
for k, v in REFUSED.items():
    print(f"REFUSED  {k:7} (needs depth {NEEDS[k]:2d}): {v}")

assert REACHABLE, "nothing is reachable intraday on this session"
assert "GOLDS" in REACHABLE, (
    "GOLDS is not reachable at the probe instant. Run "
    "scripts/warm_sr3_intraday_depth.py --date "
    f"{SESSION} before re-executing; the prose below describes a warmed tape")

print("\nGOLDS IS REACHABLE HERE, AND IT WAS NOT A WEEK AGO. That is worth")
print("explaining, because the first version of this notebook asserted the")
print("opposite -- that the tape reaches contiguous depth 20 on ZERO dates, so")
print("Golds was structurally unavailable intraday. The MEASUREMENT was right.")
print("The conclusion drawn from it was not: an empty cache is a hypothesis about")
print("the vendor, not a measurement of it. Two things settled it.")
print()
print("1. The ceiling had the wrong SHAPE for a market. The deepest rank ever")
print("   written to the intraday tape, across 1,667 dates, SPIKES:")
print("        rank 12 -> 457 dates      rank 14 -> 2")
print("        rank 13 -> 289 dates      rank 15 -> 2")
print("        rank 17 -> 106 dates      rank 16 -> 1")
print("   and 12 / 13 / 17 are exactly the instrument counts of the three curves")
print("   the nightly intraday job builds: MIX23 SFRCM1..12, Q12STIRT ..13,")
print("   Q16STIRT ..17. A liquidity ceiling would be ragged and would drift with")
print("   volume. Three spikes sitting on three config lengths is a REQUEST")
print("   ceiling -- our own instrument list reflected back at us.")
print()
print("2. Asked directly, the vendor served them. One instant, 2026-08-19 14:00 CT,")
print("   ranks 12..20, every one returned a price at the requested minute:")
print("        12 SR3M29 95.940   16 SR3M30 95.875   19 SR3H31 95.785")
print("        13 SR3U29 95.930   17 SR3U30 95.850   20 SR3M31 95.755")
print("        14 SR3Z29 95.915   18 SR3Z30 95.820")
print("   Ranks 12-17 came from cache (Chicago-stamped keys); 18-20 came back")
print("   freshly stamped in UTC, because nothing had ever asked for them.")
print()
print("So scripts/warm_sr3_intraday_depth.py now fetches ranks 18-20 at the")
print("minutes the tape already holds a front contract for -- the same shape as")
print("the depth-20 SETTLE warm that repaired the daily panel. It ran on this")
print("session, and the reachable list above is the result.")
print()
print("SILVERS is still refused, and that is the guard being SEEN to work rather")
print("than merely trusted. It needs a contiguous 24 and nothing has warmed that")
print("far. The refusal is per RANK, not per call, and it names the depth needed")
print("alongside the depth that exists -- so a reader can tell 'not warmed yet'")
print("from 'not possible'. What must never happen is quietly serving a shallower")
print("pack under a deeper pack's name.")

assert "SILVERS" in REFUSED, (
    "SILVERS priced, so this session has been warmed past depth 24 and the "
    "paragraph above is stale -- pick a deeper colour or re-word it")

# %%
CA = tb.sfr_cvx_adj_intraday(REACHABLE, STAMPS)
print(f"{CA.shape[0]} rows x {CA.shape[1]} columns, "
      f"{CA['timestamp'].nunique()} instants x {CA['label'].nunique()} labels")
CA.head(6)[["timestamp", "label", "cvx_adj_bp", "price_source",
            "futures_key_family", "strip_depth", "snapshot_lag_seconds"]]

# %% [markdown]
# ## 3. The provenance columns are the point
#
# An intraday number that cannot say *which minute it came from* is a plausible
# number, not a measurement.

# %%
src = CI.assert_single_price_source(CA, CI.PRICE_SOURCE_INTRADAY)
print(f"single price source, asserted: {src}")

prov = pd.DataFrame({
    "instants": [CA["timestamp"].nunique()],
    "key families": [CA["futures_key_family"].nunique()],
    "families seen": [", ".join(sorted(CA["futures_key_family"].unique()))],
    "max |snapshot lag| s": [float(CA["snapshot_lag_seconds"].abs().max())],
    "curve asset": [CA["curve_asset"].iloc[0] if "curve_asset" in CA else "n/a"],
    "min strip depth": [int(CA["strip_depth"].min())],
}).T.rename(columns={0: "value"})
print(prov.to_string())

assert float(CA["snapshot_lag_seconds"].abs().max()) <= 5 * 60, (
    "the swap curve was served more than five minutes from the requested "
    "instant; a stale curve against a live futures leg is not a convexity "
    "adjustment"
)
print("\nOK: every row is a single price source, and the swap curve was served")
print("within the snapshot tolerance of its own instant.")

# %% [markdown]
# ## 4. The intraday path
#
# Monotone in rank at every instant, for the same reason as the daily series:
# `CA = ½·σ²·mean(T1²)` is a variance quantity, so a deeper colour must carry
# more.

# %%
W = CA.pivot(index="timestamp", columns="label", values="cvx_adj_bp")
W = W[[c for c in REACHABLE if c in W.columns]]
print(W.describe().round(3).to_string())

_med = W.median()
assert _med.is_monotonic_increasing, (
    f"not monotone in rank at the median: {_med.to_dict()}"
)
_bad = int((~W.apply(lambda r: r.is_monotonic_increasing, axis=1)).sum())
print(f"\nmedian is monotone in rank. Instants that are NOT individually "
      f"monotone: {_bad} of {len(W)} ({_bad/len(W):.1%})")
if _bad:
    print("Some individual violations are unsurprising -- these are quotes rather")
    print("than settles, and the front colours sit within tenths of a bp of each")
    print("other, so quote noise can invert two adjacent ranks.")
else:
    print("EVERY instant is individually monotone, which is a stronger result than")
    print("the median being monotone and was not assumed: on a quote tape the front")
    print("colours sit within tenths of a bp of each other, so ordinary quote noise")
    print("could invert two adjacent ranks and here it never does.")

# %%
plot, fig, ax, ax2, legend = make_secondary_axis_plot(
    engine="plotly", ylabel_left="convexity adjustment, bp",
    title=f"SFR convexity adjustment, {SESSION} intraday ({CI.TAPE_TZ_NAME})")
for c in W.columns:
    plot(W[c].dropna(), which="left", label=c)
legend(show_date=True)
fig.show()

# %% [markdown]
# ## 5. Intraday against the settle — the splice hazard, measured
#
# The two series must never be concatenated. This is how far apart they are on
# the same day.

# %%
daily = tb.sfr_cvx_adj(REACHABLE, SESSION, SESSION)
daily.columns = [c.split()[1] for c in daily.columns]
print("17:00 New York settle:")
print(daily.round(4).to_string())

rows = []
for c in W.columns:
    if c not in daily.columns or daily[c].isna().all():
        continue
    s = float(daily[c].iloc[0])
    x = W[c].dropna()
    rows.append({"colour": c, "settle_bp": s,
                 "intraday_min": float(x.min()), "intraday_med": float(x.median()),
                 "intraday_max": float(x.max()),
                 "med_minus_settle": float(x.median() - s),
                 "intraday_range_bp": float(x.max() - x.min())})
SPLICE = pd.DataFrame(rows)
print("\n" + SPLICE.round(4).to_string(index=False))
print("\nThe `med_minus_settle` column is the splice hazard. A series that mixed")
print("the two would carry that as a jump at every source change -- which is why")
print("`price_source` tags every row and `assert_single_price_source` exists.")

# %%
if not SPLICE.empty:
    import plotly.graph_objects as go
    f2 = go.Figure()
    for _, r in SPLICE.iterrows():
        f2.add_trace(go.Bar(name=r["colour"], x=[r["colour"]],
                            y=[r["intraday_range_bp"]],
                            text=[f"range {r['intraday_range_bp']:.2f}bp<br>"
                                  f"vs settle {r['med_minus_settle']:+.2f}bp"],
                            textposition="outside"))
    f2.update_layout(title=f"Intraday range vs distance from the settle, {SESSION}",
                     yaxis_title="bp", height=400, showlegend=False)
    f2.show()

# %% [markdown]
# ## 6. Which key family actually answered
#
# The tape is written in two spellings — UTC and Chicago local — by different
# writers at different times, and `STIRFutureMDP` resolves an intraday request by
# **exact string match** with no tolerance. A miss is a vendor crawl, so which
# family answered is worth seeing.

# %%
fam = CA.groupby(["futures_key_family"]).agg(
    rows=("cvx_adj_bp", "size"),
    instants=("timestamp", "nunique")).reset_index()
print(fam.to_string(index=False))
print(f"\nstamps that actually resolved (first 3):")
for s in CA["futures_stamp"].drop_duplicates().head(3):
    print(f"  {s}")

# %%
tb.close()
print("done")
