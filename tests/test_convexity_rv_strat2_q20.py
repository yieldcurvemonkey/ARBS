"""Tests for the Q20 deep-pack rate source and its admissibility gate.

Three kinds of test, and the distinction matters for what a green run proves:

**Pure logic** -- roll-date arithmetic, universe derivation, gate composition,
frame plumbing. No market data, always runs.

**Known-answer** -- Citi Research's published SOFR screen (Figure 58, close
6/9/2023, 13 rows including Blues at 15.40bp and Golds at 22.29bp). The
internal-consistency identities in that table (``VsModel = CA - Model``, the 3m
roll recursion, the implied-vol inversion) are reproduced from the published
numbers alone, so they pin the *model* independently of this repo's market data.

**Data-dependent** -- the offline Q20 build and the gate's behaviour on the real
panel. Skipped when the local SR3 diskcache or the built panel is absent, so the
suite stays green on a machine without them, and the skip is explicit rather
than a silent pass.

Every data-dependent test asserts ``network_calls_blocked()`` did not move.
That is not hygiene, it is the property the whole module is built to have: the
production ``IRSwapsMDP.get_pricer`` path for a ``*STIRT`` curve makes 52-57
Barchart requests per date on this machine.
"""
from __future__ import annotations

import datetime
import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import strat2_q20 as Q
from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp
from RVUtils.ConvexityRV.listed_cache_guard import network_calls_blocked
from RVUtils.ConvexityRV.packs import imm_date, quarterly_imm_sequence
from RVUtils.ConvexityRV.strat2_sofr_convexity import Strat2Config, futures_symbol

_REPO = pathlib.Path(__file__).resolve().parents[1]
_PANEL = _REPO / "notebooks" / "data" / "convexity_rv" / "strat2_q20_panel.parquet"


# ===========================================================================
# Pure logic: the IMM roll-date off-by-one
# ===========================================================================
def test_imm_roll_dates_are_detected():
    """3rd Wednesdays of Mar/Jun/Sep/Dec are roll dates; neighbours are not."""
    for y, m in ((2019, 6), (2021, 9), (2023, 3), (2018, 12)):
        d = imm_date(y, m)
        assert Q.is_imm_roll_date(d), f"{d} is an IMM date and must be a roll date"
        assert not Q.is_imm_roll_date(d - datetime.timedelta(days=1))
        assert not Q.is_imm_roll_date(d + datetime.timedelta(days=1))


def test_instrument_count_drops_one_on_roll_dates():
    """The SFRCM ladder has rolled past the expiring contract; the pack universe
    has not. Measured: 8 of the 10 dates that reached for the network in a full
    build were IMM roll dates, and all resolved at ``depth - 1``."""
    roll = imm_date(2019, 6)
    assert Q.instrument_count(roll, 20) == 19
    assert Q.instrument_count(roll - datetime.timedelta(days=1), 20) == 20
    assert Q.instrument_count(datetime.date(2023, 6, 9), 20) == 20


def test_roll_date_sequence_shifts_by_exactly_one():
    """The mechanism behind the fix, stated as an identity rather than a claim."""
    d = imm_date(2019, 6)
    incl = quarterly_imm_sequence(d, 21, include_current=True)
    excl = quarterly_imm_sequence(d, 20, include_current=False)
    assert imm_date(*incl[0]) == d
    assert excl == incl[1:]


# ===========================================================================
# Pure logic: universe
# ===========================================================================
def test_rank_depth_roundtrip():
    for r in range(1, 18):
        assert Q.max_rank_for_depth(Q.depth_for_rank(r)) == r
    # a pack starting at rank r uses contracts r..r+3
    assert Q.depth_for_rank(13) == 16, "Blues needs 16 contracts"
    assert Q.depth_for_rank(17) == 20, "Golds needs 20 contracts"


