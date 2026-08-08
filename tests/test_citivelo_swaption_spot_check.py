r"""The spot check, and five proofs that it can fail.

``tests/test_citivelo_vol_cube.py`` and ``tests/test_citivelo_native_vol_cube.py``
prove the cubes reproduce their own nodes. That is worth pinning and it is also a
tautology: an interpolator is exact at its data sites by construction. Those tests
cannot see a wrong annuity, a wrong schedule, a wrong day count, a wrong
discounting convention or a strike/forward misalignment.

This file drives
:func:`MDP.CitiVelocityExcel.vol.spot_check.spot_check_frame`, which prices the
actual swaption at ``forward + offset/1e4``, inverts the premium with a
pure-Python bisection that shares no code with either pricer, crosses the
annuities between rateslib and QuantLib, and compares against **Citi's own quoted
volatility**.

Everything here runs on the recorded live snapshot
(``MDP/CitiVelocityExcel/harvest/snapshots/usd_cube_2026-08-06.json``): 260 tags
captured from a signed-in add-in, zero per-tag failures. No network, no Excel, no
database. A real skew has wing flattening and a kink that a generated smile does
not, and the mutations below are only convincing against one.

The five mutations exist because the obvious three - shift a node, transpose two
tenor slices, perturb a forward - all move the **volatility** the pricer reads.
Scaling an annuity and swapping payer for receiver do not, so without them the
check could be nothing more than an expensive round trip.
"""

from __future__ import annotations

import dataclasses

import pytest

rl = pytest.importorskip("rateslib")

from MDP.CitiVelocityExcel.curves import build_ql_ois_curve, build_rl_ois_curve  # noqa: E402
from MDP.CitiVelocityExcel.vol.live_snapshot import load_snapshot  # noqa: E402
from MDP.CitiVelocityExcel.vol.rl_native_cube import RATESLIB_NATIVE_AVAILABLE  # noqa: E402
from MDP.CitiVelocityExcel.vol.spot_check import (  # noqa: E402
    DEFAULT_TOLERANCES,
    SpotCheckError,
    assert_spot_check,
    build_ql_mirror_curve,
    format_spot_check_report,
    node_error_matrix,
    spot_check_frame,
    summarise_spot_check,
)
from MDP.CitiVelocityExcel.vol.swaption_cube import build_citivelo_swaption_cube  # noqa: E402

pytestmark = pytest.mark.skipif(
    not RATESLIB_NATIVE_AVAILABLE,
    reason="needs rateslib >= 2.7.0 for IRSplineCube / IRSCall",
)

# A corner of the recorded grid, not all of it: the check prices two swaptions per
# node per backend, and 520 nodes takes minutes. These four points span short and
# long expiries and short and long tails, which is where the schedule conventions
# actually differ.
EXPIRIES = ("1Y", "10Y")
TENORS = ("2Y", "30Y")
OFFSETS = (-200.0, -50.0, 0.0, 50.0, 200.0)


@pytest.fixture(scope="module")
def snapshot():
    return load_snapshot()


@pytest.fixture(scope="module")
def cube(snapshot):
    return snapshot.cube(expiries=EXPIRIES, tenors=TENORS, offsets_bp=OFFSETS)


@pytest.fixture(scope="module")
def curves(snapshot):
    rlc = build_rl_ois_curve(
        par_rates=snapshot.par_rates, ref_date=snapshot.as_of, citi_index=snapshot.citi_index
    )
    qlc = build_ql_ois_curve(
        par_rates=snapshot.par_rates, ref_date=snapshot.as_of, citi_index=snapshot.citi_index
    )
    return rlc, qlc


@pytest.fixture(scope="module")
def clean_frame(cube, curves, snapshot):
    rlc, qlc = curves
    return spot_check_frame(
        cube=cube,
        rl_curve=rlc,
        ql_curve=qlc,
        backends=("rl-native", "ql"),
        citi_index=snapshot.citi_index,
        citi_forwards=snapshot.citi_forwards,
    )


def _pricer(cube_data, curves, snapshot, backend="rl-native"):
    rlc, qlc = curves
    return build_citivelo_swaption_cube(
        cube=cube_data,
        rl_curve=rlc,
        ql_curve=qlc,
        backend=backend,
        citi_index=snapshot.citi_index,
    )


def _run(cube_truth, cube_obj, snapshot):
    """Price through ``cube_obj``, compare against ``cube_truth``'s quotes."""
    return spot_check_frame(
        cube=cube_truth,
        cube_obj=cube_obj,
        backends=("rl-native", "ql"),
        citi_index=snapshot.citi_index,
        expiries=EXPIRIES,
        tenors=TENORS,
        offsets=OFFSETS,
    )


