r"""Known-answer tests for the Fedspeak-detachment study.

Three jobs.

The ordinary one: contract selection, cost arithmetic and the trade schedule
must be what they claim.

The one that earns its keep: every construction must be computable in real time,
and the direction convention must survive ``STIRFutureQuery``'s documented sign
trap. Both are pinned against known answers rather than against themselves.

And the third: two defects found while building this are pinned so they cannot
come back. Ranking a grid on ``|Sharpe|`` picks the reading a costed flip made
WORSE, because with a round trip charged both ways ``follow`` is not ``-fade``.
And a USD SOFR par rate of 67 is swaption vol, not a rate -- the shared tag cache
serves that on 47% of its rows, and two studies already on ``main`` regressed
against it.
"""
from __future__ import annotations

import dataclasses
import datetime
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO), str(REPO / "notebooks" / "rv")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_detachment_data as D  # noqa: E402
import fed_detachment_grid as G  # noqa: E402
import fed_detachment_prices as PX  # noqa: E402


# ------------------------------------------------------------------ contracts
def test_rank_three_on_the_handover_date_is_SFRH27():
    """The handover names SR3H27 as the 3rd deferred on 2026-08-20. It is."""
    assert PX.rank_symbol(datetime.date(2026, 8, 20), 3) == "SR3H27"
    assert PX.rank_symbol(datetime.date(2026, 8, 20), 1) == "SR3U26"
    assert PX.rank_symbol(datetime.date(2026, 8, 20), 2) == "SR3Z26"


def test_rank_one_is_the_contract_whose_quarter_has_not_started():
    """The desk convention: a started contract is partially fixed and is not front."""
    # 2026-09-16 IS the third Wednesday of September
    assert PX.rank_symbol(datetime.date(2026, 9, 15), 1) == "SR3U26"
    assert PX.rank_symbol(datetime.date(2026, 9, 16), 1) == "SR3Z26"


def test_no_rank_contract_can_expire_inside_the_longest_hold():
    """The claim that makes this study roll-free, checked on every week for a decade.

    Rank 1 selected at ``t`` starts at the next IMM and runs a further quarter,
    so its expiry is never nearer than about thirteen weeks. The longest holding
    period in the grid is eight. If that ever stopped being true, every P&L here
    would silently start differencing two contracts -- and 22 of 33 SR3 rolls are
    FOMC decision dates, so the jump would be correlated with the signal.
    """
    worst = 10_000
    for t in pd.date_range("2018-01-01", "2027-12-31", freq="W-FRI"):
        for rank in (1, 2, 3, 4):
            sym = PX.rank_symbol(t.date(), rank)
            days = (PX.contract_window(sym).end - t.date()).days
            worst = min(worst, days)
    assert worst > max(D.HORIZONS_W) * 7, (
        f"a rank contract expired {worst} days after selection, inside the "
        f"{max(D.HORIZONS_W)}-week horizon")


def test_merge_history_never_shrinks_a_cached_series():
    """A Barchart answer that comes back short must cost nothing."""
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    old = pd.DataFrame({"Close": np.arange(10.0)}, index=idx)
    short = pd.DataFrame({"Close": [99.0]}, index=idx[-1:])
    merged = PX.merge_history(old, short)
    assert len(merged) == 10
    assert merged["Close"].iloc[-1] == 99.0      # new wins where both have a row
    assert merged["Close"].iloc[0] == 0.0        # and nothing is lost


def test_gate_contract_history_catches_a_short_parquet(monkeypatch):
    idx = pd.date_range("2026-01-02", periods=5, freq="B")
    monkeypatch.setattr(PX, "load_local",
                        lambda s: pd.DataFrame({"Close": np.ones(5)}, index=idx))
    out = PX.gate_contract_history(["SR3U26"], {"SR3U26": pd.Timestamp("2025-09-19")})
    assert not bool(out["ok"].iloc[0])
    assert out["short_by_days"].iloc[0] > 100