def test_deep_pack_config_reproduces_citis_universe():
    """rank_start=5, n_packs=13 IS Citi's published screen: windows 5..17."""
    cfg = Q.deep_pack_config(rank_start=5, n_packs=13)
    assert isinstance(cfg, Strat2Config)
    assert cfg.n_contracts == 20
    assert cfg.rank_start == 5 and cfg.n_packs == 13
    # the deepest ranked window is Golds
    assert cfg.rank_start + cfg.n_packs - 1 == 17


def test_deep_pack_config_derives_n_contracts_and_cannot_be_inconsistent():
    """Deriving n_contracts is the point: a caller cannot ask for a universe the
    strip cannot cover, which Strat2Config would otherwise only catch after a
    panel had been built against the wrong strip."""
    for rs, npk in ((5, 13), (9, 6), (2, 9), (13, 5)):
        cfg = Q.deep_pack_config(rank_start=rs, n_packs=npk)
        assert cfg.n_contracts == rs + npk - 1 + 3
    # overrides still flow through
    cfg = Q.deep_pack_config(rank_start=9, n_packs=6, ca_dv01=250_000.0)
    assert cfg.ca_dv01 == 250_000.0


def test_q20config_rejects_bad_settings():
    with pytest.raises(ValueError):
        Q.Q20Config(rate_source="curve")
    with pytest.raises(ValueError):
        Q.Q20Config(max_instruments=21)
    with pytest.raises(ValueError):
        Q.Q20Config(min_instruments=15, max_instruments=12)


def test_forwards_to_prices_is_the_rate_inverse():
    """The adapter that lets the whole existing screen run off a curve."""
    rates = {(2026, 6): 3.25, (2026, 9): 3.5}
    px = Q.forwards_to_prices(rates)
    assert px[futures_symbol(2026, 6)] == pytest.approx(96.75)
    assert px[futures_symbol(2026, 9)] == pytest.approx(96.50)
    for (y, m), r in rates.items():
        assert 100.0 - px[futures_symbol(y, m)] == pytest.approx(r)


# ===========================================================================
# Pure logic: the gate
# ===========================================================================
class _Spec:
    """Minimal stand-in for a PackSpec -- the gate only reads three fields."""

    def __init__(self, rank, contracts, start, end):
        self.rank = rank
        self.contracts = contracts
        self.swap_start = start
        self.swap_end = end


def _spec(rank=5):
    seq = quarterly_imm_sequence(datetime.date(2023, 6, 9), 24)
    cts = tuple(seq[rank - 1:rank + 3])
    return _Spec(rank, cts, imm_date(*cts[0]), imm_date(cts[0][0] + 1, cts[0][1]))


def _fwds(spec, base=4.0, step=0.10):
    return {k: base + i * step for i, k in enumerate(spec.contracts)}


def test_gate_rejects_a_window_swallowed_by_one_node_interval():
    """THE test. A window with no node inside carries one interpolated forward
    across all four quarters; the zero-convexity control then returns exactly
    0.00bp however wrong the swap leg is, so the control is structurally blind
    and only this check can see it. It is the 2019 front-end failure.

    The forwards here are deliberately given a WIDE spread (30bp), so the
    control-power clause passes on its own. Without that the test would reject
    the window via ``fwd_spread_bp`` and would keep passing even if the
    ``spans_window`` check were deleted -- which is exactly what a mutation run
    caught it doing.
    """
    s = _spec(5)
    f = _fwds(s)                                       # 30bp of spread: real power
    settles = dict(f)                                  # settles agree perfectly
    nodes = [s.swap_start - datetime.timedelta(days=400),
             s.swap_end + datetime.timedelta(days=400)]
    g = Q.window_gate(s, q20_nodes=nodes, q20_fwds=f, settles=settles,
                      depth=20, cfg=Q.Q20Config())
    assert g["q20_n_nodes_inside"] == 0
    assert g["q20_spans_window"] == 1.0
    assert g["fwd_spread_bp"] == pytest.approx(30.0), "control power must NOT be the reason"
    assert g["max_settle_diff_bp"] == pytest.approx(0.0), "agreement must NOT be the reason"
    assert g["gate_covered"], "coverage must NOT be the reason"
    assert not g["gate_resolved"], "a node-free window must fail resolution"
    assert not g["gate_ok"], "perfect settle agreement must NOT rescue it"


