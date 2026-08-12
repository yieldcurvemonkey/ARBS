"""Notebook helper for the dealer-direction pipeline -- tested, cached, silent.

The notebook that sits beside this file is narrative and plots. Every API
mismatch, every convention trap and every cache decision lives **here**, behind
functions that return data and print nothing, so the notebook never becomes the
place where a signature is discovered.

    import sys; sys.path.insert(0, r"C:\\Users\\chris\\clee\\ARBS-dd\\notebooks\\dealer_direction")
    import dd_nb
    cfg  = dd_nb.config()
    pipe = dd_nb.run_pipeline(cfg)          # legs -> units -> ... -> daily
    trace = dd_nb.one_trade(pipe, pipe.calls.frame["unit_key"].iloc[0])

THE PIPELINE, AND WHOSE CALL SEQUENCE IT IS
===========================================
``BT/dd_signals/s2_positioning.py`` built 371 tape days through these modules
and is the reference; this file follows its sequence rather than re-deriving
one::

    universe.load_legs      -> the raw tape frame, read-only
    universe.unit_frame     -> one row per unit + its exclusion (the accounting)
    universe.build_universe -> the kept `Unit` objects + the excluded rows
    midprice.UnitRepricer   -> per-leg mid / PV01 / payer-frame NPV, T-1min snap
    probability / upfront /
      package_price         -> the three direction rules
    krd.KrdProjector        -> the 28-pillar signed key-rate profile
    ladder.unit_ladder_rows -> weight = conventions.signed_weight(p) = 2p-1
    indicator.daily_levels  -> the ten TENOR10 buckets, per availability date

THE PINNED CONVENTION (``conventions.py``), restated because everything turns on it
-----------------------------------------------------------------------------
``customer pays fixed -> dealer RECEIVED fixed -> dealer long duration ->
delta_dv01 > 0``; ``p = p(customer paid fixed)``; ``ladder weight = 2p - 1``.

WHERE THIS DIVERGES FROM ``s2_positioning``, AND WHY
====================================================
Four deliberate differences. Each one is a *notebook* requirement, not a better
idea about the signal, and s2's choice is stated beside it.

1. **All three rules, including ``PACKAGE_PRICE_VS_MODEL``.** s2's population
   loop called ``conventions.base_orientation(kind, n_legs, rule)`` on every
   unit, and for a ``PKG-N`` that call **succeeds** under ``RULE_UPFRONT``
   (`conventions.py:122` returns ``(1,) * n_legs``). So s2 did not drop the
   recovered packages -- it routed them through the upfront rule with *every
   leg pointed the same way*, discarding the internal orientation the package
   price recovers. That is precisely the seam
   ``krd.received_hypothesis_signs`` documents. Measured on 2025-06-17: 7 units
   land in s2's cache under ``NPV_VS_UPFRONT``; here they are oriented from
   their own package price. **Routing is by ``kind`` first**, so a PKG can
   never fall into the upfront branch.

2. **Lifecycle units are kept, as their own series.** s2 dropped them
   (``if u.rate_index != "SOFR" or u.is_lifecycle: continue``) because a
   termination is a different signal. The ladder already separates them
   (``ladder.SERIES_FLOW`` / ``SERIES_LIFECYCLE``), and the pilot window is
   chosen post-2024-07 precisely because terminations exist there -- a pipeline
   walk-through that cannot show one is missing a population. ``Config
   .include_lifecycle`` turns them off to reproduce s2.

3. **No 15:00 ET availability cut.** s2 re-stamped every print onto the next
   15:00 ET mark so a bucket-day panel would be *takeable* at that mark. That is
   a property of s2's regression, not of the ladder: the ladder's own clock is
   ``ladder.visibility_date`` (the New York session date of the Part 43
   availability stamp), and ``daily()`` here uses it unmodified.

4. **SOFR only, following s2** (``Config.indices``). FED_FUNDS is ~3% of
   universe DV01 and doubles the per-block KRD solver builds. It is a one-word
   config change and not a code change -- ``config(indices=("SOFR",
   "FED_FUNDS"))`` -- but **the self-test never runs it**, so treat it as
   supported-by-construction rather than verified. ``snapshot.CURVE_FOR`` has a
   Fed Funds curve and ``midprice`` refuses a missing one by name
   (``UNSUPPORTED_INDEX``), so the failure mode if it does not work is a named
   exclusion rather than a wrong number -- but it is untested here and the
   window carries 254 kept FED_FUNDS units that would arrive with it.

TWO CONVENTION TRAPS THIS MODULE HANDLES, BOTH MEASURED
=======================================================
**A. The upfront rule's ``dealer_sign`` and its ``p`` are allowed to disagree,
and the ladder refuses that.** ``upfront.classify``'s docstring says so
explicitly: ``dealer_sign`` is the point call (mid at face value) while ``p``
marginalises over the mid's own error, and where they differ
``FLAG_SIGN_FRAGILE`` fires. But ``ladder._assert_weight_agrees_with_side``
raises when ``sign(2p-1) != dealer_sign``. s2 never hit this because it merged
weights onto the KRD frame by hand instead of calling the ladder. Here the
``DirectionCall`` carries the **weight's own side** -- the ladder aggregates
``2p-1``, so that is the side that is actually loaded -- and the point call
travels beside it as ``dealer_sign_point``, with the disagreement counted in
``CallsResult.diagnostics["sign_fragile_disagreements"]``.

**B. The package rule produces no ``p``.** ``package_price.classify`` returns a
sign and a ``deviation_bps``; nothing has fitted a mixture on package residuals
(the S3 gap -- ``scratch/ddseam_ladder_trace.py`` traces the ladder *raising* on
a ``p=None`` call). So ``p`` is **borrowed**: the pooled rate-rule fit for the
unit's bucket, with ``b0`` forced to zero. Zeroing the bias is not a tidy-up --
the rate-rule ``b0`` is in bp of the *structure's quoted price* and the package
deviation is in bp of *package DV01*, so it does not transfer -- and it also
makes ``sign(2p-1) == conventions.dealer_side(dev) == the rule's own
dealer_sign`` by construction, which is asserted per unit. The lifecycle flip is
``p -> 1-p`` (exactly ``sigmoid(-z) = 1 - sigmoid(z)``, the same negation
``upfront._edge_from_dev`` applies). Every such call is labelled
``tau_bucket = "BORROWED_B0_ZEROED:<donor>"``. **The borrowed tau is on the
wrong scale**, so these ``p`` are over- or under-saturated by an unknown factor;
the notebook must present them as the S3 gap illustrated, not solved.

THE PILOT WINDOW, AND HOW IT WAS CHOSEN
=======================================
``2025-06-16 .. 2025-06-18`` -- Monday to Wednesday, the June 2025 FOMC.
Measured before it was pinned (``scratch/nbhelp_probe1.py``, ``probe2``,
``probe3``):

===========  =====  =====  ====  =====  ===  =======  =========  ===  ===  ===
day          legs   units  kept  DV01%  PKG  CURVE    FLY        upf  D2C  D2D
===========  =====  =====  ====  =====  ===  =======  =========  ===  ===  ===
2025-06-16   3193   1971   1596  58.5%    1      238        130  511  1479   67
2025-06-17   4000   2343   1758  56.4%    7      298        205  512  1644   63
2025-06-18   3834   2579   1932  59.5%    5      333        178  581  1830   58
===========  =====  =====  ====  =====  ===  =======  =========  ===  ===  ===

* **Post-2024-07**, as required (before that the tape carries no termination
  events at all). Also **inside s2's design sample** (2024-03-01..2025-08-22),
  which keeps the hold-out (2025-09-01..2026-08-07) shut and lets the trailing
  calibration below be a real one rather than an in-window fit.
* **13 recovered ``PKG-N`` units** over the three days, at least one every day,
  against 159 ``PKG-4+`` given up for ``PKG_SIGNS_AMBIGUOUS`` -- so the notebook
  can show both sides of the identification gate.
* **Both venue classes on every day**, plus the ``VENUE_UNKNOWN`` residual.
* **1,604 upfront-rule units** and 242 lifecycle units over the window.
* 2025-06-16 prices **100%**; 2025-06-17 prices **94.46%** and every one of its
  94 failures is a print stamped 20:00-00:59 ET, where Citi's minute store has
  no snapshot. One clean day and one holed day is the contrast the coverage
  panel needs. (The 94.46% reproduces s2's own cached figure for that day to
  seven decimals -- the cross-check that says this pipeline is s2's.)
* Nothing here is futures-side, so the ``sr3`` MBO window (2026-06-07..08-06)
  does not constrain the choice.

CACHING
=======
Everything lands under ``D:\\ddnb_cache`` -- **nothing on ``C:``**, which has
run to zero twice. Measured, not assumed: a full legs -> units -> price -> KRD
pass opens **zero** ``Caching.DiskCacheMixin`` caches
(``DiskCacheMixin._CACHE_REGISTRY == []``) and changes **zero** of the shards
under ``%LOCALAPPDATA%\\ARBS\\Cache\\diskcache``. The curve reads go to the
DuckDB curve store, and the whole three-day cache here is 5 MB.

Stage caches are keyed on ``(source_digest, window, day)``
where the digest hashes every ``SDRUtils/dealer_direction/*.py`` plus this file
plus the config knobs that change the numbers, so editing the pipeline
invalidates the cache instead of silently serving stale marks.

``krd`` is cached without the calibration in its key **on purpose**:
``KrdProjector.krd_frame`` reads only ``call.rule``, ``call.exclusion`` and
``call.base_orientation``, all of which are tau-free. Swapping ``taus`` re-runs
``classify`` and the ladder, and correctly reuses the risk.

The digest covers **this file's whole text**, comments included, so a docstring
edit invalidates the stage cache and costs a ~3-minute rebuild. That is the
deliberate side of the trade: the alternative -- hashing only the imported
modules -- would let an edit to ``_rate_deviation`` right here serve stale
marks, and a wrong mark is silent while a rebuild is merely slow.

**Which stages that actually covers, and how to see it.** Three of the eight
stages can be read rather than computed -- ``load_legs`` (from
``D:\\ddnb_cache\\legs``), ``price_units`` and ``krd_frame`` (from
``D:\\ddnb_cache\\stage\\<digest>\\<window>\\{pricing,krd}\\*.parquet``) -- and
one, ``taus``, is **never fitted here at all** in the default mode: it unpickles
``D:\\dd_signals_cache\\s2_pos\\calibrations.pkl``, which is an external input
listed in ``data/PROVENANCE.md`` §7.1 and which supplies ``tau``, ``b0``, the
dead zone and therefore ``p`` on every call. ``run_pipeline`` records all of
this: ``timings.source`` is the one-word summary and :func:`cache_report` is the
paths. A cell that says ``COMPUTED`` over a stage read off parquet is
mislabelled, not wrong, and this is how it stops being mislabelled.

WHAT THE SELF-TEST MEASURES ON THE PILOT WINDOW
===============================================
Reproduced on every run; the notebook should quote these from the frames, not
from this list.

* **Universe** 6,893 units, 5,286 kept (76.69%), **58.13% of DV01**. The
  dominant exclusion is ``UNORIENTABLE_PKG``, split by ``exclusion_detail``
  into ``PKG-4+/PKG_SIGNS_AMBIGUOUS`` (159 units, 12.94% of DV01) and the
  asset-swap family (``SPREADOVER`` 7.95%, ``MATCHED_MATURITY`` 3.15%,
  ``INVOICE`` 3.09%, ...). The window's 76.69%/58.13% sit close to the 610-day
  75.28%/56.96%, so it is not an unrepresentative three days.
* **Pricing** 4,938 of 5,032 units (98.13%). Every one of the 94 failures is on
  2025-06-17 and every one is ``NO_CURVE``; ``snap_hour_coverage`` shows they
  are **100%** of that day's prints snapped in NY hours 00, 20, 21, 22 and 23,
  and no other day/hour is incomplete. Citi's minute store publishes roughly
  01:00-19:59 ET; this is that hole, not a flaky curve.
* **Rules** 3,403 ``RATE_VS_MID``, 1,522 ``NPV_VS_UPFRONT``, 13
  ``PACKAGE_PRICE_VS_MODEL``. **All 13 recovered packages carry a two-sided
  orientation** (e.g. ``(1,-1,-1,-1)``, ``(-1,-1,1,1)``), so the upfront
  fallback's ``(1,1,1,1)`` would have inverted part of every one of them.
* **Trap A, measured**: 46 of 1,522 upfront calls have ``dealer_sign`` and
  ``sign(2p-1)`` on opposite sides (3.0%). Unhandled, the first of them stops
  ``ladder.unit_ladder_rows``.
* **Trap B**: 13 of 13 package ``p`` are borrowed; their mean ``|2p-1|`` is
  0.062 against 0.367 for the upfront rule, and 11 of 13 land in the dead zone
  -- the borrowed tau is on the wrong scale and it shows.
* **Risk** 138,012 KRD rows, **zero** projection failures, 28 pillars on every
  unit. The ladder's 103-unit remainder is 94 ``RULE:NO_CURVE`` plus 9
  ``FLAT_PROFILE``.
* **Clocks** ``visibility_lag`` finds three populations: 161 units stamped on
  the *previous* NY date, 4,734 same-day, and **33 uncleared off-facility
  prints from 06-16 that only become actionable on 06-24** -- eight days. A
  ladder stamped on execution would claim all 33 were tradeable on the 16th.
* **Tie-out** against ``s2_positioning``'s own cache: 4,806 shared units, the
  same pricing outcome on all of them, and ``deviation_bps`` / ``npv_pay`` /
  ``structure_dv01`` / ``gross_pv01`` **bit-identical** (max |diff| 0.0e+00) on
  the 4,702 both builds price under the same rule. The only 13 that differ are
  the packages, and they differ by rule, not by number.
* **Cost** two to four minutes for three days cold; pricing is ~70-80% of it
  and KRD most of the rest, and the run-to-run spread is curve-store warmth
  rather than anything in the pipeline. **Under 15 s warm.**
  ``Pipeline.timings`` carries the run's own numbers and is what the notebook
  should quote -- a figure pinned in this docstring would drift.

ONE STDERR LINE THAT IS NOT A PROBLEM
=====================================
A run prints, once::

    citivelo_excel: USD-SOFR-1D-CITIVELOEXCELMIN served a snapshot from a
    DIFFERENT local date (2025-06-15 for a 2025-06-16 request) ...

That is the minute store's own notice, and here it is correct behaviour, not
the nearest-snapshot hazard it exists to warn about. The request is a 00:xx ET
print; ``snapshot.policy_for`` returns the out-of-session policy, whose bound is
``OUT_OF_SESSION_MAX_LAG = 2 hours``, and a 2025-06-15 22:xx ET curve is inside
it. The direction of the reach is guarded separately and unconditionally:
``midprice._assert_telemetry`` raises ``CircularCurve`` on any negative lag, so
a curve from *after* the print cannot be used whatever the store says. The
notebook should show it rather than filter it.

The self-test's own honesty is checked by ``scratch/nbhelp_mutate.py``, which
breaks the pipeline four ways -- weight by ``p``, route ``PKG`` the way s2 does,
return an empty KRD frame, replace the recovered orientation with ``(1,)*n`` --
and confirms all four are caught (4/4).

ENVIRONMENT
===========
``ARBS_SUPABASE_ENABLED=0`` before anything imports ``Caching``;
``ARBS_CITIVELO_QUOTES_OFFLINE=1`` so no Excel is ever opened; ``TMPDIR`` on
``D:``. Run the interpreter directly -- ``conda run`` collides on a temp file
under concurrency and returns empty output with exit 0.

    C:/Users/chris/anaconda3/envs/stir/python.exe -W ignore \
        notebooks/dealer_direction/dd_nb.py
"""
from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"          # never open Excel
os.environ.setdefault("TMPDIR", "D:/ddnb_cache/tmp")

