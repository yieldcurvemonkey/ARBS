"""Tests for RVUtils.CvxSuite.board — the cross-wrapper breakeven board.

Style per the suite convention (test_convexity_rv_strat2_q20): pure-logic
tests always run against hermetic fakes (no store, no parquet, no MDP);
data-backed tests are ``@pytest.mark.integration`` and self-skip with named
reasons when the local stores are absent.

Fake curve: the quadratic-forward fake from ``test_cvx_suite_carry`` (copied
with attribution) — instantaneous forward ``f(u) = A + B*u + C*u^2`` so par
rates and static-curve rolls have hand-derivable closed forms. Planted board
literals derived by hand in comments:

* W1 flattener carries on the fake (roll_bp(f,t) = -(B + C*(2f+t-1))*1e4):
  15Yx5Y/20Yx10Y -> -8.4-(-9.9) = +1.5 bp; 10Yx10Y/20Yx10Y -> +2.0 bp;
  10Yx10Y/15Yx10Y -> +1.0 bp. All positive -> be_daily_exact = 0.0.
* W3 adjacent-triple fly carries (second difference of the leg roll in f):
  (5y1y,6y1y,7y1y): rolls linear in f at fixed tenor -> EXACTLY 0.0;
  (10y2y,12y3y,15y5y): 2*(-(B+26C)) + (B+21C) + (B+34C) = +3C = +0.3 bp;
  (15y5y,20y5y,25y5y): equal tenor/spacing -> EXACTLY 0.0.
  The +0.3 literal is the discriminating one: mutating the fly weights to
  (-1,+1,-1) turns it into B+29C = +7.9 bp.
* W2 planted snapshot: ca(rank r) = 0.5*r bp, time_weight = r^2 ->
  sigma_impl(rank 1) = sqrt(2e4*0.5/1) = 100 bp/yr = 6.2994 bp/day;
  theta(rank 5) = 4*(2.5-2.0) = +2.0 bp/yr; whites theta NaN (no rank 0).
"""

from __future__ import annotations

import datetime
import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.CvxSuite import board as B
from RVUtils.CvxSuite import rent, vols
from RVUtils.CvxSuite.board import BOARD_COLUMNS, BoardConfig, board_priced, build_breakeven_board
from RVUtils.CvxSuite.grids import KinkPoint

# ---------------------------------------------------------------------------
# Fakes (curve fake copied from tests/test_cvx_suite_carry.py, same constants,
# so its hand-derived closed forms carry over verbatim)
# ---------------------------------------------------------------------------
A, C_A, C_C = 0.03, 5e-4, 1e-5  # A, B, C of the quadratic instantaneous forward
REF = datetime.datetime(2026, 8, 21)
ASOF = REF.date()


def fake_rate(f: float, t: float) -> float:
    return A + C_A * (f + t / 2.0) + C_C * (f * f + f * t + t * t / 3.0)


def fake_rate_inverted(f: float, t: float) -> float:
    """Mirror curve: rolls flip sign exactly, so flattener carries go NEGATIVE."""
    return 2.0 * A - fake_rate(f, t)


class FakeHandle:
    def __init__(self, shift_dec: float = 0.0, roll_y: float = 0.0):
        self.shift_dec = shift_dec
        self.roll_y = roll_y

    def shift(self, bp: float) -> "FakeHandle":
        return FakeHandle(self.shift_dec + bp / 1e4, self.roll_y)

    def roll(self, to_dt) -> "FakeHandle":
        h = (pd.Timestamp(to_dt) - pd.Timestamp(REF)).days / 365.0
        return FakeHandle(self.shift_dec, self.roll_y + h)


class FakeSwap:
    def __init__(self, f: float, t: float, k: float, notional: float, rate_fn):
        self.f, self.t, self.k, self.notional = f, t, k, notional
        self._rate_fn = rate_fn

    def npv(self, curves: FakeHandle) -> float:
        r = self._rate_fn(self.f - curves.roll_y, self.t) + curves.shift_dec
        return (r - self.k) * self.t * self.notional


class FakePricer:
    """Serves the curvefly identity, strat3 leg_metrics and build_irswap(bpv=...)."""

    def __init__(self, rate_fn=fake_rate):
        self._rate_fn = rate_fn

    def reference_date(self):
        return REF

    def handle(self) -> FakeHandle:
        return FakeHandle()

    def build_irswap(self, fwd=None, tenor=None, notional=None, **kw) -> FakeSwap:
        f = float(str(fwd).rstrip("Yy"))
        t = float(str(tenor).rstrip("Yy"))
        return FakeSwap(f, t, self._rate_fn(f, t), notional if notional else 1.0,
                        self._rate_fn)

    def fair_rate(self, swap: FakeSwap) -> float:
        return self._rate_fn(swap.f, swap.t)


