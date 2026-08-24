r"""Data layer for the data-surprise -> Fedspeak lead study.

The claim under test comes from JWS Macro #8, *Playing Devil's Advocate*
(23-Aug-2026): an equally-weighted Bloomberg Inflation & Labor Market Surprise
composite, **pushed forward 5 weeks**, tracks the Bloomberg Fed Sentiment
Language Model. The reading offered is that data surprises lead Fedspeak by a
tidy five weeks, so the July->August rolldown in the surprise composite implies
dovish Fedspeak through the 16-Sep-2026 FOMC.

This module supplies the two series on our own infrastructure and the estimators
that *measure* the lead rather than assuming it. Every knob lives in
:class:`LeadConfig`, which is frozen: the headline number is taken at the frozen
configuration and every alternative is reported as robustness, never as a
replacement. That ordering is the point -- see
``feedback_adversarial_review_flatters``.

Two data facts shape everything here.

**The sentiment corpus is not point-in-time.** JPM publishes a PDF per speech
carrying that speaker's *history*, and re-scores history as the model is
revised. Of the 730 Fed rows, 53% come from a report published after the speech
they describe (median 1 day, p90 246 days, max 6432). The publication date is
recoverable only from the ``source_file`` prefix. So there are two legitimate
series and they answer different questions:

``as_published``
    keyed on the speech date alone. Reproduces the *shape* of JWS's chart and is
    fine for describing history. Not tradeable.
``point_in_time``
    gated on ``pub_date <= t`` as well. Starts 2023-05-02, is choppier, and is
    the only one that says anything about what could have been acted on.

**The surprise side is not the binding constraint.** Citi's daily economic
surprise sub-indices run from 2003-01; the sentiment corpus starts 2023-05. The
honest point-in-time sample is therefore ~3 years of weekly observations, which
is the number to quote, not the width of the x-axis.

Sources
-------
sentiment
    ``project-oasis/private/jpm_research/fed_speak_nlp/global_hawk_dove_scores.csv``
    read through the existing
    ``intraday_fed_hawk_dove.global_hawk_dove_common.load_global_scores``, which
    already recovers ``pub_date``.
surprise
    Citi Velocity ``CVTSHIST`` economic surprise tags, served from a committed
    snapshot parquet (built by ``fed_sentiment_lead_refresh.py``, which can
    rebuild it from the live add-in or from the hand-exported workbook).
"""
from __future__ import annotations

import dataclasses
import datetime
import os
import pathlib
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]

#: The JPM NLP corpus. It lives outside this repo (it is licensed research), so
#: the path is a default rather than a constant: set ``ARBS_FED_SPEAK_CSV`` to
#: point at another checkout. Everything else in the study runs from the
#: committed snapshot, so this is the one input another machine must supply.
DEFAULT_SCORES_CSV = os.environ.get(
    "ARBS_FED_SPEAK_CSV",
    r"C:\Users\chris\clee\project-oasis\private\jpm_research\fed_speak_nlp"
    r"\global_hawk_dove_scores.csv",
)

#: The hand-exported CVTSHIST workbook, used when the snapshot is missing.
DEFAULT_XLSX = (
    r"C:\Users\chris\Downloads\citi_economic_and_inflation_data_suprise_dataset.xlsx"
)

#: The committed snapshot the notebook reads. Small, and it makes the notebook
#: reproducible on a machine with neither Excel nor the workbook.
DEFAULT_SNAPSHOT = HERE / "fed_sentiment_lead_citi_snapshot.parquet"

_PREFIX = "ECONOMICS.SURPRISE_INDEX."
_SUFFIX = " - CLOSE"

#: Citi daily economic **surprise** sub-indices. The chart needs the two that
#: correspond to Bloomberg's Labor Market and Inflation surprise indices.
TAG_LABOUR = _PREFIX + "ESI.CESI.DM.SI_USD.LABOUR_MARKET"
TAG_PRICES = _PREFIX + "ESI.CESI.DM.SI_USD.PRICES_OR_MONEY_SUPPLY"
TAG_ECON_TOTAL = _PREFIX + "ESI.CESI.DM.SI_USD.TOTAL"

#: The proper Citi **Inflation** Surprise Index -- MONTHLY, 343 observations
#: back to 1998. Kept as a cross-check on a separate panel; never averaged into
#: a daily series, because forward-filling a monthly leg into a daily one makes
#: the composite a step function whose turning points are calendar artefacts,
#: and turning points are the entire claim under test.
TAG_CISI_MONTHLY = _PREFIX + "ISI.SI_CISI.DM.SI_USD"

#: Front-end rate for the tradeability section. Daily, 2005-01 onwards, already
#: in the shared Citi tag cache, so no COM is needed to read it.
TAG_SOFR_2Y = "RATES.OIS.USD_SOFR.PAR.2Y"