import bisect                                              # noqa: E402
import contextlib                                          # noqa: E402
import dataclasses                                         # noqa: E402
import datetime                                            # noqa: E402
import hashlib                                             # noqa: E402
import pathlib                                             # noqa: E402
import pickle                                              # noqa: E402
import sys                                                 # noqa: E402
import time                                                # noqa: E402
import warnings                                            # noqa: E402

import numpy as np                                         # noqa: E402
import pandas as pd                                        # noqa: E402

REPO = str(pathlib.Path(__file__).resolve().parents[2])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from SDRUtils.dealer_direction import conventions as conv   # noqa: E402
from SDRUtils.dealer_direction import indicator as ind      # noqa: E402
from SDRUtils.dealer_direction import krd as krd_mod        # noqa: E402
from SDRUtils.dealer_direction import ladder as ladder_mod  # noqa: E402
from SDRUtils.dealer_direction import midprice              # noqa: E402
from SDRUtils.dealer_direction import package_price as pp   # noqa: E402
from SDRUtils.dealer_direction import probability as P      # noqa: E402
from SDRUtils.dealer_direction import snapshot              # noqa: E402
from SDRUtils.dealer_direction import types as T            # noqa: E402
from SDRUtils.dealer_direction import universe              # noqa: E402
from SDRUtils.dealer_direction import upfront as U          # noqa: E402

# ===========================================================================
# configuration
# ===========================================================================

#: The pilot window. See the module docstring for how it was chosen.
PILOT_START = "2025-06-16"
PILOT_END = "2025-06-18"

#: Everything cached goes here. `C:` has hit zero twice; nothing large lands there.
CACHE_DIR = pathlib.Path(r"D:\ddnb_cache")
OUT_DIR = CACHE_DIR / "out"

#: s2's rolling calibrations, fitted on strictly-prior 60-calendar-day windows
#: of rate-rule deviations. Reused when it covers the window -- it is the same
#: code (`probability.rolling_calibrations`) on a wider sample than three days
#: could ever supply, and it is trailing, so nothing here reads its own day.
S2_CALIBRATIONS = pathlib.Path(r"D:\dd_signals_cache\s2_pos\calibrations.pkl")

CALIB_TRAILING = "trailing_s2"
CALIB_IN_WINDOW = "in_window"

#: Files whose contents key the stage caches.
_SOURCE_FILES = tuple(
    sorted((pathlib.Path(REPO) / "SDRUtils" / "dealer_direction").glob("*.py"))
) + (pathlib.Path(__file__).resolve(),)


@dataclasses.dataclass(frozen=True)
class Config:
    """Every knob that changes a number, in one hashable object."""

    start: str = PILOT_START
    end: str = PILOT_END
    cache_dir: pathlib.Path = CACHE_DIR
    out_dir: pathlib.Path = OUT_DIR
    #: Curve family the mid and the KRD are both taken from.
    curve_source: str = snapshot.CURVE_SOURCE
    #: Rate indices admitted to the *pricing* population. The universe
    #: accounting always covers the whole tape.
    indices: tuple[str, ...] = ("SOFR",)
    include_lifecycle: bool = True
    calibration: str = CALIB_TRAILING
    s2_calibrations: pathlib.Path = S2_CALIBRATIONS
    block_minutes: int = krd_mod.BLOCK_MINUTES
    dust_frac: float = 0.0
    #: `probability.direction_probability`'s dead-zone reporting threshold.
    #: Reporting only -- `2p-1` is already ~0 there, and the ladder must not move.
    dead_zone_delta: float = P.DEAD_ZONE_DELTA
    use_cache: bool = True

    @property
    def window(self) -> str:
        return f"{self.start}_{self.end}"

    def digest_payload(self) -> str:
        return repr((self.curve_source, tuple(self.indices),
                     self.include_lifecycle, self.block_minutes,
                     self.dust_frac))


def config(**overrides) -> Config:
    """A :class:`Config`, defaulted to the pilot window.

    ``config(start="2025-06-17", end="2025-06-17")`` narrows it;
    ``config(indices=("SOFR", "FED_FUNDS"))`` widens the pricing population.
    """
    known = {f.name for f in dataclasses.fields(Config)}
    bad = set(overrides) - known
    if bad:
        raise TypeError(f"unknown config field(s) {sorted(bad)}; "
                        f"known: {sorted(known)}")
    for k in ("cache_dir", "out_dir", "s2_calibrations"):
        if k in overrides and overrides[k] is not None:
            overrides[k] = pathlib.Path(overrides[k])
    if "indices" in overrides:
        overrides["indices"] = tuple(overrides["indices"])
    cfg = Config(**overrides)
    if cfg.calibration not in (CALIB_TRAILING, CALIB_IN_WINDOW):
        raise ValueError(f"calibration must be {CALIB_TRAILING!r} or "
                         f"{CALIB_IN_WINDOW!r}, got {cfg.calibration!r}")
    return cfg


_SOURCE_HASH: str | None = None


def source_digest(cfg: Config) -> str:
    """Short hash of the pipeline's source plus the config knobs that matter.

    Keyed on *contents*, not mtimes: a checkout that restores a file must not
    invalidate a cache, and an edit that changes a mark must. The file read is
    memoised per process -- an edit mid-run would be a torn cache key, not a
    feature.
    """
    global _SOURCE_HASH
    if _SOURCE_HASH is None:
        h = hashlib.sha256()
        for p in _SOURCE_FILES:
            h.update(p.name.encode())
            h.update(p.read_bytes())
        _SOURCE_HASH = h.hexdigest()
    return hashlib.sha256(
        (_SOURCE_HASH + cfg.digest_payload()).encode()).hexdigest()[:12]


def _stage_dir(cfg: Config, stage: str) -> pathlib.Path:
    d = cfg.cache_dir / "stage" / source_digest(cfg) / cfg.window / stage
    d.mkdir(parents=True, exist_ok=True)
    return d


def _atomic_parquet(df: pd.DataFrame, path: pathlib.Path) -> None:
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# which stages were served from a cache, and from where
# ---------------------------------------------------------------------------
#
# A stage cache is not a cosmetic detail and a notebook that banners a cell
# `COMPUTED` while reading its numbers off parquet is mislabelling itself.
# Every cache read is recorded here so :func:`cache_report` can say plainly
# which stage came from where, and :func:`run_pipeline` can put a `source`
# column beside the timings that would otherwise be the only clue.

_CACHE_LOG: dict[str, dict] = {}


def _log_cache(stage: str, *, hit: int = 0, miss: int = 0,
               where: str | None = None, hit_label: str = "CACHE") -> None:
    e = _CACHE_LOG.setdefault(stage, {"hit": 0, "miss": 0, "where": None,
                                      "hit_label": hit_label})
    e["hit"] += hit
    e["miss"] += miss
    if where:
        e["where"] = where
    if hit:
        e["hit_label"] = hit_label


def cache_source(stage: str) -> str:
    """``COMPUTED`` / ``CACHE`` / ``CACHE 2/3d`` / ``LOADED`` for one stage.

    One word per stage, meant to sit beside the timings so the banner and the
    stopwatch cannot disagree.
    """
    e = _CACHE_LOG.get(stage)
    if not e or not e["hit"]:
        return "COMPUTED"
    if not e["miss"]:
        return e["hit_label"]
    return f"{e['hit_label']} {e['hit']}/{e['hit'] + e['miss']}d"


def cache_report() -> pd.DataFrame:
    """Where each stage of the last :func:`run_pipeline` actually got its rows.

    Two of the eight stages are cached to parquet -- ``price_units`` and
    ``krd_frame``, the two a reader would most want recomputed -- plus the raw
    ``load_legs`` frame, plus the calibration, which is never fitted here at
    all. The stage cache is keyed on :func:`source_digest`: the *contents* of
    every ``SDRUtils/dealer_direction/*.py`` plus this file, plus the config
    knobs in :meth:`Config.digest_payload`. An edit to any of them is a new key
    and a cold run, so nothing here can serve a mark computed by different
    code -- but "cannot be stale" is not "was computed in front of you", and
    this frame is the difference.
    """
    rows = [{"stage": s,
             "source": cache_source(s),
             "days_read": e["hit"],
             "days_computed": e["miss"],
             "served_from": e["where"] or "-"}
            for s, e in _CACHE_LOG.items()]
    return pd.DataFrame(rows, columns=["stage", "source", "days_read",
                                       "days_computed", "served_from"])


class _WarningTally:
    """Count warnings by ``(category, first 120 chars)`` instead of storing them.

    ``catch_warnings(record=True)`` keeps every message object, and rateslib's
    fixings warning embeds a 6,891-row Series repr -- a few thousand of those is
    hundreds of megabytes for a diagnostic nobody reads twice.
    """

    def __init__(self):
        self.counts: dict[tuple[str, str], int] = {}

    @contextlib.contextmanager
    def capture(self):
        prev_show, prev_filters = warnings.showwarning, warnings.filters[:]

        def show(message, category, filename, lineno, file=None, line=None):
            key = (category.__name__, str(message)[:120].replace("\n", " "))
            self.counts[key] = self.counts.get(key, 0) + 1

        warnings.showwarning = show
        warnings.simplefilter("always")
        try:
            yield self
        finally:
            warnings.showwarning = prev_show
            warnings.filters[:] = prev_filters

    def frame(self) -> pd.DataFrame:
        rows = [{"category": c, "message": m, "n": n}
                for (c, m), n in sorted(self.counts.items(),
                                        key=lambda kv: -kv[1])]
        return pd.DataFrame(rows, columns=["category", "message", "n"])


# ===========================================================================
# stage 1 -- legs
# ===========================================================================

def connect():
    """A read-only session against the production tape. **Write nothing.**"""
    import psycopg2

    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    return psycopg2.connect(resolve_pg_url())


def load_legs(start: str | None = None, end: str | None = None,
              cfg: Config | None = None) -> pd.DataFrame:
    """The raw tape frame for the window. Read-only, cached to ``D:``.

    Straight through ``universe.load_legs`` (``LEGS_SQL``, one ordered SELECT),
    so the column set and the total order are the pipeline's own. The cache is
    keyed on the window alone -- the tape is immutable history and does not
    depend on any config knob.
    """
    cfg = cfg or config()
    start = start or cfg.start
    end = end or cfg.end
    d = cfg.cache_dir / "legs"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"legs_{start}_{end}.parquet"
    if cfg.use_cache and path.exists():
        _log_cache("load_legs", hit=1, where=str(path))
        return pd.read_parquet(path)
    _log_cache("load_legs", miss=1,
               where="production Postgres via resolve_pg_url() "
                     "[DATABASE_URL / PG_URL / SWAPPULSE_DB_* defaults]")
    conn = connect()
    try:
        legs = universe.load_legs(conn, start, end)
    finally:
        conn.close()
    if legs.empty:
        raise RuntimeError(
            f"the tape returned no legs for {start}..{end}. A business day with "
            "no prints is a failed read, not a quiet market")
    tmp = path.with_suffix(".tmp.parquet")
    legs.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return legs


def tape_days(legs: pd.DataFrame) -> list[str]:
    """The ``as_of_date`` values actually present, ascending."""
    return [str(pd.Timestamp(d).date())
            for d in sorted(pd.to_datetime(legs["as_of_date"]).unique())]


# ===========================================================================
# stage 2 -- units
# ===========================================================================

@dataclasses.dataclass
class UnitsResult:
    """The universe, and the accounting that says what it left out."""

    units: list                       #: kept `types.Unit` objects, all days
    frame: pd.DataFrame               #: `universe.unit_frame` -- one row per unit
    excluded: pd.DataFrame            #: the excluded rows of the same frame
    exclusions: pd.DataFrame          #: reason x (units, legs, DV01, share)
    accounting: dict                  #: the headline retention numbers
    by_day: pd.DataFrame              #: per-day units / kept / DV01 share

    def units_by_day(self) -> dict:
        out: dict[str, list] = {}
        for u in self.units:
            out.setdefault(str(u.as_of_date), []).append(u)
        return out


