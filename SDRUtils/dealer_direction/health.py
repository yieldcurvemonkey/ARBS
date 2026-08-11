"""Monitoring, built now rather than retrofitted.

The whole ladder is garbage if the mid drifts off venue, and **that failure is
silent**. It is not hypothetical and it is not small: F-20 measured the
predecessor's barchart mid biased ~0.5 bp high with ~7x the dispersion of the
citi minute curve, which pushed 78% of its ``RATE_VS_MID`` calls to one side
and 21.7% of prints "above mid" where the unbiased curve gives 55.5%. Every
downstream conclusion drawn from that table -- including a "no signal" verdict
on the dealer ladder programme -- rests on labels manufactured by a
half-basis-point curve error. Nothing in that pipeline reported a problem.

So: **degradation here is a reason to flatten, not a curiosity.** A monitor
whose breach is filed for later reading is a monitor that would have let F-20
run for six months, which is what happened. Every metric carries a
:class:`Threshold` with the measurement its number came from and the action its
breach implies, in code rather than in a document, because the number and the
reason go stale together.

THE ONE THAT NEEDS DESIGNING
----------------------------
Four of the six metrics are counts of a known pathology. The fifth
(:func:`d2d_recycling_kappa`) is the only one that reads *classifier accuracy*,
and the naive version of it fails in the specific way that matters: a mid bias
lands identically on the D2C and D2D populations, so a matched-sign hit rate
**rises** as the mid degrades. Its docstring is where that is dealt with.
"""
from __future__ import annotations

import dataclasses
import re

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import snapshot

OK = "OK"
WARN = "WARN"
ALARM = "ALARM"
NO_DATA = "NO_DATA"

_RANK = {NO_DATA: 0, OK: 1, WARN: 2, ALARM: 3}

#: A leg is "spot" if it starts within this many calendar days of the trade
#: date. Wide enough for USD T+2 plus a holiday weekend, narrow enough that a
#: genuine short forward start does not hide inside it.
SPOT_WINDOW_DAYS = 5

#: Dead zone: above this share of units, the ladder is mostly zeros whatever
#: the reference says.
DEAD_ZONE_ABS_ALARM = 0.60

#: Imputed-notional limits, on the DV01 share rather than the leg count.
IMPUTED_DV01_WARN = 0.20
IMPUTED_DV01_ALARM = 0.30


# --------------------------------------------------------------------------
# the reporting objects
# --------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Threshold:
    """A limit, the measurement it came from, and what to do when it fires.

    ``rationale`` is not documentation. A threshold with no stated derivation
    cannot be argued with when it fires at 03:00, so it gets relaxed -- and a
    relaxed threshold is indistinguishable from no threshold.
    """

    name: str
    direction: str                 # above | below | outside
    warn: object
    alarm: object
    rationale: str
    action: str

    def evaluate(self, value) -> str:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return NO_DATA
        if self.direction == "above":
            if self.alarm is not None and value >= self.alarm:
                return ALARM
            if self.warn is not None and value >= self.warn:
                return WARN
            return OK
        if self.direction == "below":
            if self.alarm is not None and value <= self.alarm:
                return ALARM
            if self.warn is not None and value <= self.warn:
                return WARN
            return OK
        if self.direction == "outside":
            if self.alarm is not None and not (self.alarm[0] <= value <= self.alarm[1]):
                return ALARM
            if self.warn is not None and not (self.warn[0] <= value <= self.warn[1]):
                return WARN
            return OK
        raise ValueError(f"unknown threshold direction {self.direction!r}")


@dataclasses.dataclass(frozen=True)
class Metric:
    name: str
    value: object
    n: int
    threshold: Threshold
    status: str
    detail: dict = dataclasses.field(default_factory=dict)


def _worse(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b


def _require(frame, columns, who: str) -> None:
    """A monitor with a silently missing input column is worse than no monitor.

    ``legs.get(col, default)`` is the convenient spelling and it is the wrong
    one here: a typo'd or renamed column then reports a clean OK forever.
    """
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"{who} needs column(s) {missing}; it cannot report "
                         "OK on data it was not given")


# --------------------------------------------------------------------------
# 1. the D2D recycling monitor
# --------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class KappaResult:
    kappa: float
    hit_rate: float
    chance_rate: float
    n_pairs: int
    n_dropped_zero: int
    degenerate: bool
    placebo_kappa_p95: float | None
    bootstrap_ci: tuple
    block_length: int
    horizon_days: int
    expected_alignment: int
    status: str
    threshold: Threshold
    rank_corr: float | None = None

    def as_metric(self) -> Metric:
        return Metric(
            name="d2d_recycling_kappa", value=self.kappa, n=self.n_pairs,
            threshold=self.threshold, status=self.status,
            detail={
                "hit_rate": self.hit_rate, "chance_rate": self.chance_rate,
                "placebo_kappa_p95": self.placebo_kappa_p95,
                "bootstrap_ci": self.bootstrap_ci, "degenerate": self.degenerate,
                "rank_corr": self.rank_corr,
                "n_dropped_zero": self.n_dropped_zero,
            },
        )