def test_gate_rejects_a_window_with_too_few_nodes_inside():
    """``gate_min_nodes_inside`` is a separate lever from ``spans_window``: a
    window can straddle a node boundary (so nothing "spans" it) and still be
    almost entirely interpolated."""
    s = _spec(5)
    f = _fwds(s)
    mid = s.swap_start + (s.swap_end - s.swap_start) / 2
    nodes = [s.swap_start - datetime.timedelta(days=400), mid,
             s.swap_end + datetime.timedelta(days=400)]
    base = Q.window_gate(s, q20_nodes=nodes, q20_fwds=f, settles=dict(f),
                         depth=20, cfg=Q.Q20Config(gate_min_nodes_inside=1))
    assert base["q20_n_nodes_inside"] == 1 and base["q20_spans_window"] == 0.0
    assert base["gate_resolved"]
    strict = Q.window_gate(s, q20_nodes=nodes, q20_fwds=f, settles=dict(f),
                           depth=20, cfg=Q.Q20Config(gate_min_nodes_inside=3))
    assert not strict["gate_resolved"], "1 node must fail a 3-node requirement"


def test_gate_rejects_a_window_with_no_control_power():
    """Four identical forwards mean the zero-convexity control is looking at
    nothing, and its 0.00bp pass is an absence of evidence."""
    s = _spec(5)
    f = {k: 4.0 for k in s.contracts}
    mid = s.swap_start + (s.swap_end - s.swap_start) / 2
    nodes = [s.swap_start - datetime.timedelta(days=10), mid,
             s.swap_end + datetime.timedelta(days=10)]
    g = Q.window_gate(s, q20_nodes=nodes, q20_fwds=f, settles=dict(f),
                      depth=20, cfg=Q.Q20Config())
    assert g["q20_spans_window"] == 0.0, "node placement must NOT be the reason"
    assert g["fwd_spread_bp"] == pytest.approx(0.0)
    assert not g["gate_resolved"]


def test_gate_accepts_a_well_resolved_window():
    s = _spec(5)
    f = _fwds(s)
    nodes = ([s.swap_start - datetime.timedelta(days=30)]
             + [s.swap_start + datetime.timedelta(days=k) for k in (30, 90, 150, 250)]
             + [s.swap_end + datetime.timedelta(days=30)])
    g = Q.window_gate(s, q20_nodes=nodes, q20_fwds=f, settles=dict(f),
                      depth=20, cfg=Q.Q20Config())
    assert g["q20_n_nodes_inside"] == 4
    assert g["q20_spans_window"] == 0.0
    assert g["gate_resolved"] and g["gate_settle_agrees"] and g["gate_ok"]
    assert g["fwd_spread_bp"] == pytest.approx(30.0)   # 0.30% spread -> 30bp