# ------------------------------------------------------------------ #
#                            the control                             #
# ------------------------------------------------------------------ #


def test_the_snapshot_is_real_citi_data(snapshot):
    """Guard the fixture itself: a synthetic stand-in would void every mutation."""
    assert snapshot.currency == "USD"
    assert snapshot.as_of.isoformat() == "2026-08-06"
    assert len(snapshot.vol_quotes) == 260
    assert len(snapshot.par_rates) >= 40
    assert snapshot.citi_forwards, "the published Citi forwards are the only external witness"
    # 1Y10Y normal vol: basis points, not decimals and not percent.
    assert 40.0 < snapshot.vol_quotes["RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y"] < 200.0


def test_clean_cube_passes_and_reports_what_it_measured(clean_frame):
    observed = assert_spot_check(clean_frame)
    assert observed["implied_vol_self_bp"] < DEFAULT_TOLERANCES["implied_vol_self_bp"]
    assert observed["implied_vol_cross_bp"] < DEFAULT_TOLERANCES["implied_vol_cross_bp"]
    assert observed["parity_rel"] < DEFAULT_TOLERANCES["parity_rel"]


def test_every_node_and_both_rights_are_covered(clean_frame):
    expected = len(EXPIRIES) * len(TENORS) * len(OFFSETS) * 2 * 2  # backends x rights
    assert len(clean_frame) == expected
    assert set(clean_frame["offset_bp"]) == set(OFFSETS)
    assert set(clean_frame["right"]) == {"payer", "receiver"}
    assert set(clean_frame["backend"]) == {"rl-native", "ql"}
    assert clean_frame["implied_vol_self_bp"].notna().all()
    assert clean_frame["implied_vol_cross_bp"].notna().all()


def test_the_summary_breaks_the_error_out_rather_than_reporting_one_max(clean_frame):
    summary = summarise_spot_check(clean_frame)
    assert set(summary) == {"by_expiry", "by_tenor", "by_offset", "by_backend", "worst"}
    assert list(summary["by_expiry"].index) == list(EXPIRIES)
    assert list(summary["by_tenor"].index) == list(TENORS)
    assert list(summary["by_offset"].index) == sorted(OFFSETS)
    assert len(summary["worst"]) > 0


def test_the_report_carries_a_per_node_table_for_atm_and_every_offset(clean_frame):
    """The deliverable is a table, not a maximum.

    A max says the worst node is small; it does not say whether the error is
    spread evenly or piled into one corner, and those are different defects. On
    the recorded cube it is piled into one corner (short expiry, long tail, deep
    wing), which only a node-by-node table shows.
    """
    table = node_error_matrix(clean_frame, backend="ql", right="payer")
    assert list(table.columns) == sorted(OFFSETS)
    assert 0.0 in table.columns, "the ATM node must be a column, not a separate report"
    assert len(table) == len(EXPIRIES) * len(TENORS)
    assert table.notna().to_numpy().all()

    report = format_spot_check_report(clean_frame, title="unit test")
    assert "PER NODE" in report
    for label in ("by expiry", "by swap tenor", "by strike offset"):
        assert label in report
    assert "worst 10 nodes" in report


def test_put_call_parity_and_monotonicity_hold_on_the_real_cube(clean_frame):
    assert clean_frame["parity_rel"].abs().max() < 1e-9
    assert clean_frame["monotonic_violation"].max() == 0.0


def test_our_forward_is_where_citi_anchors_its_offsets(clean_frame):
    """The one number the cube cannot check against itself.

    Citi measures its strike offsets from CITI's forward. A gap slides the whole
    smile along the strike axis without changing a single node volatility. This
    is a level check, not an equality: 1 bp is loose enough to survive a fixing
    source or roll-convention difference and tight enough to catch a wrong curve.
    """
    gaps = clean_frame["citi_forward_gap_bp"].dropna()
    assert len(gaps) > 0
    assert gaps.abs().max() < 1.0


def test_the_two_libraries_agree_on_the_premium(clean_frame):
    rel = clean_frame["backend_price_rel"].dropna()
    assert len(rel) > 0
    assert rel.abs().max() < DEFAULT_TOLERANCES["backend_price_rel"]


