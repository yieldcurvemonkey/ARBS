"""Tests for RVUtils.CvxSuite.panels — the historical signal panels feeding
the two W3 QDB strategies.

Pure-logic tests run on SYNTHETIC leg histories (no market data, no curve
store).  The glue tests import the two BT strategy modules and run their real
``episodes_from_panel`` extractors on panels built here — proving the panel
contract (index names, gate/sizing columns, label forms) fits the consumers
byte-for-byte, mechanics only (the economic direction seam is documented in
``panels`` and owned by the strategy layer).  INTEGRATION tests run on the
real ``docs/cvxsuite/leg_history.parquet`` and self-skip when it is absent.

MUTATION notes (load-bearing asserts, each verified kill-able):
* ``test_parallel_shift_zs_small`` — reimplementing ``zs`` on the OUTRIGHT
  point level (instead of the fly level) is caught: the planted common trend
  drives outright z > 3 while the fly z stays < 1.5.
* ``test_single_point_kink_fires`` — a zs POLARITY flip (zs = z(-L) or
  L = wings - belly) is caught: the planted HIGH belly must print zs > +2,
  not < -2.
* ``test_carry_strip_identity`` — the carry composition sign (level-long =
  MINUS the composed roll-down) and the strip-interpolation direction are
  pinned to a hand-computed +15/252 bp/day; a dropped minus or a k+1
  interpolation gives a different number.
* ``test_lowercase_leg_panel_refused`` — removing the ``_screen_block``
  leg/pair asserts lets ``screen_panel_from_legs`` skip missing legs
  SILENTLY (``except KeyError: continue``) and the build would report
  success with every harvest gate refusing forever.
* ``test_rac_net_identity`` — the rac_net arithmetic and the
  steepener-orientation of the carry (``carry_lvl = -carry_flat``) are
  asserted from the frame's own columns.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime as dt
import pathlib

import numpy as np
import pandas as pd
import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from RVUtils.CvxSuite import grids  # noqa: E402
from RVUtils.CvxSuite import panels as P  # noqa: E402

LEG_HISTORY = _REPO / "docs" / "cvxsuite" / "leg_history.parquet"

GRID_LABELS = [grids.leg_label(p) for p in grids.KINK_GRID]
GRID_KS = np.asarray([grids.k_coord(p) for p in grids.KINK_GRID])
INTERIOR = GRID_LABELS[1:-1]

#: The strategy contracts, restated here so a drift in EITHER place fails
#: loudly (the glue tests check against the imported BT modules themselves).
HARVEST_GATE_COLS = ("be_over_rv", "zs", "rac_net")
DISL_REQUIRED_COLS = ("zs", "sign_agree", "tag", "edge_bp",
                      "leg_front", "leg_belly", "leg_back",
                      "w_front", "w_belly", "w_back")


# ---------------------------------------------------------------------------
# synthetic builders
# ---------------------------------------------------------------------------

def _ar1(rng, n, phi=0.9, sigma=0.8, cols=1):
    """AR(1) noise (n, cols) — persistent so rolling AR(1) fits mean-revert."""
    eps = np.zeros((n, cols))
    innov = rng.normal(0.0, sigma, (n, cols))
    for t in range(1, n):
        eps[t] = phi * eps[t - 1] + innov[t]
    return eps


def make_hist(n=900, seed=7, *, trend_last=0, trend_bp=0.0,
              extra=("10y10y", "15y10y", "20y10y")) -> pd.DataFrame:
    """Grid labels (+ harvest legs) in bp: smooth base + common RW + AR noise.

    ``trend_last``/``trend_bp``: add a common LINEAR ramp of ``trend_bp`` over
    the final ``trend_last`` rows — the parallel move a fly must not see.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-06", periods=n)
    base = 250.0 + 8.0 * np.sqrt(GRID_KS)
    shift = np.cumsum(rng.normal(0.0, 1.0, n))
    if trend_last:
        ramp = np.zeros(n)
        ramp[-int(trend_last):] = np.linspace(0.0, float(trend_bp), int(trend_last))
        shift = shift + ramp
    eps = _ar1(rng, n, cols=len(GRID_KS))
    hist = pd.DataFrame(base[None, :] + shift[:, None] + eps,
                        index=idx, columns=GRID_LABELS)
    for j, lab in enumerate(extra):
        if lab not in hist.columns:
            hist[lab] = 320.0 + 10.0 * j + shift + _ar1(rng, n)[:, 0]
    return hist


