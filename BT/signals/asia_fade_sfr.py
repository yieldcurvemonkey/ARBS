"""Asia Fade SFR — query-driven, event-driven backtest.

Hypothesis
----------
Directional moves in the SOFR strip during the Asia session tend to reverse
during the subsequent NY session.

Architecture (follows the repo's BT conventions used by
``notebooks/backtests/intraday_fed_hawk_dove`` and
``notebooks/backtests/intraday_*_q12stirt_query_backtest`` notebooks):

    IRSwapsMDP(source="BARCHART_STIRF-RL")
        + UnifiedQuery(curve="USD-SOFR-1D-Q12STIRT", tenor="IMM_NxIMM_{N+1}",
                       value=UnifiedValue.IRS_RATE)
        for intraday rate sampling

    TimeGrid([entry_ts, exit_ts, ...])           — sparse, one slot per event
    QueryStrategy(triggers=[exit_trigger] + [entry_triggers])
    QueryDrivenBacktest(...).run()

Per (trade_date D, tenor):
    signal_open_rate  = rate at signal_start_hhmm ET on D   (default 17:00 = 5pm)
    signal_close_rate = rate at signal_end_hhmm   ET on D   (default 22:00 = 10pm)
    entry_rate        = rate at entry_hhmm        ET on D   (default 22:00)
    exit_rate         = rate at exit_hhmm         ET on D + exit_day_offset bd
                                                            (default 08:00 next bd)
    signal_move_bp    = (signal_close_rate - signal_open_rate) * 100   # rate is in %

Fade rule (sign convention: positive signal_move_bp = rates rose during signal):
    bpv = -sign(signal_move_bp) * base_bpv_usd
            > 0 → REC (profits if rates fall back overnight) when rates rose 5-10pm
            < 0 → PAY (profits if rates rise back overnight) when rates fell 5-10pm

Entry order   = IRSwapQuery(tenor, value=IRSwapValue.NPV, structure_kwargs={"bpv": bpv})
Exit          = UnwindPositionsAction(match_tag="asia_fade", fee=cost_per_trade)

Config is dict-like (``AsiaFadeConfig`` implements ``collections.abc.Mapping``)
so the backtest can be re-parametrized for different curves/contracts:

    cfg = {
        "curve": "USD-SOFR-1D-Q12STIRT",
        "tenors": ["IMM_1xIMM_2", "IMM_5xIMM_6", "IMM_9xIMM_10"],
        "start": "2024-01-01",
        "end":   "2026-05-14",
    }
    bt, trades = run_asia_fade(cfg)

Q12STIRT has 12 quarterly knots → IMM_1xIMM_2 through IMM_12xIMM_13
(whites / reds / greens).  For blues use a longer curve (or a SR3 contract
code tenor like "IMM_H29xIMM_M29") and supply it via the config.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping as MappingT, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
import pytz

# Ensure repo root is on sys.path so imports work whether invoked as module or script.
_REPO_ROOT = Path(r"C:\Users\chris\clee\ARBS")
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import FlowSignalTriggerRequirements, Trigger

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.Unified.UnifiedQuery import UnifiedQuery
from Query.Unified.registry import UnifiedValue
from TB.IRSwapsTB import IRSwapsTB
from TB.TimeseriesBuilder import TimeseriesBuilder

logger = logging.getLogger(__name__)

NY_TZ = pytz.timezone("America/New_York")
TRADE_TAG = "asia_fade"

# ────────────────────────────── Configuration ─────────────────────────────

SECTORS: Dict[str, Tuple[int, int]] = {
    "whites": (1, 4),
    "reds":   (5, 8),
    "greens": (9, 12),
    "blues":  (13, 16),
}


def _default_tenors_ranks_1_to_12() -> List[str]:
    return [f"IMM_{i}xIMM_{i + 1}" for i in range(1, 13)]


@dataclass
class AsiaFadeConfig(Mapping):
    """Dict-like config for the Asia fade backtest.

    Implements ``collections.abc.Mapping`` so it can be consumed wherever a
    dict is expected.  Build from a plain dict via ``AsiaFadeConfig.from_dict(d)``
    or construct directly.

    The ``curve`` + ``tenors`` pair is the only thing you need to change in
    order to point the backtest at a different STIR contract universe:

        # SOFR ranks 1-12 (whites/reds/greens) — default
        cfg = AsiaFadeConfig()

        # SOFR whites only, named SR3 contracts
        cfg = AsiaFadeConfig.from_dict({
            "curve":  "USD-SOFR-1D-Q12STIRT",
            "tenors": ["IMM_M26xIMM_U26", "IMM_U26xIMM_Z26",
                       "IMM_Z26xIMM_H27", "IMM_H27xIMM_M27"],
        })

        # CORRA Q8 strip
        cfg = AsiaFadeConfig.from_dict({
            "curve":  "CAD-CORRA-Q8STIRT",
            "tenors": [f"IMM_{i}xIMM_{i+1}" for i in range(1, 8)],
            "mdp_source": "BARCHART_STIRF-RL",
        })
    """

    # ---- Market data ----
    mdp_source: str = "BARCHART_STIRF-RL"
    curve: str = "USD-SOFR-1D-Q12STIRT"
    tenors: List[str] = field(default_factory=_default_tenors_ranks_1_to_12)

    # ---- Backtest window ----
    start: str = "2023-05-01"          # ISO date
    end:   str = "2026-05-14"

    # ---- Session / event timing (all 24h ET) ----
    # The strategy: observe the rate move during [signal_start, signal_end]
    # on day D, then fade by entering at entry_ts (also on D, by default the
    # same as signal_end) and exit at exit_ts on day (D + exit_day_offset).
    # All four timestamps reference the SAME calendar trade-date D except for
    # exit_ts which can be on the next business day.
    signal_start_hhmm: Tuple[int, int] = (17, 0)   # 5pm ET (NY close / Asia takes over)
    signal_end_hhmm:   Tuple[int, int] = (22, 0)   # 10pm ET (mid Asia)
    entry_hhmm:        Tuple[int, int] = (22, 0)   # 10pm ET — fade the 5pm→10pm move
    exit_hhmm:         Tuple[int, int] = (8,  0)   # 08:00 ET next morning
    exit_day_offset:   int = 1                     # 0 = same day, 1 = next business day

    # ---- Sampling ----
    bar_freq: str = "5min"             # passed to TimeseriesBuilder.get_timeseries
    sample_tolerance_min: int = 30     # max look-back if exact bar missing

    # ---- Sizing & costs ----
    base_bpv_usd: float = 100_000.0    # DV01 in $ per unit signal direction
    bid_ask_bp_rt:        float = 0.5  # round-trip bid-ask in BP (0.5 ≈ 1 tick on SR3)
    commission_per_side_usd: float = 0.50
    slippage_bp_rt:       float = 0.0

    # ---- Signal gating ----
    min_signal_move_bp: float = 0.0    # only trade signal moves >= this size (bp)

    # ---- Signal polarity ----
    # "fade"     → take the OPPOSITE side of the Asia move (default — the
    #              hypothesis under test).  Asia rates up → take RECEIVER.
    # "momentum" → take the SAME side (continuation).
    # IRSwapQuery resolves the swap to a fixed direction (PAYER, profits as
    # rates rise) regardless of bpv sign, so we apply this multiplier as a
    # post-processing step on framework PnL.  See ``trades_dataframe``.
    signal_polarity: str = "fade"

    # ---- Conditioning bins ----
    signal_size_bins_bp: List[float] = field(
        default_factory=lambda: [0.0, 0.25, 0.5, 1.0, 2.0, 4.0, float("inf")]
    )
    fomc_window_days: int = 2

    # ---- I/O ----
    results_dir: str = str(Path(_REPO_ROOT, "BT", "results", "asia_fade"))

    # ---- Backtest runtime knobs ----
    show_progress: bool = True
    strategy_name: str = "asia_fade_sfr"
    ts_builder_jobs: int = 8

    # ──────────────── dict-like protocol ────────────────

    def __getitem__(self, key: str) -> Any:
        if not hasattr(self, key):
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self):
        return iter(f.name for f in fields(self))

    def __len__(self) -> int:
        return len(fields(self))

    # ──────────────── (de)serialization ────────────────

    @classmethod
    def from_dict(cls, d: Union["AsiaFadeConfig", MappingT[str, Any], None]) -> "AsiaFadeConfig":
        if d is None:
            return cls()
        if isinstance(d, AsiaFadeConfig):
            return d
        valid = {f.name for f in fields(cls)}
        unknown = set(d.keys()) - valid
        if unknown:
            raise ValueError(f"Unknown AsiaFadeConfig keys: {sorted(unknown)}")
        return cls(**{k: d[k] for k in d if k in valid})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    # ──────────────── derived ────────────────

    @property
    def start_date(self) -> dt.date:
        return dt.date.fromisoformat(self.start)

    @property
    def end_date(self) -> dt.date:
        return dt.date.fromisoformat(self.end)

    @property
    def results_path(self) -> Path:
        return Path(self.results_dir)

    @property
    def plots_path(self) -> Path:
        return self.results_path / "plots"


# ───────────────────────── Tenor / sector helpers ──────────────────────────


_TENOR_RANK_RE = re.compile(r"^IMM_(\d+)xIMM_(\d+)$")


def tenor_to_rank(tenor: str) -> Optional[int]:
    """Return rank for ``IMM_NxIMM_{N+1}`` tenors, else None.

    Named-contract tenors (``IMM_M26xIMM_U26``) return None — those are not
    rank-numbered.
    """
    m = _TENOR_RANK_RE.match(tenor)
    return int(m.group(1)) if m else None


def _tenor_pct_to_bp_mult(tenor: str) -> float:
    """Multiplier converting the curve's reported rate units to basis points.

    OUTRIGHT (single tenor, no '/') → returned in PERCENT, so ×100 → bp.
    CURVE / FLY (slash-separated) → already returned in BP (×10000 baked
    into IRSwapValue.RATE per ``_swap_structure_legs_mapper``).
    """
    return 1.0 if "/" in tenor else 100.0


def sector_for_rank(rank: Optional[int]) -> Optional[str]:
    if rank is None:
        return None
    for name, (lo, hi) in SECTORS.items():
        if lo <= rank <= hi:
            return name
    return None


# ─────────────────────────── Data fetching ───────────────────────────────


def _localize_window(cfg: AsiaFadeConfig) -> Tuple[dt.datetime, dt.datetime]:
    s = NY_TZ.localize(dt.datetime.combine(cfg.start_date, dt.time(0, 0)))
    e = NY_TZ.localize(dt.datetime.combine(cfg.end_date,   dt.time(23, 59)))
    return s, e


def load_intraday_rates(
    cfg: AsiaFadeConfig,
    mdp: Optional[IRSwapsMDP] = None,
    ts_builder: Optional[TimeseriesBuilder] = None,
) -> pd.DataFrame:
    """Load intraday rate series at ``cfg.bar_freq`` for every tenor in cfg.

    Returns a DataFrame indexed by NY-tz timestamps with one column per tenor
    (renamed to the bare tenor string for easy downstream lookup).  Rates are
    in PERCENT (e.g. 3.635 = 3.635%).
    """
    mdp = mdp or IRSwapsMDP(source=cfg.mdp_source)
    ts_builder = ts_builder or TimeseriesBuilder()

    queries = [
        UnifiedQuery(
            curve=cfg.curve,
            tenor=tenor,
            value=UnifiedValue.IRS_RATE,
        )
        for tenor in cfg.tenors
    ]

    start, end = _localize_window(cfg)
    df = ts_builder.get_timeseries(
        start=start,
        end=end,
        queries=queries,
        freq=cfg.bar_freq,
        n_jobs=cfg.ts_builder_jobs,
        routers={"IRS": IRSwapsTB(mdp, show_tqdm=cfg.show_progress)},
        mdps={"IRS": mdp},
        ignore_cache_miss=True,
    )
    if df is None or df.empty:
        raise RuntimeError("TimeseriesBuilder returned no data — check curve/tenors/window.")

    df = df.sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize(NY_TZ)
    else:
        df.index = df.index.tz_convert(NY_TZ)

    # Map "<curve> <tenor> {OUTRIGHT|CURVE|FLY} RATE" → "<tenor>".
    # Match tenor as a whole space-bracketed token to avoid substring
    # collisions (e.g. spread "IMM_1xIMM_2/IMM_5xIMM_6" containing the
    # outright "IMM_1xIMM_2").
    rename: Dict[str, str] = {}
    for col in df.columns:
        # Prefer longest tenor match so "IMM_1xIMM_2/IMM_5xIMM_6" wins over
        # "IMM_1xIMM_2" if both appear in cfg.tenors.
        candidates = [t for t in cfg.tenors if f" {t} " in f" {col} "]
        if not candidates:
            continue
        rename[col] = max(candidates, key=len)

    df = df.rename(columns=rename)

    # Keep only one column per tenor (drop duplicates from mis-routed renames).
    keep_cols, seen = [], set()
    for c in df.columns:
        if c in cfg.tenors and c not in seen:
            keep_cols.append(c)
            seen.add(c)
    return df[keep_cols].apply(pd.to_numeric, errors="coerce")


def _sample_at_or_before(
    series: pd.Series,
    ts: dt.datetime,
    tolerance: dt.timedelta,
) -> Optional[float]:
    if series.empty:
        return None
    # Use pandas asof — finds the last value at-or-before ts
    val = series.asof(ts)
    if pd.isna(val):
        return None
    idx = series.index.asof(ts)
    if pd.isna(idx) or (ts - idx) > tolerance:
        return None
    return float(val)


# ─────────────────────────── Trade event build ────────────────────────────


def trading_dates(start: dt.date, end: dt.date) -> List[dt.date]:
    out: List[dt.date] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def _next_business_day(d: dt.date, offset: int) -> dt.date:
    """Return the date ``offset`` business days after ``d`` (or before, if
    offset < 0).  Skips Saturdays and Sundays."""
    step = 1 if offset >= 0 else -1
    remaining = abs(int(offset))
    cur = d
    while remaining > 0:
        cur = cur + dt.timedelta(days=step)
        if cur.weekday() < 5:
            remaining -= 1
    return cur


def build_trade_events(
    cfg: AsiaFadeConfig,
    rates: pd.DataFrame,
) -> List[Dict[str, Any]]:
    """Build the list of trade events from intraday rate samples.

    Layout per trade-date ``D``:
        signal_start_ts = D @ signal_start_hhmm   (e.g. 17:00 ET)
        signal_end_ts   = D @ signal_end_hhmm     (e.g. 22:00 ET)
        entry_ts        = D @ entry_hhmm          (e.g. 22:00 ET)
        exit_ts         = (D + exit_day_offset business days) @ exit_hhmm
                            (e.g. next morning 08:00 ET)

    Signal move (bp) = (rate at signal_end_ts) − (rate at signal_start_ts), ×100
    Fade direction   = − sign(signal_move_bp)   (so receive-fixed if rates rose)
    """
    tol = dt.timedelta(minutes=cfg.sample_tolerance_min)
    events: List[Dict[str, Any]] = []

    for d in trading_dates(cfg.start_date, cfg.end_date):
        exit_day = _next_business_day(d, cfg.exit_day_offset)
        signal_start_ts = NY_TZ.localize(dt.datetime.combine(d, dt.time(*cfg.signal_start_hhmm)))
        signal_end_ts   = NY_TZ.localize(dt.datetime.combine(d, dt.time(*cfg.signal_end_hhmm)))
        entry_ts        = NY_TZ.localize(dt.datetime.combine(d, dt.time(*cfg.entry_hhmm)))
        exit_ts         = NY_TZ.localize(dt.datetime.combine(exit_day, dt.time(*cfg.exit_hhmm)))

        for tenor in cfg.tenors:
            if tenor not in rates.columns:
                continue
            s = rates[tenor].dropna()

            r_ss = _sample_at_or_before(s, signal_start_ts, tol)
            r_se = _sample_at_or_before(s, signal_end_ts,   tol)
            r_en = _sample_at_or_before(s, entry_ts,        tol)
            r_ex = _sample_at_or_before(s, exit_ts,         tol)
            if any(x is None for x in (r_ss, r_se, r_en, r_ex)):
                continue

            unit_mult = _tenor_pct_to_bp_mult(tenor)
            signal_move_bp = (r_se - r_ss) * unit_mult
            if abs(signal_move_bp) < cfg.min_signal_move_bp:
                continue
            if signal_move_bp == 0:
                continue

            # IRSwapQuery's OUTRIGHT structure normalizes the swap to a
            # fixed direction (PAYER — profits as rates rise) regardless of
            # bpv sign.  We always pass ``bpv = +base_bpv_usd`` (magnitude
            # only) and carry the trade direction in event meta to apply as
            # a multiplier on framework PnL downstream.
            #
            # FADE convention:
            #   signal_move_bp > 0 (rates rose)  → take RECEIVER → mult = -1
            #   signal_move_bp < 0 (rates fell)  → take PAYER    → mult = +1
            # i.e. trade_direction = -sign(signal_move_bp).  MOMENTUM is the
            # opposite.
            sgn = float(np.sign(signal_move_bp))
            trade_direction = (-sgn) if cfg.signal_polarity == "fade" else (+sgn)
            bpv = cfg.base_bpv_usd

            rank = tenor_to_rank(tenor)
            sector = sector_for_rank(rank)

            events.append({
                "date":              d,                 # trade-date (entry day)
                "tenor":             tenor,
                "rank":              rank,
                "sector":            sector,
                "entry_ts":          entry_ts,
                "exit_ts":           exit_ts,
                "bpv":               bpv,
                "signal_open_rate":  r_ss,
                "signal_close_rate": r_se,
                "entry_rate":        r_en,
                "exit_rate":         r_ex,
                "signal_move_bp":    float(signal_move_bp),
                "hold_move_bp":      float((r_ex - r_en) * unit_mult),
                "trade_direction":   float(trade_direction),
                "tag":               TRADE_TAG,
            })

    return events


# ─────────────────────── Cost computation per trade ───────────────────────


def _unwind_fee_per_event(cfg: AsiaFadeConfig, event: Dict[str, Any]) -> float:
    """Total round-trip cost in USD for one event (one open + one close).

    Charged in full at unwind via UnwindPositionsAction(fee=...).  Includes
    bid-ask + slippage in bp×|bpv| terms + 2 sides of commission.
    """
    cost_bp = cfg.bid_ask_bp_rt + cfg.slippage_bp_rt
    return cost_bp * abs(event["bpv"]) + 2.0 * cfg.commission_per_side_usd


# ──────────────────── Trigger / strategy construction ─────────────────────


def _exit_signal_fn_factory(exit_ts_set: set) -> Callable[[dt.datetime, Any], bool]:
    def _fn(state, backtest):
        return state in exit_ts_set
    return _fn


def _entry_signal_fn_factory(entry_ts: dt.datetime, tenor: str) -> Callable[[dt.datetime, Any], Any]:
    def _fn(state, backtest):
        # Fire only on exact entry_ts and only if no open position for this tenor.
        if state != entry_ts:
            return False
        for pos in backtest.portfolio.positions:
            q = pos.source_query
            if getattr(q, "tenor", None) == tenor:
                return False
        return True
    return _fn


def build_strategy(cfg: AsiaFadeConfig, events: List[Dict[str, Any]]) -> Tuple[QueryStrategy, TimeGrid]:
    if not events:
        raise RuntimeError("No trade events constructed — relax liquidity gates or widen window.")

    # Group events by exit_ts so the single exit trigger can carry the right fee.
    # We bundle fees by (exit_ts → total fee) and the unwind action distributes
    # the fee evenly across positions closed at that step (handled by
    # _handle_unwind in BT/query_engine.py).
    exit_ts_to_total_fee: Dict[dt.datetime, float] = {}
    for ev in events:
        f = _unwind_fee_per_event(cfg, ev)
        exit_ts_to_total_fee[ev["exit_ts"]] = exit_ts_to_total_fee.get(ev["exit_ts"], 0.0) + f

    exit_ts_set = set(exit_ts_to_total_fee.keys())

    class _FeeAwareUnwindAction:
        """Wrapper that emits one UnwindOrder per call but uses per-timestamp
        total fee carried in the order meta so realized P&L matches our cost
        model exactly."""

        def __init__(self, fee_map: Dict[dt.datetime, float]):
            self._fee_map = fee_map
            self.risk = None

        def __call__(self, *, now, backtest, info):
            fee = float(self._fee_map.get(now, 0.0))
            # Build via UnwindPositionsAction so we get the same selector
            # behaviour, but with the appropriate fee.
            return UnwindPositionsAction(match_tag=TRADE_TAG, fee=fee)(
                now=now, backtest=backtest, info=info
            )

    exit_trigger = Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(signal_fn=_exit_signal_fn_factory(exit_ts_set)),
        actions=[_FeeAwareUnwindAction(exit_ts_to_total_fee)],
    )

    entry_triggers: List[Trigger] = []
    for ev in events:
        q = IRSwapQuery(
            curve=cfg.curve,
            tenor=ev["tenor"],
            value=IRSwapValue.NPV,
            structure_kwargs={"bpv": ev["bpv"]},
            tags=(TRADE_TAG, ev["tenor"]),
            meta={
                "date":              ev["date"].isoformat(),
                "tenor":             ev["tenor"],
                "rank":              ev["rank"],
                "sector":            ev["sector"],
                "signal_open_rate":  ev["signal_open_rate"],
                "signal_close_rate": ev["signal_close_rate"],
                "signal_move_bp":    ev["signal_move_bp"],
                "hold_move_bp":      ev["hold_move_bp"],
                "trade_direction":   ev["trade_direction"],
                "tag":               TRADE_TAG,
            },
        )
        entry_triggers.append(
            Trigger(
                trigger_requirements=FlowSignalTriggerRequirements(
                    signal_fn=_entry_signal_fn_factory(ev["entry_ts"], ev["tenor"])
                ),
                actions=[AddQueryAction(query=q)],
            )
        )

    strategy = QueryStrategy(name=cfg.strategy_name, triggers=[exit_trigger] + entry_triggers)

    all_ts = sorted(set(ev["entry_ts"] for ev in events) | set(ev["exit_ts"] for ev in events))
    return strategy, TimeGrid(all_ts)


# ─────────────────────────────── Run API ──────────────────────────────────


def run_asia_fade(
    config: Union[AsiaFadeConfig, MappingT[str, Any], None] = None,
    *,
    return_rates: bool = False,
) -> Dict[str, Any]:
    """End-to-end runner.

    Returns a dict with:
      ``backtest``     — the QueryDrivenBacktest after run()
      ``trades``       — DataFrame of closed trades (with metadata)
      ``events``       — original event list (also useful for diagnostics)
      ``config``       — resolved AsiaFadeConfig
      ``rates``        — only if ``return_rates=True``
    """
    cfg = AsiaFadeConfig.from_dict(config)

    logger.info("Loading intraday rates: curve=%s tenors=%d freq=%s window=%s..%s",
                cfg.curve, len(cfg.tenors), cfg.bar_freq, cfg.start, cfg.end)
    mdp = IRSwapsMDP(source=cfg.mdp_source)
    ts_builder = TimeseriesBuilder()
    rates = load_intraday_rates(cfg, mdp=mdp, ts_builder=ts_builder)
    logger.info("Loaded %d rate bars across %d tenors", len(rates), rates.shape[1])

    events = build_trade_events(cfg, rates)
    logger.info("Constructed %d trade events", len(events))
    if not events:
        return {"backtest": None, "trades": pd.DataFrame(), "events": [],
                "config": cfg, **({"rates": rates} if return_rates else {})}

    strategy, time_grid = build_strategy(cfg, events)
    bt = QueryDrivenBacktest(
        time_grid=time_grid,
        mdp=mdp,
        strategy=strategy,
        show_progress=cfg.show_progress,
        progress_desc="ASIA-FADE",
    )
    bt.run()

    trades = trades_dataframe(bt, events)
    out: Dict[str, Any] = {
        "backtest": bt, "trades": trades, "events": events, "config": cfg,
    }
    if return_rates:
        out["rates"] = rates
    return out


def trades_dataframe(bt: QueryDrivenBacktest, events: List[Dict[str, Any]]) -> pd.DataFrame:
    """Normalize bt.portfolio.closed_positions_log → flat trade DataFrame
    merging the event metadata (which trigger fired, sector, etc.) onto each
    closed position."""
    cl = pd.DataFrame(bt.portfolio.closed_positions_log)
    if cl.empty:
        return cl

    # Pull per-trade meta from source_query.meta (carries our event payload)
    def _q_meta(q, key, default=None):
        if q is None:
            return default
        m = getattr(q, "meta", None) or {}
        return m.get(key, default)

    cl["date"]            = cl["source_query"].apply(lambda q: _q_meta(q, "date"))
    cl["tenor"]           = cl["source_query"].apply(lambda q: _q_meta(q, "tenor"))
    cl["rank"]            = cl["source_query"].apply(lambda q: _q_meta(q, "rank"))
    cl["sector"]          = cl["source_query"].apply(lambda q: _q_meta(q, "sector"))
    cl["signal_move_bp"]  = cl["source_query"].apply(lambda q: _q_meta(q, "signal_move_bp")).astype(float)
    cl["hold_move_bp"]    = cl["source_query"].apply(lambda q: _q_meta(q, "hold_move_bp")).astype(float)
    cl["trade_direction"] = cl["source_query"].apply(lambda q: _q_meta(q, "trade_direction", 1.0)).astype(float)
    cl["entry_ts"]        = pd.to_datetime(cl["opened_at"], utc=False)
    cl["exit_ts"]         = pd.to_datetime(cl["closed_at"], utc=False)

    # Framework reports PnL as if every position were a PAYER (rate-rise =
    # profit) regardless of bpv sign — see comment in build_trade_events.
    # We re-apply the trade direction here so positive net_usd really means
    # the trade made money in its intended (fade/momentum) sense.
    raw_gross = cl["gross_realized_pnl"].astype(float)
    fee       = cl["fee_allocated"].astype(float)
    cl["gross_usd"] = raw_gross * cl["trade_direction"]
    cl["fee_usd"]   = fee
    cl["net_usd"]   = cl["gross_usd"] - cl["fee_usd"]
    cl["abs_signal_move_bp"] = cl["signal_move_bp"].astype(float).abs()
    cl["date"]               = pd.to_datetime(cl["date"])

    # Strip non-serializable framework objects (ResolvedQueryPosition,
    # IRSwapQuery, etc.) so the result round-trips through parquet/csv.
    drop_cols = [c for c in ("position", "source_query", "position_meta",
                             "exit_meta", "handler_name") if c in cl.columns]
    cl = cl.drop(columns=drop_cols)
    return cl


# ─────────────────────────────── Metrics ──────────────────────────────────


def _annualized_sharpe(pnl: pd.Series, n_days: int) -> float:
    if pnl.empty or pnl.std() == 0:
        return 0.0
    n_years = max(n_days / 252.0, 0.25)
    tpy = len(pnl) / n_years if n_years > 0 else 0
    return float(pnl.mean() / pnl.std() * np.sqrt(max(tpy, 1.0)))


def metrics_for_group(grp: pd.DataFrame, n_days: int) -> Dict[str, Any]:
    if grp.empty:
        return {"n_trades": 0, "hit_rate": np.nan, "avg_usd": np.nan,
                "avg_win_usd": np.nan, "avg_loss_usd": np.nan,
                "total_usd": 0.0, "sharpe": np.nan, "max_dd_usd": np.nan,
                "avg_signal_size_bp": np.nan}
    wins = grp[grp["net_usd"] > 0]
    losses = grp[grp["net_usd"] < 0]
    cum = grp.sort_values("date")["net_usd"].cumsum()
    dd = (cum - cum.cummax()).min()
    return {
        "n_trades":         int(len(grp)),
        "hit_rate":         float((grp["net_usd"] > 0).mean()),
        "avg_usd":          float(grp["net_usd"].mean()),
        "avg_win_usd":      float(wins["net_usd"].mean()) if len(wins) else 0.0,
        "avg_loss_usd":     float(losses["net_usd"].mean()) if len(losses) else 0.0,
        "total_usd":        float(grp["net_usd"].sum()),
        "sharpe":           _annualized_sharpe(grp["net_usd"], n_days),
        "max_dd_usd":       float(dd) if not np.isnan(dd) else 0.0,
        "avg_signal_size_bp": float(grp["abs_signal_move_bp"].mean()),
    }


def metrics_per_tenor(trades: pd.DataFrame, n_days: int) -> pd.DataFrame:
    rows = []
    for tenor, grp in trades.groupby("tenor"):
        m = metrics_for_group(grp, n_days)
        m["tenor"] = tenor
        m["rank"] = grp["rank"].iloc[0]
        m["sector"] = grp["sector"].iloc[0]
        rows.append(m)
    return pd.DataFrame(rows).sort_values(["rank", "tenor"], na_position="last")


def metrics_per_sector(trades: pd.DataFrame, n_days: int) -> pd.DataFrame:
    rows = []
    for name in SECTORS:
        grp = trades[trades["sector"] == name]
        m = metrics_for_group(grp, n_days)
        m["sector"] = name
        rows.append(m)
    return pd.DataFrame(rows)


def metrics_by_signal_size(trades: pd.DataFrame, cfg: AsiaFadeConfig, n_days: int) -> pd.DataFrame:
    bins = cfg.signal_size_bins_bp
    labels = []
    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        labels.append(f">{lo:g}bp" if np.isinf(hi) else f"{lo:g}-{hi:g}bp")
    sizes = pd.cut(trades["abs_signal_move_bp"], bins=bins, labels=labels, include_lowest=True)
    rows = []
    for label, grp in trades.assign(size_bin=sizes).groupby("size_bin", observed=True):
        m = metrics_for_group(grp, n_days)
        m["size_bin"] = str(label)
        rows.append(m)
    return pd.DataFrame(rows)


def metrics_by_fomc(
    trades: pd.DataFrame,
    fomc_dates: List[dt.date],
    cfg: AsiaFadeConfig,
    n_days: int,
) -> pd.DataFrame:
    window = cfg.fomc_window_days

    def _classify(d: pd.Timestamp) -> str:
        d_date = d.date()
        for fd in fomc_dates:
            delta = (d_date - fd).days
            if delta == 0:
                return "FOMC_day"
            if 0 < delta <= window:
                return "post_FOMC"
            if -window <= delta < 0:
                return "pre_FOMC"
        return "non_FOMC"

    if not fomc_dates:
        return pd.DataFrame()
    cat = trades["date"].apply(_classify)
    rows = []
    for label, grp in trades.assign(fomc_bucket=cat).groupby("fomc_bucket"):
        m = metrics_for_group(grp, n_days)
        m["fomc_bucket"] = label
        rows.append(m)
    return pd.DataFrame(rows)


def metrics_by_vol_regime(trades: pd.DataFrame, n_days: int, vol_window: int = 21) -> pd.DataFrame:
    out_frames = []
    for tenor, grp in trades.groupby("tenor"):
        g = grp.sort_values("date").copy()
        rv = g["signal_move_bp"].rolling(vol_window, min_periods=5).std()
        terc = pd.qcut(rv, 3, labels=["low_vol", "mid_vol", "high_vol"], duplicates="drop")
        g["vol_bucket"] = terc.astype(object).fillna("mid_vol")
        out_frames.append(g)
    tagged = pd.concat(out_frames)
    rows = []
    for label, grp in tagged.groupby("vol_bucket"):
        m = metrics_for_group(grp, n_days)
        m["vol_bucket"] = label
        rows.append(m)
    return pd.DataFrame(rows)


__all__ = [
    "AsiaFadeConfig",
    "SECTORS",
    "TRADE_TAG",
    "build_strategy",
    "build_trade_events",
    "load_intraday_rates",
    "metrics_by_fomc",
    "metrics_by_signal_size",
    "metrics_by_vol_regime",
    "metrics_for_group",
    "metrics_per_sector",
    "metrics_per_tenor",
    "run_asia_fade",
    "sector_for_rank",
    "tenor_to_rank",
    "trades_dataframe",
    "trading_dates",
]
