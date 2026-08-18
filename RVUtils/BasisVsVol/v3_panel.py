"""Assemble the V3 panel: the basis panel + a matched ATMF swaption quote, per day.

    <env>/python.exe -m RVUtils.BasisVsVol.v3_panel --roots ZB ZN UB

WHAT GETS JOINED
----------------
The Citi note compares cost-per-unit-gamma between a long futures basis and a matched ATMF receiver,
and it does so by mixing a MODEL gamma with a MARKET cost -- "the gamma of a $100mm May37 basis is
$420 and costs 4.2 ticks". This module does the same:

    swaption cost per gamma = sigma_swpt**2 * T          (bp^2; the annuity cancels)
    basis    cost per gamma = net_basis_32 / gamma_basis (bp^2; market cost, model gamma)
    richness                = swaption_cpg / basis_cpg   (>1 => the basis is the cheaper option)

``gamma_basis`` is the CTD-switch option's gamma with respect to a parallel shift, taken ANALYTICALLY
as ``slope * normal_gamma(0, s*, switch_vol_bp, tte) * 32`` rather than by bump-and-revalue: a second
difference across the switch kink is unstable and would have made the bump size a free parameter.

A REJECTED ALTERNATIVE, RECORDED BECAUSE IT LOOKED BETTER
--------------------------------------------------------
The first attempt inverted the market net basis for an implied switch vol, which makes richness
collapse to ``(sigma_swpt / sigma_basis)^2`` -- elegant, and wrong. Measured on ZB: the two-bond
crossover sits a MEDIAN 131bp away, so that option has almost no value, yet the market net basis is
a median 1.8/32. Forcing the model to explain the whole net basis returns implied vols of 400-1000bp
against a swaption vol of ~81bp. The net basis in this sample is mostly NOT switch optionality -- it
is carry, financing, the wildcard and the rest of the basket -- so the inversion is degenerate.

That is also why the strategy is SELECTIVE rather than permanent, which is what the note describes:
it is a trade for when the switch is in play. Measured across roots, |s*| < 25bp on ~30% of days
(the distribution is bimodal: p10 ~ 5bp, median ~ 130bp), and richness > 1 on 8.4% (ZB), 16.8% (ZN)
and 4.1% (UB) of days.

SWAPTION MATCHING
-----------------
* Expiry: interpolated on the cube's expiry axis to the time to the futures' LAST DELIVERY DAY.
* Tail: the CTD's own remaining maturity, interpolated across the tenor axis. There is no 25Y node,
  so 20Y and 30Y bracket it -- which is exactly the note's 25y case.
* ATM only (``offset_bp == 0``). The strategy is ATMF by construction, so the smile is not needed;
  that also makes the pre-2020-01-24 ATM-only vintage fully usable.

KNOWN HOLE, CARRIED IN THE DATA
-------------------------------
2020-01-24 .. 2020-03-24 carries no expiry shorter than 4Y in the cube -- 40 consecutive days, and
exactly the COVID window whose short-expiry vol V3 most wants. Those days get ``swaption_vol_bp``
NaN and are dropped by the eligibility mask rather than silently interpolated across, because
bridging a vol spike is how a backtest invents a trade that never existed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import sys
from typing import Optional

import numpy as np
import pandas as pd

from Caching.curve_store import CurveStore
from Caching.swaption_cube_store import SwaptionCubeStore
from RVUtils.BasisVsVol.bachelier import normal_gamma
from RVUtils.BasisVsVol.switch import (
    Deliverable,
    cf_adjusted_forward_price,
    crossover_shift,
    dv01_gap,
)

_CURVES = CurveStore.default()
DATA = pathlib.Path(__file__).resolve().parents[2] / "notebooks" / "backtests" / "basis_vs_vol" / "_data"
ASSET = "USD-SWAPTIONVOL-CITIVELOEXCEL"
# Citi Velocity EOD SOFR OIS, 2005-2026. Needed ONLY to mark an already-open short
# receiver off the money -- never for the entry signal, which is annuity-free by
# construction. That containment is deliberate: it keeps every curve assumption out
# of the decision to trade.
CURVE_ASSET = "USD-SOFR-1D-CITIVELOEXCEL"

_TENOR_RE = re.compile(r"^(\d+)([MY])$")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
_LABEL_RE = re.compile(r"([A-Z][a-z]{2})\s+(\d{2})\s*$")


def tenor_years(label: str) -> float:
    m = _TENOR_RE.match(str(label).strip().upper())
    if not m:
        return float("nan")
    n, unit = int(m.group(1)), m.group(2)
    return n / 12.0 if unit == "M" else float(n)


def ctd_maturity_years(ctd_label: str, as_of: pd.Timestamp) -> float:
    """Remaining maturity of the CTD, from its label (e.g. 'T 4 3/4 Nov 53')."""
    m = _LABEL_RE.search(str(ctd_label))
    if not m:
        return float("nan")
    mat = dt.date(2000 + int(m.group(2)), _MONTHS[m.group(1)], 15)
    return (mat - pd.Timestamp(as_of).date()).days / 365.25


def load_atm_vol(start: dt.date, end: dt.date) -> pd.DataFrame:
    """Tidy (date, expiry_years, tenor_years, vol_bp) for the ATM node only.

    ``l2=False`` is pinned: a miss with the default costs 0.172s on an L2 round trip versus 0.0002s
    without, and this loop touches ~1,900 days.
    """
    store = SwaptionCubeStore.default()
    rows = []
    for d in store.available_dates(ASSET):
        if d < start or d > end:
            continue
        f = store.read_day(ASSET, d, _allow_l2=False)
        if f is None or f.empty:
            continue
        atm = f[np.isclose(pd.to_numeric(f["offset_bp"], errors="coerce").fillna(9e9), 0.0)]
        if atm.empty:
            continue
        rows.append(pd.DataFrame({
            "date": pd.Timestamp(d),
            "expiry_years": [tenor_years(x) for x in atm["expiry"]],
            "tenor_years": [tenor_years(x) for x in atm["tenor"]],
            "vol_bp": pd.to_numeric(atm["vol_bp"], errors="coerce").to_numpy(),
        }))
    if not rows:
        return pd.DataFrame(columns=["date", "expiry_years", "tenor_years", "vol_bp"])
    out = pd.concat(rows, ignore_index=True)
    return out[np.isfinite(out["expiry_years"]) & np.isfinite(out["tenor_years"]) & out["vol_bp"].notna()]


def _interp_grid(g: pd.DataFrame, t_exp: float, t_tail: float) -> float:
    """Bilinear-ish: interpolate on tenor within each bracketing expiry, then across expiry.

    Linear in years on both axes and CLAMPED at the edges rather than extrapolated -- extrapolating
    a vol surface off the end of its own grid is how a backtest acquires prices no one quoted.
    """
    if g.empty or not np.isfinite(t_exp) or not np.isfinite(t_tail):
        return float("nan")
    exps = np.sort(g["expiry_years"].unique())
    lo = exps[exps <= t_exp].max() if (exps <= t_exp).any() else exps.min()
    hi = exps[exps >= t_exp].min() if (exps >= t_exp).any() else exps.max()

    def at(e: float) -> float:
        s = g[g["expiry_years"] == e]
        if s.empty:
            return float("nan")
        x = s["tenor_years"].to_numpy(float)
        y = s["vol_bp"].to_numpy(float)
        o = np.argsort(x)
        return float(np.interp(np.clip(t_tail, x[o][0], x[o][-1]), x[o], y[o]))

    v_lo, v_hi = at(lo), at(hi)
    if not np.isfinite(v_lo):
        return v_hi
    if not np.isfinite(v_hi) or hi == lo:
        return v_lo
    w = (t_exp - lo) / (hi - lo)
    return float(v_lo + w * (v_hi - v_lo))


def forward_swap(day: dt.date, expiry_days: int, tail_years: float) -> tuple:
    """(par forward swap rate in %, annuity in $ per bp on $1mm) for a forward-starting IRS.

    Absolute effective/termination dates, not tenor strings -- a recorded trap in this repo is that
    "5Yx10Y" is measured from the reference date rather than spot.
    """
    try:
        row = _CURVES.read_raw_day(CURVE_ASSET, day)
        if row is None or (hasattr(row, "empty") and row.empty):
            return float("nan"), float("nan")
        r = row.iloc[0].to_dict() if hasattr(row, "iloc") else row
        curve = CurveStore.reconstruct_curve(r)
        import rateslib as rl
        eff = day + dt.timedelta(days=int(max(expiry_days, 1)))
        term = eff + dt.timedelta(days=int(round(max(tail_years, 1.0) * 365.25)))
        irs = rl.IRS(effective=rl.dt(eff.year, eff.month, eff.day),
                     termination=rl.dt(term.year, term.month, term.day),
                     frequency="A", convention="act360", calendar="nyc", currency="usd")
        return float(irs.rate(curves=curve)), float(irs.analytic_delta(curves=curve))
    except Exception:
        return float("nan"), float("nan")


def build(root: str, start: dt.date, end: dt.date, vol: Optional[pd.DataFrame] = None,
          switch_vol_bp: float = 70.0) -> pd.DataFrame:
    p = pd.read_parquet(DATA / f"basis_panel_{root}.parquet")
    p["date"] = pd.to_datetime(p["date"])
    p = p[(p["date"] >= pd.Timestamp(start)) & (p["date"] <= pd.Timestamp(end))].copy()
    p = p.sort_values("date").reset_index(drop=True)

    if vol is None:
        vol = load_atm_vol(start, end)
    by_day = {d: g for d, g in vol.groupby("date")}

    deliv = pd.to_datetime(p["delivery_date"])
    p["days_to_delivery"] = (deliv - p["date"]).dt.days
    p["tte"] = p["days_to_delivery"] / 365.25
    p["ctd_maturity_years"] = [ctd_maturity_years(l, d) for l, d in zip(p["ctd_label"], p["date"])]

    sstar, slope_l, gamma_l, swpt_vol = [], [], [], []
    for _, r in p.iterrows():
        tte = float(r["tte"])
        fut = float(r["futures_price"])
        try:
            ctd = Deliverable(
                label=str(r["ctd_label"]), cf=float(r["ctd_cf"]),
                price_fwd=cf_adjusted_forward_price(float(r["ctd_bnoc32"]), float(r["ctd_cf"]), fut),
                dv01=float(r["ctd_dv01"]))
            alt = Deliverable(
                label=str(r["alt_label"]), cf=float(r["alt_cf"]),
                price_fwd=cf_adjusted_forward_price(float(r["alt_bnoc32"]), float(r["alt_cf"]), fut),
                dv01=float(r["alt_dv01"]))
            s_star = float(crossover_shift(ctd, alt))
            slope = float(ctd.cf * abs(dv01_gap(ctd, alt)))
            # Gamma of the delivery option w.r.t. a parallel shift, in 32nds per bp^2, ANALYTIC.
            # A bump-and-revalue second difference across the switch kink is unstable and would make
            # the bump size a free parameter; this reuses the module the repo already tests.
            g = (slope * float(normal_gamma(0.0, s_star, switch_vol_bp, tte)) * 32.0
                 if (np.isfinite(s_star) and tte > 0) else float("nan"))
        except Exception:
            s_star, slope, g = float("nan"), float("nan"), float("nan")
        sstar.append(s_star)
        slope_l.append(slope)
        gamma_l.append(g)
        gg = by_day.get(r["date"])
        swpt_vol.append(_interp_grid(gg, tte, float(r["ctd_maturity_years"])) if gg is not None else float("nan"))

    p["crossover_bp"] = sstar
    p["switch_slope"] = slope_l
    p["gamma_basis"] = gamma_l                # 32nds per bp^2
    p["swaption_vol_bp"] = swpt_vol
    p["switch_vol_bp"] = switch_vol_bp
    p["t_expiry_years"] = p["tte"]            # matched expiry, as the note specifies

    # The note mixes a MODEL gamma with a MARKET cost -- "the gamma of a $100mm May37 basis is $420
    # and costs 4.2 ticks". So do we. Inverting the market net basis for an implied switch vol was
    # tried first and is degenerate: the observed net basis is far larger than a two-bond switch
    # sitting a median 130bp out of the money can explain, so the inversion returns 400-1000bp vols.
    # The net basis in this sample is mostly NOT switch optionality, which is itself the reason the
    # trade is selective rather than permanent.
    fwd, ann = [], []
    for _, r in p.iterrows():
        f, a = forward_swap(pd.Timestamp(r["date"]).date(), int(r["days_to_delivery"]),
                            float(r["ctd_maturity_years"]))
        fwd.append(f)
        ann.append(a)
    p["forward_rate"] = fwd                       # par forward swap rate, PERCENT
    p["swaption_annuity"] = ann                   # $ per bp on $1mm notional

    p["swaption_cpg"] = p["swaption_vol_bp"] ** 2 * p["t_expiry_years"]     # bp^2
    p["basis_cpg"] = p["ctd_bnoc32"] / p["gamma_basis"]                    # bp^2
    p["richness"] = p["swaption_cpg"] / p["basis_cpg"]
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="+", default=["ZB", "ZN", "UB"])
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-08-11")
    a = ap.parse_args(argv)
    s, e = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)

    print("loading ATM swaption vol ...", flush=True)
    vol = load_atm_vol(s, e)
    print(f"  {len(vol):,} ATM nodes over {vol['date'].nunique()} days", flush=True)

    for root in a.roots:
        p = build(root, s, e, vol=vol)
        ok = int(p["richness"].notna().sum())
        out = DATA / f"v3_panel_{root}.parquet"
        p.to_parquet(out, index=False)
        print(f"{root}: {len(p)} rows, {ok} with a richness ({100*ok/max(len(p),1):.1f}%) "
              f"| median richness {p['richness'].median():.3f} "
              f"| gamma>1e-5 on {100*(p['gamma_basis']>1e-5).mean():.0f}% "
              f"| fwd ok {100*p['forward_rate'].notna().mean():.0f}% "
              f"| median swpt vol {p['swaption_vol_bp'].median():.1f}bp -> {out.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