def make_leg_panel(dates, *, roll_long=2e-3, seed=3) -> pd.DataFrame:
    """Synthetic strat3-form leg panel for the three harvest pairs.

    Constant dv01 1e-3 and roll_1y 0 (front) / ``roll_long`` (backs) make the
    flattener carry EXACTLY ``-roll_long/1e-3`` bp for every pair; long-leg
    rates get a random walk so the trailing 252d realized vol (min 120 obs)
    is defined and ``be_over_rv`` populates.
    """
    rng = np.random.default_rng(seed)
    legs = ("10Yx10Y", "15Yx10Y", "20Yx10Y", "15Yx5Y")
    rows = []
    walks = {l: 400.0 + np.cumsum(rng.normal(0.0, 3.0, len(dates))) for l in legs}
    for i, d in enumerate(dates):
        for l in legs:
            is_front = l in ("10Yx10Y", "15Yx5Y")
            rows.append({
                "date": pd.Timestamp(d), "leg": l,
                "rate_bp": float(walks[l][i]),
                "dv01": 1e-3,
                "gamma": -2e-6 if is_front else -4e-6,
                "roll_1y": 0.0 if is_front else float(roll_long),
                "roll_1d": 0.0,
            })
    return (pd.DataFrame(rows).set_index(["date", "leg"]).sort_index())


# ---------------------------------------------------------------------------
# labels / cfg
# ---------------------------------------------------------------------------

def test_label_canonicalisation():
    assert P.leg_to_strat3("10y10y") == "10Yx10Y"
    assert P.leg_to_strat3("10Yx10Y") == "10Yx10Y"
    assert P.leg_to_lc("15Yx5Y") == "15y5y"
    assert P.parse_pair("10y10y/15y10y") == ("10y10y", "15y10y")
    with pytest.raises(ValueError):
        P.leg_to_strat3("10y")          # spot leg: the 0Y/0D trap refuses
    with pytest.raises(ValueError):
        P.parse_pair("10y10y")          # not a pair
    with pytest.raises(ValueError):
        P.parse_pair("10q10q/15y10y")   # unparseable leg


def test_cfg_defaults_are_section6():
    cfg = P.CvxPanelCfg()
    assert (cfg.z_window, cfg.ou_window) == (756, 756)
    assert (cfg.n_pcs, cfg.pca_window, cfg.pca_min_window, cfg.pca_refit) == \
        (2, 756, 504, "M")
    assert cfg.fpt_steps == 504
    assert cfg.cost_rt_bp == 2.3
    with pytest.raises(ValueError):
        P.CvxPanelCfg(z_min_obs=800)


# ---------------------------------------------------------------------------
# dislocation panel — pure logic
# ---------------------------------------------------------------------------

def test_dislocation_shape_names_and_contract_columns(tmp_path):
    hist = make_hist(n=560)
    d = P.build_dislocation_panel(hist)
    assert list(d.index.names) == ["date", "point"]
    assert set(d.index.get_level_values("point")) == set(INTERIOR)
    assert len(d) == 560 * len(INTERIOR)
    for c in DISL_REQUIRED_COLS:
        assert c in d.columns, c
    # parquet round trip preserves the exact index names (the script's write path)
    f = tmp_path / "d.parquet"
    d.to_parquet(f)
    back = pd.read_parquet(f)
    assert list(back.index.names) == ["date", "point"]


def test_dislocation_w_orientation_and_adjacent_legs():
    d = P.build_dislocation_panel(make_hist(n=400))
    assert (d["w_belly"] > 0).all() and (d["w_front"] < 0).all() and (d["w_back"] < 0).all()
    assert (d["w_front"] == -0.5).all() and (d["w_belly"] == 1.0).all()
    one = d.xs(d.index.get_level_values("date")[-1], level="date")
    for i, lab in enumerate(GRID_LABELS):
        if lab in one.index:
            assert one.at[lab, "leg_front"] == GRID_LABELS[i - 1]
            assert one.at[lab, "leg_back"] == GRID_LABELS[i + 1]
            assert one.at[lab, "leg_belly"] == lab
    tags = one["tag"]
    assert tags.value_counts().to_dict() == {"clean": 11, "convexity": 3, "meeting": 1}


