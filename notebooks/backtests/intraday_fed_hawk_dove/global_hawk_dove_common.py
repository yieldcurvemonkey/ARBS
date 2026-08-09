"""Plumbing for the GLOBAL (Fed / ECB / BOE / BOJ) intraday hawk-dove backtest.

The notebook keeps the config, the analytics and the plots. Everything that has a
right answer independent of presentation lives here so it can be tested directly.

Design notes that are NOT obvious and were established empirically (see the
_probe*.py scripts next to this file):

1. DIRECTION.  hawk = pay fixed = SELL the future; dove = receive fixed = BUY it.
   On the STIRFuture path the ONLY encoding that shorts is
       structure_kwargs={"bpv": +X, "risk_weights": [-1.0]}
   A negative ``bpv`` does NOT short: it flips the contract count, which flips
   BOTH the risk-weighted price and the PV01, and the position handler's
   ``(dprice/0.01) * pv01`` multiplies the two so the signs cancel and you get a
   LONG. Measured: SR3Z25 2025-11-20 10:00->14:00, price -0.0025, bpv=-100k
   returned -25,000 (identical to the long) while bpv=+100k with rw=[-1.0]
   returned +25,000 (correct short).

2. INTRADAY.  ``BaseQuery.build_mdp_request`` injects ``now.date()`` unless
   ``market_request`` carries the literal "now" sentinel. Without it every
   STIRFuture query prices off the daily bar and all same-day P&L is exactly
   zero. Every query built here sets market_request={"timestamp": "now"}.

3. LOOKAHEAD.  ``STIRFutureMDP.get_data`` serves the last bar at-or-before the
   request *while inside the session*, but when the request PRECEDES the day's
   first bar it serves a LATER bar - measured up to 335 minutes of lookahead.
   Every event is therefore gated on a real causal bar at both entry and exit
   (``gate_events``), which also pre-warms the minute cache.

4. TIMESTAMPS.  ``MDP._as_datetime`` tests ``type(ts) == datetime.datetime``, so a
   ``pd.Timestamp`` (a subclass) raises TypeError. All timestamps are plain.
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import pytz
import QuantLib as ql

from rateslib.scheduling import next_imm

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import Trigger, FlowSignalTriggerRequirements

from MDP.STIRFutures.STIRFutureMDP import (
    STIRFutureMDP,
    _normalize_symbol,
    _to_barchart_symbol,
)
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
from Query.STIRFutures.STIRFutureValue import STIRFutureValue

from RVUtils.forex_factory_calendar import ForexFactoryCalendarFetcher, ForexFactoryTheme

MONTH_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}


# ===========================================================================
# Per-central-bank configuration
# ===========================================================================
@dataclass(frozen=True)
class CBConfig:
    code: str
    label: str
    theme: ForexFactoryTheme
    root: str                      # STIR futures root, e.g. "SR3"
    curve_id: str                  # for central-bank meeting dates
    market_tz: str                 # tz the futures session is quoted in
    ql_calendar: Any               # business-day calendar for the market
    session_start: datetime.time   # local session bounds, from measured bars
    session_end: datetime.time
    ccy: str

    @property
    def tz(self):
        return pytz.timezone(self.market_tz)


def _ql_cal(name: str):
    return {
        "US": ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        "UK": ql.UnitedKingdom(ql.UnitedKingdom.Exchange),
        "EU": ql.TARGET(),
        "JP": ql.Japan(),
    }[name]


#: Session bounds are the measured minute-bar envelopes (see _probe_coverage.csv),
#: pulled in so an entry/exit at the edge still has a causal bar.
#:
#: ``session_end`` must sit STRICTLY INSIDE the quoted window, with margin. A
#: timestamp on the boundary resolves to the NEXT session inside the MDP, and
#: because exits are clamped to session_end that hits every late speech at once.
#: With FED session_end at exactly 17:00 ET, 31 of 496 Fed trades marked their
#: exit against the next day's price - the engine returned 95.615 where the day's
#: own bars ended at 95.54 (see _probe8_mark_mismatch.py). It is the same hazard
#: the Fed notebook's _cap_exit_to_valid_trading_date worked around by capping at
#: 16:59; a margin fixes it for every market rather than one.
CB_CONFIGS: Dict[str, CBConfig] = {
    "FED": CBConfig(
        code="FED", label="Federal Reserve", theme=ForexFactoryTheme.FED_SPEAKERS,
        root="SR3", curve_id="USD-SOFR-1D", market_tz="America/New_York",
        ql_calendar=_ql_cal("US"),
        session_start=datetime.time(7, 0), session_end=datetime.time(16, 45), ccy="USD",
    ),
    "ECB": CBConfig(
        code="ECB", label="ECB", theme=ForexFactoryTheme.ECB_SPEAKERS,
        # EB = CME 3M ESTR. Chosen over ICE's RA purely on measured bar density
        # (EB 121-473 bars/day vs RA 18-213 on the same dates).
        root="EB", curve_id="EUR-ESTR", market_tz="Europe/London",
        ql_calendar=_ql_cal("EU"),
        session_start=datetime.time(7, 0), session_end=datetime.time(20, 15), ccy="EUR",
    ),
    "BOE": CBConfig(
        code="BOE", label="Bank of England", theme=ForexFactoryTheme.BOE_SPEAKERS,
        root="J8", curve_id="GBP-SONIA", market_tz="Europe/London",
        ql_calendar=_ql_cal("UK"),
        session_start=datetime.time(7, 45), session_end=datetime.time(17, 30), ccy="GBP",
    ),
    "BOJ": CBConfig(
        code="BOJ", label="Bank of Japan", theme=ForexFactoryTheme.BOJ_SPEAKERS,
        # T0 = JPX 3M TONA. Barchart serves NOTHING for this root (or TFX's IT):
        # MDP.get_data raises "returned no data". Kept wired so the leg reports
        # its own emptiness rather than being silently dropped.
        root="T0", curve_id="JPY-TONA", market_tz="Asia/Tokyo",
        ql_calendar=_ql_cal("JP"),
        session_start=datetime.time(8, 45), session_end=datetime.time(18, 0), ccy="JPY",
    ),
}


# ===========================================================================
# Contract resolution
# ===========================================================================
def nth_quarterly_contract(root: str, ref: datetime.date, n: int) -> str:
    """The Nth listed quarterly contract as of ``ref`` - i.e. the futures analogue
    of the Fed notebook's ``IMM_3xIMM_4`` swap tenor.

    The seed is ``ref``, NOT ``ref + 1 day``. Seeding a day later reproduces
    ``Query.Base.imm_resolution.resolve_imm_token``, which rolls the contract one
    business day EARLY: on the Tuesday before an IMM Wednesday it has already
    jumped a whole quarter forward. Measured over 1,460 business days 2021-01-04
    to 2026-08-07 that is 22 days (1.5%), one per quarter, e.g. 2021-06-15 gives
    SR3H22 instead of SR3Z21. With this seed the function agrees with the repo's
    own futures alias resolver (``_resolve_aliases_bulk('SFRCM3', d)``) on all
    1,460 days.
    """
    imm = datetime.datetime(ref.year, ref.month, ref.day)
    for _ in range(n):
        imm = next_imm(imm)
    return f"{root}{MONTH_CODES[imm.month]}{str(imm.year)[-2:]}"


# ===========================================================================
# Central-bank blackout dates
# ===========================================================================
#: The registry (_CENTRAL_BANK_DATES) only reaches back to 2023-02 for EUR/GBP
#: and 2023-01 for JPY, but GBP futures data starts 2020-10. Without these the
#: 2021-2022 GBP sample would have NO blackout at all, quietly including every
#: MPC decision day. These are the published announcement dates.
_PRE2023_DECISIONS: Dict[str, List[datetime.date]] = {
    "BOE": [
        datetime.date(2021, 2, 4), datetime.date(2021, 3, 18), datetime.date(2021, 5, 6),
        datetime.date(2021, 6, 24), datetime.date(2021, 8, 5), datetime.date(2021, 9, 23),
        datetime.date(2021, 11, 4), datetime.date(2021, 12, 16),
        datetime.date(2022, 2, 3), datetime.date(2022, 3, 17), datetime.date(2022, 5, 5),
        datetime.date(2022, 6, 16), datetime.date(2022, 8, 4), datetime.date(2022, 9, 22),
        datetime.date(2022, 11, 3), datetime.date(2022, 12, 15),
    ],
    "ECB": [
        datetime.date(2021, 1, 21), datetime.date(2021, 3, 11), datetime.date(2021, 4, 22),
        datetime.date(2021, 6, 10), datetime.date(2021, 7, 22), datetime.date(2021, 9, 9),
        datetime.date(2021, 10, 28), datetime.date(2021, 12, 16),
        datetime.date(2022, 2, 3), datetime.date(2022, 3, 10), datetime.date(2022, 4, 14),
        datetime.date(2022, 6, 9), datetime.date(2022, 7, 21), datetime.date(2022, 9, 8),
        datetime.date(2022, 10, 27), datetime.date(2022, 12, 15),
    ],
    "BOJ": [
        datetime.date(2021, 1, 21), datetime.date(2021, 3, 19), datetime.date(2021, 4, 27),
        datetime.date(2021, 6, 18), datetime.date(2021, 7, 16), datetime.date(2021, 9, 22),
        datetime.date(2021, 10, 28), datetime.date(2021, 12, 17),
        datetime.date(2022, 1, 18), datetime.date(2022, 3, 18), datetime.date(2022, 4, 28),
        datetime.date(2022, 6, 17), datetime.date(2022, 7, 21), datetime.date(2022, 9, 22),
        datetime.date(2022, 10, 28), datetime.date(2022, 12, 20),
    ],
}


def decision_dates(cfg: CBConfig) -> List[datetime.date]:
    """Policy decision dates for this bank, registry first, pre-2023 supplement second."""
    from Query.IRSwaps._CENTRAL_BANK_DATES import central_bank_date_map

    out: set[datetime.date] = set()
    try:
        for eff, _mat in central_bank_date_map(cfg.curve_id).values():
            d = eff.date() if isinstance(eff, datetime.datetime) else eff
            out.add(d)
    except Exception:  # noqa: BLE001
        pass
    out.update(_PRE2023_DECISIONS.get(cfg.code, []))
    return sorted(out)


def make_blackout_fn(cfg: CBConfig, blackout_bd: int) -> Callable[[datetime.date], bool]:
    dates = decision_dates(cfg)
    cal = cfg.ql_calendar
    windows: List[tuple[datetime.date, datetime.date]] = []
    for d in dates:
        q = ql.Date(d.day, d.month, d.year)
        lo = cal.advance(q, ql.Period(-blackout_bd, ql.Days), ql.Preceding)
        hi = cal.advance(q, ql.Period(blackout_bd, ql.Days), ql.Following)
        windows.append(
            (datetime.date(lo.year(), lo.month(), lo.dayOfMonth()),
             datetime.date(hi.year(), hi.month(), hi.dayOfMonth()))
        )

    def _fn(d: datetime.date) -> bool:
        return any(lo <= d <= hi for lo, hi in windows)

    return _fn


# ===========================================================================
# Scores
# ===========================================================================
def load_global_scores(path: str, score_metric: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.sort_values(["central_bank", "speaker", "date"]).reset_index(drop=True)


class ScoreLookup:
    """Most recent score for a speaker STRICTLY BEFORE a date.

    Strict ``<`` matters: ``trailing_5_avg`` stamped on date X already contains
    speech X's own hawk-dove score, which does not exist until the speech is over.
    """

    def __init__(self, scores: pd.DataFrame, bank: str, score_metric: str):
        self._cache: Dict[str, tuple] = {}
        sub = scores[scores["central_bank"] == bank]
        for speaker, grp in sub.groupby("speaker"):
            g = grp.sort_values("date")
            self._cache[speaker] = (
                np.array([np.datetime64(d) for d in g["date"]]),
                g[score_metric].to_numpy(dtype=float),
            )

    def speakers(self) -> set:
        return set(self._cache)

    def get(self, speaker: str, as_of: datetime.date) -> float:
        if speaker not in self._cache:
            return np.nan
        dates, vals = self._cache[speaker]
        mask = dates < np.datetime64(as_of)
        if not mask.any():
            return np.nan
        v = vals[mask][-1]
        return float(v) if v == v else np.nan


def absolute_bucket(score: float, hi: float = 20.0, lo: float = 10.0) -> int:
    """Fed convention, applied unchanged to every bank."""
    if score is None or score != score:
        return 0
    if score >= hi:
        return 2
    if score >= lo:
        return 1
    if score > -lo:
        return 0
    if score > -hi:
        return -1
    return -2


#: Percentile cutoffs -> bucket. By construction this splits each bank's own
#: history ~40% hawk / ~40% dove / ~20% neutral, whatever that bank's scale is.
PERCENTILE_EDGES = ((0.80, 2), (0.60, 1), (0.40, 0), (0.20, -1))


def make_percentile_bucketer(
    scores: pd.DataFrame,
    bank: str,
    score_metric: str,
    *,
    min_history: int = 30,
    window_obs: Optional[int] = 60,
    edges: Sequence[tuple] = PERCENTILE_EDGES,
) -> Callable[[str, float, datetime.date], int]:
    """Rank a score inside that BANK's OWN prior distribution, then bucket.

    Why this and not the Fed's absolute +-10/+-20 cutoffs: the JPM hawk-dove
    scale is not comparable across banks. Measured medians of ``trailing_5_avg``
    are FED ~+7, ECB +10, BOE +15, BOJ -23. Absolute cutoffs would therefore
    label almost every BOE speech a hawk and almost every BOJ speech a dove,
    turning those legs into a constant directional bet on the level of rates -
    which is a bet on the sample, not on the label.

    A qualitative hawk/dove read should be roughly evenly split within a bank, so
    the score is converted to its percentile against that bank's history and
    bucketed on percentile. Two properties matter:

      - scale-free: an offset or rescale of one bank's scores changes nothing;
      - no lookahead: the reference distribution uses ONLY observations strictly
        before the speech date, so an early trade is ranked against what was
        actually knowable then.

    ``window_obs`` is a TRAILING window, not an expanding one, and that choice is
    what actually delivers the even split. Ranked against ALL prior history, the
    Fed's 2025-26 speeches are compared to the very hawkish 2022-23 era and come
    out 26% hawk / 52% dove - the drift in the level leaks back in as a
    directional tilt. Measured hawk/dove balance by window (FED, ECB, BOE):
        expanding  26/52, 21/58, 29/34
        60 obs     39/40, 41/37, 32/38     <- chosen
        200 obs    34/45, 36/44, 29/34
    60 was chosen on LABEL BALANCE ALONE, before any P&L was computed.

    The distribution is pooled ACROSS speakers within the bank, deliberately.
    Ranking each speaker against only themselves would erase the cross-sectional
    information (that Pill is hawkish and Dhingra is not), which is the part of
    the label with any content.
    """
    sub = scores[scores["central_bank"] == bank].sort_values("date")
    dates = np.array([np.datetime64(d) for d in sub["date"]])
    vals = sub[score_metric].to_numpy(dtype=float)

    def _fn(_speaker: str, score: float, as_of: datetime.date) -> int:
        if score is None or score != score:
            return 0
        hist = vals[dates < np.datetime64(as_of)]
        hist = hist[~np.isnan(hist)]
        if len(hist) < min_history:
            return 0
        if window_obs:
            hist = hist[-window_obs:]
        # Mid-rank percentile: ties (the scores are integers, so ties are common)
        # sit at the centre of their block instead of all landing on one side.
        pct = (float((hist < score).sum()) + 0.5 * float((hist == score).sum())) / len(hist)
        for cutoff, bucket in edges:
            if pct >= cutoff:
                return bucket
        return -2

    return _fn


def bucket_split(
    scores: pd.DataFrame, bank: str, score_metric: str, bucket_fn
) -> pd.Series:
    """Realised bucket distribution for a bank - the check that the split is even."""
    sub = scores[scores["central_bank"] == bank].sort_values("date")
    b = [bucket_fn(r["speaker"], r[score_metric], r["date"]) for _, r in sub.iterrows()]
    return pd.Series(b).value_counts(normalize=True).sort_index()


# ===========================================================================
# Events
# ===========================================================================
_SPEAKER_STRIP = re.compile(r"\b(Speaks?|Testifies|Testimony)\b")


def extract_speaker(title: str) -> str:
    """Last name from a ForexFactory title. Verified against all four title
    families: 'FOMC Member Cook Speaks', 'ECB President Lagarde Speaks',
    'MPC Member Pill Speaks', 'BOJ Gov Ueda Speaks'."""
    cleaned = _SPEAKER_STRIP.sub("", title or "").strip()
    parts = cleaned.split()
    return parts[-1] if parts else ""


def _plain_dt(ts) -> datetime.datetime:
    """MDP._as_datetime uses ``type(ts) == datetime.datetime``; a pd.Timestamp is
    a subclass and is REJECTED. Everything handed downstream must be plain."""
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    return datetime.datetime(ts.year, ts.month, ts.day, ts.hour, ts.minute,
                             ts.second, tzinfo=ts.tzinfo)


def fetch_events(cfg: CBConfig, start: str, end: str, show_tqdm: bool = False) -> pd.DataFrame:
    fetcher = ForexFactoryCalendarFetcher()
    return fetcher.fetch_range(start, end, themes=[cfg.theme],
                               show_tqdm=show_tqdm, bulk_chunk_weeks=52)


def build_trade_events(
    cfg: CBConfig,
    events_df: pd.DataFrame,
    lookup: ScoreLookup,
    *,
    entry_offset: datetime.timedelta,
    exit_offset: datetime.timedelta,
    base_bpv: float,
    contract_rank: int,
    bucket_fn: Callable[[str, float, datetime.date], int],
    blackout_fn: Callable[[datetime.date], bool],
    eligible_speakers: Optional[set] = None,
) -> tuple[List[dict], Dict[str, int]]:
    """Filter calendar events down to sized, directional trade intents.

    Entry/exit are clamped into the market's measured session; the empirical
    data gate (``gate_events``) is what finally decides tradeability.
    """
    tz = cfg.tz
    excluded: Dict[str, int] = defaultdict(int)
    out: List[dict] = []
    eligible = eligible_speakers if eligible_speakers is not None else lookup.speakers()

    for _, row in events_df.iterrows():
        title = row.get("Title") or ""
        speaker = extract_speaker(title)
        if speaker not in eligible:
            excluded["unknown_speaker"] += 1
            continue

        ts = row.get("TimestampNYC")
        if pd.isna(ts):
            excluded["no_timestamp"] += 1
            continue
        ts = pd.Timestamp(ts)
        if ts.tzinfo is None:
            ts = ts.tz_localize("America/New_York")
        speech_ts = _plain_dt(ts.tz_convert(tz))       # LOCAL market time
        speech_date = speech_ts.date()

        if "press conference" in title.lower():
            excluded["press_conference"] += 1
            continue

        if not cfg.ql_calendar.isBusinessDay(
            ql.Date(speech_date.day, speech_date.month, speech_date.year)
        ):
            excluded["not_business_day"] += 1
            continue

        if blackout_fn(speech_date):
            excluded["policy_blackout"] += 1
            continue

        raw_score = lookup.get(speaker, speech_date)
        bucket = bucket_fn(speaker, raw_score, speech_date)
        if bucket == 0:
            excluded["neutral_or_no_score"] += 1
            continue

        entry_ts = speech_ts + entry_offset
        exit_ts = speech_ts + exit_offset

        # Clamp into the measured session on the SPEECH day.
        day_open = speech_ts.replace(hour=cfg.session_start.hour,
                                     minute=cfg.session_start.minute, second=0, microsecond=0)
        day_close = speech_ts.replace(hour=cfg.session_end.hour,
                                      minute=cfg.session_end.minute, second=0, microsecond=0)
        if entry_ts < day_open:
            entry_ts = day_open
        if exit_ts > day_close:
            exit_ts = day_close

        if exit_ts - entry_ts < datetime.timedelta(minutes=30):
            excluded["window_too_short"] += 1
            continue
        if not (day_open <= entry_ts < day_close):
            excluded["entry_outside_session"] += 1
            continue

        symbol = nth_quarterly_contract(cfg.root, speech_date, contract_rank)

        out.append({
            "bank": cfg.code,
            "ccy": cfg.ccy,
            "event_id": row.get("EventId", len(out)),
            "speaker": speaker,
            "title": title,
            "symbol": symbol,
            "speech_ts": speech_ts,
            "entry_ts": entry_ts,
            "exit_ts": exit_ts,
            "raw_score": raw_score,
            "bucket": bucket,
            "bpv": abs(bucket) * base_bpv,      # magnitude only ...
            "side": -1.0 if bucket > 0 else 1.0,  # ... direction lives here
            "tag": f"{cfg.code}_{row.get('EventId', len(out))}",
        })

    return out, dict(excluded)


def drop_overlaps(events: List[dict]) -> tuple[List[dict], int]:
    """One position at a time per bank, chronological."""
    events = sorted(events, key=lambda e: e["entry_ts"])
    kept: List[dict] = []
    last_exit = None
    dropped = 0
    for ev in events:
        if last_exit is not None and ev["entry_ts"] < last_exit:
            dropped += 1
            continue
        kept.append(ev)
        last_exit = ev["exit_ts"]
    return kept, dropped


# ===========================================================================
# Empirical data gate
# ===========================================================================
#: Shared across every gate_events call in the process. The entry/exit sweep
#: re-gates the SAME (symbol, day) pairs 20 times over - without this the grid
#: refetches every bar 20x and hammers Barchart's rate limit for no new data.
_BAR_CACHE: Dict[tuple, pd.DataFrame] = {}


def save_bar_cache(path) -> int:
    """Persist the minute-bar cache so a fresh process (the notebook) does not
    re-fetch what the runner already pulled."""
    import pickle
    with open(path, "wb") as f:
        pickle.dump(_BAR_CACHE, f)
    return len(_BAR_CACHE)


def load_bar_cache(path) -> int:
    import pickle
    from pathlib import Path as _P
    if not _P(path).exists():
        return 0
    with open(path, "rb") as f:
        _BAR_CACHE.update(pickle.load(f))
    return len(_BAR_CACHE)


def _day_bars(fetcher, symbol: str, day: datetime.date, tz) -> pd.DataFrame:
    start = tz.localize(datetime.datetime(day.year, day.month, day.day, 0, 0))
    end = tz.localize(datetime.datetime(day.year, day.month, day.day, 23, 59))
    bc = _to_barchart_symbol(_normalize_symbol(symbol) or symbol)
    try:
        per = fetcher.barchart_timeseries_api(
            barchart_symbols=[bc], start_date=start, end_date=end,
            interval=1, one_df=False, show_tqdm=False,
        ) or {}
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    for _k, v in per.items():
        if v is not None and len(v):
            df = v.copy()
            if getattr(df.index, "tz", None) is not None:
                df.index = df.index.tz_convert(tz)
            return df
    return pd.DataFrame()


def gate_events(
    events: List[dict],
    cfg: CBConfig,
    mdp: STIRFutureMDP,
    *,
    max_staleness_min: int = 45,
    show_progress: bool = True,
) -> tuple[List[dict], Dict[str, int], pd.DataFrame]:
    """Keep only events with a genuine CAUSAL bar at both entry and exit.

    This is not belt-and-braces. ``STIRFutureMDP.get_data`` serves a LATER bar
    when the request precedes the session's first bar (measured: up to 335
    minutes of lookahead), and a missing bar at exit orphans the position instead
    of raising. Gating converts both failure modes into logged exclusions, and
    fetching each (symbol, day) once here also warms the cache that the backtest,
    the entry/exit heatmap and the contract sweep all read.
    """
    fetcher = mdp._get_barchart_fetcher(required_concurrency=6)
    tz = cfg.tz
    cache = _BAR_CACHE
    reasons: Dict[str, int] = defaultdict(int)
    kept: List[dict] = []
    diag: List[dict] = []

    iterator = events
    if show_progress:
        try:
            from tqdm.auto import tqdm
            iterator = tqdm(events, desc=f"gate {cfg.code}")
        except Exception:  # noqa: BLE001
            pass

    for ev in iterator:
        day = ev["entry_ts"].date()
        key = (ev["symbol"], day)
        if key not in cache:
            cache[key] = _day_bars(fetcher, ev["symbol"], day, tz)
        bars = cache[key]

        rec = {"bank": cfg.code, "symbol": ev["symbol"], "date": day,
               "speaker": ev["speaker"], "bars": len(bars)}

        if bars.empty:
            reasons["no_bars_that_day"] += 1
            rec["reason"] = "no_bars_that_day"
            diag.append(rec)
            continue

        idx = bars.index
        e_prior = idx[idx <= ev["entry_ts"]]
        x_prior = idx[idx <= ev["exit_ts"]]

        if len(e_prior) == 0:
            reasons["entry_before_first_bar"] += 1   # would LOOK AHEAD
            rec["reason"] = "entry_before_first_bar"
            diag.append(rec)
            continue
        if len(x_prior) == 0:
            reasons["exit_before_first_bar"] += 1
            rec["reason"] = "exit_before_first_bar"
            diag.append(rec)
            continue

        e_bar, x_bar = e_prior.max(), x_prior.max()
        e_stale = (ev["entry_ts"] - e_bar).total_seconds() / 60.0
        x_stale = (ev["exit_ts"] - x_bar).total_seconds() / 60.0
        rec.update({"entry_stale_min": round(e_stale, 1),
                    "exit_stale_min": round(x_stale, 1)})

        if e_stale > max_staleness_min or x_stale > max_staleness_min:
            reasons["stale_quote"] += 1
            rec["reason"] = "stale_quote"
            diag.append(rec)
            continue
        if e_bar == x_bar:
            reasons["same_bar_entry_exit"] += 1      # would book a fake zero
            rec["reason"] = "same_bar_entry_exit"
            diag.append(rec)
            continue

        ev = dict(ev)
        ev["entry_bar"] = e_bar
        ev["exit_bar"] = x_bar
        ev["entry_bar_px"] = float(bars.loc[e_bar, "Close"])
        ev["exit_bar_px"] = float(bars.loc[x_bar, "Close"])
        rec["reason"] = "ok"
        diag.append(rec)
        kept.append(ev)

    return kept, dict(reasons), pd.DataFrame(diag)


# ===========================================================================
# Backtest
# ===========================================================================
def make_query(ev: dict) -> STIRFutureQuery:
    """One rateslib STIRFuture outright, sized in bpv, direction in risk_weights.

    ``risk_weights=[side]`` is the ONLY correct way to short here - see the module
    docstring. ``market_request={"timestamp": "now"}`` is what makes it intraday.
    """
    return STIRFutureQuery(
        structure=STIRFutureStructure.OUTRIGHT,
        value=STIRFutureValue.PRICE,
        symbol=ev["symbol"],
        structure_kwargs={"bpv": float(ev["bpv"]), "risk_weights": [float(ev["side"])]},
        market_request={"timestamp": "now"},
        tags=(ev["tag"],),
        meta={
            "bank": ev["bank"], "ccy": ev["ccy"], "speaker": ev["speaker"],
            "bucket": ev["bucket"], "raw_score": ev["raw_score"],
            "symbol": ev["symbol"], "side": ev["side"], "bpv": ev["bpv"],
            "speech_ts": ev["speech_ts"],
        },
    )


def run_backtest(events: List[dict], mdp: STIRFutureMDP, *, name: str,
                 show_progress: bool = True) -> pd.DataFrame:
    if not events:
        return pd.DataFrame()

    exit_set = {ev["exit_ts"] for ev in events}
    all_ts = sorted({ev["entry_ts"] for ev in events} | exit_set)

    triggers = [
        Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(
                signal_fn=lambda s, bt, _e=exit_set: s in _e
            ),
            actions=[UnwindPositionsAction(match_all=True, fee=0.0)],
        )
    ]
    for ev in events:
        def _mk(ts):
            def fn(state, backtest):
                return state == ts and len(backtest.portfolio.positions) == 0
            return fn

        triggers.append(
            Trigger(
                trigger_requirements=FlowSignalTriggerRequirements(signal_fn=_mk(ev["entry_ts"])),
                actions=[AddQueryAction(query=make_query(ev))],
            )
        )

    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(all_ts),
        mdp=mdp,
        strategy=QueryStrategy(name=name, triggers=triggers),
        show_progress=show_progress,
        progress_desc=name,
    )
    bt.run()

    closed = pd.DataFrame(bt.portfolio.closed_positions_log)
    if closed.empty:
        return closed
    return enrich_closed(closed)


def enrich_closed(closed: pd.DataFrame) -> pd.DataFrame:
    closed = closed.copy()
    m = closed["source_query"].apply(lambda q: q.meta or {})
    for k in ("bank", "ccy", "speaker", "bucket", "raw_score", "symbol", "side", "bpv"):
        closed[k] = m.apply(lambda d, _k=k: d.get(_k))
    closed["opened_at"] = pd.to_datetime(closed["opened_at"])
    closed["closed_at"] = pd.to_datetime(closed["closed_at"])
    closed["year"] = closed["opened_at"].dt.year
    closed["direction"] = np.where(closed["bucket"] > 0, "hawk (short fut)", "dove (long fut)")
    closed["profitable"] = closed["realized_pnl"] > 0
    # Currency-free: realized_pnl / bpv is literally the bp of favourable move,
    # which is the only unit in which USD, EUR and GBP trades can be pooled.
    closed["pnl_bp"] = closed["realized_pnl"] / closed["bpv"]
    closed["abs_bucket"] = closed["bucket"].abs()
    return closed


# ===========================================================================
# Metrics
# ===========================================================================
def summarize(closed: pd.DataFrame, pnl_col: str = "pnl_bp") -> Dict[str, float]:
    if closed.empty:
        return {"trades": 0}
    p = closed[pnl_col]
    n = len(closed)
    span_days = (closed["opened_at"].max() - closed["opened_at"].min()).days
    years = max(span_days / 365.25, 1e-9)
    tpy = n / years if years > 0 else n
    std = p.std()
    sharpe = (p.mean() / std * np.sqrt(tpy)) if std and std > 0 else 0.0
    cum = p.cumsum()
    dd = (cum - cum.cummax()).min()
    return {
        "trades": n,
        "total": p.sum(),
        "avg": p.mean(),
        "std": std,
        "hit_rate": (p > 0).mean(),
        "sharpe": sharpe,
        "max_dd": dd,
        "trades_per_year": tpy,
        "t_stat": (p.mean() / (std / np.sqrt(n))) if std and std > 0 else 0.0,
        "first": closed["opened_at"].min(),
        "last": closed["opened_at"].max(),
    }


def rebuild_with_offsets(
    events: List[dict],
    cfg: CBConfig,
    entry_offset: datetime.timedelta,
    exit_offset: datetime.timedelta,
) -> List[dict]:
    """Re-time an already-gated event list. Session clamping is re-applied, so a
    wider exit offset cannot silently walk past the last bar of the day."""
    out: List[dict] = []
    for ev in events:
        s = ev["speech_ts"]
        entry_ts = s + entry_offset
        exit_ts = s + exit_offset
        day_open = s.replace(hour=cfg.session_start.hour,
                             minute=cfg.session_start.minute, second=0, microsecond=0)
        day_close = s.replace(hour=cfg.session_end.hour,
                              minute=cfg.session_end.minute, second=0, microsecond=0)
        entry_ts = max(entry_ts, day_open)
        exit_ts = min(exit_ts, day_close)
        if exit_ts - entry_ts < datetime.timedelta(minutes=30):
            continue
        e = dict(ev)
        e["entry_ts"] = entry_ts
        e["exit_ts"] = exit_ts
        out.append(e)
    return drop_overlaps(out)[0]


def rebuild_with_contract(events: List[dict], cfg: CBConfig, rank: int) -> List[dict]:
    out = []
    for ev in events:
        e = dict(ev)
        e["symbol"] = nth_quarterly_contract(cfg.root, ev["speech_ts"].date(), rank)
        out.append(e)
    return out


def sweep(
    events_by_bank: Dict[str, List[dict]],
    mdp: STIRFutureMDP,
    variants: Dict[str, Callable[[str, List[dict]], List[dict]]],
    *,
    gate: bool = True,
    max_staleness_min: int = 45,
) -> pd.DataFrame:
    """Run a family of re-parameterised backtests and summarise each.

    ``gate=True`` re-applies the causal-bar gate, which matters whenever the
    variant MOVES the entry/exit times: a wider window can land outside the
    session, and an ungated re-run would silently mark those against a
    lookahead bar rather than dropping them.
    """
    rows = []
    for name, fn in variants.items():
        per_bank = []
        for bank, evs in events_by_bank.items():
            cfg = CB_CONFIGS[bank]
            new_evs = fn(bank, evs)
            if not new_evs:
                continue
            if gate:
                new_evs, _r, _d = gate_events(
                    new_evs, cfg, mdp, max_staleness_min=max_staleness_min,
                    show_progress=False,
                )
            if not new_evs:
                continue
            cl = run_backtest(new_evs, mdp, name=f"{name}_{bank}", show_progress=False)
            if not cl.empty:
                per_bank.append(cl)
        if not per_bank:
            rows.append({"variant": name, "trades": 0})
            continue
        pooled = pd.concat(per_bank, ignore_index=True).sort_values("opened_at")
        s = summarize(pooled)
        s["variant"] = name
        rows.append(s)
    return pd.DataFrame(rows)


def sign_flip_permutation(closed: pd.DataFrame, n_perm: int = 2000, seed: int = 42,
                          pnl_col: str = "pnl_bp") -> Dict[str, float]:
    """Null = the labels carried no direction. Preserves each trade's realised
    move and randomises only the side."""
    if closed.empty:
        return {}
    rng = np.random.default_rng(seed)
    p = closed[pnl_col].to_numpy(dtype=float)
    n = len(p)
    years = max((closed["opened_at"].max() - closed["opened_at"].min()).days / 365.25, 1e-9)
    tpy = n / years

    def _sr(x):
        s = x.std()
        return (x.mean() / s * np.sqrt(tpy)) if s > 0 else 0.0

    realized = _sr(p)
    perm = np.empty(n_perm)
    for i in range(n_perm):
        perm[i] = _sr(p * rng.choice([-1.0, 1.0], size=n))
    return {
        "realized_sharpe": realized,
        "perm_mean": perm.mean(),
        "perm_std": perm.std(),
        "p_value": float((perm >= realized).mean()),
        "perm": perm,
    }