def d2d_recycling_kappa(d2c, d2d, *, horizon_days: int = 1,
                        step_days: int | None = None,
                        expected_alignment: int = 1,
                        placebo_shift_days: int = 7,
                        max_placebo: int = 200,
                        n_bootstrap: int = 200,
                        block_length: int | None = None,
                        seed: int = 0,
                        min_pairs: int = 30) -> KappaResult:
    """Does the inferred customer flow predict the inter-dealer flow that follows?

    **The economics.** A customer pays fixed; the dealer receives fixed and is
    long duration; to shed it the dealer must pay fixed in the inter-dealer
    market, and it does so by *crossing the spread*. Our price-vs-mid rule
    identifies the party that overpaid -- the taker -- and calls it "the
    customer". So in a D2D print the inferred "dealer" is the **maker**, and the
    shedding dealer is the taker. The maker ends up on the same side the
    original dealer was on, which is why recycled risk carries the **same** sign
    as the customer flow that created it, and why ``expected_alignment`` is
    ``+1``. If the alignment turns out to be stably negative, the monitor is
    still working and this paragraph is wrong: pass ``-1``, and none of the
    alarm logic changes.

    **Why not a hit rate.** A hit rate is the statistic this test obviously
    wants and it is the wrong one, because it is maximised by the failure being
    monitored. A mid biased off venue pushes *both* populations to the same
    side -- F-20's 78% PAID is a curve property, not a flow property -- so
    matched signs become common for a reason that has nothing to do with the
    classifier working. Taken to the limit, a mid so bad that every print is
    labelled the same way scores a hit rate of 1.000. Cohen's kappa subtracts
    exactly that: it scores agreement against what the two **marginals** would
    produce on their own, so the degenerate case scores 0 and raises the alarm
    rather than clearing it. This is pinned by a known-answer test before the
    statistic is used on real flow.

    **Why a placebo rather than a p-value.** Flow is autocorrelated, so pairs
    are not independent and a nominal standard error understates the spread by
    an unknown factor. The reference distribution is therefore generated by
    circularly shifting the D2D sign series by at least ``placebo_shift_days``:
    that preserves each series' marginal *and* its own serial correlation, and
    destroys only the pairing -- the same control shape as F-15's seven-day
    curve placebo, which separated a real signal from a 48.8x wider null. The
    reported interval is a **moving-block** bootstrap for the same reason.

    **Assumptions, all of which can fail.** (a) The taker/maker reading above.
    (b) Risk recycles inside ``horizon_days``; too short a horizon reads as no
    skill. (c) Errors are independent across venue classes -- this is the one
    that fails when the mid is off, and kappa plus the placebo are what stand in
    for it. (d) D2D venue classification is right; F-7's whitelist is a platform
    heuristic, and ``VENUE_UNKNOWN`` is deliberately not folded in here.

    **This is a necessary condition, not a certificate.** Passing does not make
    the ladder right. Failing means the direction calls have stopped tracking
    anything the inter-dealer market does, and the response is to **flatten** --
    stop trading the signal -- not to file the reading for later.

    ``horizon_days`` and ``step_days`` are calendar days; the two series are
    reindexed onto a complete daily calendar first, so a weekend contributes
    zero rather than shifting the horizon.
    """
    x, y = _align_daily(d2c, d2d)
    n = len(x)
    step = int(step_days) if step_days else int(horizon_days)
    block_length = int(block_length) if block_length else max(int(horizon_days), 5)

    # forward window: the D2D flow strictly AFTER each date, so the pairing can
    # never read a print against itself
    # k is capped at n: a horizon longer than the history has no forward window
    # at all, and the uncapped slice pair broadcasts (n-k,) against () instead
    # of reporting NO_DATA
    fwd = np.zeros(n, dtype="float64")
    for k in range(1, min(int(horizon_days), n) + 1):
        fwd[: n - k] += y[k:]
    sy = np.sign(fwd) * int(expected_alignment)
    sx = np.sign(x)

    take = np.arange(0, n, max(1, step))
    sx, sy = sx[take], sy[take]
    keep = (sx != 0) & (sy != 0)
    n_dropped = int((~keep).sum())
    sx, sy = sx[keep], sy[keep]

    kappa, hit, chance, degenerate = _kappa(sx, sy)
    placebo_p95 = _placebo_p95(sx, sy, placebo_shift_days, max_placebo)
    ci = _block_bootstrap_ci(sx, sy, block_length, n_bootstrap, seed)

    threshold = Threshold(
        name="d2d_recycling_kappa", direction="below",
        warn=0.10, alarm=placebo_p95,
        rationale=(
            "Kappa scores agreement net of the two marginals, so the F-20 "
            "failure mode -- a mid biased ~0.5bp off venue pushing 78% of both "
            "populations to one side -- scores 0 here where a raw hit rate "
            "scores 1.00. The alarm level is not a chosen number: it is the "
            "95th percentile of a placebo built by circularly shifting the D2D "
            "signs by >= {}d, which keeps both marginals and both "
            "autocorrelations and destroys only the pairing. At or below that "
            "line the classifier is not distinguishable from no link. The 0.10 "
            "warn floor is a separate, weaker check for a placebo that is "
            "itself degenerate.".format(placebo_shift_days)
        ),
        action=("FLATTEN. Stop trading the ladder and re-run the curve bias "
                "control (F-15: printed-minus-mid median and its bootstrap CI) "
                "before restarting. Do not file this and continue."),
    )
    if len(sx) < min_pairs:
        status = NO_DATA
    elif degenerate:
        status = ALARM
    else:
        status = threshold.evaluate(kappa)

    return KappaResult(
        kappa=kappa, hit_rate=hit, chance_rate=chance, n_pairs=int(len(sx)),
        n_dropped_zero=n_dropped, degenerate=degenerate,
        placebo_kappa_p95=placebo_p95, bootstrap_ci=ci,
        block_length=block_length, horizon_days=int(horizon_days),
        expected_alignment=int(expected_alignment), status=status,
        threshold=threshold, rank_corr=_rank_corr(x, fwd * int(expected_alignment)),
    )


#: The rolling frame's shape, defined once. Two paths return an empty version
#: of it -- no data at all, and a history shorter than one window -- and they
#: used to disagree: the second returned a one-column frame, so a monitor loop
#: starting on a short history died on ``out["kappa"]`` instead of reading
#: NO_DATA off an empty series.
ROLLING_KAPPA_COLUMNS = ["window_end", "kappa", "hit_rate",
                         "placebo_kappa_p95", "n_pairs", "reference_kappa",
                         "status"]


