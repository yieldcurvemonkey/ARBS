"""Load and normalise the stored UST-futures-option and swaption vol snapshots.

Source tables (mirrored to parquet by ``_pull_vol_snapshots.py``):

* ``arbs_ustf_vol_snapshots_v2``      one row per (date, product, expiry_label)
* ``arbs_swaption_vol_snapshots_v2``  one row per (date, expiry_label, tail_label)
* ``arbs_ustf_vs_swaption_comparison_v2``  the vendor-side ATM difference

Three things in this module exist because of defects found in the stored data. They are not
defensive boilerplate; each one corresponds to a measured problem:

1. **``strike_offset_otm_vols`` is unusable on the futures-option leg.** The historical ingest
   computed ``strike = forward + offset_bps * fv01 / 10_000`` where ``fv01`` is already price
   points per bp, so every "OTM" bucket landed 1/100th of the requested distance from the forward
   and is ATM in disguise (a requested 25bp strike sits 0.25bp away). The swaption leg is fine.
   Struck comparisons therefore rebuild the futures smile from ``smile_points``, which is
   delta-based and correct. The ingest bug is fixed going forward, but the stored history is not.

2. **``forward_yield`` jumps on contract rolls.** ``underlying_contract`` changes from e.g. ZBZ22
   to ZBH23 and the forward yield gaps by a non-market amount. Any realized-vol or P&L series
   built by differencing it must drop those days or it will book the roll as a return.

3. **Constant-maturity labels are not instruments.** ``1M``/``2M``/``3M`` are interpolated
   constant-maturity slots, so differencing a CM series mixes the roll-down of the vol term
   structure with the actual vol move. Holding a real option requires interpolating each day to
   the position's *remaining* time to expiry -- :func:`vol_term_structure_interp`.

Units throughout: vols in **annualised bp normal**; ``forward_yield`` in **percent**; swaption
``atmf_rate`` and ``strike_rate`` in **decimal**; ``fv01`` in **price points per bp**.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "DEFAULT_DATA_DIR",
    "PRODUCT_TAIL",
    "VolData",
    "load",
    "sanitize_ustf",
    "expand_ustf_smile_points",
    "expand_swaption_offsets",
    "vol_term_structure_interp",
    "ustf_vol_at_yield_offset",
    "swaption_vol_at_rate_offset",
    "add_roll_flags",
    "add_liveness_flags",
    "ustf_market_vs_model",
    "realized_vol_bp",
    "data_quality_report",
]

DEFAULT_DATA_DIR = pathlib.Path(__file__).resolve().parents[2] / "notebooks" / "backtests" / "basis_vs_vol" / "_data"

# Default futures-product -> swaption tail map. Matches the production ingest. Note that JPM's own
# Cross Market Volatility Spread Report uses 15Y for US, not 20Y, and the ZB CTD's remaining
# maturity at delivery is ~18.7y -- so this is a modelling choice, not a fact. Run it as a
# sensitivity rather than trusting it.
PRODUCT_TAIL = {"TU": "2Y", "FV": "5Y", "TY": "7Y", "TN": "10Y", "US": "20Y", "UL": "30Y"}

_EXPIRY_YEARS = {"1M": 1 / 12, "2M": 2 / 12, "3M": 0.25, "6M": 0.5, "1Y": 1.0}


@dataclass
class VolData:
    """Normalised panels. All frames carry ``as_of_date`` as a ``datetime64[ns]``."""

    ustf: pd.DataFrame
    swpt: pd.DataFrame
    cmp: pd.DataFrame
    ustf_smile: pd.DataFrame
    dropped_ustf: pd.DataFrame | None = None

    def products(self) -> list[str]:
        return sorted(self.ustf["product"].unique())

    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(sorted(self.ustf["as_of_date"].unique()))


def _norm_date(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["as_of_date"] = pd.to_datetime(df["as_of_date"])
    return df


def load(data_dir: str | pathlib.Path | None = None, products: list[str] | None = None,
         sanitize: bool = True) -> VolData:
    """Load the parquet mirrors and normalise types. Cheap; no smile expansion."""
    d = pathlib.Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    ustf = _norm_date(pd.read_parquet(d / "arbs_ustf_vol_snapshots_v2.parquet"))
    swpt = _norm_date(pd.read_parquet(d / "arbs_swaption_vol_snapshots_v2.parquet"))
    cmp_ = _norm_date(pd.read_parquet(d / "arbs_ustf_vs_swaption_comparison_v2.parquet"))
    if products:
        ustf = ustf[ustf["product"].isin(products)].copy()
        cmp_ = cmp_[cmp_["product"].isin(products)].copy()
    ustf, dropped = sanitize_ustf(ustf, drop=sanitize)
    ustf = add_roll_flags(ustf)
    ustf = add_liveness_flags(ustf)
    smile = expand_ustf_smile_points(ustf)
    return VolData(ustf=ustf, swpt=swpt, cmp=cmp_, ustf_smile=smile, dropped_ustf=dropped)


# Plausible bands for a deliverable-grade CBOT Treasury future. These are deliberately wide: the
# point is to catch corruption, not to police the market.
_PRICE_BAND = (50.0, 200.0)
_YIELD_BAND = (0.0, 20.0)  # percent


def sanitize_ustf(ustf: pd.DataFrame, drop: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reject rows whose futures price or forward yield is not physically plausible.

    This is not hypothetical. A block of ``UL`` rows stores ``forward_price`` as ``11.28`` rather
    than ``111.28`` -- a dropped leading digit in the price feed -- which drives ``forward_yield``
    to 50.3% and ``atm_nvol_bps`` down to 6.5 against a true level near 75. Left in, those rows
    make the Ultra Bond leg's implied/realized ratio 2.0 while every other product sits near 1.0.
    Returns ``(clean, dropped)``.
    """
    p = ustf["forward_price"].astype(float)
    y = ustf["forward_yield"].astype(float)
    bad = (
        ~p.between(*_PRICE_BAND)
        | ~y.between(*_YIELD_BAND)
        | ~np.isfinite(ustf["fv01"].astype(float))
        | (ustf["fv01"].astype(float) <= 0)
        | ~np.isfinite(ustf["atm_nvol_bps"].astype(float))
        | (ustf["atm_nvol_bps"].astype(float) <= 0)
    )
    dropped = ustf[bad].copy()
    return (ustf[~bad].copy() if drop else ustf.copy()), dropped


