"""Probe 15: verify the shipped `SDRUtils/dealer_direction/krd.py` on real curves.

(a) per-day vs per-block vs per-minute solver reuse, on an FOMC date and on the
    biggest intraday curve-shape break in the store -- run through KrdProjector
    itself, not through a parallel probe wiring.
(b) the independent zero-space bump-and-reprice cross-check at the full 28
    pillars on the real Citi minute curve, including a past-start leg.
"""
from __future__ import annotations

import datetime
import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np
import pandas as pd
import pytz
import rateslib as rl

from Caching.curve_store import CurveStore
from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import krd as K
from SDRUtils.dealer_direction import types as T
from SDRUtils.dealer_direction.midprice import SessionBranchPricer

pd.set_option("display.width", 250)
NY = pytz.timezone("America/New_York")
ASSET = "USD-SOFR-1D-CITIVELOEXCELMIN"

DAYS = [
    (datetime.date(2025, 4, 7), "biggest intraday shape break (2y 42bp, 10y 33bp)"),
    (datetime.date(2024, 6, 12), "FOMC, biggest 10y range of any FOMC day (15bp)"),
    (datetime.date(2026, 6, 17), "FOMC, recent (2y 17bp)"),
]
EVERY = 10          # sample every 10th stored minute


def unit_at(key, instant, tenor, notional, rate, *, effective=None, fwd=None):
    spot = rl.get_calendar("nyc").lag_bus_days(
        rl.dt(instant.year, instant.month, instant.day), 2, True)
    if effective is not None:
        e = pd.Timestamp(effective)
        eff = rl.dt(e.year, e.month, e.day)      # rateslib 2.x rejects date
    else:
        eff = rl.add_tenor(spot, fwd, "MF", "nyc") if fwd else spot
    legs = pd.DataFrame([{
        "trade_id": key,
        "effective_date": pd.Timestamp(eff).date(),
        "expiration_date": pd.Timestamp(rl.add_tenor(eff, tenor, "MF", "nyc")).date(),
        "notional": float(notional), "fixed_rate": float(rate),
    }])
    clocks = T.Clocks(pricing=instant, execution=instant, event=instant,
                      visibility=instant, visibility_source="PROBE")
    return T.Unit(unit_key=key, kind=conv.OUTRIGHT, legs=legs, package_id=None,
                  rate_index="SOFR", as_of_date=instant.date(),
                  venue_class=T.VENUE_D2C, clocks=clocks)


CASES = [("2Y payer 200mm", "2Y", 200e6, 0.039, None),
         ("10Y payer 100mm", "10Y", 100e6, 0.041, None),
         ("30Y recv 50mm", "30Y", 50e6, 0.043, None),
         ("50Y payer 25mm", "50Y", 25e6, 0.042, None),
         ("5Yx5Y payer 300mm", "5Y", 300e6, 0.042, "5Y")]


def part_a():
    store = CurveStore.default()
    print("=" * 100)
    print("(a) solver reuse: per-minute (exact) vs 60-min block vs whole day")
    print(f"    sampling every {EVERY}th stored minute; projector fed in "
          f"chronological order, so a block's anchor is its first trade")
    for day, why in DAYS:
        raw = store.read_raw_nodes(ASSET, start=day, end=day)
        stamps = sorted(pd.Timestamp(t).tz_convert(NY) for t in raw["timestamp_utc"])
        sample = stamps[::EVERY]
        print(f"\n  {day}  {why}\n    {len(stamps)} stored minutes, "
              f"{len(sample)} sampled, {sample[0]} .. {sample[-1]}")

        projs = {}
        for tag, block in (("exact_1min", 1), ("block_15min", 15), ("block_30min", 30),
                           ("block_60min", 60), ("whole_day", 1440)):
            projs[tag] = K.KrdProjector(SessionBranchPricer(), block_minutes=block)

        from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

        t0 = time.perf_counter()
        got: dict = {t: {} for t in projs}
        skipped = 0
        for m in sample:
            # A minute the strict in-session policy refuses is refused for every
            # model; scoring it for one and not another would compare policies,
            # not solver reuse.
            try:
                staged = {
                    tag: {nm: p.unit_krd(
                        unit_at(f"{nm}@{m:%H%M}", m, tenor, notl, rate, fwd=fwd),
                        conv.RULE_RATE)
                        for nm, tenor, notl, rate, fwd in CASES}
                    for tag, p in projs.items()
                }
            except SnapshotMiss:
                skipped += 1
                continue
            for tag, per_case in staged.items():
                for nm, prof in per_case.items():
                    got[tag][(m, nm)] = prof
        dt = time.perf_counter() - t0
        print(f"    {skipped} sampled minute(s) refused by the snapshot policy")
        print(f"    {len(sample)*len(CASES)} units x 3 models in {dt:.0f}s; "
              f"solvers built: " +
              ", ".join(f"{t}={p.n_models}" for t, p in projs.items()))

        rows = []
        for (m, nm), exact in got["exact_1min"].items():
            tot = abs(sum(exact.values()))
            for tag in ("block_15min", "block_30min", "block_60min", "whole_day"):
                ap = got[tag][(m, nm)]
                rows.append({
                    "case": nm, "model": tag,
                    "bkt_pct": max(abs(ap[k] - exact[k]) for k in exact) / tot * 100,
                    "tot_pct": abs(sum(ap.values()) - sum(exact.values())) / tot * 100,
                })
        df = pd.DataFrame(rows)
        for tag in ("block_15min", "block_30min", "block_60min", "whole_day"):
            d = df[df["model"] == tag]
            print(f"    {tag:12s} max bucket {d['bkt_pct'].max():6.3f}%  "
                  f"p95 {d['bkt_pct'].quantile(.95):6.3f}%  "
                  f"median {d['bkt_pct'].median():6.3f}%  |  "
                  f"max total {d['tot_pct'].max():6.3f}%")
        worst = df[df["model"] == "block_60min"].groupby("case")["bkt_pct"].max()
        print("    60-min worst by case: " +
              "  ".join(f"{k}={v:.3f}%" for k, v in worst.items()))