def rolling_recycling_kappa(d2c, d2d, *, window_days: int = 90,
                            step_days: int = 5, degradation_ratio: float = 0.5,
                            min_pairs: int = 30, **kwargs) -> pd.DataFrame:
    """:func:`d2d_recycling_kappa` over a rolling window, so **decay is visible**.

    A single number over the whole sample cannot say the thing this monitor
    exists to say. F-20's mid bias was not present on day one and absent on day
    two; a curve source degrades, and the question is always "is it worse than
    it was", which needs a series. Ninety days is the default window because it
    is roughly a quarter and because a ~90-day reach-back holds 90% of the
    flippable lineage population (LEDGER F-18: 90.7% is the figure for 63 days,
    95.6% for 252) -- long enough for a stable kappa, short enough that a month
    of degradation is visible in it rather than averaged away.

    Two ways a window fails, and both mean the same thing:

    * ``kappa`` falls to the window's own placebo band -- no link at all;
    * ``kappa`` falls below ``degradation_ratio`` of the trailing median of the
      windows before it. **This one is the point.** An absolute level cannot be
      set in advance for an economic prediction across venue classes, but a
      halving against a reference this system established itself can.

    Either is an ALARM, and the response is the same: **flatten**. The reference
    is a trailing (expanding) median of prior windows only, never including the
    window being judged, so a slow decay cannot drag its own benchmark down with
    it.
    """
    if "n_bootstrap" in kwargs:
        raise TypeError(
            "rolling_recycling_kappa does not bootstrap per window -- one CI "
            "per step over a whole sample is the cost this function exists to "
            "avoid. Read the interval off d2d_recycling_kappa on the window "
            "you care about."
        )
    x, _y = _align_daily(d2c, d2d)
    if len(x) == 0:
        return pd.DataFrame(columns=ROLLING_KAPPA_COLUMNS)
    a = pd.Series(d2c).copy()
    a.index = pd.to_datetime(pd.Index(a.index))
    b = pd.Series(d2d).copy()
    b.index = pd.to_datetime(pd.Index(b.index))
    lo = min(a.index.min(), b.index.min())
    hi = max(a.index.max(), b.index.max())

    rows = []
    end = lo + pd.Timedelta(days=window_days)
    while end <= hi:
        start = end - pd.Timedelta(days=window_days)
        res = d2d_recycling_kappa(
            a[(a.index > start) & (a.index <= end)],
            b[(b.index > start) & (b.index <= end)],
            n_bootstrap=0, min_pairs=min_pairs, **kwargs,
        )
        rows.append({"window_end": end.date(), "kappa": res.kappa,
                     "hit_rate": res.hit_rate,
                     "placebo_kappa_p95": res.placebo_kappa_p95,
                     "n_pairs": res.n_pairs, "status": res.status})
        end += pd.Timedelta(days=step_days)

    out = pd.DataFrame(rows)
    if out.empty:
        # a history shorter than one window closes none, and it must return the
        # same shape the no-data path above does
        return pd.DataFrame(columns=ROLLING_KAPPA_COLUMNS)
    # trailing median of EARLIER windows only -- a benchmark that includes the
    # window it judges cannot detect a slow decay
    out["reference_kappa"] = out["kappa"].shift(1).expanding().median()
    degraded = (out["reference_kappa"].notna()
                & (out["reference_kappa"] > 0)
                & (out["kappa"] < degradation_ratio * out["reference_kappa"]))
    out.loc[degraded, "status"] = ALARM
    return out[ROLLING_KAPPA_COLUMNS]


def _align_daily(a, b):
    """Both series on one complete calendar-day axis, missing days as zero flow."""
    a = pd.Series(a).copy()
    b = pd.Series(b).copy()
    a.index = pd.to_datetime(pd.Index(a.index))
    b.index = pd.to_datetime(pd.Index(b.index))
    if a.empty or b.empty:
        return np.zeros(0), np.zeros(0)
    lo = min(a.index.min(), b.index.min())
    hi = max(a.index.max(), b.index.max())
    axis = pd.date_range(lo, hi, freq="D")
    return (a.groupby(level=0).sum().reindex(axis).fillna(0.0).to_numpy(dtype="float64"),
            b.groupby(level=0).sum().reindex(axis).fillna(0.0).to_numpy(dtype="float64"))


def _kappa(sx, sy):
    """Cohen's kappa on two sign vectors, plus the raw and chance rates.

    **A degenerate marginal is ONE series entirely one sign, and it does not
    need the chance rate to reach 1.** ``chance = px*py + (1-px)(1-py)``, so
    ``px = 1`` against a balanced ``py = 0.5`` gives ``chance = 0.5``, not 1 --
    and a flag conditioned on ``chance == 1`` therefore only ever fires when
    *both* series are one-sided the *same* way. That was the bug: the F-20
    state where the mid has collapsed one population is exactly the
    single-degenerate case, and it was being scored as an ordinary reading.

    Kappa is nevertheless **exactly 0** whenever either marginal is degenerate
    (with ``sx = +1`` throughout, ``hit = py`` and ``chance = py``), so the
    arithmetic never needed protecting -- the *flag* did, because
    :func:`d2d_recycling_kappa` promotes it straight to ALARM and 0.0 alone
    only clears the 0.10 warn floor when the placebo is unavailable. A series
    that says the same thing about every print carries no information about any
    of them: 0.0 with the flag, never 1.0 and never NaN.
    """
    n = len(sx)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), False
    hit = float((sx == sy).mean())
    px = float((sx > 0).mean())
    py = float((sy > 0).mean())
    chance = px * py + (1.0 - px) * (1.0 - py)
    degenerate = px in (0.0, 1.0) or py in (0.0, 1.0)
    if chance >= 1.0 - 1e-12:
        return 0.0, hit, chance, True
    return float((hit - chance) / (1.0 - chance)), hit, chance, degenerate


