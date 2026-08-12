"""Data sources for the cross-currency basis book.

Two implementations behind one interface, because the two answer different questions:

* :class:`BankedRVPFSource` reads the archive's own computed panels — the forward and rolled-down
  basis curves and the daily swap returns that ``returns_generator.py`` produced. This is the
  **tie-out** source: the port is only faithful if it reproduces the archive's own numbers on the
  archive's own inputs, and those inputs stop in 2015.
* :class:`CitiXccySource` reads the live instrument from Citi Velocity. ARBS quotes the *exact*
  object RVPF modelled — ``RATES.XCCY_OIS_SWAP.<c1>.<c2>.<fwd>.<tenor>.<leg>.BASIS_SPREAD``,
  a full forward × tenor grid — so the whole bootstrap RVPF carried is unnecessary here.

Three conventions on the Citi path are **unverified** and are exposed as knobs rather than
assumed, because ``MDP/CitiVelocityExcel/xccy/basis_data.py`` says so itself: which currency
``SPREAD_LEG`` denotes, the collateral currency, and **the sign**. Signal 1 is
``-(fwd - rolled)``; if Citi signs its basis the other way the whole book inverts.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__all__ = ["XccyPanel", "XccySource", "BankedRVPFSource", "CitiXccySource", "xccy_basis_tag"]


@dataclass
class XccyPanel:
    """Dates × instruments. Everything the signal stack needs and nothing else.

    ``fwd_basis`` / ``rolled_basis`` are in **basis points**; ``returns`` are decimal daily
    returns of the instrument (already inclusive of carry when the source provides that).
    """

    fwd_basis: pd.DataFrame
    rolled_basis: pd.DataFrame
    returns: pd.DataFrame
    #: Optional extras used by signals 3-5; absent is fine, those signals then score as NaN.
    short_basis: Optional[pd.DataFrame] = None      # the 6m basis, for the momentum signal
    fx_spot: Optional[pd.DataFrame] = None
    credit_spread: Optional[pd.DataFrame] = None
    meta: Dict[str, str] = field(default_factory=dict)

    @property
    def instruments(self) -> List[str]:
        return list(self.returns.columns)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.returns.index)

    def carry(self) -> pd.DataFrame:
        """``-(fwd_basis - rolled_basis)`` — signal 1's numerator, in bp per year.

        The sign is the original's: a forward basis *above* the rolled-down basis means the
        position rolls against you, so the carry is negative.
        """
        common = self.fwd_basis.columns.intersection(self.rolled_basis.columns)
        return -(self.fwd_basis[common] - self.rolled_basis[common])

    def summary(self) -> str:
        d = self.dates
        return (
            f"XccyPanel {len(d)} days {d.min().date()}..{d.max().date()}, "
            f"{len(self.instruments)} instruments ({self.meta.get('source', '?')})"
        )


class XccySource(Protocol):
    def load(self) -> XccyPanel: ...


# --------------------------------------------------------------------- banked
@dataclass
class BankedRVPFSource:
    """The archive's own ``Save/`` panels, 2005-2015.

    ``root`` is the RVPF directory. Layout, unchanged from the original::

        Save/Returns with carry/<PAIR>_<f>Y<m>Y_1d_swap_returns.csv
        Save/Returns/<PAIR>_<f>Y<m>Y_1d_swap_returns.csv
        Save/Forward basis/<PAIR>_<f>Y_fwd_basis.csv
        Save/Forward basis/<PAIR>_<f-h>Y_rldown_basis.csv     (h = carry horizon, e.g. 0.75)
    """

    root: Path
    pairs: Sequence[str]
    points: Dict[int, int]
    carry_horizon: float = 0.25
    carry_returns: bool = True

    def _returns_path(self, pair: str, fwd: int) -> Path:
        mat = self.points[fwd]
        folder = "Returns with carry" if self.carry_returns else "Returns"
        return Path(self.root) / "Save" / folder / f"{pair}_{fwd}Y{mat}Y_1d_swap_returns.csv"

    def load(self) -> XccyPanel:
        root = Path(self.root)
        fwd_cols: Dict[str, pd.Series] = {}
        rol_cols: Dict[str, pd.Series] = {}
        ret_cols: Dict[str, pd.Series] = {}
        short_cols: Dict[str, pd.Series] = {}

        for pair in self.pairs:
            for fwd in sorted(self.points):
                mat = self.points[fwd]
                name = f"{pair} {fwd}Yx{mat}Y"
                rp = self._returns_path(pair, fwd)
                fb = root / "Save" / "Forward basis" / f"{pair}_{fwd}Y_fwd_basis.csv"
                rb = root / "Save" / "Forward basis" / f"{pair}_{fwd - self.carry_horizon:.2f}Y_rldown_basis.csv"
                if not (rp.exists() and fb.exists() and rb.exists()):
                    logger.debug("skipping %s: missing one of %s", name, [p.name for p in (rp, fb, rb)])
                    continue

                ret = pd.read_csv(rp, header=None, index_col=0, parse_dates=True).iloc[:, 0]
                fwd_basis = pd.read_csv(fb, header=0, index_col=0, parse_dates=True)
                rolled = pd.read_csv(rb, header=0, index_col=0, parse_dates=True)
                col = f"{mat}Y"
                if col not in fwd_basis.columns or col not in rolled.columns:
                    logger.debug("skipping %s: no %s column in the basis files", name, col)
                    continue

                # The archive banks its basis curves in DECIMALS (-0.003191 is -31.91bp) while
                # this panel documents -- and the engine's $/bp arithmetic assumes -- basis
                # points. Normalise here rather than at the point of use: leaving it decimal makes
                # every mark and every carry accrual 10,000x too small, and the book still runs.
                ret_cols[name] = ret
                fwd_cols[name] = fwd_basis[col] * 1e4
                rol_cols[name] = rolled[col] * 1e4
                if "6m" in fwd_basis.columns:
                    short_cols[name] = fwd_basis["6m"] * 1e4

        if not ret_cols:
            raise FileNotFoundError(f"no RVPF instruments found under {root}/Save")

        panel = XccyPanel(
            fwd_basis=pd.DataFrame(fwd_cols).sort_index(),
            rolled_basis=pd.DataFrame(rol_cols).sort_index(),
            returns=pd.DataFrame(ret_cols).sort_index(),
            short_basis=pd.DataFrame(short_cols).sort_index() if short_cols else None,
            meta={"source": "banked RVPF Save/", "root": str(root)},
        )
        logger.info("%s", panel.summary())
        return panel


# ----------------------------------------------------------------------- Citi
def xccy_basis_tag(
    ccy1: str,
    ccy2: str,
    tenor: str,
    forward: str = "SPOT",
    leg: str = "SPREAD_LEG",
) -> str:
    """``RATES.XCCY_OIS_SWAP.<ccy1>.<ccy2>.<forward>.<tenor>.<leg>.BASIS_SPREAD``."""
    return f"RATES.XCCY_OIS_SWAP.{ccy1.upper()}.{ccy2.upper()}.{forward.upper()}.{tenor.upper()}.{leg.upper()}.BASIS_SPREAD"


@dataclass
class CitiXccySource:
    """The live instrument, straight off Citi's forward × tenor basis grid.

    Requires a signed-in Excel with the Velocity add-in. No cross-currency history is cached in
    ARBS at the time of writing (0 of 14,438 citivelo parquets are XCCY), so the first call is a
    cold fetch and :mod:`scripts.warm_citivelo_xccy_repo` exists to do it in bulk.
    """

    pairs: Sequence[str]
    points: Dict[int, int]
    start: datetime.date
    end: datetime.date
    carry_horizon: float = 0.25
    #: Unverified conventions, exposed rather than assumed. See the module docstring.
    sign: int = 1
    leg: str = "SPREAD_LEG"
    quotes: object = None

    #: Citi's forward axis has no 9M token, so a 0.25y roll-down off a 1Y forward has no direct
    #: quote. The rolled point is interpolated in forward-time between the bracketing quotes.
    _FORWARD_TOKENS = ("SPOT", "1M", "3M", "6M", "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y",
                       "8Y", "9Y", "10Y", "11Y", "12Y", "15Y", "20Y", "25Y", "30Y")

    @staticmethod
    def _split_pair(pair: str) -> Tuple[str, str]:
        return pair[:3].upper(), pair[3:].upper()

    @classmethod
    def _forward_years(cls, token: str) -> float:
        t = token.upper()
        if t == "SPOT":
            return 0.0
        if t.endswith("M"):
            return float(t[:-1]) / 12.0
        return float(t[:-1])

    @classmethod
    def _bracket(cls, years: float) -> Tuple[str, str, float]:
        """Return (lo_token, hi_token, weight_on_hi) for a forward point in years."""
        ys = [(cls._forward_years(t), t) for t in cls._FORWARD_TOKENS]
        ys.sort()
        for (y0, t0), (y1, t1) in zip(ys, ys[1:]):
            if y0 <= years <= y1:
                w = 0.0 if y1 == y0 else (years - y0) / (y1 - y0)
                return t0, t1, w
        raise ValueError(f"forward {years}y is outside Citi's grid {ys[0][1]}..{ys[-1][1]}")

    def load(self) -> XccyPanel:
        if self.quotes is None:
            from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

            self.quotes = CitiVeloQuotes()

        wanted: Dict[str, Tuple[str, str, float]] = {}   # instrument -> (tag_lo, tag_hi, w)
        tags: List[str] = []
        for pair in self.pairs:
            c1, c2 = self._split_pair(pair)
            for fwd in sorted(self.points):
                mat = self.points[fwd]
                name = f"{pair} {fwd}Yx{mat}Y"
                f_tag = xccy_basis_tag(c1, c2, f"{mat}Y", f"{fwd}Y", self.leg)
                lo, hi, w = self._bracket(fwd - self.carry_horizon)
                r_lo = xccy_basis_tag(c1, c2, f"{mat}Y", lo, self.leg)
                r_hi = xccy_basis_tag(c1, c2, f"{mat}Y", hi, self.leg)
                wanted[name] = (r_lo, r_hi, w)
                tags += [f_tag, r_lo, r_hi]
                wanted[name + "|fwd"] = (f_tag, f_tag, 0.0)

        frame = self.quotes.frame(sorted(set(tags)), "DAILY", start=self.start, end=self.end)
        if frame is None or frame.empty:
            raise RuntimeError("Citi returned no cross-currency basis rows for the requested window")

        fwd_cols, rol_cols = {}, {}
        for name, (lo, hi, w) in wanted.items():
            if name.endswith("|fwd"):
                base = name[:-4]
                if lo in frame.columns:
                    fwd_cols[base] = self.sign * frame[lo]
                continue
            if lo in frame.columns and hi in frame.columns:
                rol_cols[name] = self.sign * ((1 - w) * frame[lo] + w * frame[hi])

        common = sorted(set(fwd_cols) & set(rol_cols))
        if not common:
            raise RuntimeError("no instrument had both a forward and a rolled-down basis quote")

        fwd_df = pd.DataFrame({k: fwd_cols[k] for k in common}).sort_index()
        rol_df = pd.DataFrame({k: rol_cols[k] for k in common}).sort_index()
        # Returns of a basis position are the basis change; the panel carries them in decimals to
        # match the banked source, so bp -> decimal.
        ret_df = fwd_df.diff() / 10_000.0

        panel = XccyPanel(
            fwd_basis=fwd_df,
            rolled_basis=rol_df,
            returns=ret_df,
            meta={
                "source": "Citi Velocity XCCY_OIS_SWAP",
                "sign": str(self.sign),
                "leg": self.leg,
                "caveat": "spread-leg currency, collateral currency and sign are UNVERIFIED",
            },
        )
        logger.info("%s", panel.summary())
        return panel