class FakeCubeStore:
    """Serves a smooth ATM grid: vol_bp = level + expiry - tenor (bp/yr)."""

    def __init__(self, level: float = 100.0):
        self.level = float(level)
        self.reads = 0

    def read_day(self, asset, date, _allow_l2=False):
        self.reads += 1
        rows = []
        for e in (1, 5, 10, 15, 20, 30):
            for t in (1, 2, 5, 10, 30):
                rows.append({"expiry": f"{e}Y", "tenor": f"{t}Y",
                             "offset_bp": 0.0, "vol_bp": self.level + e - t})
        return pd.DataFrame(rows)


class _RaisingMDP:
    """A futures MDP whose every read misses (planted) — never a network call."""

    def get_data(self, request):
        raise RuntimeError("planted-miss")


class _QuadPayoff:
    """Stands in for curve_ops.payoff_profile: exact c*s^2 (USD)."""

    def __init__(self, c: float):
        self.c = float(c)

    def __call__(self, pricer, package, shifts, **kw):
        s = np.asarray(list(shifts), dtype=float)
        return self.c * s * s


def _mk_leg_hist(n: int = 900, scale: float = 1.0) -> pd.DataFrame:
    """Deterministic bp leg history ending at ASOF; per-leg phase so spreads move."""
    labels = ["15y5y", "20y10y", "10y10y", "15y10y",
              "5y1y", "6y1y", "7y1y", "10y2y", "12y3y", "20y5y", "25y5y",
              "1y10y", "5y10y"]
    idx = pd.bdate_range(end=pd.Timestamp(ASOF), periods=n)
    i = np.arange(n, dtype=float)
    data = {}
    for k, lab in enumerate(labels):
        f, t = _parse_cfs(lab)
        base = fake_rate(f, t) * 1e4
        wiggle = 25.0 * np.sin(2.0 * np.pi * (i / (55.0 + 3.0 * k) + 0.1 * k))
        data[lab] = (base + wiggle) * scale
    return pd.DataFrame(data, index=idx)


def _parse_cfs(lab: str):
    parts = lab.split("y")
    if parts[-1] == "":
        parts = parts[:-1]
    if len(parts) == 1:
        return 0.0, float(parts[0])
    return float(parts[0]), float(parts[1])


def _w2_snapshot(ranks=range(1, 14), drop=(), ca=None) -> pd.DataFrame:
    """Planted snapshot: ca(rank) = 0.5*rank bp (overridable), weight = rank^2."""
    colours = {1: "Whites", 5: "Reds", 9: "Greens", 13: "Blues"}
    rows = []
    for r in ranks:
        if r in drop:
            continue
        rows.append({
            "rank": r,
            "pack": f"P{r}",
            "colour": colours.get(r),
            "ca_bp": (ca or {}).get(r, 0.5 * r),
            "time_weight": float(r * r),
        })
    return pd.DataFrame(rows)


def _hermetic_cfg(**over) -> BoardConfig:
    kw = dict(
        leg_hist=_mk_leg_hist(),
        pricer=FakePricer(),
        cube_store=FakeCubeStore(),
        w2_snapshot=_w2_snapshot(),
    )
    kw.update(over)
    return BoardConfig(**kw)