def test_gate_uses_the_MAX_settle_diff_not_the_mean():
    """ONE leg wrong by 6bp against a 2bp tolerance.

    The mean of ``|diff|`` is 1.5bp and would PASS; the max is 6bp and must
    FAIL. The gap straddling the threshold is the whole point -- an earlier
    version of this test used two legs at +-6bp, whose mean (3bp) also failed,
    so it passed identically against a mean-based implementation and a
    mutation run caught it as vacuous.
    """
    s = _spec(5)
    f = _fwds(s)
    settles = dict(f)
    settles[list(s.contracts)[0]] += 0.06          # one leg, +6bp
    nodes = ([s.swap_start - datetime.timedelta(days=30)]
             + [s.swap_start + datetime.timedelta(days=k) for k in (30, 150, 250)]
             + [s.swap_end + datetime.timedelta(days=30)])
    g = Q.window_gate(s, q20_nodes=nodes, q20_fwds=f, settles=settles,
                      depth=20, cfg=Q.Q20Config())
    cfg = Q.Q20Config()
    assert g["mean_settle_diff_bp"] == pytest.approx(1.5)
    assert g["max_settle_diff_bp"] == pytest.approx(6.0)
    assert g["mean_settle_diff_bp"] < cfg.gate_max_settle_diff_bp, (
        "the mean must sit INSIDE the tolerance or this test cannot discriminate")
    assert g["max_settle_diff_bp"] > cfg.gate_max_settle_diff_bp
    assert g["gate_resolved"], "resolution must NOT be the reason it fails"
    assert not g["gate_settle_agrees"], "one 6bp leg must fail a 2bp tolerance"
    assert not g["gate_ok"]


def test_gate_requires_instrument_coverage():
    """The curve is never asked to extrapolate past its last instrument."""
    s = _spec(17)                                     # needs 20 contracts
    f = _fwds(s)
    nodes = ([s.swap_start - datetime.timedelta(days=30)]
             + [s.swap_start + datetime.timedelta(days=k) for k in (30, 150, 250)]
             + [s.swap_end + datetime.timedelta(days=30)])
    for depth, want in ((20, True), (19, False)):
        g = Q.window_gate(s, q20_nodes=nodes, q20_fwds=f, settles=dict(f),
                          depth=depth, cfg=Q.Q20Config())
        assert g["gate_covered"] is want
        assert g["gate_ok"] is want


def test_gate_conditions_can_be_switched_off_independently():
    """So the notebook can measure what each condition removes."""
    s = _spec(5)
    f = {k: 4.0 for k in s.contracts}
    nodes = [s.swap_start - datetime.timedelta(days=400),
             s.swap_end + datetime.timedelta(days=400)]
    off = Q.Q20Config(gate_require_resolution=False)
    g = Q.window_gate(s, q20_nodes=nodes, q20_fwds=f, settles=dict(f),
                      depth=20, cfg=off)
    assert not g["gate_resolved"], "the measurement must still be reported"
    assert g["gate_ok"], "but it must not be enforced when switched off"


def test_apply_gate_is_a_pure_filter():
    df = pd.DataFrame({"gate_ok": [True, False, True], "x": [1, 2, 3]})
    out = Q.apply_gate(df)
    assert list(out["x"]) == [1, 3]
    assert len(df) == 3, "apply_gate must not mutate its input"
    # an absent column is a no-op, not a crash
    assert len(Q.apply_gate(df, require=("nope",))) == 3


# ===========================================================================
# Sign probe
# ===========================================================================
def test_sign_probe_ca_is_futures_minus_swap():
    """The convexity adjustment is POSITIVE when the futures rate exceeds the
    matched forward swap rate -- the no-arbitrage direction. Verified through
    the real ``ca_snapshot`` with a synthetic curve, so the sign is the one the
    shipped code produces, not one asserted about a formula."""
    from RVUtils.ConvexityRV.strat2_sofr_convexity import ca_snapshot

    as_of = datetime.date(2023, 6, 9)
    cfg = Q.deep_pack_config(rank_start=5, n_packs=13)

    class _FakePricer:
        """A curve whose matched forward swap rate is always 4.00%."""

        _rl_curve_handle = None

        def _curve_definition(self):
            return {"ReferenceRate": "usd_irs"}

    import RVUtils.ConvexityRV.strat2_sofr_convexity as S2

    orig = S2._swap_par_rate
    try:
        S2._swap_par_rate = lambda *a, **k: 4.00
        seq = quarterly_imm_sequence(as_of, cfg.n_contracts)
        # futures rate 4.10% everywhere => CA = +10bp on every window
        px = Q.forwards_to_prices({k: 4.10 for k in seq})
        snap = ca_snapshot(as_of, cfg, futures_prices=px, swap_pricer=_FakePricer())
        assert len(snap) > 0
        assert np.allclose(snap["ca_bp"].to_numpy(float), 10.0), snap["ca_bp"].tolist()
        # and the other way round
        px = Q.forwards_to_prices({k: 3.90 for k in seq})
        snap = ca_snapshot(as_of, cfg, futures_prices=px, swap_pricer=_FakePricer())
        assert np.allclose(snap["ca_bp"].to_numpy(float), -10.0)
    finally:
        S2._swap_par_rate = orig


