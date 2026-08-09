"""The copula-coordinate butterfly, ported to QueryDrivenBacktest.

Forked from ``famb_fly_qdb.py``. That book is always-on and rolls on a calendar; this one
trades only when the copula coordinate leaves its own trailing distribution, so the schedule
is a consequence of the signal rather than an input to it.

Structure: an all-call 1/-2/1 SR3 butterfly struck on the K-atom lattice at the FLY25
spacing (+/-0.25 price = +/-25bp = exactly the atom spacing).

  lambda_z <= -threshold  the market prices a fat middle, so the wings are cheap
                          -> LONG THE WINGS, i.e. SHORT the fly, weights [-1, 2, -1]
  lambda_z >= +threshold  -> LONG the fly, weights [1, -2, 1]

Costs follow the parent exactly: ``tcost_vol_bp`` is bp per OPTION contract per side, a
1-lot fly is 4 contracts, and the full round trip is booked once at the unwind as
``2 x 4 x contracts x tcost_vol_bp x $25``.

Two defects in the parent are fixed rather than inherited:

* The parent's delta hedge is unwound in the step it opens (the engine processes adds before
  unwinds and ``pop_matching`` has no "opened before now" filter), so the hedged run carries
  no hedge while still accruing hedging cost. Every unwind here uses a selector that requires
  ``position.opened < now``.
* The parent has no force-flatten, so a position still open on the final grid state never
  reaches ``closed_positions_log`` and is silently missing from the trade count. One is added.

Everything the signal reads is a value that existed at the time it is read: the z-score uses
a trailing window that strictly excludes the current session.
"""
from __future__ import annotations

import ast
import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryFactoryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import FlowSignalTriggerRequirements, Trigger
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from Query.STIRFutureOptions.STIRFutureOptionStructure import STIRFutureOptionStructure
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue

NY = pytz.timezone("America/New_York")

#: Half a tick, per option contract per side. The parent's default and the house convention.
DEFAULT_TCOST_VOL_BP = 0.125
#: 1 fly lot = 4 option contracts (famb_common.n_contracts("FLY25")).
CONTRACTS_PER_FLY = 4.0
#: $ per bp per option contract (SOFR_OPTION_POINT_VALUE 2500 x 0.01).
USD_PER_BP_PER_CONTRACT = 25.0


def _ts(d, hour: int = 17) -> datetime.datetime:
    """Every grid state is 17:00 America/New_York and tz-AWARE.

    Trigger equality is ``now == t`` on these exact objects, so a naive datetime or a bare
    pd.Timestamp silently never matches -- and because ``run()`` swallows exceptions, the
    symptom is a clean zero-trade backtest rather than an error.
    """
    d = pd.Timestamp(d)
    return NY.localize(datetime.datetime(d.year, d.month, d.day, hour, 0))


def opt_label(symbol: str, right: str, strike_price: float) -> str:
    return f"{symbol}|{int(round(strike_price * 100))}{right}"


def _parse_list(x) -> List[float]:
    if isinstance(x, (list, tuple, np.ndarray)):
        return [float(v) for v in x]
    if not isinstance(x, str) or not x.strip():
        return []
    try:
        return [float(v) for v in ast.literal_eval(x)]
    except (ValueError, SyntaxError):
        return []


# ---------------------------------------------------------------------------------------
# signal construction
# ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SignalConfig:
    z_threshold: float = 1.0
    z_window: int = 60
    z_min_obs: int = 30
    max_fwd_resid_bp: float = 1.0
    max_pre_norm_mass: float = 1.02
    max_ghost: float = 0.05
    max_atom_spread: float = 0.60
    max_hold_sessions: int = 40
    lambda_col: str = "lambda_wing"