def _placebo_p95(sx, sy, shift_days: int, max_placebo: int):
    """Null kappas from circular shifts of the D2D signs.

    Shifting the *sign* vector rather than re-running the pairing keeps each
    series' marginal and its own serial dependence intact while breaking the
    correspondence, which is the property a permutation test would not have.
    """
    n = len(sx)
    if n < 2 * shift_days + 2:
        return None
    shifts = np.arange(shift_days, n - shift_days)
    if len(shifts) > max_placebo:
        shifts = shifts[np.linspace(0, len(shifts) - 1, max_placebo).astype(int)]
    vals = [_kappa(sx, np.roll(sy, int(k)))[0] for k in shifts]
    vals = [v for v in vals if not np.isnan(v)]
    return None if not vals else float(np.percentile(vals, 95))


def _block_bootstrap_ci(sx, sy, block_length: int, n_bootstrap: int, seed: int):
    """Moving-block bootstrap CI. An iid bootstrap here understates the spread,
    because consecutive days of flow are not independent draws."""
    n = len(sx)
    if n_bootstrap <= 0 or n < block_length + 1:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_length))
    starts_max = n - block_length + 1
    out = np.empty(n_bootstrap, dtype="float64")
    offsets = np.arange(block_length)
    for i in range(n_bootstrap):
        starts = rng.integers(0, starts_max, size=n_blocks)
        idx = (starts[:, None] + offsets[None, :]).ravel()[:n]
        out[i] = _kappa(sx[idx], sy[idx])[0]
    out = out[~np.isnan(out)]
    if out.size == 0:
        return (float("nan"), float("nan"))
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


def _rank_corr(x, y):
    """Spearman on the magnitudes, as a secondary read. Not thresholded --
    kappa is the sign test and this only says whether size travels with it."""
    if len(x) < 3:
        return None
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


# --------------------------------------------------------------------------
# 2. dead zone
# --------------------------------------------------------------------------

def dead_zone_fraction(calls, *, reference: float | None = None) -> Metric:
    """Share of units the mid cannot separate -- and the alarm is TWO-SIDED.

    The obvious reading is that a growing dead zone is bad. It is not reliably
    either. F-20 measured the two curves side by side on the same prints: 40.5%
    of on-market SOFR outrights land within +-0.1 bp of the citi mid, against
    **5.43%** on the barchart mid. The *worse* curve has the smaller dead zone,
    because a mid drifting off venue pushes prints away from it and manufactures
    confident deviations out of its own error.

    So a **fall** in near-mid density is the signature this monitor is looking
    for, and a one-sided threshold would miss it entirely. The upper absolute
    limit is still enforced -- past ``DEAD_ZONE_ABS_ALARM`` the ladder is mostly
    zeros however good the mid is -- but it is the weaker of the two tests.
    """
    calls = list(calls)
    n = len(calls)
    value = (float(np.mean([bool(getattr(c, "in_dead_zone", False)) for c in calls]))
             if n else float("nan"))

    if reference is None:
        threshold = Threshold(
            name="dead_zone_fraction", direction="above",
            warn=0.45, alarm=DEAD_ZONE_ABS_ALARM,
            rationale=(
                "With no trailing reference only the absolute limit can fire, "
                "and it is the weak half of the test: past 60% of units in the "
                "dead zone the ladder is mostly zeros whatever the cause. The "
                "informative test needs a reference -- F-20 measured 40.5% of "
                "on-market SOFR outrights within +-0.1bp of the citi mid "
                "against 5.43% on the biased barchart mid, so a COLLAPSE in "
                "this fraction is the mid drifting off venue."),
            action=("Supply a trailing reference so the two-sided band applies; "
                    "on an absolute breach, check tau calibration before the curve."),
        )
        status = threshold.evaluate(value)
    else:
        threshold = Threshold(
            name="dead_zone_fraction", direction="outside",
            warn=(0.5 * reference, 2.0 * reference),
            alarm=(0.25 * reference, 4.0 * reference),
            rationale=(
                "Two-sided against the trailing reference of {:.3f}. A fall is "
                "the mid drifting off venue: the barchart mid put 5.43% of "
                "prints within +-0.1bp where the citi mid puts 40.5% (F-20), a "
                "7.5x collapse, so the 4x band catches that failure before it "
                "is complete. A rise is tau widening, i.e. the mixture fit "
                "reporting that the two components stopped separating."
                .format(reference)),
            action=("FLATTEN on a fall: re-run the F-15 bias control (printed "
                    "minus mid, median plus bootstrap CI, plus the 7-day "
                    "placebo) before trusting another day's ladder. On a rise, "
                    "re-fit tau and check for a leptokurtic bucket."),
        )
        status = threshold.evaluate(value)
        if not np.isnan(value) and value > DEAD_ZONE_ABS_ALARM:
            status = ALARM

    return Metric(name="dead_zone_fraction", value=value, n=n,
                  threshold=threshold, status=status,
                  detail={"reference": reference})


# --------------------------------------------------------------------------
# 3. imputed notional
# --------------------------------------------------------------------------

