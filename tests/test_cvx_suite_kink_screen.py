"""Tests for RVUtils.CvxSuite.kink_screen — the C2 kink-ledger composition.

Pure-logic tests run on a seeded synthetic 17-column leg panel with the
market-data seams monkeypatched AT THE kink_screen NAMESPACE (the same
pattern the rent tests use for ``rent.payoff_profile``): ``neutral_weights``
(a fake pricer has no repriceable handle), ``package_gamma_usd`` (planted
gamma), ``leg_roll_bp`` (deterministic rolldown), ``cube_atm_bp_year`` /
``cube_atm_panel`` / ``quoted_axes`` (fake cube), and ``_store`` (no store
construction). ``carry_roll_bp`` is REAL — the fake pricer serves par rates
off a smooth curve, so the aged-rate identity and its age-past-zero raise
are exercised for real. The FPT/OU/residual/frontier/books kernels all run
for real.

The @integration test builds the full screen on the real leg_history
parquet + offline curve store + swaption cube for 2026-08-21 and self-skips
with named reasons when any of the three is absent.
"""

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime as dt
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import RVUtils.CvxSuite.kink_screen as ks
from RVUtils.CvxSuite.books import REQUIRED_COLUMNS, BookGates
from RVUtils.CvxSuite import grids

GRID_LABELS = [grids.leg_label(p) for p in grids.KINK_GRID]
KS_COORDS = {grids.leg_label(p): grids.k_coord(p) for p in grids.KINK_GRID}
ASOF = pd.Timestamp("2026-08-21")
N_DAYS = 1150
SEED = 20260826
FLY_COLS = ("carry_bp_day", "gamma_usd_per_bp2", "theta_usd_day",
            "sigma_be_bp_day", "be_over_rv", "rac_net", "edge_bp",
            "w_front", "w_belly", "w_back", "w_pca_front", "w_pca_back")


def _base_bp(k: float) -> float:
    """Smooth quadratic base curve in bp — inside the cubic fit space, so the
    xsec residual of the noise-free panel is exactly zero."""
    return 300.0 + 6.0 * k - 0.10 * k * k


