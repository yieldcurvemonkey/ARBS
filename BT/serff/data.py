"""SERFF model panel: daily SOFR-EFFR spread + liquidity covariates.

Reuses the repo's fixings cache (NY Fed SOFR/EFFR) and the new
MDP/USMoneyMarkets fetchers (H.4.1 weekly aggregates, BEA GDP).

Two publication-alignment modes (SerffDataConfig.alignment):

- ``contemporaneous``: weekly/quarterly series forward-filled on their
  *reference* dates -- reproduces the standalone prototype exactly; fine for
  fair-value description, look-ahead for trading.
- ``published``: each row's covariates are the latest values *published* by
  the time the row's own fixing prints (fixing date + 1bd, 08:00 ET; H.4.1
  Wednesday + 1d release + optional next-day availability; GDP quarter end +
  ~30d).  Each row carries ``published_at`` so walk-forward fits can filter
  to information actually available at a decision timestamp.
"""

from __future__ import annotations

import datetime
from typing import Optional

import numpy as np
import pandas as pd

from BT.serff.config import SerffDataConfig, SerffModelConfig
from BT.serff.mechanics import SOFR_CAL, next_business_day


# --------------------------------------------------------------------------
# raw inputs
# --------------------------------------------------------------------------
def load_fixings(curve_name: str, as_of: datetime.date | str = "live") -> pd.Series:
    """SOFR/EFFR fixing history in PERCENT, via the repo fixings cache."""
    from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings

    s = _fetch_fixings(as_of, curve_name)
    s = pd.to_numeric(s, errors="coerce").dropna().sort_index()
    return (s * 100.0).rename(curve_name)  # cache stores decimals


def load_h41(force_refresh: bool = False):
    from MDP.USMoneyMarkets import fetch_h41_series

    return {name: fetch_h41_series(name, force_refresh=force_refresh) for name in ("reserves", "rrp", "tga")}


def load_gdp(publication_lag_days: int, force_refresh: bool = False) -> pd.DataFrame:
    from MDP.USMoneyMarkets import fetch_nominal_gdp

    return fetch_nominal_gdp(publication_lag_days=publication_lag_days, force_refresh=force_refresh)


# --------------------------------------------------------------------------
# alignment helpers
# --------------------------------------------------------------------------
def _align_contemporaneous(target_idx: pd.DatetimeIndex, values: pd.Series) -> pd.Series:
    """Prototype convention: ffill on reference dates."""
    union = target_idx.union(values.index)
    return values.reindex(union).ffill().reindex(target_idx)


def _align_published(
    target_pub: pd.Series,
    values: pd.Series,
    published: pd.Series,
) -> pd.Series:
    """Latest value whose publication date <= each row's publication date."""
    rel = pd.DataFrame({"published": pd.to_datetime(published.values), "value": values.values}).sort_values("published")
    tgt = pd.DataFrame({"published_at": pd.to_datetime(target_pub.values)}, index=target_pub.index)
    tgt = tgt.sort_values("published_at")
    merged = pd.merge_asof(tgt, rel, left_on="published_at", right_on="published", direction="backward")
    out = pd.Series(merged["value"].values, index=tgt.index).reindex(target_pub.index)
    return out


def regime_labels(dates: pd.DatetimeIndex, cfg: SerffModelConfig) -> pd.Series:
    bounds = [pd.Timestamp(b) for b in cfg.regime_boundaries]
    labels = list(cfg.regime_labels)
    if len(labels) != len(bounds) + 1:
        raise ValueError("regime_labels must have exactly one more entry than regime_boundaries")
    idx = np.searchsorted(pd.DatetimeIndex(bounds), dates, side="right")
    return pd.Series([labels[i] for i in idx], index=dates, name="regime")