# ------------------------------------------------------------------ (b)
def tent_amplitudes(curve, grid_dates):
    node_dates = list(curve.nodes.nodes)
    nd = np.array([(pd.Timestamp(d) - pd.Timestamp(curve.nodes.initial)).days
                   for d in node_dates], float)
    gd = np.array([(pd.Timestamp(d) - pd.Timestamp(curve.nodes.initial)).days
                   for d in grid_dates], float)
    W = np.zeros((nd.size, gd.size))
    for a, t in enumerate(nd):
        if t <= gd[0]:
            W[a, 0] = 1.0
        elif t >= gd[-1]:
            W[a, -1] = 1.0
        else:
            j = int(np.searchsorted(gd, t) - 1)
            f = (t - gd[j]) / (gd[j + 1] - gd[j])
            W[a, j], W[a, j + 1] = 1.0 - f, f
    return node_dates, W * (nd / 365.0)[:, None]


def shocked(curve, node_dates, amps, j, bump_bp):
    tent = rl.Curve(nodes={d: float(np.exp(-bump_bp * 1e-4 * amps[i, j]))
                           for i, d in enumerate(node_dates)},
                    convention=curve.meta.convention, calendar=curve.meta.calendar,
                    modifier=curve.meta.modifier, id=f"tent{j}")
    return rl.CompositeCurve([curve, tent])


def part_b():
    print("\n" + "=" * 100)
    print("(b) 28-pillar cross-check on the real Citi minute curve: rateslib solver "
          "delta\n    vs an independent zero-space bump-and-reprice converted "
          "through ds/dz")
    instant = pd.Timestamp(NY.localize(datetime.datetime(2026, 6, 16, 11, 0)))
    proj = K.KrdProjector(SessionBranchPricer())
    spot = rl.get_calendar("nyc").lag_bus_days(rl.dt(2026, 6, 16), 2, True)
    shapes = [
        ("spot 10Y payer 100mm", dict(tenor="10Y", notional=100e6, rate=0.0404)),
        ("1Yx10Y 150mm", dict(tenor="10Y", notional=150e6, rate=0.0410, fwd="1Y")),
        ("spot 30Y 50mm", dict(tenor="30Y", notional=50e6, rate=0.0423)),
        ("spot 50Y 25mm", dict(tenor="50Y", notional=25e6, rate=0.0399)),
        ("7Y off-mkt 250mm", dict(tenor="7Y", notional=250e6, rate=0.0250)),
        ("past-start 5Y 50mm", dict(tenor="5Y", notional=50e6, rate=0.0425,
                                    effective=datetime.date(2024, 3, 15))),
    ]
    for name, kw in shapes:
        u = unit_at(name, instant, **kw)
        t0 = time.perf_counter()
        model, instruments = proj.unit_positions(u, conv.RULE_RATE)
        curve = model.risk_handle.handle()
        grid = [i.leg1.schedule.termination for i in model.calibrating_instruments]
        node_dates, amps = tent_amplitudes(curve, grid)
        n = len(grid)
        zero = np.empty(n)
        dsdz = np.empty((n, n))
        for j in range(n):
            up = shocked(curve, node_dates, amps, j, +1.0)
            dn = shocked(curve, node_dates, amps, j, -1.0)
            zero[j] = 0.5 * (float(rl.Portfolio(instruments).npv(curves=up))
                             - float(rl.Portfolio(instruments).npv(curves=dn)))
            for i, inst in enumerate(model.calibrating_instruments):
                dsdz[i, j] = 0.5 * 100.0 * (float(inst.rate(curves=up).real)
                                            - float(inst.rate(curves=dn).real))
        ref = conv.RL_DELTA_TO_FUTURES_EQ * np.linalg.solve(dsdz.T, zero)
        raw = conv.RL_DELTA_TO_FUTURES_EQ * zero
        got = np.array([proj.unit_krd(u, conv.RULE_RATE)[p] for p in model.pillars])
        tot = abs(got.sum())
        print(f"  {name:22s} total {got.sum():14,.1f} USD/bp  "
              f"| converted max diff {np.abs(ref-got).max()/tot*100:8.4f}% of DV01"
              f"  | RAW zero-KRD would be {np.abs(raw-got).max()/tot*100:8.2f}% off"
              f"  ({time.perf_counter()-t0:.0f}s)")


if __name__ == "__main__":
    import sys as _s
    if "--a" not in _s.argv:
        part_b()
    part_a()
