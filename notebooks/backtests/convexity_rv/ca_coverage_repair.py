# %% [markdown]
# # The convexity-adjustment series was sparse for two reasons, and only one of them was missing data
#
# The complaint: *"the convexity-adjustment timeseries is sparse from ~May-2024
# to Aug-2026 and looks interpolated."* Both halves are true, both are defects,
# and they are unrelated to each other.
#
# ## The five findings, up front
#
# 1. **A universe gate discarded ~500 rank-1 dates that were fully priceable.**
#    `strat2_q20.strip_depth_by_date` admitted a date only when its contiguous
#    strip reached `min_instruments` — the **curve-solve** floor, 12 — so a date
#    holding four good front settles was dropped for *every* rank, including the
#    ranks that never look past contract 4. Measured: 2024 held **252** dates
#    able to quote rank 1 and the panel carried **19**; 2025 held 198 and carried
#    2; 2026 held 37 and carried 3. Nothing about that is a data shortage.
#
# 2. **The deep end is a genuine absence and only a fetch fixes it.** Nothing has
#    written a deferred SR3 settle to this machine since the ad-hoc analysis that
#    needed one. Blues (rank 13) needs a 16-contract strip and Golds (rank 17)
#    needs 20; 2025 held **two** such dates. `scripts/warm_sr3_deferred.py` is
#    the fetch, and this notebook separates what it bought from what the code fix
#    bought — every table below splits **recovered by code** from **recovered by
#    fetching**, date by date, from the warm's own ledger.
#
# 3. **A third defect, found while fixing the first: the universe counted cache
#    keys the fetcher cannot read.** The EOD alias is stamped in *New York local
#    time*, and the store also holds 17:00 keys stamped `+00:00`. They match the
#    key regex, so the scan counted them; `get_data` asks for the New York stamp
#    and misses. **51 dates scanned deeper than they resolve** — 2026-07-09
#    scanned at depth 12 and resolves at 0 — and they cost 906 blocked outbound
#    requests in the first rebuild before the filter was added.
#
# 4. **"Looks interpolated" was literally true, and `connectgaps=False` was not
#    the fix.** The flag was already set on the CA traces and was **inert**: it
#    only breaks a line where `y` is null, and the frames were built by an inner
#    join, so they carried zero NaN rows. The Blues CA trace held 503 points and
#    drew straight lines across gaps of **301 and 502 days** with the flag on.
#    The fix is to reindex onto the business-day grid *first*.
#
# 5. **The repair moved nothing.** Every (date, rank) row common to the shipped
#    panel and the rebuilt one is identical to floating-point exactness on
#    `ca_bp`, both rate sources, the swap rate, the gate columns and the
#    zero-convexity control. Coverage was added, not re-computed.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import dataclasses
import datetime
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_REPO = (pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir()
         else pathlib.Path.cwd().parents[2])
sys.path.insert(0, str(_REPO))

import plotly.graph_objects as go
import plotly.io as pio

pio.renderers.default = "plotly_mimetype+notebook_connected"

import RVUtils.ConvexityRV.ca_plots as CAP
import RVUtils.ConvexityRV.strat2_q20 as Q
import RVUtils.ConvexityRV.strat2_sofr_convexity as S2
from RVUtils.ConvexityRV import ca_diagnostics, ca_staleness
from RVUtils.ConvexityRV.listed_cache_guard import cache_only, network_calls_blocked

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 240)

# %% [markdown]
# ## 1. CONFIG — every knob, and why it is set where it is

# %%
@dataclasses.dataclass(frozen=True)
class RepairConfig:
    """Everything this notebook chooses over and above the module defaults."""

    # ---- window -------------------------------------------------------------
    start: datetime.date = datetime.date(2018, 1, 1)
    end: datetime.date = datetime.date(2026, 8, 18)
    """The panel window. **The end is yesterday, not today, and that is
    deliberate.** The EOD request alias is written from whatever the vendor
    serves at request time, so a date warmed during its own session stamps an
    intraday print with a settlement key — the precise confusion
    `assert_settle_source` exists to prevent, arriving through the back door. The
    warm now refuses `d >= today` for the same reason."""

    # ---- the two floors that were one --------------------------------------
    min_strip_depth: int = 4
    """UNIVERSE admission, in contracts. Four is one pack window (rank 1), the
    smallest strip that can produce any CA at all."""

    min_instruments: int = 4
    """CURVE-SOLVE floor, in calibration instruments. Was 12 and was applied to
    universe admission, which is the whole defect. Lowered only after measuring
    that the solve converges and agrees with the settles at shallow depth —
    section 3 reproduces that measurement inline."""

    min_priced_contracts: int = 4
    """The same decoupling on the near-pack path
    (`build_panel`, was `rank_start + n_packs + 2` = 13)."""

    # ---- the near-pack panel -----------------------------------------------
    near_n_contracts: int = 13
    near_rank_start: int = 2
    near_n_packs: int = 9
    """Windows 2..10 — the shipped near-pack strategy, unchanged. Only the date
    universe and the trim change."""

    # ---- statistics --------------------------------------------------------
    window_span_tolerance: float = 1.5
    """Calendar-span guard on every rolling window, ON for every panel this
    notebook builds. Restoring coverage restores the gaps, and `rolling(252)`
    counts ROWS: measured on the shipped panel, the "1Y" z-score as of
    2025-03-05 spanned **1,289 calendar days**. Un-trimming without this would
    swap a truncated series for a silently wrong one. 1.5 admits ordinary holiday
    clustering (a clean 252-row year spans ~365 days = 1.0)."""

    trim_keep: str = "none"
    """`"longest"` (legacy) | `"latest"` | `"none"`. The legacy rule kept the
    LONGEST gap-free run, which truncated the near-pack series at **2024-05-08**
    — the "~May-2024" of the complaint. Coverage is reported both ways in
    section 7 rather than one being chosen silently."""

    gap_days: int = 15
    """A hole longer than this is drawn as a hole and listed in the gap table."""


