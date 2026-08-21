r"""What explains the convexity adjustment besides volatility.

Citi's own answer, printed rather than argued:

    "Dealers, who are on the other side of the shorts established by hedge funds
    and asset managers, have ended up with significant long ED positions
    (Figure 2). Convexity adjustments have therefore widened to compensate
    dealers for this concentration risk."

and the regression behind it — *Sell Eurodollar convexity in Blues*, Figure 4,
monthly 2013-01-01 → 2017-12-26:

    d(Blues CA − model) on d(dealer positioning):  y = 2e−06·x − 0.1053,
    R² = 0.2724

That is a **published, dated, out-of-sample target** for the same regression on
SOFR, which is what :func:`positioning_regression` computes.

The three enrichment families the brief names, and what each actually is here
-----------------------------------------------------------------------------
``dealer_net``  **AVAILABLE.** CFTC Traders in Financial Futures, Dealer /
    Intermediary long minus short, for ``SOFR-3M``. Weekly, 2020-01-07 →
    2026-05-12. Measured: dealer net correlates **−0.9547** in levels against
    (leveraged money + asset managers), so the "other side of the shorts"
    mechanism is visible in the data rather than assumed.

    **It must be lagged to publication.** The report measures Tuesday and is
    released Friday 15:30 ET; the raw file carries no release stamp.
    ``BT.signals.cftc_positioning.build_positioning_panel`` now applies
    ``release_lag_bdays=3`` by default and this module does not second-guess it.

``ccp_basis_bp``  **AVAILABLE, entitled.** LCH minus CME on the matched USD SOFR
    swap, from ``IRClearingHouseBasisSwapsMDP``. It belongs in a convexity model
    because the futures leg is CME-margined and the swap leg is not, so the
    basis is a direct wedge in ``CA = pack_rate − swap_rate``. JPM: *"CME CA net
    of theory as % of LCH CA ~80%"* (01-May-2017).

``open_interest``  **PARTIAL, and the shape is the finding.** Per-contract SR3
    open interest exists on this machine only for the ~21 contracts **live
    today**: coverage splits into two disjoint groups at exactly the
    live/expired line (SR3M26 0.008, SR3U26 0.980), so the panel is
    *survivorship-shaped*, not liquidity-shaped, and **front ranks before ~2025
    have no per-contract OI at all**. The usable historical substitute is CFTC
    ``Open_Interest_All`` for SOFR-3M — weekly, whole-strip, no per-contract
    dimension. This module offers the substitute and says which one it served.

Everything is lagged before it is returned. A signal that reads a number
published after the date it is indexed on is the defect this package has now
found twice — once as a ``bfill`` in a price panel, once as an unlagged CFTC
report date.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "CITI_FIG4_BLUES",
    "EnrichmentConfig",
    "PositioningFit",
    "build_enrichment_panel",
    "enrich_screen",
    "positioning_regression",
    "residual_series",
]

#: Citi, *Sell Eurodollar convexity in Blues*, Figure 4. Monthly changes,
#: 2013-01-01 .. 2017-12-26, Eurodollars. ``slope`` is bp of CA-minus-model per
#: contract of dealer positioning.
CITI_FIG4_BLUES = {
    "slope": 2e-06,
    "intercept": -0.1053,
    "r2": 0.2724,
    "freq": "M",
    "window": ("2013-01-01", "2017-12-26"),
    "market": "Eurodollars",
}


@dataclass(frozen=True)
class EnrichmentConfig:
    """Knobs, each with the reason for its default."""

    start: dt.date = dt.date(2021, 1, 1)
    end: dt.date = dt.date(2026, 8, 20)

    #: CFTC market key in ``BT.signals.cftc_positioning._CONTRACT_MAP``.
    cftc_market: str = "SOFR3M"

    #: Extra business days applied on TOP of the release lag the positioning
    #: panel already applies. Zero by default: double-lagging is as wrong as not
    #: lagging, and harder to spot.
    extra_lag_bdays: int = 0

    #: Basis tenors to carry. 10y is the one with a published level to check.
    basis_tenors: Tuple[str, ...] = ("5y", "10y", "30y")

    #: Lag on market-observable series (basis, open interest). One business day:
    #: a settle is known the next morning.
    market_lag_bdays: int = 1

    #: Frequency for the positioning regression. Citi's Figure 4 is monthly and
    #: reproducing it at a different frequency would not be reproducing it.
    regression_freq: str = "ME"

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["start"], d["end"] = str(self.start), str(self.end)
        d["basis_tenors"] = list(self.basis_tenors)
        return d


# ---------------------------------------------------------------------------
# The residual the regression is about
# ---------------------------------------------------------------------------
#: rank at which each colour starts. A pack at rank r spans contracts r..r+3.
COLOUR_RANK = {"Whites": 1, "Reds": 5, "Greens": 9, "Blues": 13, "Golds": 17}


def residual_series(panel: pd.DataFrame, cfg_s2: Any, *, colour: str = "Blues",
                    model: Optional[Dict[str, pd.DataFrame]] = None) -> pd.Series:
    """``CA − model`` for one pack colour, as a date-indexed series in bp.

    Citi's *"Vs Model (bp)"* column and the left-hand side of Figure 4, computed
    through ``strat2_sofr_convexity.model_timeseries`` so the fair-value model is
    the package's own rather than a second one invented here.

    **A colour is a RANK, stitched across pack labels.** ``vs_model`` is a wide
    frame indexed by date with one column per *pack label* (``M4-H5``, ``U4-M5``
    …), and a label lives only until the strip rolls past it. The first version
    of this function picked the lowest-ranked label and returned that single
    column, which collapsed Blues from 2,000 dates to **239 inside one calendar
    year** — and then reported a monthly regression on **eleven** points at
    t = −3.80, R² = 0.359. A confident number from an accidental one-year sample
    is worse than no number, so the join is now on ``(date, rank)``: for each
    date, the pack whose rank is the colour's, whatever it is called that day.
    """
    from RVUtils.ConvexityRV.strat2_sofr_convexity import model_timeseries

    if colour not in COLOUR_RANK:
        raise KeyError(f"unknown colour {colour!r}; expected {sorted(COLOUR_RANK)}")

    model = model if model is not None else model_timeseries(panel, cfg_s2)
    vs = model.get("vs_model")
    if vs is None or vs.empty:
        return pd.Series(dtype=float)

    rank = COLOUR_RANK[colour]
    sel = panel.loc[panel["rank"] == rank, ["date", "pack"]].dropna()
    if sel.empty:
        return pd.Series(dtype=float)

    long = (vs.stack().rename("vs_model").reset_index()
              .rename(columns={vs.index.name or "level_0": "date",
                               "level_1": "pack"}))
    long["date"] = pd.to_datetime(long["date"])
    sel = sel.assign(date=pd.to_datetime(sel["date"]))

    merged = sel.merge(long, on=["date", "pack"], how="inner")
    out = (merged.set_index("date")["vs_model"]
                 .sort_index().dropna().rename(f"vs_model_{colour}"))
    return out[~out.index.duplicated(keep="first")]


# ---------------------------------------------------------------------------
# The enrichment panel
# ---------------------------------------------------------------------------
def build_enrichment_panel(cfg: EnrichmentConfig = EnrichmentConfig(),
                           *, raw_cftc: Optional[pd.DataFrame] = None,
                           basis: Optional[pd.DataFrame] = None,
                           open_interest: Optional[pd.Series] = None,
                           ) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Date-indexed enrichment columns, plus a provenance dict.

    Returns ``(panel, provenance)``. The provenance says, per column, exactly
    which source served it and at what lag — because "open interest" served from
    a weekly whole-strip aggregate and "open interest" served per contract are
    different quantities, and a caller that cannot tell them apart will report
    whichever it got as though it were the other.

    Every input is optional so the whole thing is testable without network.
    """
    idx = pd.bdate_range(cfg.start, cfg.end)
    out = pd.DataFrame(index=idx)
    prov: Dict[str, str] = {}

    # --- dealer positioning -------------------------------------------------
    if raw_cftc is None:
        try:
            from pathlib import Path

            from BT.signals.cftc_positioning import fetch_cftc_financial_futures

            import RVUtils.ConvexityRV as _p
            root = Path(_p.__file__).resolve().parents[2]
            cache = root / "BT" / "results" / "tfp_screener" / "cftc_raw.parquet"
            raw_cftc = fetch_cftc_financial_futures(cache_path=str(cache)) \
                if cache.exists() else None
        except Exception:                                        # noqa: BLE001
            raw_cftc = None

    if raw_cftc is not None and len(raw_cftc):
        from BT.signals.cftc_positioning import (
            RELEASE_LAG_BUSINESS_DAYS, build_positioning_panel)

        for metric in ("dealer_net", "lev_net", "am_net"):
            p = build_positioning_panel(raw=raw_cftc, tenors=[cfg.cftc_market],
                                        metric=metric)
            if p.empty or cfg.cftc_market not in p.columns:
                continue
            s = p[cfg.cftc_market]
            if cfg.extra_lag_bdays:
                s.index = s.index + pd.tseries.offsets.BDay(cfg.extra_lag_bdays)
            out[metric] = s.reindex(idx, method="ffill")
            prov[metric] = (f"CFTC TFF {cfg.cftc_market}, weekly, lagged "
                            f"{RELEASE_LAG_BUSINESS_DAYS + cfg.extra_lag_bdays} "
                            f"bdays to publication")
        if "dealer_net" in out:
            out["dealer_net_chg"] = out["dealer_net"].diff()
            prov["dealer_net_chg"] = "first difference of the lagged level"

        # Whole-strip open interest, the historical substitute for per-contract
        oi_col = "Open_Interest_All"
        if open_interest is None and oi_col in raw_cftc.columns:
            from BT.signals.cftc_positioning import _CONTRACT_MAP

            names = _CONTRACT_MAP.get(cfg.cftc_market, [])
            sub = raw_cftc[raw_cftc["Market_and_Exchange_Names"].isin(names)]
            if len(sub):
                s = (sub.assign(date=pd.to_datetime(sub["Report_Date_as_YYYY-MM-DD"]))
                        .groupby("date")[oi_col].sum().sort_index())
                s.index = s.index + pd.tseries.offsets.BDay(
                    RELEASE_LAG_BUSINESS_DAYS + cfg.extra_lag_bdays)
                out["open_interest"] = s.reindex(idx, method="ffill")
                prov["open_interest"] = (
                    f"CFTC TFF Open_Interest_All for {cfg.cftc_market} — WHOLE "
                    "STRIP, weekly, no per-contract dimension. Per-contract SR3 "
                    "OI is survivorship-shaped on this machine and does not "
                    "exist for front ranks before ~2025.")

    if open_interest is not None:
        s = open_interest.copy()
        s.index = pd.to_datetime(s.index) + pd.tseries.offsets.BDay(cfg.market_lag_bdays)
        out["open_interest"] = s.reindex(idx, method="ffill")
        prov["open_interest"] = (
            f"caller-supplied, lagged {cfg.market_lag_bdays} bday")

    if "open_interest" in out:
        out["oi_chg"] = out["open_interest"].diff()
        prov["oi_chg"] = "first difference of the lagged level"

    # --- CCP basis ----------------------------------------------------------
    if basis is not None and len(basis):
        b = basis.copy()
        b.index = pd.to_datetime(b.index) + pd.tseries.offsets.BDay(cfg.market_lag_bdays)
        for t in cfg.basis_tenors:
            if t in b.columns:
                out[f"ccp_basis_{t}_bp"] = b[t].reindex(idx, method="ffill")
                prov[f"ccp_basis_{t}_bp"] = (
                    f"LCH minus CME, USD SOFR {t}, lagged "
                    f"{cfg.market_lag_bdays} bday")

    return out, prov