# ---------------------------------------------------------------------------
# Column contract + constants
# ---------------------------------------------------------------------------
def test_column_contract_and_wrapper_counts(monkeypatch):
    """Columns exactly BOARD_COLUMNS in order; 3+4+3+3 rows; attrs populated.

    MUTATION: reorder/rename any BOARD_COLUMNS entry, or drop a wrapper
    section — the exact-list and per-wrapper-count asserts fail.
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    df = build_breakeven_board(ASOF, cfg=_hermetic_cfg())
    assert list(df.columns) == list(BOARD_COLUMNS)
    counts = df["wrapper"].value_counts().to_dict()
    assert counts == {"W2": 4, "W1": 3, "W3": 3, "W5": 3}
    assert df.attrs["asof"] == ASOF
    assert df.attrs["skips"] == {}
    assert set(df["wrapper"]) == {"W1", "W2", "W3", "W5"}
    # numeric columns are numeric (a stringly typed board breaks downstream math)
    for col in BOARD_COLUMNS[2:-1]:
        assert pd.api.types.is_float_dtype(df[col]), col


def test_citi_anchor_note_is_verbatim():
    """The task-specified label, pinned to the exact string.

    MUTATION: reword the label — this literal fails."""
    assert B.CITI_ANCHOR_NOTE == (
        "curve-pair anchors (0.8 long / 1.17-1.38 short) - not validated on micro-flies")
    assert B.CITI_ANCHOR_NOTE in B.CITI_ANCHOR_LINES


# ---------------------------------------------------------------------------
# W1 mapping
# ---------------------------------------------------------------------------
def test_w1_maps_screen_frame_columns_exactly(monkeypatch):
    """Board W1 rows == screen_frame columns under the documented map.

    The same inputs (fake pricer + composed histories) are fed to
    ``strat3.screen_frame`` directly; the board row must equal the screen's
    carry_1y_bp / gamma_usd_bp2 / be_daily_exact / rlzd_vol_bp / zs_3y.

    MUTATION: map sigma_be from ``be_daily_analytic`` instead of
    ``be_daily_exact`` — on this fake all carries are positive so both are
    0.0, but the paired negative-carry test below separates them. MUTATION:
    map z from zs_1y — the zs_3y equality here fails (different windows on a
    sin history).
    """
    from RVUtils.ConvexityRV.strat3_strikeless_vol import screen_frame

    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    cfg = _hermetic_cfg()
    df = build_breakeven_board(ASOF, cfg=cfg)
    w1 = df[df["wrapper"] == "W1"].set_index("structure")

    level_hist, rate_hist = B._w1_histories(cfg.leg_hist, cfg.w1_pairs)
    sf = screen_frame(FakePricer(), cfg.w1_pairs, asof=ASOF,
                      package_dv01_usd=cfg.package_dv01_usd,
                      level_hist=level_hist, rate_hist=rate_hist).set_index("pair")

    assert set(w1.index) == set(sf.index)
    for pair in sf.index:
        b, s = w1.loc[pair], sf.loc[pair]
        assert b["theta_bp_yr"] == pytest.approx(s["carry_1y_bp"], rel=1e-12)
        assert b["gamma_usd_bp2"] == pytest.approx(s["gamma_usd_bp2"], abs=1e-9)
        assert b["sigma_be"] == pytest.approx(s["be_daily_exact"], abs=1e-12)
        assert b["sigma_rlzd"] == pytest.approx(s["rlzd_vol_bp"], rel=1e-12)
        assert b["z"] == pytest.approx(s["zs_3y"], rel=1e-12)
        assert b["tag"] == "flattener"

    # hand-derived planted carries (fake closed form, see module docstring)
    assert w1.loc["15Yx5Y/20Yx10Y", "theta_bp_yr"] == pytest.approx(1.5, abs=1e-9)
    assert w1.loc["10Yx10Y/20Yx10Y", "theta_bp_yr"] == pytest.approx(2.0, abs=1e-9)
    assert w1.loc["10Yx10Y/15Yx10Y", "theta_bp_yr"] == pytest.approx(1.0, abs=1e-9)
    # positive carry -> be_daily_exact = 0.0 -> be_over_rv = 0.0 (finite, not NaN)
    assert (w1["sigma_be"] == 0.0).all()
    assert (w1["be_over_rv"] == 0.0).all()


def test_w1_sigma_impl_is_the_front_leg_cube_point(monkeypatch):
    """sigma_impl(W1) = cube ATM at (front fwd, front tenor), bp/DAY.

    Fake cube serves vol_bp = 100 + e - t bp/yr, so the 15Yx5Y front reads
    (100+15-5) = 110 bp/yr = 6.9294 bp/day and the 10Yx10Y fronts read 100
    bp/yr = 6.2994 bp/day.

    MUTATION: match the LONG leg instead of the front — 20Yx10Y would read
    110 not 110/100 as planted; MUTATION: drop bp_year_to_day — values come
    out ~15.9x too big and the units guard (tested separately) also fires.
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    df = build_breakeven_board(ASOF, cfg=_hermetic_cfg())
    w1 = df[df["wrapper"] == "W1"].set_index("structure")
    assert w1.loc["15Yx5Y/20Yx10Y", "sigma_impl"] == pytest.approx(110.0 / math.sqrt(252.0), rel=1e-12)
    assert w1.loc["10Yx10Y/20Yx10Y", "sigma_impl"] == pytest.approx(100.0 / math.sqrt(252.0), rel=1e-12)
    assert w1.loc["10Yx10Y/15Yx10Y", "sigma_impl"] == pytest.approx(100.0 / math.sqrt(252.0), rel=1e-12)