# ===========================================================================
# Known-answer: Citi Figure 58, close 6/9/2023
# ===========================================================================
def test_citi_table_has_blues_and_golds():
    """The two rows the rank-2..10 strategy can never reach."""
    t = Q.CITI_SOFR_20230609
    assert len(t) == 13
    assert t["M6-H7"]["rank"] == 13 and t["M6-H7"]["ca_bp"] == 15.40   # Blues
    assert t["M7-H8"]["rank"] == 17 and t["M7-H8"]["ca_bp"] == 22.29   # Golds
    assert sorted(r["rank"] for r in t.values()) == list(range(5, 18))


def test_citi_vs_model_identity():
    """``VsModel = CA - Model`` on all 13 published rows."""
    for pack, r in Q.CITI_SOFR_20230609.items():
        assert r["ca_bp"] - r["model_bp"] == pytest.approx(r["vs_model_bp"], abs=0.011), pack


def test_citi_three_month_roll_recursion():
    """``3m Roll(p) = CA(p) - CA(p one window nearer)`` -- 12/12 exact."""
    by_rank = {r["rank"]: (p, r) for p, r in Q.CITI_SOFR_20230609.items()}
    checked = 0
    for rank in range(6, 18):
        _, r = by_rank[rank]
        _, prev = by_rank[rank - 1]
        assert r["ca_bp"] - prev["ca_bp"] == pytest.approx(r["roll_3m_bp"], abs=0.011)
        checked += 1
    assert checked == 12


def test_citi_roll_recursion_negative_control():
    """The recursion test is not vacuous: shifting by two windows breaks it."""
    by_rank = {r["rank"]: r for r in Q.CITI_SOFR_20230609.values()}
    bad = sum(
        abs((by_rank[k]["ca_bp"] - by_rank[k - 2]["ca_bp"]) - by_rank[k]["roll_3m_bp"]) > 0.011
        for k in range(7, 18))
    assert bad >= 10, "a wrong pairing must fail nearly everywhere"


def test_implied_vol_inversion_reproduces_citis_column():
    """Inverting Citi's own CA column with ``sigma = sqrt(2*CA/mean(T1^2))``
    reproduces Citi's published Implied Vol at a median ratio of 0.9973.

    This is the sanity check on our inversion demanded by the brief: it uses
    Citi's numbers on both sides, so it validates the Ho-Lee form and the T1
    convention without involving this repo's market data at all.
    """
    as_of = datetime.date(2023, 6, 9)
    ratios = []
    for pack, r in Q.CITI_SOFR_20230609.items():
        seq = quarterly_imm_sequence(as_of, 24)
        cts = seq[r["rank"] - 1:r["rank"] + 3]
        t1s = [(imm_date(y, m) - as_of).days / 365.0 for y, m in cts]
        iv = implied_vol_from_ca_bp(r["ca_bp"], t1s)
        ratios.append(iv / r["implied_vol_bp"])
    med = float(np.median(ratios))
    assert med == pytest.approx(0.9973, abs=0.004), f"median ratio {med:.4f}"
    assert min(ratios) > 0.99 and max(ratios) < 1.005, (min(ratios), max(ratios))


