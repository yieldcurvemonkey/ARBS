"""H15 — aging decay: Γ and DV01 of an aged package as a fraction of inception.

"In 3 years that's still 7y10y" (PM claim): does a back-booked ultra-long
flattener retain its convexity? For inception dates spaced through the sample,
build the package on its inception curve (CurvePricer's aged contract), then
measure package Γ(25bp) and leg DV01s k years later on the contemporaneous
curve, as fractions of inception. Falsified if convexity decays fast enough
that multi-year back-book holding retains little exposure.

Run:  conda run -n stir python scripts/sv_h15_aging.py USD
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
PKG_DV01 = 100_000.0
HOLD_YEARS = [1, 2, 3, 5]


def main() -> None:
    import logging

    logging.disable(logging.WARNING)
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from RVUtils.StrikelessVol.citivelo import (
        CITIVELO_MARKET_CURVES, CITIVELO_SOURCE, citivelo_pairs, stored_dates,
    )
    from RVUtils.StrikelessVol.greeks import build_package, package_gamma, _reprice_dv01

    market = (sys.argv[1] if len(sys.argv) > 1 else "USD").upper()
    pairs = [p for p in citivelo_pairs([market])
             if p.name in (f"{market} 10Y10Y/20Y10Y", f"{market} 15Y5Y/20Y10Y",
                           f"{market} 10Y10Y/25Y10Y")]
    days = stored_dates(market)
    day_set = set(days)

    def nearest(d: datetime.date):
        for k in range(0, 10):
            for cand in (d + datetime.timedelta(days=k), d - datetime.timedelta(days=k)):
                if cand in day_set:
                    return cand
        return None

    inceptions = [d for d in days if d.month == 6 and d.day <= 7 and d.year in
                  range(2006, 2022, 3)]
    inceptions = sorted({min((x for x in days if x.year == y and x.month == 6),
                             default=None) for y in range(2006, 2022, 3)} - {None})

    mdp = IRSwapsMDP(source=CITIVELO_SOURCE)
    rows = []
    for inc in inceptions:
        wanted = [inc] + [nearest(inc.replace(year=inc.year + k)) for k in HOLD_YEARS]
        wanted = [w for w in wanted if w is not None]
        cm = mdp.bulk_get_data({"curve_name": CITIVELO_MARKET_CURVES[market],
                                "timestamps": wanted, "offline": True})
        cm = {(k.date() if hasattr(k, "date") else k): v for k, v in cm.items()}
        c0 = cm.get(inc)
        if c0 is None:
            continue
        for pair in pairs:
            try:
                pkg = build_package(c0, pair, package_dv01_usd=PKG_DV01)
                g0 = package_gamma(c0, pkg)
                d0 = abs(pkg.long_dv01)
            except Exception:
                continue
            # PURE aging: same curve, shape slid forward k years (rl.Curve.roll)
            # — no market move, so the fraction isolates position aging from the
            # level path that confounds the market-curve fractions below.
            from RVUtils.StrikelessVol.greeks import package_npv

            h0 = c0.handle()
            for k in HOLD_YEARS:
                try:
                    hk = h0.roll(f"{int(k * 365)}d")
                    base = package_npv(hk, pkg)
                    up = package_npv(hk.shift(25.0), pkg)
                    dn = package_npv(hk.shift(-25.0), pkg)
                    g_pure = (up + dn - 2.0 * base) / (25.0 ** 2)
                    rows.append({"market": market, "pair": pair.name,
                                 "inception": str(inc), "years_held": k,
                                 "measure": "pure_aging",
                                 "gamma_frac": g_pure / g0 if g0 else float("nan")})
                except Exception:
                    pass
            for k in HOLD_YEARS:
                w = nearest(inc.replace(year=inc.year + k))
                ck = cm.get(w)
                if ck is None:
                    continue
                try:
                    gk = package_gamma(ck, pkg)
                    dk = abs(_reprice_dv01(ck, pkg.long))
                except Exception:
                    continue
                rows.append({"market": market, "pair": pair.name, "inception": str(inc),
                             "years_held": k, "measure": "market_curve",
                             "gamma_frac": gk / g0 if g0 else float("nan"),
                             "long_dv01_frac": dk / d0 if d0 else float("nan"),
                             "gamma_0": g0, "gamma_k": gk})

    df = pd.DataFrame(rows)
    out = DATA / f"h15_aging_{market}.parquet"
    df.to_parquet(out, index=False)
    if len(df):
        summ = df.groupby(["pair", "measure", "years_held"])[["gamma_frac", "long_dv01_frac"]].median()
        print(summ.to_string(float_format=lambda x: f"{x:6.3f}"))
    print(f"wrote {out.name} ({len(df)} rows)")


if __name__ == "__main__":
    main()