def test_w1_negative_carry_maps_exact_not_analytic(monkeypatch):
    """A negative-carry pair on a gamma-less fake: exact be is NaN, analytic is
    finite — the board must carry the EXACT one (NaN), not the analytic.

    The mirror curve (``fake_rate_inverted = 2A - fake_rate``) flips every
    roll sign exactly, so 15Yx5Y/20Yx10Y carries -1.5 bp with the pair in its
    proper shorter-first order (dM stays +10y). leg gamma == 0 on the linear
    fake, so be_daily_exact is NaN while be_daily_analytic =
    sqrt(|carry|/(252*dM/1e4)) = sqrt(1.5/(252*7.5e-4)) = 2.8172 bp/day is
    finite (dM = (20+5) - (15+2.5) = 7.5y).

    MUTATION: sigma_be <- be_daily_analytic — the NaN assert fails (the
    analytic value is finite here by construction).
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    cfg = _hermetic_cfg(pricer=FakePricer(rate_fn=fake_rate_inverted),
                        w1_pairs=(("15Yx5Y", "20Yx10Y"),))
    df = build_breakeven_board(ASOF, cfg=cfg)
    w1 = df[df["wrapper"] == "W1"]
    assert len(w1) == 1
    assert w1["theta_bp_yr"].iloc[0] == pytest.approx(-1.5, abs=1e-9)
    assert np.isnan(w1["sigma_be"].iloc[0])
    assert np.isnan(w1["be_over_rv"].iloc[0])
    # the analytic form IS finite here — proving the mapping picked "exact"
    from RVUtils.ConvexityRV.strat3_strikeless_vol import screen_frame

    level_hist, rate_hist = B._w1_histories(cfg.leg_hist, cfg.w1_pairs)
    sf = screen_frame(FakePricer(rate_fn=fake_rate_inverted), cfg.w1_pairs,
                      asof=ASOF, level_hist=level_hist, rate_hist=rate_hist)
    assert sf["be_daily_analytic"].iloc[0] == pytest.approx(
        math.sqrt(1.5 / (252.0 * 7.5 / 1e4)), rel=1e-9)


# ---------------------------------------------------------------------------
# W2 — injected snapshot logic
# ---------------------------------------------------------------------------
def test_w2_theta_is_the_annualised_ca_roll_and_whites_refuse(monkeypatch):
    """theta = 4*(CA(p) - CA(p-1)); whites (rank 1) NaN — no nearer window.

    Planted ca = 0.5*rank -> every ranked theta is 4*0.5 = +2.0 bp/yr.

    MUTATION: drop the x4 annualisation -> +0.5 fails; roll against rank+1
    (farther) instead of rank-1 -> sign flips on a non-linear plant (covered
    by the rank-12-missing control below, where rank+1 exists but rank-1
    does not).
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    df = build_breakeven_board(ASOF, cfg=_hermetic_cfg())
    w2 = df[df["wrapper"] == "W2"].set_index("structure")
    assert np.isnan(w2.loc["sr3-whites-pack-ca", "theta_bp_yr"])
    for s in ("sr3-reds-pack-ca", "sr3-greens-pack-ca", "sr3-blues-pack-ca"):
        assert w2.loc[s, "theta_bp_yr"] == pytest.approx(2.0, rel=1e-12)
    assert (w2["tag"].str.startswith("short-ca ")).all()
    # gamma is deliberately not quoted for a bp-space CA structure
    assert w2["gamma_usd_bp2"].isna().all()


def test_w2_missing_nearer_rank_gives_nan_theta_never_zero(monkeypatch):
    """Negative control: snapshot without rank 12 -> blues theta NaN.

    MUTATION: default the missing nearer CA to 0.0 — theta becomes
    4*(6.5-0) = 26.0, not NaN, and this fails."""
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    cfg = _hermetic_cfg(w2_snapshot=_w2_snapshot(drop=(12,)))
    df = build_breakeven_board(ASOF, cfg=cfg)
    w2 = df[df["wrapper"] == "W2"].set_index("structure")
    assert np.isnan(w2.loc["sr3-blues-pack-ca", "theta_bp_yr"])
    assert w2.loc["sr3-greens-pack-ca", "theta_bp_yr"] == pytest.approx(2.0, rel=1e-12)


