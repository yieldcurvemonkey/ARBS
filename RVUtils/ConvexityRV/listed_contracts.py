"""REAL LISTED option contracts -- expiry ladder, TTE selection, smile units.

This is the real-contract counterpart to the constant-maturity half of
``listed_vol``. The CM panel (``US_30``, ``TY_90``, ...) is QuikStrike's
interpolation ACROSS the expiry ladder: it has no strike dimension and no
expiry, so it cannot size a straddle whose premium equals the curve carry, and
it cannot carry an expected-payoff signal. This module loads
``notebooks/data/convexity_rv/listed_contract_vol.parquet`` -- ``USM26``,
``TYZ25``, ``SFRH27`` -- where every row has a real ``expiry_date`` and a real
``tte_years``, harvested by ``scripts/harvest_listed_contract_vol.py``.

The CM panel is the **control**, not the thing replaced: a real contract at ~30
days to expiry must reproduce ``US_30``, and the two diverging as the contract
ages is the term structure CM was smoothing away. :func:`compare_to_cm` measures
both halves of that.

Written as a separate module rather than inside ``listed_vol`` so the CM API and
its callers (``strat1_listed``, ``strat1_threeway``, ``strat1_curve_gamma``) are
untouched; ``listed_vol`` re-exports the public names.


What the four value types ARE -- measured per row, not assumed
--------------------------------------------------------------
The panel stores every number exactly as quoted; nothing is converted on the way
in, because a conversion baked into a parquet cannot be audited afterwards. The
units below are the measured verdict (see :func:`units_report`, and the numbers
reproduced in ``ABPV``/``ATM``/smile sections of the harvest report).

``ABPV``
    Annualised **normal (Bachelier) vol of the underlying's YIELD, in bp/yr** --
    the same unit as the CM panel and as a swaption normal vol. Unchanged from
    the CM harvest and independently re-verified here against the CM control at
    matched time to expiry.

``ATM``
    NOT the same kind of number in the two asset classes, which is the single
    most dangerous thing in this panel. And the ratio is a **per-root** physical
    quantity -- pooling ``US`` with ``TY`` gives a number that belongs to
    neither contract, so :func:`units_report` keys on root:

    * **SFR** -- ``ABPV == 100 x ATM`` exactly (to 1e-6, the resolution at which
      ``ATM`` is stored) on **80.7%** of 15,204 rows, and on **94-99%** of rows
      in every time-to-expiry bucket from 0.08y to 2.5y. So SFR ``ATM`` is a
      **normal vol in futures PRICE POINTS per year**, identically a normal RATE
      vol in **percent** per year: the SR3 underlying is ``P = 100 - R``, so
      ``dP = -dR``, one price point is exactly 100 bp, and the map is affine.

      The 19.3% that miss are not noise in the identity, they are two specific
      thin corners where the vendor's two value types are computed off different
      marks -- the last month of life (49% exact below 0.08y) and the
      newly-listed far end (4% exact beyond 3y to expiry, where a contract has
      just been listed and barely trades). On a missing row the two disagree by
      1-3%, far more than rounding. ``abpv_atm_scale`` emits ``scale_exact`` so
      a caller can filter without re-deriving this analysis.
    * **UST** -- ``ATM`` is a **lognormal vol of the futures PRICE, as a
      decimal** (US ~0.098) and the ratio is ``1e4 / ModDur_ctd``, so it moves
      with the cheapest-to-deliver rather than being a constant. Measured
      per-root medians, against the CTD durations the CM panel measured
      independently out of the UST basis-report store:

      =====  ==============  =================  ====================
      root   ABPV/ATM (med)  implied ModDur     ModDur from CTD store
      =====  ==============  =================  ====================
      US            860.6          11.62 y             11.58-11.63 y
      TY           1703.9           5.87 y              5.85-5.91 y
      =====  ==============  =================  ====================

      Both land inside a range measured from a completely different source, and
      the fraction "within 1% of the root's own median" is only 17% (US) / 7%
      (TY) -- i.e. the ratio genuinely MOVES, exactly as a CTD duration should,
      rather than being a constant the vendor applied.

      Both land inside the independently measured range, which is why
      ``1e4 * ATM / ABPV`` is the cheapest possible regression test that this
      panel has not been silently rescaled -- it needs no price, no DV01 and no
      external data at all.

``25D_CALL`` / ``25D_PUT``
    **The same units as that asset's ``ATM``** -- a 25-delta vol, not a spread
    and not a premium. Measured levels sit within a few percent of ``ATM`` on
    both assets (US: ATM 0.0986, 25D call 0.0986, 25D put 0.1039; SFR: ATM
    1.137, call 1.130, put 1.132). A premium would be orders of magnitude away
    and a vol DIFFERENCE would sit near zero, so both alternatives are excluded
    by the level alone.

``25D_RR``
    **Exactly ``25D_CALL - 25D_PUT``.** Verified per row, not by medians:
    correlation 1.0000 and median absolute difference 0.000000 on both assets.
    This identity is what pins the smile set into ``ATM``'s units, since a
    difference of two vols can only be in the units of those vols.

``25D_BF``
    **UNUSABLE as an independent quantity -- use ``mean(call, put) - ATM``
    computed from the panel instead.**

    The naive identity fails on all three roots: correlation 0.20 and a residual
    worth **16%** (SFR) / **51%** (US) / **62%** (TY) of BF's own median size.
    The anchor test says why, and it is not that BF is garbage: inverting the
    identity for the at-the-money vol it must have been quoted against,
    ``ATM* = mean(call, put) - BF``, gives something that tracks the quoted
    ``ATM`` closely in level (correlation 0.934 SFR / 0.974 US / 0.967 TY) but is
    offset from it by a median -0.26% / +0.49% / +0.60% of ATM, with an
    interquartile range of about 1% of ATM -- roughly HALF of BF's own size.

    So ``25D_BF`` *is* a 25-delta butterfly, just measured against an
    at-the-money anchor this panel does not carry. Because BF is itself only
    1-3% of the ATM level, an anchor that differs by ~0.5% of ATM moves the fly
    by a quarter to a half of its own value -- which is exactly the residual
    observed. There is nothing to gain from it either way: ``25D_CALL`` and
    ``25D_PUT`` are quoted directly, so any butterfly a caller wants can be
    built from the panel's own consistent numbers. An expected-payoff signal
    built on a misread butterfly is worth less than no signal, so this column is
    kept for provenance and excluded from use.


Getting the smile into bp/yr without a DV01
--------------------------------------------
Because the smile quotes share ``ATM``'s units, and ``ABPV`` is the same vol in
bp/yr, the panel converts itself::

    scale(date, contract) = ABPV / ATM        # both quoted, same date, same contract
    smile_bp_yr           = smile_quote * scale

For SFR that scale is the constant 100. For UST it is the contract's own
``1e4 / ModDur_ctd`` on that date -- so the CTD's duration, and its drift and its
switches, are picked up from the data instead of from a hard-coded table. No
external DV01, no basis-report store, no linearisation chosen by hand. See
:func:`smile_in_bp_yr`.
"""