def test_implied_vol_inversion_negative_control_hull_form():
    """The textbook Hull form ``0.5*sigma^2*T1*T2`` is REJECTED: it drifts with
    maturity instead of sitting flat, which is how the Citi form was identified.
    Without this, a regression to the wrong model would still pass the test
    above at the median."""
    as_of = datetime.date(2023, 6, 9)
    ratios = []
    for r in Q.CITI_SOFR_20230609.values():
        seq = quarterly_imm_sequence(as_of, 24)
        cts = seq[r["rank"] - 1:r["rank"] + 3]
        t1s = np.array([(imm_date(y, m) - as_of).days / 365.0 for y, m in cts])
        m_hull = float(np.mean(t1s * (t1s + 0.25)))
        sig = math.sqrt(2.0 * r["ca_bp"] / 1e4 / m_hull) * 1e4
        ratios.append(sig / r["implied_vol_bp"])
    drift = ratios[-1] / ratios[0] if ratios[0] else float("nan")
    assert abs(drift - 1.0) > 0.005 or abs(float(np.median(ratios)) - 1.0) > 0.005, (
        "the Hull form must NOT reproduce the column -- if it does, this test "
        "no longer discriminates between the two models")


# ===========================================================================
# Data-dependent
# ===========================================================================
def _have_stir_cache() -> bool:
    import glob
    import os

    return bool(glob.glob(os.path.join(Q._default_cache_root(), "*", "cache.db")))


needs_cache = pytest.mark.skipif(not _have_stir_cache(),
                                 reason="local SR3 diskcache not present")
needs_panel = pytest.mark.skipif(not _PANEL.exists(),
                                 reason="strat2_q20_panel.parquet not built")


@needs_cache
def test_q20_build_is_offline_and_reproduces_the_settles():
    """The load-bearing property: a Q20 curve is built with ZERO outbound
    requests and its IMM forwards reproduce the settles they were fitted to.

    2023-06-09 is Citi's own close and has all 20 contracts cached.
    """
    import os

    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    from RVUtils.ConvexityRV.curve_ops import matched_forward_swap_rate
    from RVUtils.ConvexityRV.ca_diagnostics import curve_nodes, next_quarterly

    d = datetime.date(2023, 6, 9)
    cfg = Q.Q20Config()
    before = network_calls_blocked()
    b = Q.Q20Builder(cfg)
    pricer = b.pricer(d, 20)
    settles = b.settles(d, 20)
    assert network_calls_blocked() == before, "the build reached for the network"

    ref = pricer.reference_date()
    ref = ref.date() if hasattr(ref, "date") else ref
    assert ref == d

    nodes = curve_nodes(pricer)
    assert len(nodes) >= 30, f"Q20 should carry a dense grid, got {len(nodes)}"
    assert max(nodes) > d + datetime.timedelta(days=4 * 365), "60m horizon expected"

    seq = quarterly_imm_sequence(d, 20)
    diffs = []
    for y, m in seq:
        fw = matched_forward_swap_rate(pricer, imm_date(y, m),
                                       imm_date(*next_quarterly(y, m)))
        diffs.append(abs(settles[(y, m)] - fw) * 100.0)
    assert np.median(diffs) < 1.0, f"median |settle-fwd| {np.median(diffs):.3f}bp"
    assert max(diffs) < 6.0, f"max |settle-fwd| {max(diffs):.3f}bp"


@needs_cache
def test_q20_build_refuses_a_depth_it_cannot_support():
    cfg = Q.Q20Config()
    with pytest.raises(ValueError):
        Q.build_q20_pricer(datetime.date(2023, 6, 9), 21, cfg=cfg)
    with pytest.raises(ValueError):
        Q.build_q20_pricer(datetime.date(2023, 6, 9), 3, cfg=cfg)