# ------------------------------------------------------------------ the rate
def test_par_rate_from_nodes_ties_out_to_the_recorded_curve_reprice():
    """Known answer: 2026-08-14, CurveStore repriced 2Y to 4.02995.

    Recorded in ``project_citivelo_tagcache_vol_poison``, which used it to show
    the tag cache -- serving 67.1 that week -- was the wrong side. Rebuilding the
    par rate from the stored discount factors has to land on it.
    """
    import pyarrow.dataset as pads

    root = PX.CURVE_STORE_ASSET / "date=2026-08-14"
    if not root.exists():
        pytest.skip("curve store not warmed on this machine")
    row = pads.dataset(str(root), format="parquet").to_table().to_pandas().iloc[0]
    par = PX._par_from_nodes(row["node_dates"], row["discount_factors"],
                             pd.Timestamp("2026-08-14"), 2)
    assert abs(par - 4.02995) < 0.01, f"2y par came out {par:.5f}, expected ~4.02995"


def test_gate_rate_sanity_rejects_swaption_vol():
    """67 is not a USD SOFR par rate. This is the check whose absence cost two studies."""
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    good = pd.Series([4.0, 4.1, 4.2, 4.15, 4.05], index=idx)
    PX.gate_rate_sanity(good)                       # must not raise
    poisoned = good.copy()
    poisoned.iloc[2] = 67.1
    with pytest.raises(AssertionError, match="outside"):
        PX.gate_rate_sanity(poisoned)