CFG = RepairConfig()

QCFG = Q.Q20Config(min_strip_depth=CFG.min_strip_depth,
                   min_instruments=CFG.min_instruments,
                   start=CFG.start, end=CFG.end)
NEAR = S2.Strat2Config(n_contracts=CFG.near_n_contracts,
                       rank_start=CFG.near_rank_start, n_packs=CFG.near_n_packs,
                       min_priced_contracts=CFG.min_priced_contracts,
                       window_span_tolerance=CFG.window_span_tolerance,
                       start=CFG.start, end=CFG.end)

print(f"Q20  : min_strip_depth={QCFG.min_strip_depth} (universe) "
      f"min_instruments={QCFG.min_instruments} (curve solve)")
print(f"near : n_contracts={NEAR.n_contracts} windows "
      f"{NEAR.rank_start}..{NEAR.rank_start + NEAR.n_packs - 1} "
      f"min_priced_contracts={NEAR.min_priced_contracts}")
print(f"stats: window_span_tolerance={NEAR.window_span_tolerance} "
      f"trim_keep={CFG.trim_keep!r}")

# %% [markdown]
# ## 2. The two floors, separated — this is the whole code fix
#
# `min_instruments` describes what the **Q20 curve** needs to solve.
# `min_strip_depth` describes what a **pack window** needs to exist. They are
# different questions and one number was answering both.
#
# The shipped rule, at `strat2_q20.py:413`:
#
# ```python
# if instrument_count(dd, depth) >= cfg.min_instruments:   # 12
#     out[dd] = depth
# ```
#
# Depth is then used per rank three hundred lines later
# (`gate_covered = spec.rank + 3 <= depth`) — so the code already knew how to
# vary the rank set by depth. The date never reached that line.

# %%
# The warm ledger, loaded FIRST. Every table below attributes a recovered date to
# code or to fetching from it, and the pre-warm depth map is reconstructed from
# its `depth_before` field. A live re-scan cannot serve as the "before" number,
# because the fetch has already changed what a scan sees.
_LEDGER_F = DATA / "warm_sr3_deferred_ledger.json"
WARMED, WARM_DEPTH_BEFORE, WARM_SUMMARY = set(), {}, {}
if _LEDGER_F.exists():
    _led = json.loads(_LEDGER_F.read_text(encoding="utf-8"))
    WARM_SUMMARY = _led.get("summary", {})
    for _k, _v in _led.get("dates", {}).items():
        _dd = datetime.date.fromisoformat(_k)
        WARMED.add(_dd)
        WARM_DEPTH_BEFORE[_dd] = int(_v.get("depth_before", 0))
print(f"warm ledger: {len(WARMED)} dates fetched")

_t0 = time.time()
DEPTHS = Q.strip_depth_by_date(QCFG, min_depth=1)           # every date, any depth
DEPTHS_PRE = {d: WARM_DEPTH_BEFORE.get(d, v) for d, v in DEPTHS.items()}
NOW = {d: v for d, v in DEPTHS.items() if v >= CFG.min_strip_depth}
BEFORE_FIX = {d: v for d, v in DEPTHS_PRE.items() if v >= 12}    # the shipped floor
print(f"universe: {len(NOW):,} dates now; {len(BEFORE_FIX):,} under the shipped "
      f"12-deep floor and the pre-warm store  [{time.time() - _t0:.0f}s, 0 network]")

_d = pd.Series(NOW)
_d.index = pd.to_datetime(list(NOW))
_o = pd.Series(BEFORE_FIX)
_o.index = pd.to_datetime(list(BEFORE_FIX))

_u = pd.DataFrame({"dates_now": _d.groupby(_d.index.year).size(),
                   "dates_shipped_rule": _o.groupby(_o.index.year).size()}
                  ).fillna(0).astype(int)
for _r in (1, 5, 9, 13, 17):
    _u[f"rank{_r}"] = (_d >= Q.depth_for_rank(_r)).groupby(_d.index.year).sum()
print("\ndates able to quote each pack rank (rank 13 = Blues, 17 = Golds):")
print(_u.to_string())

assert len(NOW) > len(BEFORE_FIX), "the permissive universe must be larger"

# %% [markdown]
# ## 3. The floor's stated rationale, tested rather than inherited
#
# The docstring justified 12 as *"a 20-node curve fitted to 6 contracts is mostly
# interpolation, and the resolution gate would reject its windows anyway."* Both
# halves are checkable, so they are checked here rather than argued about: build
# the curve at the shallowest depths in the store and measure how far its
# forwards sit from the settles they were calibrated to.
#
# The second half of the rationale is the interesting one — *the gate would
# reject them anyway*. If that were true the floor would be a free optimisation.
# It is not true, and where it IS true the gate says so on the row, which is the
# difference between a date being **judged** and a date being **discarded
# unjudged**.

