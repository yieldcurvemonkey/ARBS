"""S3 -- what `ladder.unit_ladder_rows` does with a recovered PKG-N unit.

`package_price.classify` produces a per-leg SIGN and a `deviation_bps`, but no
`p`: there is no package tau, because nothing has fitted `probability
.fit_mixture` on the package residual. This traces, rather than asserts, what
the ladder does with such a call in each of the three states a producer could
hand it over in.

Curve-free: the KRD frame is written by hand so the trace is about the ladder's
own branching and not about pricing. Run:

    python scratch/ddseam_ladder_trace.py
"""
from __future__ import annotations

import datetime
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import pandas as pd  # noqa: E402

from SDRUtils.dealer_direction import conventions as conv  # noqa: E402
from SDRUtils.dealer_direction import krd, ladder  # noqa: E402
from SDRUtils.dealer_direction import package_price as pp  # noqa: E402
from SDRUtils.dealer_direction import types as T  # noqa: E402

TS = pd.Timestamp("2026-06-17 15:00", tz="America/New_York")
TENORS = ("2Y", "5Y", "10Y", "30Y")


def _unit(unit_key="PKG"):
    legs = pd.DataFrame([
        {"trade_id": f"{unit_key}-{i}",
         "effective_date": datetime.date(2026, 6, 19),
         "expiration_date": datetime.date(2026 + y, 6, 19),
         "notional": 1e8, "fixed_rate": 0.04}
        for i, y in enumerate((2, 5, 10, 30))
    ])
    clocks = T.Clocks(pricing=TS, execution=TS, event=TS,
                      visibility=TS + pd.Timedelta(minutes=15),
                      visibility_source="APPENDIX_C_ESTIMATE")
    return T.Unit(unit_key=unit_key, kind=conv.PKG, legs=legs,
                  package_id=unit_key, rate_index="SOFR",
                  as_of_date=datetime.date(2026, 6, 17),
                  venue_class=T.VENUE_D2C, clocks=clocks, upfront=3_000.0,
                  upfront_source="PTP")


def _krd_frame(unit_key, signs):
    return pd.DataFrame([
        {"unit_key": unit_key, "bucket_space": krd.BUCKET_SPACE,
         "bucket_key": t, "dv01_if_received": s * 80_000.0}
        for t, s in zip(TENORS, signs)
    ])


def main() -> None:
    # Powers of two so the signed subset-sum is unique, and scaled so the
    # solver's margin to the runner-up (2 * min(opa) = 30,000 = 1.5 bp of the
    # 20,000 USD/bp package DV01) clears the ambiguity gate.
    got = pp.classify(opas=[15_000.0, 30_000.0, 60_000.0, 120_000.0],
                      package_price=-45_000.0,
                      npv_pays=[-6_000.0, 7_000.0, -5_000.0, 12_000.0],
                      pv01s=[1e4] * 4, structure_dv01=2e4)
    assert got.exclusion is None, got.exclusion
    print(f"package_price.classify -> dealer_sign={got.dealer_sign}, "
          f"deviation_bps={got.deviation_bps}, p=<the rule produces none>, "
          f"base_orientation={got.base_orientation}")

    unit = _unit()
    frame = _krd_frame(unit.unit_key, got.base_orientation)
    gross = float(frame["dv01_if_received"].abs().sum())
    print(f"KRD gross |DV01| available to the ladder: {gross:,.0f}\n")

    def call(**kw):
        base = dict(unit_key=unit.unit_key, rule=pp.RULE_PACKAGE_PRICE,
                    deviation_bps=got.deviation_bps, p=None, signed_weight=None,
                    dealer_sign=got.dealer_sign, tau_bucket=None, tau_bps=None,
                    base_orientation=got.base_orientation)
        base.update(kw)
        return T.DirectionCall(**base)

    cases = {
        "A. p=None, no exclusion (what the rule actually produces today)":
            call(),
        "B. p=None, exclusion=UNORIENTABLE_PKG (the pre-recovery state)":
            call(exclusion=T.EXCL_UNORIENTABLE),
        # `p` has to sit on `dealer_sign`'s side or `_assert_weight_agrees_
        # _with_side` refuses -- case D. So the fitted p is mirrored about 0.5.
        "C. p from a fitted package tau (what S3 says is missing)":
            call(p=(0.62 if got.dealer_sign >= 0 else 0.38),
                 signed_weight=conv.signed_weight(
                     0.62 if got.dealer_sign >= 0 else 0.38),
                 tau_bucket="PKG", tau_bps=0.35),
        "D. the same p on the WRONG side of 0.5 (a producer constraint)":
            call(p=(0.38 if got.dealer_sign >= 0 else 0.62),
                 signed_weight=conv.signed_weight(
                     0.38 if got.dealer_sign >= 0 else 0.62),
                 tau_bucket="PKG", tau_bps=0.35),
    }
    for label, c in cases.items():
        print(label)
        try:
            rows, excluded = ladder.unit_ladder_rows([unit], [c], frame)
        except Exception as exc:                                  # noqa: BLE001
            print(f"    RAISES {type(exc).__name__}: {str(exc)[:160]}\n")
            continue
        weighted = float(rows["delta_dv01"].abs().sum()) if len(rows) else 0.0
        print(f"    rows={len(rows)}  excluded={len(excluded)}"
              f"{'  reason=' + str(excluded['failure_reason'].iloc[0]) if len(excluded) else ''}")
        print(f"    |delta_dv01| reaching the ladder: {weighted:,.0f} "
              f"of {gross:,.0f} gross ({100 * weighted / gross:.1f}%)\n")

    print("EXCL_* names available for 'oriented but not weightable': none.")
    print("  types.EXCL_*:", [n for n in dir(T) if n.startswith("EXCL_")])
    print("  package_price.STRATA:", list(pp.STRATA))


if __name__ == "__main__":
    main()