def add_roll_flags(ustf: pd.DataFrame) -> pd.DataFrame:
    """Flag days on which ``underlying_contract`` changed, per (product, expiry_label)."""
    out = ustf.sort_values(["product", "expiry_label", "as_of_date"]).copy()
    grp = out.groupby(["product", "expiry_label"], sort=False)["underlying_contract"]
    out["prev_contract"] = grp.shift(1)
    out["is_roll"] = out["prev_contract"].notna() & (out["prev_contract"] != out["underlying_contract"])
    return out


_MONTH_CODE = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
               "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}


def contract_last_delivery(code: str) -> pd.Timestamp | None:
    """Approximate last delivery day (month end) for a Globex contract code like ``ZBH26``."""
    if not isinstance(code, str) or len(code) < 4:
        return None
    m = _MONTH_CODE.get(code[-3].upper())
    try:
        yy = int(code[-2:])
    except ValueError:
        return None
    if m is None:
        return None
    year = 2000 + yy
    return pd.Timestamp(year=year, month=m, day=1) + pd.offsets.MonthEnd(1)


def add_liveness_flags(ustf: pd.DataFrame) -> pd.DataFrame:
    """Flag rows whose nominal option expiry falls after the referenced contract can exist.

    A 30-day option quoted on 2026-03-13 against ``ZBH26`` would expire around 2026-04-12, but the
    March contract stops trading in mid-March and is in its delivery month. Such a row references
    an instrument that is not live; it is an artefact of the constant-maturity slot holding a stale
    contract through the roll. These rows are marked, not silently kept, because they cluster at
    the roll -- exactly where a mean-reversion signal is most likely to fire.
    """
    out = ustf.copy()
    ld = out["underlying_contract"].map(contract_last_delivery)
    out["contract_last_delivery"] = ld
    out["option_expiry"] = out["as_of_date"] + pd.to_timedelta(out["expiry_days"], unit="D")
    out["is_live"] = ~(out["option_expiry"] > out["contract_last_delivery"])
    out["is_live"] = out["is_live"].fillna(True)
    return out