def prepare_signal_frame(
    panel: pd.DataFrame,
    config: SignalConfig = SignalConfig(),
    *,
    shuffle_seed: Optional[int] = None,
) -> pd.DataFrame:
    """Attach the admissibility gate and the trailing z-score, per contract.

    ``shuffle_seed`` permutes the lambda series WITHIN each contract, keeping every other
    column and every date in place. That is the null the strategy has to beat: same trade
    calendar, same fit quality, same costs, lambda carrying no information.
    """
    df = panel.copy()
    df["as_of"] = pd.to_datetime(df["as_of"])
    df = df.sort_values(["symbol", "as_of"]).reset_index(drop=True)

    for col in ("atom_prices", "lambda_atoms"):
        if col in df.columns:
            df[col] = df[col].map(_parse_list)

    df["admissible"] = (
        df["ok"].astype(bool)
        & df["forward_residual_bp"].abs().le(config.max_fwd_resid_bp)
        & df["pre_normalization_mass"].le(config.max_pre_norm_mass)
        & df["ghost_mass_fraction"].le(config.max_ghost)
        & df["lambda_atom_spread"].le(config.max_atom_spread)
        & df[config.lambda_col].notna()
    )

    if shuffle_seed is not None:
        rng = np.random.default_rng(int(shuffle_seed))
        out = []
        for _, sub in df.groupby("symbol", sort=True):
            sub = sub.copy()
            mask = sub["admissible"].to_numpy()
            vals = sub.loc[mask, config.lambda_col].to_numpy()
            # Permute positionally, on a deterministically ordered frame: a fixed seed is not
            # reproducibility if the RNG is consumed against an arbitrary row order.
            sub.loc[mask, config.lambda_col] = rng.permutation(vals)
            out.append(sub)
        df = pd.concat(out, ignore_index=True).sort_values(["symbol", "as_of"])

    # The window counts ADMISSIBLE observations, not calendar sessions. The pre-registration
    # asks for "a trailing 60-session window" with "minimum 30 admissible observations in the
    # window"; a calendar window cannot satisfy the second clause when the fit gate rejects
    # most sessions, so the admissible-observation reading is the one that has both halves.
    # Stated here because it is an interpretation, not a free choice.
    mus = pd.Series(np.nan, index=df.index, dtype=float)
    sds = pd.Series(np.nan, index=df.index, dtype=float)
    for _, sub in df.groupby("symbol", sort=False):
        adm = sub[sub["admissible"]]
        if adm.empty:
            continue
        lam = adm[config.lambda_col].astype(float)
        # shift(1) is what makes this usable at t: the window ends at the previous ADMISSIBLE
        # observation, so nothing from session t enters its own standardisation.
        prior = lam.shift(1)
        mus.loc[adm.index] = prior.rolling(config.z_window, min_periods=config.z_min_obs).mean()
        sds.loc[adm.index] = prior.rolling(config.z_window, min_periods=config.z_min_obs).std(ddof=1)
    df["lambda_mu"] = mus
    df["lambda_sd"] = sds
    df["lambda_z"] = (
        df[config.lambda_col].where(df["admissible"]).astype(float) - mus
    ) / sds.replace(0.0, np.nan)
    return df


def _fly_strikes(atom_prices: List[float], forward_price: float) -> Optional[Tuple[float, float, float]]:
    """Body on the lattice atom nearest the forward, wings one 25bp step either side."""
    if not atom_prices:
        return None
    mid = min(atom_prices, key=lambda p: abs(p - float(forward_price)))
    mid = round(mid * 4.0) / 4.0  # the FLY25 strike grid
    return mid - 0.25, mid, mid + 0.25


@dataclass
class LambdaState:
    """Strategy-side bookkeeping the engine does not own."""

    open_tag: Optional[str] = None
    open_sign: int = 0
    open_since: Optional[datetime.datetime] = None
    n_opened: int = 0
    pending: Optional[Dict[str, Any]] = None
    entries: List[Dict[str, Any]] = field(default_factory=list)
    skipped_no_strikes: int = 0