# %%
_probe_rows = []
_b0 = network_calls_blocked()
_builder = Q.Q20Builder(QCFG)
for _target in (4, 5, 6, 7, 8, 10):
    _hit = [(k, v) for k, v in sorted(DEPTHS.items()) if v == _target and k.year >= 2024]
    if not _hit:
        continue
    _dt, _dep = _hit[len(_hit) // 2]
    try:
        with cache_only():
            _p = _builder.pricer(_dt, _dep)
            _fw = Q.q20_imm_forwards(_p, S2.quarterly_imm_sequence(_dt, _dep))
            _st = _builder.settles(_dt, _dep)
        _diffs = [abs((_st[k] - _fw[k]) * 100.0) for k in _fw if k in _st]
        _probe_rows.append({"depth": _dep, "date": _dt,
                            "n_instruments": Q.instrument_count(_dt, _dep),
                            "solver": "converged",
                            "max_diff_bp": max(_diffs), "median_diff_bp": float(np.median(_diffs))})
    except Exception as _e:                                    # noqa: BLE001
        _probe_rows.append({"depth": _dep, "date": _dt,
                            "n_instruments": Q.instrument_count(_dt, _dep),
                            "solver": type(_e).__name__,
                            "max_diff_bp": np.nan, "median_diff_bp": np.nan})
PROBE = pd.DataFrame(_probe_rows)
print("Q20 curve at the shallow depths the 12-floor used to discard:")
print(PROBE.to_string(index=False))
print(f"\nnetwork_calls_blocked delta = {network_calls_blocked() - _b0}")
assert network_calls_blocked() == _b0, "the probe must be entirely offline"
assert (PROBE["solver"] == "converged").any(), "the solve must work below depth 12"
_clean = PROBE[PROBE["solver"] == "converged"]
print(f"\n{len(_clean)}/{len(PROBE)} shallow depths solve; "
      f"median |settle - Q20 fwd| across them = "
      f"{_clean['median_diff_bp'].median():.2f}bp against a 2.0bp gate.")

# %% [markdown]
# ## 4. The third defect — the universe counted keys the fetcher cannot read
#
# The EOD request alias is `{iso_timestamp}-{TICKER}-{SOURCE}` with the timestamp
# in **New York local time**, so its UTC offset flips with daylight saving. The
# store also holds 17:00 keys stamped `+00:00` and `-06:00`, written by other
# jobs. They match the key regex.
#
# Counting them does not merely overstate coverage — it manufactures dates that
# then **miss inside `cache_only()` and reach for the vendor**. The first rebuild
# after the depth fix logged **906 blocked outbound requests across 43 dates**;
# with the offset filter that fell to **4 across 3**.

# %%
_ny = {d: S2.ny_utc_offset(d) for d in
       (datetime.date(2025, 6, 20), datetime.date(2025, 11, 3))}
print("New York UTC offset at 17:00:", _ny)
assert _ny[datetime.date(2025, 6, 20)] == "-04:00"
assert _ny[datetime.date(2025, 11, 3)] == "-05:00"

_lax = Q.strip_depth_by_date(QCFG, min_depth=1, require_readable_offset=False)
_ok = Q.strip_depth_by_date(QCFG, min_depth=1)
_mismatch = pd.DataFrame([
    {"date": d, "depth_any_offset": _lax[d], "depth_readable": _ok.get(d, 0)}
    for d in sorted(_lax) if _lax[d] != _ok.get(d, 0)])
print(f"\ndates whose scanned depth exceeds their RESOLVABLE depth: {len(_mismatch)}")
if len(_mismatch):
    _mm = _mismatch.copy()
    _mm["year"] = _mm["date"].map(lambda x: x.year)
    print(_mm.groupby("year").size().to_string())
    print(_mm.nlargest(6, "depth_any_offset").to_string(index=False))

# %% [markdown]
# ## 5. The rebuilt Q20 panel, against the shipped one
#
# Built by `scripts/strat2_q20_build.py`, unchanged except that it now retries
# its skipped dates **serially**. Six workers share eight sqlite shards, and
# contention surfaces as a cache MISS rather than a lock error — the MDP shrugs,
# reaches for the vendor, and `cache_only()` turns that into an exception. The
# result was a build whose skipped dates changed from run to run (2022-06-22
# dropped in one pass and priced cleanly in the next, 0 blocked requests). That
# nondeterminism is fatal to a before/after comparison.

# %%
BASE = pd.read_parquet(DATA / "ca_coverage_baseline_q20_panel.parquet")
PANEL = pd.read_parquet(DATA / "strat2_q20_panel.parquet")
for _f in (BASE, PANEL):
    _f["date"] = pd.to_datetime(_f["date"])
    _f["year"] = _f["date"].dt.year
PANEL = PANEL[PANEL["date"] <= pd.Timestamp(CFG.end)]

print(f"shipped : {len(BASE):>7,} rows  {BASE['date'].nunique():>5,} dates  "
      f"{BASE['date'].min().date()} .. {BASE['date'].max().date()}")
print(f"rebuilt : {len(PANEL):>7,} rows  {PANEL['date'].nunique():>5,} dates  "
      f"{PANEL['date'].min().date()} .. {PANEL['date'].max().date()}")

# %% [markdown]
# ### 5a. THE INVARIANT — this is a coverage fix, so nothing may move
#
# Join the two panels on `(date, rank)` and require exact equality on every
# quantity a reader could have quoted: both rate sources, both adjustments, the
# swap leg, the gate columns, and the **zero-convexity control** (`ca_synthetic_bp`
# and the two measurements it must be read against). Not `approx` — exact.

# %%
_KEY = ["date", "rank"]
_INVARIANT = [c for c in (
    "ca_bp", "ca_bp_q20", "ca_bp_settle", "pack_rate_q20", "pack_rate_settle",
    "swap_rate", "time_weight", "t_mid", "max_settle_diff_bp", "mean_settle_diff_bp",
    "fwd_spread_bp", "q20_n_nodes", "q20_n_nodes_inside", "q20_spans_window",
    "ca_synthetic_bp", "ca_synthetic_pred_bp", "swap_fwd_spread_bp",
    "swap_n_nodes_inside", "annual_qq_gap_bp",
    "gate_covered", "gate_resolved", "gate_settle_agrees", "gate_ok",
) if c in BASE.columns and c in PANEL.columns]

_m = BASE[_KEY + _INVARIANT].merge(PANEL[_KEY + _INVARIANT], on=_KEY,
                                   suffixes=("_old", "_new"), how="inner")
_moved = {}
for _c in _INVARIANT:
    _a, _b = _m[f"{_c}_old"], _m[f"{_c}_new"]
    if _a.dtype == bool or _b.dtype == bool:
        _n = int((_a.astype(bool) != _b.astype(bool)).sum())
    else:
        _a, _b = _a.astype(float), _b.astype(float)
        _n = int((((_a - _b).abs() > 0) | (_a.isna() != _b.isna())).sum())
    if _n:
        _moved[_c] = _n
print(f"common (date, rank) rows: {len(_m):,} of {len(BASE):,} shipped rows "
      f"({100 * len(_m) / len(BASE):.2f}%)")
print(f"columns checked for exact equality: {len(_INVARIANT)}")
print(f"columns that moved: {_moved if _moved else 'NONE'}")
assert not _moved, f"a coverage fix moved a published value: {_moved}"

_lost = BASE[_KEY].merge(PANEL[_KEY], on=_KEY, how="left", indicator=True)
_lost = _lost[_lost["_merge"] == "left_only"]
_lost_dates = sorted(set(_lost["date"].dt.date))
print(f"\nshipped rows absent from the rebuild: {len(_lost)} on {len(_lost_dates)} "
      f"date(s): {_lost_dates}")

# %% [markdown]
# **The one lost date, and why it is not a regression.** 2018-12-06 scans at
# contiguous depth 19 with correctly-stamped keys, so the universe is right, but
# `STIRFutureMDP.get_data` misses on it offline at every depth tried (12/16/20)
# and raises inside `cache_only()`. Its cached payload decayed between the
# shipped build (15-Aug) and this one. It is not recoverable: a deliberate direct
# fetch on the full 20-contract strip — the last call of the warm budget —
# returned `RuntimeError: BARCHART_STIRF-RL returned no data for requested STIR
# futures`. The vendor no longer serves that date. Reported as lost to cache
# decay rather than papered over.

# %%
_probe = {"date": "2018-12-06", "scanned_depth": DEPTHS.get(datetime.date(2018, 12, 6)),
          "offline_settles": "CacheMissOffline at depth 12/16/20",
          "direct_fetch": "RuntimeError: source returned no data",
          "rows_lost": int(len(_lost))}
print(json.dumps(_probe, indent=1))
assert len(_lost_dates) <= 1, "more than one shipped date vanished — investigate"

# %% [markdown]
# ### 5b. Coverage, per year per rank, split by what paid for it
#
# The warm keeps a ledger of every date it fetched, so attribution is exact
# rather than inferred: a recovered date that appears in the ledger was bought
# with network, and every other recovered date was free.

# %%
print(f"warm ledger: {len(WARMED)} dates fetched")
if WARM_SUMMARY:
    print(json.dumps({k: v for k, v in WARM_SUMMARY.items()
                      if k not in ("window",)}, indent=1))


def coverage_split(base: pd.DataFrame, new: pd.DataFrame, ranks=(1, 5, 9, 13, 17),
                   gated: bool = False) -> pd.DataFrame:
    """Dates per (year, rank) before and after, split code vs fetch."""
    b = base[base["gate_ok"]] if gated else base
    n = new[new["gate_ok"]] if gated else new
    rows = []
    for r in ranks:
        br = b[b["rank"] == r]
        nr = n[n["rank"] == r]
        have = set(br["date"].dt.date)
        for y in sorted(set(nr["year"]) | set(br["year"])):
            gained = {d for d in nr[nr["year"] == y]["date"].dt.date if d not in have}
            rows.append({
                "rank": r, "year": int(y),
                "before": int(br[br["year"] == y]["date"].nunique()),
                "after": int(nr[nr["year"] == y]["date"].nunique()),
                "by_code": len(gained - WARMED),
                "by_fetch": len(gained & WARMED),
            })
    out = pd.DataFrame(rows)
    out["delta"] = out["after"] - out["before"]
    return out


COV = coverage_split(BASE, PANEL)
COV_GATED = coverage_split(BASE, PANEL, gated=True)
print("\nDATES PER YEAR PER RANK — all rows (rank 13 = Blues, 17 = Golds)")
for _c in ("before", "after", "by_code", "by_fetch"):
    print(f"\n  {_c}:")
    print(COV.pivot(index="year", columns="rank", values=_c)
          .fillna(0).astype(int).to_string())
COV.to_csv(DATA / "ca_coverage_by_rank.csv", index=False)
COV_GATED.to_csv(DATA / "ca_coverage_by_rank_gated.csv", index=False)

_tot = COV.groupby("rank")[["before", "after", "by_code", "by_fetch"]].sum()
_tot["delta"] = _tot["after"] - _tot["before"]
print("\nTOTAL across all years:")
print(_tot.to_string())
print(f"\nrecovered by CODE alone : {int(COV['by_code'].sum()):,} (date, rank) pairs")
print(f"recovered by FETCHING   : {int(COV['by_fetch'].sum()):,}")

# %% [markdown]
# ### 5c. Coverage without correctness loss — the zero-convexity control on the NEW rows
#
# The recovered dates are new rows, so the exact-equality test of 5a says nothing
# about them. The control that does is the one built for exactly this: recompute
# the identical arithmetic with the four futures rates replaced by the **swap
# curve's own** IMM×IMM forwards. Those carry no convexity by construction, so
# `ca_synthetic_bp` must be ~0 — and its power (`swap_fwd_spread_bp`) has to be
# reported next to it or a 0.00 reading is an absence of evidence rather than
# evidence.

# %%
_old_keys = set(map(tuple, BASE[["date", "rank"]].to_numpy()))
NEWROWS = PANEL[~PANEL[["date", "rank"]].apply(tuple, axis=1).isin(_old_keys)]
print(f"rows present only in the rebuild: {len(NEWROWS):,}")

_ctl = pd.DataFrame({
    "n": [len(BASE), len(NEWROWS)],
    "ca_synthetic_bp median": [BASE["ca_synthetic_bp"].median(),
                               NEWROWS["ca_synthetic_bp"].median()],
    "|ca_synthetic_bp| p95": [BASE["ca_synthetic_bp"].abs().quantile(.95),
                              NEWROWS["ca_synthetic_bp"].abs().quantile(.95)],
    "swap_fwd_spread_bp median": [BASE["swap_fwd_spread_bp"].median(),
                                  NEWROWS["swap_fwd_spread_bp"].median()],
    "annual_qq_gap_bp median": [BASE["annual_qq_gap_bp"].median(),
                                NEWROWS["annual_qq_gap_bp"].median()],
    "gate_ok rate": [BASE["gate_ok"].mean(), NEWROWS["gate_ok"].mean()],
}, index=["shipped rows", "recovered rows"]).round(4)
print("\nzero-convexity control, shipped rows vs recovered rows:")
print(_ctl.to_string())
assert abs(NEWROWS["ca_synthetic_bp"].median()) < 0.5, (
    "the zero-convexity control must stay near zero on recovered rows")

# %% [markdown]
# The `annual_qq_gap_bp` column is the other standing control: the matched swap
# priced at the `usd_irs` spec default (annual fixed) minus the
# quarterly/quarterly rate Citi specifies. It is a **prediction** with no free
# parameter, `0.375·r²`, and it must stay a diagnostic rather than becoming a
# correction. Its median above confirms the recovered rows are priced on the same
# quarterly/quarterly convention as the shipped ones.

# %%
_r = PANEL["swap_rate"].to_numpy(float)
_pred = 0.375 * _r ** 2
_obs = PANEL["annual_qq_gap_bp"].to_numpy(float)
_ok = np.isfinite(_pred) & np.isfinite(_obs)
print(f"annual-vs-QQ gap: observed median {np.median(_obs[_ok]):.3f}bp, "
      f"predicted 0.375*r^2 median {np.median(_pred[_ok]):.3f}bp, "
      f"corr {np.corrcoef(_obs[_ok], _pred[_ok])[0, 1]:+.4f}")
assert np.corrcoef(_obs[_ok], _pred[_ok])[0, 1] > 0.9, (
    "the matched swap is no longer quarterly/quarterly")

# %% [markdown]
# ## 6. The near-pack panel, rebuilt the same way
#
# Same defect, different route: `local_cached_dates` is all-or-nothing over the
# full `n_contracts` strip (`all(s in have[d] for s in names)`), and `build_panel`
# then demanded `rank_start + n_packs + 2` resolved contracts before it would
# keep **any** pack. `ca_snapshot` already skips the windows it cannot quote, so
# neither test bought correctness.

# %%
_NEAR_F, _NEAR_R = DATA / "strat2_panel.parquet", DATA / "strat2_rates.parquet"
_strict = S2.local_cached_dates(NEAR)
_perm = S2.local_cached_dates(NEAR, min_contracts=CFG.min_priced_contracts)
print(f"strict universe (full {NEAR.n_contracts}-contract strip): {len(_strict):,} dates")
print(f"permissive universe (>= {CFG.min_priced_contracts} contiguous): {len(_perm):,} dates")

if _NEAR_F.exists() and _NEAR_R.exists() and os.environ.get("CA_REPAIR_REUSE", "1") == "1":
    NEAR_PANEL = pd.read_parquet(_NEAR_F)
    NEAR_RATES = pd.read_parquet(_NEAR_R)
    print(f"loaded cached near-pack panel {NEAR_PANEL.shape}")
else:
    _t0 = time.time()
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    _fut = STIRFutureMDP(source=NEAR.futures_source)
    _swp = IRSwapsMDP(source=NEAR.swap_source)
    with cache_only():
        NEAR_PANEL, NEAR_RATES = S2.build_panel(_perm, NEAR, futures_mdp=_fut,
                                                swaps_mdp=_swp, progress=False)
    NEAR_PANEL.to_parquet(_NEAR_F)
    NEAR_RATES.to_parquet(_NEAR_R)
    print(f"built near-pack panel {NEAR_PANEL.shape} in {time.time() - _t0:.0f}s")

NEAR_PANEL["date"] = pd.to_datetime(NEAR_PANEL["date"])
NEAR_PANEL = NEAR_PANEL[NEAR_PANEL["date"] <= pd.Timestamp(CFG.end)]
NEAR_PANEL["year"] = NEAR_PANEL["date"].dt.year

NEAR_BASE = pd.read_parquet(DATA / "ca_coverage_baseline_near_panel.parquet")
NEAR_BASE["date"] = pd.to_datetime(NEAR_BASE["date"])
NEAR_BASE["year"] = NEAR_BASE["date"].dt.year
print(f"\nshipped near-pack: {len(NEAR_BASE):,} rows, "
      f"{NEAR_BASE['date'].nunique():,} dates, "
      f"{NEAR_BASE['date'].min().date()} .. {NEAR_BASE['date'].max().date()}")
print(f"rebuilt near-pack: {len(NEAR_PANEL):,} rows, "
      f"{NEAR_PANEL['date'].nunique():,} dates, "
      f"{NEAR_PANEL['date'].min().date()} .. {NEAR_PANEL['date'].max().date()}")

# %%
_NK = ["date", "rank"]
_NI = [c for c in ("ca_bp", "pack_rate", "swap_rate", "time_weight", "t_mid")
       if c in NEAR_BASE.columns and c in NEAR_PANEL.columns]
_nm = NEAR_BASE[_NK + _NI].merge(NEAR_PANEL[_NK + _NI], on=_NK,
                                 suffixes=("_old", "_new"), how="inner")
_nmoved = {c: int((((_nm[f"{c}_old"].astype(float) - _nm[f"{c}_new"].astype(float)).abs() > 0)
                   | (_nm[f"{c}_old"].isna() != _nm[f"{c}_new"].isna())).sum())
           for c in _NI}
_nmoved = {k: v for k, v in _nmoved.items() if v}
print(f"common (date, rank) rows: {len(_nm):,} of {len(NEAR_BASE):,} shipped "
      f"({100 * len(_nm) / len(NEAR_BASE):.2f}%)")
print(f"columns that moved: {_nmoved if _nmoved else 'NONE'}")
assert not _nmoved, f"the near-pack rebuild moved a published value: {_nmoved}"

NEAR_COV = coverage_split(NEAR_BASE, NEAR_PANEL, ranks=(2, 5, 10))
print("\nNEAR-PACK dates per year per rank:")
for _c in ("before", "after", "by_code", "by_fetch"):
    print(f"\n  {_c}:")
    print(NEAR_COV.pivot(index="year", columns="rank", values=_c)
          .fillna(0).astype(int).to_string())
NEAR_COV.to_csv(DATA / "ca_coverage_near_by_rank.csv", index=False)

# %% [markdown]
# ## 7. Trimming is a choice, and it is now an explicit one
#
# `trim_to_contiguous_run` kept the **longest** gap-free run, not the latest.
# Measured at the shipped call sites that rule truncated the near-pack series at
# **2024-05-08** — literally the "~May-2024" in the complaint — and cut the Q20
# near band from 518 dates to 301, discarding every date in 2023, 2024 and 2025
# because the longest gap-free block happened to sit in 2021.
#
# Coverage is reported all three ways rather than one being chosen in silence.

# %%
_rows = []
for _keep in ("longest", "latest", "none"):
    _p, _r = S2.trim_to_contiguous_run(NEAR_PANEL, NEAR_RATES, keep=_keep,
                                       max_gap_days=CFG.gap_days)
    _dd = pd.DatetimeIndex(sorted(_p["date"].unique()))
    _rows.append({"keep": _keep, "dates": len(_dd), "rows": len(_p),
                  "first": _dd[0].date(), "last": _dd[-1].date()})
TRIM = pd.DataFrame(_rows)
print("near-pack panel under each trim rule:")
print(TRIM.to_string(index=False))
print("\nevery contiguous run in the rebuilt near-pack panel:")
print(S2.coverage_by_run(NEAR_PANEL, max_gap_days=CFG.gap_days).to_string(index=False))

NEAR_TRIM, NEAR_TRIM_RATES = S2.trim_to_contiguous_run(
    NEAR_PANEL, NEAR_RATES, keep=CFG.trim_keep, max_gap_days=CFG.gap_days)
print(f"\nkeeping {CFG.trim_keep!r}: {NEAR_TRIM['date'].nunique():,} dates")

# %% [markdown]
# ## 8. What un-trimming would have broken, and the guard that stops it
#
# `rolling(252)` counts **rows**. On a gappy panel that is not a time window at
# all, and nothing in pandas says so. The measured spans on the shipped panel:
# the "1Y" window as of 2024-01-03 covered **883 calendar days**, and as of
# 2025-03-05 it covered **1,289**. That was invisible only because the trim
# deleted the gappy tail before anyone computed a z-score on it.
#
# So restoring coverage without `window_span_tolerance` would replace a truncated
# series with a silently wrong one. Below: the same panel, same windows, guard
# off and on.

# %%
_span_rows = []
for _tol, _label in ((0.0, "guard OFF (legacy)"), (CFG.window_span_tolerance, "guard ON")):
    _cfg = dataclasses.replace(NEAR, window_span_tolerance=_tol)
    _ts = S2.panel_timeseries(NEAR_PANEL, _cfg)
    _span_rows.append({
        "setting": _label,
        "ca_z3m finite": int(_ts["ca_z3m"].notna().to_numpy().sum()),
        "ca_z1y finite": int(_ts["ca_z1y"].notna().to_numpy().sum()),
        "rv finite": int(_ts["rv"].notna().to_numpy().sum()),
    })
SPAN = pd.DataFrame(_span_rows)
print(SPAN.to_string(index=False))

_idx = pd.DatetimeIndex(sorted(NEAR_PANEL["date"].unique()))
_ok252 = S2.window_span_ok(_idx, NEAR.z_window_1y, CFG.window_span_tolerance)
_bad = _idx[~_ok252.to_numpy()]
_spans = pd.Series(_idx).diff(NEAR.z_window_1y - 1).dt.days
print(f"\n1Y windows rejected for span: {int((~_ok252).sum())} of {len(_idx)}")
print(f"worst 252-row calendar span in the panel: "
      f"{int(np.nanmax(_spans.to_numpy())):,} days (nominal ~365)")
assert SPAN.loc[1, "ca_z1y finite"] <= SPAN.loc[0, "ca_z1y finite"], (
    "the span guard can only remove statistics, never add them")

# %% [markdown]
# ## 9. Stop the charts interpolating
#
# `connectgaps=False` was already set on the CA traces, and it was **inert**. It
# only breaks a line where `y` is null; the frames were built by an inner join on
# observed dates, so they held zero NaN rows and plotly drew straight through the
# holes — correctly by its own rules, wrongly by ours. A grep for the flag
# therefore cannot answer the question either, which is why the audit that found
# this parsed the *rendered* plotly arrays.
#
# The fix is upstream of plotly and is two things, neither sufficient alone:
# reindex onto the business-day grid so the holes become NaN rows, then set the
# flag so it has something to break on. `RVUtils.ConvexityRV.ca_plots` packages
# both, plus the observation count — a sparse line and a dense line look
# identical once drawn, and the count is the only thing on the chart that
# distinguishes them.

# %%
_CA = "ca_bp_settle"
COLOURS = {"Whites (rank 1)": 1, "Reds (rank 5)": 5, "Greens (rank 9)": 9,
           "Blues (rank 13)": 13, "Golds (rank 17)": 17}
SERIES = {}
for _name, _rk in COLOURS.items():
    _s = (PANEL[(PANEL["rank"] == _rk) & PANEL["gate_ok"]]
          .set_index("date")[_CA].sort_index())
    if len(_s):
        SERIES[_name] = _s

print("gaps longer than %d days, per pack colour, in the REBUILT panel:" % CFG.gap_days)
for _name, _s in SERIES.items():
    _g = CAP.gap_table(_s.index, max_gap_days=CFG.gap_days)
    print(f"\n{_name}: {CAP.coverage_note(_s)}")
    print(("  no gap" if not len(_g)
           else _g.head(4).to_string(index=False).replace("\n", "\n  ")))

# %%
PALETTE = {"Whites (rank 1)": "#1f4e79", "Reds (rank 5)": "#c0392b",
           "Greens (rank 9)": "#2e8b57", "Blues (rank 13)": "#1c7ed6",
           "Golds (rank 17)": "#d98b00"}

figca = go.Figure()
for _name, _s in SERIES.items():
    figca.add_trace(go.Scatter(**CAP.line(
        CAP.bday_reindex(_s, start=CFG.start, end=CFG.end),
        name=f"{_name} — {CAP.coverage_note(_s)}",
        line=dict(color=PALETTE.get(_name), width=1.8))))
figca.update_layout(
    title=("<b>Convexity adjustment by pack, rebuilt — every hole drawn as a hole</b>"
           "<br><sub>settle-marked CA, gate-passed rows only, reindexed onto the "
           "business-day grid so <code>connectgaps=False</code> has NaN rows to "
           "break on. The legend carries each series' observation count.</sub>"),
    yaxis=dict(title="convexity adjustment (bp)"),
    xaxis=dict(title=None), template="plotly_white", height=520,
    legend=dict(orientation="h", yanchor="bottom", y=-0.34, x=0))
figca.show()

# %% [markdown]
# ### The same chart the old way, for one series, so the defect is visible
#
# One trace, two treatments, identical data. The observed-dates-only version is
# what every CA chart in this repo was drawing.

# %%
_blue = (SERIES["Blues (rank 13)"] if "Blues (rank 13)" in SERIES
         else list(SERIES.values())[-1])
figcmp = go.Figure()
figcmp.add_trace(go.Scatter(
    x=list(_blue.index), y=_blue.to_numpy(float), mode="lines",
    name=f"observed dates only (what was drawn) — {len(_blue)} pts",
    line=dict(color="#c0392b", width=2.4, dash="dot"), connectgaps=False))
figcmp.add_trace(go.Scatter(**CAP.line(
    CAP.bday_reindex(_blue, start=CFG.start, end=CFG.end),
    name=f"business-day grid (honest) — {CAP.coverage_note(_blue)}",
    line=dict(color="#1c7ed6", width=2.0))))
figcmp.update_layout(
    title=("<b>Why <code>connectgaps=False</code> was inert</b>"
           "<br><sub>Identical data. The dotted red line has the flag set and no "
           "NaN rows to act on, so it bridges every hole; the solid blue line is "
           "the same series on a business-day grid.</sub>"),
    yaxis=dict(title="convexity adjustment (bp)"),
    xaxis=dict(title=None), template="plotly_white", height=470,
    legend=dict(orientation="h", yanchor="bottom", y=-0.30, x=0))
figcmp.show()

# %% [markdown]
# ### Coverage as its own series — sparsity you can read off the axis
#
# The availability columns the rebuild writes onto every row (`strip_depth`,
# `max_rank_available`) turn "why does the line stop" from an inference into a
# lookup.

# %%
_avail = (PANEL.groupby("date")["max_rank_available"].max()
          .pipe(CAP.bday_reindex, start=CFG.start, end=CFG.end))
figav = go.Figure()
figav.add_trace(go.Scatter(**CAP.line(_avail, name="deepest quotable pack rank",
                                      line=dict(color="#495057", width=1.5))))
for _rk, _lab in ((13, "Blues needs 13"), (17, "Golds needs 17")):
    figav.add_hline(y=_rk, line=dict(color="#adb5bd", width=1, dash="dash"),
                    annotation_text=_lab, annotation_position="top left")
figav.update_layout(
    title=("<b>Why each series stops where it stops</b>"
           "<br><sub>deepest pack window the local SR3 strip supports on each "
           "date (<code>strip_depth − 3</code>). Recorded on every panel row, so "
           "sparsity is data rather than absence.</sub>"),
    yaxis=dict(title="deepest quotable rank"),
    xaxis=dict(title=None), template="plotly_white", height=430, showlegend=False)
figav.show()

# %% [markdown]
# ## 10. Controls — coverage must not be bought with correctness
#
# Four standing controls, re-run on the rebuilt panel: the CA-quality diagnostic,
# the staleness detector on the raw settle panel, the gate's own incidence, and
# the settle-vs-Q20 agreement that the whole deep-pack argument rests on.

# %%
GATE = Q.gate_summary(PANEL)
print("gate incidence by year on the rebuilt panel:")
print(GATE.round(3).to_string())

_cmp = Q.rate_source_comparison(PANEL[PANEL["gate_ok"]])
_deep = _cmp.reset_index()
_deep = _deep[_deep["rank"] >= 9]
print(f"\ngate-passed deep rows (rank >= 9): median |CA(Q20) - CA(settle)| = "
      f"{_deep['abs_diff_median_bp'].median():.4f}bp, "
      f"median corr = {_deep['corr'].median():.4f}")
assert _deep["abs_diff_median_bp"].median() < 0.5, (
    "the gate stopped guaranteeing that the Q20 forward IS the settlement mark")

# %%
SETTLES = pd.read_parquet(DATA / "strat2_q20_settles.parquet")
# The detector needs a LIQUID reference column to establish that the market moved
# at all -- otherwise a quiet day reads as a stale day. The rank-1 pack rate is
# that reference, exactly as `strat2_q20_deep_packs` builds it.
_S = SETTLES.copy()
_S["FRONT"] = 100.0 - (PANEL[PANEL["rank"] == 1].set_index("date")["pack_rate_settle"]
                       .reindex(_S.index))
_st = ca_staleness.flag_stale_prices(_S, reference="FRONT")
_st = _st[_st["contract"] != "FRONT"]
_rate = float(_st["stale_run"].mean())

_recent = _st[pd.to_datetime(_st["date"]).dt.year >= 2024]
print(f"staleness detector on the rebuilt settle panel: "
      f"{_rate * 100:.2f}% of {len(_st):,} (date, contract) cells in a stale run; "
      f"on 2024+ rows alone {_recent['stale_run'].mean() * 100:.2f}% "
      f"({len(_recent):,} cells)")
assert _rate < 0.15, "the recovered dates brought stale settles with them"

# %% [markdown]
# ## 11. Citi Figure 58 tie-out — the known answer, unchanged
#
# The published SOFR screen, close 6/9/2023, 13 rows, windows 5..17. This is the
# check that the repair did not disturb the number the whole module was built to
# reproduce.

# %%
_D58 = pd.Timestamp("2023-06-09")
_day = PANEL[(PANEL["date"] == _D58) & (PANEL["rank"].between(5, 17))].set_index("rank")
_ours = _day["ca_bp_q20"]
_citi = pd.Series({v["rank"]: v["ca_bp"] for v in Q.CITI_SOFR_20230609.values()})
_j = pd.DataFrame({"ours_bp": _ours, "citi_bp": _citi}).dropna()
_j["diff_bp"] = _j["ours_bp"] - _j["citi_bp"]
print(_j.round(3).to_string())
_corr = float(np.corrcoef(_j["ours_bp"], _j["citi_bp"])[0, 1])
_blues = float(_j.loc[13, "ours_bp"])
print(f"\nrows {len(_j)}  corr {_corr:.4f}  max |diff| {_j['diff_bp'].abs().max():.2f}bp"
      f"  Blues {_blues:.2f} vs Citi 15.40")
assert len(_j) == 13, "the tie-out must still reach all 13 published rows"
assert _corr > 0.96, f"Figure 58 correlation regressed to {_corr:.4f}"
assert _j["diff_bp"].abs().max() < 4.0
assert abs(_blues - 15.40) < 1.0, f"Blues moved to {_blues:.2f}"

# %% [markdown]
# ## 12. What was fetched, what it cost, and what remains

# %%
REMAINING = {}
if WARM_SUMMARY:
    REMAINING = {
        "calls_made": WARM_SUMMARY.get("calls_made"),
        "wall_clock_s": WARM_SUMMARY.get("wall_clock_s"),
        "dates_gained_depth": WARM_SUMMARY.get("dates_gained_depth"),
        "dates_at_target": WARM_SUMMARY.get("dates_at_target"),
        "remaining_dates_in_window": WARM_SUMMARY.get("remaining_dates"),
        "dates_protected_already_deep": WARM_SUMMARY.get("dates_protected_already_deep"),
    }
_short = {d: v for d, v in NOW.items() if v < 20 and d.year >= 2024}
REMAINING["dates_2024plus_still_below_depth_20"] = len(_short)
REMAINING["dates_2024plus_still_below_depth_16"] = sum(1 for v in _short.values() if v < 16)
REMAINING["resume_command"] = (
    "python scripts/warm_sr3_deferred.py --start 2024-01-01 --end 2026-08-18 "
    "--max-calls 400")
print(json.dumps(REMAINING, indent=1, default=str))

SUMMARY = {
    "built": datetime.datetime.now().isoformat(timespec="seconds"),
    "window": [str(CFG.start), str(CFG.end)],
    "q20_panel": {"rows_before": int(len(BASE)), "rows_after": int(len(PANEL)),
                  "dates_before": int(BASE["date"].nunique()),
                  "dates_after": int(PANEL["date"].nunique())},
    "near_panel": {"rows_before": int(len(NEAR_BASE)), "rows_after": int(len(NEAR_PANEL)),
                   "dates_before": int(NEAR_BASE["date"].nunique()),
                   "dates_after": int(NEAR_PANEL["date"].nunique())},
    "recovered_by_code": int(COV["by_code"].sum()),
    "recovered_by_fetch": int(COV["by_fetch"].sum()),
    "published_values_moved": 0,
    "shipped_rows_lost": int(len(_lost)),
    "shipped_dates_lost": [str(d) for d in _lost_dates],
    "fig58": {"rows": int(len(_j)), "corr": round(_corr, 4),
              "max_abs_diff_bp": round(float(_j["diff_bp"].abs().max()), 3),
              "blues_bp": round(_blues, 2), "citi_blues_bp": 15.40},
    "warm": REMAINING,
}
(DATA / "ca_coverage_repair_summary.json").write_text(
    json.dumps(SUMMARY, indent=2, default=str), encoding="utf-8")
print("\n" + json.dumps(SUMMARY, indent=1, default=str))
print(f"\nnetwork_calls_blocked at end of notebook: {network_calls_blocked()}")
