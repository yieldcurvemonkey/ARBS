"""Known-answer validation for the health statistic, before it is trusted on flow.

Three questions the unit tests do not answer:

1. kappa is 1 at a perfect classifier and 0 at a degenerate one -- but is it
   MONOTONE in accuracy in between, on a realistically skewed 78/22 base rate?
   A statistic that is only right at the endpoints is not a monitor.
2. does the naive hit rate actually mislead on the same inputs (i.e. is the
   correction earning its keep, or is it decoration)?
3. do the report/aggregate paths survive empty and single-row inputs, which is
   what a per-day monitor sees on a thin day?
"""
from __future__ import annotations

import datetime
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")

from SDRUtils.dealer_direction import health, ladder, provenance  # noqa: E402
from SDRUtils.dealer_direction import types as T  # noqa: E402


def _series(vals, start="2024-01-01"):
    idx = pd.date_range(start, periods=len(vals), freq="D").date
    return pd.Series(list(vals), index=pd.Index(idx))


def q1_monotone():
    """A classifier that is right with probability `a` on a 78/22 base."""
    print("\n=== Q1: is kappa monotone in classifier accuracy? ===")
    print(f"{'accuracy':>9} {'hit_rate':>9} {'kappa':>8} {'placebo p95':>12} {'status':>7}")
    rng = np.random.default_rng(2)
    n = 3000
    truth = np.where(rng.random(n) < 0.78, 1.0, -1.0)      # the real flow, skewed
    prev = None
    for a in (0.50, 0.60, 0.70, 0.80, 0.90, 1.00):
        flip = rng.random(n) > a
        called = np.where(flip, -truth, truth)             # the D2C call
        recycled = np.r_[0.0, truth[:-1]]                  # the D2D print is the truth
        res = health.d2d_recycling_kappa(_series(called), _series(recycled),
                                         horizon_days=1, n_bootstrap=0)
        print(f"{a:9.2f} {res.hit_rate:9.3f} {res.kappa:8.3f} "
              f"{res.placebo_kappa_p95:12.3f} {res.status:>7}")
        if prev is not None and res.kappa < prev - 0.02:
            print("  !! NOT MONOTONE")
        prev = res.kappa


def q2_naive_misleads():
    """The failure being monitored: a mid bias pushes BOTH sides one way."""
    print("\n=== Q2: does the naive hit rate mislead where kappa does not? ===")
    print(f"{'bias share +':>13} {'hit_rate':>9} {'kappa':>8} {'status':>7}")
    rng = np.random.default_rng(5)
    n = 3000
    for share in (0.50, 0.65, 0.78, 0.90, 0.99, 1.00):
        # no link at all between the two series -- only a shared one-way bias
        x = np.where(rng.random(n) < share, 1.0, -1.0)
        y = np.where(rng.random(n) < share, 1.0, -1.0)
        res = health.d2d_recycling_kappa(_series(x), _series(np.r_[0.0, y[:-1]]),
                                         horizon_days=1, n_bootstrap=0)
        print(f"{share:13.2f} {res.hit_rate:9.3f} {res.kappa:8.3f} {res.status:>7}")


def q3_degenerate_inputs():
    print("\n=== Q3: empty / single-row inputs ===")
    empty_prov = pd.DataFrame(columns=["unit_key", "snapshot_policy",
                                       "snapshot_lag_seconds", "notional_imputed"])
    print("overnight_hole_fraction(empty) ->",
          health.overnight_hole_fraction(empty_prov).status)
    print("imputed_notional_fraction(empty) ->",
          health.imputed_notional_fraction(empty_prov).status)
    print("dead_zone_fraction([]) ->", health.dead_zone_fraction([]).status)
    print("snapshot_lag_distribution(empty) rows ->",
          len(health.snapshot_lag_distribution(empty_prov)))
    print("report_lag_by_block(empty) rows ->",
          len(health.report_lag_by_block(pd.DataFrame())))
    print("pricing_success_by_stratum(empty) rows ->",
          len(health.pricing_success_by_stratum(pd.DataFrame())))
    print("kappa(1 point) ->",
          health.d2d_recycling_kappa(_series([1.0]), _series([1.0])).status)
    print("aggregate(empty) cols ->", list(ladder.aggregate(pd.DataFrame()).columns))
    print("decayed_flow(empty) ->",
          list(ladder.decayed_flow(ladder.aggregate(pd.DataFrame()),
                                   half_life_days=5.0).columns))
    print("coverage_table(empty) rows ->",
          len(provenance.coverage_table(pd.DataFrame(columns=["unit_key",
                                                              "failure_reason"]),
                                        dv01=pd.Series(dtype=float))))