#: Every tag the snapshot carries. Superset of what the frozen config uses, so a
#: robustness question does not need a re-export.
SNAPSHOT_TAGS: Tuple[str, ...] = (
    TAG_LABOUR,
    TAG_PRICES,
    TAG_ECON_TOTAL,
    _PREFIX + "ESI.CESI.DM.SI_USD.BUSINESS_CYCLE",
    _PREFIX + "ESI.CESI.DM.SI_USD.CONSUMER_SECTOR",
    _PREFIX + "ESI.CESI.DM.SI_USD.INDUSTRIAL_OUTPUT",
    _PREFIX + "ESI.CESI.DM.SI_USD.REAL_ESTATE",
    _PREFIX + "ESI.CESI.DM.SI_USD.SURVEYS_AGGREGATE_BUSINESS",
    _PREFIX + "ESI.CEDI.DM.SI_USD.LABOUR_MARKET",
    _PREFIX + "ESI.CEDI.DM.SI_USD.PRICES_OR_MONEY_SUPPLY",
    TAG_CISI_MONTHLY,
    _PREFIX + "ISI.SI_CIDI.DM.SI_USD",
)


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class LeadConfig:
    """Every knob, and why it sits where it does.

    Frozen deliberately. The headline lead is measured once at these values;
    everything else in the notebook is robustness around them. Choosing the
    window after seeing the lag curve would tune the argmax, which is the
    failure mode this desk keeps rediscovering.
    """

    # -- sentiment -------------------------------------------------------
    scores_csv: str = DEFAULT_SCORES_CSV
    central_bank: str = "FED"
    #: ``hawk_dove_score`` is the per-speech number. ``trailing_5_avg`` and
    #: ``rolling_6m_avg`` are JPM's own smoothers and already contain the
    #: speech being scored, so they are cross-checks, not the input.
    score_column: str = "hawk_dove_score"
    #: Calendar half-life of the committee sentiment EWMA. 21 days ~ 10 Fed
    #: speeches at the observed 3.28/week, which is roughly the committee size
    #: that speaks in any month. Short enough to turn inside a five-week lead;
    #: long enough that one speech cannot set the level.
    ewma_halflife_days: float = 21.0
    #: A speech older than this contributes nothing at all. At hl=21d a
    #: 126-day-old speech carries weight 2**-6 = 1.6%, so the truncation costs
    #: almost nothing and it bounds how far a late-published report can reach
    #: back. NOTE the interaction with the vintage gate: a report published 245
    #: days after the speech becomes visible already outside this window, so it
    #: never contributes to the point-in-time index. That is correct -- it is
    #: stale news on arrival -- and the share it removes is reported by G1.
    ewma_window_days: int = 126
    #: A weekly index built on fewer than this many visible speeches is NaN.
    #: The point-in-time series has 8 visible rows at 2023-05-02; the first
    #: weeks are composition noise, not sentiment.
    min_speeches_in_window: int = 5

    # -- surprise --------------------------------------------------------
    #: The two legs of the composite. Both are daily members of the same Citi
    #: family, so no mixed-frequency splice is involved.
    surprise_tags: Tuple[str, ...] = (TAG_LABOUR, TAG_PRICES)
    #: Trailing standardisation window, business days. 756bd ~ 3 years: long
    #: enough to be a level, short enough to follow a regime. Citi's raw index
    #: runs in the tens; JWS's axis runs -0.75..+1.50, so he is plotting
    #: something standardised.
    z_window_bd: int = 756
    #: Minimum observations before a z-score is emitted. 504bd = 2 years.
    z_min_periods: int = 504

    # -- sampling --------------------------------------------------------
    #: Weekly anchor. Friday-ending weeks match how a macro chart is read and
    #: put payrolls inside the week they print.
    week_anchor: str = "W-FRI"

    # -- lead scan -------------------------------------------------------
    #: Scanned symmetrically. Negative lags -- sentiment leading surprises --
    #: are a control: if the curve peaks there the story is backwards.
    min_lag_weeks: int = -13
    max_lag_weeks: int = 13
    #: JWS's claim, plotted for the reproduction panel.
    jws_lead_weeks: int = 5

    # -- inference -------------------------------------------------------
    #: Stationary (Politis-Romano) block bootstrap. Mean block 8 weeks ~ two
    #: months, long enough to carry the persistence both series inherit from
    #: their own smoothers.
    boot_draws: int = 2000
    boot_mean_block_weeks: float = 8.0
    #: Phase-randomised surrogates for the null. Each surrogate is scored by
    #: the SAME search the real analysis runs -- the max over every lag -- so
    #: the null pays for the search too.
    surrogate_draws: int = 2000
    seed: int = 20260823

    # -- sample ----------------------------------------------------------
    #: First JPM report in the corpus. Under honest gating there is no signal
    #: before this date at all.
    corpus_start: datetime.date = datetime.date(2023, 5, 2)
    #: The as-published panel is density-gated rather than run back to the
    #: earliest speech date (2008): 2021 carries 8 Fed speeches in the whole
    #: year, which is a chart, not a sample.
    as_published_start: datetime.date = datetime.date(2022, 1, 1)
    #: Reproduction panel window, matching the cut being worked from.
    chart_start: datetime.date = datetime.date(2023, 4, 1)

    # -- turning points --------------------------------------------------
    #: Minimum prominence, in composite units, for a local extremum to count.
    #: Found algorithmically; hand-picking points to match JWS's four arrows
    #: would bake in his conclusion.
    turning_point_prominence: float = 0.60
    #: The same, on the sentiment side. It needs its own value because the two
    #: series live on different scales -- the composite is a z-score of order 1,
    #: the sentiment index runs -9 to +30 -- so one number cannot serve both.
    #: 6.0 is a little under one standard deviation of the sentiment series
    #: (6.82 on the point-in-time sample), which is the same relative bar the
    #: 0.60 sets on a composite whose sample standard deviation is 0.68.
    sentiment_turning_point_prominence: float = 6.0

    def lags(self) -> np.ndarray:
        return np.arange(self.min_lag_weeks, self.max_lag_weeks + 1, dtype=int)

    def rng(self, offset: int = 0) -> np.random.Generator:
        return np.random.default_rng(self.seed + offset)

    def describe(self) -> pd.DataFrame:
        """Every knob as a table, so the notebook can print it verbatim."""
        rows = []
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            if isinstance(v, tuple):
                v = "\n".join(str(x) for x in v)
            rows.append({"knob": f.name, "value": v})
        return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# surprise side
# --------------------------------------------------------------------------
def _strip_close(name: str) -> str:
    return name[: -len(_SUFFIX)] if name.endswith(_SUFFIX) else name


def read_surprise_xlsx(path: str = DEFAULT_XLSX) -> pd.DataFrame:
    """The hand-exported CVTSHIST workbook as a wide daily frame.

    Row 0 holds the literal ``=CVTSHIST(...)`` array formula; the header is row
    1. Column names carry a trailing ``' - CLOSE'`` which is stripped so the
    frame is keyed by bare Velocity tags -- the same keys the live path uses.
    """
    raw = pd.read_excel(path, sheet_name="Sheet1", header=1)
    raw = raw.rename(columns={raw.columns[0]: "Date"})
    raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")
    raw = raw.dropna(subset=["Date"]).set_index("Date").sort_index()
    raw = raw.apply(pd.to_numeric, errors="coerce")
    raw.columns = [_strip_close(c) for c in raw.columns]
    raw.index.name = "date"
    return raw


def read_surprise_snapshot(path: pathlib.Path = DEFAULT_SNAPSHOT) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame.index = pd.to_datetime(frame.index)
    frame.index.name = "date"
    return frame.sort_index()


