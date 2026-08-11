"""Do the new tests fail when the thing they guard is broken?

A test suite that passes is not evidence until you have seen it fail for the
right reason. Four mutations, each aimed at one specific failure mode this
module exists to prevent.
"""
import dataclasses, os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
import numpy as np
from SDRUtils.dealer_direction import imputation as imp
import tests.test_dealer_direction_imputation as T

def check(name, mutate, restore, test_fn):
    mutate()
    try:
        test_fn()
        verdict = "*** SURVIVED -- the test does not guard this ***"
    except AssertionError as e:
        msg = (str(e).splitlines() or ["<bare assert>"])[0][:70]
        verdict = f"caught ({msg})"
    except Exception as e:
        verdict = f"caught by {type(e).__name__}: {str(e)[:60]}"
    finally:
        restore()
    print(f"{name:<52} {verdict}")

orig_bands = imp.CAP_BANDS
orig_by_cap = dict(imp._BY_CAP)

def set_bands(bands):
    imp.CAP_BANDS = tuple(bands)
    imp._BY_CAP.clear()
    imp._BY_CAP.update({(b.vintage, b.cap): b for b in bands})

def restore():
    imp.CAP_BANDS = orig_bands
    imp._BY_CAP.clear(); imp._BY_CAP.update(orig_by_cap)

# 1. a mis-transcribed multiplier, 10% out
check("multiplier of one band x1.10",
      lambda: set_bands([dataclasses.replace(b, multiplier=b.multiplier * 1.1)
                         if b.label == "5y-10y" and b.vintage == "V2" else b
                         for b in orig_bands]),
      restore, T.test_frozen_multiplier_is_recomputable_from_the_stored_parameters)

# 2. the infinite-mean trap quietly papered over
check("alpha<1 cell rewritten to alpha=1.2",
      lambda: set_bands([dataclasses.replace(b, tail_index=1.2)
                         if b.tail_index < 1 else b for b in orig_bands]),
      restore, T.test_every_band_reports_a_tail_index_and_whether_its_mean_exists)

# 3. the vintage boundary off by one day
orig_vintage = imp.vintage_for
def bad_vintage(d):
    return imp.VINTAGE_V1 if imp._as_date(d) <= imp.CAP_SCHEDULE_SWITCH else imp.VINTAGE_V2
check("vintage_for boundary '<' -> '<='",
      lambda: setattr(imp, "vintage_for", bad_vintage),
      lambda: setattr(imp, "vintage_for", orig_vintage),
      lambda: [T.test_vintage_boundary_is_the_measured_changeover(d, v) for d, v in
               [(__import__("datetime").date(2024, 10, 7), imp.VINTAGE_V2)]])

# 4. THE failure mode: an unrecognised cap silently imputed off the tenor band
orig_impute = imp.impute
def silent_impute(notional, as_of_date, is_capped, tenor_years=None):
    r = orig_impute(notional, as_of_date, is_capped, tenor_years)
    if r.reason == imp.REASON_CAP_UNRECOGNISED and tenor_years is not None:
        band = imp.band_for_tenor(tenor_years, as_of_date)
        return imp.Imputation(True, band.multiplier, band.multiplier * notional,
                              band.label, band.tail_index, band.tail_mean_exists,
                              imp.REASON_IMPUTED)
    return r
check("unrecognised cap silently imputed from tenor",
      lambda: setattr(imp, "impute", silent_impute),
      lambda: setattr(imp, "impute", orig_impute),
      T.test_an_unrecognised_cap_value_is_flagged_not_scaled)

# 5. the multiplier applied to notional instead of the KRD is not catchable by a
#    unit test of this module -- it is prevented by there being no such helper.
check("a scale_notional helper added to the module",
      lambda: setattr(imp, "scale_notional_by_cap_multiplier", lambda n, f: n * f),
      lambda: delattr(imp, "scale_notional_by_cap_multiplier"),
      T.test_the_module_exposes_no_way_to_scale_a_notional)