def test_w2_implied_vol_closed_form_and_negative_ca_refuses(monkeypatch):
    """sigma_impl = sqrt(2e4*CA/M)/sqrt(252); CA<=0 -> NaN (holee refusal).

    Whites planted: sqrt(2e4*0.5/1) = 100 bp/yr = 6.29941 bp/day — the same
    number through the closed form. Negative-CA control: blues at -0.1 bp
    must produce NaN sigma_impl AND NaN sigma_be, never a complex/zero.

    MUTATION: pass convention="hull" — the pseudo-T1 sqrt(M) then weights
    sqrt(M)*(sqrt(M)+0.25) != M and the whites literal fails. MUTATION: feed
    t_mid instead of sqrt(time_weight) — same failure.
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    df = build_breakeven_board(ASOF, cfg=_hermetic_cfg())
    w2 = df[df["wrapper"] == "W2"].set_index("structure")
    assert w2.loc["sr3-whites-pack-ca", "sigma_impl"] == pytest.approx(
        100.0 / math.sqrt(252.0), rel=1e-12)
    assert w2.loc["sr3-reds-pack-ca", "sigma_impl"] == pytest.approx(
        math.sqrt(2e4 * 2.5 / 25.0) / math.sqrt(252.0), rel=1e-12)

    cfg = _hermetic_cfg(w2_snapshot=_w2_snapshot(ca={13: -0.1}))
    df2 = build_breakeven_board(ASOF, cfg=cfg)
    w2b = df2[df2["wrapper"] == "W2"].set_index("structure")
    assert np.isnan(w2b.loc["sr3-blues-pack-ca", "sigma_impl"])
    assert np.isnan(w2b.loc["sr3-blues-pack-ca", "sigma_be"])


def test_w2_be_equals_impl_identity(monkeypatch):
    """W2's sigma_be IS the CA-implied vol (same closed form), so
    be_over_rv == impl_over_rv row by row (or both NaN).

    MUTATION: set W2 sigma_be to NaN or 0.0 — the equality fails on rows with
    a finite realized."""
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    hist_idx = pd.bdate_range(end=pd.Timestamp(ASOF), periods=70)
    wig = pd.Series(400.0 + 10.0 * np.sin(np.arange(70) / 5.0), index=hist_idx)
    cfg = _hermetic_cfg(w2_pack_history=pd.DataFrame({"P1": wig, "P5": wig + 5.0}))
    df = build_breakeven_board(ASOF, cfg=cfg)
    w2 = df[df["wrapper"] == "W2"]
    assert np.isfinite(w2["sigma_rlzd"]).sum() == 2  # P1, P5 supplied; P9/P13 absent
    for _, r in w2.iterrows():
        if np.isfinite(r["be_over_rv"]) or np.isfinite(r["impl_over_rv"]):
            assert r["be_over_rv"] == r["impl_over_rv"]
        assert (r["sigma_be"] == r["sigma_impl"]) or (
            np.isnan(r["sigma_be"]) and np.isnan(r["sigma_impl"]))


def test_w2_sigma_rlzd_matches_the_vols_kernel(monkeypatch):
    """Injected pack history -> sigma_rlzd == realized_vol_bp_day(...) last value.

    MUTATION: annualise (x sqrt 252) inside the board — this equality fails
    (and the real-data units guard would also fire)."""
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    idx = pd.bdate_range(end=pd.Timestamp(ASOF), periods=70)
    ser = pd.Series(400.0 + 10.0 * np.sin(np.arange(70) / 4.0), index=idx)
    cfg = _hermetic_cfg(w2_pack_history=pd.DataFrame({"P9": ser}))
    df = build_breakeven_board(ASOF, cfg=cfg)
    w2 = df[df["wrapper"] == "W2"].set_index("structure")
    expected = float(vols.realized_vol_bp_day(ser, window=63, min_periods=42).iloc[-1])
    assert w2.loc["sr3-greens-pack-ca", "sigma_rlzd"] == pytest.approx(expected, rel=1e-12)
    assert np.isfinite(expected) and expected > 0


# ---------------------------------------------------------------------------
# W2 — wrapper-skip logic (production path against a planted-miss MDP)
# ---------------------------------------------------------------------------
def test_w2_skip_ships_the_rest_of_the_board(monkeypatch):
    """No cached settles -> W2 SKIPPED with a named reason; W1/W3/W5 still ship.

    MUTATION: let a W2 failure abort the whole board (re-raise) — the row
    counts fail. MUTATION: swallow the reason (skips stays empty) — the
    attrs assert fails. MUTATION: emit W2 rows of NaNs instead of skipping —
    the zero-W2-row assert fails.
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    cfg = _hermetic_cfg(w2_snapshot=None, futures_mdp=_RaisingMDP())
    df = build_breakeven_board(ASOF, cfg=cfg)
    assert (df["wrapper"] == "W2").sum() == 0
    assert "W2" in df.attrs["skips"]
    reason = df.attrs["skips"]["W2"]
    assert "SR3" in reason and str(ASOF) in reason
    assert (df["wrapper"] == "W1").sum() == 3
    assert (df["wrapper"] == "W3").sum() == 3
    assert (df["wrapper"] == "W5").sum() == 3
    assert board_priced(df)