def test_parallel_shift_zs_small():
    """A common (parallel) trend must not reach the fly z.

    MUTATION: computing zs on the OUTRIGHT point level — the planted +200bp
    ramp over the last 150 days drives every outright z far above 3, so the
    trended and untrended builds would print DIFFERENT zs; the fly weights
    sum to zero, so the true fly zs cancels the ramp EXACTLY.
    """
    hist_flat = make_hist(n=900, seed=7)
    hist_trend = make_hist(n=900, seed=7, trend_last=150, trend_bp=200.0)
    d_flat = P.build_dislocation_panel(hist_flat)
    d_trend = P.build_dislocation_panel(hist_trend)
    outright_z = ((hist_trend - hist_trend.rolling(756, min_periods=252).mean())
                  / hist_trend.rolling(756, min_periods=252).std(ddof=1)).iloc[-1]
    assert float(outright_z[GRID_LABELS].min()) > 3.0, "trend was not planted hard enough"
    assert np.allclose(d_trend["fly_bp"].to_numpy(),
                       d_flat["fly_bp"].to_numpy(), equal_nan=True, atol=1e-9)
    z_t, z_f = d_trend["zs"].to_numpy(), d_flat["zs"].to_numpy()
    assert np.allclose(z_t, z_f, equal_nan=True, atol=1e-9), (
        "fly zs saw the parallel shift: max diff "
        f"{np.nanmax(np.abs(z_t - z_f)):.3f} z-units")


def test_single_point_kink_fires():
    """+8bp on one belly must fire THAT point, with the binding polarity.

    MUTATION: a zs polarity flip (z of -L, or L = wings - belly) prints
    zs < -2 here and is caught by the SIGNED assert.
    """
    hist = make_hist(n=900)
    hist.iloc[-1, hist.columns.get_loc("5y1y")] += 8.0
    d = P.build_dislocation_panel(hist)
    last_day = d.index.get_level_values("date").max()
    row = d.loc[(last_day, "5y1y")]
    others = d.xs(last_day, level="date").drop("5y1y")
    assert row["zs"] > 2.0, f"kinked point did not fire: zs={row['zs']:.2f}"
    assert row["res_x"] > 0.5, "xsec residual must be cheap-positive at a high belly"
    assert row["sign_agree"] == 1.0, "both models cheap => sign_agree +1"
    assert row["tag"] == "clean"
    assert float(others["zs"].abs().max()) < row["zs"]
    assert row["e_rev_bp"] > 0
    # neighbours' flies see the bump with the OPPOSITE sign (wing weight -0.5)
    assert d.loc[(last_day, "4y1y"), "zs"] < 0
    assert d.loc[(last_day, "6y1y"), "zs"] < 0


def test_carry_strip_identity():
    """Hand-computed ING strip carry on a flat curve with one high wing.

    Flat 300bp everywhere except ``4y1y`` (k=4.5) at 310. Leg 1y roll-downs
    ``f(k) - interp(k-1)``: 3y1y: 0;  4y1y: 310 - interp(3.5) = +10;
    5y1y: 300 - interp(4.5) = -10;  6y1y: 300 - interp(5.5) = 0.
    Level-long fly carry at 5y1y (wings 4y1y/6y1y) =
    -[(-10) - 0.5*(10 + 0)]/252 = +15/252 bp/day (the belly ages INTO the
    high wing: the belly payer gains — sign convention pinned); at 4y1y
    (wings 3y1y/5y1y) = -[10 - 0.5*(0 - 10)]/252 = -15/252.
    MUTATION: dropping the minus or interpolating at k+1 both fail.
    """
    n = 300
    idx = pd.bdate_range("2023-01-02", periods=n)
    hist = pd.DataFrame(300.0, index=idx, columns=GRID_LABELS)
    hist["4y1y"] = 310.0
    d = P.build_dislocation_panel(hist)
    last_day = idx[-1]
    got = d.loc[(last_day, "5y1y"), "carry_bp_day"]
    assert got == pytest.approx(15.0 / 252.0, rel=1e-12)
    assert d.loc[(last_day, "4y1y"), "carry_bp_day"] == pytest.approx(
        -15.0 / 252.0, rel=1e-12)
    # spot-1y wing has no k-1 on the strip -> the 1y1y fly's carry is NaN
    assert np.isnan(d.loc[(last_day, "1y1y"), "carry_bp_day"])
    # fully flat points earn exactly zero
    assert d.loc[(last_day, "9y1y"), "carry_bp_day"] == 0.0