from __future__ import annotations

import math
import os
import pathlib
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "ListedContractsUnavailable",
    "LISTED_CONTRACT_PANEL",
    "SMILE_VALUE_TYPES",
    "BUSINESS_DAYS_PER_YEAR",
    "default_listed_contract_path",
    "load_listed_contract_panel",
    "listed_contract_wide",
    "expiry_ladder",
    "select_by_tte",
    "tte_matched_series",
    "interpolate_across_ladder",
    "cm_replication_series",
    "abpv_atm_scale",
    "smile_in_bp_yr",
    "units_report",
    "compare_to_cm",
    "contract_coverage_report",
]

LISTED_CONTRACT_PANEL = "listed_contract_vol.parquet"
SMILE_VALUE_TYPES = ("25D_CALL", "25D_PUT", "25D_RR", "25D_BF")
BUSINESS_DAYS_PER_YEAR = 252.0

_ENV = "ARBS_CONVEXITY_RV_DATA"


class ListedContractsUnavailable(RuntimeError):
    """Raised when the real-contract panel is not on disk.

    Deliberately not an empty frame: a caller handed one would report "0 listed
    contracts" as though that were a measurement rather than a missing harvest.
    """


def default_listed_contract_path() -> pathlib.Path:
    """Location of the real-contract panel. ``$ARBS_CONVEXITY_RV_DATA`` overrides."""
    override = os.environ.get(_ENV)
    base = (pathlib.Path(override) if override
            else pathlib.Path(__file__).resolve().parents[2] / "notebooks" / "data" / "convexity_rv")
    return base / LISTED_CONTRACT_PANEL