def ustf_market_vs_model(ustf: pd.DataFrame) -> pd.DataFrame:
    """Model-minus-market ATM bias per product, from the delta buckets.

    ``atm_nvol_bps`` is the SABR *model* value. The futures-option delta buckets also carry
    ``market_vol_bps`` -- the quote the model was fitted to. The gap between them is a fit
    residual, it is product-dependent, and on this data it is the same order as a
    cross-product comparison of the signal, so it must be measured rather than assumed away.
    (The swaption delta buckets carry no market vol, so a fully market-to-market comparison is
    not available from this vintage.)
    """
    recs = []
    it = ustf[["as_of_date", "product", "expiry_label", "atm_nvol_bps", "delta_otm_vols"]].itertuples(index=False)
    for as_of, product, expiry, model_atm, raw in it:
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for side, buckets in (payload or {}).items():
            b = (buckets or {}).get("50d") or (buckets or {}).get("50")
            if not b:
                continue
            mk = b.get("market_vol_bps")
            md = b.get("vol_bps")
            if mk is None or md is None:
                continue
            recs.append((as_of, product, expiry, side, float(md), float(mk), float(mk) - float(md)))
            break
    return pd.DataFrame.from_records(
        recs, columns=["as_of_date", "product", "expiry_label", "side",
                       "model_vol_bps", "market_vol_bps", "market_minus_model_bps"])


def expand_ustf_smile_points(ustf: pd.DataFrame) -> pd.DataFrame:
    """Explode ``smile_points`` into a long frame in **yield-offset** space.

    Returns columns: as_of_date, product, expiry_label, right ('P'/'C'), delta_abs,
    strike_futures_ytm (pct), iv_normal_bps, yield_offset_bps.

    ``yield_offset_bps = (strike_futures_ytm - forward_yield) * 100``, i.e. positive means the
    strike is at a HIGHER yield than the forward. A put on the futures price is a call on yield,
    so puts sit at positive offsets.
    """
    recs = []
    cols = ustf[["as_of_date", "product", "expiry_label", "forward_yield", "smile_points"]].itertuples(index=False)
    for as_of, product, expiry, fwd_y, raw in cols:
        if not raw:
            continue
        try:
            pts = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for p in pts:
            sy = p.get("strike_futures_ytm")
            iv = p.get("iv_normal_bps")
            if sy is None or iv is None:
                continue
            recs.append(
                (as_of, product, expiry, p.get("right"), p.get("delta_abs"),
                 float(sy), float(iv), (float(sy) - float(fwd_y)) * 100.0)
            )
    return pd.DataFrame.from_records(
        recs,
        columns=["as_of_date", "product", "expiry_label", "right", "delta_abs",
                 "strike_futures_ytm", "iv_normal_bps", "yield_offset_bps"],
    )


def expand_swaption_offsets(swpt: pd.DataFrame) -> pd.DataFrame:
    """Explode the swaption ``strike_offset_otm_vols`` payload (which IS correct) into a long frame.

    Returns: as_of_date, expiry_label, tail_label, side ('payer'/'receiver'), signed_offset_bps,
    strike_rate (decimal), vol_bps.
    """
    recs = []
    it = swpt[["as_of_date", "expiry_label", "tail_label", "strike_offset_otm_vols"]].itertuples(index=False)
    for as_of, expiry, tail, raw in it:
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for side, buckets in (payload or {}).items():
            for _sel, b in (buckets or {}).items():
                v = b.get("vol_bps")
                if v is None:
                    continue
                recs.append((as_of, expiry, tail, side, float(b.get("signed_offset_bps", np.nan)),
                             b.get("strike_rate"), float(v)))
    return pd.DataFrame.from_records(
        recs,
        columns=["as_of_date", "expiry_label", "tail_label", "side", "signed_offset_bps",
                 "strike_rate", "vol_bps"],
    )


def vol_term_structure_interp(ttes: np.ndarray, vols: np.ndarray, target_tte: float) -> float:
    """Interpolate a normal vol to ``target_tte`` linearly in **total variance**.

    Total variance ``w = sigma^2 * T`` is the quantity that is additive in time, so interpolating
    sigma directly would put a kink in the forward variance. Outside the node range the vol (not
    the variance) is held flat, which is the conservative choice at the short end where the term
    structure is steepest and we have no information.
    """
    ttes = np.asarray(ttes, float)
    vols = np.asarray(vols, float)
    ok = np.isfinite(ttes) & np.isfinite(vols) & (ttes > 0)
    ttes, vols = ttes[ok], vols[ok]
    if ttes.size == 0 or not np.isfinite(target_tte) or target_tte <= 0:
        return float("nan")
    order = np.argsort(ttes)
    ttes, vols = ttes[order], vols[order]
    if ttes.size == 1:
        return float(vols[0])
    if target_tte <= ttes[0]:
        return float(vols[0])
    if target_tte >= ttes[-1]:
        return float(vols[-1])
    w = vols**2 * ttes
    w_t = float(np.interp(target_tte, ttes, w))
    return float(np.sqrt(max(w_t, 0.0) / target_tte))


