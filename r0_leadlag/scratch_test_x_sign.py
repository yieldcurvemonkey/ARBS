"""Unit test for the ONE place the R0 sign convention lives.

The pre-registered chain (r0_prereg.md, not editable):

    customer pays fixed
      -> dealer received fixed
      -> dealer is long duration
      -> dealer SELLS futures to hedge

therefore **positive X predicts NEGATIVE signed futures flow**, and the hedge
channel appears as ``beta_k < 0`` at small positive ``k``. A positive ``beta_k`` of
the same magnitude is a different phenomenon, not a pass.

Run:  C:/Users/chris/anaconda3/envs/stir/python.exe r0_leadlag/scratch_test_x_sign.py

MUTATION-CHECKED. Every mutation below was actually applied to build_x_tape.py and
the suite confirmed to FAIL; a passing suite on unmutated code proves nothing on its
own. Two mutations survived the first draft of this file and the tests were
strengthened until they did not:
  predicted_futures_sign returns +x .................. killed by test_prereg_chain
  tick rule inverted (rate > mid -> -1) .............. killed by test_tick_rule
  tie returns +1 instead of 0 ........................ killed by test_end_to_end
  mid window leaks 2 future prints (t[lo:j+2]) ....... killed by test_mid_window_is_causal
      (SURVIVED the first draft -- the fixture's rates were symmetric, so leaking
       left the median unchanged; the fixture is now monotone)
  MID_WINDOW_N 10 -> 1000 ............................ killed by test_mid_window_length_cap
  MID_WINDOW_MAX_AGE 24h -> 3650d .................... killed by test_mid_window_age_cap
  MID_WINDOW_MIN_N 3 -> 0 ............................ killed by test_mid_window_min_predecessors
      (SURVIVED the first draft -- every fixture used identical rates, so early
       prints tied to unsigned whatever the minimum was; the fixture is now distinct)
  bucket edge 12y inclusive -> exclusive ............. killed by test_bucket_boundaries
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_x_tape as B


def test_prereg_chain():
    """positive X (customer paid) must predict NEGATIVE futures flow."""
    assert B.predicted_futures_sign(+1) == -1, (
        "customer PAID fixed -> dealer RECEIVED -> dealer long duration -> dealer "
        "SELLS futures. Positive X must predict negative Y."
    )
    assert B.predicted_futures_sign(-1) == +1, (
        "customer RECEIVED fixed -> dealer PAID -> dealer short duration -> dealer "
        "BUYS futures."
    )
    assert B.predicted_futures_sign(0) == 0
    print("PASS test_prereg_chain")


def test_tick_rule():
    """rate above the recent same-key median == the customer paid fixed."""
    assert B.customer_sign_from_mid(0.0405, 0.0400) == +1   # paid
    assert B.customer_sign_from_mid(0.0395, 0.0400) == -1   # received
    assert B.customer_sign_from_mid(0.0400, 0.0400) == 0    # tie -> unsigned
    assert B.customer_sign_from_mid(0.0400, np.nan) == 0    # no mid -> unsigned
    assert B.customer_sign_from_mid(np.nan, 0.0400) == 0
    assert B.customer_sign_from_mid(0.0400, None) == 0
    print("PASS test_tick_rule")


def test_end_to_end():
    """A synthetic tape whose answer is known by construction.

    Five identical 10y prints at 4.00% establish the mid, then one print at 4.05%
    (customer paid) and one at 3.95% (customer received). The paid print must carry
    +1 and therefore predict a dealer SELL in futures.
    """
    base = pd.Timestamp("2026-06-01 12:00", tz="UTC")
    rows = []
    for i, r in enumerate([0.0400] * 5 + [0.0405, 0.0395]):
        rows.append(dict(
            trade_id=f"t{i}", execution_timestamp=base + pd.Timedelta(minutes=i),
            fixed_rate=r, rate_index_clean="SOFR", tenor_label="10Y",
            fwd_key="spot", is_mac=False,
        ))
    out = B.attach_mid_sign(pd.DataFrame(rows))
    got = dict(zip(out["trade_id"], out["customer_sign"]))
    assert got["t0"] == got["t1"] == got["t2"] == 0, "first 3 have <3 predecessors"
    assert got["t3"] == 0 and got["t4"] == 0, "ties against a 4.00% mid are unsigned"
    assert got["t5"] == +1, f"4.05% vs a 4.00% mid is customer PAID, got {got['t5']}"
    assert got["t6"] == -1, f"3.95% vs a 4.00% mid is customer RECEIVED, got {got['t6']}"
    assert B.predicted_futures_sign(got["t5"]) == -1
    print("PASS test_end_to_end")


def _frame(rates, minutes=None):
    base = pd.Timestamp("2026-06-01 12:00", tz="UTC")
    return pd.DataFrame([
        dict(trade_id=f"t{i}",
             execution_timestamp=base + pd.Timedelta(minutes=(minutes[i] if minutes else i)),
             fixed_rate=r, rate_index_clean="SOFR", tenor_label="10Y",
             fwd_key="spot", is_mac=False)
        for i, r in enumerate(rates)
    ])


def test_mid_window_is_causal():
    """The mid must never see a print at or after the one it is signing.

    Constructed so that ANY forward leak changes both the mid VALUE and the SIGN --
    an earlier version of this test used a symmetric set of rates where leaking two
    future prints left the median unchanged, so the bug survived the mutation.
    Rates rise monotonically and two enormous prints sit just after the print under
    test, so a leaking window drags the median up past the print and flips +1 to 0.
    """
    rates = [0.010, 0.020, 0.030, 0.025, 0.990, 0.990]
    out = B.attach_mid_sign(_frame(rates)).set_index("trade_id")
    assert out.loc["t3", "mid"] == 0.020, (
        f"mid at t3 must be median(0.010, 0.020, 0.030) = 0.020, got {out.loc['t3','mid']} "
        "-- a value of 0.025 or 0.030 means the window is leaking future prints"
    )
    assert out.loc["t3", "customer_sign"] == +1, (
        f"0.025 above a 0.020 mid is customer PAID, got {out.loc['t3','customer_sign']}"
    )
    print("PASS test_mid_window_is_causal")


def test_mid_window_length_cap():
    """Only the last MID_WINDOW_N predecessors may enter the median.

    Ten stale 0.99 prints then ten recent 0.04 prints: with the cap at 10 the mid is
    0.04 and the target signs -1; without the cap the stale block drags the median up.
    """
    assert B.MID_WINDOW_N == 10
    rates = [0.99] * 10 + [0.04] * 10 + [0.03]
    out = B.attach_mid_sign(_frame(rates)).set_index("trade_id")
    assert out.loc["t20", "mid"] == 0.04, (
        f"mid must use only the last 10 predecessors, got {out.loc['t20','mid']}"
    )
    assert out.loc["t20", "customer_sign"] == -1
    print("PASS test_mid_window_length_cap")


def test_mid_window_min_predecessors():
    """A print with fewer than MID_WINDOW_MIN_N predecessors must be UNSIGNED.

    Rates are all DISTINCT and monotone here on purpose: with the identical-rate
    fixtures used elsewhere every early print ties and reads as unsigned whatever the
    minimum is, so lowering MID_WINDOW_MIN_N went undetected. With distinct rates a
    smaller minimum would sign t1 and t2, and this test fails.
    """
    assert B.MID_WINDOW_MIN_N == 3
    out = B.attach_mid_sign(_frame([0.010, 0.020, 0.030, 0.040, 0.050])).set_index("trade_id")
    for t in ("t0", "t1", "t2"):
        assert not np.isfinite(out.loc[t, "mid"]), (
            f"{t} has fewer than 3 predecessors and must have NO mid, "
            f"got {out.loc[t, 'mid']}"
        )
        assert out.loc[t, "customer_sign"] == 0, f"{t} must be unsigned"
    assert np.isfinite(out.loc["t3", "mid"]), "t3 has exactly 3 predecessors and must be signed"
    assert out.loc["t3", "mid"] == 0.020
    assert out.loc["t3", "customer_sign"] == +1
    print("PASS test_mid_window_min_predecessors")


def test_mid_window_age_cap():
    """Predecessors older than 24h must not count towards the minimum."""
    out = B.attach_mid_sign(_frame([0.04 + 0.0001 * i for i in range(6)],
                                   minutes=[3 * 1440 * i for i in range(6)]))
    assert out["mid"].isna().all(), "prints 3 days apart can never form a 24h window"
    assert (out["customer_sign"] == 0).all()
    print("PASS test_mid_window_age_cap")


def test_bucket_boundaries():
    """The documented edge inclusivity, pinned."""
    cases = [(0.5, "SFR_FF"), (1.5, "SFR_FF"), (1.51, "TU"), (2.0, "TU"), (3.0, "TU"),
             (3.01, "FV"), (5.0, "FV"), (7.0, "FV"), (7.01, "TY_UXY"),
             (10.0, "TY_UXY"), (12.0, "TY_UXY"), (12.01, "US"), (30.0, "US")]
    for t, want in cases:
        assert B.bucket_for_tenor(t) == want, f"tenor {t} -> {B.bucket_for_tenor(t)}, want {want}"
    # the vectorised path must agree with the scalar one
    s = pd.Series([c[0] for c in cases])
    assert list(B._bucket_series(s)) == [c[1] for c in cases], "vectorised bucket drift"
    print("PASS test_bucket_boundaries")


def test_forward_key_agrees_vectorised():
    vals = [np.nan, 0.0, 0.02, 0.1, 0.3, 0.6, 1.0, 1.5, 3.0, 10.0]
    scalar = [B.forward_start_key(v) for v in vals]
    vec = list(B._forward_key_series(pd.Series(vals)))
    assert scalar == vec, f"forward key drift: {scalar} vs {vec}"
    print("PASS test_forward_key_agrees_vectorised")


if __name__ == "__main__":
    test_prereg_chain()
    test_tick_rule()
    test_end_to_end()
    test_mid_window_is_causal()
    test_mid_window_length_cap()
    test_mid_window_min_predecessors()
    test_mid_window_age_cap()
    test_bucket_boundaries()
    test_forward_key_agrees_vectorised()
    print("\nALL SIGN-CONVENTION TESTS PASSED")