def build_units(legs: pd.DataFrame, cfg: Config | None = None) -> UnitsResult:
    """Units plus the exclusion accounting, both off one ``unit_frame``.

    ``universe.build_universe`` returns the kept ``Unit`` objects and the
    excluded rows from the *same* frame, so a unit cannot be counted in one and
    missing from the other. The DV01 here is the annuity proxy
    (``sanity.expected_dv01``), never the tape's ``risk`` column.
    """
    cfg = cfg or config()
    frame = universe.unit_frame(legs)
    units, excluded = universe.build_universe(legs)

    total_dv01 = float(frame["dv01_proxy"].sum())
    kept = frame[frame["exclusion"].isna()]
    reason = frame["exclusion"].astype(object).where(
        frame["exclusion"].notna(), "(kept)")
    detail = frame["exclusion_detail"].astype(object).fillna("-")
    ex = (frame.assign(_reason=reason, _detail=detail)
          .groupby(["_reason", "_detail"], dropna=False, observed=True)
          .agg(n_units=("n_legs", "size"), n_legs=("n_legs", "sum"),
               dv01_proxy=("dv01_proxy", "sum"))
          .reset_index()
          .rename(columns={"_reason": "reason", "_detail": "detail"})
          .sort_values("dv01_proxy", ascending=False))
    ex["dv01_share_pct"] = 100.0 * ex["dv01_proxy"] / total_dv01

    f = frame.assign(
        _kept=frame["exclusion"].isna(),
        _dv01_kept=frame["dv01_proxy"].where(frame["exclusion"].isna(), 0.0),
        _pkg=frame["exclusion"].isna() & (frame["n_legs"] >= 4),
        _upf=frame["exclusion"].isna() & frame["upfront"].notna(),
        _life=frame["exclusion"].isna() & frame["is_lifecycle"].astype(bool))
    by_day = (f.groupby("as_of_date", observed=True)
              .agg(n_units=("n_legs", "size"), n_kept=("_kept", "sum"),
                   dv01_total=("dv01_proxy", "sum"),
                   dv01_kept=("_dv01_kept", "sum"),
                   n_pkg_recovered=("_pkg", "sum"), n_upfront=("_upf", "sum"),
                   n_lifecycle=("_life", "sum"))
              .reset_index())
    by_day["unit_retention"] = by_day["n_kept"] / by_day["n_units"]
    by_day["dv01_retention"] = (by_day["dv01_kept"]
                                / by_day["dv01_total"].where(
                                    by_day["dv01_total"] != 0))
    by_day = by_day[["as_of_date", "n_units", "n_kept", "unit_retention",
                     "dv01_retention", "n_pkg_recovered", "n_upfront",
                     "n_lifecycle"]]

    accounting = {
        "n_units": len(frame),
        "n_kept": len(kept),
        "unit_retention": float(len(kept) / len(frame)) if len(frame) else np.nan,
        "dv01_total": total_dv01,
        "dv01_kept": float(kept["dv01_proxy"].sum()),
        "dv01_retention": float(kept["dv01_proxy"].sum() / total_dv01)
        if total_dv01 else np.nan,
        "n_excluded": int(frame["exclusion"].notna().sum()),
        "n_pkg_recovered": int((kept["n_legs"] >= 4).sum()),
        "n_pkg_ambiguous": int(frame["exclusion_detail"].astype(str)
                               .eq("PKG-4+/PKG_SIGNS_AMBIGUOUS").sum()),
        "n_lifecycle_kept": int(kept["is_lifecycle"].sum()),
        "n_upfront_kept": int(kept["upfront"].notna().sum()),
        "venue_counts": kept["venue_class"].value_counts().to_dict(),
        "kind_counts": kept["kind"].value_counts().to_dict(),
        "index_counts": kept["rate_index"].value_counts().to_dict(),
    }
    return UnitsResult(units=units, frame=frame, excluded=excluded,
                       exclusions=ex, accounting=accounting, by_day=by_day)


def route_rule(unit) -> str | None:
    """Which of the **three** rules classifies this unit, or ``None``.

    Routing is by ``kind`` **first**, and that ordering is the point:
    ``conventions.base_orientation(PKG, n, RULE_UPFRONT)`` succeeds and returns
    ``(1,) * n``, so a leg-count-blind router silently sends a recovered package
    into the upfront branch with every leg pointed the same way -- the hazard
    ``krd.received_hypothesis_signs`` names, and what ``s2_positioning`` does.
    """
    if unit.kind == conv.PKG:
        return pp.RULE_PACKAGE_PRICE
    rule = conv.RULE_UPFRONT if unit.upfront is not None else conv.RULE_RATE
    try:
        conv.base_orientation(unit.kind, unit.n_legs, rule)
    except conv.UnorientableUnit:
        return None
    return rule


def pricing_population(units: list, cfg: Config | None = None) -> tuple:
    """``(units, {unit_key: rule})`` -- the units the three rules can reach.

    Sorted by ``snapshot.snap_instant(clocks.pricing)``. Not by
    ``execution_timestamp``: the KRD block anchor is the first unit to ask for
    it, so an out-of-order unit is served a curve from after its own print and
    ``krd.LookaheadCurve`` fires (s2's own note; measured at 167 of 4,329 legs
    on one day).
    """
    cfg = cfg or config()
    keep = set(cfg.indices)
    pop, rules = [], {}
    for u in units:
        if u.rate_index not in keep:
            continue
        if u.is_lifecycle and not cfg.include_lifecycle:
            continue
        rule = route_rule(u)
        if rule is None:
            continue
        pop.append(u)
        rules[u.unit_key] = rule
    pop.sort(key=lambda u: snapshot.snap_instant(u.clocks.pricing))
    return pop, rules


# ===========================================================================
# stage 3 -- repricing
# ===========================================================================

UNIT_COLS = [
    "unit_key", "as_of_date", "kind", "n_legs", "rule", "venue_class",
    "rate_index", "is_lifecycle", "is_block", "is_capped", "tenor_years",
    "tenor_band", "special_tenor_type", "package_transaction_price",
    "visibility_ts", "visibility_source", "visibility_date", "pricing_ts",
    "execution_ts", "event_ts", "snap_instant", "curve_name",
    "snapshot_policy", "snapshot_lag_s", "npv_pay", "upfront",
    "upfront_source", "structure_dv01", "gross_pv01", "traded_price_bps",
    "mid_price_bps", "deviation_bps", "failure", "failure_detail", "flags",
]

LEG_COLS = [
    "unit_key", "leg_index", "trade_id", "as_of_date", "effective_date",
    "expiration_date", "notional", "fixed_rate", "other_payment_amount",
    "start_class", "is_capped", "mid_pct", "pv01", "npv_pay", "failure",
    "failure_detail",
]


@dataclasses.dataclass
class PricingResult:
    """Repriced marks, and the per-leg reason for everything that has none."""

    units: pd.DataFrame               #: one row per priced unit, `UNIT_COLS`
    legs: pd.DataFrame                #: one row per leg, `LEG_COLS`
    failures: pd.DataFrame            #: the failed unit rows, reason + detail
    coverage: pd.DataFrame            #: priced fraction by start_class
    warnings: pd.DataFrame            #: tallied, not stored verbatim
    seconds: float = 0.0

    @property
    def priced(self) -> pd.DataFrame:
        return self.units[self.units["failure"].isna()]


_ENGINE_CACHE: dict = {}


def _engines(cfg: Config, *, shared: bool = False):
    """``(UnitRepricer, KrdProjector)`` sharing one pricer, hence one handle cache.

    ``shared=True`` memoises them per config so a notebook calling
    :func:`one_trade` repeatedly does not stand up a new ``IRSwapsMDP`` each
    time. The batch stages take fresh ones: they own a ``day_scope`` and
    dropping the solvers at the day boundary is the point.
    """
    if shared:
        k = (cfg.curve_source, cfg.block_minutes, cfg.dust_frac)
        if k not in _ENGINE_CACHE:
            _ENGINE_CACHE[k] = _engines(cfg)
        return _ENGINE_CACHE[k]
    rep = midprice.UnitRepricer.for_source(cfg.curve_source)
    proj = krd_mod.KrdProjector(rep.pricer, block_minutes=cfg.block_minutes,
                                dust_frac=cfg.dust_frac)
    return rep, proj


def _unit_static(u, rule: str) -> dict:
    tenor = pd.to_numeric(u.legs["tenor_years"], errors="coerce").max()
    tenor = float(tenor) if pd.notna(tenor) else np.nan
    stt = u.legs["special_tenor_type"].iloc[0]
    ptp = pd.to_numeric(u.legs["package_transaction_price"],
                        errors="coerce").dropna()
    return {
        "unit_key": u.unit_key, "as_of_date": str(u.as_of_date),
        "kind": u.kind, "n_legs": int(u.n_legs), "rule": rule,
        "venue_class": u.venue_class, "rate_index": u.rate_index,
        "is_lifecycle": bool(u.is_lifecycle), "is_block": bool(u.is_block),
        "is_capped": bool(u.is_capped), "tenor_years": tenor,
        "tenor_band": P.tenor_band(tenor) if pd.notna(tenor) else None,
        "special_tenor_type": ("STANDARD" if stt is None or pd.isna(stt)
                               else str(stt)),
        "package_transaction_price": (float(ptp.iloc[0]) if len(ptp)
                                      else np.nan),
        "visibility_ts": u.clocks.visibility,
        "visibility_source": u.clocks.visibility_source,
        "visibility_date": ladder_mod.visibility_date(u.clocks.visibility),
        "pricing_ts": u.clocks.pricing,
        "execution_ts": u.clocks.execution,
        "event_ts": u.clocks.event,
        "snap_instant": snapshot.snap_instant(u.clocks.pricing),
        "upfront": u.upfront, "upfront_source": u.upfront_source,
    }


def _rate_deviation(u, rule: str, out) -> tuple:
    """``(traded_bps, mid_bps, deviation_bps)`` for a rate-rule unit.

    ``conventions.structure_price`` takes **percent** and returns **bp**; the
    tape's ``fixed_rate`` is decimal (flow median 0.0394), hence the ``* 100``.
    """
    if rule != conv.RULE_RATE:
        return (np.nan, np.nan, np.nan)
    traded = [float(l["fixed_rate"]) * 100.0 for _, l in u.legs.iterrows()]
    tp = conv.structure_price(traded, u.kind, u.n_legs, rule)
    mp = conv.structure_price(list(out.pricing.leg_mid_pct), u.kind, u.n_legs,
                              rule)
    return (tp, mp, tp - mp)


def _price_day(day: str, units: list, rules: dict, cfg: Config,
               rep=None) -> tuple:
    own = rep is None
    if own:
        rep, _ = _engines(cfg)
    urows, lrows = [], []
    scope = rep.day_scope() if own else contextlib.nullcontext(rep)
    with scope:
        for u in units:
            rule = rules[u.unit_key]
            out = rep.price_unit(u)
            base = _unit_static(u, rule)
            base.update({
                "curve_name": out.pricing.curve_name,
                "snapshot_policy": out.pricing.snapshot_policy,
                "snapshot_lag_s": out.pricing.snapshot_lag_seconds,
                "npv_pay": out.pricing.npv_pay,
                "structure_dv01": out.pricing.structure_dv01,
                "gross_pv01": out.gross_pv01,
                "failure": out.failure,
                "failure_detail": out.failure_detail,
                "flags": ",".join(out.flags) if out.flags else None,
            })
            tp, mp, dev = ((np.nan, np.nan, np.nan) if out.failure is not None
                           else _rate_deviation(u, rule, out))
            base.update({"traded_price_bps": tp, "mid_price_bps": mp,
                         "deviation_bps": dev})
            urows.append(base)
            for i, ((_, leg), q) in enumerate(zip(u.legs.iterrows(), out.legs)):
                lrows.append({
                    "unit_key": u.unit_key, "leg_index": i,
                    "trade_id": leg.get("trade_id"), "as_of_date": day,
                    "effective_date": leg.get("effective_date"),
                    "expiration_date": leg.get("expiration_date"),
                    "notional": _f(leg.get("notional")),
                    "fixed_rate": _f(leg.get("fixed_rate")),
                    "other_payment_amount": _f(leg.get("other_payment_amount")),
                    "start_class": q.start_class, "is_capped": bool(q.is_capped),
                    "mid_pct": q.mid_pct, "pv01": q.pv01, "npv_pay": q.npv_pay,
                    "failure": q.failure, "failure_detail": q.failure_detail,
                })
    return (pd.DataFrame(urows).reindex(columns=UNIT_COLS),
            pd.DataFrame(lrows).reindex(columns=LEG_COLS))


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def price_units(units_result: UnitsResult, cfg: Config | None = None,
                *, days: list[str] | None = None) -> PricingResult:
    """Reprice the population, one ``day_scope`` per tape day, cached per day.

    The day scope is not decoration: a solver holds an ``rl.Curve`` and its
    Jacobian, nothing evicts them, and the pricer's handle cache is dropped on
    the same boundary.
    """
    cfg = cfg or config()
    ud, cache = units_result.units_by_day(), _stage_dir(cfg, "pricing")
    days = days or sorted(ud)
    tally = _WarningTally()
    t0 = time.perf_counter()
    uparts, lparts = [], []
    rep = None
    with tally.capture():
        for day in days:
            up, lp = cache / f"{day}.units.parquet", cache / f"{day}.legs.parquet"
            if cfg.use_cache and up.exists() and lp.exists():
                _log_cache("price_units", hit=1, where=str(cache))
                uparts.append(pd.read_parquet(up))
                lparts.append(pd.read_parquet(lp))
                continue
            _log_cache("price_units", miss=1, where=str(cache))
            pop, rules = pricing_population(ud.get(day, []), cfg)
            if not pop:
                raise RuntimeError(
                    f"{day}: the pricing population is empty. With "
                    f"indices={cfg.indices} that is a failed read or a routing "
                    "bug, not a quiet market")
            if rep is None:
                rep, _ = _engines(cfg)
            with rep.day_scope():
                udf, ldf = _price_day(day, pop, rules, cfg, rep=rep)
            _atomic_parquet(udf, up)
            _atomic_parquet(ldf, lp)
            uparts.append(udf)
            lparts.append(ldf)
    u = pd.concat(uparts, ignore_index=True)
    l = pd.concat(lparts, ignore_index=True)

    cov = (l.assign(ok=l["failure"].isna())
           .groupby(["as_of_date", "start_class"], observed=True)["ok"]
           .agg(n_legs="size", priced_frac="mean").reset_index())
    tot = (l.assign(ok=l["failure"].isna())
           .groupby("start_class", observed=True)["ok"]
           .agg(n_legs="size", priced_frac="mean").reset_index())
    tot["as_of_date"] = "ALL"
    cov = pd.concat([cov, tot], ignore_index=True)

    return PricingResult(
        units=u, legs=l,
        failures=u[u["failure"].notna()].copy(),
        coverage=cov, warnings=tally.frame(),
        seconds=time.perf_counter() - t0)


# ===========================================================================
# stage 4 -- calibration
# ===========================================================================

@dataclasses.dataclass
class TauSet:
    """The calibrations that govern each classification date, and where from."""

    by_day: dict                      #: ``date -> probability.Calibration``
    provenance: pd.DataFrame          #: one row per day: donor, window, n fits
    report: pd.DataFrame              #: ``Calibration.report()`` for one donor
    mode: str = CALIB_TRAILING

    def for_day(self, day) -> "P.Calibration":
        d = _as_date(day)
        try:
            return self.by_day[d]
        except KeyError:
            raise KeyError(
                f"no calibration governs {d}; TauSet covers "
                f"{sorted(self.by_day)[:1]}..{sorted(self.by_day)[-1:]}"
            ) from None


def _as_date(v) -> datetime.date:
    if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
        return v
    return pd.Timestamp(v).date()