def snapshot_provenance(path: pathlib.Path = DEFAULT_SNAPSHOT) -> Dict[str, str]:
    """How the snapshot was built and when. Printed, never assumed."""
    meta = path.with_suffix(".json")
    if not meta.exists():
        return {"source": "unknown", "built": "unknown", "note": "no sidecar"}
    import json

    return json.loads(meta.read_text(encoding="utf-8"))


def load_surprise_panel(
    *,
    snapshot: pathlib.Path = DEFAULT_SNAPSHOT,
    xlsx: str = DEFAULT_XLSX,
) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Snapshot first, workbook second. Never COM -- see the refresh script.

    Driving Excel over COM from inside a notebook runner is a measured hazard
    in this repo, so the live path is an explicit, separate command
    (``fed_sentiment_lead_refresh.py --live``) that rewrites the snapshot. The
    notebook then reads the snapshot and prints its provenance, so a stale
    input is visible rather than silent.
    """
    if pathlib.Path(snapshot).exists():
        return read_surprise_snapshot(pathlib.Path(snapshot)), snapshot_provenance(
            pathlib.Path(snapshot)
        )
    if os.path.exists(xlsx):
        frame = read_surprise_xlsx(xlsx)
        return frame, {
            "source": "xlsx",
            "path": xlsx,
            "built": "read at import",
            "note": "snapshot missing; run fed_sentiment_lead_refresh.py",
        }
    raise FileNotFoundError(
        f"neither the snapshot ({snapshot}) nor the workbook ({xlsx}) is readable"
    )


def read_cached_rate(tag: str = TAG_SOFR_2Y) -> Optional[pd.Series]:
    """A daily rate from the shared Citi tag cache, read-only, no COM.

    Returns ``None`` rather than raising when the cache has nothing, so the
    tradeability section can degrade to "not testable here" instead of failing
    the notebook on a machine with a cold cache.
    """
    try:
        from MDP.CitiVelocityExcel.cache import CitiVeloTagCache

        series = CitiVeloTagCache().read(tag, "DAILY", "CLOSE")
    except (ImportError, FileNotFoundError, OSError) as exc:  # pragma: no cover
        # a MISSING cache is absence and degrades to "not testable here"; a
        # CORRUPT one is a defect and must not be reported as absence, so
        # anything other than these three propagates
        print(f"read_cached_rate({tag}): cache unavailable -- {type(exc).__name__}: {exc}")
        return None
    if series is None or len(series) == 0:
        return None
    out = pd.Series(series.values, index=pd.to_datetime(series.index), name=tag)
    return out.sort_index()


def trailing_z(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Standardise on a TRAILING window only.

    The window ends at ``t`` inclusive, which uses no future information: the
    value at ``t`` is knowable at ``t``. A full-sample mean and standard
    deviation would not be, and would quietly rescale the whole history every
    time a new observation arrived.
    """
    s = pd.Series(series).astype(float)
    mu = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std(ddof=1)
    return (s - mu) / sd.replace(0.0, np.nan)


def build_surprise_composite(
    panel: pd.DataFrame, cfg: LeadConfig
) -> Tuple[pd.Series, pd.DataFrame]:
    """Equal-weighted composite of trailing-z legs, daily.

    Returns ``(composite, legs)`` where ``legs`` carries the raw and z form of
    each leg so the notebook can show what the standardisation did.
    """
    legs: Dict[str, pd.Series] = {}
    for tag in cfg.surprise_tags:
        if tag not in panel.columns:
            raise KeyError(f"surprise tag missing from the panel: {tag}")
        raw = panel[tag].astype(float)
        legs[f"{_short(tag)}_raw"] = raw
        legs[f"{_short(tag)}_z"] = trailing_z(raw, cfg.z_window_bd, cfg.z_min_periods)
    frame = pd.DataFrame(legs).sort_index()
    zcols = [c for c in frame.columns if c.endswith("_z")]
    # every leg must be present; a composite that silently becomes one leg when
    # the other is missing is a different series wearing the same name
    composite = frame[zcols].mean(axis=1).where(frame[zcols].notna().all(axis=1))
    composite.name = "surprise_composite"
    return composite, frame


def _short(tag: str) -> str:
    return tag.split(".")[-1].lower()


def weekly_last(series: pd.Series, anchor: str) -> pd.Series:
    """Last observation inside each week. Weeks with no observation are NaN."""
    s = pd.Series(series).dropna()
    if s.empty:
        return pd.Series(dtype=float)
    return s.resample(anchor).last()


# --------------------------------------------------------------------------
# sentiment side
# --------------------------------------------------------------------------
def load_fed_scores(cfg: LeadConfig) -> pd.DataFrame:
    """Fed rows with ``pub_date`` recovered, via the existing loader.

    Uses ``global_hawk_dove_common.load_global_scores`` rather than a fresh
    parser: that function already handles the vintage recovery and the two
    parser bugs recorded in ``reference_jpm_nlp_score_vintage``.
    """
    common = _import_hawk_dove_common()
    df = common.load_global_scores(cfg.scores_csv, cfg.score_column)
    fed = df[df["central_bank"] == cfg.central_bank].copy()
    fed["date"] = pd.to_datetime(fed["date"])
    fed["pub_date"] = pd.to_datetime(fed["pub_date"])
    fed = fed.dropna(subset=[cfg.score_column])
    return fed.sort_values(["date", "speaker"]).reset_index(drop=True)


def _import_hawk_dove_common():
    path = REPO / "notebooks" / "backtests" / "intraday_fed_hawk_dove"
    if str(path) not in sys.path:
        sys.path.append(str(path))
    if str(REPO) not in sys.path:
        sys.path.append(str(REPO))
    import global_hawk_dove_common  # type: ignore

    return global_hawk_dove_common