# ------------------------------------------------------------------ detachment
def _toy_sides(n=200, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-07", periods=n, freq="W-FRI")
    zc = pd.Series(np.cumsum(rng.normal(size=n)) * 0.1, index=idx)
    zs = pd.Series(np.cumsum(rng.normal(size=n)) * 0.1, index=idx)
    return zc, zs


@pytest.mark.parametrize("construction", D.CONSTRUCTIONS)
@pytest.mark.parametrize("k", D.LEAD_KS)
def test_every_construction_is_computable_in_real_time(construction, k):
    """G-D1 on the whole cross-product: truncation after t cannot move D at t."""
    zc, zs = _toy_sides()
    cfg = dataclasses.replace(D.PRIMARY, construction=construction, lead_k=k,
                              sent_z_min_w=12, reg_window_w=52, rank_window_w=52)
    probes = zs.index[[120, 150, 180]]
    out = D.gate_trailing_detachment(zc, zs, cfg, probe_dates=probes)
    assert len(out) == 3


def test_gate_trailing_detachment_actually_catches_a_leak():
    """The gate must fail on something. A full-sample z is the thing it is for."""
    zc, zs = _toy_sides()
    cfg = dataclasses.replace(D.PRIMARY, construction="gap", lead_k=0)

    def leaky(a, b, c):
        # standardise on the WHOLE sample -- knowable only at the end
        return ((b - b.mean()) / b.std()) - ((a - a.mean()) / a.std())

    real = D.detachment
    D.detachment = leaky
    try:
        with pytest.raises(AssertionError, match="G-D1 FAILED"):
            D.gate_trailing_detachment(zc, zs, cfg, probe_dates=zs.index[[120, 150]])
    finally:
        D.detachment = real


def test_positive_detachment_means_fedspeak_is_the_hawkish_side():
    """The sign convention every trade in the study depends on."""
    idx = pd.date_range("2024-01-05", periods=60, freq="W-FRI")
    zc = pd.Series(np.full(60, -1.0), index=idx)     # the data is soft
    zs = pd.Series(np.full(60, +1.0), index=idx)     # the Fed is hawkish
    d = D.detachment(zc, zs, dataclasses.replace(D.PRIMARY, construction="gap", lead_k=0))
    assert (d.dropna() > 0).all()


# ------------------------------------------------------------------ costs
def test_cost_is_per_contract_not_per_leg():
    """0.25bp one-way per CONTRACT: outright 0.50, calendar spread 1.00, pack 0.50.

    The pack is four contracts and four times the risk, so per unit of gross
    risk it costs the same as an outright. Only the spread -- two contracts
    against one basis point of quote -- is genuinely dearer.
    """
    def rt(structure):
        return dataclasses.replace(D.PRIMARY, structure=structure).cost_bp_round_trip()

    assert rt("out3") == pytest.approx(0.50)
    assert rt("spr2x4") == pytest.approx(1.00)
    assert rt("pack1") == pytest.approx(0.50)


def test_price_book_refuses_a_non_futures_structure():
    cfg = dataclasses.replace(D.PRIMARY, structure="ois2y")
    with pytest.raises(ValueError, match="not an SR3 structure"):
        D.price_book(pd.DataFrame([{"entry_date": pd.Timestamp("2025-01-06"),
                                    "exit_date": pd.Timestamp("2025-02-03"),
                                    "side": 1}]), pd.DataFrame(), cfg)


# ------------------------------------------------------------------ scheduling
def _sessions(start="2024-01-01", n=800):
    return np.asarray(pd.bdate_range(start, periods=n).values, dtype="datetime64[ns]")


def test_the_fill_is_the_NEXT_session_not_the_signal_session():
    """Filling on the session the signal was read from harvests mark noise."""
    idx = pd.date_range("2024-01-05", periods=40, freq="W-FRI")
    d = pd.Series(np.where(np.arange(40) % 8 == 0, 3.0, 0.0), index=idx)
    cfg = dataclasses.replace(D.PRIMARY, threshold=1.0, horizon_w=4)
    t = D.schedule(d, cfg, _sessions())
    assert len(t) > 0
    assert (pd.to_datetime(t["entry_date"]) > pd.to_datetime(t["signal_date"])).all()
    same = D.schedule(d, dataclasses.replace(cfg, entry_lag_sessions=0), _sessions())
    assert (pd.to_datetime(same["entry_date"]) <= pd.to_datetime(same["signal_date"])).all()


def test_trades_do_not_overlap():
    idx = pd.date_range("2024-01-05", periods=120, freq="W-FRI")
    rng = np.random.default_rng(4)
    d = pd.Series(rng.normal(size=120) * 2.0, index=idx)
    cfg = dataclasses.replace(D.PRIMARY, threshold=0.5, horizon_w=4)
    t = D.schedule(d, cfg, _sessions())
    assert len(t) > 5
    ex = pd.to_datetime(t["exit_date"]).to_numpy()
    en = pd.to_datetime(t["entry_date"]).to_numpy()
    assert (en[1:] >= ex[:-1]).all(), "a trade opened before the previous one closed"


# ------------------------------------------------------------------ the grid
def test_best_of_both_does_not_pick_the_reading_the_flip_made_worse():
    """The defect this pins cost the first pass of the grid its whole league table.

    Costs are paid whichever way round the trade goes, so ``follow`` is
    ``-(p + cost) - cost`` and NOT ``-p``. Ranking on ``|Sharpe|`` therefore
    reports whichever magnitude is larger, which for a cell whose gross edge is
    small against its cost is the LOSING reading. Constructed here so that the
    two readings lose 0.1bp and 3.9bp a trade: neither should win, and the one
    that is reported must be the better of the two.
    """
    n = 60
    d = np.ones(n)                       # always long, always above threshold
    r = np.full(n, 1.9)                  # gross +1.9bp; cost 2.0bp round trip
    cost = 2.0
    sr, sign, idx, p = G.best_of_both(d, r, threshold=0.5, horizon=1, cost_bp=cost,
                                      n_weeks=n, min_trades=8)
    assert sign == 1, "the better reading is fade (-0.1bp), not follow (-3.9bp)"
    assert p.mean() == pytest.approx(-0.1)
    flipped = -(p + cost) - cost
    assert flipped.mean() == pytest.approx(-3.9)
    assert abs(flipped.mean()) > abs(p.mean()), (
        "the constructed case must be one where |flipped| is the bigger number, "
        "otherwise this test cannot catch the bug it exists for")


def test_grid_statistic_agrees_with_the_league_it_summarises():
    """Two code paths compute the same maximum; they must not drift apart."""
    n = 160
    rng = np.random.default_rng(11)
    weeks = pd.date_range("2023-01-06", periods=n, freq="W-FRI")
    bank = {(c, k): pd.Series(rng.normal(size=n), index=weeks)
            for c in ("gap", "dchg") for k in (0, 2)}
    rb = {(s, h): rng.normal(scale=10.0, size=n)
          for s in ("out3", "spr2x4") for h in (1, 4)}
    keys = G.cell_keys(constructions=("gap", "dchg"), ks=(0, 2), thresholds=(0.0, 1.0),
                       horizons=(1, 4), structures=("out3", "spr2x4"))
    league, dmat, _s, keys, key_row, _b = G.run_grid(bank, rb, weeks, D.PRIMARY, keys=keys)
    obs, best, _ = G.grid_statistic(dmat, keys, key_row, rb, D.PRIMARY)
    assert obs == pytest.approx(float(league["sharpe"].max()))
    assert keys[best][0] == league.iloc[int(league["sharpe"].idxmax())]["construction"]


def test_rotation_offsets_exclude_every_alignment_the_grid_can_reach():
    """min_offset > 2*(max k + max horizon), or the surrogate matches the truth.

    ``reference_rotation_null_self_match``: at the obvious bound the rotation's
    own scan window still contains the real alignment, the surrogate reproduces
    the observed statistic exactly, and the p-value stops measuring effect size.
    """
    off = G.rotation_offsets(200, max_k=11, max_h=8)
    assert off.min() == 39
    assert off.max() == 200 - 39 - 1
    assert G.rotation_offsets(80, 11, 8).size == 0, "too short to rotate safely"


def test_book_sharpe_carries_trade_frequency_and_per_trade_sharpe_does_not():
    """Why the grid ranks on the weekly book and not on the per-trade number."""
    n = 208
    rare_idx, rare_p = np.arange(0, n, 26), np.full(8, 1.0)
    often_idx, often_p = np.arange(0, n, 4), np.full(52, 1.0)
    # identical per-trade P&L, wildly different books
    assert G.book_sharpe(often_idx, often_p, n) > 2 * G.book_sharpe(rare_idx, rare_p, n)


def test_sign_flip_null_finds_a_real_edge_and_clears_a_fake_one():
    rng = np.random.default_rng(2)
    real = rng.normal(loc=1.0, scale=1.0, size=120)
    fake = rng.normal(loc=0.0, scale=1.0, size=120)
    assert G.sign_flip_pvalue(real, draws=4000, rng=np.random.default_rng(1))["p"] < 0.01
    assert G.sign_flip_pvalue(fake, draws=4000, rng=np.random.default_rng(1))["p"] > 0.05


def test_episode_stats_sees_one_disagreement_as_one_episode():
    """A run of same-side trades close together is one bet, not six."""
    idx = np.arange(0, 24, 4)
    sides = np.ones(6)
    pnl = np.full(6, 2.0)
    out = G.episode_stats(idx, sides, pnl, gap_weeks=8)
    assert out["episodes"] == 1
    assert out["top_episode_share"] == pytest.approx(1.0)
    flipping = np.tile([1.0, -1.0], 3)
    assert G.episode_stats(idx, flipping, pnl, gap_weeks=8)["episodes"] == 6


# ------------------------------------------------------------------ the engine
@pytest.mark.slow
def test_engine_direction_and_tie_out():
    """G-E1 and G-E2 against the real MDP, on the pre-registered book."""
    import fed_detachment_engine as E

    cfg = D.PRIMARY
    zc, zs, _ = D.load_sides(cfg)
    bank = G.build_signal_bank(zc, zs, cfg)
    sup = G.common_support(bank)
    syms = PX.sr3_universe(sup.min().date(),
                           sup.max().date() + pd.Timedelta(weeks=12), 4)
    panel = PX.settle_panel(syms)
    sessions = np.asarray(pd.DatetimeIndex(panel.index).values, dtype="datetime64[ns]")
    d = bank[(cfg.construction, cfg.lead_k)].reindex(sup)
    book, _reasons = D.price_book(D.schedule(d, cfg, sessions), panel, cfg)
    assert len(book) > 10

    mdp = E.open_mdp()
    first = book.iloc[0]
    E.gate_direction(panel, first["symbols"], first["entry_date"],
                     first["exit_date"], mdp=mdp)
    tie = E.tie_out(book, E.replay(book, panel, mdp=mdp))
    E.gate_engine_tie_out(tie)


def test_negative_contracts_are_refused_outright():
    """The trap is not worked around, it is made impossible to express."""
    import fed_detachment_engine as E

    with pytest.raises(ValueError, match="must be POSITIVE"):
        E._query("SR3H27", -1.0, "t", contracts=-1)


def test_thin_cells_are_not_counted_as_deflation_trials():
    """A cell too thin to win the grid is not a trial.

    ``grid_statistic`` scores a cell with fewer than ``min_trades`` trades NaN,
    so it can never be selected. Feeding it to the deflation anyway inflates N
    and with it the SR0 the winner has to clear -- and when the result is a
    NULL, that makes the null look better established than it is. Measured on
    the real JPM grid before the fix: 264 of 2048 cells were that thin, and the
    deflation counted 4032 trials where the grid could select from 3568.
    """
    n = 200
    rng = np.random.default_rng(5)
    weeks = pd.date_range("2022-01-07", periods=n, freq="W-FRI")
    # a signal that clears a high threshold only a handful of times
    d = np.zeros(n)
    d[::40] = 5.0
    bank = {("gap", 0): pd.Series(d, index=weeks)}
    rb = {("out3", 1): rng.normal(scale=10.0, size=n)}
    keys = G.cell_keys(constructions=("gap",), ks=(0,), thresholds=(0.0, 1.0),
                       horizons=(1,), structures=("out3",))
    league, dmat, _s, keys, key_row, both = G.run_grid(bank, rb, weeks, D.PRIMARY,
                                                       keys=keys, min_trades=8)
    thin = league["trades"] < 8
    assert thin.any(), "the fixture must contain a thin cell for this to test anything"
    assert league.loc[thin, "sharpe"].isna().all()
    for j in np.flatnonzero(thin.to_numpy()):
        assert not both[j].any(), "a thin cell leaked into the deflation trial set"
        assert not both[len(keys) + j].any()


def test_the_deflation_and_the_grid_pick_the_same_winner():
    """Two code paths choose the best cell; they must not name different ones."""
    n = 180
    rng = np.random.default_rng(9)
    weeks = pd.date_range("2022-01-07", periods=n, freq="W-FRI")
    bank = {(c, k): pd.Series(rng.normal(size=n), index=weeks)
            for c in ("gap", "dchg") for k in (0, 2)}
    rb = {(s, h): rng.normal(scale=10.0, size=n)
          for s in ("out3", "spr2x4") for h in (1, 4)}
    keys = G.cell_keys(constructions=("gap", "dchg"), ks=(0, 2), thresholds=(0.0, 1.0),
                       horizons=(1, 4), structures=("out3", "spr2x4"))
    league, dmat, _s, keys, key_row, both = G.run_grid(bank, rb, weeks, D.PRIMARY,
                                                       keys=keys)
    obs, _best, _ = G.grid_statistic(dmat, keys, key_row, rb, D.PRIMARY)
    dfl = G.deflate(both, league)
    assert dfl["best_sharpe"] == pytest.approx(obs), (
        "the deflation is ranking on a different statistic from the grid")


def test_romano_wolf_rank_one_equals_the_rotation_p_value():
    """The family test and the max test must agree where they overlap.

    With the FULL family, the stepdown's first suffix maximum is the grid
    maximum, so the rank-1 adjusted p is the rotation p by construction. If they
    diverge, the family has been subset -- which is exactly the defect this
    pins: choosing the tested set with the observed Sharpes shrinks every suffix
    maximum and quietly destroys familywise control.
    """
    rng = np.random.default_rng(17)
    m, M = 40, 60
    obs = rng.normal(size=m)
    null = rng.normal(size=(M, m))
    fam = G.family_test(obs, {"cell_sharpes": null},
                        pd.DataFrame({"construction": ["c"] * m, "lead_k": [0] * m,
                                      "threshold": [0.0] * m, "horizon_w": [1] * m,
                                      "structure": ["s"] * m, "sign": ["fade"] * m}))
    rot = G.rotation_pvalue(float(np.nanmax(obs)),
                            {"max_abs_sharpe": null.max(axis=1)})
    assert fam["rank1_adjusted_p"] == pytest.approx(rot)


def test_family_test_is_anti_conservative_if_the_family_is_subset(monkeypatch):
    """And the defect it pins is real: show subsetting makes the p SMALLER."""
    from RVUtils.StatisticalFinance.family import romano_wolf

    rng = np.random.default_rng(23)
    m, M = 200, 80
    obs = rng.normal(size=m)
    null = rng.normal(size=(M, m))
    order = np.argsort(-obs)
    full = romano_wolf(obs, null).table["p_adjusted"].iloc[0]
    top = order[:20]
    subset = romano_wolf(obs[top], null[:, top]).table["p_adjusted"].iloc[0]
    assert subset < full, (
        "subsetting the family by observed rank must lower the adjusted p -- if "
        "it does not on this fixture the test cannot catch the defect")


def test_trailing_rank_ignores_the_NaN_prefix_it_is_reindexed_onto():
    """A rank must not count NaN slots as observations it failed to beat.

    Both sides arrive at ``detachment`` reindexed onto a union index -- the
    surprise composite runs from 2005, the sentiment index from 2023 -- so every
    window straddling the start of the shorter series is part real, part NaN.
    Counting those slots compresses the rank toward -1 for a full window's worth
    of weeks. On a strictly RISING series every observation is by construction
    the top of its own window and must score +1.0; the broken version returned
    -0.02 on all 25 affected weeks, the opposite end of the range.
    """
    idx = pd.date_range("2023-01-06", periods=80, freq="W-FRI")
    rising = pd.Series(np.arange(80, dtype=float), index=idx)
    with_gap = rising.copy()
    with_gap.iloc[:30] = np.nan

    clean = D._trailing_rank(rising, 52, 26).dropna()
    gapped = D._trailing_rank(with_gap, 52, 26).dropna()
    assert np.allclose(clean.to_numpy(), 1.0), "a rising series must rank +1 everywhere"
    assert np.allclose(gapped.to_numpy(), 1.0), (
        "the NaN prefix changed the rank -- the denominator is counting NaN slots")
    # and the two agree wherever both are defined
    both = pd.concat([clean.rename("a"), gapped.rename("b")], axis=1).dropna()
    assert len(both) > 20
    assert float((both["a"] - both["b"]).abs().max()) < 1e-12


def test_rankgap_is_unchanged_by_NaN_PADDING_the_sentiment_side():
    """The end-to-end version of the same invariant.

    ``detachment`` puts both sides on a union index, so the shorter series --
    the sentiment index -- acquires a long NaN prefix. Extending that prefix
    must not change D anywhere: NaN is absence of data, not data.

    Note what this does NOT assert. Truncating the COMPOSITE's real history does
    legitimately change its own trailing rank, because a rank is a statement
    about the observations in the window and there are then fewer of them. That
    is the statistic working, not a defect, and an invariance test over it would
    be wrong.
    """
    idx = pd.date_range("2022-01-07", periods=200, freq="W-FRI")
    rng = np.random.default_rng(3)
    zc = pd.Series(np.cumsum(rng.normal(size=200)) * 0.1, index=idx)
    zs = pd.Series(np.cumsum(rng.normal(size=120)) * 0.1, index=idx[-120:])
    cfg = dataclasses.replace(D.PRIMARY, construction="rankgap", lead_k=0)

    padded = zs.reindex(idx)                       # explicit leading NaN
    a = D.detachment(zc, zs, cfg)
    b = D.detachment(zc, padded, cfg)
    both = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    assert len(both) > 30
    assert float((both["a"] - both["b"]).abs().max()) < 1e-12, (
        "extending the sentiment side's NaN prefix moved D -- the rank is "
        "reading its own padding")