def imputed_notional_fraction(prov, *, weights=None) -> Metric:
    """Share of units whose notional is a cap rather than a number.

    Counted **and** weighted, because they are different numbers and the
    weighted one is the one that matters: F-7 measured 3.01% of flow legs capped
    but 15.4% of the DV01 imputed (10.6-16.0% across six threshold choices), and
    a model-free cross-check brackets it at 12.8-13.9%. Weighting by DV01 is
    also what would catch a cap-schedule break, since the caps are a function of
    tenor and every band moved by 1.55-3.57x when the schedule was re-set on
    2024-10-07 -- to the day, simultaneously across all nine bands (F-7's table:
    the 6m-1y band moved least, $1.1bn to $1.7bn, and 46d-3m most, $2.1bn to
    $7.5bn).
    """
    prov = pd.DataFrame(prov)
    n = len(prov)
    if n == 0:
        return Metric(name="imputed_notional_fraction", value=float("nan"), n=0,
                      threshold=_imputed_threshold(), status=NO_DATA,
                      detail={"dv01_share": None})
    # the flag column named rather than `.get`-ed: renamed, this metric reports
    # a clean 0.00 forever, and with weights it raises an IndexError on a
    # zero-length boolean mask instead
    _require(prov, ["notional_imputed"], "imputed_notional_fraction")
    flags = prov["notional_imputed"].fillna(False).astype(bool)
    value = float(flags.mean())

    dv01_share = None
    if weights is not None:
        _require(prov, ["unit_key"], "imputed_notional_fraction(weights=...)")
        w = prov["unit_key"].map(pd.Series(weights, dtype="float64")).abs()
        total = float(w.sum())
        if total > 0:
            dv01_share = float(w[flags.to_numpy()].sum() / total)

    threshold = _imputed_threshold()
    status = threshold.evaluate(value)
    if dv01_share is not None:
        if dv01_share >= IMPUTED_DV01_ALARM:
            status = _worse(status, ALARM)
        elif dv01_share >= IMPUTED_DV01_WARN:
            status = _worse(status, WARN)

    return Metric(name="imputed_notional_fraction", value=value, n=n,
                  threshold=threshold, status=status,
                  detail={"dv01_share": dv01_share})


def _imputed_threshold() -> Threshold:
    return Threshold(
        name="imputed_notional_fraction", direction="above",
        warn=0.06, alarm=0.10,
        rationale=(
            "F-7 measured the base rate at 3.01% of flow legs, stable across "
            "the sample and not venue-selective (D2C 3.00% / D2D 3.11%). Twice "
            "that is a regime change, three times is a broken cap schedule -- "
            "which is a live risk, not a hypothetical: the whole nine-band "
            "schedule was re-set on 2024-10-07 with zero overlap, and an "
            "unrecognised third vintage would surface here first. The DV01 "
            "share is thresholded separately at {:.0%}/{:.0%}, above the top of "
            "the measured 10.6-16.0% sensitivity range."
            .format(IMPUTED_DV01_WARN, IMPUTED_DV01_ALARM)),
        action=("Re-derive the cap schedule from the capped prints themselves "
                "(their notional IS the cap) before trusting the imputation; a "
                "stale schedule silently under-imputes the whole long end."),
    )


# --------------------------------------------------------------------------
# 4. the overnight hole
# --------------------------------------------------------------------------

_MAX_LAG_RE = re.compile(r"max_lag=(?P<v>unbounded|[0-9.]+)s?")
_ALLOW_FUTURE_RE = re.compile(r"allow_future=(?P<v>\w+)")


def is_overnight_hole(policy) -> bool:
    """Was this row answered by something other than the strict in-session branch?

    **Read the policy, not the served timestamp.** The snapshot that answers a
    00:30 ET request is by construction *in* session -- it is the last one Citi
    published before the feed stopped at 23:00 -- so asking whether the served
    stamp is in session answers a different question and always says yes. The
    policy string is the record of which branch fired, which is the question.

    **The test is affirmative on two fields, not one.** Reading ``max_lag``
    alone -- the obvious spelling -- lets ``allow_future=True`` through as long
    as it carries a bound, and a 60-second window *centred* on the print is not
    the 60-second window *before* it. That is the circularity this whole
    exercise exists to prevent, and it is the property behind the 1.09% of legs
    the shipped nearest-either-direction default serves from the future. So the
    row is the strict branch only if the policy states ``allow_future=False``
    **and** a parseable bound no looser than ``IN_SESSION_MAX_LAG``.

    ``method`` is deliberately **not** part of the test, and that is a measured
    call rather than an omission: ``select_snapshot`` picks the globally
    nearest stamp under ``method=nearest`` and then *rejects* it outright when
    it is from the future and ``allow_future=False`` -- it does not fall back
    to the nearest backward stamp. So a row that was actually **served** under
    ``nearest`` with no-future and a 60s bound came from a backward stamp
    within the bound, which is the strict outcome; flagging it here would put a
    fresh row in the stale population and take it out of the
    ``in_session_lag_over_policy`` check. Verified directly against
    ``select_snapshot`` on a two-stamp window (30s before / 5s after the
    request): ``asof`` serves the backward stamp, ``nearest`` with
    ``allow_future=False`` returns ``None``.

    An unparseable or unbounded policy counts as the hole: it is not the strict
    in-session branch, and the legacy nearest-either-way rule is worse than the
    2h reach-back, not better.

    An **absent** policy raises instead. ``provenance.build`` writes
    ``snapshot_policy=""`` for a unit that never priced, and answering "hole"
    for those would silently re-label the entire pricing-failure population as
    a curve-staleness problem -- inflating this metric by exactly the number of
    rows that have nothing to do with it. Callers filter to the served
    population first; :func:`served_mask` is that filter.
    """
    if policy is None or (isinstance(policy, float) and np.isnan(policy)) \
            or not str(policy).strip():
        raise ValueError(
            "no snapshot policy recorded for this row, so it was never served a "
            "curve at all; filter to the served population (health.served_mask) "
            "before asking which branch answered it"
        )
    text = str(policy)
    future = _ALLOW_FUTURE_RE.search(text)
    if future is None or future.group("v").lower() != "false":
        return True
    m = _MAX_LAG_RE.search(text)
    if m is None or m.group("v") == "unbounded":
        return True
    return float(m.group("v")) > snapshot.IN_SESSION_MAX_LAG.total_seconds()


