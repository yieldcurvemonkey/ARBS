"""``<LABEL>_MODEL`` on ``IRSwapsTB.sfr_cvx_adj`` -- the Ho-Lee model level.

Every test here is hermetic: a fake MDP (the model path never prices a curve),
an in-memory cache mapping, and an injected volatility provider. The tie-outs
that need the machine's swaption cube -- the incumbent ``VOL_BENCH`` map, the
block-5 screen, the byte-identity of the observed path -- live in
``notebooks/backtests/convexity_rv/_hl_verify.py``, because a unit test that
skips when a local store is missing is a test that measures nothing on CI.
"""
from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

from MDP.MarketDataProvider import MarketDataProvider
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp, pack_ca_bp
from TB import IRSwapsTB as M
from TB.IRSwapsTB import IRSwapsTB, _query_fingerprint

START, END = "2025-06-02", "2025-06-13"
SIGMA = 95.0


class _FakeMDP(MarketDataProvider):
    """The model path never asks the MDP for anything; this proves it."""

    def __init__(self, source: str = "TEST_HOLEE"):
        super().__init__(source=source)
        self.calls = 0

    def get_pricer(self, request: Dict[str, Any]) -> Any:
        self.calls += 1
        raise AssertionError("the model path must not price a curve")

    def bulk_get_data(self, request: Dict[str, Any]) -> Dict[Any, Any]:
        self.calls += 1
        raise AssertionError("the model path must not fetch market data")


def _tb() -> IRSwapsTB:
    tb = IRSwapsTB(_FakeMDP(), show_tqdm=False, use_duckdb=False)
    setattr(tb, tb._cache_attr, {})          # in-memory L1, nothing on disk
    return tb


def _fixed(sigma: float = SIGMA):
    def _p(_as_of, _t1_mean):
        return sigma
    return _p


# ---------------------------------------------------------------------------
# 1. the label grammar
# ---------------------------------------------------------------------------
def test_model_base_splits_the_suffix():
    assert M._cvx_model_base("BLUES_MODEL") == ("BLUES", True)
    assert M._cvx_model_base("  blues_model ") == ("BLUES", True)
    assert M._cvx_model_base("BLUES") == ("BLUES", False)
    assert M._cvx_model_base("SFR9_MODEL") == ("SFR9", True)
    assert M._cvx_model_base("BUNDLE5Y_MODEL") == ("BUNDLE5Y", True)


def test_a_bare_suffix_is_not_a_model_label():
    """``_MODEL`` alone has no base; it must not become the empty structure."""
    assert M._cvx_model_base("_MODEL") == ("_MODEL", False)


def test_the_tag_strips_the_suffix_but_the_RESOLVERS_DO_NOT():
    """The safety property behind the intraday refusal.

    ``_cvx_structure_tag`` is presentational and may strip. Every helper that
    resolves a label to CONTRACTS must stay suffix-blind, because
    ``sfr_cvx_adj_intraday`` shares this vocabulary -- if it could resolve
    ``BLUES_MODEL`` it would serve the OBSERVED intraday adjustment under a
    model name.
    """
    assert M._cvx_structure_tag("BLUES_MODEL") == "PACKS"
    assert M._cvx_structure_tag("BUNDLE5Y_MODEL") == "BUNDLES"
    assert M._cvx_structure_tag("SFR9_MODEL") == "OUTRIGHT"

    assert M._cvx_ranks_for_label("BLUES_MODEL") is None
    assert M._cvx_pack_span("BLUES_MODEL") is None
    assert M._cvx_cm_rank("SFR9_MODEL") is None
    assert not M._cvx_is_imm("H26_MODEL")
    # ...and they still resolve the base
    assert M._cvx_ranks_for_label("BLUES") == [13, 14, 15, 16]


def test_the_column_name_carries_the_model_label_and_the_right_tag():
    assert (M._cvx_col_name("USD-SOFR-1D", "BLUES_MODEL")
            == "USD-SOFR-1D BLUES_MODEL PACKS CVX_ADJ")
    assert (M._cvx_col_name("USD-SOFR-1D", "BLUES")
            == "USD-SOFR-1D BLUES PACKS CVX_ADJ")