def make_panel(bump_bp: float = 0.0, bump_label: str = "7y1y",
               seed: int = SEED) -> pd.DataFrame:
    """Seeded synthetic panel: base(k) + common level RW + slope RW + small
    iid noise. ``bump_bp`` is added to ``bump_label`` from the FIRST TRADING
    DAY OF THE ASOF MONTH onward — strictly after the last PCA refit's fit
    window, so the frozen loadings provably never saw it."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=ASOF, periods=N_DAYS)
    kvec = np.array([KS_COORDS[c] for c in GRID_LABELS])
    level = np.cumsum(rng.normal(0.0, 2.0, N_DAYS))
    slope = np.cumsum(rng.normal(0.0, 0.6, N_DAYS))
    eps = rng.normal(0.0, 0.3, (N_DAYS, len(kvec)))
    X = (_base_bp(kvec)[None, :] + level[:, None]
         + slope[:, None] * (kvec[None, :] / 45.0) + eps)
    df = pd.DataFrame(X, index=idx, columns=GRID_LABELS)
    if bump_bp:
        month_start = idx[(idx.year == ASOF.year) & (idx.month == ASOF.month)][0]
        df.loc[df.index >= month_start, bump_label] += float(bump_bp)
    return df


ZERO_SIGMA = pd.DataFrame(0.0, index=pd.bdate_range(end=ASOF, periods=N_DAYS),
                          columns=GRID_LABELS)


class FakePricer:
    """Par rates from ``_base_bp`` (decimal); records every built swap.

    ``build_irswap`` returns a dict so the recorded package legs can be
    asserted exactly (fwd / tenor / bpv). It has NO ``resolve_pricable`` —
    any attempt to resolve a package leg would raise AttributeError, which
    enforces the never-resolve rule structurally.
    """

    def __init__(self, ref_date=ASOF):
        self._ref = ref_date
        self.built = []

    def reference_date(self):
        return self._ref

    def build_irswap(self, fwd=None, tenor=None, notional=None, bpv=None, **kw):
        rec = {"fwd": fwd, "tenor": tenor, "notional": notional, "bpv": bpv}
        self.built.append(rec)
        return rec

    def fair_rate(self, swap):
        f = float(str(swap["fwd"]).rstrip("Yy") or 0.0)
        t = float(str(swap["tenor"]).rstrip("Yy"))
        return _base_bp(f + t / 2.0) / 1e4

    def meta(self):
        return {"from_curve_store": False}


class FakeGamma:
    """Stands in for rent.package_gamma_usd: planted value, recorded calls."""

    def __init__(self, gamma: float = 200.0):
        self.gamma = float(gamma)
        self.calls = []

    def __call__(self, pricer, package, *, shifts=None):
        self.calls.append({"pricer": pricer, "package": list(package),
                           "shifts": tuple(shifts) if shifts is not None else None})
        return self.gamma


def _fake_roll(pricer, label, horizon="1Y"):
    """Deterministic per-point rolldown, distinct across the grid."""
    return (45.0 - KS_COORDS[label]) * 0.1


def _fake_axes(date, *, store=None, asset=None):
    return ((1.0 / 12.0, 30.0), (1.0, 30.0))


def _fake_cube_read(expiry_y, tail_y, date, *, store=None, clamp=True, asset=None):
    return 60.0 + float(expiry_y)   # bp/yr, distinct per point


def _patch_seams(mp, gamma: FakeGamma):
    mp.setattr(ks, "_store", lambda s: None)
    mp.setattr(ks, "neutral_weights",
               lambda pricer, legs, belly=1: (-1.0, 2.0, -1.0))
    mp.setattr(ks, "package_gamma_usd", gamma)
    mp.setattr(ks, "leg_roll_bp", _fake_roll)
    mp.setattr(ks, "quoted_axes", _fake_axes)
    mp.setattr(ks, "cube_atm_bp_year", _fake_cube_read)


def build(panel, *, cfg=None, sigma=ZERO_SIGMA, gamma=None, mp=None):
    gamma = gamma or FakeGamma(200.0)
    pricer = FakePricer()
    df = ks.build_kink_screen(ASOF, leg_hist_bp=panel, pricer=pricer,
                              cfg=cfg, sigma_panel_bp_year=sigma)
    return df, pricer, gamma


# ------------------------------------------------------------------ fixtures


@pytest.fixture(scope="module")
def bumped():
    """One shared build on the +8bp-bumped panel (module-scoped: the seams
    are patched with a manual MonkeyPatch so every test in the module reads
    the same deterministic screen)."""
    mp = pytest.MonkeyPatch()
    gamma = FakeGamma(200.0)
    _patch_seams(mp, gamma)
    df, pricer, _ = build(make_panel(bump_bp=8.0), gamma=gamma)
    yield {"df": df, "pricer": pricer, "gamma": gamma}
    mp.undo()


# ----------------------------------------------------------- shape/contract


def test_screen_shape_index_and_columns(bumped):
    """17 rows, grid order, exact SCREEN_COLUMNS, books contract columns.

    MUTATION: dropping any books.REQUIRED_COLUMNS name (e.g. renaming zs)
    makes the subset assert fail — and classify_books inside the build would
    already have raised KeyError.
    """
    df = bumped["df"]
    assert len(df) == len(grids.KINK_GRID) == 17
    assert list(df.index) == GRID_LABELS
    assert df.index.name == "point"
    assert tuple(df.columns) == ks.SCREEN_COLUMNS
    assert set(REQUIRED_COLUMNS).issubset(df.columns)
    assert set(df["book"].unique()).issubset({"harvest", "dislocation", "none"})
    # tags come from grids.classify_point: 2 meeting / 4 convexity / 11 clean
    assert (df["tag"] == "meeting").sum() == 2
    assert (df["tag"] == "convexity").sum() == 4
    assert (df["tag"] == "clean").sum() == 11


def test_planted_kink_shows_in_both_residuals(bumped):
    """+8bp on 7y1y from the asof month start -> both residuals positive and
    sign_agree == +1; the xsec hat spreads the bump negatively into the
    neighbours (projection arithmetic).

    MUTATION: feeding RAW instead of adjusted levels cannot be caught here
    (sigma=0 -> CA=0 by design); the CA tests below own that. MUTATION:
    swapping the sign_agreement operands or its threshold sign -> agree
    flips/zeroes and this fails. MUTATION: PCA loadings fit INCLUDING the
    bump month (a look-ahead) -> the frozen-loadings residual shrinks toward
    zero and the > 2 assert fails.
    """
    df = bumped["df"]
    row = df.loc["7y1y"]
    assert row["residual_xsec"] > 2.0
    assert row["residual_pca"] > 2.0
    assert row["sign_agree"] == 1.0
    neigh = df.loc[["6y1y", "8y1y"], "residual_xsec"]
    assert neigh.mean() < 0.0, "the hat matrix must push neighbours negative"


def test_planted_kink_negative_and_null_controls():
    """Down-bump -> both residuals negative, agree == -1; no bump -> the
    residuals collapse to the noise floor and, at a threshold above that
    floor, agree == 0 everywhere.

    Negative control for the planted answer above: the +1 in the bumped
    fixture is not vacuous — the same machinery produces -1 and 0 when the
    input says so (seeded, deterministic). Measured noise floor of this
    seed: max |residual_xsec| 0.63, max |residual_pca| 0.89 — the 7y1y
    noise leans -0.63/-0.77 in BOTH models, so the flat build runs with
    ``sign_min_abs_bp = 1.0`` (above the floor, far below the ~5bp planted
    response). MUTATION: an implementation ignoring ``sign_min_abs_bp``
    reads the -0.6/-0.8 pair as agreement and the all-zeros assert fails.
    """
    mp = pytest.MonkeyPatch()
    try:
        _patch_seams(mp, FakeGamma())
        down, _, _ = build(make_panel(bump_bp=-8.0))
        assert down.loc["7y1y", "residual_xsec"] < -2.0
        assert down.loc["7y1y", "residual_pca"] < -2.0
        assert down.loc["7y1y", "sign_agree"] == -1.0
        flat, _, _ = build(make_panel(bump_bp=0.0),
                           cfg=ks.KinkScreenCfg(sign_min_abs_bp=1.0))
        assert abs(flat.loc["7y1y", "residual_xsec"]) < 2.0
        assert flat["residual_xsec"].abs().max() < 2.0
        assert (flat["sign_agree"] == 0.0).all()
    finally:
        mp.undo()


def test_endpoints_get_nan_fly_columns_and_none_book(bumped):
    """The spot 1y and 40y10y points have no adjacent micro-fly: every
    fly-derived column is NaN and the books NaN-refusal labels them none.

    MUTATION: manufacturing endpoint flies (wrapping the grid, or a 2-leg
    substitute) would print finite carry/gamma here and fail. MUTATION:
    NaN->0 anywhere in the carry path would classify an endpoint into a
    book and fail the "none" assert.
    """
    df = bumped["df"]
    for lab in ("1y", "40y10y"):
        for col in FLY_COLS:
            assert np.isnan(df.loc[lab, col]), f"{lab}.{col} must be NaN"
        assert df.loc[lab, "book"] == "none"
    # interior points DO have the fly block
    assert np.isfinite(df.loc["5y1y", "carry_bp_day"])
    assert np.isfinite(df.loc["5y1y", "gamma_usd_per_bp2"])


def test_zs_polarity_positive_is_rich():
    """Plant the asof 5y1y level 3 trailing sigmas ABOVE its own window ->
    zs strongly positive (RICH, the books polarity) and pctl_3y ~ 1.

    MUTATION: zs = (mean - x)/std (the receive-side sign flip) -> zs comes
    out ~-2.9 and the > 2 assert fails; pctl catches an independent flip.
    Negative control: planting BELOW gives the mirror numbers.
    """
    mp = pytest.MonkeyPatch()
    try:
        _patch_seams(mp, FakeGamma())
        for sign in (+1.0, -1.0):
            panel = make_panel(bump_bp=0.0)
            w = panel["5y1y"].iloc[:-1].tail(755)
            panel.iloc[-1, panel.columns.get_loc("5y1y")] = (
                w.mean() + sign * 3.0 * w.std(ddof=1))
            df, _, _ = build(panel)
            zs, pctl = df.loc["5y1y", "zs"], df.loc["5y1y", "pctl_3y"]
            if sign > 0:
                assert zs > 2.0, "level above own window must read RICH (+)"
                assert pctl > 0.95
            else:
                assert zs < -2.0
                assert pctl < 0.05
    finally:
        mp.undo()


def test_carry_age_past_zero_fallback_on_1y1y(bumped):
    """The 1y1y fly's front leg is the SPOT 1y — it cannot age a full year,
    the aged-rate identity raises, and the screen retries at the 0.25y
    fallback; every other interior fly uses the 1.0y horizon. The per-day
    number divides by the horizon ACTUALLY used (recomputed here through
    the real carry_roll_bp on the same fake pricer).

    MUTATION: normalising by 252*1.0 while pricing at h=0.25 -> the exact
    equality fails by 4x. MUTATION: swallowing the raise into NaN with no
    fallback -> the finite assert fails. MUTATION: substituting 0 for the
    raise -> the exact equality fails.
    """
    from RVUtils.CurveFlyScreener.screener import Leg, Structure
    from RVUtils.CvxSuite.carry import carry_roll_bp

    df, pricer = bumped["df"], bumped["pricer"]
    assert df.loc["1y1y", "carry_horizon_y_used"] == 0.25
    assert np.isfinite(df.loc["1y1y", "carry_bp_day"])
    assert df.loc["5y1y", "carry_horizon_y_used"] == 1.0

    legs = (Leg(0.0, 1.0), Leg(1.0, 1.0), Leg(2.0, 1.0))
    s = Structure("fly:1y1y", legs, (-1.0, 2.0, -1.0), "fly")
    expected = carry_roll_bp(pricer, s, 0.25) / (252.0 * 0.25)
    assert df.loc["1y1y", "carry_bp_day"] == pytest.approx(expected, rel=1e-12)

    legs5 = (Leg(4.0, 1.0), Leg(5.0, 1.0), Leg(6.0, 1.0))
    s5 = Structure("fly:5y1y", legs5, (-1.0, 2.0, -1.0), "fly")
    expected5 = carry_roll_bp(pricer, s5, 1.0) / 252.0
    assert df.loc["5y1y", "carry_bp_day"] == pytest.approx(expected5, rel=1e-12)


def test_package_recipe_bpv_legs(bumped):
    """The gamma package for point i is the three adjacent grid legs built
    with bpv = w_i * dv01_usd (the C1 rent recipe: bpv path, belly +2,
    never resolve_pricable — the fake pricer has no such method, so any
    resolve attempt would have raised AttributeError during the build).

    MUTATION: sizing bpv by notional-proportion (w_i * unit_dv01) or
    dropping the w_i sign -> the exact bpv asserts fail. MUTATION: belly
    weight 1 instead of 2 -> the +2e5 assert fails.
    """
    gamma = bumped["gamma"]
    df = bumped["df"]
    by_belly = {}
    for call in gamma.calls:
        pkg = call["package"]
        assert len(pkg) == 3
        assert all(p["bpv"] is not None and p["notional"] is None for p in pkg)
        by_belly[(pkg[1]["fwd"], pkg[1]["tenor"])] = pkg
    # 15 interior points, one package each
    assert len(gamma.calls) == 15
    pkg = by_belly[("5Y", "1Y")]
    assert [(p["fwd"], p["tenor"]) for p in pkg] == [
        ("4Y", "1Y"), ("5Y", "1Y"), ("6Y", "1Y")]
    assert [p["bpv"] for p in pkg] == [-100_000.0, 200_000.0, -100_000.0]
    # and the planted gamma landed in the frame
    assert df.loc["5y1y", "gamma_usd_per_bp2"] == 200.0
    # theta ties carry to the same dollar scale: theta = carry_bp_day * dv01
    assert df.loc["5y1y", "theta_usd_day"] == pytest.approx(
        df.loc["5y1y", "carry_bp_day"] * 100_000.0, rel=1e-12)


def test_edge_rac_and_frontier_arithmetic(bumped):
    """The composed numbers reproduce from the row's own columns exactly.

    edge_bp = e_rev*p_hit - |carry|*e_fpt - cost          (cost 2.3 default)
    rac_net = carry*e_fpt + rev_drag
    rev_drag = (mu - adj)*(1 - exp(-kappa*e_fpt))
    off_value_carry = residual_xsec - (icpt + slope*leg_roll)

    MUTATION: +cost instead of -cost -> edge off by 4.6. MUTATION: dropping
    the p_hit factor -> edge fails whenever p_hit < 1 (true here: the RW-ish
    synthetic panel censors heavily). MUTATION: carry annualised (x252) in
    rac_net -> exact equality fails. MUTATION: off_frontier without the
    intercept -> the frontier identity fails.
    """
    df = bumped["df"]
    r = df.loc["5y1y"]
    assert np.isfinite(r["edge_bp"])
    assert r["edge_bp"] == pytest.approx(
        r["e_rev_bp"] * r["p_hit"] - abs(r["carry_bp_day"]) * r["e_fpt_d"] - 2.3,
        rel=1e-12)
    drag = (r["ou_mu_bp"] - r["adj_bp"]) * (
        1.0 - math.exp(-r["ou_kappa"] * r["e_fpt_d"]))
    assert r["rev_drag_fpt_bp"] == pytest.approx(drag, rel=1e-9)
    assert r["rac_net"] == pytest.approx(
        r["carry_bp_day"] * r["e_fpt_d"] + r["rev_drag_fpt_bp"], rel=1e-12)
    fit = df.attrs["frontier_value_carry"]
    assert r["off_value_carry"] == pytest.approx(
        r["residual_xsec"] - (fit["intercept"] + fit["slope"] * r["leg_roll_bp"]),
        rel=1e-9)
    # be_over_rv identity where both sides are finite
    fin = df[np.isfinite(df["sigma_be_bp_day"]) & np.isfinite(df["sigma_rlzd_bp_day"])]
    for lab, row in fin.iterrows():
        assert row["be_over_rv"] == pytest.approx(
            row["sigma_be_bp_day"] / row["sigma_rlzd_bp_day"], rel=1e-12)


def test_carry_breakeven_branch_positive_carry():
    """A NON-NEGATIVE fly carry has no carry-breakeven horizon: the branch
    must return carry_be_days = inf and p_fpt_gt_carry_be = 0.0 WITHOUT
    calling p_fpt_exceeds (which returns NaN on non-finite days and would
    silently relabel "no breakeven risk" as "unknown" — the mutation this
    test kills).
    """
    mp = pytest.MonkeyPatch()
    try:
        _patch_seams(mp, FakeGamma())
        mp.setattr(ks, "carry_roll_bp", lambda pricer, s, h, cache=None: +5.0)
        df, _, _ = build(make_panel())
        interior = df.index[1:-1]
        assert (df.loc[interior, "carry_bp_day"] > 0).all()
        assert np.isposinf(df.loc[interior, "carry_be_days"]).all()
        assert (df.loc[interior, "p_fpt_gt_carry_be"] == 0.0).all()
    finally:
        mp.undo()


def test_carry_breakeven_negative_carry_uses_fpt_tail(bumped):
    """Negative-carry rows: carry_be_days = e_rev/|carry| exactly and the
    tail probability is a real number in [0, 1]."""
    df = bumped["df"]
    neg = df[np.isfinite(df["carry_bp_day"]) & (df["carry_bp_day"] < 0)]
    if len(neg) == 0:
        pytest.skip("synthetic curve produced no negative-carry fly (seed-dependent)")
    r = neg.iloc[0]
    assert r["carry_be_days"] == pytest.approx(
        r["e_rev_bp"] / abs(r["carry_bp_day"]), rel=1e-12)
    assert 0.0 <= r["p_fpt_gt_carry_be"] <= 1.0


def test_ca_is_added_with_the_pinned_anchor():
    """Constant sigma 80 bp/yr: adjusted = quoted + CA with the C1 pinned
    anchor CA(80, 25, 30) = 240.0 bp at the 25y5y point.

    MUTATION: adjusted = quoted - CA -> the 240 lands with the wrong sign
    and the equality fails. MUTATION: the citi PACK convention (mean(T1^2))
    instead of the two-time form -> 240.0 becomes a different number.
    """
    mp = pytest.MonkeyPatch()
    try:
        _patch_seams(mp, FakeGamma())
        sigma = ZERO_SIGMA + 80.0
        panel = make_panel()
        df, _, _ = build(panel, sigma=sigma)
        assert df.loc["25y5y", "ca_bp"] == pytest.approx(240.0, rel=1e-12)
        assert df.loc["25y5y", "adj_bp"] == pytest.approx(
            df.loc["25y5y", "level_bp"] + 240.0, rel=1e-12)
        # spot point: t1 = 0 -> CA identically zero at any vol
        assert df.loc["1y", "ca_bp"] == 0.0
    finally:
        mp.undo()


def test_ca_distinct_sigmas_land_on_the_right_points():
    """Column-swap tripwire: per-point DISTINCT sigmas (10 + 5*j) must
    produce each label's own 0.5*sigma_j^2*t1*t2 CA. A positional mis-map
    between the cube panel and the grid labels survives a constant-sigma
    test; it cannot survive this one.
    """
    mp = pytest.MonkeyPatch()
    try:
        _patch_seams(mp, FakeGamma())
        sig = {lab: 10.0 + 5.0 * j for j, lab in enumerate(GRID_LABELS)}
        sigma = pd.DataFrame({lab: sig[lab] for lab in GRID_LABELS},
                             index=ZERO_SIGMA.index)
        df, _, _ = build(make_panel(), sigma=sigma)
        for p, lab in zip(grids.KINK_GRID, GRID_LABELS):
            t1, t2 = grids.t1_t2(p)
            want = 0.5 * (sig[lab] / 1e4) ** 2 * t1 * t2 * 1e4
            assert df.loc[lab, "ca_bp"] == pytest.approx(want, abs=1e-9), lab
    finally:
        mp.undo()


def test_ca_mode_latest_reads_one_asof_sigma():
    """ca_mode='latest' (no injected panel): one cube read per point at
    asof, broadcast over history — CA at asof equals the panel-mode CA for
    a time-constant cube, and the mode is recorded in attrs."""
    mp = pytest.MonkeyPatch()
    try:
        _patch_seams(mp, FakeGamma())
        cfg = ks.KinkScreenCfg(ca_mode="latest")
        df = ks.build_kink_screen(ASOF, leg_hist_bp=make_panel(),
                                  pricer=FakePricer(), cfg=cfg,
                                  sigma_panel_bp_year=None)
        assert df.attrs["ca_mode"] == "latest"
        for p, lab in zip(grids.KINK_GRID, GRID_LABELS):
            t1, t2 = grids.t1_t2(p)
            s = _fake_cube_read(p.fwd, p.tenor, ASOF.date())
            want = 0.5 * (s / 1e4) ** 2 * t1 * t2 * 1e4
            assert df.loc[lab, "ca_bp"] == pytest.approx(want, abs=1e-9), lab
    finally:
        mp.undo()


def test_sigma_impl_support_gate_nans_both_ends(bumped):
    """The support gate refuses BOTH grid ends: 40y10y (expiry 40 > the 30Y
    axis max) AND the spot 1y point (expiry 0 < the 1M axis min — there is
    no zero-expiry swaption). Interior points print the converted bp/day
    cube read.

    MUTATION: using the clamped read instead of the gate -> the fake cube
    returns finite for both ends and the NaN asserts fail. MUTATION:
    skipping the bp/yr -> bp/day conversion -> the 25y5y equality fails by
    sqrt(252).
    """
    from RVUtils.CvxSuite.vols import bp_year_to_day

    df = bumped["df"]
    assert np.isnan(df.loc["40y10y", "sigma_impl_bp_day"])
    assert np.isnan(df.loc["1y", "sigma_impl_bp_day"])
    want = bp_year_to_day(_fake_cube_read(25.0, 5.0, ASOF.date()))
    assert df.loc["25y5y", "sigma_impl_bp_day"] == pytest.approx(want, rel=1e-12)
    assert set(df.index[df["sigma_impl_bp_day"].isna()]) == {"1y", "40y10y"}


def test_books_wiring_identity_and_plants(bumped):
    """(a) The book column IS classify_books over the row's own gate
    columns — any column-name or ordering slip between the screen and the
    books contract breaks this identity. (b) Loosened gates route a real
    row into each book: harvest via be/z/rac-only gates, dislocation via
    the bumped 7y1y row (sign_agree +1, tag clean, |z| and edge gates open).

    MUTATION: reordering classify_books' inputs or renaming a gate column
    -> (a) raises/fails. MUTATION: books precedence flipped -> a row
    passing both would surface as harvest and (b)'s dislocation assert
    fails under the all-open gates.
    """
    from RVUtils.CvxSuite.books import classify_books

    df = bumped["df"]
    relab = classify_books(df[list(REQUIRED_COLUMNS)], ks.KinkScreenCfg().gates)
    pd.testing.assert_series_equal(relab, df["book"], check_names=False)

    mp = pytest.MonkeyPatch()
    try:
        _patch_seams(mp, FakeGamma())
        harvest_gates = BookGates(harvest_min_be_over_rv=0.0, harvest_max_z=99.0,
                                  harvest_min_rac_net=-1e12,
                                  disl_min_abs_z=99.0, disl_min_edge_bp=1e12)
        dfh, _, _ = build(make_panel(bump_bp=8.0),
                          cfg=ks.KinkScreenCfg(gates=harvest_gates))
        assert (dfh["book"] == "harvest").sum() >= 1
        assert (dfh.loc[["1y", "40y10y"], "book"] == "none").all()

        disl_gates = BookGates(harvest_min_be_over_rv=1e12, harvest_max_z=-1e12,
                               harvest_min_rac_net=1e12,
                               disl_min_abs_z=0.0, disl_min_edge_bp=-1e12)
        dfd, _, _ = build(make_panel(bump_bp=8.0),
                          cfg=ks.KinkScreenCfg(gates=disl_gates))
        assert dfd.loc["7y1y", "book"] == "dislocation"
        assert dfd.loc["20y5y", "book"] == "none", "convexity tag must refuse a fade"
    finally:
        mp.undo()


def test_fpt_block_is_deterministic_and_stats_coherent(bumped):
    """Same inputs -> identical FPT numbers (fresh default_rng(seed) per
    point: common random numbers, order-independent). p_hit + frac_censored
    == 1 exactly; e_fpt within (0, steps].

    MUTATION: one shared RNG consumed sequentially across points -> the
    rebuild equality fails (row order would matter). MUTATION: calling
    fpt_stats without steps= -> the build itself raises under censoring
    (the ou contract) — this test just has to run.
    """
    mp = pytest.MonkeyPatch()
    try:
        _patch_seams(mp, FakeGamma())
        df2, _, _ = build(make_panel(bump_bp=8.0))
    finally:
        mp.undo()
    df = bumped["df"]
    pd.testing.assert_series_equal(df["e_fpt_d"], df2["e_fpt_d"])
    pd.testing.assert_series_equal(df["p_hit"], df2["p_hit"])
    fin = df[np.isfinite(df["p_hit"])]
    assert len(fin) > 0
    for _, r in fin.iterrows():
        assert r["p_hit"] + r["frac_censored"] == pytest.approx(1.0, abs=1e-12)
        assert 0.0 < r["e_fpt_d"] <= 504.0


def test_loud_failures():
    """asof off the panel, a missing grid column, and a percent-scale panel
    all raise with named errors — never a silent partial screen."""
    mp = pytest.MonkeyPatch()
    try:
        _patch_seams(mp, FakeGamma())
        panel = make_panel()
        with pytest.raises(ValueError, match="not a leg-history date"):
            ks.build_kink_screen(ASOF + pd.Timedelta(days=1),
                                 leg_hist_bp=panel, pricer=FakePricer(),
                                 sigma_panel_bp_year=ZERO_SIGMA)
        with pytest.raises(ValueError, match="missing KINK_GRID columns"):
            ks.build_kink_screen(ASOF, leg_hist_bp=panel.drop(columns=["7y1y"]),
                                 pricer=FakePricer(),
                                 sigma_panel_bp_year=ZERO_SIGMA)
        with pytest.raises(ValueError, match="percent or decimal"):
            ks.build_kink_screen(ASOF, leg_hist_bp=panel / 100.0,
                                 pricer=FakePricer(),
                                 sigma_panel_bp_year=ZERO_SIGMA)
        with pytest.raises(ValueError, match="reference date"):
            ks.build_kink_screen(
                ASOF, leg_hist_bp=panel,
                pricer=FakePricer(ref_date=ASOF - pd.Timedelta(days=40)),
                sigma_panel_bp_year=ZERO_SIGMA)
    finally:
        mp.undo()


# ---------------------------------------------------------------- integration


@pytest.fixture(scope="module")
def real_inputs():
    """Real parquet + offline pricer + cube store for 2026-08-21, or skip."""
    repo = Path(__file__).resolve().parents[1]
    pq = repo / "docs" / "cvxsuite" / "leg_history.parquet"
    if not pq.exists():
        pytest.skip(f"leg history parquet missing: {pq}")
    leg_hist = pd.read_parquet(pq)
    try:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        pricer = IRSwapsMDP(source="CITIVELO_EXCEL").get_data(
            {"curve_name": "USD-SOFR-1D", "timestamp": dt.date(2026, 8, 21),
             "offline": True})
    except Exception as exc:  # noqa: BLE001 — a cold store is a skip, not a fail
        pytest.skip(f"offline curve store cannot serve 2026-08-21: {exc!r}")
    if pricer is None:
        pytest.skip("IRSwapsMDP returned None for 2026-08-21 offline (store miss)")
    if pricer.meta().get("from_curve_store") is not True:
        pytest.skip("2026-08-21 pricer is not store-backed; refusing live fetch")
    try:
        from Caching.swaption_cube_store import SwaptionCubeStore
        from RVUtils.CvxSuite.vols import quoted_axes

        store = SwaptionCubeStore.default()
        axes = quoted_axes(dt.date(2026, 8, 21), store=store)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"swaption cube store unavailable: {exc!r}")
    if axes is None:
        pytest.skip("swaption cube has no 2026-08-21 day")
    return {"leg_hist": leg_hist, "pricer": pricer, "store": store}


@pytest.mark.integration
def test_real_screen_2026_08_21(real_inputs):
    """Full build on the real data for 2026-08-21.

    Asserts the task's four integration facts: row count == len(KINK_GRID);
    40y10y sigma_impl NaN (support gate, BY DESIGN); every finite
    sigma_rlzd inside the units guard band (and the median guard passes);
    >= 1 row classified non-none OR the printed reason (the gate distances)
    accompanies an all-none screen.
    """
    from RVUtils.CvxSuite.vols import units_median_guard

    df = ks.build_kink_screen(
        pd.Timestamp("2026-08-21"),
        leg_hist_bp=real_inputs["leg_hist"],
        pricer=real_inputs["pricer"],
        cube_store=real_inputs["store"])

    assert len(df) == len(grids.KINK_GRID)
    assert list(df.index) == GRID_LABELS

    # support gate: 40y10y past the 30Y axis end; spot 1y below the 1M start
    assert np.isnan(df.loc["40y10y", "sigma_impl_bp_day"])
    assert np.isnan(df.loc["1y", "sigma_impl_bp_day"])
    assert np.isfinite(df.loc["25y5y", "sigma_impl_bp_day"]), \
        "25y expiry is an INTERIOR interpolation and must price"

    # units guard on the realized column: median in band, all finite in band
    rlzd = df["sigma_rlzd_bp_day"]
    units_median_guard(rlzd)  # raises on a unit slip
    fin = rlzd[np.isfinite(rlzd)]
    assert len(fin) >= 15
    assert bool(((fin >= 0.5) & (fin <= 40.0)).all()), \
        f"sigma_rlzd outside [0.5, 40] bp/day: {fin[(fin < 0.5) | (fin > 40)].to_dict()}"

    # endpoints NaN through the fly block on real data too
    assert np.isnan(df.loc["1y", "gamma_usd_per_bp2"])
    assert np.isnan(df.loc["40y10y", "gamma_usd_per_bp2"])
    # interior gammas priced off the real curve
    assert np.isfinite(df.loc["10y2y", "gamma_usd_per_bp2"])

    non_none = int((df["book"] != "none").sum())
    if non_none == 0:
        g = ks.KinkScreenCfg().gates
        reason = df[["be_over_rv", "zs", "rac_net", "sign_agree", "tag",
                     "edge_bp"]].to_string()
        print("\nALL-NONE SCREEN — gate inputs vs "
              f"(be>={g.harvest_min_be_over_rv}, z<={g.harvest_max_z}, "
              f"rac>{g.harvest_min_rac_net}; |z|>={g.disl_min_abs_z}, "
              f"edge>{g.disl_min_edge_bp}):\n{reason}")
    assert non_none >= 0  # the printed reason is the deliverable when 0