def make_lambda_fly_backtest(
    signal_frame: pd.DataFrame,
    symbol: str,
    opt_mdp,
    *,
    config: SignalConfig = SignalConfig(),
    contracts: float = 1.0,
    tcost_vol_bp: float = DEFAULT_TCOST_VOL_BP,
    show_progress: bool = False,
) -> Tuple[QueryDrivenBacktest, LambdaState]:
    sub = signal_frame[signal_frame.symbol == symbol].sort_values("as_of").reset_index(drop=True)
    if sub.empty:
        raise ValueError(f"no signal rows for {symbol}")

    ts_list = [_ts(d) for d in sub["as_of"]]
    by_ts = {t: sub.iloc[i] for i, t in enumerate(ts_list)}
    index_of = {t: i for i, t in enumerate(ts_list)}
    last_ts = ts_list[-1]
    state = LambdaState()
    opt_fee_side = CONTRACTS_PER_FLY * contracts * tcost_vol_bp * USD_PER_BP_PER_CONTRACT

    def _entry_signal(now, bt) -> bool:
        if state.open_tag is not None or now not in by_ts or now == last_ts:
            return False
        row = by_ts[now]
        if not bool(row["admissible"]):
            return False
        z = float(row["lambda_z"]) if pd.notna(row["lambda_z"]) else float("nan")
        if not np.isfinite(z) or abs(z) < config.z_threshold:
            return False
        strikes = _fly_strikes(row["atom_prices"], row["forward_price"])
        if strikes is None:
            state.skipped_no_strikes += 1
            return False
        # z below -threshold: the market prices a fat middle, so buy the wings = short the fly.
        sign = -1 if z <= -config.z_threshold else +1
        state.pending = {
            "sign": sign, "strikes": strikes, "z": z,
            "lambda": float(row[config.lambda_col]),
            "as_of": row["as_of"], "n_meetings": int(row["n_meetings"]),
            "dte": float(row["time_to_expiry"]),
        }
        return True

    def _entry_factory(*, now, backtest, info):
        pending = state.pending
        state.pending = None
        if pending is None:
            return None
        low, mid, high = pending["strikes"]
        tag = f"lam{state.n_opened}"
        weights = [1.0, -2.0, 1.0] if pending["sign"] > 0 else [-1.0, 2.0, -1.0]
        state.open_tag = tag
        state.open_sign = pending["sign"]
        state.open_since = now
        state.n_opened += 1
        state.entries.append({**pending, "tag": tag, "entered_at": now,
                              "low": low, "mid": mid, "high": high})
        return STIRFutureOptionQuery(
            structure=STIRFutureOptionStructure.FLY,
            value=STIRFutureOptionValue.PRICE,
            contracts=contracts,
            structure_kwargs={
                "low_symbol": opt_label(symbol, "C", low),
                "mid_symbol": opt_label(symbol, "C", mid),
                "high_symbol": opt_label(symbol, "C", high),
                "risk_weights": weights,
            },
            tags=("sr3_lambda", tag),
        )

    def _should_exit(now) -> bool:
        if now == last_ts:
            return True  # force-flatten: an open position never reaches the closed log
        row = by_ts[now]
        if index_of[now] - index_of[state.open_since] >= config.max_hold_sessions:
            return True
        z = row["lambda_z"]
        if pd.isna(z):
            return False
        # Exit when the coordinate has come back through its own trailing mean.
        return (state.open_sign < 0 and float(z) >= 0.0) or (state.open_sign > 0 and float(z) <= 0.0)

    def _exit_signal(now, bt) -> bool:
        if state.open_tag is None or now not in by_ts:
            return False
        if not _should_exit(now):
            return False
        # Cleared here, not in the action. UnwindPositionsAction.__call__ always returns one
        # UnwindOrder whether or not anything matches -- the matching happens later in the
        # engine -- so the action's return value cannot tell us whether a position closed.
        # Clearing here is still correct in the one case where nothing matches: an entry
        # whose legs had no quote never became a position, and we are flat either way.
        state.open_tag = None
        state.open_sign = 0
        state.open_since = None
        return True

    def _opened_before_now(now):
        # The engine processes ADDS BEFORE UNWINDS inside a timestep and pop_matching has no
        # "opened before now" filter, so a tag-matched unwind on an entry day closes the
        # position it just opened. That is the live defect in the parent file.
        def _sel(position) -> bool:
            tags = set(getattr(position, "meta", {}).get("tags", ()) or ())
            tags |= set(getattr(getattr(position, "source_query", None), "tags", ()) or ())
            return "sr3_lambda" in tags and position.opened < now
        return _sel

    triggers: List[Trigger] = [
        # Exit first, so a session that both exits and re-enters batches as [unwind, add].
        Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(signal_fn=_exit_signal),
            actions=[_SelectorAtFireTime(_opened_before_now, fee=2.0 * opt_fee_side)],
        ),
        Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(signal_fn=_entry_signal),
            actions=[AddQueryFactoryAction(query_factory=_entry_factory,
                                           meta={"strategy": "sr3_lambda"})],
        ),
    ]

    strategy = QueryStrategy(
        name=f"SR3 copula-lambda FLY25 {symbol}",
        triggers=triggers,
        default_mdp=opt_mdp,
    )
    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(ts_list), mdp=opt_mdp, strategy=strategy,
        show_progress=show_progress, progress_desc=f"lambda fly {symbol}",
    )
    return bt, state


class _SelectorAtFireTime(UnwindPositionsAction):
    """UnwindPositionsAction whose selector is built when the trigger fires.

    The selector has to close over ``now`` -- that is the whole point of the
    ``position.opened < now`` guard -- and the base class takes a fixed one.
    """

    def __init__(self, selector_builder, *, fee: float = 0.0):
        super().__init__(selector=lambda _p: False, fee=fee)
        self._selector_builder = selector_builder

    def __call__(self, *, now, backtest, info):
        self.selector = self._selector_builder(now)
        return super().__call__(now=now, backtest=backtest, info=info)
