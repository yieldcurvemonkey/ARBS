"""Transaction costs and repo carry for the GSS butterfly book.

Two things the original had that ARBS did not, and that this module supplies:

* a **TTM-bucketed one-way bid/offer** in bp of yield (``GSS_module.fly_tcost``);
* a **repo curve**, which ARBS carries nowhere. The tag grammar was recovered from the Citi
  Velocity workbook the user supplied and is

      RATES.REPO.USD.<collateral>.SPOT.<tenor>

  with ``collateral`` in ``USTREASGC`` (general collateral) or ``USD{5,10,30}YOTR`` (the
  on-the-run specials) and ``tenor`` in ON, TN, 1W, 1M, 3M, 6M, 9M, 1Y, 2Y, 3Y, 4Y, 5Y, 7Y, 10Y.
  Having the OTR specials as well as GC matters: an on-the-run bond finances well below GC, which
  is exactly why the GSS universe filter drops it.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from BT.gss_fly.config import REPO_BASIS, CostConfig

__all__ = [
    "REPO_TENORS",
    "REPO_COLLATERAL",
    "repo_tag",
    "repo_tag_grid",
    "fly_tcost_bp",
    "repo_carry_bp",
    "RepoCurve",
    "load_repo_from_workbook",
]

REPO_TENORS = ("ON", "TN", "1W", "1M", "3M", "6M", "9M", "1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y")
REPO_COLLATERAL = ("USTREASGC", "USD5YOTR", "USD10YOTR", "USD30YOTR")


def repo_tag(collateral: str = "USTREASGC", tenor: str = "ON", currency: str = "USD") -> str:
    """``RATES.REPO.USD.USTREASGC.SPOT.ON`` and friends."""
    coll = str(collateral).strip().upper()
    ten = str(tenor).strip().upper()
    if coll not in REPO_COLLATERAL:
        raise ValueError(f"unknown repo collateral {collateral!r}; expected one of {REPO_COLLATERAL}")
    if ten not in REPO_TENORS:
        raise ValueError(f"unknown repo tenor {tenor!r}; expected one of {REPO_TENORS}")
    return f"RATES.REPO.{currency.upper()}.{coll}.SPOT.{ten}"


def repo_tag_grid(
    collaterals: Iterable[str] = REPO_COLLATERAL,
    tenors: Iterable[str] = REPO_TENORS,
    currency: str = "USD",
) -> list:
    return [repo_tag(c, t, currency) for c in collaterals for t in tenors]


# --------------------------------------------------------------------------- transaction costs
def _bucket_cost(ttm: float, table: Dict[float, float]) -> float:
    """One-way half-spread for a bond at ``ttm``, from a lower-edge-keyed bucket table.

    ``np.digitize`` on the sorted edges, clamped at both ends — the same lookup
    ``GSS_module.fly_tcost`` performs, minus its off-by-one guard which is folded into the clamp.
    """
    edges = np.array(sorted(table.keys()), dtype=float)
    idx = int(np.digitize([float(ttm)], edges, right=False)[0]) - 1
    idx = min(max(idx, 0), len(edges) - 1)
    return float(table[edges[idx]])


def fly_tcost_bp(ttms: Sequence[float], weights: Sequence[float], cfg: Optional[CostConfig] = None) -> float:
    """One-way cost of putting the fly on, in bp of fly yield.

    ``belly_only`` reproduces the original — it returns the belly's bucket cost and nothing else,
    on the stated reasoning that the fly's cost "is given by the cost of buying / selling the body
    bond". ``all`` (the default here) charges every leg in proportion to |weight|, which is what a
    three-legged package actually costs to execute.
    """
    cfg = cfg or CostConfig()
    ttms = list(ttms)
    if cfg.cost_legs == "belly_only":
        return _bucket_cost(ttms[1], cfg.half_spread_bp)
    return float(sum(abs(w) * _bucket_cost(t, cfg.half_spread_bp) for t, w in zip(ttms, weights)))


# --------------------------------------------------------------------------- repo
class RepoCurve:
    """A dates × tenors repo panel with an as-of accessor.

    ``rate_pct(date, tenor)`` returns the last quote at or before ``date`` — repo does not print
    every day on every tenor, and a forward-filled read is the honest one.
    """

    def __init__(self, frame: pd.DataFrame, collateral: str = "USTREASGC"):
        df = frame.copy()
        df.index = pd.to_datetime(df.index)
        self.frame = df.sort_index()
        self.collateral = collateral

    def rate_pct(self, when, tenor: str = "ON") -> float:
        ten = str(tenor).strip().upper()
        if ten not in self.frame.columns:
            raise KeyError(f"tenor {tenor!r} not in repo curve; have {list(self.frame.columns)}")
        s = self.frame[ten].dropna()
        s = s.loc[: pd.Timestamp(when)]
        if s.empty:
            return float("nan")
        return float(s.iloc[-1])

    def __repr__(self) -> str:
        return (
            f"<RepoCurve {self.collateral} {len(self.frame)} days "
            f"{self.frame.index.min().date()}..{self.frame.index.max().date()} "
            f"{len(self.frame.columns)} tenors>"
        )


def load_repo_from_workbook(path, collateral: str = "USTREASGC") -> RepoCurve:
    """Read a repo panel out of a Citi Velocity Excel export.

    The workbook the user supplied has the tag in row 2 and dates down column A; every
    ``RATES.REPO.<ccy>.<collateral>.SPOT.<tenor>`` column for the requested collateral is kept and
    renamed to its bare tenor. This is the offline path — the online one is
    :func:`repo_tag_grid` through the Citi timeseries fetcher.
    """
    path = Path(path)
    raw = pd.read_excel(path, sheet_name=0, header=None)

    # Pick the row with the MOST RATES.REPO cells, not the first row containing one. Row 0 of a
    # Velocity export holds the `=CVTSHIST("RATES.REPO.USD...,RATES.REPO.USD...")` formula as a
    # single string, so "first row that mentions RATES.REPO" selects the formula and then parses a
    # comma-joined tag list as one column name — every tenor lookup misses and the whole workbook
    # reads as having no columns for the collateral.
    counts = {
        r: int(raw.iloc[r].astype(str).str.contains(r"RATES\.REPO\.", na=False, regex=True).sum())
        for r in range(min(8, len(raw)))
    }
    header_row = max(counts, key=lambda r: counts[r]) if counts else None
    if header_row is None or counts.get(header_row, 0) == 0:
        raise ValueError(f"no RATES.REPO header row found in {path}")

    headers = raw.iloc[header_row].astype(str)
    body = raw.iloc[header_row + 1 :].copy()
    dates = pd.to_datetime(body.iloc[:, 0], errors="coerce")

    cols = {}
    want = f".{collateral.upper()}.SPOT."
    for j, h in headers.items():
        if want not in h:
            continue
        tenor = h.split(want)[-1].split(" ")[0].strip().upper()
        if tenor in REPO_TENORS:
            cols[tenor] = pd.to_numeric(body.iloc[:, j], errors="coerce").to_numpy()

    if not cols:
        raise ValueError(f"no columns for collateral {collateral!r} in {path}")

    frame = pd.DataFrame(cols, index=dates).dropna(how="all")
    frame = frame[~frame.index.isna()]
    return RepoCurve(frame.sort_index(), collateral=collateral)


def repo_carry_bp(
    rate_pct: float,
    days_held: float,
    weights: Optional[Sequence[float]] = None,
) -> float:
    """Financing drag over ``days_held``, in bp of fly yield.

    ``GSS_module`` books ``Repo = -(r / 360) * days`` and then subtracts it inside the yield
    change, so the sign convention is: a **positive repo rate produces a negative number here**,
    and holding the position longer costs more.

    The weights argument scales the drag by the net financed position ``Σw``. For a GSS fly that
    sum is zero by construction (``w_L + w_R = -1``, ``w_B = +1``), so a maturity-weighted fly is
    close to self-financing and the drag is small — which is precisely why the original could get
    away with a single flat rate. It is exposed so a differently-weighted book still prices it.
    """
    if not np.isfinite(rate_pct):
        return 0.0
    scale = 1.0 if weights is None else abs(float(np.sum(weights)))
    return -(float(rate_pct) / REPO_BASIS) * float(days_held) * scale