#: What to do about a missing or non-covering calibration pickle. Named
#: separately because both failure paths need it and a reader hitting either
#: one needs the command, not a diagnosis.
_CALIB_REMEDY = (
    "  REGENERATE (writes D:/dd_signals_cache/s2_pos/calibrations.pkl in the\n"
    "  `signal` stage; `build` and `target` must have run first, and `build`\n"
    "  reads the production tape):\n"
    "      set ARBS_SUPABASE_ENABLED=0\n"
    "      C:/Users/chris/anaconda3/envs/stir/python.exe "
    "BT/dd_signals/s2_positioning.py build\n"
    "      C:/Users/chris/anaconda3/envs/stir/python.exe "
    "BT/dd_signals/s2_positioning.py target\n"
    "      C:/Users/chris/anaconda3/envs/stir/python.exe "
    "BT/dd_signals/s2_positioning.py signal\n"
    "  OR point at another copy:  dd_nb.config(s2_calibrations=<path>)\n"
    f"  OR fit on the window itself -- which is NOT trailing, is a different\n"
    f"  claim, and will fail the strictly-prior provenance assertion by\n"
    f"  design:  dd_nb.config(calibration={CALIB_IN_WINDOW!r})\n"
    "  See notebooks/dealer_direction/data/PROVENANCE.md section 7.1.")


def _missing_calibration_msg(cfg: "Config") -> str:
    return (
        f"calibration mode {CALIB_TRAILING!r} needs s2_positioning's rolling "
        f"calibrations and\n{cfg.s2_calibrations} does not exist.\n"
        "This is an EXTERNAL input, not something this notebook fits: it "
        "supplies tau, b0,\nthe dead zone and therefore `p` on every call, and "
        "the whole calibration section\nreads off it. Without it there is no "
        "trailing calibration at all.\n" + _CALIB_REMEDY)


def taus(pricing: PricingResult | None = None,
         cfg: Config | None = None) -> TauSet:
    """The per-day :class:`probability.Calibration`.

    ``CALIB_TRAILING`` (default) reuses ``s2_positioning``'s rolling
    calibrations: ``probability.rolling_calibrations`` on a **strictly prior**
    60-calendar-day window of rate-rule deviations, refit every five sessions,
    and each classification date is governed by the most recent fit **at or
    before** it. Requiring an exact-date key would silently drop four days in
    five. Nothing about a pilot day enters its own tau.

    ``CALIB_IN_WINDOW`` fits one ``Calibration`` on the window's own rate-rule
    deviations. Loudly labelled, and defensible only because the notebook makes
    no signal claim: three days is ~3.6k deviations, so with
    ``MIN_BUCKET_N = 800`` most leaves pool to a coarse parent -- which
    ``TauSet.report`` shows rather than hides.

    ``CALIB_TRAILING`` **loads, it does not fit.** The pickle is an external
    input, listed in ``data/PROVENANCE.md`` §7.1, and it sets ``tau``, ``b0``
    and the dead zone on every single call. If it is missing, or does not reach
    the window, this raises and names the real cause -- it must never fall back
    silently to an in-window fit, because that fit is not trailing and the
    failure then surfaces four cells later as a strictly-prior assertion,
    blaming window ordering for a missing file.
    """
    cfg = cfg or config()
    if cfg.calibration == CALIB_TRAILING:
        if not cfg.s2_calibrations.exists():
            raise FileNotFoundError(_missing_calibration_msg(cfg))
        with open(cfg.s2_calibrations, "rb") as fh:
            cals = pickle.load(fh)
        keys = sorted(cals)
        want = pd.date_range(cfg.start, cfg.end, freq="D").date
        by_day, rows = {}, []
        for d in want:
            i = bisect.bisect_right(keys, d) - 1
            if i < 0:
                continue
            lo, hi, cal = cals[keys[i]]
            if _as_date(hi) >= d:
                raise RuntimeError(
                    f"the calibration governing {d} was fitted on a window "
                    f"ending {hi}, which is not strictly prior; that puts the "
                    "day's own deviations into its own b0")
            by_day[d] = cal
            rows.append({"date": d, "donor_date": keys[i], "window_lo": lo,
                         "window_hi": hi, "staleness_days": (d - keys[i]).days,
                         "n_fits": len(cal.fits)})
        if not by_day:
            span = (f"{keys[0]} .. {keys[-1]}" if keys else "(it is empty)")
            raise RuntimeError(
                f"{cfg.s2_calibrations} exists but no fit in it is dated at or "
                f"before {cfg.start}: its donor dates span {span}. The window "
                f"{cfg.start}..{cfg.end} is outside s2's design sample, so "
                "there is no strictly-prior calibration to serve it.\n"
                + _CALIB_REMEDY)
        donor = by_day[sorted(by_day)[0]]
        _log_cache("taus", hit=len(by_day), hit_label="LOADED",
                   where=f"{cfg.s2_calibrations}  "
                         f"[data/PROVENANCE.md section 7.1]")
        return TauSet(by_day=by_day, provenance=pd.DataFrame(rows),
                      report=donor.report(cfg.dead_zone_delta),
                      mode=CALIB_TRAILING)

    if pricing is None:
        raise ValueError(
            f"calibration mode {cfg.calibration!r} needs the window's own "
            "rate-rule deviations, so `pricing` is required. Pass "
            "`price_units(...)`'s result, or point `s2_calibrations` at a "
            "pickle that covers the window")
    rate = pricing.priced
    rate = rate[(rate["rule"] == conv.RULE_RATE)
                & rate["deviation_bps"].notna()
                & ~rate["is_lifecycle"]]
    if rate.empty:
        raise RuntimeError("no rate-rule deviations to calibrate on")
    df = rate.rename(columns={"kind": "structure"})[
        ["deviation_bps", "venue_class", "rate_index", "structure",
         "special_tenor_type", "tenor_band"]].copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cal = P.Calibration.fit(df, as_of=_as_date(cfg.end))
    days = [_as_date(d) for d in sorted(pricing.units["as_of_date"].unique())]
    prov = pd.DataFrame([{"date": d, "donor_date": None,
                          "window_lo": cfg.start, "window_hi": cfg.end,
                          "staleness_days": 0, "n_fits": len(cal.fits)}
                         for d in days])
    _log_cache("taus", miss=len(days),
               where="fitted in this kernel on the window's own deviations "
                     "(NOT trailing)")
    return TauSet(by_day={d: cal for d in days}, provenance=prov,
                  report=cal.report(cfg.dead_zone_delta), mode=CALIB_IN_WINDOW)


# ===========================================================================
# stage 5 -- the three rules
# ===========================================================================

#: One row per unit. **``deviation_bps`` means three different things here**,
#: one per rule, and a display that does not say which is inviting a false
#: sign reading:
#:
#: * ``RATE_VS_MID``            -- traded structure rate minus curve mid, in bp
#:   of the structure's quoted price. This is the deviation everywhere else.
#: * ``NPV_VS_UPFRONT``         -- ``upfront.classify``'s ``edge_bps``: the paid
#:   upfront against the payer-frame NPV, in bp of ``structure_dv01``. It is a
#:   different quantity on a different frame; the pricing frame's own
#:   ``deviation_bps`` is NULL on every one of these units.
#: * ``PACKAGE_PRICE_VS_MODEL`` -- the package price against the sum of the
#:   legs' model values, in bp of *package* DV01.
#:
#: They share a column because the ladder wants one; they do not share a
#: meaning. Rename it in any display that mixes rules.
CALL_COLS = [
    "unit_key", "as_of_date", "rule", "kind", "n_legs", "venue_class",
    "rate_index", "is_lifecycle", "tenor_band", "special_tenor_type",
    "deviation_bps", "p", "signed_weight", "dealer_sign", "dealer_sign_point",
    "sign_disagrees", "tau_bucket", "tau_bps", "mid_bias_bps", "in_dead_zone",
    "base_orientation", "tieout_bps", "margin_bps", "rule_flags", "exclusion",
]


@dataclasses.dataclass
class CallsResult:
    """Direction calls across all three rules, plus what each rule refused."""

    calls: list                       #: `types.DirectionCall`, one per unit
    frame: pd.DataFrame               #: `CALL_COLS`
    exclusions: pd.DataFrame          #: rule x exclusion counts
    diagnostics: dict

    @property
    def called(self) -> pd.DataFrame:
        return self.frame[self.frame["exclusion"].isna()]


@contextlib.contextmanager
def _probability_clip():
    """Let a ``p`` that rounded one machine epsilon past 1 through, and nothing else.

    ``upfront.classify`` hands ``conventions.signed_weight`` the output of
    ``p_marginalised``, a logistic-normal integral, and on a deeply off-market
    print that integral returns ``1.0000000000000002``. ``signed_weight``
    refuses it -- rightly, it cannot tell ``1+2e-16`` from a real 1.4 -- and the
    pass dies. Dropping those units instead drops precisely the largest,
    most-confident upfront calls, which is a biased sample. So the boundary is
    clipped by **1e-9 and no more**, and the firing count is returned so a guard
    that fires on half the population cannot hide.
    """
    original = conv.signed_weight
    state = {"n_high": 0, "n_low": 0, "worst": 0.0}

    def guarded(p):
        q = float(p)
        if 1.0 < q <= 1.0 + 1e-9:
            state["n_high"] += 1
            state["worst"] = max(state["worst"], q - 1.0)
            q = 1.0
        elif -1e-9 <= q < 0.0:
            state["n_low"] += 1
            state["worst"] = max(state["worst"], -q)
            q = 0.0
        return original(q)

    # Every consumer reaches this through the *module* object
    # (`conventions.signed_weight` in `upfront`, `conv.signed_weight` in
    # `probability` and `ladder`) rather than by importing the name, so
    # rebinding the attribute is enough -- checked, not assumed.
    for m in (U, P, ladder_mod):
        assert getattr(m, "conventions", None) is conv or \
            getattr(m, "conv", None) is conv, \
            f"{m.__name__} does not reach conventions through the module object"
    conv.signed_weight = guarded
    try:
        yield state
    finally:
        conv.signed_weight = original


def _bucket_key(row) -> "P.BucketKey":
    return P.BucketKey(venue_class=row["venue_class"],
                       rate_index=row["rate_index"],
                       structure=row["kind"],
                       special_tenor_type=row["special_tenor_type"],
                       tenor_band=row["tenor_band"])


def classify(units_result: UnitsResult, pricing: PricingResult,
             tau_set: TauSet | None = None,
             cfg: Config | None = None) -> CallsResult:
    """Direction calls under **all three** rules.

    ==========================  ==========================================
    rule                        how ``p`` is produced
    ==========================  ==========================================
    ``RATE_VS_MID``             ``probability.direction_probability`` on the
                                quoted-structure deviation.
    ``NPV_VS_UPFRONT``          ``upfront.classify`` with a ``TauUpfront``
                                built from the same fit (s2's borrow).
    ``PACKAGE_PRICE_VS_MODEL``  no ``p`` exists -- borrowed pooled fit with
                                ``b0`` zeroed. See the module docstring.
    ==========================  ==========================================

    Every rule's own refusal (``PKG_TIEOUT_FAIL``, ``PKG_SIGNS_AMBIGUOUS``,
    ``PKG_LEG_AT_MID``, ``NO_UPFRONT``, ...) is carried on the call as
    ``exclusion`` rather than swallowed: the ladder needs a call for every unit
    or the coverage accounting has a hole.
    """
    cfg = cfg or config()
    tau_set = tau_set or taus(pricing, cfg)

    by_key = {u.unit_key: u for u in units_result.units}
    legs_by_unit = {k: v.sort_values("leg_index")
                    for k, v in pricing.legs.groupby("unit_key", sort=False)}
    fit_memo: dict = {}
    calls, rows = [], []
    n_borrowed = 0

    with _probability_clip() as clip:
        for r in pricing.units.to_dict("records"):
            key = r["unit_key"]
            unit = by_key[key]
            base = {c: r.get(c) for c in
                    ("unit_key", "as_of_date", "rule", "kind", "n_legs",
                     "venue_class", "rate_index", "is_lifecycle", "tenor_band",
                     "special_tenor_type")}
            base.update({"deviation_bps": None, "p": None,
                         "signed_weight": None, "dealer_sign": 0,
                         "dealer_sign_point": 0, "sign_disagrees": False,
                         "tau_bucket": None, "tau_bps": None,
                         "mid_bias_bps": None, "in_dead_zone": False,
                         "base_orientation": None, "tieout_bps": None,
                         "margin_bps": None, "rule_flags": None,
                         "exclusion": None})

            if r["failure"] is not None:
                base["exclusion"] = r["failure"]
                rows.append(base)
                calls.append(T.DirectionCall(
                    unit_key=key, rule=r["rule"], deviation_bps=None, p=None,
                    signed_weight=None, dealer_sign=0, exclusion=r["failure"]))
                continue

            cal = tau_set.for_day(r["as_of_date"])
            bk = _bucket_key(r)
            memo = (id(cal), bk)
            fit = fit_memo.get(memo)
            if fit is None:
                fit = cal.for_key(bk)
                fit_memo[memo] = fit

            if r["rule"] == conv.RULE_RATE:
                _rate_call(base, calls, key, r, fit, cfg)
            elif r["rule"] == conv.RULE_UPFRONT:
                _upfront_call(base, calls, key, r, unit, fit)
            elif r["rule"] == pp.RULE_PACKAGE_PRICE:
                if _package_call(base, calls, key, r, unit,
                                 legs_by_unit.get(key), fit):
                    n_borrowed += 1
            else:                                            # pragma: no cover
                raise ValueError(f"unrouted rule {r['rule']!r}")
            rows.append(base)

    frame = pd.DataFrame(rows).reindex(columns=CALL_COLS)
    ex = (frame.assign(_e=frame["exclusion"].astype(object).fillna("(called)"))
          .groupby(["rule", "_e"], observed=True)
          .size().reset_index(name="n_units")
          .rename(columns={"_e": "exclusion"})
          .sort_values(["rule", "n_units"], ascending=[True, False]))

    called = frame[frame["exclusion"].isna()]
    diagnostics = {
        "n_units": len(frame),
        "n_called": len(called),
        "n_excluded": int(frame["exclusion"].notna().sum()),
        "by_rule": called["rule"].value_counts().to_dict(),
        "n_package_p_borrowed": n_borrowed,
        "sign_fragile_disagreements": int(called["sign_disagrees"].sum()),
        "n_dead_zone": int(called["in_dead_zone"].sum()),
        "probability_clip": dict(clip),
        "mean_abs_signed_weight": float(called["signed_weight"].abs().mean())
        if len(called) else np.nan,
        "calibration_mode": tau_set.mode,
    }
    _assert_weights(called)
    return CallsResult(calls=calls, frame=frame, exclusions=ex,
                       diagnostics=diagnostics)


