"""Tie our listed-vol panels out against the J.P. Morgan package parquets.

Everything here is deliberately small and pure so the notebook
``notebooks/backtests/convexity_rv/jpm_package_tieout.py`` and
``tests/test_convexity_rv_jpm_tieout.py`` exercise the *same* code rather than
two paraphrases of it.

The date convention, decided by measurement not assertion
--------------------------------------------------------
Both frames carry two dates.  Ours (``listed_contract_vol``) is a Barchart EOD
mark on the trading date; JPM's is a 3:00 pm NY close on ``as_of``, filed for
use on ``business_date`` (the next business day).  **Join on ``as_of``.**

Grading the three candidates on 21,054 deduped Treasury rows:

==================  ==========  ============  ==============  ==========
key / lag           n joined    med abs err    ratio IQR       as_of+days
                                (ATMx100 vs                    == expiry
                                 JPM pct)
==================  ==========  ============  ==============  ==========
``as_of``  +0        12,880      0.0062        0.00145         100.000%
``as_of``  -1        10,089      0.1711        0.04309           0.000%
``as_of``  +1         9,978      0.1684        0.04238           0.000%
``business_date`` +0 12,602      0.1698        0.04367           0.000%
``business_date`` -1 10,262      0.0063        0.00144          99.211%
==================  ==========  ============  ==============  ==========

``business_date - 1`` is *nearly* ``as_of`` -- they differ only across
weekends and holidays -- which is why it looks almost as good and is still
wrong: it drops 2.2% of the joinable rows and misses the expiry identity on
0.8% of them.  A one-day error costs only ~2% of the vol level in the median,
which is exactly the "close enough to look right" failure; the dispersion
(a 30x wider ratio IQR) and the expiry identity are what give it away.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "DATA_DIR",
    "PRODUCT_TO_ROOT",
    "MONTH_CODE",
    "SQRT_252",
    "contract_code",
    "dedupe",
    "load_jpm_treasury",
    "load_jpm_swaptions",
    "load_listed_pivot",
    "join_treasury",
    "implied_moddur",
    "swaption_grid",
    "interp_swaption",
    "modal_expiry",
    "grade_expiry_rule",
]

DATA_DIR = Path(__file__).resolve().parents[2] / "notebooks" / "data" / "convexity_rv"

#: JPM's Treasury Volatility Summary product labels -> our CME root.
#: ``5 Year Treasury Note`` is carried because JPM prints it, but note that
#: ``listed_contract_vol`` holds no FV contracts at all -- FV can only be
#: graded through the constant-maturity control ``ust_listed_vol``.
PRODUCT_TO_ROOT: dict[str, str] = {
    "Treasury Bond": "US",
    "Treasury Note": "TY",
    "5 Year Treasury Note": "FV",
}

#: CME month codes, 1-based.
MONTH_CODE: dict[int, str] = dict(zip(range(1, 13), "FGHJKMNQUVXZ"))

SQRT_252 = float(np.sqrt(252.0))


def contract_code(root: str, expiry_ym: str) -> str:
    """``("US", "2023-07") -> "USN23"``.

    JPM's column header ``Jul 23`` is the **option contract month**, not the
    month the option expires in: on 2023-06-08 the ``Jul 23`` column carries
    ``Days to Expiration = 15``, i.e. 2023-06-23, which is USN23's last
    trading day.  That makes the mapping a pure relabelling and lets the join
    key stay independent of any expiry rule -- joining on the expiry *date*
    would make the expiry test circular, because a contract whose expiry we
    got wrong would silently drop out of the join instead of being counted.
    """
    y, m = str(expiry_ym).split("-")
    return f"{root}{MONTH_CODE[int(m)]}{y[2:]}"


def dedupe(df: pd.DataFrame, keys: Sequence[str]) -> tuple[pd.DataFrame, int]:
    """Drop repeated ``keys``, returning ``(frame, n_dropped)``.

    The archive re-publishes a stale page on some days: the file
    ``2026-04-29_...pdf`` carries a Treasury Volatility Summary whose own page
    header still reads 2026-03-16, identical cell for cell to the one in
    ``2026-03-17_...pdf``.  Four files share that one page.  The duplicates
    are byte-identical in every value column, so keeping the first is lossless
    -- but leaving them in would silently weight those dates 4x in every
    statistic below.
    """
    n0 = len(df)
    out = df.drop_duplicates(subset=list(keys), keep="first").copy()
    return out, n0 - len(out)


def load_jpm_treasury(path: Path | str | None = None) -> pd.DataFrame:
    """``jpm_pkg_treasury_vol.parquet``, deduped, with ``root``/``contract_code``."""
    p = Path(path) if path else DATA_DIR / "jpm_pkg_treasury_vol.parquet"
    df = pd.read_parquet(p)
    df, _ = dedupe(df, ["as_of", "product", "expiry_ym"])
    df["root"] = df["product"].map(PRODUCT_TO_ROOT)
    df["contract_code"] = [contract_code(r, ym) if isinstance(r, str) else None
                           for r, ym in zip(df["root"], df["expiry_ym"])]
    return df


def load_jpm_swaptions(path: Path | str | None = None) -> pd.DataFrame:
    """``jpm_pkg_swaption_vol.parquet``, deduped on (as_of, tenor, maturity)."""
    p = Path(path) if path else DATA_DIR / "jpm_pkg_swaption_vol.parquet"
    df = pd.read_parquet(p)
    df, _ = dedupe(df, ["as_of", "tenor_years", "maturity_months"])
    return df


def load_listed_pivot(path: Path | str | None = None) -> pd.DataFrame:
    """``listed_contract_vol.parquet`` with ``value_type`` pivoted to columns."""
    p = Path(path) if path else DATA_DIR / "listed_contract_vol.parquet"
    lv = pd.read_parquet(p)
    return lv.pivot_table(
        index=["date", "root", "contract_code", "expiry_date", "tte_years"],
        columns="value_type", values="value").reset_index()


def join_treasury(jpm: pd.DataFrame, listed: pd.DataFrame, *,
                  date_col: str = "as_of", lag_days: int = 0) -> pd.DataFrame:
    """Inner-join JPM Treasury rows to our listed panel on (date, root, contract).

    ``date_col``/``lag_days`` exist so the date convention can be *measured*
    rather than assumed: the caller runs the join at every candidate and reads
    off which one wins.
    """
    j = jpm.copy()
    j["join_date"] = j[date_col] + pd.to_timedelta(lag_days, unit="D")
    m = j.merge(listed, left_on=["join_date", "root", "contract_code"],
                right_on=["date", "root", "contract_code"],
                how="inner", suffixes=("", "_listed"))
    m["jpm_implied_expiry"] = m["join_date"] + pd.to_timedelta(m["days_cal"], unit="D")
    return m


def implied_moddur(price_vol_pct: pd.Series | np.ndarray,
                   yield_vol_bp_yr: pd.Series | np.ndarray) -> np.ndarray:
    """Modified duration implied by a price vol and a yield vol.

    A lognormal price vol :math:`\\sigma_P` and a normal yield vol
    :math:`\\sigma_y` (bp/yr) on the same option satisfy
    :math:`\\sigma_P = D \\cdot \\sigma_y / 10^4`, so
    :math:`D = \\sigma_P \\cdot 10^4 / \\sigma_y`.  With the price vol in
    percent that is ``pct * 100 / bp_per_year``.

    Feeding it JPM's printed percent and *our* ABPV makes the recovered
    duration genuinely cross-vendor; feeding it our own ATM and ABPV only
    re-derives the identity our panel was built on.
    """
    p = np.asarray(price_vol_pct, dtype=float)
    y = np.asarray(yield_vol_bp_yr, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(y > 0, p * 100.0 / y, np.nan)


def swaption_grid(sw: pd.DataFrame, value: str = "impl_bp_day") -> pd.DataFrame:
    """``as_of`` x (tenor_years, maturity_months) grid of the OTC swaption page."""
    return sw.pivot_table(index="as_of", columns=["tenor_years", "maturity_months"],
                          values=value)


def interp_swaption(grid: pd.DataFrame, dates: Iterable, tenor_years: Iterable,
                    maturity_months: Iterable) -> np.ndarray:
    """Bilinear read of the swaption grid at (log tenor, maturity in months).

    JPM prints a 5x4 grid -- tenors 1/2/5/10/30yr, maturities 1/3/6/12m -- and
    the things we want to compare it to sit between the nodes (a 30-day
    constant-maturity point is 0.99 months; a TY option matched to the swap
    curve sits at 7yr).  Tenor is interpolated in **log** years because that
    is the axis on which swaption vol is close to linear; maturity is
    interpolated linearly.  Both are clipped to the printed corners rather
    than extrapolated.
    """
    ten_nodes = np.array(sorted({t for t, _ in grid.columns}), dtype=float)
    mat_nodes = np.array(sorted({m for _, m in grid.columns}), dtype=float)
    cols = [(t, m) for t in ten_nodes for m in mat_nodes]
    arr = grid.reindex(columns=pd.MultiIndex.from_tuples(cols)).to_numpy(float)
    arr = arr.reshape(len(grid.index), len(ten_nodes), len(mat_nodes))
    pos = grid.index.get_indexer(pd.DatetimeIndex(list(dates)))
    ten = np.asarray(list(tenor_years), dtype=float)
    mat = np.asarray(list(maturity_months), dtype=float)
    lt = np.log(ten_nodes)
    out = np.full(len(pos), np.nan)
    for i, p in enumerate(pos):
        if p < 0:
            continue
        g = arr[p]
        if np.isnan(g).any():
            continue
        col = np.array([np.interp(mat[i], mat_nodes, g[k])
                        for k in range(len(ten_nodes))])
        out[i] = np.interp(np.log(ten[i]), lt, col)
    return out


def modal_expiry(jpm: pd.DataFrame) -> pd.DataFrame:
    """Per contract, the option expiry JPM's ``Days to Expiration`` implies.

    ``as_of + days_cal`` is computed on every date the contract appears and
    the **mode** is taken, so one stale or mis-set page cannot move the
    verdict.  ``n_dates`` and ``n_modal`` are returned so a contract with a
    weak consensus is visible instead of silently equal-weighted.
    """
    j = jpm.dropna(subset=["days_cal", "contract_code"]).copy()
    j["implied"] = j["as_of"] + pd.to_timedelta(j["days_cal"], unit="D")
    g = j.groupby(["root", "contract_code"])["implied"]
    out = g.agg(n_dates="size",
                jpm_expiry=lambda s: s.mode().iloc[0],
                n_modal=lambda s: int(s.value_counts().iloc[0])).reset_index()
    return out


def grade_expiry_rule(codes: Sequence[str], rule: Callable[[str], object]
                      ) -> pd.DataFrame:
    """Apply an expiry rule to contract codes, returning ``code``/``expiry``/``error``."""
    rows = []
    for c in codes:
        try:
            rows.append({"contract_code": c,
                         "expiry": pd.Timestamp(rule(c)), "error": None})
        except Exception as exc:  # noqa: BLE001 - a rule that raises is a failure too
            rows.append({"contract_code": c, "expiry": pd.NaT,
                         "error": f"{type(exc).__name__}: {exc}"})
    return pd.DataFrame(rows)
