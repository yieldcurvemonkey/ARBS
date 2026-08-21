r"""The gate tests the futures leg and nothing tests the swap leg.

``gate_ok = gate_covered & gate_resolved & gate_settle_agrees``, and all three
are statements about the futures side. All three can pass while the swap half of
``CA = pack_rate - swap_rate`` is unusable — which is exactly what happens in
2019-2020, where the SOFR swap curve is thin at multi-year forward starts because
SOFR discounting had not switched yet.

Measured, Golds: 92.8 % of 2020 readings are negative at a median of -19.93 bp,
while the two *futures* sources agree to 0.029 bp. A convexity adjustment is
bounded below by zero in any arbitrage-free model, so that is a measurement, not
a price.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV.ca_swap_leg_gate import (
    SWAP_LEG_MIN_DATE, add_swap_leg_gate, swap_leg_report)


def _panel() -> pd.DataFrame:
    """Rows that look like the shipped panel, spanning the bad era and the good."""
    rows = []
    for d, colour, ca in [
        ("2020-06-01", "Golds", -19.9),      # the era, and impossible magnitude
        ("2020-06-02", "Golds", -3.0),       # the era, plausible magnitude
        ("2020-06-03", "Blues", +2.0),       # the era, positive
        ("2023-06-01", "Golds", +20.9),      # good era
        ("2025-06-02", "Whites", -0.4),      # good era, small negative: KEEP
        ("2025-06-03", "Reds", -8.0),        # good era, impossible magnitude: DROP
    ]:
        rows.append({"date": pd.Timestamp(d), "colour": colour, "ca_bp": ca,
                     "gate_ok": True})
    return pd.DataFrame(rows)


def test_the_shipped_gate_says_nothing_about_the_swap_leg():
    """The premise. If gate_ok ever starts covering it, this file is redundant."""
    import inspect

    from RVUtils.ConvexityRV import strat2_q20 as Q

    src = inspect.getsource(Q)
    assert "gate_settle_agrees" in src
    # the three components are all futures-side; none mentions the swap rate
    assert "gate_swap" not in src, (
        "strat2_q20 now has a swap-leg gate of its own; fold this module into it"
    )


def test_the_early_sofr_era_is_excluded():
    out = add_swap_leg_gate(_panel())
    early = out[pd.to_datetime(out["date"]) < SWAP_LEG_MIN_DATE]
    assert len(early) == 3
    assert not early["gate_swap_sane"].any(), (
        "2019-2020 rows survived; the swap curve is thin at multi-year forward "
        "starts before SOFR discounting switched"
    )


def test_a_small_negative_reading_is_KEPT():
    """Dropping every negative reading would be fitting the theory.

    Where the true adjustment is near zero -- Whites runs a median of 0.098 bp --
    symmetric quote noise flips the sign often, and that is a measurement of a
    small number, not an error.
    """
    out = add_swap_leg_gate(_panel())
    w = out[(out["colour"] == "Whites")]
    assert len(w) == 1 and float(w["ca_bp"].iloc[0]) < 0
    assert bool(w["gate_swap_sane"].iloc[0]), (
        "a -0.4bp reading in a good era was dropped; the backstop is on "
        "MAGNITUDE, not on sign"
    )


def test_an_impossible_magnitude_is_dropped_even_in_a_good_era():
    out = add_swap_leg_gate(_panel())
    r = out[(out["colour"] == "Reds") & (out["ca_bp"] < -5)]
    assert len(r) == 1
    assert not bool(r["gate_swap_sane"].iloc[0])


def test_gate_ok_itself_is_not_modified():
    """Widening a published column silently moves numbers other work has quoted."""
    p = _panel()
    out = add_swap_leg_gate(p)
    assert out["gate_ok"].tolist() == p["gate_ok"].tolist()
    assert "gate_ok_full" in out.columns
    assert out["gate_ok_full"].tolist() == (
        out["gate_ok"] & out["gate_swap_sane"]).tolist()


def test_the_report_shows_what_would_be_removed():
    """A filter nobody can see the effect of is one nobody applied."""
    rep = swap_leg_report(_panel())
    assert {"year", "colour", "n", "dropped", "frac_dropped"} <= set(rep.columns)
    assert int(rep["dropped"].sum()) == 4          # 3 early + 1 impossible