def served_mask(prov) -> pd.Series:
    """Rows that were actually answered by the snapshot store.

    A provenance frame covers the whole population by design -- that is what
    makes the coverage table a partition -- so it contains units that never
    reached a curve. Every staleness statistic here is conditional on having
    been served, and mixing the two turns a pricing failure into a curve
    complaint.

    **The criterion is the recorded policy, not ``failure_reason``.** They are
    different questions. ``EXCL_NO_CURVE`` and ``EXCL_PRICING_ERROR`` rows carry
    no policy and drop out on the policy test alone; but a ``PKG-N`` excluded as
    ``UNORIENTABLE`` was priced perfectly well and its realised lag is a real
    observation of how the curve behaved. Gating on the exclusion instead would
    throw those away and shrink the denominator for a reason that has nothing to
    do with the curve.
    """
    prov = pd.DataFrame(prov)
    if "snapshot_policy" not in prov.columns:
        return pd.Series(False, index=prov.index)
    pol = prov["snapshot_policy"]
    return pol.notna() & pol.astype(str).str.strip().ne("")


def _hole_mask(prov, served) -> pd.Series:
    hole = pd.Series(False, index=prov.index)
    if served.any():
        hole.loc[served] = prov.loc[served, "snapshot_policy"].map(is_overnight_hole)
    return hole


def overnight_hole_fraction(prov, *, weights=None) -> Metric:
    """Share of legs priced off a curve from Citi's overnight publication hole.

    Citi publishes nothing between 23:00 and 00:59 ET, so a print in that window
    is answered by a bounded 2h reach-back rather than by the minute it asked
    for. That is the right trade -- the alternative is losing every 00:xx print
    permanently, and a stale curve is at least not circular -- but it is a
    materially different mid, and the share of the ladder resting on it is not
    something to discover afterwards.
    """
    prov = pd.DataFrame(prov)
    served = served_mask(prov)
    n = int(served.sum())
    if n == 0:
        return Metric(name="overnight_hole_fraction", value=float("nan"), n=0,
                      threshold=_overnight_threshold(), status=NO_DATA,
                      detail={"n_unserved": int(len(prov))})

    # conditional on having been served: a unit that never reached a curve is a
    # pricing failure, and counting it here would re-label the whole failure
    # population as a staleness problem
    prov = prov[served]
    hole = _hole_mask(prov, pd.Series(True, index=prov.index)).to_numpy()
    value = float(hole.mean())

    detail: dict = {"n_hole": int(hole.sum()),
                    "n_unserved": int((~served).sum())}
    if "snapshot_lag_seconds" in prov.columns and hole.any():
        lags = pd.to_numeric(prov.loc[hole, "snapshot_lag_seconds"], errors="coerce").dropna()
        if len(lags):
            detail["hole_lag_p50"] = float(lags.quantile(0.50))
            detail["hole_lag_p90"] = float(lags.quantile(0.90))
            detail["hole_lag_max"] = float(lags.max())
    if weights is not None and "unit_key" in prov.columns:
        w = prov["unit_key"].map(pd.Series(weights, dtype="float64")).abs()
        total = float(w.sum())
        if total > 0:
            detail["dv01_share"] = float(w[hole].sum() / total)

    threshold = _overnight_threshold()
    return Metric(name="overnight_hole_fraction", value=value, n=n,
                  threshold=threshold, status=threshold.evaluate(value),
                  detail=detail)


def _overnight_threshold() -> Threshold:
    return Threshold(
        name="overnight_hole_fraction", direction="above", warn=0.02, alarm=0.05,
        rationale=(
            "The 00:xx ET hour is one of roughly twenty-two publishing hours "
            "and carries far less than its proportional share of USD swap "
            "prints, so a few percent is already anomalous. At 5% the ladder's "
            "overnight tail rests on curves up to two hours stale -- priced at "
            "0.24-0.29bp median error and <=1.43bp max, against prints that "
            "land one to two bp from mid -- and a jump means either the session "
            "model broke (161 truncated-end SOFR days and 141 Fed Funds days "
            "exist in the minute store, and the night after one is when the 2h "
            "bound stops a 4.5h reach-back) or the pricing clock is landing "
            "rows in the hole that should not be there."),
        action=("Check the session model against citi_session.publishes for the "
                "dates involved before using the day; exclude the hole "
                "population and re-read the ladder to size the damage."),
    )


# --------------------------------------------------------------------------
# 5. the two lag distributions
# --------------------------------------------------------------------------

def snapshot_lag_distribution(prov) -> pd.DataFrame:
    """Realised curve staleness, split by which snapshot branch answered.

    Split, not pooled: the two populations are governed by different bounds (60
    seconds against two hours), so a pooled quantile is a mixture whose shape is
    driven by the mixing weight rather than by either bound.
    """
    prov = pd.DataFrame(prov)
    cols = ["population", "n", "p50", "p90", "p99", "max", "n_negative"]
    if prov.empty or "snapshot_lag_seconds" not in prov.columns:
        return pd.DataFrame(columns=cols)
    served = served_mask(prov)
    hole = _hole_mask(prov, served)
    rows = []
    # UNSERVED is a row rather than an omission: a population that appears
    # nowhere is how a pricing failure gets read as a clean day
    for label, mask in (("IN_SESSION", (served & ~hole).to_numpy()),
                        ("OVERNIGHT_HOLE", (served & hole).to_numpy()),
                        ("UNSERVED", (~served).to_numpy())):
        lags = pd.to_numeric(prov.loc[mask, "snapshot_lag_seconds"],
                             errors="coerce").dropna()
        rows.append({
            "population": label, "n": int(mask.sum()),
            "p50": float(lags.quantile(0.50)) if len(lags) else float("nan"),
            "p90": float(lags.quantile(0.90)) if len(lags) else float("nan"),
            "p99": float(lags.quantile(0.99)) if len(lags) else float("nan"),
            "max": float(lags.max()) if len(lags) else float("nan"),
            "n_negative": int((lags < 0).sum()),
        })
    return pd.DataFrame(rows, columns=cols)