def test_expiry_years_parses_every_unit_and_refuses_junk():
    assert M._cvx_expiry_years("3M") == pytest.approx(0.25)
    assert M._cvx_expiry_years("18M") == pytest.approx(1.5)
    assert M._cvx_expiry_years("1Y") == pytest.approx(1.0)
    assert M._cvx_expiry_years("10Y") == pytest.approx(10.0)
    assert M._cvx_expiry_years(" 6m ") == pytest.approx(0.5)
    with pytest.raises(ValueError):
        M._cvx_expiry_years("ATM")


# ---------------------------------------------------------------------------
# 2. the cache identity -- the one bug that would be invisible
# ---------------------------------------------------------------------------
def _q(value_kwargs):
    return IRSwapQuery(
        curve="USD-SOFR-1D",
        effective_date=datetime.date(2028, 3, 15),
        maturity_date=datetime.date(2029, 3, 21),
        structure=IRSwapStructure.OUTRIGHT,
        structure_kwargs={"bpv": 1},
        value=IRSwapValue.CVX_ADJ,
        value_kwargs=value_kwargs,
    )


def test_the_model_and_observed_queries_do_not_share_a_fingerprint():
    """They agree on effective date, maturity, value and structure_kwargs.

    Only ``cvx_model_value_kwargs`` separates them, and without it
    ``BLUES_MODEL`` would read AND OVERWRITE ``BLUES``'s observed adjustment
    with nothing raising.
    """
    observed = _q({"matched_frequency": "Q", "matched_leg2_frequency": "Q"})
    model = _q(M.cvx_model_value_kwargs(vol_source="swaption_cube"))
    assert _query_fingerprint(observed) != _query_fingerprint(model)

    # the hole: strip the marker and they DO collide, which is what makes the
    # assertion above a real test rather than a restatement
    assert _query_fingerprint(_q({"matched_frequency": "Q",
                                  "matched_leg2_frequency": "Q"})) == \
        _query_fingerprint(observed)


def test_the_model_spec_is_IN_the_fingerprint():
    """Changing the model must ORPHAN the old rows, not serve them."""
    a = _query_fingerprint(_q(M.cvx_model_value_kwargs(vol_source="swaption_cube")))
    for kw in (dict(vol_source="capfloor"),
               dict(vol_source="swaption_cube", vol_tenor="2Y"),
               dict(vol_source="swaption_cube", convention="hull"),
               dict(vol_source="swaption_cube", vol_interp="snap")):
        assert _query_fingerprint(_q(M.cvx_model_value_kwargs(**kw))) != a


# ---------------------------------------------------------------------------
# 3. the arithmetic
# ---------------------------------------------------------------------------
def test_model_ca_is_the_holee_form_and_matches_by_hand():
    t1s = [3.25, 3.5, 3.75, 4.0]
    got = M._cvx_model_ca_bp(120.0, t1s)
    hand = 120.0 ** 2 * float(np.mean(np.asarray(t1s) ** 2)) / 2e4
    assert got == pytest.approx(hand, rel=1e-12)
    assert got == pytest.approx(pack_ca_bp(120.0, t1s, convention="citi"))


def test_the_two_time_weight_conventions_are_not_the_same_number():
    t1s = [3.25, 3.5, 3.75, 4.0]
    citi = M._cvx_model_ca_bp(120.0, t1s, convention="citi")
    hull = M._cvx_model_ca_bp(120.0, t1s, convention="hull")
    assert hull > citi                       # T1*(T1+0.25) > T1^2
    assert abs(hull - citi) > 0.1


def test_the_model_inverts_back_to_its_own_vol():
    t1s = [2.0, 2.25, 2.5, 2.75]
    ca = M._cvx_model_ca_bp(SIGMA, t1s)
    assert implied_vol_from_ca_bp(ca, t1s, convention="citi") == pytest.approx(SIGMA)


def test_t1s_resolve_for_every_label_family():
    as_of = datetime.date(2025, 6, 2)
    pack = M._cvx_model_t1s(as_of, "BLUES_MODEL")
    assert len(pack) == 4
    assert pack == sorted(pack)
    assert 3.0 < pack[0] < 4.0
    assert len(M._cvx_model_t1s(as_of, "SFR9_MODEL")) == 1
    assert len(M._cvx_model_t1s(as_of, "BUNDLE5Y_MODEL")) == 20
    assert len(M._cvx_model_t1s(as_of, "SILVERS_MODEL")) == 4
    front = M._cvx_front_imm_code(as_of)
    assert len(M._cvx_model_t1s(as_of, f"{front}_MODEL")) == 1