# --------------------------------------------------------------------------
# panel
# --------------------------------------------------------------------------
def build_panel(
    data_cfg: Optional[SerffDataConfig] = None,
    model_cfg: Optional[SerffModelConfig] = None,
    *,
    sofr: Optional[pd.Series] = None,
    effr: Optional[pd.Series] = None,
    h41: Optional[dict] = None,
    gdp: Optional[pd.DataFrame] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Daily model panel (index = fixing dates with both SOFR and EFFR).

    Raw inputs can be injected (tests / fixtures); by default they are
    fetched through the repo caches.
    """
    data_cfg = data_cfg or SerffDataConfig()
    model_cfg = model_cfg or SerffModelConfig()

    if sofr is None:
        sofr = load_fixings("USD-SOFR-1D")
    if effr is None:
        effr = load_fixings("USD-FEDFUNDS")
    if h41 is None:
        h41 = load_h41(force_refresh=force_refresh)
    if gdp is None:
        gdp = load_gdp(data_cfg.gdp_publication_lag_days, force_refresh=force_refresh)

    panel = pd.DataFrame({"sofr": sofr, "effr": effr}).dropna()
    start = pd.Timestamp(data_cfg.start)
    end = pd.Timestamp(data_cfg.end) if data_cfg.end is not None else panel.index.max()
    panel = panel.loc[start:end].copy()
    panel["spread"] = (panel["sofr"] - panel["effr"]) * 100.0  # bp

    # row publication: fixing prints next business day ~08:00 ET
    pub_dates = [
        pd.Timestamp(next_business_day(d.date(), SOFR_CAL))
        for d in panel.index
    ]
    panel["published_at"] = pd.DatetimeIndex(pub_dates) + pd.Timedelta(hours=8)

    res_s, rrp_s, tga_s = (h41[k] for k in ("reserves", "rrp", "tga"))

    if data_cfg.alignment == "contemporaneous":
        panel["res"] = _align_contemporaneous(panel.index, res_s.values)
        panel["rrp"] = _align_contemporaneous(panel.index, rrp_s.values)
        panel["tga"] = _align_contemporaneous(panel.index, tga_s.values)
        panel["gdp"] = _align_contemporaneous(panel.index, gdp["gdp"])
    elif data_cfg.alignment == "published":
        h41_extra = pd.Timedelta(days=1) if data_cfg.h41_available_next_day else pd.Timedelta(0)
        row_pub = panel["published_at"]
        for name, series in (("res", res_s), ("rrp", rrp_s), ("tga", tga_s)):
            panel[name] = _align_published(row_pub, series.values, series.published + h41_extra)
        panel["gdp"] = _align_published(row_pub, gdp["gdp"], gdp["published"])
    else:
        raise ValueError(f"Unknown alignment {data_cfg.alignment!r}")

    panel = panel.dropna(subset=["res", "gdp"])
    panel["rrp"] = panel["rrp"].fillna(0.0)

    panel["liq_gdp"] = 100.0 * (panel["res"] + panel["rrp"]) / panel["gdp"]
    panel["tga_gdp"] = 100.0 * panel["tga"] / panel["gdp"]
    panel["ln_liq"] = np.log(panel["liq_gdp"])

    # ---- calendar features -------------------------------------------------
    dts = panel.index
    ym = dts.to_period("M")
    panel["_ym"] = ym
    grouped = panel.groupby("_ym")
    rank_from_end = grouped.cumcount(ascending=False)
    rank_from_beg = grouped.cumcount()

    last_bd_of_month = panel.index.to_series().groupby(panel["_ym"]).max()
    panel["is_me"] = dts.isin(set(last_bd_of_month.values))
    panel["is_qe"] = panel["is_me"] & dts.month.isin([3, 6, 9, 12])
    panel["is_ye"] = panel["is_me"] & (dts.month == 12)

    panel["turn_window"] = (rank_from_end <= model_cfg.turn_window_last_bd - 1) | (
        rank_from_beg <= model_cfg.turn_window_first_bd - 1
    )
    panel["is_mid"] = dts.day.isin(list(model_cfg.mid_month_days))

    panel["regime"] = regime_labels(dts, model_cfg)

    # ---- turn features (shared by Layer 2 and the ledger) ------------------
    base = panel["spread"].where(~panel["turn_window"])
    panel["local_base"] = (
        base.rolling(model_cfg.local_base_window, min_periods=model_cfg.local_base_min_periods)
        .median()
        .shift(model_cfg.local_base_shift)
    )
    panel["spike"] = panel["spread"] - panel["local_base"]

    return panel.drop(columns=["_ym"])