def test_dislocation_efpt_and_edge_wiring():
    """e_fpt/p_hit/e_rev/edge propagate together; e_rev is half the OU gap."""
    hist = make_hist(n=900, seed=11)
    d = P.build_dislocation_panel(hist)
    ok = d[["e_fpt_d", "p_hit_proxy", "e_rev_bp", "carry_bp_day"]].notna().all(axis=1)
    assert ok.sum() > 1000, "expected a populated FPT block on persistent noise"
    sub = d[ok]
    assert (sub["e_fpt_d"] > 0).all()
    assert ((sub["p_hit_proxy"] > 0) & (sub["p_hit_proxy"] <= 1)).all()
    lhs = sub["e_rev_bp"]
    rhs = 0.5 * (sub["fly_bp"] - sub["ou_mu_bp"]).abs()
    assert np.allclose(lhs, rhs, rtol=1e-12)
    edge = (sub["e_rev_bp"] * sub["p_hit_proxy"]
            - sub["carry_bp_day"].abs() * sub["e_fpt_d"]
            - P.CvxPanelCfg().cost_rt_bp)
    assert np.allclose(sub["edge_bp"], edge, rtol=1e-12)


def test_dislocation_ca_seam_one_level_definition():
    """Injected ca_bp shifts residuals AND the fly level together."""
    hist = make_hist(n=560, seed=5)
    ca = pd.Series(0.0, index=GRID_LABELS)
    ca["5y1y"] = 4.0                      # depress one quoted point by 4bp
    d_raw = P.build_dislocation_panel(hist)
    d_adj = P.build_dislocation_panel(hist, ca_bp=ca)
    last_day = d_raw.index.get_level_values("date").max()
    dl = (d_adj.loc[(last_day, "5y1y"), "fly_bp"]
          - d_raw.loc[(last_day, "5y1y"), "fly_bp"])
    assert dl == pytest.approx(4.0, abs=1e-9)   # belly weight +1
    assert d_adj.attrs["levels"] == "adjusted" and d_raw.attrs["levels"] == "raw"


def test_hist_guards():
    hist = make_hist(n=400)
    with pytest.raises(ValueError):        # percent-scale panel refused
        P.build_dislocation_panel(hist / 100.0)
    with pytest.raises(ValueError):        # missing grid column named
        P.build_dislocation_panel(hist.drop(columns=["7y1y"]))
    with pytest.raises(TypeError):         # non-datetime index
        P.build_dislocation_panel(hist.reset_index(drop=True))


# ---------------------------------------------------------------------------
# harvest panel — pure logic
# ---------------------------------------------------------------------------

def test_harvest_level_orientation_and_names(tmp_path):
    hist = make_hist(n=560)
    h = P.build_harvest_panel(hist, pairs=P.HARVEST_PAIRS)
    assert list(h.index.names) == ["date", "pair"]
    assert set(h.index.get_level_values("pair")) == set(P.HARVEST_PAIRS)
    for c in HARVEST_GATE_COLS:
        assert c in h.columns, c
    # level = back - front, exactly, from the leg history
    lvl = h.xs("10y10y/15y10y", level="pair")["level_bp"]
    expect = hist["15y10y"] - hist["10y10y"]
    assert np.allclose(lvl.to_numpy(), expect.to_numpy(), rtol=1e-12)
    f = tmp_path / "h.parquet"
    h.to_parquet(f)
    assert list(pd.read_parquet(f).index.names) == ["date", "pair"]


def test_harvest_degraded_mode_all_nan_carry():
    """No leg panel, no curve map: zs/level live, carry/be/rac all-NaN."""
    h = P.build_harvest_panel(make_hist(n=560), pairs=P.HARVEST_PAIRS)
    assert h["level_bp"].notna().all()
    assert h["zs"].notna().sum() > 0
    for c in ("carry_flat_1y_bp", "carry_lvl_1y_bp", "be_over_rv", "rac_net"):
        assert h[c].isna().all(), c