def test_an_expired_imm_contract_gives_a_negative_t1():
    """The guard the method turns into a recorded failure rather than a price."""
    t1s = M._cvx_model_t1s(datetime.date(2025, 6, 2), "H20_MODEL")
    assert t1s[0] < 0.0


def test_an_unresolvable_base_raises_rather_than_returning_nothing():
    with pytest.raises(ValueError, match="does not resolve to any SR3 contracts"):
        M._cvx_model_t1s(datetime.date(2025, 6, 2), "NOTALABEL_MODEL")


# ---------------------------------------------------------------------------
# 4. the vol provider
# ---------------------------------------------------------------------------
def _stub_panel(monkeypatch, nodes):
    """``nodes`` = {(expiry, vol_bp)} for one date, as the cube would serve it."""
    d = datetime.date(2025, 6, 2)
    rows = [{"date": pd.Timestamp(d), "expiry": e, "tenor": "1Y",
             "offset_bp": 0.0, "vol_bp": v} for e, v in nodes]
    rows += [{"date": pd.Timestamp(d), "expiry": e, "tenor": "1Y",
              "offset_bp": 25.0, "vol_bp": v + 5.0} for e, v in nodes]

    import RVUtils.ConvexityRV.swaption_cube as sc
    monkeypatch.setattr(sc, "load_vol_panel",
                        lambda *a, **k: pd.DataFrame(rows))
    return d


def test_the_vol_is_interpolated_linearly_between_the_bracketing_nodes(monkeypatch):
    d = _stub_panel(monkeypatch, [("3Y", 100.0), ("4Y", 120.0)])
    p = M.cvx_model_vol_from_cube([d])
    assert p(d, 3.0) == pytest.approx(100.0)
    assert p(d, 4.0) == pytest.approx(120.0)
    assert p(d, 3.5) == pytest.approx(110.0)     # linear in T, not snapped
    assert p(d, 3.625) == pytest.approx(112.5)


def test_the_vol_clamps_flat_outside_the_ladder(monkeypatch):
    d = _stub_panel(monkeypatch, [("3Y", 100.0), ("4Y", 120.0)])
    p = M.cvx_model_vol_from_cube([d])
    assert p(d, 0.05) == pytest.approx(100.0)
    assert p(d, 30.0) == pytest.approx(120.0)


def test_only_the_atmf_offset_is_read(monkeypatch):
    """The stub carries a +25bp skew row at vol+5; reading it would show."""
    d = _stub_panel(monkeypatch, [("3Y", 100.0), ("4Y", 120.0)])
    assert M.cvx_model_vol_from_cube([d])(d, 3.0) == pytest.approx(100.0)


def test_a_date_the_cube_does_not_carry_returns_nan(monkeypatch):
    d = _stub_panel(monkeypatch, [("3Y", 100.0), ("4Y", 120.0)])
    p = M.cvx_model_vol_from_cube([d])
    assert np.isnan(p(datetime.date(1999, 1, 4), 3.0))


# ---------------------------------------------------------------------------
# 5. end to end through sfr_cvx_adj
# ---------------------------------------------------------------------------
def test_the_method_returns_the_hand_computed_model_level():
    tb = _tb()
    df = tb.sfr_cvx_adj(["BLUES_MODEL"], START, END,
                        model_vol_provider=_fixed())
    assert list(df.columns) == ["USD-SOFR-1D BLUES_MODEL PACKS CVX_ADJ"]
    assert len(df) > 5
    d0 = df.index[0].date()
    t1s = M._cvx_model_t1s(d0, "BLUES")
    hand = SIGMA ** 2 * float(np.mean(np.asarray(t1s) ** 2)) / 2e4
    assert float(df.iloc[0, 0]) == pytest.approx(hand, rel=1e-12)
    assert tb.mdp.calls == 0, "the model path priced a curve"


