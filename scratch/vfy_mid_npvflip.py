"""pytest plugin (verification pass): flip the NPV frame on the REAL pricing path.

The review's finding was that `test_npv_is_the_fixed_payer_frame_summed_over_legs`
pins the fake's own arithmetic, so a receiver-frame `IRSwapValue.NPV` would pass
it unchanged. The fix is a new `slow` test on the Citi minute curve. This mutant
exists to show that new test can actually fail: it negates `npv_pay` coming out
of `SessionBranchPricer.price_leg`, which is the real seam, and leaves the fake
untouched.

Selected by ARBS_MUTV=npv_receiver_frame.
"""
import os


def pytest_configure(config):
    if os.environ.get("ARBS_MUTV", "") != "npv_receiver_frame":
        return
    from SDRUtils.dealer_direction import midprice

    orig = midprice.SessionBranchPricer.price_leg

    def price_leg(self, *a, **kw):
        lp = orig(self, *a, **kw)
        if getattr(lp, "npv_pay", None) is None:
            return lp
        try:
            import dataclasses
            return dataclasses.replace(lp, npv_pay=-lp.npv_pay)
        except Exception:
            return type(lp)(mid_pct=lp.mid_pct, npv_pay=-lp.npv_pay, pv01=lp.pv01)

    midprice.SessionBranchPricer.price_leg = price_leg