# ---------------------------------------------------------------------------
# W3 — micro-flies
# ---------------------------------------------------------------------------
def test_w3_planted_fly_carries_and_rent_composition(monkeypatch):
    """The hand-derived triple carries (0.0 / +0.3 / 0.0 bp) and the full rent
    chain through the monkeypatched quadratic payoff (c=-0.15 -> gamma=-0.30).

    (10y2y,12y3y,15y5y): theta=+0.3, gamma<0 -> ROOT:
    sigma_be = sqrt(2*(0.3/252*50_000)/0.30) = sqrt(396.825) = 19.9205 bp/day.
    (5y1y,6y1y,7y1y) and (15y5y,20y5y,25y5y): theta=0, gamma<0 -> never_cheap
    -> sigma_be = inf (the strat1 taxonomy through the board; a NaN here
    would hide the state).

    MUTATION: fly weights (-1,+1,-1) — the +0.3 literal becomes +7.9.
    MUTATION: dv01_usd = package_dv01 instead of package_dv01/2 — the root
    sigma_be inflates by sqrt(2) and the 19.9205 literal fails.
    MUTATION: never_cheap collapsed to NaN — the inf asserts fail.
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    df = build_breakeven_board(ASOF, cfg=_hermetic_cfg())
    w3 = df[df["wrapper"] == "W3"].set_index("structure")
    assert list(w3.index) == ["5y1y/6y1y/7y1y", "10y2y/12y3y/15y5y", "15y5y/20y5y/25y5y"]

    assert w3.loc["5y1y/6y1y/7y1y", "theta_bp_yr"] == pytest.approx(0.0, abs=1e-9)
    assert w3.loc["10y2y/12y3y/15y5y", "theta_bp_yr"] == pytest.approx(0.3, abs=1e-9)
    assert w3.loc["15y5y/20y5y/25y5y", "theta_bp_yr"] == pytest.approx(0.0, abs=1e-9)

    assert np.allclose(w3["gamma_usd_bp2"].to_numpy(), -0.30, rtol=1e-12)
    be = w3.loc["10y2y/12y3y/15y5y", "sigma_be"]
    assert be == pytest.approx(math.sqrt(2.0 * (0.3 / 252.0 * 50_000.0) / 0.30), rel=1e-9)
    assert np.isposinf(w3.loc["5y1y/6y1y/7y1y", "sigma_be"])
    assert np.isposinf(w3.loc["15y5y/20y5y/25y5y", "sigma_be"])

    # zone tags come from the BELLY point
    assert w3["tag"].tolist() == ["clean", "clean", "convexity"]

    # belly-point cube vol: 12y3y -> (100+12-3)=109 bp/yr on the fake cube
    assert w3.loc["10y2y/12y3y/15y5y", "sigma_impl"] == pytest.approx(
        109.0 / math.sqrt(252.0), rel=1e-12)


def test_w3_long_gamma_positive_theta_is_always_cheap(monkeypatch):
    """c>0 (long gamma) with theta>=0 -> always_cheap -> sigma_be = 0.0 exactly.

    MUTATION: always_cheap collapsed to NaN — fails."""
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=+0.15))
    df = build_breakeven_board(ASOF, cfg=_hermetic_cfg())
    w3 = df[df["wrapper"] == "W3"].set_index("structure")
    assert w3.loc["10y2y/12y3y/15y5y", "sigma_be"] == 0.0
    assert w3.loc["5y1y/6y1y/7y1y", "sigma_be"] == 0.0


def test_w3_rlzd_and_z_come_from_the_composed_fly_level(monkeypatch):
    """sigma_rlzd/z equal the vols kernels on the hand-composed 2b-a-c series.

    MUTATION: compose b-a-c or a+c-2b (sign flip) — the realized matches (vol
    is sign-blind) but the z literal flips sign and fails; MUTATION: read the
    belly leg's own history — both fail.
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    cfg = _hermetic_cfg()
    df = build_breakeven_board(ASOF, cfg=cfg)
    w3 = df[df["wrapper"] == "W3"].set_index("structure")

    lh = cfg.leg_hist
    fly = 2.0 * lh["12y3y"] - lh["10y2y"] - lh["15y5y"]
    exp_rv = float(vols.realized_vol_bp_day(fly.dropna(), window=252, min_periods=100).iloc[-1])
    tail = fly.dropna().iloc[-756:]
    exp_z = float((tail.iloc[-1] - tail.mean()) / tail.std(ddof=1))
    assert w3.loc["10y2y/12y3y/15y5y", "sigma_rlzd"] == pytest.approx(exp_rv, rel=1e-12)
    assert w3.loc["10y2y/12y3y/15y5y", "z"] == pytest.approx(exp_z, rel=1e-12)
    assert np.isfinite(exp_rv) and exp_rv > 0
    assert abs(exp_z) > 1e-6  # non-vacuous: the sign-flip mutation has something to flip