def test_a_mirrored_quantlib_curve_shows_the_schedules_are_identical(cube, curves, snapshot):
    """Hand both libraries the same nodes and the swaption difference goes to zero.

    This is the strong form of the cross-backend check. With the curve difference
    removed, rateslib's ``IRSCall`` underlying and QuantLib's ``MakeOIS`` produce
    the same forward to ~1e-13 bp and the same annuity to ~1e-15 relative, which
    means the schedule, the roll, the fixed-leg day count, the payment lag and
    the discounting all agree. Whatever is left in the ordinary run is the curve
    bootstrap, not the swaption.
    """
    rlc, _ = curves
    mirrored = build_ql_mirror_curve(rlc.rl_pricing_curve)
    frame = spot_check_frame(
        cube=cube,
        rl_curve=rlc,
        ql_curve=mirrored,
        backends=("rl-native", "ql"),
        citi_index=snapshot.citi_index,
        expiries=EXPIRIES,
        tenors=TENORS,
        offsets=OFFSETS,
    )
    assert_spot_check(frame)

    point = ["expiry", "tenor"]
    fwd = frame.pivot_table(index=point, columns="backend", values="forward", aggfunc="first")
    ann = frame.pivot_table(index=point, columns="backend", values="annuity", aggfunc="first")
    assert ((fwd["ql"] - fwd["rl-native"]).abs() * 1e4).max() < 1e-9, "forwards must coincide"
    assert (((ann["ql"] - ann["rl-native"]) / ann["rl-native"]).abs()).max() < 1e-12

    # The cross-inversion now measures the same thing the self-inversion does,
    # because there is nothing left to cross.
    assert frame["err_cross_bp"].abs().max() == pytest.approx(
        frame["err_self_bp"].abs().max(), rel=1e-3
    )
    assert frame["backend_price_rel"].abs().max() < DEFAULT_TOLERANCES["backend_price_rel"]


# ------------------------------------------------------------------ #
#                            the mutations                           #
# ------------------------------------------------------------------ #


def test_mutation_one_node_shifted_by_a_basis_point(cube, curves, snapshot):
    """The pricer's cube has one node 1 bp off; the quotes are the truth."""
    bad_atm = cube.atm.copy()
    bad_atm.at["1Y", "30Y"] = bad_atm.at["1Y", "30Y"] + 1.0
    mutated = dataclasses.replace(cube, atm=bad_atm)
    frame = _run(cube, _pricer(mutated, curves, snapshot), snapshot)
    with pytest.raises(SpotCheckError, match="implied_vol_self_bp"):
        assert_spot_check(frame)
    hit = frame[(frame["expiry"] == "1Y") & (frame["tenor"] == "30Y") & (frame["offset_bp"] == 0.0)]
    assert hit["err_self_bp"].abs().min() == pytest.approx(1.0, abs=1e-3)


def test_mutation_two_tenor_slices_transposed(cube, curves, snapshot):
    """The 2Y and 30Y columns swapped: same shape, every builder accepts it."""
    swapped = cube.atm.copy()
    swapped[["2Y", "30Y"]] = swapped[["30Y", "2Y"]].to_numpy()
    skew = {}
    for off, frame_ in cube.skew.items():
        flipped = frame_.copy()
        flipped[["2Y", "30Y"]] = flipped[["30Y", "2Y"]].to_numpy()
        skew[off] = flipped
    mutated = dataclasses.replace(cube, atm=swapped, skew=skew)
    frame = _run(cube, _pricer(mutated, curves, snapshot), snapshot)
    with pytest.raises(SpotCheckError, match="implied_vol"):
        assert_spot_check(frame)


def test_mutation_one_forward_perturbed(cube, curves, snapshot):
    """A 5 bp error in one point's forward, with every volatility left alone.

    Nothing in the cube data reveals this - node volatilities are keyed by offset
    and still round-trip exactly. It shows up only because the check prices at a
    strike and inverts back.
    """
    pricer = _pricer(cube, curves, snapshot)
    for backend in ("rl-native", "ql"):
        inner = pricer.with_backend(backend).inner
        fwd, ann, tte = inner._point("1Y", "30Y")
        inner._point_cache[("1Y", "30Y")] = (fwd + 5e-4, ann, tte)
    frame = _run(cube, pricer, snapshot)
    with pytest.raises(SpotCheckError):
        assert_spot_check(frame)
    hit = frame[(frame["expiry"] == "1Y") & (frame["tenor"] == "30Y")]
    assert hit["err_self_bp"].abs().max() > 0.5


def test_mutation_one_annuity_scaled_by_one_percent(cube, curves, snapshot):
    """A wrong annuity is invisible to a self-inversion; this proves it is not here.

    ``premium = notional * annuity * bachelier(...)``, so inverting a backend's own
    premium with its own annuity cancels the error exactly. It is caught because
    the annuity used to invert is the OTHER library's.
    """
    pricer = _pricer(cube, curves, snapshot)
    inner = pricer.with_backend("ql").inner
    fwd, ann, tte = inner._point("10Y", "30Y")
    inner._point_cache[("10Y", "30Y")] = (fwd, ann * 1.01, tte)
    frame = _run(cube, pricer, snapshot)
    with pytest.raises(SpotCheckError, match="implied_vol_cross_bp"):
        assert_spot_check(frame)
    hit = frame[
        (frame["backend"] == "rl-native")
        & (frame["expiry"] == "10Y")
        & (frame["tenor"] == "30Y")
    ]
    assert hit["err_cross_bp"].abs().max() > 0.1