# ---------------------------------------------------------------------------
# Citi's Figure 4
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PositioningFit:
    """One regression of a CA residual on a positioning change."""

    n: int
    freq: str
    slope: float
    intercept: float
    r2: float
    tstat: float
    pvalue: float
    x_name: str
    y_name: str
    window: Tuple[str, str]

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["window"] = list(self.window)
        return d


def positioning_regression(residual: pd.Series, positioning: pd.Series, *,
                           freq: str = "ME",
                           x_name: str = "d_dealer_net",
                           y_name: str = "d_vs_model_bp") -> PositioningFit:
    """Citi Figure 4: change in (CA − model) on change in dealer positioning.

    **Both sides are CHANGES, resampled to** ``freq`` **first.** Regressing
    levels on levels would score two trending series against each other and
    report a large R² that is about the trend; Citi's own figure is explicitly
    monthly changes, and reproducing it at another frequency, or in levels, is
    not reproducing it.

    HAC (Newey-West) t-stat, because monthly changes built from a weekly series
    overlap.
    """
    import statsmodels.api as sm

    y = residual.resample(freq).last().diff()
    x = positioning.resample(freq).last().diff()
    df = pd.concat([y.rename("_y"), x.rename("_x")], axis=1).replace(
        [np.inf, -np.inf], np.nan).dropna()
    if len(df) < 8:
        return PositioningFit(len(df), freq, float("nan"), float("nan"),
                              float("nan"), float("nan"), float("nan"),
                              x_name, y_name, ("", ""))

    X = sm.add_constant(df["_x"].to_numpy())
    fit = sm.OLS(df["_y"].to_numpy(), X).fit(
        cov_type="HAC", cov_kwds={"maxlags": 3})
    return PositioningFit(
        n=int(len(df)), freq=freq,
        slope=float(fit.params[1]), intercept=float(fit.params[0]),
        r2=float(fit.rsquared), tstat=float(fit.tvalues[1]),
        pvalue=float(fit.pvalues[1]), x_name=x_name, y_name=y_name,
        window=(str(df.index[0].date()), str(df.index[-1].date())),
    )


def enrich_screen(screen: pd.DataFrame, enrichment: pd.DataFrame,
                  as_of: dt.date) -> pd.DataFrame:
    """Attach the enrichment row for *as_of* to every pack row of a daily screen.

    The enrichment is a per-DATE quantity and the screen is per-pack, so the
    columns are broadcast. They are named with an ``enr_`` prefix so a reader
    cannot mistake them for a per-pack measurement.
    """
    out = screen.copy()
    d = pd.Timestamp(as_of)
    if enrichment is None or enrichment.empty:
        return out
    row = enrichment.reindex([d], method="ffill")
    if row.empty:
        return out
    for c in enrichment.columns:
        v = row.iloc[0][c]
        out[f"enr_{c}"] = float(v) if pd.notna(v) else float("nan")
    return out