def snapshot_lag_metrics(prov) -> list:
    """The three curve-staleness limits that are policy violations, not tails."""
    prov = pd.DataFrame(prov)
    lags = (pd.to_numeric(prov.get("snapshot_lag_seconds"), errors="coerce")
            if "snapshot_lag_seconds" in prov.columns
            else pd.Series(dtype="float64"))
    served = served_mask(prov)
    hole = _hole_mask(prov, served)

    future = Threshold(
        name="curve_snapshot_from_future", direction="above", warn=1, alarm=1,
        rationale=(
            "A curve stamped after the print contains the print, so the "
            "direction call reads back the trade it is classifying. That is "
            "circular in the one way this whole exercise exists to prevent, and "
            "it is not a tail: the policy sets allow_future=False, so a single "
            "occurrence means the policy was not the one that served the row. "
            "The shipped nearest-either-direction default does exactly this to "
            "1.09% of legs, by up to three hours."),
        action="Halt the run. Re-check the SnapshotPolicy actually reaching the store.",
    )
    n_future = int((lags < 0).sum())

    in_sess_over = Threshold(
        name="in_session_lag_over_policy", direction="above", warn=1, alarm=1,
        rationale=(
            "Inside the session the snapshot must be the minute asked for "
            "(IN_SESSION_MAX_LAG = 60s). A row that is in-session by policy and "
            "yet staler than the bound means the served snapshot did not come "
            "from the branch the provenance says it did -- 60s admits 0.21bp of "
            "5Y drift at p90, 30 minutes admits 1.07bp."),
        action="Halt the run and re-check the session branch for those timestamps.",
    )
    n_in_over = (int(((served & ~hole).to_numpy()
                      & (lags > snapshot.IN_SESSION_MAX_LAG.total_seconds())
                      .fillna(False).to_numpy()).sum())
                 if len(lags) else 0)

    hole_p90 = (float(lags[(served & hole).to_numpy()].quantile(0.90))
                if len(lags) and bool((served & hole).any()) else float("nan"))
    hole_thr = Threshold(
        name="overnight_hole_lag_p90_seconds", direction="above",
        warn=3600.0, alarm=snapshot.OUT_OF_SESSION_MAX_LAG.total_seconds(),
        rationale=(
            "The 2h reach-back is the bound, not the expectation: the seven "
            "hour-00 prints in the session-branch probe were all served at "
            "1-97 minutes (7/7 -- a sample, not a population, so treat the "
            "range as indicative and the bound as the contract). A p90 pressed "
            "against the bound means the feed stopped earlier than the session "
            "model thinks, and the rows at the bound are the ones carrying the "
            "1.43bp tail."),
        action="Re-check the publication session for the dates involved.",
    )

    n_served = int(served.sum())
    return [
        Metric("curve_snapshot_from_future", n_future, n_served, future,
               future.evaluate(n_future)),
        Metric("in_session_lag_over_policy", n_in_over, n_served, in_sess_over,
               in_sess_over.evaluate(n_in_over)),
        Metric("overnight_hole_lag_p90_seconds", hole_p90, int(hole.sum()),
               hole_thr, hole_thr.evaluate(hole_p90)),
    ]


def report_lag_by_block(legs) -> pd.DataFrame:
    """Report lag (event minus execution), **split by the block flag. Always.**

    There is no pooled row in this frame and that is the interface doing its
    job. A block arrives delayed, and by the time it prints the dealer has
    already partially hedged it -- so a block print and an ASAP print of the
    same size are not the same event and their lags are not draws from one
    distribution. Pooling them produces a single number that describes neither.

    What the numbers should look like, so a departure is visible: F-3 measured
    p50 = p90 = 0 over all 2,289,646 flow legs for blocks and non-blocks alike,
    with p99 at 1,091s / 911s and a 2.4M-second maximum. So this column is
    **not** a publication delay -- the tape has no dissemination timestamp at
    all, and the real measured publication lag is a median 5.23 min / p95 11.3
    min recovered from slice mtimes (F-19/F-21). A p90 that departs from zero
    means the column changed meaning, which is an ingest regime change, not a
    market one.
    """
    legs = pd.DataFrame(legs)
    cols = ["is_block", "n", "p50", "p90", "p99", "max", "status"]
    if legs.empty:
        return pd.DataFrame(columns=cols)
    _require(legs, ["is_block", "report_lag_seconds"], "report_lag_by_block")

    threshold = _report_lag_threshold()
    rows = []
    for flag in (False, True):
        mask = legs["is_block"].fillna(False).astype(bool) == flag
        lags = pd.to_numeric(legs.loc[mask, "report_lag_seconds"],
                             errors="coerce").dropna()
        p90 = float(lags.quantile(0.90)) if len(lags) else float("nan")
        rows.append({
            "is_block": flag, "n": int(mask.sum()),
            "p50": float(lags.quantile(0.50)) if len(lags) else float("nan"),
            "p90": p90,
            "p99": float(lags.quantile(0.99)) if len(lags) else float("nan"),
            "max": float(lags.max()) if len(lags) else float("nan"),
            "status": threshold.evaluate(p90) if len(lags) else NO_DATA,
        })
    return pd.DataFrame(rows, columns=cols)


def _report_lag_threshold() -> Threshold:
    return Threshold(
        name="report_lag_p90_seconds", direction="above", warn=1.0, alarm=60.0,
        rationale=(
            "F-3 measured p50 = p90 = 0 across all 2,289,646 flow legs, blocks "
            "included, so any non-zero p90 is a change in what the column "
            "means rather than a change in the market. Evaluated per block "
            "class because the two populations are different events."),
        action=("Re-measure event-minus-execution against the raw slices before "
                "using the availability clock; if the tape has started carrying "
                "a real dissemination delay, visibility_timestamp is no longer "
                "the most conservative estimate and must be revisited."),
    )


# --------------------------------------------------------------------------
# 6. pricing success, stratified
# --------------------------------------------------------------------------