def _assert_weights(called: pd.DataFrame) -> None:
    """``2p-1`` re-derived, exactly as ``ladder._assert_weight_agrees_with_side``.

    Checked here as well as there because the ladder sees one call at a time and
    raises on the first bad one; this says how many.
    """
    if called.empty:
        return
    w = 2.0 * called["p"].astype(float) - 1.0
    bad = (w - called["signed_weight"].astype(float)).abs() > 1e-12
    if bad.any():
        raise AssertionError(f"{int(bad.sum())} call(s) carry signed_weight != 2p-1")
    side = called["dealer_sign"].astype(int)
    mism = (w != 0) & (side != 0) & ((w > 0) != (side > 0))
    if mism.any():
        raise AssertionError(
            f"{int(mism.sum())} call(s) have signed_weight and dealer_sign on "
            "opposite sides; ladder.unit_ladder_rows would refuse them")


def _rate_call(base, calls, key, r, fit, cfg) -> None:
    dev = float(r["deviation_bps"])
    call = P.direction_probability(dev, fit, cfg.dead_zone_delta)
    # `dealer_side` on the BIAS-CORRECTED deviation, which is what `p` is a
    # function of -- `sigmoid((dev - b0)/tau) > 0.5` iff `dev > b0`. Taking the
    # raw deviation would disagree with the weight on any print between 0 and
    # `b0`, and `ladder._assert_weight_agrees_with_side` refuses that.
    side = conv.dealer_side(dev - fit.b0)
    base.update({"deviation_bps": dev, "p": call.p,
                 "signed_weight": call.signed_weight, "dealer_sign": side,
                 "dealer_sign_point": side, "tau_bucket": call.tau_bucket,
                 "tau_bps": call.tau_bps, "mid_bias_bps": call.mid_bias_bps,
                 "in_dead_zone": bool(call.in_dead_zone),
                 "rule_flags": ",".join(call.flags) if call.flags else None})
    calls.append(T.DirectionCall(
        unit_key=key, rule=conv.RULE_RATE, deviation_bps=dev, p=call.p,
        signed_weight=call.signed_weight, dealer_sign=side,
        tau_bucket=call.tau_bucket, tau_bps=call.tau_bps,
        mid_bias_bps=call.mid_bias_bps, in_dead_zone=bool(call.in_dead_zone)))


def _upfront_call(base, calls, key, r, unit, fit) -> None:
    tau = U.TauUpfront(
        tau_bps=fit.tau, bias_bps=fit.b0, half_spread_bps=fit.h,
        sigma_bps=fit.s, n=fit.n_trimmed,
        population=(U.POPULATION_LIFECYCLE if unit.is_lifecycle
                    else U.POPULATION_FLOW),
        bucket=fit.bucket)
    c = U.classify(npv_pay=r["npv_pay"], upfront=r["upfront"],
                   structure_dv01=r["structure_dv01"],
                   upfront_source=r["upfront_source"],
                   is_lifecycle=bool(unit.is_lifecycle),
                   is_capped=bool(unit.is_capped),
                   tau=tau, mid_sigma_bps=fit.s, mid_bias_bps=fit.b0)
    if c.exclusion is not None or c.p is None or c.signed_weight is None:
        reason = c.exclusion or T.EXCL_PRICING_ERROR
        base.update({"exclusion": reason, "deviation_bps": c.edge_bps,
                     "rule_flags": ",".join(c.flags) if c.flags else None})
        calls.append(T.DirectionCall(
            unit_key=key, rule=conv.RULE_UPFRONT, deviation_bps=c.edge_bps,
            p=None, signed_weight=None, dealer_sign=0, exclusion=reason))
        return
    # TRAP A (module docstring): the point call and the marginalised p are two
    # estimators and `upfront.classify` documents them as allowed to disagree
    # inside the FLAG_SIGN_FRAGILE set -- but the ladder refuses a call whose
    # weight and side disagree. The ladder aggregates `2p-1`, so the weight's
    # own side is what is loaded, and the point call is carried beside it.
    w = float(c.signed_weight)
    side = 1 if w > 0 else (-1 if w < 0 else 0)
    disagrees = bool(side != 0 and int(c.dealer_sign) != 0
                     and side != int(c.dealer_sign))
    base.update({"deviation_bps": c.edge_bps, "p": c.p, "signed_weight": w,
                 "dealer_sign": side, "dealer_sign_point": int(c.dealer_sign),
                 "sign_disagrees": disagrees, "tau_bucket": c.tau_bucket,
                 "tau_bps": c.tau_bps, "mid_bias_bps": c.mid_bias_bps,
                 "rule_flags": ",".join(c.flags) if c.flags else None})
    calls.append(T.DirectionCall(
        unit_key=key, rule=conv.RULE_UPFRONT, deviation_bps=c.edge_bps,
        p=c.p, signed_weight=w, dealer_sign=side, tau_bucket=c.tau_bucket,
        tau_bps=c.tau_bps, mid_bias_bps=c.mid_bias_bps))


def _package_call(base, calls, key, r, unit, legs, fit) -> bool:
    """The package-price rule. Returns True when a borrowed ``p`` was formed."""
    if legs is None or legs.empty:                           # pragma: no cover
        raise RuntimeError(f"unit {key!r} priced but has no leg rows")
    c = pp.classify(
        opas=[_f(v) for v in legs["other_payment_amount"]],
        package_price=r["package_transaction_price"],
        npv_pays=[_f(v) for v in legs["npv_pay"]],
        pv01s=[_f(v) for v in legs["pv01"]],
        structure_dv01=r["structure_dv01"],
        is_lifecycle=bool(unit.is_lifecycle),
        ufro_sum=None)
    base.update({"tieout_bps": c.tieout_bps, "margin_bps": c.margin_bps,
                 "deviation_bps": c.deviation_bps,
                 "rule_flags": ",".join(c.flags) if c.flags else None,
                 "base_orientation": (None if c.base_orientation is None
                                      else str(tuple(c.base_orientation)))})
    if c.exclusion is not None:
        base["exclusion"] = c.exclusion
        calls.append(T.DirectionCall(
            unit_key=key, rule=pp.RULE_PACKAGE_PRICE,
            deviation_bps=c.deviation_bps, p=None, signed_weight=None,
            dealer_sign=0, exclusion=c.exclusion))
        return False

    # TRAP B: no package tau exists. Borrow the pooled rate-rule fit with `b0`
    # forced to zero -- the rate-rule bias is in bp of the structure's quoted
    # price and this deviation is in bp of package DV01, so it does not
    # transfer; and zeroing it makes sign(2p-1) == dealer_side(dev) by
    # construction. Lifecycle flips `p -> 1-p`, which is `sigmoid(-z)`.
    dev = float(c.deviation_bps)
    p = float(P.p_customer_paid(dev, dataclasses.replace(fit, b0=0.0)))
    if unit.is_lifecycle:
        p = 1.0 - p
    w = conv.signed_weight(p)
    side = int(c.dealer_sign)
    if side != 0 and w != 0.0 and (w > 0) != (side > 0):     # pragma: no cover
        raise AssertionError(
            f"unit {key!r}: the borrowed p landed on the opposite side from "
            f"package_price's own dealer_sign ({side}); the b0-zeroing that "
            "makes those identical has been broken")
    label = f"BORROWED_B0_ZEROED:{fit.bucket}"
    half = P.dead_zone_half_width_bps(fit.tau)
    base.update({"p": p, "signed_weight": w, "dealer_sign": side,
                 "dealer_sign_point": side, "tau_bucket": label,
                 "tau_bps": fit.tau, "mid_bias_bps": 0.0,
                 "in_dead_zone": bool(abs(dev) < half)})
    calls.append(T.DirectionCall(
        unit_key=key, rule=pp.RULE_PACKAGE_PRICE, deviation_bps=dev, p=p,
        signed_weight=w, dealer_sign=side, tau_bucket=label, tau_bps=fit.tau,
        mid_bias_bps=0.0, in_dead_zone=bool(abs(dev) < half),
        base_orientation=tuple(c.base_orientation)))
    return True


# ===========================================================================
# stage 6 -- key-rate risk
# ===========================================================================

@dataclasses.dataclass
class KrdResult:
    """Signed key-rate profiles and the named remainder."""

    krd: pd.DataFrame                 #: unit_key, bucket_space, bucket_key,
    #: dv01_if_received, and (when weights are attached) delta_dv01
    failures: pd.DataFrame
    warnings: pd.DataFrame = dataclasses.field(default_factory=pd.DataFrame)
    seconds: float = 0.0


def krd_frame(units_result: UnitsResult, calls_result: CallsResult,
              cfg: Config | None = None,
              *, days: list[str] | None = None) -> KrdResult:
    """The 28-pillar signed key-rate profile per unit, cached per day.

    ``dv01_if_received`` is the profile the dealer would hold **if the dealer
    received fixed** -- the hypothesis orientation, per leg, from
    ``krd.received_hypothesis_signs``. It is signed by the *structure* (or, for
    a recovered package, by ``base_orientation``); it is **not** yet signed by
    the direction call. ``delta_dv01 = signed_weight * dv01_if_received`` is
    attached here for convenience and produced for real by the ladder.

    The cache key omits the calibration deliberately: ``krd_frame`` reads only
    ``rule``, ``exclusion`` and ``base_orientation``, so a different ``taus``
    correctly reuses this risk.
    """
    cfg = cfg or config()
    ud = units_result.units_by_day()
    call_by_key = {c.unit_key: c for c in calls_result.calls}
    cache = _stage_dir(cfg, "krd")
    days = days or sorted(ud)
    t0 = time.perf_counter()
    kparts, fparts = [], []
    proj = None
    tally = _WarningTally()
    with tally.capture():
        for day in days:
            kp = cache / f"{day}.krd.parquet"
            fp = cache / f"{day}.krdfail.parquet"
            if cfg.use_cache and kp.exists() and fp.exists():
                _log_cache("krd_frame", hit=1, where=str(cache))
                kparts.append(pd.read_parquet(kp))
                fparts.append(pd.read_parquet(fp))
                continue
            _log_cache("krd_frame", miss=1, where=str(cache))
            pop, _rules = pricing_population(ud.get(day, []), cfg)
            pop = [u for u in pop if u.unit_key in call_by_key]
            sub = [call_by_key[u.unit_key] for u in pop]
            if proj is None:
                _rep, proj = _engines(cfg)
            with proj.day_scope():
                kf, kfail = proj.krd_frame(pop, sub)
            kf = kf.reindex(columns=krd_mod.KRD_COLUMNS)
            kfail = kfail.reindex(columns=krd_mod.FAILURE_COLUMNS)
            _atomic_parquet(kf, kp)
            _atomic_parquet(kfail, fp)
            kparts.append(kf)
            fparts.append(kfail)
    kf = pd.concat(kparts, ignore_index=True)
    fail = pd.concat(fparts, ignore_index=True)

    w = calls_result.frame[["unit_key", "signed_weight", "p", "rule",
                            "venue_class", "as_of_date"]]
    kf = kf.merge(w, on="unit_key", how="left", validate="many_to_one")
    kf["delta_dv01"] = kf["signed_weight"] * kf["dv01_if_received"]
    kf["tenor_bucket"] = kf["bucket_key"].map(ind.PILLAR_BUCKET)
    if len(kf) and kf["tenor_bucket"].isna().any():
        raise RuntimeError("a KRD pillar has no TENOR10 bucket")
    return KrdResult(krd=kf, failures=fail, warnings=tally.frame(),
                     seconds=time.perf_counter() - t0)


# ===========================================================================
# stage 7 -- ladder and daily indicator
# ===========================================================================

@dataclasses.dataclass
class LadderResult:
    """Per-unit ladder contributions, the cell aggregate, and the remainder."""

    unit_rows: pd.DataFrame
    excluded: pd.DataFrame
    ladder: pd.DataFrame              #: `ladder.aggregate`, pillar space
    customer_flow: pd.DataFrame
    interdealer_flow: pd.DataFrame
    #: Why each excluded unit was excluded, one level finer than the ladder's
    #: own vocabulary. See :func:`ladder_rows`.
    remainder: pd.DataFrame = dataclasses.field(default_factory=pd.DataFrame)


def ladder_rows(units_result: UnitsResult, calls_result: CallsResult,
                krd_result: KrdResult, cfg: Config | None = None,
                *, drop_dead_zone: bool = False) -> LadderResult:
    """``ladder.unit_ladder_rows`` over the population, plus the aggregate.

    ``unit_ladder_rows`` demands that ``units``, ``calls`` and the risk frame be
    a partition -- a call with no unit, a unit twice, or a risk row whose unit is
    absent all raise -- so the inputs are trimmed to the exact population here
    rather than allowed to disagree.

    ``LadderResult.remainder`` splits the ladder's ``excluded`` frame one level
    finer, because ``EXCL_PRICING_ERROR`` there covers two very different
    things. The ladder emits it for **any** called unit with no risk rows, and
    on this window all nine of them are ``FLAT_PROFILE``: two-leg packages whose
    legs are *identical* -- same effective date, same maturity, same notional,
    same rate -- so the ``CURVE`` orientation ``(-1, +1)`` builds an exactly
    offsetting portfolio, every one of the 28 pillar deltas is ``0.0``, and
    ``dust_frac = 0`` drops exact zeros. Their quoted price is identically zero
    too (``-R0 + R1`` on one rate), so they carry ``p = 0.5`` and no weight.
    Nothing is lost; the *reason* is just not a pricing error, and a coverage
    table that reports it as one is wrong about nine units.
    """
    cfg = cfg or config()
    call_by_key = {c.unit_key: c for c in calls_result.calls}
    pop = []
    seen = set()
    for day, us in sorted(units_result.units_by_day().items()):
        day_pop, _ = pricing_population(us, cfg)
        for u in day_pop:
            if u.unit_key in call_by_key and u.unit_key not in seen:
                seen.add(u.unit_key)
                pop.append(u)
    calls = [call_by_key[u.unit_key] for u in pop]
    krd = krd_result.krd[krd_result.krd["unit_key"].isin(seen)][
        ["unit_key", "bucket_space", "bucket_key", "dv01_if_received"]]

    rows, excluded = ladder_mod.unit_ladder_rows(
        pop, calls, krd, drop_dead_zone=drop_dead_zone,
        curve_source=cfg.curve_source)
    agg = ladder_mod.aggregate(rows)

    call_excl = {c.unit_key: c.exclusion for c in calls}
    krd_fail = dict(zip(krd_result.failures["unit_key"],
                        krd_result.failures["failure_reason"]))
    with_risk = set(krd["unit_key"])
    fine = []
    for k in excluded["unit_key"]:
        if call_excl.get(k) is not None:
            why = f"RULE:{call_excl[k]}"
        elif k in krd_fail:
            why = f"KRD:{krd_fail[k]}"
        elif k not in with_risk:
            why = "FLAT_PROFILE"      # every pillar exactly 0.0
        else:
            why = "DEAD_ZONE_DROPPED"
        fine.append({"unit_key": k, "why": why})
    remainder = (pd.DataFrame(fine, columns=["unit_key", "why"])
                 .merge(excluded, on="unit_key", how="left"))

    return LadderResult(
        unit_rows=rows, excluded=excluded, ladder=agg,
        customer_flow=ladder_mod.customer_flow(agg),
        interdealer_flow=ladder_mod.interdealer_flow(agg),
        remainder=remainder)


