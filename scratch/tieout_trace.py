"""Hand-trace the direction mapping in BOTH systems, with numbers.

Run BEFORE trusting any agreement number. A sign error in a pre-registration on
this project survived until an independent reviewer noticed two stated
mechanisms could not both be true, so the mapping is confirmed here on worked
examples that print their arithmetic.

The two systems:

* OLD  ``SDRUtils.stir_flow.classifier.classify_unit``
       on-market:  ``s2m = (traded - mid) * 100``; ``RECEIVED if s2m > 0 else PAID``
       off-market: ``dealer_bought = U < |npv_pay|``; ``itm = PAID if npv_pay > 0
                    else RECEIVED``; ``direction = itm if dealer_bought else other``
* NEW  ``SDRUtils.dealer_direction.conventions`` + ``.upfront``
       on-market:  ``dev = structure_price(traded) - structure_price(mid)``;
                   ``dealer_side(dev)`` -> ``+1 = DEALER_RECEIVED``, ``0`` on a tie
       off-market: ``upfront.classify(...).dealer_sign``

There is NO synthetic pricing here: the mids and NPVs are hand-picked so the
expected answer is known by inspection, which is the point (a checker validated
only against the system it checks reports success and hides the bug).
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import pandas as pd  # noqa: E402

from SDRUtils.dealer_direction import conventions as conv  # noqa: E402
from SDRUtils.dealer_direction import upfront as uf  # noqa: E402
from SDRUtils.stir_flow.classifier import classify_unit  # noqa: E402
from SDRUtils.stir_flow.pricing import LegPricing  # noqa: E402
from SDRUtils.stir_flow.trade_selection import Unit as OldUnit  # noqa: E402

OK = 0
BAD = 0


def check(label, lhs, rhs):
    global OK, BAD
    good = lhs == rhs
    OK += good
    BAD += not good
    print(f"    {'OK  ' if good else 'FAIL'}  {label}: {lhs!r} vs {rhs!r}")


def old_legs(rates_decimal, notional=1e8, ufro=0.0, ptp=None):
    """Minimal leg frame the frozen classifier accepts, maturity-ordered."""
    n = len(rates_decimal)
    return pd.DataFrame({
        "trade_id": [f"T{i}" for i in range(n)],
        "package_id": [None] * n,
        "as_of_date": [pd.Timestamp("2026-04-01").date()] * n,
        "execution_timestamp": [pd.Timestamp("2026-04-01 14:30", tz="UTC")] * n,
        "effective_date": [pd.Timestamp("2026-04-03").date()] * n,
        "expiration_date": [pd.Timestamp("2027-04-03").date()
                            + pd.Timedelta(days=365 * i) for i in range(n)],
        "fixed_rate": list(rates_decimal),
        "notional": [notional] * n,
        "risk": [1e4] * n,
        "other_payment_ufro": [ufro] * n,
        "pkg_ptp": [ptp] * n,
        "rate_index_clean": ["SOFR"] * n,
        "special_tenor_type": [None] * n,
        "is_block": [False] * n,
        "leg_tape_label": [""] * n,
        "trade_type": ["OUTRIGHT"] * n,
    })


def run_rate_case(name, kind, traded_pct, mid_pct, expect_old, expect_sign):
    print(f"\n[{name}] kind={kind}")
    n = len(traded_pct)
    legs = old_legs([r / 100.0 for r in traded_pct])
    unit = OldUnit(f"U_{name}", kind, legs, None, False)
    pricings = [LegPricing(mid_pct=m, npv_pay=None, pv01=1e4) for m in mid_pct]
    res = classify_unit(unit, pricings)

    dev = (conv.structure_price(traded_pct, kind, n, conv.RULE_RATE)
           - conv.structure_price(mid_pct, kind, n, conv.RULE_RATE))
    sign = conv.dealer_side(dev)

    print(f"    traded_pct={traded_pct}  mid_pct={mid_pct}")
    print(f"    OLD  quote coeffs implicit; s2m = {res.spread_to_mid_bps!r} bp"
          f"  -> dealer_direction = {res.dealer_direction!r}"
          f"  (method {res.classification_method})")
    print(f"    NEW  q = {conv.quote_weights(kind, n, conv.RULE_RATE)}"
          f"  P_traded = {conv.structure_price(traded_pct, kind, n, conv.RULE_RATE):.6f} bp"
          f"  P_mid = {conv.structure_price(mid_pct, kind, n, conv.RULE_RATE):.6f} bp")
    print(f"    NEW  dev = {dev!r} bp -> dealer_side = {sign!r} "
          f"({'DEALER_RECEIVED' if sign > 0 else 'DEALER_PAID' if sign < 0 else 'NO CALL'})")
    check("old direction", res.dealer_direction, expect_old)
    check("new dealer_sign", sign, expect_sign)
    check("old s2m == new dev", round(float(res.spread_to_mid_bps), 12), round(dev, 12))
    mapped = {1: "RECEIVED", -1: "PAID"}.get(sign)
    check("SAME SIDE", mapped, res.dealer_direction)


def run_upfront_case(name, npv_pay, upfront, dv01, expect_old, expect_sign):
    print(f"\n[{name}] npv_pay={npv_pay} U={upfront} dv01={dv01}")
    # OLD, arithmetic reproduced from classifier.classify_unit lines 68-83
    dealer_bought = upfront < abs(npv_pay)
    itm = "PAID" if npv_pay > 0 else "RECEIVED"
    old_dir = itm if dealer_bought else ("RECEIVED" if itm == "PAID" else "PAID")
    print(f"    OLD  dealer_bought = (U < |npv|) = {dealer_bought}; itm_side = {itm}"
          f"  -> {old_dir}")

    call = uf.classify(npv_pay=npv_pay, upfront=upfront, structure_dv01=dv01)
    print(f"    NEW  dev = -npv/dv01 = {call.dev_bps:.6f} bp; u = U/dv01 = "
          f"{call.upfront_bps:.6f} bp; z = |dev|-u = {call.residual_bps:.6f} bp")
    print(f"    NEW  edge = sign(dev)*z = {call.edge_bps:.6f} -> dealer_sign = "
          f"{call.dealer_sign!r}")
    check("old direction", old_dir, expect_old)
    check("new dealer_sign", call.dealer_sign, expect_sign)
    mapped = {1: "RECEIVED", -1: "PAID"}.get(call.dealer_sign)
    check("SAME SIDE", mapped, old_dir)


def main():
    print("=" * 78)
    print("DIRECTION MAPPING HAND-TRACE  (old stir_flow  vs  new dealer_direction)")
    print("=" * 78)
    print("convention: p = p(customer paid fixed) = p(dealer RECEIVED fixed);")
    print("            conventions.DEALER_RECEIVED = +1, DEALER_PAID = -1, tie = 0")

    # --- the rate rule ----------------------------------------------------
    # OUTRIGHT: printed 5 bp ABOVE mid -> the customer overpaid -> dealer received
    run_rate_case("outright_above_mid", "OUTRIGHT", [4.05], [4.00],
                  "RECEIVED", conv.DEALER_RECEIVED)
    run_rate_case("outright_below_mid", "OUTRIGHT", [3.95], [4.00],
                  "PAID", conv.DEALER_PAID)
    # CURVE: legs maturity-ordered, so index 0 is the FRONT leg. Both systems
    # quote back-minus-front: old (traded[1]-traded[0]), new q = (-1, +1).
    run_rate_case("curve_above_mid", "CURVE", [4.00, 4.20], [4.00, 4.10],
                  "RECEIVED", conv.DEALER_RECEIVED)
    run_rate_case("curve_below_mid", "CURVE", [4.00, 4.05], [4.00, 4.10],
                  "PAID", conv.DEALER_PAID)
    # FLY: index 1 is the belly. Old 2*t1-t0-t2, new q = (-1, +2, -1).
    run_rate_case("fly_above_mid", "FLY", [4.00, 4.20, 4.30], [4.00, 4.15, 4.30],
                  "RECEIVED", conv.DEALER_RECEIVED)
    run_rate_case("fly_below_mid", "FLY", [4.00, 4.10, 4.30], [4.00, 4.15, 4.30],
                  "PAID", conv.DEALER_PAID)

    # --- the zero branch, which is where the two systems genuinely differ ---
    print("\n[outright_exact_tie] the ONE deliberate divergence (LEDGER T-4)")
    legs = old_legs([0.04])
    unit = OldUnit("U_tie", "OUTRIGHT", legs, None, False)
    res = classify_unit(unit, [LegPricing(mid_pct=4.00, npv_pay=None, pv01=1e4)])
    dev = 0.0
    print(f"    OLD  s2m = {res.spread_to_mid_bps!r} -> {res.dealer_direction!r}"
          "   (`RECEIVED if s2m > 0 else PAID` has NO zero branch)")
    print(f"    NEW  dealer_side(0.0) = {conv.dealer_side(dev)!r}   (0 = no call)")
    check("old calls PAID on an exact tie", res.dealer_direction, "PAID")
    check("new refuses to call an exact tie", conv.dealer_side(dev), 0)

    # --- the upfront rule -------------------------------------------------
    # npv_pay is the PAYER-frame NPV summed over legs. npv_pay > 0 means paying
    # fixed is in the money.
    run_upfront_case("upfront_dealer_bought_itm_payer", 100.0, 5.0, 10.0,
                     "PAID", conv.DEALER_PAID)
    run_upfront_case("upfront_dealer_sold_itm_payer", 100.0, 200.0, 10.0,
                     "RECEIVED", conv.DEALER_RECEIVED)
    run_upfront_case("upfront_dealer_bought_itm_recvr", -100.0, 5.0, 10.0,
                     "RECEIVED", conv.DEALER_RECEIVED)
    run_upfront_case("upfront_dealer_sold_itm_recvr", -100.0, 200.0, 10.0,
                     "PAID", conv.DEALER_PAID)

    # --- p, and why b0 must be zero for the LOGIC tie-out ------------------
    print("\n[probability mapping]  p = sigmoid((dev - b0)/tau) = p(dealer RECEIVED)")
    from SDRUtils.dealer_direction import probability as prob
    fit0 = prob.MixtureFit(bucket="TRACE", n=1000, n_trimmed=1000,
                           b0=0.0, h=0.35, s=0.30, loglik=0.0)
    for d in (-2.0, -0.05, 0.0, 0.05, 2.0):
        p = prob.p_customer_paid(d, fit0)
        side = "RECEIVED" if p > 0.5 else "PAID"
        print(f"    dev = {d:+6.2f} bp -> p = {p:.6f} -> {side:8s}"
              f"   dealer_side = {conv.dealer_side(d):+d}")
    check("b0=0: p>0.5 iff dev>0 (+)", prob.p_customer_paid(1e-9, fit0) > 0.5, True)
    check("b0=0: p>0.5 iff dev>0 (-)", prob.p_customer_paid(-1e-9, fit0) > 0.5, False)
    fitb = prob.MixtureFit(bucket="TRACE_B0", n=1000, n_trimmed=1000,
                           b0=-0.4836, h=0.35, s=0.30, loglik=0.0)
    pb = prob.p_customer_paid(-0.20, fitb)
    print(f"    with the measured Barchart b0 = -0.4836 (F-20): dev = -0.20 bp"
          f" -> p = {pb:.4f} -> {'RECEIVED' if pb > 0.5 else 'PAID'}"
          "   <- OPPOSITE of the old rule, by CALIBRATION not by logic")
    check("fitted b0 flips a sub-bias print", pb > 0.5, True)

    print("\n" + "=" * 78)
    print(f"checks: {OK} ok, {BAD} failed")
    print("=" * 78)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