def test_the_vol_is_requested_at_the_structures_MEAN_expiry():
    """A constant provider cannot see where it was asked.

    Every other end-to-end test here injects a FIXED vol, so none of them
    notices which expiry the model reads it at -- the mutation harness found
    exactly that, by replacing ``mean(t1s)`` with ``t1s[0]`` and surviving. A
    T1-sensitive provider closes it: Ho-Lee has ONE sigma per structure and the
    declared place to read it is the structure's own mean expiry, not its front
    contract's.
    """
    seen: list[tuple[Any, float]] = []

    def _linear(as_of, t1_mean):
        seen.append((as_of, t1_mean))
        return 100.0 * t1_mean

    tb = _tb()
    df = tb.sfr_cvx_adj(["BLUES_MODEL"], START, END, model_vol_provider=_linear)
    d0 = df.index[0].date()
    t1s = M._cvx_model_t1s(d0, "BLUES")
    want_mean = float(np.mean(t1s))

    assert seen and seen[0][0] == d0
    assert seen[0][1] == pytest.approx(want_mean, rel=1e-12)
    assert seen[0][1] != pytest.approx(t1s[0])       # the front is NOT the mean

    sigma = 100.0 * want_mean
    hand = sigma ** 2 * float(np.mean(np.asarray(t1s) ** 2)) / 2e4
    assert float(df.iloc[0, 0]) == pytest.approx(hand, rel=1e-12)


def test_a_single_contract_label_reads_its_own_expiry():
    """For one contract the mean IS that contract's T1, which is the check that
    the mean rule degrades correctly rather than being special-cased."""
    seen: list[float] = []

    def _p(_as_of, t1_mean):
        seen.append(t1_mean)
        return 90.0

    tb = _tb()
    tb.sfr_cvx_adj(["SFR9_MODEL"], START, END, model_vol_provider=_p)
    d0 = pd.Timestamp(START).date()
    assert seen[0] == pytest.approx(M._cvx_model_t1s(d0, "SFR9")[0], rel=1e-12)


def test_every_label_family_answers():
    tb = _tb()
    labels = ["SFR1_MODEL", "SFR20_MODEL", "WHITES_MODEL", "GOLDS_MODEL",
              "SILVERS_MODEL", "BUNDLE2_MODEL", "BUNDLE5Y_MODEL"]
    df = tb.sfr_cvx_adj(labels, START, END, model_vol_provider=_fixed())
    assert df.shape[1] == len(labels)
    assert df.notna().all().all()
    assert not tb.sfr_cvx_adj_failures
    # deeper structures carry a larger adjustment at one vol -- mean(T1^2) grows
    w = df.mean()
    assert (w["USD-SOFR-1D SFR1_MODEL OUTRIGHT CVX_ADJ"]
            < w["USD-SOFR-1D WHITES_MODEL PACKS CVX_ADJ"]
            < w["USD-SOFR-1D GOLDS_MODEL PACKS CVX_ADJ"]
            < w["USD-SOFR-1D SILVERS_MODEL PACKS CVX_ADJ"])


def test_an_unresolvable_model_label_raises_instead_of_returning_empty():
    """Before this feature, ``sfr_cvx_adj(["BLUES_MODEL"])`` returned an empty
    frame and recorded no failure. A silent nothing is the worst answer."""
    tb = _tb()
    with pytest.raises(ValueError, match="not a convexity structure"):
        tb.sfr_cvx_adj(["WOMBAT_MODEL"], START, END,
                       model_vol_provider=_fixed())


def test_a_bad_vol_is_recorded_as_a_failure_and_produces_no_row():
    for bad in (float("nan"), 0.0, -12.0):
        tb = _tb()
        df = tb.sfr_cvx_adj(["BLUES_MODEL"], START, END,
                            model_vol_provider=_fixed(bad))
        assert df.empty
        assert "BLUES_MODEL" in tb.sfr_cvx_adj_failures
        assert all("bad vol" in r
                   for r in tb.sfr_cvx_adj_failures["BLUES_MODEL"].values())


def test_an_expired_contract_is_recorded_as_a_failure():
    tb = _tb()
    df = tb.sfr_cvx_adj(["H20_MODEL"], START, END, model_vol_provider=_fixed())
    assert df.empty
    assert all("expired" in r
               for r in tb.sfr_cvx_adj_failures["H20_MODEL"].values())


def test_the_model_and_the_observed_label_can_be_asked_for_together():
    """Mixing them must not make the observed one disappear or vice versa.

    The observed side needs futures data the fake MDP will not serve, so it
    records failures -- the point is that BOTH labels are handled and the model
    column survives every early return the method can take.
    """
    tb = _tb()
    df = tb.sfr_cvx_adj(["BLUES_MODEL", "BLUES"], START, END,
                        model_vol_provider=_fixed())
    assert "USD-SOFR-1D BLUES_MODEL PACKS CVX_ADJ" in df.columns