def test_w3_triple_validation_is_loud():
    """Non-adjacent or off-grid triples raise at once (never a silent fly).

    MUTATION: drop the adjacency check — the non-adjacent case stops raising."""
    with pytest.raises(ValueError, match="ADJACENT"):
        B._validate_triple((KinkPoint(5.0, 1.0), KinkPoint(7.0, 1.0), KinkPoint(8.0, 1.0)))
    with pytest.raises(ValueError, match="KINK_GRID"):
        B._validate_triple((KinkPoint(5.5, 1.0), KinkPoint(6.0, 1.0), KinkPoint(7.0, 1.0)))
    pts = B._validate_triple((KinkPoint(5.0, 1.0), KinkPoint(6.0, 1.0), KinkPoint(7.0, 1.0)))
    assert pts == (KinkPoint(5.0, 1.0), KinkPoint(6.0, 1.0), KinkPoint(7.0, 1.0))


# ---------------------------------------------------------------------------
# W5 — cube ATM vs realized forward par rate
# ---------------------------------------------------------------------------
def test_w5_impl_and_rlzd_and_missing_leg_refusal(monkeypatch):
    """W5: sigma_impl = cube point bp/day; sigma_rlzd = matching leg realized;
    an absent leg label -> NaN + a printed note, never a nearest-neighbour.

    (1,10) reads cube (100+1-10)=91 bp/yr and leg '1y10y'. The custom point
    (2,7) has no '2y7y' column in the planted history -> NaN rlzd, note names
    the label.

    MUTATION: nearest-label fallback — the NaN assert fails; MUTATION: read
    the tail-matched spot leg ('10y') — the mapping equality fails.
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    cfg = _hermetic_cfg(w5_points=((1.0, 10.0), (5.0, 10.0), (2.0, 7.0)))
    df = build_breakeven_board(ASOF, cfg=cfg)
    w5 = df[df["wrapper"] == "W5"].set_index("structure")

    assert w5.loc["1yx10y", "sigma_impl"] == pytest.approx(91.0 / math.sqrt(252.0), rel=1e-12)
    exp = float(vols.realized_vol_bp_day(
        cfg.leg_hist["1y10y"], window=252, min_periods=100).iloc[-1])
    assert w5.loc["1yx10y", "sigma_rlzd"] == pytest.approx(exp, rel=1e-12)
    assert w5.loc["1yx10y", "impl_over_rv"] == pytest.approx(
        w5.loc["1yx10y", "sigma_impl"] / exp, rel=1e-12)

    assert np.isnan(w5.loc["2yx7y", "sigma_rlzd"])
    assert any("2y7y" in n for n in df.attrs["notes"])
    # vol-only wrapper: theta/gamma/sigma_be/z all refuse
    assert w5[["theta_bp_yr", "gamma_usd_bp2", "sigma_be", "z"]].isna().all().all()
    assert (w5["tag"] == "atm-vol").all()


# ---------------------------------------------------------------------------
# Units-guard wiring
# ---------------------------------------------------------------------------
def test_units_guard_fires_on_a_bp_year_cube(monkeypatch):
    """A cube left in bp/yr scale (2000 -> ~126 bp/day) must RAISE, naming bp/DAY.

    MUTATION: drop the bp_year_to_day conversion on sigma_impl — the normal
    100 bp/yr store then reads ~100 bp/day and the negative control below
    raises instead; MUTATION: drop the _guard_units call — this test fails.
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    with pytest.raises(ValueError, match="bp/DAY"):
        build_breakeven_board(ASOF, cfg=_hermetic_cfg(cube_store=FakeCubeStore(level=2000.0)))


def test_units_guard_negative_control_normal_scale_passes(monkeypatch):
    """The same board at a plausible 100 bp/yr cube does NOT raise."""
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    df = build_breakeven_board(ASOF, cfg=_hermetic_cfg())
    assert len(df) == 13