def sentiment_index(
    scores: pd.DataFrame,
    grid: pd.DatetimeIndex,
    cfg: LeadConfig,
    *,
    point_in_time: bool,
    score_column: Optional[str] = None,
    weight_by_relevance: bool = False,
) -> pd.DataFrame:
    """Committee sentiment on ``grid``, as an EWMA over VISIBLE speeches.

    At each grid date ``t`` the index is a calendar-time exponentially weighted
    mean of the Fed speeches visible at ``t``:

    * ``as_published`` visibility is ``speech_date <= t``;
    * ``point_in_time`` visibility is ``speech_date <= t AND pub_date <= t``.

    The weight is set by *speech* recency, ``0.5 ** (age_days / halflife)``, in
    both vintages. So a report published 245 days after its speech arrives with
    that speech already 245 days old and -- past ``ewma_window_days`` --
    contributes nothing. That is the intended behaviour: a re-score of an old
    speech is not news about the committee's current stance.

    Returns a frame with the index, the number of contributing speeches, and
    the age of the newest visible speech, so the notebook can show where the
    series is thin rather than trusting a number computed from two speeches.
    """
    col = score_column or cfg.score_column
    s_date = scores["date"].to_numpy("datetime64[D]")
    p_date = scores["pub_date"].to_numpy("datetime64[D]")
    vals = scores[col].to_numpy(float)
    if weight_by_relevance:
        rel = scores["relevance_pct"].to_numpy(float)
        rel = np.where(np.isfinite(rel), rel, np.nanmedian(rel))
        rel = np.clip(rel, 1.0, None)
    else:
        rel = np.ones_like(vals)

    out_idx, out_n, out_age = [], [], []
    for t in grid:
        td = np.datetime64(t.date(), "D")
        age = (td - s_date).astype("timedelta64[D]").astype(int)
        visible = (age >= 0) & (age <= cfg.ewma_window_days) & np.isfinite(vals)
        if point_in_time:
            visible &= p_date <= td
        n = int(visible.sum())
        if n < cfg.min_speeches_in_window:
            out_idx.append(np.nan)
            out_n.append(n)
            out_age.append(np.nan if n == 0 else float(age[visible].min()))
            continue
        w = np.power(0.5, age[visible] / cfg.ewma_halflife_days) * rel[visible]
        out_idx.append(float(np.sum(w * vals[visible]) / np.sum(w)))
        out_n.append(n)
        out_age.append(float(age[visible].min()))

    return pd.DataFrame(
        {"sentiment": out_idx, "n_speeches": out_n, "newest_age_days": out_age},
        index=grid,
    )


def weekly_grid(start, end, anchor: str) -> pd.DatetimeIndex:
    return pd.date_range(start=pd.Timestamp(start), end=pd.Timestamp(end), freq=anchor)


# --------------------------------------------------------------------------
# lead estimation
# --------------------------------------------------------------------------
def lag_matrix(
    x: pd.Series, y: pd.Series, lags: Sequence[int]
) -> Tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    """``y`` and every lagged copy of ``x``, on ONE common-support row set.

    Every lag is then scored on the same rows, so a difference between lags is
    a difference in the relationship and not a difference in the sample. The
    varying-sample curve is reported alongside as a check that the two agree.
    """
    xy = pd.concat([x.rename("x"), y.rename("y")], axis=1).sort_index()
    cols = {f"x{k}": xy["x"].shift(k) for k in lags}
    cols["y"] = xy["y"]
    frame = pd.DataFrame(cols, index=xy.index).dropna()
    Y = frame["y"].to_numpy(float)
    X = np.column_stack([frame[f"x{k}"].to_numpy(float) for k in lags])
    return X, Y, frame.index


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 3:
        return np.nan
    sa, sb = a.std(), b.std()
    if sa == 0 or sb == 0 or not np.isfinite(sa) or not np.isfinite(sb):
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def lag_curve_common(X: np.ndarray, Y: np.ndarray, lags: Sequence[int]) -> pd.DataFrame:
    """Correlation at every lag on the common-support matrix."""
    cor = [_corr(X[:, j], Y) for j in range(X.shape[1])]
    return pd.DataFrame({"lag_weeks": list(lags), "corr": cor, "n": len(Y)})


def lag_curve_pairwise(
    x: pd.Series, y: pd.Series, lags: Sequence[int]
) -> pd.DataFrame:
    """Correlation at every lag using each lag's own maximal sample."""
    xy = pd.concat([x.rename("x"), y.rename("y")], axis=1).sort_index()
    rows = []
    for k in lags:
        pair = pd.concat([xy["x"].shift(k), xy["y"]], axis=1).dropna()
        rows.append(
            {
                "lag_weeks": int(k),
                "corr": _corr(pair.iloc[:, 0].to_numpy(), pair.iloc[:, 1].to_numpy()),
                "n": len(pair),
            }
        )
    return pd.DataFrame(rows)