def daily(ladder_result: LadderResult) -> pd.DataFrame:
    """``indicator.daily_levels`` -- the ten TENOR10 buckets per availability date.

    This is the **level** series, deliberately not ``indicator.build``'s full
    :class:`DailyPositioning`: the published ``z`` needs
    ``indicator.Z_MIN_OBS = 60`` sessions of own history and a three-day pilot
    cannot produce one. That is also the reason the notebook may show levels
    within a bucket over time and **must not** compare levels across buckets --
    retention runs 0.761 at 0-1Y against 0.495 at 15-20Y, a 1.54x distortion,
    and only ``z`` is invariant to a constant retention factor.

    ``daily_levels`` re-asserts on the way in that every row is stamped on the
    availability clock and that ``delta_dv01 == (2p-1) * dv01_if_received``.

    **THE EDGE DATES ARE NOT FULL SESSIONS, AND THE FRAME CANNOT SAY SO.**
    Stamping on availability means the availability dates are not the tape
    dates: on this window ``visibility_lag`` puts 3.96% of units off their own
    ``as_of_date`` (161 at -1, 1 at +1, 33 at +8). So the frame carries a
    2025-06-15 row built only from the backward-stamped part of 06-16's tape
    (64 units against ~1,500 on a full day) and a 2025-06-24 row holding 33
    late-published prints -- while the 06-16 and 06-18 cells are *missing* the
    forward-lagged prints from tape days this window did not load. A notebook
    plotting the daily frame must either drop the edge dates or say what they
    are; read as sessions they are a 95% drop in flow that never happened. The
    only real fix is loading a wider tape window than the one being reported,
    which is a property of any availability-stamped series and not of this
    pilot.
    """
    return ind.daily_levels(ladder_result.unit_rows)


# ===========================================================================
# the whole thing
# ===========================================================================

@dataclasses.dataclass
class Pipeline:
    """Every stage's output, plus the wall clock and row count of each."""

    cfg: Config
    legs: pd.DataFrame
    units: UnitsResult
    pricing: PricingResult
    taus: TauSet
    calls: CallsResult
    krd: KrdResult
    ladder: LadderResult
    daily: pd.DataFrame
    timings: pd.DataFrame
    digest: str
    #: :func:`cache_report` for this run -- which stages were read rather than
    #: computed, and from where. `timings.source` is its one-word summary.
    cache: pd.DataFrame = dataclasses.field(default_factory=pd.DataFrame)

    def one_trade(self, key):
        return one_trade(self, key)


def run_pipeline(cfg: Config | None = None,
                 *, days: list[str] | None = None) -> Pipeline:
    """legs -> units -> marks -> calls -> risk -> ladder -> daily, timed.

    The returned ``timings`` frame carries a ``source`` column and the
    ``cache`` frame carries the paths: three of the eight stages can come off
    disk (``load_legs``, ``price_units``, ``krd_frame``) and one -- ``taus`` --
    is *never* fitted here in the default mode. A 0.04 s ``price_units`` beside
    a 3.28 s ``build_units`` is the only other clue, and a reader should not
    have to infer provenance from a stopwatch.
    """
    cfg = cfg or config()
    _CACHE_LOG.clear()
    rec = []

    def stage(name, fn):
        t0 = time.perf_counter()
        out = fn()
        rec.append({"stage": name, "seconds": time.perf_counter() - t0})
        return out

    legs = stage("load_legs", lambda: load_legs(cfg.start, cfg.end, cfg))
    if days is None:
        days = tape_days(legs)
    else:
        legs = legs[legs["as_of_date"].astype(str).isin(set(days))]
    units = stage("build_units", lambda: build_units(legs, cfg))
    pricing = stage("price_units",
                    lambda: price_units(units, cfg, days=days))
    tau_set = stage("taus", lambda: taus(pricing, cfg))
    calls = stage("classify", lambda: classify(units, pricing, tau_set, cfg))
    krd = stage("krd_frame", lambda: krd_frame(units, calls, cfg, days=days))
    lad = stage("ladder_rows", lambda: ladder_rows(units, calls, krd, cfg))
    dly = stage("daily", lambda: daily(lad))

    counts = {
        "load_legs": len(legs), "build_units": len(units.frame),
        "price_units": len(pricing.units), "taus": len(tau_set.by_day),
        "classify": len(calls.frame), "krd_frame": len(krd.krd),
        "ladder_rows": len(lad.unit_rows), "daily": len(dly),
    }
    timings = pd.DataFrame(rec)
    timings["rows_out"] = timings["stage"].map(counts)
    timings["source"] = timings["stage"].map(cache_source)
    return Pipeline(cfg=cfg, legs=legs, units=units, pricing=pricing,
                    taus=tau_set, calls=calls, krd=krd, ladder=lad, daily=dly,
                    timings=timings, digest=source_digest(cfg),
                    cache=cache_report())


# ===========================================================================
# one print, traced all the way through
# ===========================================================================