def test_mutation_payer_and_receiver_swapped_on_one_node(cube, curves, snapshot):
    """A right mix-up moves no volatility and breaks no interpolation.

    Patched on the unified object rather than on the backend, because
    ``NativeSwaptionCube._point`` calls its own ``price`` to check that the
    annuity it backed out reprices a 25 bp strike; flipping the right underneath
    that would trip its self-check instead of the spot check, and prove nothing
    about the spot check.
    """
    pricer = _pricer(cube, curves, snapshot)
    native = pricer.with_backend("rl-native")
    original = native.price

    def flipped(expiry, tenor, strike, right="payer", notional=None):
        if (str(expiry), str(tenor)) == ("10Y", "2Y"):
            right = "receiver" if str(right).lower().startswith("pay") else "payer"
        return original(expiry, tenor, strike, right=right, notional=notional)

    native.price = flipped
    try:
        frame = _run(cube, pricer, snapshot)
    finally:
        del native.price
    with pytest.raises(SpotCheckError):
        assert_spot_check(frame)
    hit = frame[
        (frame["backend"] == "rl-native")
        & (frame["expiry"] == "10Y")
        & (frame["tenor"] == "2Y")
        & (frame["offset_bp"] != 0.0)
    ]
    # At the money a payer and a receiver are worth the same, so only the wings
    # move - which is exactly why parity and monotonicity are checked too.
    assert hit["err_self_bp"].abs().max() > 1.0


def test_the_sabr_backend_still_serves_and_is_still_a_fit(cube, curves, snapshot):
    """``ql-sabr`` is preserved, and its looseness is the point of it.

    A ``ql.SabrSwaptionVolatilityCube`` smooths across strikes rather than
    interpolating, so it does NOT reproduce its own input nodes and the ordering
    assertion is skipped for it. That is a property, not a defect - but it means
    it must never be the default, and the difference has to be visible rather than
    assumed. On the recorded snapshot the fit sits within ~2 bp of the quotes
    while the interpolated cube reproduces them exactly.
    """
    pricer = _pricer(cube, curves, snapshot, backend="ql")
    sabr = pricer.with_backend("ql-sabr")
    assert sabr.sabr if hasattr(sabr, "sabr") else True
    assert sabr.inner.sabr is True

    exact_hits, fit_error = 0, 0.0
    for expiry in EXPIRIES:
        for tenor in TENORS:
            for off in OFFSETS:
                quoted = cube.vol(expiry, tenor, off)
                assert pricer.normal_vol(expiry, tenor, offset_bp=off) == pytest.approx(
                    quoted, abs=1e-6
                )
                exact_hits += 1
                fit_error = max(
                    fit_error, abs(sabr.normal_vol(expiry, tenor, offset_bp=off) - quoted)
                )
    assert exact_hits == len(EXPIRIES) * len(TENORS) * len(OFFSETS)
    assert fit_error < 2.0, "the SABR fit has drifted far enough to be a different surface"
    assert fit_error > 0.0, "a SABR cube that reproduced every node exactly would not be a fit"

    # It prices, and the premium is the same order as the interpolated one.
    strike = pricer.strike_for("1Y", "10Y", 0.0)
    assert sabr.price("1Y", "10Y", strike) == pytest.approx(
        pricer.price("1Y", "10Y", strike), rel=5e-3
    )


def test_a_mutated_cube_still_round_trips_its_own_nodes(cube, curves, snapshot):
    """The control for every mutation above: the OLD check would pass all of them.

    A shifted node reproduces itself perfectly once the pricer is built from it -
    which is exactly why a vol -> cube -> vol comparison proves nothing.
    """
    bad_atm = cube.atm.copy()
    bad_atm.at["1Y", "30Y"] = bad_atm.at["1Y", "30Y"] + 1.0
    mutated = dataclasses.replace(cube, atm=bad_atm)
    pricer = _pricer(mutated, curves, snapshot)
    for expiry in EXPIRIES:
        for tenor in TENORS:
            for off in OFFSETS:
                assert pricer.normal_vol(expiry, tenor, offset_bp=off) == pytest.approx(
                    mutated.vol(expiry, tenor, off), abs=1e-9
                )