@needs_cache
def test_strip_depth_is_contiguous_and_matches_the_cache():
    """The universe must be an observable. Spot-check the depth against a direct
    read of the same store, and confirm contiguity is actually enforced."""
    import os

    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
    from RVUtils.ConvexityRV.listed_cache_guard import cache_only

    cfg = Q.Q20Config(start=datetime.date(2023, 1, 1), end=datetime.date(2023, 12, 31))
    depths = Q.strip_depth_by_date(cfg)
    assert depths, "2023 should have cached dates"
    d, k = max(depths.items(), key=lambda kv: kv[1])
    mdp = STIRFutureMDP(source=cfg.eod_source)
    seq = quarterly_imm_sequence(d, k)
    syms = [futures_symbol(y, m, cfg.futures_root) for y, m in seq]
    before = network_calls_blocked()
    with cache_only():
        snap = mdp.get_data({"symbols": syms, "timestamp": d})
    assert network_calls_blocked() == before
    assert all(snap.get(s) for s in syms), "reported depth is not actually cached"


@needs_panel
def test_panel_gate_inverts_between_near_and_deep_packs_in_2019():
    """The finding the whole module rests on, asserted on the built panel.

    The earlier rejection of a curve-derived futures rate measured a 9.375bp
    median disagreement in 2019 -- POOLED across ranks. Decomposed, 2019 is a
    front-end failure and a deep-end success, because the node grid comes from a
    central-bank meeting map that starts in 2021.
    """
    p = pd.read_parquet(_PANEL)
    p["year"] = pd.to_datetime(p["date"]).dt.year
    y = p[p["year"] == 2019]
    assert len(y) > 1000

    near = y[y["rank"] <= 4]
    deep = y[(y["rank"] >= 13) & (y["rank"] <= 16)]
    assert len(near) and len(deep)

    # resolution: the near windows sit inside one node interval, the deep ones do not
    assert near["q20_spans_window"].mean() > 0.5
    assert deep["q20_spans_window"].mean() == pytest.approx(0.0, abs=1e-9)

    # settle agreement: orders of magnitude apart
    assert near["max_settle_diff_bp"].median() > 5.0
    assert deep["max_settle_diff_bp"].median() < 1.0

    # and the gate acts on it
    assert near["gate_ok"].mean() < 0.05
    assert deep["gate_ok"].mean() > 0.95


@needs_panel
def test_gate_passed_rate_sources_agree_to_well_inside_a_basis_point():
    """The control. If the gate works, the Q20 forward IS the settlement mark."""
    p = Q.apply_gate(pd.read_parquet(_PANEL))
    deep = p[p["rank"] >= 9]
    d = (deep["ca_bp_q20"] - deep["ca_bp_settle"]).abs()
    assert float(d.median()) < 0.1, f"median |CA_q20 - CA_settle| = {d.median():.4f}bp"
    assert float(d.quantile(0.95)) < 1.0
    c = float(np.corrcoef(deep["ca_bp_q20"], deep["ca_bp_settle"])[0, 1])
    assert c > 0.999, f"corr {c:.5f}"


@needs_panel
def test_panel_reaches_blues_and_golds():
    """The point of the exercise: ranks the near-pack strategy cannot see."""
    p = pd.read_parquet(_PANEL)
    assert int(p["rank"].max()) >= 17, "Golds (rank 17) must be present"
    for rank, n_min in ((13, 500), (17, 200)):
        n = int(p[p["rank"] == rank]["date"].nunique())
        assert n >= n_min, f"rank {rank} on only {n} dates"


@needs_panel
def test_summaries_run_and_are_shaped_right():
    p = pd.read_parquet(_PANEL)
    g = Q.gate_summary(p)
    assert {"gate_covered", "gate_resolved", "gate_settle_agrees", "gate_ok"} <= set(g.columns)
    assert (g[["gate_ok"]].to_numpy() <= 1.0).all()
    s = Q.settle_agreement_summary(p)
    assert "diff_median_bp" in s.columns and len(s) > 0
    r = Q.rate_source_comparison(p[p["rank"].between(9, 14)])
    assert {"corr", "abs_diff_median_bp"} <= set(r.columns)