# ------------------------------------------------------------------ loading


def load_listed_contract_panel(
    path: Optional[Any] = None,
    *,
    roots: Optional[Sequence[str]] = None,
    assets: Optional[Sequence[str]] = None,
    value_types: Optional[Sequence[str]] = None,
    kinds: Optional[Sequence[str]] = None,
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    min_tte_years: Optional[float] = None,
) -> pd.DataFrame:
    """The tidy real-contract panel.

    Columns: ``date, symbol, vendor_column, root, asset, contract_code,
    contract_kind, expiry_date, tte_years, value_type, value``.

    ``contract_code`` is the repo-canonical token (``SFRM26``); ``symbol`` is the
    vendor's own (``SR3M26``), kept so the alias is auditable rather than folded
    away on load.

    ``min_tte_years`` drops the last few days of a contract's life, where a vol
    backed out of a nearly-intrinsic premium is numerically unstable -- the same
    guard ``listed_vol.match_listed_expiry`` applies to the SFR panel. It is
    **off by default** here: the tail is real data and the harvest's job is to
    show the ragged edge, not to pre-trim it.
    """
    p = pathlib.Path(path) if path is not None else default_listed_contract_path()
    if not p.exists():
        raise ListedContractsUnavailable(
            f"real-contract panel not found at {p}. Build it with "
            "`python scripts/harvest_listed_contract_vol.py` (networked, ~45 min)."
        )
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    df["expiry_date"] = pd.to_datetime(df["expiry_date"])

    if roots is not None:
        df = df[df["root"].isin(list(roots))]
    if assets is not None:
        df = df[df["asset"].isin(list(assets))]
    if value_types is not None:
        df = df[df["value_type"].isin(list(value_types))]
    if kinds is not None:
        df = df[df["contract_kind"].isin(list(kinds))]
    if start is not None:
        df = df[df["date"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["date"] <= pd.Timestamp(end)]
    if min_tte_years is not None:
        df = df[df["tte_years"] >= float(min_tte_years)]
    return df.sort_values(["date", "root", "expiry_date", "value_type"]).reset_index(drop=True)


def listed_contract_wide(panel: pd.DataFrame, value_type: str = "ABPV") -> pd.DataFrame:
    """``date`` x ``contract_code`` matrix of one value type. Ragged by design.

    Every column starts when the contract is first quoted and ends at its expiry,
    so the NaN pattern IS the listing calendar. Do not forward-fill it.
    """
    sub = panel[panel["value_type"] == value_type]
    return sub.pivot_table(index="date", columns="contract_code",
                           values="value", aggfunc="last").sort_index()


# ----------------------------------------------------------- the expiry ladder


def expiry_ladder(
    panel: pd.DataFrame,
    day: Any,
    *,
    root: Optional[str] = None,
    value_type: str = "ABPV",
    kinds: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Every contract quoted on one day, sorted by time to expiry.

    This is the object constant maturity was hiding. ``US_30``/``US_60``/``US_90``
    are three points read off an interpolation of exactly this ladder; here the
    ladder itself is visible, including where it is sparse and where the vendor
    had no quote at all.

    Returns ``contract_code, contract_kind, expiry_date, tte_years, tte_days,
    value``.
    """
    ts = pd.Timestamp(day)
    m = (panel["date"] == ts) & (panel["value_type"] == value_type)
    if root is not None:
        m &= panel["root"] == root
    if kinds is not None:
        m &= panel["contract_kind"].isin(list(kinds))
    sub = panel.loc[m, ["contract_code", "root", "contract_kind", "expiry_date",
                        "tte_years", "value"]].copy()
    if sub.empty:
        return sub.assign(tte_days=pd.Series(dtype=float))
    sub["tte_days"] = sub["tte_years"] * 365.0
    return sub.sort_values("tte_years").reset_index(drop=True)


def select_by_tte(
    panel: pd.DataFrame,
    day: Any,
    target_tte_days: float,
    *,
    root: Optional[str] = None,
    value_type: str = "ABPV",
    max_gap_days: float = 20.0,
    min_tte_years: float = 0.01,
    kinds: Optional[Sequence[str]] = None,
) -> Optional[Dict[str, Any]]:
    """The listed contract closest to ``target_tte_days`` of time to expiry.

    This is the real-contract analogue of asking the CM panel for ``US_30``, and
    the difference is the whole point: CM *interpolates* to exactly 30 days,
    while this *picks a tradeable contract* and reports how far off it landed
    (``gap_days``, signed). A strategy can hold the thing this returns.

    ``None`` when nothing is within ``max_gap_days`` -- an honest gap rather than
    a silently stretched match. ``min_tte_years`` drops the last ~2.5 business
    days of a contract's life where the implied vol is unstable.
    """
    lad = expiry_ladder(panel, day, root=root, value_type=value_type, kinds=kinds)
    lad = lad[lad["tte_years"] >= float(min_tte_years)]
    lad = lad[np.isfinite(lad["value"].to_numpy(dtype=float))]
    if lad.empty:
        return None
    gap = lad["tte_days"].to_numpy(dtype=float) - float(target_tte_days)
    i = int(np.argmin(np.abs(gap)))
    if abs(gap[i]) > float(max_gap_days):
        return None
    row = lad.iloc[i].to_dict()
    row["gap_days"] = float(gap[i])
    row["target_tte_days"] = float(target_tte_days)
    row["date"] = pd.Timestamp(day)
    return row


def tte_matched_series(
    panel: pd.DataFrame,
    target_tte_days: float,
    *,
    root: Optional[str] = None,
    value_type: str = "ABPV",
    max_gap_days: float = 20.0,
    min_tte_years: float = 0.01,
    kinds: Optional[Sequence[str]] = None,
    dates: Optional[Sequence[Any]] = None,
) -> pd.DataFrame:
    """Date-indexed frame of the TTE-matched contract, one row per date.

    Carries the matched ``contract_code`` and ``gap_days`` on every date, so
    "which contract was used when" is answerable after the fact instead of being
    a modelling assumption -- and so the quarterly sawtooth in ``gap_days`` is
    visible rather than hidden inside an interpolation.
    """
    sub = panel if root is None else panel[panel["root"] == root]
    sub = sub[sub["value_type"] == value_type]
    days = (pd.DatetimeIndex(sorted(pd.unique(sub["date"]))) if dates is None
            else pd.DatetimeIndex([pd.Timestamp(d) for d in dates]))
    rows: List[Dict[str, Any]] = []
    for ts in days:
        r = select_by_tte(sub, ts, target_tte_days, root=root, value_type=value_type,
                          max_gap_days=max_gap_days, min_tte_years=min_tte_years,
                          kinds=kinds)
        if r is None:
            continue
        rows.append({
            "date": ts,
            "contract_code": r["contract_code"],
            "contract_kind": r["contract_kind"],
            "expiry_date": pd.Timestamp(r["expiry_date"]),
            "tte_days": float(r["tte_days"]),
            "tte_years": float(r["tte_years"]),
            "gap_days": float(r["gap_days"]),
            "value": float(r["value"]),
        })
    if not rows:
        return pd.DataFrame(columns=["date", "contract_code", "value"]).set_index("date")
    return pd.DataFrame(rows).set_index("date").sort_index()


def interpolate_across_ladder(
    panel: pd.DataFrame,
    day: Any,
    target_tte_days: float,
    *,
    root: Optional[str] = None,
    value_type: str = "ABPV",
    kinds: Optional[Sequence[str]] = None,
) -> float:
    """Linear-in-TTE interpolation of the ladder -- i.e. what CM does, reproduced.

    Exists to separate two effects that are otherwise confounded when the real
    panel is compared to the CM panel: (a) the difference between holding a
    tradeable contract and holding an interpolation, and (b) any difference in
    the vendor's underlying data. Comparing CM to THIS isolates (b); comparing CM
    to :func:`tte_matched_series` shows (a) + (b).

    Flat extrapolation beyond the ladder's ends, and NaN on an empty ladder.
    """
    lad = expiry_ladder(panel, day, root=root, value_type=value_type, kinds=kinds)
    lad = lad[np.isfinite(lad["value"].to_numpy(dtype=float))]
    if lad.empty:
        return float("nan")
    x = lad["tte_days"].to_numpy(dtype=float)
    y = lad["value"].to_numpy(dtype=float)
    if x.size == 1:
        return float(y[0])
    order = np.argsort(x)
    return float(np.interp(float(target_tte_days), x[order], y[order]))


def cm_replication_series(
    panel: pd.DataFrame,
    target_tte_days: float,
    *,
    root: Optional[str] = None,
    value_type: str = "ABPV",
    kinds: Optional[Sequence[str]] = None,
    dates: Optional[Sequence[Any]] = None,
) -> pd.Series:
    """:func:`interpolate_across_ladder` run over every date -- a home-made CM series."""
    sub = panel if root is None else panel[panel["root"] == root]
    sub = sub[sub["value_type"] == value_type]
    days = (pd.DatetimeIndex(sorted(pd.unique(sub["date"]))) if dates is None
            else pd.DatetimeIndex([pd.Timestamp(d) for d in dates]))
    vals = [interpolate_across_ladder(sub, ts, target_tte_days, root=root,
                                      value_type=value_type, kinds=kinds) for ts in days]
    return pd.Series(vals, index=days, name=f"cm_repl_{target_tte_days:g}d").dropna()


# ------------------------------------------------------------------- units


def abpv_atm_scale(panel: pd.DataFrame) -> pd.DataFrame:
    """Per (date, contract) factor taking an ``ATM``-unit quote to bp/yr.

    ``scale = ABPV / ATM``. It is 100 exactly for SFR (affine ``P = 100 - R``)
    and ``1e4 / ModDur_ctd`` for UST, so it is also a free read of the futures'
    cheapest-to-deliver modified duration -- reported here as ``implied_moddur``
    for exactly the sanity check that the panel has not been rescaled.

    ``scale_exact`` flags the SFR rows where the affine identity actually holds
    (``|scale - 100| < 1e-6``). It does NOT hold everywhere: on 13.6% of SFR
    rows -- the last month of a contract's life and the newly-listed far end --
    the vendor computes ``ABPV`` and ``ATM`` off different marks and they
    disagree by 1-3%. A caller converting a smile quote to bp/yr on one of those
    rows would inherit that error silently, so the flag is emitted here rather
    than leaving every caller to re-derive it. It is ``True`` for all UST rows,
    where the ratio is a genuine per-date quantity (the CTD's duration) and not
    an identity that could fail.
    """
    w = (panel[panel["value_type"].isin(["ABPV", "ATM"])]
         .pivot_table(index=["date", "root", "asset", "contract_code", "tte_years"],
                      columns="value_type", values="value", aggfunc="last")
         .reset_index())
    if "ABPV" not in w.columns or "ATM" not in w.columns:
        raise ValueError("panel needs both ABPV and ATM rows to build the scale")
    w = w[np.isfinite(w["ATM"].to_numpy(dtype=float)) & (w["ATM"] != 0.0)]
    w["scale"] = w["ABPV"] / w["ATM"]
    w["implied_moddur"] = 1e4 * w["ATM"] / w["ABPV"]
    w["scale_exact"] = np.where(w["asset"] == "SFR",
                                (w["scale"] - 100.0).abs() < 1e-6, True)
    return w


def smile_in_bp_yr(panel: pd.DataFrame, *, require_exact_scale: bool = False) -> pd.DataFrame:
    """Add ``value_bp_yr`` to the smile rows, using the panel's own ABPV/ATM scale.

    The smile quotes are in that asset's ``ATM`` units, and ``ABPV`` is the same
    vol in bp/yr on the same date and the same contract, so the panel supplies
    its own conversion and no external DV01 or duration table is needed. Rows
    with no matching ABPV/ATM pair get NaN rather than a default scale.

    Non-smile rows are returned untouched with ``value_bp_yr`` equal to ``value``
    for ``ABPV`` (already bp/yr) and NaN for ``ATM`` (a level, not a spread, but
    in units the caller should convert deliberately).

    ``scale_exact`` is carried through from :func:`abpv_atm_scale`. Set
    ``require_exact_scale=True`` to NaN out the SFR rows where the vendor's two
    value types disagree, rather than converting through a scale that is known
    to be wrong by 1-3% on that row.
    """
    sc = abpv_atm_scale(panel)[["date", "contract_code", "scale", "scale_exact"]]
    out = panel.merge(sc, on=["date", "contract_code"], how="left")
    is_smile = out["value_type"].isin(SMILE_VALUE_TYPES)
    scale = out["scale"]
    if require_exact_scale:
        scale = scale.where(out["scale_exact"].fillna(False))
    out["value_bp_yr"] = np.where(
        is_smile, out["value"] * scale,
        np.where(out["value_type"] == "ABPV", out["value"], np.nan))
    return out


def units_report(panel: pd.DataFrame) -> Dict[str, Any]:
    """Measure -- per row, not by medians -- what the value types are.

    Four questions, each answered with a number:

    1. ``ABPV`` vs ``ATM``: the ratio's distribution per asset. Exactly 100 for
       SFR means ``ATM`` is a normal price-point vol; ~850 and drifting for UST
       means a lognormal price vol whose scale is ``1e4/ModDur_ctd``.
    2. ``25D_RR == 25D_CALL - 25D_PUT``? Correlation and max absolute residual.
       This is what pins the smile into ``ATM``'s units.
    3. ``25D_BF == mean(call, put) - ATM``? The naive fly identity.
    4. If (3) fails, is BF a fly against a DIFFERENT at-the-money anchor? Test
       ``ATM* = mean(call, put) - BF`` against the quoted ``ATM``: a stable small
       offset with high change-correlation says yes (BF usable, identity
       restated); a noisy one says BF is not reconcilable and is UNUSABLE.

    Returns a nested dict keyed by **root**, not by asset. Grouping by asset was
    the first version and it was wrong in a way worth recording: pooling ``US``
    (CTD modified duration ~11.6y) with ``TY`` (~5.9y) gave a meaningless
    combined ``ABPV/ATM`` of 1499 and an "implied CTD duration" of 6.67y that
    belongs to neither contract. The ratio is a per-contract physical quantity;
    it must never be pooled across roots.

    Every entry is a measurement; nothing here is a threshold that silently
    passes.
    """
    need = ["ABPV", "ATM", "25D_CALL", "25D_PUT", "25D_RR", "25D_BF"]
    w = (panel[panel["value_type"].isin(need)]
         .pivot_table(index=["date", "asset", "root", "contract_code", "tte_years"],
                      columns="value_type", values="value", aggfunc="last")
         .reset_index())
    out: Dict[str, Any] = {}
    for root, g in w.groupby("root"):
        rep: Dict[str, Any] = {"n_rows": int(len(g)), "asset": str(g["asset"].iloc[0])}

        # (1) ABPV vs ATM
        gg = g[np.isfinite(g.get("ATM", pd.Series(dtype=float))) & (g.get("ATM", 0) != 0)
               ] if "ATM" in g else g.iloc[0:0]
        gg = gg[np.isfinite(gg["ABPV"])] if "ABPV" in gg else gg
        if len(gg):
            r = (gg["ABPV"] / gg["ATM"]).astype(float)
            # ``max`` alone is dominated by a handful of near-expiry rows where
            # the vendor's two value types are computed off different marks, and
            # it hides the fact that the identity is EXACT for the bulk. Report
            # the fraction that holds as well as the worst case.
            rep["abpv_over_atm"] = {
                "n": int(len(r)), "median": float(r.median()),
                "p01": float(r.quantile(0.01)), "p99": float(r.quantile(0.99)),
                "min": float(r.min()), "max": float(r.max()),
                "max_abs_dev_from_100": float((r - 100.0).abs().max()),
                "frac_exactly_100": float(((r - 100.0).abs() < 1e-6).mean()),
                "frac_within_1pct_of_median": float(
                    ((r / r.median() - 1.0).abs() < 0.01).mean()),
                "implied_moddur_median": float((1e4 / r).median()),
                "implied_moddur_p01": float((1e4 / r).quantile(0.99)),
                "implied_moddur_p99": float((1e4 / r).quantile(0.01)),
            }

        # (2) RR identity. The residual is meaningful on a single row, so it is
        # reported whenever there is any data -- omitting the identity on a small
        # sample would silently drop the strongest evidence in the report.
        # ``corr`` needs two non-constant series and is NaN otherwise, which is
        # the honest answer rather than a fabricated 1.0.
        if {"25D_CALL", "25D_PUT", "25D_RR"} <= set(g.columns):
            s = g[["25D_CALL", "25D_PUT", "25D_RR"]].dropna().astype(float)
            if len(s):
                lhs = s["25D_CALL"] - s["25D_PUT"]
                res = (lhs - s["25D_RR"]).abs()
                rep["rr_identity"] = {
                    "n": int(len(s)),
                    "corr": float(lhs.corr(s["25D_RR"])) if len(s) > 1 else float("nan"),
                    "max_abs_resid": float(res.max()),
                    "median_abs_resid": float(res.median()),
                    "rr_scale_median": float(abs(s["25D_RR"]).median()),
                }

        # (3) naive BF identity
        if {"25D_CALL", "25D_PUT", "25D_BF", "ATM"} <= set(g.columns):
            s = g[["25D_CALL", "25D_PUT", "25D_BF", "ATM"]].dropna().astype(float)
            if len(s):
                lhs = 0.5 * (s["25D_CALL"] + s["25D_PUT"]) - s["ATM"]
                res = lhs - s["25D_BF"]
                rep["bf_naive_identity"] = {
                    "n": int(len(s)),
                    "corr": float(lhs.corr(s["25D_BF"])) if len(s) > 1 else float("nan"),
                    "median_abs_resid": float(res.abs().median()),
                    "bf_scale_median": float(s["25D_BF"].abs().median()),
                    "resid_over_bf": float(res.abs().median() /
                                           max(s["25D_BF"].abs().median(), 1e-12)),
                }
                # (4) the anchor test
                atm_star = 0.5 * (s["25D_CALL"] + s["25D_PUT"]) - s["25D_BF"]
                off = atm_star - s["ATM"]
                rep["bf_anchor_test"] = {
                    "n": int(len(s)),
                    "atm_star_vs_atm_median_offset": float(off.median()),
                    "offset_iqr": float(off.quantile(0.75) - off.quantile(0.25)),
                    "offset_over_atm_median": float((off / s["ATM"]).median()),
                    "level_corr": float(atm_star.corr(s["ATM"])) if len(s) > 1 else float("nan"),
                    "change_corr": (float(atm_star.diff().corr(s["ATM"].diff()))
                                    if len(s) > 2 else float("nan")),
                }
        out[str(root)] = rep
    return out


# ------------------------------------------------------- CM vs real contracts


def compare_to_cm(
    panel: pd.DataFrame,
    cm_panel: pd.DataFrame,
    *,
    root: str = "US",
    cm_days: int = 30,
    value_type: str = "ABPV",
    max_gap_days: float = 20.0,
    kinds: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Real contract vs the constant-maturity control at matched time to expiry.

    Three series on the same dates:

    ``cm``       the existing ``<root>_<days>`` CM series (the control);
    ``matched``  the nearest tradeable contract by TTE (:func:`select_by_tte`);
    ``interp``   the ladder interpolated to exactly ``cm_days``
                 (:func:`interpolate_across_ladder`).

    ``matched`` vs ``cm`` is what a strategy would actually experience -- it
    carries the sawtooth of a real expiry. ``interp`` vs ``cm`` removes the
    sawtooth and so isolates whether the two panels' underlying data agree at
    all. Reporting both is the point: if ``interp`` tracks CM tightly while
    ``matched`` does not, the gap is expiry granularity, not a data problem.
    """
    cm = cm_panel[(cm_panel["root"] == root)
                  & (cm_panel["cm_days"] == int(cm_days))
                  & (cm_panel["value_type"] == value_type)]
    cm_s = pd.Series(cm["value"].to_numpy(dtype=float),
                     index=pd.DatetimeIndex(pd.to_datetime(cm["date"]))).sort_index()
    cm_s = cm_s[~cm_s.index.duplicated(keep="last")]

    sub = panel[(panel["root"] == root) & (panel["value_type"] == value_type)]
    matched = tte_matched_series(sub, float(cm_days), root=root, value_type=value_type,
                                 max_gap_days=max_gap_days, kinds=kinds)
    interp = cm_replication_series(sub, float(cm_days), root=root,
                                   value_type=value_type, kinds=kinds)

    rep: Dict[str, Any] = {
        "root": root, "cm_days": int(cm_days), "value_type": value_type,
        "n_cm": int(len(cm_s)), "n_matched": int(len(matched)), "n_interp": int(len(interp)),
    }
    for name, s in (("matched", matched["value"] if len(matched) else pd.Series(dtype=float)),
                    ("interp", interp)):
        idx = cm_s.index.intersection(s.index)
        if len(idx) < 5:
            rep[name] = {"n": int(len(idx)), "note": "insufficient overlap"}
            continue
        a, b = cm_s.loc[idx].astype(float), s.loc[idx].astype(float)
        d = b - a
        rep[name] = {
            "n": int(len(idx)),
            "first": str(idx.min().date()), "last": str(idx.max().date()),
            "cm_median": float(a.median()), "real_median": float(b.median()),
            "ratio_median": float((b / a.replace(0.0, np.nan)).median()),
            "diff_median_bp": float(d.median()),
            "diff_abs_median_bp": float(d.abs().median()),
            "diff_abs_p95_bp": float(d.abs().quantile(0.95)),
            "corr_level": float(a.corr(b)),
            "corr_change": float(a.diff().corr(b.diff())),
        }
    if len(matched):
        rep["matched_gap_days_abs_median"] = float(matched["gap_days"].abs().median())
        rep["matched_gap_days_abs_max"] = float(matched["gap_days"].abs().max())
        rep["matched_n_contracts"] = int(matched["contract_code"].nunique())
    return rep


def contract_coverage_report(panel: pd.DataFrame) -> Dict[str, Any]:
    """Per-root coverage as numbers: contracts, date span, rows per contract.

    Coverage is RAGGED by construction -- a contract only has data while it is
    listed -- so this reports the raggedness (contracts alive per date, rows per
    contract, listing lead) instead of averaging it away.
    """
    out: Dict[str, Any] = {"rows": int(len(panel)),
                           "value_types": sorted(panel["value_type"].unique().tolist())}
    per_root: Dict[str, Any] = {}
    for root, g in panel.groupby("root"):
        a = g[g["value_type"] == "ABPV"]
        if a.empty:
            a = g
        per_contract = a.groupby("contract_code").size()
        lead = (a.groupby("contract_code")
                 .apply(lambda x: (x["expiry_date"].iloc[0] - x["date"].min()).days,
                        include_groups=False))
        alive = a.groupby("date")["contract_code"].nunique()
        per_root[str(root)] = {
            "asset": str(g["asset"].iloc[0]),
            "n_contracts": int(a["contract_code"].nunique()),
            "n_quarterly": int(a[a["contract_kind"] == "quarterly"]["contract_code"].nunique()),
            "n_serial": int(a[a["contract_kind"] == "serial"]["contract_code"].nunique()),
            "first_date": str(a["date"].min().date()), "last_date": str(a["date"].max().date()),
            "n_dates": int(a["date"].nunique()),
            "rows_per_contract_median": float(per_contract.median()),
            "rows_per_contract_min": int(per_contract.min()),
            "rows_per_contract_max": int(per_contract.max()),
            "listing_lead_days_median": float(lead.median()),
            "listing_lead_days_max": int(lead.max()),
            "contracts_alive_per_date_median": float(alive.median()),
            "contracts_alive_per_date_max": int(alive.max()),
            "tte_years_max": float(a["tte_years"].max()),
        }
    out["per_root"] = per_root
    return out