def ustf_vol_at_yield_offset(smile_rows: pd.DataFrame, offset_bps: float) -> float:
    """Interpolate the futures-option smile to a yield offset from the forward, in bp.

    ``smile_rows`` must be the smile points for a single (date, product, expiry). Linear in
    offset, flat beyond the observed wings -- the stored smile spans roughly the 5-delta put to
    the 5-delta call, so extrapolation past that is not information we have.
    """
    if smile_rows.empty:
        return float("nan")
    s = smile_rows.dropna(subset=["yield_offset_bps", "iv_normal_bps"])
    if s.empty:
        return float("nan")
    s = s.sort_values("yield_offset_bps")
    x = s["yield_offset_bps"].to_numpy(float)
    y = s["iv_normal_bps"].to_numpy(float)
    # collapse duplicate abscissae (puts and calls can quote the same strike)
    x_u, idx = np.unique(x, return_index=True)
    y_u = np.array([y[x == xv].mean() for xv in x_u])
    return float(np.interp(float(offset_bps), x_u, y_u))


def swaption_vol_at_rate_offset(off_rows: pd.DataFrame, offset_bps: float, atm_vol: float) -> float:
    """Interpolate the swaption smile to a signed rate offset in bp (positive = higher rate).

    The stored payload carries payers at positive ``signed_offset_bps`` and receivers at negative.
    ATM (offset 0) is not in the payload, so it is injected from ``atm_nvol_bps``.
    """
    if not np.isfinite(offset_bps):
        return float("nan")
    if off_rows.empty:
        return float(atm_vol) if abs(offset_bps) < 1e-9 else float("nan")
    s = off_rows.dropna(subset=["signed_offset_bps", "vol_bps"])
    if s.empty:
        return float(atm_vol) if abs(offset_bps) < 1e-9 else float("nan")
    x = np.concatenate([s["signed_offset_bps"].to_numpy(float), [0.0]])
    y = np.concatenate([s["vol_bps"].to_numpy(float), [float(atm_vol)]])
    order = np.argsort(x)
    x, y = x[order], y[order]
    x_u, idx = np.unique(x, return_index=True)
    y_u = np.array([y[x == xv].mean() for xv in x_u])
    return float(np.interp(float(offset_bps), x_u, y_u))


def realized_vol_bp(series: pd.Series, is_roll: pd.Series | None = None, window: int = 21,
                    scale: float = 100.0, annualise: bool = True) -> pd.Series:
    """Rolling realized normal vol, in annualised bp, from a level series.

    ``scale`` converts the level's native units into bp (100 for a percent yield, 10_000 for a
    decimal rate). Roll days are excluded rather than differenced -- differencing across a
    contract change books the roll as a return.
    """
    lvl = pd.Series(series).astype(float)
    d = lvl.diff() * scale
    if is_roll is not None:
        d = d.mask(pd.Series(is_roll).fillna(False).to_numpy(), np.nan)
    rv = d.rolling(window, min_periods=max(5, window // 2)).std()
    if annualise:
        rv = rv * np.sqrt(252.0)
    return rv


def data_quality_report(vd: VolData) -> pd.DataFrame:
    """Per-product integrity screen. Every column here caught something real at least once."""
    rows = []
    for product, g in vd.ustf.groupby("product"):
        g = g.sort_values("as_of_date")
        atm = g[g["expiry_label"] == "3M"].set_index("as_of_date")
        ident = (g["atm_nvol_price"] / g["fv01"] - g["atm_nvol_bps"]).abs().max()
        rv = realized_vol_bp(atm["forward_yield"], atm.get("is_roll"), window=21, scale=100.0)
        iv = atm["atm_nvol_bps"]
        both = pd.concat([iv.rename("iv"), rv.rename("rv")], axis=1).dropna()
        # staleness: consecutive identical ATM vols
        stale = int((atm["atm_nvol_bps"].diff() == 0).sum())
        rows.append(
            {
                "product": product,
                "n_days": g["as_of_date"].nunique(),
                "start": g["as_of_date"].min().date(),
                "end": g["as_of_date"].max().date(),
                "identity_max_err": ident,
                "median_atm_bps_3m": float(iv.median()),
                "median_fv01": float(g["fv01"].median()),
                "median_realized_bps": float(both["rv"].median()) if len(both) else np.nan,
                "iv_over_rv": float((both["iv"] / both["rv"]).median()) if len(both) else np.nan,
                "n_rolls": int(g["is_roll"].sum()) if "is_roll" in g else 0,
                "n_stale_days": stale,
            }
        )
    return pd.DataFrame(rows).sort_values("product").reset_index(drop=True)