def test_rac_net_identity():
    """rac_net arithmetic + steepener orientation, from the frame's own columns.

    MUTATION: dropping the carry sign flip (carry_lvl = -carry_flat) or the
    0.5 drag factor breaks the recomputation; the orientation assert pins
    carry_lvl > 0 when the BACK leg out-rolls the front (steepener earns).
    """
    hist = make_hist(n=560, seed=9)
    dates = hist.index
    lp = make_leg_panel(dates, roll_long=2e-3)
    h = P.build_harvest_panel(hist, pairs=P.HARVEST_PAIRS, leg_panel=lp)
    sub = h[h["rac_net"].notna()]
    assert len(sub) > 100, "expected finite rac_net rows on persistent noise"
    recomputed = (sub["carry_lvl_1y_bp"] * sub["half_life_d"] / 252.0
                  + sub["rev_drag_bp"])
    assert np.allclose(sub["rac_net"], recomputed, rtol=1e-12)
    assert np.allclose(sub["carry_lvl_1y_bp"], -sub["carry_flat_1y_bp"], rtol=1e-12)
    # constant-roll construction: flattener carry -2bp, steepener +2bp
    assert np.allclose(sub["carry_flat_1y_bp"], -2.0, rtol=1e-9)
    assert (sub["carry_lvl_1y_bp"] > 0).all()
    # drag = 0.5*(rolling mean - level) wherever HL is finite
    one = h.xs("10y10y/20y10y", level="pair")
    lvl = hist["20y10y"] - hist["10y10y"]
    mu = lvl.rolling(756, min_periods=252).mean()
    want = 0.5 * (mu - lvl)
    got = one["rev_drag_bp"]
    m = got.notna()
    assert m.sum() > 100
    assert np.allclose(got[m], want[m], rtol=1e-9)


def test_harvest_be_over_rv_matches_strat3_formula():
    """be_over_rv = sqrt(|carry_flat|/(252*dM/1e4)) / rlzd_vol(long leg)."""
    from RVUtils.ConvexityRV.strat3_strikeless_vol import delta_m_years

    hist = make_hist(n=560, seed=13)
    lp = make_leg_panel(hist.index, roll_long=2e-3)
    h = P.build_harvest_panel(hist, pairs=("10y10y/15y10y",), leg_panel=lp)
    sub = h[h["be_over_rv"].notna()]
    assert len(sub) > 100
    dM = delta_m_years("10Yx10Y", "15Yx10Y")
    be = np.sqrt(2.0 / (252.0 * dM / 1e4))   # |carry|=2bp by construction
    assert np.allclose(sub["be_daily_bp"], be, rtol=1e-9)
    assert np.allclose(sub["be_over_rv"], be / sub["rlzd_vol_bp"], rtol=1e-9)


def test_lowercase_leg_panel_refused():
    """MUTATION: without the _screen_block asserts a lowercase-keyed leg
    panel is skipped SILENTLY by screen_panel_from_legs (empty screen, every
    gate refusing, build 'succeeds')."""
    hist = make_hist(n=400)
    lp = make_leg_panel(hist.index)
    lp_lc = lp.rename(index={"10Yx10Y": "10y10y", "15Yx10Y": "15y10y",
                             "20Yx10Y": "20y10y", "15Yx5Y": "15y5y"}, level="leg")
    with pytest.raises(ValueError, match="strat3-form"):
        P.build_harvest_panel(hist, pairs=P.HARVEST_PAIRS, leg_panel=lp_lc)


def test_leg_panel_input_guards():
    with pytest.raises(ValueError, match="spot leg"):
        P.build_leg_panel([dt.date(2024, 1, 3)], ["10y"], curve_map={})
    with pytest.raises(ValueError, match="duplicate"):
        P.build_leg_panel([dt.date(2024, 1, 3)], ["10y10y", "10Yx10Y"], curve_map={})


# ---------------------------------------------------------------------------
# glue — the real BT episode extractors consume these panels
# ---------------------------------------------------------------------------