def test_units_guard_fires_on_an_annualised_realized(monkeypatch):
    """A leg history 100x too big (percent-of-percent style slip) drives the
    W1/W5 realized median above 40 bp/day -> RAISE.

    W3's fly-level realized is excluded from this population by design (a
    micro-fly level vol may sit below the 0.5 floor legitimately); the raise
    here comes from the rate-level population.
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.15))
    with pytest.raises(ValueError, match="bp/DAY"):
        build_breakeven_board(ASOF, cfg=_hermetic_cfg(leg_hist=_mk_leg_hist(scale=100.0)))


# ---------------------------------------------------------------------------
# Exit semantics
# ---------------------------------------------------------------------------
def test_board_priced_semantics():
    """priced = any finite sigma_be/sigma_impl/sigma_rlzd; 0.0 counts, inf/NaN
    do not; empty board is not priced.

    MUTATION: invert the exit condition or count inf as priced — these fail."""
    empty = pd.DataFrame(columns=list(BOARD_COLUMNS))
    assert board_priced(empty) is False

    def mk(be, impl, rlzd):
        r = B._row("x", "W5", sigma_be=be, sigma_impl=impl, sigma_rlzd=rlzd)
        d = pd.DataFrame([r])
        d["be_over_rv"] = d["sigma_be"] / d["sigma_rlzd"]
        d["impl_over_rv"] = d["sigma_impl"] / d["sigma_rlzd"]
        return d[list(BOARD_COLUMNS)]

    assert board_priced(mk(np.nan, np.nan, np.nan)) is False
    assert board_priced(mk(np.inf, np.nan, np.nan)) is False
    assert board_priced(mk(0.0, np.nan, np.nan)) is True
    assert board_priced(mk(np.nan, 5.0, np.nan)) is True


def test_w1_history_composition_is_long_minus_short():
    """level = rate(long) - rate(short); missing legs raise naming the column.

    MUTATION: compose short-long (sign flip) — the planted constant fails."""
    lh = pd.DataFrame({
        "15y5y": [100.0, 101.0],
        "20y10y": [110.0, 112.0],
    }, index=pd.bdate_range(end=pd.Timestamp(ASOF), periods=2))
    level, rate = B._w1_histories(lh, (("15Yx5Y", "20Yx10Y"),))
    assert list(level.columns) == ["15Yx5Y/20Yx10Y"]
    assert level.iloc[0, 0] == pytest.approx(10.0)
    assert level.iloc[1, 0] == pytest.approx(11.0)
    assert set(rate.columns) == {"15Yx5Y", "20Yx10Y"}
    with pytest.raises(KeyError, match="10y10y"):
        B._w1_histories(lh, (("10Yx10Y", "20Yx10Y"),))


# ---------------------------------------------------------------------------
# Integration — the real stores, self-skipping
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def real_pricer_2026_08_21():
    try:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        pricer = IRSwapsMDP(source="CITIVELO_EXCEL").get_data(
            {"curve_name": "USD-SOFR-1D", "timestamp": datetime.date(2026, 8, 21),
             "offline": True})
    except Exception as exc:  # noqa: BLE001 — a cold store is not a failure
        pytest.skip(f"local Citi curve store cannot serve 2026-08-21 offline: {exc!r}")
    if pricer is None:
        pytest.skip("IRSwapsMDP.get_data returned None for 2026-08-21 offline (store miss)")
    if pricer.meta().get("from_curve_store") is not True:
        pytest.skip("2026-08-21 pricer is not store-backed; offline discipline forbids it")
    return pricer


@pytest.mark.integration
def test_board_real_2026_08_21(real_pricer_2026_08_21):
    """Full board on real stores, 2026-08-21 (Friday; SR3 cache likely ended
    ~08-13 so W2 skips — either outcome is accepted but must be coherent).

    Asserts (task contract): all three W1 pairs price with FINITE be_over_rv;
    the pooled W1 sigma_be+sigma_rlzd population passes the 0.5-40 bp/day
    units guard (MUTATION: annualise rlzd_vol_bp — the guard raises); W3/W5
    fully populated; W2 rows XOR a W2 skip reason.
    """
    if not B._default_leg_hist_path().exists():
        pytest.skip(f"leg history parquet absent at {B._default_leg_hist_path()}")
    try:
        from Caching.swaption_cube_store import SwaptionCubeStore

        store = SwaptionCubeStore.default()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"swaption cube store unavailable: {exc!r}")

    cfg = BoardConfig(pricer=real_pricer_2026_08_21, cube_store=store)
    df = build_breakeven_board(datetime.date(2026, 8, 21), cfg=cfg)

    assert list(df.columns) == list(BOARD_COLUMNS)
    w1 = df[df["wrapper"] == "W1"]
    assert len(w1) == 3, f"W1 must price all three pairs; skips={df.attrs['skips']}"
    assert np.isfinite(w1["be_over_rv"]).all(), "W1 be_over_rv must be finite on real data"
    assert np.isfinite(w1["theta_bp_yr"]).all()
    assert (w1["gamma_usd_bp2"] > 0).all(), "flatteners are long convexity (measured convention)"

    pool = pd.concat([w1["sigma_be"], w1["sigma_rlzd"]])
    vols.units_median_guard(pool)  # raises on a bp/yr slip — the task's units gate

    assert (df["wrapper"] == "W3").sum() == 3
    assert (df["wrapper"] == "W5").sum() == 3
    w5 = df[df["wrapper"] == "W5"]
    assert np.isfinite(w5["sigma_rlzd"]).all(), "all three W5 legs exist in the history"

    has_w2 = bool((df["wrapper"] == "W2").any())
    assert has_w2 != ("W2" in df.attrs["skips"]), "W2 must either price or skip with a reason"
    assert board_priced(df)