def test_the_model_write_does_not_land_on_the_observed_key():
    tb = _tb()
    # NAMED, because an unnamed injected provider is no longer persisted at all
    # -- see test_an_unnamed_injected_provider_is_never_written.
    tb.sfr_cvx_adj(["BLUES_MODEL"], START, END, model_vol_provider=_fixed(),
                   model_vol_source="test-fixed")
    mapping = getattr(tb, tb._cache_attr)
    assert mapping, "the model path wrote nothing to cache"
    written = set(mapping)

    obs_keys = set()
    import rateslib as rl
    for ts in pd.to_datetime(list(pd.bdate_range(START, END))):
        codes = [M._cvx_imm_code_from_date_rank(ts.date(), r)
                 for r in M._cvx_ranks_for_label("BLUES")]
        q = IRSwapQuery(
            curve="USD-SOFR-1D",
            effective_date=rl.get_imm(code=codes[0]).date(),
            maturity_date=rl.next_imm(rl.get_imm(code=codes[-1])).date(),
            structure=IRSwapStructure.OUTRIGHT, structure_kwargs={"bpv": 1},
            value=IRSwapValue.CVX_ADJ,
            value_kwargs={"matched_frequency": "Q",
                          "matched_leg2_frequency": "Q"})
        obs_keys.add(tb._cache_key(ts.to_pydatetime(), "USD-SOFR-1D", q))
    assert not (written & obs_keys), "a model value landed on an observed key"


def test_a_second_call_is_served_from_cache_without_the_provider():
    """...when the provider is NAMED. An unnamed one recomputes every time."""
    tb = _tb()
    first = tb.sfr_cvx_adj(["BLUES_MODEL"], START, END,
                           model_vol_provider=_fixed(),
                           model_vol_source="test-fixed")

    def _explode(_a, _b):
        raise AssertionError("the provider was called on a warm cache")

    second = tb.sfr_cvx_adj(["BLUES_MODEL"], START, END,
                            model_vol_provider=_explode,
                            model_vol_source="test-fixed")
    pd.testing.assert_frame_equal(first, second)


def test_ignore_cache_recomputes():
    tb = _tb()
    tb.sfr_cvx_adj(["BLUES_MODEL"], START, END, model_vol_provider=_fixed(80.0))
    again = tb.sfr_cvx_adj(["BLUES_MODEL"], START, END, ignore_cache=True,
                           model_vol_provider=_fixed(160.0))
    d0 = again.index[0].date()
    t1s = M._cvx_model_t1s(d0, "BLUES")
    assert float(again.iloc[0, 0]) == pytest.approx(
        160.0 ** 2 * float(np.mean(np.asarray(t1s) ** 2)) / 2e4, rel=1e-12)


def test_an_unknown_vol_source_with_no_provider_refuses():
    tb = _tb()
    with pytest.raises(ValueError, match="no built-in provider"):
        tb.sfr_cvx_adj(["BLUES_MODEL"], START, END, model_vol_source="capfloor")


# ---------------------------------------------------------------------------
# 6. the intraday path must refuse a model label
# ---------------------------------------------------------------------------
def test_the_intraday_path_refuses_a_model_label():
    """It shares this vocabulary and prices the OBSERVED adjustment. Serving a
    model label there would return an observed number under a model name."""
    tb = _tb()
    with pytest.raises(ValueError, match="MODEL labels"):
        tb.sfr_cvx_adj_intraday(["BLUES_MODEL"],
                                [pd.Timestamp("2025-06-02 15:00", tz="UTC")])


# ---------------------------------------------------------------------------
# 7. the cached-record reader
# ---------------------------------------------------------------------------
def test_the_cached_model_reader_handles_the_shapes_it_writes():
    f = M._cvx_cached_model_value
    col = "USD-SOFR-1D BLUES_MODEL PACKS CVX_ADJ"
    assert f({"date": pd.Timestamp("2025-06-02"), col: 5.25}, "date", col) == 5.25
    assert f({"date": pd.Timestamp("2025-06-02"), "other": 5.25}, "date", col) == 5.25
    assert f((pd.Timestamp("2025-06-02"), col, 5.25), "date", col) == 5.25
    assert f(None, "date", col) is None
    assert f({"date": pd.Timestamp("2025-06-02")}, "date", col) is None
    assert f({"date": pd.Timestamp("2025-06-02"), col: "x"}, "date", col) is None
