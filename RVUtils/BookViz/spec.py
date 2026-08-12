"""How a book's frame maps onto the figures — the one thing that has to be general.

Every ARBS study names its columns differently: the econ-release-fade books carry ``pnl_bp`` and
``release_ts``, a ``QueryDrivenBacktest`` closed log carries ``realized_pnl`` and ``closed_at``,
a screener carries ``net_pnl`` and ``date``. Hard-coding either vocabulary is what made the
original dashboard un-reusable, so the mapping is data.

Two conventions are worth stating because getting them wrong is silent:

**Units.** P&L in basis points and P&L in currency need different formatting and different axis
labels, and a figure that says "bp" over dollars is worse than one that says nothing. ``unit`` is
carried explicitly and never guessed from magnitude.

**The equity curve is not always the cumulative sum of the trades.** For an unfinanced book it is.
For a financed one it is not, and the difference is the carry — so :class:`BookSpec` lets a caller
supply a *marked* equity series alongside the trade ledger, and the dashboard will draw that as
the curve and place the trades on it rather than quietly re-deriving a curve that disagrees with
the engine's own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

import pandas as pd

__all__ = ["BookSpec", "resolve_spec", "pick_column"]

#: Candidate column names, most specific first, for each role. Extend rather than branch.
_CANDIDATES: Mapping[str, Sequence[str]] = {
    "pnl": ("pnl_bp", "net_pnl_bp", "realized_pnl", "pnl_usd", "net_pnl", "pnl"),
    "gross": ("pnl_bp_gross", "gross_pnl_bp", "gross_realized_pnl", "gross_pnl"),
    "cost": ("cost_bp", "fee_allocated", "cost_usd", "fee", "cost"),
    "time": ("release_ts", "entry_ts", "opened_at", "closed_at", "exit_ts", "date", "timestamp"),
    "category": ("exit_reason", "reason", "category", "label"),
    "signal": ("z", "zsig_bp", "move_bp", "signal", "surprise"),
    "hold": ("hold_min", "holding_period_days", "hold_days", "holding_period_steps"),
    "label": ("release", "lead_title", "fly_id", "symbol", "tag", "cusip"),
}


def pick_column(df: pd.DataFrame, *names: str) -> Optional[str]:
    """First of ``names`` that is actually a column."""
    for n in names:
        if n and n in df.columns:
            return n
    return None


@dataclass
class BookSpec:
    """Column mapping plus presentation for one book.

    Every field may be left ``None`` and inferred by :func:`resolve_spec`; passing one explicitly
    overrides inference, which matters when a frame carries two plausible candidates and the
    wrong one is chosen silently.
    """

    pnl: Optional[str] = None
    time: Optional[str] = None
    category: Optional[str] = None
    signal: Optional[str] = None
    gross: Optional[str] = None
    cost: Optional[str] = None
    hold: Optional[str] = None
    label: Optional[str] = None

    #: "bp" or a currency code. Drives axis titles and number formatting, never inferred.
    unit: str = "bp"
    #: Decimal places for per-trade numbers. Currency wants 0-2; bp wants 3-4.
    precision: int = 4
    #: Timezone to display timestamps in. ``None`` leaves them as they are, which is right for a
    #: daily book; intraday event studies want an explicit market timezone.
    tz: Optional[str] = None
    #: Extra columns to append to the tooltip, in order.
    extra_hover: Sequence[str] = field(default_factory=tuple)

    @property
    def is_currency(self) -> bool:
        return self.unit.lower() not in ("bp", "bps", "basis points")

    def fmt(self, v: float) -> str:
        if v is None or not isinstance(v, (int, float)) or pd.isna(v):
            return "-"
        if self.is_currency:
            return f"{v:,.{min(self.precision, 2)}f}"
        return f"{v:+.{self.precision}f}"

    @property
    def axis_unit(self) -> str:
        return self.unit


def resolve_spec(df: pd.DataFrame, spec: Optional[BookSpec] = None) -> BookSpec:
    """Fill in whatever the caller left unset, from the frame's actual columns.

    Raises rather than guessing when no P&L or time column can be found: a dashboard drawn from
    the wrong column is worse than no dashboard, because it looks like an answer.
    """
    s = BookSpec(**vars(spec)) if spec is not None else BookSpec()
    for role in ("pnl", "time", "category", "signal", "gross", "cost", "hold", "label"):
        if getattr(s, role) is None:
            setattr(s, role, pick_column(df, *_CANDIDATES[role]))
    if s.pnl is None:
        raise ValueError(
            f"no P&L column found; looked for {list(_CANDIDATES['pnl'])} in {list(df.columns)}. "
            "Pass BookSpec(pnl='...') explicitly."
        )
    if s.time is None:
        raise ValueError(
            f"no time column found; looked for {list(_CANDIDATES['time'])} in {list(df.columns)}. "
            "Pass BookSpec(time='...') explicitly."
        )
    return s