def fit_ar(x: np.ndarray, max_p: int = 8) -> Tuple[np.ndarray, int]:
    """AR(p) by OLS with p chosen on AIC. Returns ``(phi, p)``.

    Used for prewhitening. Both series here are low-pass filtered by
    construction -- Citi's index carries its own decay, ours adds a trailing
    z-score, and the sentiment side is an EWMA -- so the raw cross-correlation
    of levels is a broad plateau by construction. Prewhitening by the input's
    own AR model is the textbook way to see the lead structure underneath.
    """
    x = np.asarray(x, float)
    n = len(x)
    max_p = int(min(max_p, (n - 3) // 4))
    if max_p < 1:
        return np.zeros(0), 0
    # every candidate order is fitted on the SAME rows -- the last n - max_p of
    # them. AIC compares log-likelihoods, and a likelihood computed on a
    # different number of observations is not comparable, so letting the sample
    # grow as p shrinks would bias the selection toward the shortest lag.
    start = max_p
    yv = x[start:]
    best = (np.inf, np.zeros(0), 0)
    for p in range(1, max_p + 1):
        Z = np.column_stack([x[start - j - 1 : n - j - 1] for j in range(p)])
        beta, *_ = np.linalg.lstsq(Z, yv, rcond=None)
        resid = yv - Z @ beta
        sigma2 = float(resid @ resid) / len(yv)
        if sigma2 <= 0:
            continue
        aic = len(yv) * np.log(sigma2) + 2 * p
        if aic < best[0]:
            best = (aic, beta, p)
    return best[1], best[2]


def prewhiten(x: pd.Series, y: pd.Series, max_p: int = 8) -> Tuple[pd.Series, pd.Series, int]:
    """Filter BOTH series by the AR model fitted to ``x``.

    Box-Jenkins: the cross-correlation of the two filtered series estimates the
    impulse response, which is what "leads by k" actually means. Filtering ``y``
    by ``x``'s model, not its own, is the part that matters.

    ``max_p`` defaults to 8 because AIC picks 6 on this study's weekly sample
    and a selection sitting on the cap is not a selection. It does not matter
    much either way: sweeping the cap from 2 to 16 moves the point-in-time
    argmax only between +12w and +13w and the peak correlation between 0.14 and
    0.22, never near five weeks and never below p = 0.055.
    """
    xy = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna().sort_index()
    phi, p = fit_ar(xy["x"].to_numpy(float), max_p=max_p)
    if p == 0:
        return xy["x"], xy["y"], 0
    def _filter(v: np.ndarray) -> np.ndarray:
        n = len(v)
        out = v[p:].copy()
        for j in range(p):
            out = out - phi[j] * v[p - j - 1 : n - j - 1]
        return out
    idx = xy.index[p:]
    return (
        pd.Series(_filter(xy["x"].to_numpy(float)), index=idx, name="x_pw"),
        pd.Series(_filter(xy["y"].to_numpy(float)), index=idx, name="y_pw"),
        p,
    )


def transform_pair(
    x: pd.Series, y: pd.Series, transform: str, max_p: int = 8
) -> Tuple[pd.Series, pd.Series, Dict[str, object]]:
    """``levels`` / ``changes`` / ``prewhitened``, as one switch."""
    if transform == "levels":
        return x, y, {}
    if transform == "changes":
        return x.diff(), y.diff(), {}
    if transform == "prewhitened":
        xp, yp, p = prewhiten(x, y, max_p=max_p)
        return xp, yp, {"ar_order": p}
    raise ValueError(f"unknown transform {transform!r}")


def stationary_bootstrap_index(
    n: int, mean_block: float, rng: np.random.Generator
) -> np.ndarray:
    """Politis-Romano stationary bootstrap row indices (circular, geometric)."""
    p = 1.0 / float(mean_block)
    idx = np.empty(n, dtype=int)
    cur = int(rng.integers(0, n))
    for i in range(n):
        idx[i] = cur
        if rng.random() < p:
            cur = int(rng.integers(0, n))
        else:
            cur = (cur + 1) % n
    return idx


def bootstrap_lead(
    X: np.ndarray,
    Y: np.ndarray,
    lags: Sequence[int],
    cfg: LeadConfig,
    *,
    draws: Optional[int] = None,
    rng: Optional[np.random.Generator] = None,
) -> Dict[str, object]:
    """Block-bootstrap the whole lag curve; report the argmax distribution.

    Rows of the common-support matrix are resampled in blocks, so every draw
    recomputes the *entire* curve from a coherent sample and the argmax is a
    statistic of that draw rather than a re-pick over independent noise.
    """
    lags = np.asarray(list(lags), dtype=int)
    rng = rng or cfg.rng(1)
    draws = draws or cfg.boot_draws
    n = len(Y)
    curves = np.full((draws, len(lags)), np.nan)
    for b in range(draws):
        idx = stationary_bootstrap_index(n, cfg.boot_mean_block_weeks, rng)
        Yb, Xb = Y[idx], X[idx, :]
        for j in range(len(lags)):
            curves[b, j] = _corr(Xb[:, j], Yb)
    finite = np.isfinite(curves).all(axis=1)
    curves = curves[finite]
    arg = lags[np.nanargmax(curves, axis=1)]
    return {
        "curves": curves,
        "argmax": arg,
        "argmax_q05": float(np.quantile(arg, 0.05)),
        "argmax_q50": float(np.quantile(arg, 0.50)),
        "argmax_q95": float(np.quantile(arg, 0.95)),
        "band_lo": np.nanquantile(curves, 0.05, axis=0),
        "band_hi": np.nanquantile(curves, 0.95, axis=0),
        "draws_used": int(curves.shape[0]),
    }


def phase_randomise(x: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """A surrogate with the SAME power spectrum and no relation to anything.

    Preserving the spectrum preserves the autocorrelation exactly, which is the
    property that would otherwise manufacture a large correlation between two
    unrelated but persistent series.
    """
    x = np.asarray(x, float)
    n = len(x)
    mu = x.mean()
    f = np.fft.rfft(x - mu)
    ph = rng.uniform(0.0, 2.0 * np.pi, size=f.shape)
    ph[0] = 0.0
    if n % 2 == 0:
        ph[-1] = 0.0
    return np.fft.irfft(np.abs(f) * np.exp(1j * ph), n) + mu


def surrogate_null(
    x_weekly: pd.Series,
    y_weekly: pd.Series,
    lags: Sequence[int],
    cfg: LeadConfig,
    *,
    transform: str = "levels",
    draws: Optional[int] = None,
    rng: Optional[np.random.Generator] = None,
) -> Dict[str, object]:
    """Phase-randomised null -- the PERMISSIVE one. Report it beside
    :func:`shift_null`, never instead of it.

    Each surrogate replaces the surprise composite with a phase-randomised
    series of identical power spectrum, then is scored the way the real
    analysis is scored -- the maximum over every lag in the grid. Scoring a
    null at one fixed lag while the real number is a maximum over 27 would
    flatter the real number by exactly the amount the search is worth.

    Its size is not quoted here on purpose. Hard-coding a measured size in a
    docstring is how a number outlives the estimator it described -- this one
    read 8.3%/5.0%/9.2% while the rotations were sampled with replacement and
    the AR order was selected on a moving sample, and both of those were later
    fixed. Call :func:`measure_null_size`; the notebook does, in a cell, and
    prints Wilson intervals beside it.
    """
    rng = rng or cfg.rng(2)
    draws = draws or cfg.surrogate_draws
    lags = list(lags)
    joint = pd.concat([x_weekly.rename("x"), y_weekly.rename("y")], axis=1).dropna()
    xv = joint["x"].to_numpy(float)
    maxima, argmaxima = [], []
    for _ in range(draws):
        xs = pd.Series(phase_randomise(xv, rng), index=joint.index)
        xt, yt, _ = transform_pair(xs, joint["y"], transform)
        X, Y, _ = lag_matrix(xt, yt, lags)
        if len(Y) < 10:
            continue
        curve = np.array([_corr(X[:, j], Y) for j in range(X.shape[1])])
        if not np.isfinite(curve).any():
            continue
        maxima.append(float(np.nanmax(curve)))
        argmaxima.append(int(lags[int(np.nanargmax(curve))]))
    maxima = np.asarray(maxima, float)
    return {
        "max_corr": maxima,
        "argmax": np.asarray(argmaxima, int),
        "q50": float(np.quantile(maxima, 0.50)) if maxima.size else np.nan,
        "q95": float(np.quantile(maxima, 0.95)) if maxima.size else np.nan,
        "draws_used": int(maxima.size),
    }


def shift_null(
    x_weekly: pd.Series,
    y_weekly: pd.Series,
    lags: Sequence[int],
    cfg: LeadConfig,
    *,
    transform: str = "levels",
    draws: Optional[int] = None,
    rng: Optional[np.random.Generator] = None,
    min_offset: Optional[int] = None,
) -> Dict[str, object]:
    """The conservative null: keep both paths EXACTLY, destroy only alignment.

    Each draw rotates the surprise series circularly by a random offset and
    rescores the whole lag grid. Every surrogate therefore has the real
    series' trend, persistence, variance and marginal distribution -- only the
    correspondence with sentiment is broken.

    The rotation set is finite and is enumerated in full whenever it fits the
    draw budget, so the p-value is exact and its floor is reported as
    ``p_floor``. Sampling ~190 distinct rotations 1,500 times with replacement
    would let a p-value be quoted at 0.001 when the reference set cannot resolve
    below ~0.005; that is a real trap and it is closed here rather than noted.

    This exists because the obvious alternative, phase randomisation, wraps the
    path: it preserves the power spectrum but a surrogate therefore wanders less
    than a near-unit-root sample really does. What first motivated the switch was
    a single measured pair -- two *unrelated* AR(0.97) series cleared the phase
    null at p = 0.03 while the shift null absorbed them. Do not read that as the
    settled comparison: once the rotations were enumerated exactly and the AR
    order moved onto a common sample, the two nulls' measured sizes came out
    close. Call :func:`measure_null_size` for the current numbers rather than
    trusting any figure written into a docstring.
    """
    rng = rng or cfg.rng(3)
    draws = draws or cfg.surrogate_draws
    lags = list(lags)
    joint = pd.concat([x_weekly.rename("x"), y_weekly.rename("y")], axis=1).dropna()
    n = len(joint)
    min_offset = min_offset or (max(abs(min(lags)), abs(max(lags))) + 1)
    if n < 3 * min_offset:
        return {"max_corr": np.array([]), "argmax": np.array([]), "q50": np.nan,
                "q95": np.nan, "draws_used": 0, "exhaustive": False,
                "distinct_rotations": 0, "p_floor": np.nan}
    xv = joint["x"].to_numpy(float)
    maxima, argmaxima = [], []
    # The reference set is FINITE: only ``n - 2*min_offset`` distinct rotations
    # exist. Sampling it with replacement cannot make a p-value finer than
    # 1/(distinct+1), and quoting one that is finer claims a resolution the
    # surrogate set does not have. So enumerate the whole set when it fits in
    # the draw budget -- the test is then exact, and cheaper.
    candidates = np.arange(min_offset, n - min_offset, dtype=int)
    exhaustive = len(candidates) <= draws
    offsets = candidates if exhaustive else rng.choice(candidates, size=draws, replace=False)
    for d in offsets:
        xs = pd.Series(np.roll(xv, int(d)), index=joint.index)
        xt, yt, _ = transform_pair(xs, joint["y"], transform)
        X, Y, _ = lag_matrix(xt, yt, lags)
        if len(Y) < 10:
            continue
        curve = np.array([_corr(X[:, j], Y) for j in range(X.shape[1])])
        if not np.isfinite(curve).any():
            continue
        maxima.append(float(np.nanmax(curve)))
        argmaxima.append(int(lags[int(np.nanargmax(curve))]))
    maxima = np.asarray(maxima, float)
    return {
        "max_corr": maxima,
        "argmax": np.asarray(argmaxima, int),
        "q50": float(np.quantile(maxima, 0.50)) if maxima.size else np.nan,
        "q95": float(np.quantile(maxima, 0.95)) if maxima.size else np.nan,
        "draws_used": int(maxima.size),
        "exhaustive": bool(exhaustive),
        "distinct_rotations": int(len(candidates)),
        "p_floor": 1.0 / (maxima.size + 1) if maxima.size else np.nan,
    }


def surrogate_pvalue(observed_max: float, null: Dict[str, object]) -> float:
    m = np.asarray(null["max_corr"], float)
    if m.size == 0:
        return np.nan
    return float((1 + np.sum(m >= observed_max)) / (1 + m.size))


def plateau(curve: pd.DataFrame, boot_curves: np.ndarray, alpha: float = 0.05) -> List[int]:
    """Lags that a PAIRED bootstrap cannot separate from the peak.

    Two low-pass filtered series produce a broad plateau, and quoting only the
    argmax of a plateau claims a precision the data does not carry.

    The comparison has to be paired. Testing each lag's point estimate against
    the *marginal* bootstrap band of the peak ignores that the two correlations
    move together across draws -- they are computed from the same resampled
    rows -- so the marginal band is far wider than the distribution of their
    difference, and every plateau comes out too wide. Instead: within each
    bootstrap draw take ``peak_lag`` minus ``this_lag``, and keep the lag when
    the lower ``alpha`` quantile of that difference is at or below zero, i.e.
    when the draws do not consistently rank the peak above it.
    """
    vals = curve["corr"].to_numpy()
    j = int(np.nanargmax(vals))
    diff = boot_curves[:, [j]] - boot_curves          # (draws, lags), paired
    lo = np.nanquantile(diff, alpha, axis=0)
    return [int(l) for l, d in zip(curve["lag_weeks"], lo) if np.isfinite(d) and d <= 0.0]


# --------------------------------------------------------------------------
# turning points, regression helpers
# --------------------------------------------------------------------------
def turning_points(series: pd.Series, prominence: float) -> pd.DataFrame:
    """Algorithmic local extrema, both signs, above a prominence threshold.

    **Non-causal by construction.** ``find_peaks`` sees the whole series, so a
    turn here is only identifiable after the series has turned back. Use it to
    describe history -- which is what a chart's annotations do -- never as a
    signal. Nothing that feeds a p-value or a trade in this study reads it.
    """
    from scipy.signal import find_peaks

    s = pd.Series(series).dropna()
    v = s.to_numpy(float)
    hi, _ = find_peaks(v, prominence=prominence)
    lo, _ = find_peaks(-v, prominence=prominence)
    rows = [{"date": s.index[i], "value": float(v[i]), "kind": "peak"} for i in hi]
    rows += [{"date": s.index[i], "value": float(v[i]), "kind": "trough"} for i in lo]
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def newey_west_t(y: np.ndarray, x: np.ndarray, lag: int) -> Dict[str, float]:
    """OLS slope of ``y`` on ``x`` with a Newey-West HAC standard error.

    Overlapping forward-horizon regressions are the standard way to get a
    t-statistic that is two to three times too large; the HAC lag is set to the
    horizon so the overlap is paid for.
    """
    y = np.asarray(y, float)
    x = np.asarray(x, float)
    ok = np.isfinite(y) & np.isfinite(x)
    y, x = y[ok], x[ok]
    n = len(y)
    if n < 10:
        return {"beta": np.nan, "t": np.nan, "n": n, "r2": np.nan}
    Z = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(Z, y, rcond=None)
    resid = y - Z @ beta
    XtX_inv = np.linalg.inv(Z.T @ Z)
    S = (Z * resid[:, None]).T @ (Z * resid[:, None])
    for l in range(1, min(lag, n - 1) + 1):
        w = 1.0 - l / (lag + 1.0)
        A = (Z[l:] * resid[l:, None]).T @ (Z[:-l] * resid[:-l, None])
        S = S + w * (A + A.T)
    cov = XtX_inv @ S @ XtX_inv
    se = float(np.sqrt(max(cov[1, 1], 0.0)))
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = np.nan if ss_tot == 0 else 1.0 - float((resid**2).sum()) / ss_tot
    return {
        "beta": float(beta[1]),
        "t": float(beta[1] / se) if se > 0 else np.nan,
        "n": n,
        "r2": r2,
        "effective_n": float(n / max(lag, 1)),
    }


# --------------------------------------------------------------------------
# gates
# --------------------------------------------------------------------------
def gate_vintage(scores: pd.DataFrame, grid: pd.DatetimeIndex, cfg: LeadConfig) -> pd.DataFrame:
    """G1 -- what the publication gate removes, date by date.

    A gate that removes nothing is a gate that is not wired up, so the share
    removed is reported rather than asserted away.
    """
    rows = []
    s_date = scores["date"].to_numpy("datetime64[D]")
    p_date = scores["pub_date"].to_numpy("datetime64[D]")
    for t in grid:
        td = np.datetime64(t.date(), "D")
        naive = s_date <= td
        pit = naive & (p_date <= td)
        # the cumulative counts describe the corpus; the index only ever reads
        # rows inside the EWMA window, so the share removed THERE is the number
        # that actually changes a sentiment value
        age = (td - s_date).astype("timedelta64[D]").astype(int)
        inwin = naive & (age <= cfg.ewma_window_days)
        inwin_pit = inwin & (p_date <= td)
        n_naive, n_pit = int(naive.sum()), int(pit.sum())
        n_w, n_wp = int(inwin.sum()), int(inwin_pit.sum())
        rows.append(
            {
                "date": t,
                "n_as_published": n_naive,
                "n_point_in_time": n_pit,
                "n_removed": n_naive - n_pit,
                "share_removed": np.nan if n_naive == 0 else 1.0 - n_pit / n_naive,
                "n_in_window": n_w,
                "n_in_window_pit": n_wp,
                "share_removed_in_window": np.nan if n_w == 0 else 1.0 - n_wp / n_w,
            }
        )
    out = pd.DataFrame(rows).set_index("date")
    assert (out["n_point_in_time"] <= out["n_as_published"]).all(), (
        "G1 FAILED: the point-in-time count exceeds the as-published count"
    )
    assert out["n_removed"].sum() > 0, (
        "G1 FAILED: the publication gate removed nothing anywhere -- it is not wired up"
    )
    return out


def gate_no_pre_corpus(index: pd.Series, cfg: LeadConfig) -> None:
    """G2 -- the point-in-time series must be empty before the first report."""
    before = index[index.index < pd.Timestamp(cfg.corpus_start)]
    leaked = before.dropna()
    assert leaked.empty, (
        f"G2 FAILED: {len(leaked)} point-in-time observations before "
        f"{cfg.corpus_start} (first {leaked.index[0].date()}) -- the mask leaks"
    )


def gate_surprise_sanity(
    panel: pd.DataFrame, cfg: LeadConfig, *, min_nonzero: int = 100
) -> pd.DataFrame:
    """G3 -- coverage, non-zero-ness, and one shared frequency."""
    rows = []
    for tag in cfg.surprise_tags:
        s = panel[tag].dropna()
        nz = int((s != 0).sum())
        gaps = s.index.to_series().diff().dt.days.dropna()
        rows.append(
            {
                "tag": tag,
                "n": len(s),
                "n_nonzero": nz,
                "first": s.index.min(),
                "last": s.index.max(),
                "median_gap_days": float(gaps.median()) if len(gaps) else np.nan,
            }
        )
        assert nz > min_nonzero, (
            f"G3 FAILED: {tag} has {nz} non-zero observations -- an identically "
            f"zero sub-index must never enter an equal-weight average"
        )
    out = pd.DataFrame(rows)
    gaps = out["median_gap_days"].dropna().unique()
    assert len(gaps) == 1, (
        f"G3 FAILED: the legs do not share a frequency (median gaps {gaps}) -- "
        f"averaging a daily leg with a forward-filled monthly one makes the "
        f"turning points calendar artefacts"
    )
    return out


def gate_trailing_only(series: pd.Series, cfg: LeadConfig, *, probe_dates: Iterable) -> pd.DataFrame:
    """G5 -- recompute the z-score on truncated history and require equality.

    A trailing statistic has one testable property: truncating the series after
    ``t`` cannot change its value at ``t``. A full-sample statistic fails it.
    """
    rows = []
    for t in probe_dates:
        t = pd.Timestamp(t)
        truncated = trailing_z(
            series[series.index <= t], cfg.z_window_bd, cfg.z_min_periods
        )
        full = trailing_z(series, cfg.z_window_bd, cfg.z_min_periods)
        if t not in truncated.index or t not in full.index:
            continue
        a, b = truncated.loc[t], full.loc[t]
        rows.append({"date": t, "truncated": a, "full_history": b, "abs_diff": abs(a - b)})
    out = pd.DataFrame(rows)
    if not out.empty:
        worst = float(out["abs_diff"].max())
        assert worst < 1e-12, (
            f"G5 FAILED: the z-score at a date changes when later data is removed "
            f"(worst |diff| {worst:.3e}) -- it is not a trailing statistic"
        )
    return out

# --------------------------------------------------------------------------
# synthetic worlds, and the null's own calibration
# --------------------------------------------------------------------------
def ar1_path(n: int, phi: float, rng: np.random.Generator, scale: float = 1.0) -> np.ndarray:
    """One AR(1) path. Used only to build data whose answer is known."""
    e = rng.normal(scale=scale, size=n)
    out = np.empty(n)
    out[0] = e[0]
    for i in range(1, n):
        out[i] = phi * out[i - 1] + e[i]
    return out


def synthetic_world(
    *,
    lead_days: int,
    rng: np.random.Generator,
    years: int = 9,
    speech_years: int = 3,
    noise: float = 0.35,
    speeches_per_week: float = 3.3,
    cfg: Optional[LeadConfig] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, "LeadConfig"]:
    """A surprise panel and a speech book with a KNOWN lead between them.

    ``lead_days`` is the true lead of the surprise driver over the latent stance
    that speeches are drawn from. Everything downstream -- the trailing z-score,
    the weekly sampling, the EWMA over speeches -- is the production pipeline,
    unmodified, which is the point: pushing a *zero* lead through it is how the
    pipeline's own filter offset gets measured instead of assumed.

    This lives here rather than in the test file so that the notebook's
    calibration cell and ``test_pipeline_reports_a_lead_even_when_the_true_lead_is_zero``
    are the same construction, without the deliverable notebook importing from
    ``tests/``.

    ``speeches_per_week`` defaults to the JPM corpus's observed 3.3. The filter
    offset depends on how densely the response side is sampled, so a study on a
    corpus with a different density must recalibrate at ITS density rather than
    inherit this one -- the FedLock corpus runs at 2.52/week.
    """
    cfg = cfg or LeadConfig()
    days = pd.bdate_range("2016-01-01", periods=years * 261)
    driver = pd.Series(ar1_path(len(days), 0.985, rng, scale=1.0), index=days)

    panel = pd.DataFrame(
        {
            TAG_LABOUR: 10.0 * driver + rng.normal(scale=2.0, size=len(days)),
            TAG_PRICES: 10.0 * driver + rng.normal(scale=2.0, size=len(days)),
        },
        index=days,
    )
    panel.index.name = "date"

    latent = driver.copy()
    latent.index = latent.index + pd.Timedelta(days=lead_days)
    latent = latent.reindex(days.union(latent.index)).interpolate().reindex(days)

    speech_start = days[-speech_years * 261]
    candidates = days[days >= speech_start]
    n_speech = int(len(candidates) * float(speeches_per_week) / 5.0)
    picks = np.sort(rng.choice(len(candidates), size=n_speech, replace=False))
    sdates = candidates[picks]
    scores = 20.0 * latent.reindex(sdates).to_numpy() + rng.normal(
        scale=20.0 * noise, size=len(sdates)
    )
    book = pd.DataFrame(
        {
            "central_bank": "FED",
            "date": sdates,
            "pub_date": sdates,
            "speaker": [f"S{i % 12}" for i in range(len(sdates))],
            "hawk_dove_score": scores,
            "relevance_pct": 50.0,
        }
    )
    return panel, book, cfg


def wilson_interval(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for a proportion. Honest at small ``n``."""
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1.0 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((centre - half) / d, (centre + half) / d)


def measure_null_size(
    cfg: LeadConfig,
    *,
    transform: str,
    which: str = "shift",
    trials: int = 60,
    n_weeks: int = 170,
    phi: float = 0.97,
    seed: int = 1000,
    draws: int = 400,
) -> Dict[str, object]:
    """How often does the null reject when there is nothing to find?

    Two unrelated AR(``phi``) series, scored exactly as the real analysis scores
    them -- the maximum correlation over the whole lag grid -- ``trials`` times.
    The rejection rate at a nominal 5% is the null's actual size, and a
    p-value quoted against it should be read against that number rather than
    against 5%.

    Reported with a Wilson interval, because a size estimated on 60 or 120
    trials is itself an estimate: 6 rejections in 120 is consistent with a true
    size anywhere from about 2% to 11%.
    """
    lags = cfg.lags()
    rejected = 0
    for i in range(trials):
        rng = np.random.default_rng(seed + i)
        idx = pd.date_range("2023-05-05", periods=n_weeks, freq=cfg.week_anchor)
        a = pd.Series(ar1_path(n_weeks, phi, rng), index=idx)
        b = pd.Series(ar1_path(n_weeks, phi, rng), index=idx)
        at, bt, _ = transform_pair(a, b, transform)
        X, Y, _ = lag_matrix(at, bt, lags)
        obs = float(np.nanmax(lag_curve_common(X, Y, lags)["corr"].to_numpy()))
        fn = shift_null if which == "shift" else surrogate_null
        null = fn(a, b, lags, cfg, transform=transform, draws=draws,
                  rng=np.random.default_rng(seed + 5000 + i))
        rejected += surrogate_pvalue(obs, null) < 0.05
    lo, hi = wilson_interval(rejected, trials)
    return {
        "null": which,
        "transform": transform,
        "trials": trials,
        "rejected": rejected,
        "size": rejected / trials,
        "wilson_lo": lo,
        "wilson_hi": hi,
    }