def test_glue_kink_harvest_episodes():
    from BT.signals.cvx_kink_harvest import KinkHarvestConfig, episodes_from_panel

    hist = make_hist(n=560, seed=21)
    lp = make_leg_panel(hist.index)
    h = P.build_harvest_panel(hist, pairs=P.HARVEST_PAIRS, leg_panel=lp)

    # doctor one pair's gates: pass for ~3 months, then fail
    dates = hist.index
    win = dates[-120:-40]
    ix = pd.IndexSlice
    h.loc[ix[win, "10y10y/15y10y"], ["be_over_rv", "zs", "rac_net"]] = \
        np.array([1.30, 0.0, 1.0])
    h.loc[ix[dates[-40:], "10y10y/15y10y"], ["be_over_rv", "zs", "rac_net"]] = \
        np.array([0.5, 3.0, -1.0])

    cfg = KinkHarvestConfig(pairs=("10y10y/15y10y",),
                            start=win[0].date(), end=dates[-1].date())
    eps = episodes_from_panel(h, cfg)
    assert len(eps) >= 1
    e = eps[0]
    pair, entry, exit_ = e            # unpackable 3-tuple per the contract
    assert pair == "10y10y/15y10y"
    assert entry in dates and exit_ in dates and entry < exit_


def test_glue_fly_dislocation_episodes():
    from BT.signals.cvx_fly_dislocation import (
        REQUIRED_COLUMNS,
        FlyDislocationConfig,
        episodes_from_panel,
    )

    hist = make_hist(n=560, seed=23)
    d = P.build_dislocation_panel(hist)
    for c in REQUIRED_COLUMNS:        # the contract, from the consumer itself
        assert c in d.columns, c

    dates = hist.index
    ix = pd.IndexSlice
    sig = dates[-60:-20]
    d.loc[ix[sig, "5y1y"], "zs"] = 3.0
    d.loc[ix[sig, "5y1y"], "sign_agree"] = 1.0
    d.loc[ix[sig, "5y1y"], "edge_bp"] = 5.0
    d.loc[ix[dates[-20:], "5y1y"], "zs"] = 0.0   # target exit (zero-cross)

    cfg = FlyDislocationConfig(start=sig[0].date(), end=dates[-1].date())
    eps = episodes_from_panel(d, cfg)
    mine = [e for e in eps if e.point == "5y1y"]
    assert len(mine) >= 1
    e = mine[0]
    assert e.direction in (1, -1)
    assert e.leg_front == "4y1y" and e.leg_belly == "5y1y" and e.leg_back == "6y1y"
    assert e.w_belly > 0 > e.w_front
    assert e.exit_reason in ("stop", "target", "horizon", "end")


# ---------------------------------------------------------------------------
# integration — the real leg history (self-skipping)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_integration_dislocation_on_real_history():
    if not LEG_HISTORY.exists():
        pytest.skip(f"{LEG_HISTORY} absent")
    hist = pd.read_parquet(LEG_HISTORY)
    d = P.build_dislocation_panel(hist)
    n_dates = hist.shape[0]
    assert list(d.index.names) == ["date", "point"]
    assert len(d) == n_dates * 15
    last_day = d.index.get_level_values("date").max()
    one = d.xs(last_day, level="date")
    assert one["tag"].value_counts().to_dict() == \
        {"clean": 11, "convexity": 3, "meeting": 1}
    # carry: NaN exactly at the 1y1y fly (spot wing), finite elsewhere
    assert d.xs("1y1y", level="point")["carry_bp_day"].isna().all()
    for pt in ("5y1y", "15y5y"):
        assert d.xs(pt, level="point")["carry_bp_day"].notna().all()
    # z warmup only: after the first 756 sessions the z block must be live
    zs_tail = d[d.index.get_level_values("date") >= hist.index[756]]["zs"]
    assert float(zs_tail.notna().mean()) > 0.95
    # the fly must not be a level proxy: median |zs| stays moderate
    assert float(zs_tail.abs().median()) < 2.0


@pytest.mark.integration
def test_integration_harvest_degraded_on_real_history():
    if not LEG_HISTORY.exists():
        pytest.skip(f"{LEG_HISTORY} absent")
    hist = pd.read_parquet(LEG_HISTORY)
    h = P.build_harvest_panel(hist, pairs=P.HARVEST_PAIRS)
    assert list(h.index.names) == ["date", "pair"]
    assert set(h.index.get_level_values("pair")) == set(P.HARVEST_PAIRS)
    assert h["level_bp"].notna().all()
    assert h["rac_net"].isna().all()      # no leg panel: refusal, not zeros