_STRATUM_THRESHOLDS = {
    "SPOT": (0.995, 0.99,
             "F-15 priced 200 of 200 sampled on-market SOFR outrights under the "
             "strict policy. Spot legs are the easiest population there is, so "
             "anything below 99.5% is the pricer, not the data."),
    "FORWARD_START": (0.99, 0.97,
                      "37% of flow legs are forward-starting, so this stratum is "
                      "a third of the ladder rather than a corner case; a "
                      "forward-start-specific failure is a schedule or "
                      "effective-date bug and shows up nowhere else."),
    "PAST_START": (0.98, 0.95,
                   "Past-start legs need published fixings and are the one "
                   "stratum with a known failure mode: T-4's single UNKNOWN was "
                   "'fixings contain more fixings than expected'. All 36,763 "
                   "ECONOMIC_UNWIND rows are past-effective, so this stratum "
                   "carries the whole unwind population."),
    "CAPPED": (0.99, 0.97,
               "Capping touches the notional, not the schedule, so pricing a "
               "capped leg should be exactly as easy as pricing any other. A "
               "capped-specific failure means the cap handling reached the "
               "pricer, and capped legs are 5x more likely to carry a NULL "
               "fixed_rate (5.9% vs 1.2%) so the loss is not proportional."),
}


def pricing_success_by_stratum(legs) -> pd.DataFrame:
    """Leg-level pricing success by spot / forward / past-start / capped / BASIS.

    **The strata overlap on purpose.** A capped forward-start leg is in two of
    them. A partition would put it in one cell and hide the other, and the point
    here is to catch a stratum-specific collapse, not to count legs: T-4's
    pricing failure was one row in 484 -- invisible at 99.8% overall, and 100%
    of its stratum if its stratum is small enough.

    **BASIS inverts.** It is ``EXCL_UNSUPPORTED_INDEX`` by construction, so a
    *successfully priced* BASIS leg is the alarm: the exclusion leaked and a
    single-curve mid is being taken on a two-index trade. Which is why the
    index column and ``is_capped`` are ``_require``-d rather than ``.get``-ed:
    a ``.get`` default makes those two strata empty, empty reports ``NO_DATA``,
    and a renamed column then disables an **inverted** alarm permanently and
    quietly. There is no reading of that frame in which the BASIS row's absence
    looks wrong.
    """
    legs = pd.DataFrame(legs)
    cols = ["stratum", "n", "n_priced", "success_rate", "warn", "alarm",
            "status", "rationale"]
    if legs.empty:
        return pd.DataFrame(columns=cols)
    _require(legs, ["as_of_date", "effective_date", "priced", "is_capped"],
             "pricing_success_by_stratum")
    index_col = ("rate_index" if "rate_index" in legs.columns
                 else "rate_index_clean")
    _require(legs, [index_col], "pricing_success_by_stratum (the BASIS alarm)")

    as_of = pd.to_datetime(legs["as_of_date"])
    eff = pd.to_datetime(legs["effective_date"])
    horizon = as_of + pd.Timedelta(days=SPOT_WINDOW_DAYS)
    priced = legs["priced"].fillna(False).astype(bool)

    masks = {
        "SPOT": (eff >= as_of) & (eff <= horizon),
        "FORWARD_START": eff > horizon,
        "PAST_START": eff < as_of,
        "CAPPED": legs["is_capped"].fillna(False).astype(bool),
        "BASIS": legs[index_col].astype(str).str.upper().eq("BASIS"),
    }

    rows = []
    for name, mask in masks.items():
        n = int(mask.sum())
        n_priced = int(priced[mask].sum())
        rate = (n_priced / n) if n else float("nan")
        if name == "BASIS":
            status = NO_DATA if n == 0 else (ALARM if n_priced > 0 else OK)
            warn = alarm = None
            rationale = (
                "BASIS is EXCL_UNSUPPORTED_INDEX by construction (15,182 flow "
                "legs), so success here is the failure: a priced BASIS leg "
                "means a two-index trade was mid-marked off one curve.")
        else:
            warn, alarm, rationale = _STRATUM_THRESHOLDS[name]
            thr = Threshold(name=f"pricing_success_{name}", direction="below",
                            warn=warn, alarm=alarm, rationale=rationale,
                            action="")
            status = NO_DATA if n == 0 else thr.evaluate(rate)
        rows.append({"stratum": name, "n": n, "n_priced": n_priced,
                     "success_rate": rate, "warn": warn, "alarm": alarm,
                     "status": status, "rationale": rationale})
    return pd.DataFrame(rows, columns=cols)


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------

def health_report(metrics) -> pd.DataFrame:
    """Flatten the metrics into one table, worst first.

    ``status`` is the column to page on. It is ordered so that a single ALARM
    cannot be lost in a long OK list, which is the failure mode of every
    monitoring table that sorts by name.
    """
    rows = []
    for m in metrics:
        m = m.as_metric() if isinstance(m, KappaResult) else m
        rows.append({
            "metric": m.name, "value": m.value, "n": m.n, "status": m.status,
            "direction": m.threshold.direction, "warn": m.threshold.warn,
            "alarm": m.threshold.alarm, "rationale": m.threshold.rationale,
            "action": m.threshold.action, "detail": m.detail,
        })
    out = pd.DataFrame(rows, columns=["metric", "value", "n", "status",
                                      "direction", "warn", "alarm",
                                      "rationale", "action", "detail"])
    if out.empty:
        return out
    out["_rank"] = out["status"].map(_RANK)
    return out.sort_values("_rank", ascending=False).drop(columns="_rank").reset_index(drop=True)


__all__ = [
    "ALARM", "DEAD_ZONE_ABS_ALARM", "KappaResult", "Metric", "NO_DATA", "OK",
    "SPOT_WINDOW_DAYS", "Threshold", "WARN", "d2d_recycling_kappa",
    "dead_zone_fraction", "health_report", "imputed_notional_fraction",
    "is_overnight_hole", "overnight_hole_fraction", "pricing_success_by_stratum",
    "report_lag_by_block", "rolling_recycling_kappa", "snapshot_lag_distribution",
    "snapshot_lag_metrics",
]