def q4_full_report():
    print("\n=== Q4: a whole day's report, end to end ===")
    in_sess = "method=asof max_lag=60s allow_future=False on_miss=raise"
    hole = "method=asof max_lag=7200s allow_future=False on_miss=raise"
    prov = pd.DataFrame({
        "unit_key": [f"U{i}" for i in range(20)],
        "snapshot_policy": [in_sess] * 19 + [hole],
        "snapshot_lag_seconds": [5.0] * 19 + [3300.0],
        "notional_imputed": [False] * 19 + [True],
    })
    legs = pd.DataFrame({
        "is_block": [False] * 18 + [True] * 2,
        "report_lag_seconds": [0.0] * 20,
    })
    as_of = datetime.date(2026, 6, 10)
    leg_px = pd.DataFrame({
        "as_of_date": [as_of] * 20,
        "effective_date": ([as_of] * 12
                           + [as_of + datetime.timedelta(days=400)] * 6
                           + [as_of - datetime.timedelta(days=90)] * 2),
        "is_capped": [False] * 19 + [True],
        "rate_index": ["SOFR"] * 20,
        "priced": [True] * 20,
    })
    rng = np.random.default_rng(1)
    truth = np.where(rng.random(400) < 0.6, 1.0, -1.0)
    kappa = health.d2d_recycling_kappa(_series(truth), _series(np.r_[0.0, truth[:-1]]),
                                       horizon_days=1, n_bootstrap=100)

    metrics = [
        kappa,
        health.imputed_notional_fraction(
            prov, weights=pd.Series({f"U{i}": 1000.0 for i in range(20)})),
        health.overnight_hole_fraction(prov),
        *health.snapshot_lag_metrics(prov),
    ]
    rep = health.health_report(metrics)
    with pd.option_context("display.width", 200, "display.max_colwidth", 34):
        print(rep[["metric", "value", "n", "status", "warn", "alarm"]].to_string(index=False))
    print("\nlag distribution:")
    print(health.snapshot_lag_distribution(prov).to_string(index=False))
    print("\nreport lag by block:")
    print(health.report_lag_by_block(legs).to_string(index=False))
    print("\npricing success:")
    print(health.pricing_success_by_stratum(leg_px)[
        ["stratum", "n", "n_priced", "success_rate", "status"]].to_string(index=False))


def q5_ladder_multi_group():
    print("\n=== Q5: decay over several series and a weekend gap ===")
    rows = []
    for d in (datetime.date(2026, 6, 12), datetime.date(2026, 6, 15)):   # Fri -> Mon
        for venue in (T.VENUE_D2C, T.VENUE_D2D):
            rows.append({"bucket_space": "IRS_KRD", "bucket_key": "5Y",
                         "visibility_date": d, "venue_class": venue,
                         "series": ladder.SERIES_FLOW, "delta_dv01": 100.0,
                         "abs_dv01": 100.0, "n_units": 1,
                         "mean_abs_signed_weight": 1.0})
    out = ladder.decayed_flow(pd.DataFrame(rows), half_life_days=3.0)
    print(out[["visibility_date", "venue_class", "delta_dv01",
               "decayed_flow_dv01"]].to_string(index=False))
    print("expected Monday value: 100*0.5**(3/3) + 100 = 150.0")
    ladder.assert_series_disjoint(pd.DataFrame(rows))
    print("assert_series_disjoint: OK")


def q6_vintage():
    print("\n=== Q6: the vintage components ===")
    for k, v in provenance.vintage_components().items():
        print(f"  {k:18s} {v}")
    print("  digest            ", provenance.code_vintage())
    print("  on the old curve  ", provenance.code_vintage(
        curve_source="BARCHART_STIRF-RL"))


if __name__ == "__main__":
    q1_monotone()
    q2_naive_misleads()
    q3_degenerate_inputs()
    q4_full_report()
    q5_ladder_multi_group()
    q6_vintage()