def one_trade(pipe: Pipeline, trade_id_or_row) -> dict:
    """One print, end to end. The notebook's centrepiece, so it must be exact.

    Accepts a ``unit_key``, a tape ``trade_id`` (resolved through the leg
    frame), or any row/Series carrying one of those. Returns a dict -- the
    notebook decides how to show it.

    **Nothing here is re-derived by hand.** The snap comes from
    ``snapshot.snap_instant``, the per-leg received signs from
    ``conventions.dealer_received_signs`` or
    ``package_price.received_hypothesis_signs``, the profile from the unit's own
    KRD rows. The unit is additionally **repriced live** through the same
    ``UnitRepricer`` and the recomputed deviation is compared against the cached
    one: a trace that agreed with a stale cache and disagreed with the pipeline
    would be the worst possible centrepiece.
    """
    key = _resolve_key(pipe, trade_id_or_row)
    urow = pipe.pricing.units[pipe.pricing.units["unit_key"] == key]
    if urow.empty:
        raise KeyError(f"{key!r} is not in the priced population")
    urow = urow.iloc[0]
    unit = next(u for u in pipe.units.units if u.unit_key == key)
    crow = pipe.calls.frame[pipe.calls.frame["unit_key"] == key].iloc[0]
    call = next(c for c in pipe.calls.calls if c.unit_key == key)
    legs = (pipe.pricing.legs[pipe.pricing.legs["unit_key"] == key]
            .sort_values("leg_index"))

    snap = snapshot.snap_instant(unit.clocks.pricing)
    rule = urow["rule"]

    # --- the curve, live, through the pipeline's own repricer --------------
    rep, _ = _engines(pipe.cfg, shared=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with rep.day_scope():
            curve_name = rep.pricer.curve_for(unit.rate_index)
            policy = rep.pricer.policy_for_instant(curve_name, snap)
            in_sess = snapshot.in_session(curve_name, snap)
            live = rep.price_unit(unit)
            live_dev = (np.nan if live.failure is not None
                        else _rate_deviation(unit, rule, live)[2])

    def _diff(a, b):
        """``|a - b|``, or ``None`` when either side has no value to compare."""
        if a is None or b is None or pd.isna(a) or pd.isna(b):
            return None
        return abs(float(a) - float(b))

    recheck = {
        "live_failure": live.failure,
        "cached_failure": urow["failure"],
        "live_deviation_bps": (None if live_dev is None or pd.isna(live_dev)
                               else float(live_dev)),
        "cached_deviation_bps": _none_if_nan(urow["deviation_bps"]),
        "max_abs_mid_diff_pct": (
            float(np.nanmax(np.abs(
                np.asarray([np.nan if m is None else m
                            for m in live.pricing.leg_mid_pct], dtype=float)
                - legs["mid_pct"].to_numpy(dtype=float))))
            if live.failure is None and legs["mid_pct"].notna().any()
            else None),
        # The mid is the input; these three are what the rules read off it, and
        # a trace that checked only the input would miss a divergence in
        # `structure_dv01` -- which is the denominator every deviation in bp is
        # formed against, for all three rules.
        "deviation_diff": _diff(live_dev, urow["deviation_bps"]),
        "npv_pay_diff": _diff(live.pricing.npv_pay, urow["npv_pay"]),
        "structure_dv01_diff": _diff(live.pricing.structure_dv01,
                                     urow["structure_dv01"]),
        "gross_pv01_diff": _diff(live.gross_pv01, urow["gross_pv01"]),
    }
    _tol = {"max_abs_mid_diff_pct": 1e-12, "deviation_diff": 1e-9,
            "npv_pay_diff": 1e-6, "structure_dv01_diff": 1e-6,
            "gross_pv01_diff": 1e-6}
    recheck["agrees"] = bool(
        recheck["live_failure"] == recheck["cached_failure"]
        and all(recheck[k_] is None or recheck[k_] < t
                for k_, t in _tol.items()))

    # --- per-leg received signs, from the modules that own them ------------
    # `krd.received_hypothesis_signs` is the dispatcher the risk stage itself
    # uses, so the hypothesis shown here is the one the KRD was built from --
    # not a second derivation that could differ.
    side = int(crow["dealer_sign"])
    hyp = None
    if rule != pp.RULE_PACKAGE_PRICE or call.base_orientation is not None:
        hyp = krd_mod.received_hypothesis_signs(unit.kind, unit.n_legs, rule,
                                                call)
    if hyp is None or side == 0:
        received = None
    elif rule == pp.RULE_PACKAGE_PRICE:
        # `package_price.classify`'s own composition: received = dealer_sign *
        # base_orientation, with the tear-up flip already inside dealer_sign.
        received = tuple(side * s for s in hyp)
    else:
        received = conv.dealer_received_signs(unit.kind, unit.n_legs, rule, side)

    # --- the risk profile ---------------------------------------------------
    k = pipe.krd.krd[pipe.krd.krd["unit_key"] == key]
    krd_vec = dict(zip(k["bucket_key"], k["dv01_if_received"].astype(float)))
    krd_vec = {p_: krd_vec[p_] for p_ in krd_mod.PILLARS if p_ in krd_vec}
    delta_vec = {p_: float(v) * float(crow["signed_weight"])
                 for p_, v in krd_vec.items()} if pd.notna(
                     crow["signed_weight"]) else {}
    bucket_vec = (k.groupby("tenor_bucket", observed=True)["delta_dv01"]
                  .sum().to_dict() if len(k) else {})
    kfail = pipe.krd.failures[pipe.krd.failures["unit_key"] == key]

    lr = pipe.ladder.unit_rows[pipe.ladder.unit_rows["unit_key"] == key]

    return {
        "unit_key": key,
        "trade_ids": [str(x) for x in legs["trade_id"]],
        "package_id": unit.package_id,
        "kind": unit.kind, "n_legs": int(unit.n_legs), "rule": rule,
        "venue_class": unit.venue_class, "rate_index": unit.rate_index,
        "as_of_date": str(unit.as_of_date),
        "is_lifecycle": bool(unit.is_lifecycle),
        "is_block": bool(unit.is_block), "is_capped": bool(unit.is_capped),
        "tenor_band": urow["tenor_band"],
        "special_tenor_type": urow["special_tenor_type"],

        "clocks": {
            "execution_timestamp": unit.clocks.execution,
            "event_timestamp": unit.clocks.event,
            "pricing": unit.clocks.pricing,
            "visibility": unit.clocks.visibility,
            "visibility_source": unit.clocks.visibility_source,
            "visibility_date": ladder_mod.visibility_date(unit.clocks.visibility),
        },
        "snap": {
            "snap_instant": snap,
            "rule": "T-1min (snapshot.snap_instant)",
            "curve_name": curve_name,
            "snapshot_policy": policy,
            "in_citi_session": in_sess,
            "snapshot_lag_seconds": urow["snapshot_lag_s"],
            "block_key": krd_mod.block_key(snap, pipe.cfg.block_minutes),
        },
        "legs": legs.to_dict("records"),
        "structure": {
            "traded_price_bps": _none_if_nan(urow["traded_price_bps"]),
            "mid_price_bps": _none_if_nan(urow["mid_price_bps"]),
            "deviation_bps": _none_if_nan(crow["deviation_bps"]),
            "structure_dv01": _none_if_nan(urow["structure_dv01"]),
            "gross_pv01": _none_if_nan(urow["gross_pv01"]),
            "npv_pay": _none_if_nan(urow["npv_pay"]),
            "upfront": _none_if_nan(urow["upfront"]),
            "upfront_source": urow["upfront_source"],
            "quote_weights": (None if rule == pp.RULE_PACKAGE_PRICE
                              else conv.quote_weights(unit.kind, unit.n_legs,
                                                      rule)),
            "tieout_bps": _none_if_nan(crow["tieout_bps"]),
            "margin_bps": _none_if_nan(crow["margin_bps"]),
        },
        "tau": {
            "tau_bucket": crow["tau_bucket"], "tau_bps": _none_if_nan(crow["tau_bps"]),
            "mid_bias_bps": _none_if_nan(crow["mid_bias_bps"]),
            "borrowed": bool(str(crow["tau_bucket"] or "")
                             .startswith("BORROWED")),
        },
        "call": {
            "p": _none_if_nan(crow["p"]),
            "signed_weight": _none_if_nan(crow["signed_weight"]),
            "dealer_sign": side,
            "dealer_sign_point": int(crow["dealer_sign_point"]),
            "sign_disagrees": bool(crow["sign_disagrees"]),
            "in_dead_zone": bool(crow["in_dead_zone"]),
            "exclusion": crow["exclusion"],
            "rule_flags": crow["rule_flags"],
            # gated on the net this very trace computed -- see `_side_words`
            "dealer_side_words": _side_words(
                side, (float(sum(delta_vec.values())) if delta_vec else None)),
        },
        "orientation": {
            "base_orientation": (tuple(call.base_orientation)
                                 if call.base_orientation is not None else
                                 (None if rule == pp.RULE_PACKAGE_PRICE
                                  else conv.base_orientation(unit.kind,
                                                             unit.n_legs, rule))),
            "received_hypothesis_signs": hyp,
            "per_leg_received_signs": received,
            "legend": "+1 = dealer received fixed on that leg",
        },
        "krd": {
            "dv01_if_received": krd_vec,
            "delta_dv01": delta_vec,
            "tenor_bucket_delta_dv01": bucket_vec,
            "n_pillars": len(krd_vec),
            "failure": (None if kfail.empty
                        else kfail.iloc[0].to_dict()),
        },
        "ladder_rows": lr.to_dict("records"),
        "recheck": recheck,
    }


def _side_words(side: int, net_dv01: float | None = None) -> str:
    """The direction sentence -- with the ``delta_dv01`` tail **gated on the net**.

    The pinned convention is per **leg**: ``+1`` on a leg means the dealer
    received fixed on that leg. For an ``OUTRIGHT`` there is one leg and the
    net follows the call, so ``-> delta_dv01 > 0`` is simply true. For a
    two-sided structure -- a ``CURVE``, a ``FLY``, a recovered ``PKG-N`` --
    it need not be: the net follows whichever leg carries the larger DV01, so
    a package the dealer *received* can net short. On the pilot window the net
    follows the call on 100% of outrights but only 76% of curves, 74% of flies
    and 23% of packages.

    Printing ``-> delta_dv01 > 0`` beside a computed net of -5,243 USD/bp would
    be a false claim about the sign of the risk the same trace just produced,
    in a notebook whose entire subject is a sign. So the tail is asserted only
    when ``net_dv01`` confirms it, and contradicted explicitly when it does
    not. Pass ``net_dv01=None`` only where the net is genuinely unknown.
    """
    if side > 0:
        words = ("dealer RECEIVED fixed -> customer paid fixed -> dealer long "
                 "duration")
        tail, ok = "delta_dv01 > 0", (net_dv01 is not None and net_dv01 > 0)
    elif side < 0:
        words = ("dealer PAID fixed -> customer received fixed -> dealer short "
                 "duration")
        tail, ok = "delta_dv01 < 0", (net_dv01 is not None and net_dv01 < 0)
    else:
        return "no call (exact tie)"
    if net_dv01 is None:
        return f"{words} -> {tail} on the legs the call orients"
    if ok:
        return f"{words} -> {tail}   (net sum {net_dv01:+,.1f} USD/bp)"
    return (f"{words} ON THE LEGS IT ORIENTS -- but the NET does not follow "
            f"the call here: sum(delta_dv01) = {net_dv01:+,.1f} USD/bp, not "
            f"{tail}. A two-sided structure nets the way its largest leg "
            f"points; the per-leg received signs are the invariant, not the "
            f"net.")


def net_claim_ok(trace: dict) -> bool:
    """Does a :func:`one_trade` trace's direction sentence match its own net?

    The assertion that pairs with :func:`_side_words`. It fails in **both**
    directions -- a sentence that claims a net sign the KRD does not show, and
    a sentence that disclaims one it does -- so a regression cannot quietly go
    back to teaching the wrong sign.
    """
    dv = trace["krd"]["delta_dv01"] or {}
    net = float(sum(dv.values()))
    words = trace["call"]["dealer_side_words"] or ""
    disclaimed = "does not follow the call" in words
    return disclaimed == (int(np.sign(net)) != int(trace["call"]["dealer_sign"]))


def _none_if_nan(v):
    if v is None:
        return None
    try:
        return None if pd.isna(v) else (float(v) if isinstance(v, (int, float,
                                                                   np.floating))
                                        else v)
    except (TypeError, ValueError):
        return v


def _resolve_key(pipe: Pipeline, x) -> str:
    if isinstance(x, (pd.Series, dict)):
        for c in ("unit_key", "trade_id"):
            v = x.get(c) if isinstance(x, dict) else x.get(c, None)
            if v is not None and not pd.isna(v):
                return _resolve_key(pipe, v)
        raise KeyError("row carries neither unit_key nor trade_id")
    s = str(x)
    if (pipe.pricing.units["unit_key"] == s).any():
        return s
    hit = pipe.pricing.legs.loc[pipe.pricing.legs["trade_id"].astype(str) == s,
                                "unit_key"]
    if len(hit):
        return str(hit.iloc[0])
    raise KeyError(f"{s!r} is neither a unit_key nor a trade_id in this window")


# ===========================================================================
# convenience views the notebook will want
# ===========================================================================

def priced_fraction(pricing: PricingResult) -> pd.DataFrame:
    """Priced fraction by ``start_class``, per day and pooled.

    ``midprice.start_class`` cuts against the **snap**, not ``as_of_date``: a
    leg is past-start when its accrual has begun by the instant being priced,
    and that is what decides whether published fixings enter its rate.

    **The spot window is three CALENDAR days** (``midprice._SPOT_WINDOW_DAYS``),
    and spot settlement is T+2 **business** days -- so a holiday moves a whole
    session's spot book into the forward stratum. It happens inside this pilot
    window and the notebook must not read it as a change in what was traded:
    2025-06-19 is Juneteenth, so T+2 from Wednesday 2025-06-18 is Monday
    2025-06-23, five calendar days out. Measured by :func:`spot_window_check`:
    the modal effective date is 06-18 on 06-16 (2 days from the snap, 1,109 legs
    all SPOT), 06-20 on 06-17 (3 days, 1,153 SPOT + 60 FORWARD_START -- the 60
    are evening prints whose snap date is the 16th), and 06-23 on 06-18 (5 days,
    **1,138 legs, every one FORWARD_START**). That is why 06-18 shows 2,010
    forward legs against 314 spot while the two days before it show the reverse.
    Only the stratum *label* moves; no mid, no deviation and no risk changes.
    """
    return pricing.coverage.sort_values(["as_of_date", "start_class"])


def spot_window_check(pricing: PricingResult) -> pd.DataFrame:
    """Modal effective date and its lag from the SNAP, per day -- the trap, measured.

    Returned rather than described so the notebook shows the holiday rather
    than asserting it.

    The lag is measured from ``midprice._instant_date(snap_instant)``, which is
    the reference ``start_class`` actually cuts against -- **not**
    ``as_of_date``. The two differ on every print whose snap falls on the
    previous date, so a table built on ``as_of_date`` reports a modal lag of 3
    beside a modal class of FORWARD_START and looks like a bug in the module
    rather than a property of one evening's prints. ``start_class_at_modal`` is
    therefore a tally, not a single label.
    """
    u = pricing.units[["unit_key", "snap_instant"]]
    l = pricing.legs.merge(u, on="unit_key", how="left")
    ref = pd.to_datetime(l["snap_instant"].map(
        lambda t: None if t is None or pd.isna(t) else midprice._instant_date(t)))
    l["days_from_snap"] = (pd.to_datetime(l["effective_date"]) - ref).dt.days
    out = []
    for day, g in l.groupby("as_of_date", observed=True):
        modal = g["effective_date"].mode()
        eff = modal.iloc[0] if len(modal) else None
        sub = g[g["effective_date"] == eff]
        lag = sub["days_from_snap"].mode()
        out.append({
            "as_of_date": day, "modal_effective_date": eff,
            "n_legs_at_modal": len(sub),
            "modal_days_from_snap": int(lag.iloc[0]) if len(lag) else None,
            "start_class_at_modal": sub["start_class"].value_counts().to_dict(),
            "spot_window_days": midprice._SPOT_WINDOW_DAYS})
    return pd.DataFrame(out)


def snap_hour_coverage(pricing: PricingResult) -> pd.DataFrame:
    """Priced fraction by New York hour of the snap, **per day**.

    Per day and not pooled: the Citi minute store's overnight hole is a
    property of one session's publication, and pooling three days across it
    turns "every 22:00 ET print on 2025-06-17 failed" into "36% of 22:00 ET
    prints failed", which reads as a flaky curve rather than a missing window.
    """
    u = pricing.units.copy()
    u["snap_hour_ny"] = pd.to_datetime(
        u["snap_instant"], utc=True, format="mixed", errors="coerce"
    ).dt.tz_convert(snapshot.NY).dt.hour
    g = (u.assign(ok=u["failure"].isna())
         .groupby(["as_of_date", "snap_hour_ny"], observed=True)["ok"]
         .agg(n_units="size", priced_frac="mean").reset_index())
    return g[g["priced_frac"] < 1.0].sort_values(["as_of_date", "snap_hour_ny"])


#: Summary frames :func:`write_outputs` persists. Small by construction -- the
#: per-unit and per-pillar frames stay in the (D:) stage cache.
OUTPUT_FRAMES = ("units_by_day", "exclusions", "priced_fraction",
                 "spot_window", "snap_hour_coverage", "rule_mix",
                 "call_exclusions", "calibration_provenance",
                 "ladder_remainder", "visibility_lag", "daily_levels",
                 "timings")


def output_frames(pipe: "Pipeline") -> dict:
    """The small summary frames, by name. What the notebook plots."""
    return {
        "units_by_day": pipe.units.by_day,
        "exclusions": pipe.units.exclusions,
        "priced_fraction": priced_fraction(pipe.pricing),
        "spot_window": spot_window_check(pipe.pricing),
        "snap_hour_coverage": snap_hour_coverage(pipe.pricing),
        "rule_mix": rule_mix(pipe.calls),
        "call_exclusions": pipe.calls.exclusions,
        "calibration_provenance": pipe.taus.provenance,
        "ladder_remainder": pipe.ladder.remainder,
        "visibility_lag": visibility_lag(pipe.ladder),
        "daily_levels": pipe.daily,
        "timings": pipe.timings,
    }


def write_outputs(pipe: "Pipeline", out_dir: pathlib.Path | None = None) -> dict:
    """Persist the summary frames as CSV under ``Config.out_dir``.

    ``{name: path}``. CSV rather than parquet because these are read by eye as
    often as by pandas, and they are kilobytes. The heavy frames are not written
    -- they live in the stage cache, keyed on the source digest, and copying
    them here would be a second copy that can go stale.
    """
    out = pathlib.Path(out_dir or pipe.cfg.out_dir) / pipe.cfg.window
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, df in output_frames(pipe).items():
        p = out / f"{name}.csv"
        pd.DataFrame(df).to_csv(p, index=False)
        paths[name] = p
    return paths


def visibility_lag(ladder_result: LadderResult) -> pd.DataFrame:
    """``visibility_date - as_of_date`` in days, per unit, tallied.

    Every aggregation stamps on **availability**, not execution, and Part 43's
    Appendix C delay is not one number. On this window it produces three
    populations: 161 units land on the *previous* New York date (a Sunday- or
    late-evening ET print whose UTC ``as_of_date`` is already tomorrow), 4,734
    land same-day, and **33 uncleared off-facility prints from 2025-06-16 do
    not become actionable until 2025-06-24** -- eight days. A ladder stamped on
    execution would claim all 33 were tradeable on the 16th.
    """
    ur = ladder_result.unit_rows.drop_duplicates("unit_key")
    lag = (pd.to_datetime(ur["visibility_date"])
           - pd.to_datetime(ur["as_of_date"])).dt.days
    return (ur.assign(lag_days=lag)
            .groupby(["lag_days", "visibility_source"], observed=True)
            .size().reset_index(name="n_units")
            .sort_values(["lag_days", "n_units"], ascending=[True, False]))


def rule_mix(calls_result: CallsResult) -> pd.DataFrame:
    """Units and gross weight by rule -- how much of the book each rule carries."""
    c = calls_result.called
    return (c.assign(abs_w=c["signed_weight"].abs())
            .groupby("rule", observed=True)
            .agg(n_units=("unit_key", "size"),
                 mean_abs_signed_weight=("abs_w", "mean"),
                 mean_p=("p", "mean"),
                 n_dead_zone=("in_dead_zone", "sum"))
            .reset_index())


def bucket_levels(daily_frame: pd.DataFrame,
                  venue: str = T.VENUE_D2C,
                  series: str = ladder_mod.SERIES_FLOW) -> pd.DataFrame:
    """One venue/series slice of the daily levels, buckets in curve order.

    **Levels are within-bucket quantities.** Comparing 0-1Y against 15-20Y
    compares two different retention rates (0.761 vs 0.495).
    """
    d = daily_frame[(daily_frame["venue_class"] == venue)
                    & (daily_frame["series"] == series)].copy()
    order = {b: i for i, b in enumerate(ind.TENOR_BUCKETS)}
    d["_o"] = d["bucket_key"].map(order)
    return d.sort_values(["visibility_date", "_o"]).drop(columns="_o")


# ===========================================================================
# self-test
# ===========================================================================

def _selftest(cfg: Config | None = None) -> int:
    """Run the whole pipeline over three tape days and assert the shapes are sane.

    Exit code 0 is not the contract -- **non-empty frames** are. Every assertion
    below is written so that a stage returning an empty frame fails loudly, and
    ``scratch/nbhelp_mutate.py`` proves that by breaking the pipeline four ways
    and checking this function reports each one.

    ``cfg`` is a parameter so a mutation run can point at a throwaway cache
    directory: a monkeypatch does not change ``source_digest``, so a mutated
    stage sharing the real cache would poison it.
    """
    pd.set_option("display.width", 200)
    cfg = cfg or config()
    print("=" * 78)
    print(f"dd_nb self-test | window {cfg.start}..{cfg.end} | "
          f"digest {source_digest(cfg)}")
    print(f"cache {cfg.cache_dir} | indices {cfg.indices} | "
          f"lifecycle {cfg.include_lifecycle} | calib {cfg.calibration}")
    print("=" * 78)

    t0 = time.perf_counter()
    pipe = run_pipeline(cfg)
    wall = time.perf_counter() - t0

    days = tape_days(pipe.legs)
    assert len(days) == 3, f"expected three tape days, got {days}"

    # ---- shapes ---------------------------------------------------------
    checks = []

    def ck(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    ck("legs non-empty", len(pipe.legs) > 0, f"{len(pipe.legs)} rows")
    ck("unit frame non-empty", len(pipe.units.frame) > 0,
       f"{len(pipe.units.frame)} units")
    ck("units kept", len(pipe.units.units) > 0,
       f"{len(pipe.units.units)} kept")
    ck("exclusion accounting is a partition",
       len(pipe.units.units) + len(pipe.units.excluded) == len(pipe.units.frame),
       f"{len(pipe.units.units)} + {len(pipe.units.excluded)} "
       f"== {len(pipe.units.frame)}")
    ck("priced units non-empty", len(pipe.pricing.priced) > 0,
       f"{len(pipe.pricing.priced)}/{len(pipe.pricing.units)}")
    ck("leg quotes non-empty", len(pipe.pricing.legs) > 0,
       f"{len(pipe.pricing.legs)} legs")
    ck("all three start classes present",
       {"SPOT", "FORWARD_START", "PAST_START"}
       <= set(pipe.pricing.legs["start_class"]),
       str(sorted(set(pipe.pricing.legs["start_class"]))))
    ck("calibration covers every day",
       all(_as_date(d) in pipe.taus.by_day for d in days),
       f"{len(pipe.taus.by_day)} days, mode {pipe.taus.mode}")
    ck("calls cover every priced unit",
       len(pipe.calls.frame) == len(pipe.pricing.units),
       f"{len(pipe.calls.frame)} calls")
    ck("all three rules produced calls",
       len(pipe.calls.diagnostics["by_rule"]) == 3,
       str(pipe.calls.diagnostics["by_rule"]))
    ck("at least one recovered PKG-N was oriented",
       pipe.calls.diagnostics["by_rule"].get(pp.RULE_PACKAGE_PRICE, 0) >= 1,
       f"{pipe.calls.diagnostics['n_package_p_borrowed']} borrowed p")
    # The whole point of the third rule is a per-leg orientation the upfront
    # fallback cannot produce. `(1,)*n` is exactly what that fallback returns,
    # so a recovery that only ever produced uniform vectors would be indis-
    # tinguishable from not having run.
    pkg_orients = [tuple(c.base_orientation) for c in pipe.calls.calls
                   if c.rule == pp.RULE_PACKAGE_PRICE
                   and c.base_orientation is not None]
    two_sided = [o for o in pkg_orients if len(set(o)) > 1]
    ck("recovered packages carry a TWO-SIDED orientation",
       len(two_sided) >= 1,
       f"{len(two_sided)}/{len(pkg_orients)} two-sided, e.g. "
       f"{two_sided[:2] if two_sided else pkg_orients[:2]}")
    ck("both venue classes present",
       {T.VENUE_D2C, T.VENUE_D2D} <= set(pipe.calls.called["venue_class"]),
       str(pipe.calls.called["venue_class"].value_counts().to_dict()))
    ck("KRD non-empty", len(pipe.krd.krd) > 0, f"{len(pipe.krd.krd)} rows")
    # `max()` of an empty groupby is NaN and `int(NaN)` raises, which would turn
    # the empty-frame failure mode this whole self-test exists to catch into an
    # unrelated traceback. Guarded so it reports as a FAIL instead.
    per_unit = (int(pipe.krd.krd.groupby("unit_key").size().max())
                if len(pipe.krd.krd) else 0)
    ck("KRD covers 1..28 pillars per unit",
       0 < per_unit <= len(krd_mod.PILLARS),
       f"max {per_unit} of {len(krd_mod.PILLARS)}")
    ck("ladder rows non-empty", len(pipe.ladder.unit_rows) > 0,
       f"{len(pipe.ladder.unit_rows)} rows")
    ck("ladder aggregate non-empty", len(pipe.ladder.ladder) > 0,
       f"{len(pipe.ladder.ladder)} cells")
    ck("daily non-empty", len(pipe.daily) > 0, f"{len(pipe.daily)} cells")
    ck("daily spans the three availability dates",
       pipe.daily["visibility_date"].nunique() >= 3,
       str(sorted(map(str, pipe.daily['visibility_date'].unique()))[:6]))
    ck("daily buckets are TENOR10",
       set(pipe.daily["bucket_key"]) <= set(ind.TENOR_BUCKETS),
       str(sorted(set(pipe.daily["bucket_key"]))))
    ck("weight is 2p-1 everywhere",
       float((2 * pipe.ladder.unit_rows["p"]
              - 1 - pipe.ladder.unit_rows["signed_weight"]).abs().max()) < 1e-12)
    ck("delta_dv01 == signed_weight * dv01_if_received",
       float((pipe.ladder.unit_rows["delta_dv01"]
              - pipe.ladder.unit_rows["signed_weight"]
              * pipe.ladder.unit_rows["dv01_if_received"]).abs().max()) < 1e-9)
    ck("ladder DV01 reconciles to the daily roll-up",
       abs(float(pipe.ladder.unit_rows["delta_dv01"].sum())
           - float(pipe.daily["delta_dv01"].sum())) < 1e-6,
       f"{pipe.ladder.unit_rows['delta_dv01'].sum():,.2f} vs "
       f"{pipe.daily['delta_dv01'].sum():,.2f}")
    ck("both series present in the ladder",
       {ladder_mod.SERIES_FLOW, ladder_mod.SERIES_LIFECYCLE}
       <= set(pipe.ladder.unit_rows["series"])
       if cfg.include_lifecycle else True,
       str(pipe.ladder.unit_rows["series"].value_counts().to_dict()))
    ck("the ladder remainder is fully attributed",
       len(pipe.ladder.remainder) == len(pipe.ladder.excluded)
       and pipe.ladder.remainder["why"].notna().all(),
       str(pipe.ladder.remainder["why"].value_counts().to_dict()))
    ck("every priced unit is either a ladder row or a remainder row",
       len(set(pipe.ladder.unit_rows["unit_key"])
           | set(pipe.ladder.remainder["unit_key"]))
       == len(pipe.pricing.units),
       f"{len(set(pipe.ladder.unit_rows['unit_key']))} + "
       f"{len(pipe.ladder.remainder)} vs {len(pipe.pricing.units)}")

    # --- known-answer tie-out against s2_positioning's own build ----------
    s2_dir = pathlib.Path(r"D:\dd_signals_cache\s2_pos\units")
    have = [d for d in days if (s2_dir / f"{d}.parquet").exists()]
    if have:
        s2 = pd.concat([pd.read_parquet(s2_dir / f"{d}.parquet") for d in have],
                       ignore_index=True)
        j = pipe.pricing.units.merge(s2, on="unit_key", suffixes=("_me", "_s2"))
        ck("s2 tie-out: the same units price the same way",
           bool((j["failure_me"].isna() == j["failure_s2"].isna()).all()),
           f"{len(j)} shared units")
        same = j[(j["rule_me"] == j["rule_s2"]) & j["failure_me"].isna()]
        worst = 0.0
        for col in ("deviation_bps", "npv_pay", "structure_dv01", "gross_pv01"):
            a = pd.to_numeric(same[f"{col}_me"], errors="coerce")
            b = pd.to_numeric(same[f"{col}_s2"], errors="coerce")
            m = a.notna() & b.notna()
            if m.any():
                worst = max(worst, float((a[m] - b[m]).abs().max()))
        ck("s2 tie-out: marks are bit-identical", worst == 0.0,
           f"max |diff| over 4 columns = {worst:.3e} on {len(same)} units")
        moved = j[j["rule_me"] != j["rule_s2"]]
        ck("s2 tie-out: the PKG routing divergence is present and PKG-only",
           len(moved) > 0 and set(moved["kind_me"]) == {"PKG"}
           and set(moved["rule_s2"]) == {conv.RULE_UPFRONT}
           and set(moved["rule_me"]) == {pp.RULE_PACKAGE_PRICE},
           f"{len(moved)} units re-routed")
    else:
        print("  (s2 reference cache absent -- tie-out checks skipped)")

    # one_trade, on a package (the hardest case) and on a plain outright
    traces = {}
    for label, sel in (
            ("PKG", pipe.calls.called[
                pipe.calls.called["rule"] == pp.RULE_PACKAGE_PRICE]),
            ("RATE", pipe.calls.called[
                pipe.calls.called["rule"] == conv.RULE_RATE]),
            ("UPFRONT", pipe.calls.called[
                pipe.calls.called["rule"] == conv.RULE_UPFRONT])):
        if sel.empty:
            ck(f"one_trade[{label}] has a candidate", False)
            continue
        tr = one_trade(pipe, sel["unit_key"].iloc[0])
        traces[label] = tr
        ck(f"one_trade[{label}] reprices to the cache", tr["recheck"]["agrees"],
           str(tr["recheck"]["max_abs_mid_diff_pct"]))
        ck(f"one_trade[{label}] has a KRD vector", len(tr["krd"]["dv01_if_received"]) > 0,
           f"{len(tr['krd']['dv01_if_received'])} pillars")
        ck(f"one_trade[{label}] has per-leg received signs",
           tr["orientation"]["per_leg_received_signs"] is not None
           and len(tr["orientation"]["per_leg_received_signs"]) == tr["n_legs"])
        ck(f"one_trade[{label}] weight is 2p-1",
           abs(2 * tr["call"]["p"] - 1 - tr["call"]["signed_weight"]) < 1e-12)
        ck(f"one_trade[{label}] is reachable by trade_id and as a method",
           pipe.one_trade(tr["trade_ids"][0])["unit_key"] == tr["unit_key"])

    # ---- report ---------------------------------------------------------
    print("\n--- days -------------------------------------------------------")
    print(f"tape days used: {days}")
    print(pipe.units.by_day.to_string(index=False))

    print("\n--- rows and wall clock per stage ------------------------------")
    print(pipe.timings.to_string(index=False,
                                 float_format=lambda v: f"{v:8.2f}"))
    print(f"total {wall:.1f}s "
          f"({wall / max(len(days), 1):.1f}s per tape day)")

    print("\n--- universe accounting ----------------------------------------")
    a = pipe.units.accounting
    print(f"units {a['n_units']}, kept {a['n_kept']} "
          f"({a['unit_retention']:.2%}); DV01 kept {a['dv01_retention']:.2%}")
    print(f"recovered PKG-N {a['n_pkg_recovered']}, "
          f"PKG-4+ refused as SIGNS_AMBIGUOUS {a['n_pkg_ambiguous']}")
    print(f"venue {a['venue_counts']}")
    print(f"kind  {a['kind_counts']}")
    print(pipe.units.exclusions.head(10).to_string(
        index=False, float_format=lambda v: f"{v:,.2f}"))

    print("\n--- priced fraction by start class -----------------------------")
    print(priced_fraction(pipe.pricing).to_string(
        index=False, float_format=lambda v: f"{v:.4f}"))
    print("\nwhy the strata move -- the spot window is CALENDAR days:")
    print(spot_window_check(pipe.pricing).to_string(index=False))
    if len(pipe.pricing.failures):
        print("\npricing failures by reason:")
        print(pipe.pricing.failures.groupby(
            ["as_of_date", "failure"]).size().to_string())
        print("\nincompletely priced New York hours of the snap, per day "
              "(Citi's minute store publishes ~01:00-19:59 ET):")
        print(snap_hour_coverage(pipe.pricing).to_string(
            index=False, float_format=lambda v: f"{v:.4f}"))

    print("\n--- calls ------------------------------------------------------")
    for k, v in pipe.calls.diagnostics.items():
        print(f"  {k}: {v}")
    print(rule_mix(pipe.calls).to_string(index=False,
                                         float_format=lambda v: f"{v:.4f}"))
    print("\nrule x exclusion:")
    print(pipe.calls.exclusions.to_string(index=False))

    print("\n--- calibration ------------------------------------------------")
    print(f"mode {pipe.taus.mode}")
    print(pipe.taus.provenance.to_string(index=False))

    print("\n--- risk and ladder --------------------------------------------")
    print(f"KRD rows {len(pipe.krd.krd)}, failures {len(pipe.krd.failures)}")
    if len(pipe.krd.failures):
        print(pipe.krd.failures["failure_reason"].value_counts().to_string())
    print(f"ladder unit rows {len(pipe.ladder.unit_rows)}, "
          f"excluded {len(pipe.ladder.excluded)}, "
          f"cells {len(pipe.ladder.ladder)}")
    if len(pipe.ladder.excluded):
        print(pipe.ladder.excluded["failure_reason"].value_counts().to_string())
        print("\nthe remainder, one level finer than the ladder's vocabulary:")
        print(pipe.ladder.remainder.groupby(
            ["failure_reason", "why"], observed=True).size().to_string())
    print("\nvisibility lag (availability date minus tape date):")
    print(visibility_lag(pipe.ladder).to_string(index=False))
    print("\ndaily levels, D2C FLOW (USD per bp):")
    bl = bucket_levels(pipe.daily)
    print(bl[["visibility_date", "bucket_key", "delta_dv01", "abs_dv01",
              "n_units", "mean_abs_signed_weight"]].to_string(
                  index=False, float_format=lambda v: f"{v:,.1f}"))

    if "PKG" in traces:
        t = traces["PKG"]
        print("\n--- one_trace on a recovered PKG-N -----------------------------")
        print(f"  {t['unit_key']} {t['kind']}-{t['n_legs']} {t['rule']} "
              f"{t['venue_class']} {t['as_of_date']}")
        print(f"  snap {t['snap']['snap_instant']} on {t['snap']['curve_name']} "
              f"policy={t['snap']['snapshot_policy']} "
              f"lag={t['snap']['snapshot_lag_seconds']}s")
        print(f"  deviation {t['structure']['deviation_bps']:.4f} bp, "
              f"tieout {t['structure']['tieout_bps']:.4f}, "
              f"margin {t['structure']['margin_bps']:.4f}")
        print(f"  tau {t['tau']['tau_bps']:.4f} from {t['tau']['tau_bucket']}")
        print(f"  p {t['call']['p']:.4f} -> weight {t['call']['signed_weight']:+.4f}"
              f" -> {t['call']['dealer_side_words']}")
        print(f"  base_orientation {t['orientation']['base_orientation']} "
              f"-> received {t['orientation']['per_leg_received_signs']}")
        print(f"  KRD (top 6): "
              f"{dict(sorted(t['krd']['dv01_if_received'].items(), key=lambda kv: -abs(kv[1]))[:6])}")

    written = write_outputs(pipe)
    ck("summary frames written and non-empty",
       all(p.exists() and p.stat().st_size > 0 for p in written.values())
       and len(written) == len(OUTPUT_FRAMES),
       f"{len(written)} files under {pipe.cfg.out_dir / pipe.cfg.window}")

    print("\n--- checks -----------------------------------------------------")
    bad = [c for c in checks if not c[1]]
    for name, okv, detail in checks:
        print(f"  [{'ok ' if okv else 'FAIL'}] {name}"
              + (f"  ({detail})" if detail else ""))
    print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed")
    if bad:
        print("FAILED: " + "; ".join(n for n, _, _ in bad))
        return 1
    print("SELF-TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
