"""``<LABEL>_MODEL2`` on ``IRSwapsTB.sfr_cvx_adj`` -- the Hull-White model level.

Hermetic, exactly like ``test_irswaps_tb_holee_model.py``: a fake MDP that
raises if the model path ever tries to price a curve, an in-memory cache, and
injected volatility providers. The arithmetic itself is checked against
quadrature, Monte Carlo and QuantLib in ``test_convexity_rv_hw1f_sofr.py``;
what is checked here is the WIRING -- the label grammar, the cache identity,
which expiry each volatility is read at, and that ``_MODEL`` still gets exactly
what it got before ``_MODEL2`` existed.
"""
from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

from MDP.MarketDataProvider import MarketDataProvider
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from RVUtils.ConvexityRV import hw1f_sofr as H
from TB import IRSwapsTB as M
from TB.IRSwapsTB import IRSwapsTB, _query_fingerprint

START, END = "2025-06-02", "2025-06-13"
SIGMA = 95.0
A = M.CVX_MODEL2_MEAN_REVERSION


class _FakeMDP(MarketDataProvider):
    """The model path never asks the MDP for anything; this proves it."""

    def __init__(self, source: str = "TEST_HW1F"):
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
    def _p(_as_of, _t):
        return sigma
    return _p


# ---------------------------------------------------------------------------
# 1. the label grammar, and the suffix that does NOT collide
# ---------------------------------------------------------------------------
def test_model2_labels_split_and_name_their_model():
    assert M._cvx_model_base("BLUES_MODEL2") == ("BLUES", True)
    assert M._cvx_model_base("  blues_model2 ") == ("BLUES", True)
    assert M._cvx_model_kind("BLUES_MODEL2") == "hw1f_sofr"
    assert M._cvx_model_kind("BLUES_MODEL") == "holee"
    assert M._cvx_model_kind("BLUES") is None
    assert M._cvx_model_suffix("SFR9_MODEL2") == "_MODEL2"
    assert M._cvx_model_suffix("SFR9") is None


def test_the_two_suffixes_do_not_shadow_each_other():
    """No ordering hazard TODAY -- pinned so a third suffix cannot add one.

    ``"BLUES_MODEL2"`` does not end with ``"_MODEL"`` (its last six characters
    are ``MODEL2``), so the suffix table can be scanned in any order. If that
    ever stops being true, the table needs longest-first and this test is what
    says so.
    """
    assert not "BLUES_MODEL2".endswith(M.CVX_MODEL_SUFFIX)
    assert not "BLUES_MODEL".endswith(M.CVX_MODEL2_SUFFIX)
    for order in (M.CVX_MODEL_SUFFIXES, tuple(reversed(M.CVX_MODEL_SUFFIXES))):
        got = None
        for suf in order:
            if "BLUES_MODEL2".endswith(suf):
                got = suf
                break
        assert got == "_MODEL2"


def test_a_bare_model2_suffix_is_not_a_label():
    assert M._cvx_model_base("_MODEL2") == ("_MODEL2", False)
    assert M._cvx_model_kind("_MODEL2") is None


def test_the_resolvers_stay_suffix_blind_for_model2_too():
    """Same safety property ``_MODEL`` has: only the tag may strip.

    If a contract resolver learned ``_MODEL2``, ``sfr_cvx_adj_intraday`` -- which
    shares this vocabulary -- would resolve the label and serve the OBSERVED
    intraday adjustment under a model name.
    """
    assert M._cvx_structure_tag("BLUES_MODEL2") == "PACKS"
    assert M._cvx_structure_tag("BUNDLE5Y_MODEL2") == "BUNDLES"
    assert M._cvx_structure_tag("SFR9_MODEL2") == "OUTRIGHT"
    assert M._cvx_ranks_for_label("BLUES_MODEL2") is None
    assert M._cvx_cm_rank("SFR9_MODEL2") is None
    assert not M._cvx_is_imm("H26_MODEL2")


def test_the_column_name_carries_the_model2_label():
    assert (M._cvx_col_name("USD-SOFR-1D", "BLUES_MODEL2")
            == "USD-SOFR-1D BLUES_MODEL2 PACKS CVX_ADJ")


# ---------------------------------------------------------------------------
# 2. the cache identity -- now a THREE-way separation
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


def test_observed_holee_and_hw1f_are_three_distinct_cache_entries():
    """They describe the same instrument window and differ only in value_kwargs.

    Strip the markers and all three collide -- the second assertion is what
    makes the first a test rather than a restatement of itself.
    """
    observed = _q({"matched_frequency": "Q", "matched_leg2_frequency": "Q"})
    holee = _q(M.cvx_model_value_kwargs(vol_source="swaption_cube"))
    hw = _q(M.cvx_model2_value_kwargs(vol_source="swaption_cube"))
    keys = {_query_fingerprint(observed), _query_fingerprint(holee),
            _query_fingerprint(hw)}
    assert len(keys) == 3

    bare = _q({})
    assert _query_fingerprint(bare) == _query_fingerprint(_q({}))


def test_the_mean_reversion_is_part_of_the_key():
    """Two mean reversions are two models, not one model with an option."""
    a3 = _query_fingerprint(_q(M.cvx_model2_value_kwargs(
        vol_source="swaption_cube", mean_reversion=0.03)))
    a5 = _query_fingerprint(_q(M.cvx_model2_value_kwargs(
        vol_source="swaption_cube", mean_reversion=0.05)))
    assert a3 != a5
    # ...and the same model formatted differently is still ONE key
    same = _query_fingerprint(_q(M.cvx_model2_value_kwargs(
        vol_source="swaption_cube", mean_reversion=0.03 + 2e-18)))
    assert same == a3


def test_every_part_of_the_model2_spec_is_in_the_key():
    base = _query_fingerprint(_q(M.cvx_model2_value_kwargs(vol_source="swaption_cube")))
    for kw in (dict(vol_source="capfloor"),
               dict(vol_source="swaption_cube", vol_tenor="3M"),
               dict(vol_source="swaption_cube", payoff="term"),
               dict(vol_source="swaption_cube", payoff="average"),
               dict(vol_source="swaption_cube", vol_interp="snap")):
        assert _query_fingerprint(_q(M.cvx_model2_value_kwargs(**kw))) != base


def test_the_stored_spec_names_which_model_wrote_the_row():
    """Provenance, and it is not decoration.

    The two specs already differ by their other keys, so a wrong ``cvx_model``
    would not COLLIDE -- it would sit in the store labelled as the other model,
    and the only way to tell a Ho-Lee row from a Hull-White one after the fact
    is this string. A mutation that swapped it survived every separation test,
    which is what this test exists to answer.
    """
    holee = M.cvx_model_value_kwargs(vol_source="swaption_cube")
    hw = M.cvx_model2_value_kwargs(vol_source="swaption_cube")
    assert holee["cvx_model"] == "holee"
    assert hw["cvx_model"] == "hw1f_sofr"
    assert set(M.CVX_MODEL_KINDS.values()) == {holee["cvx_model"], hw["cvx_model"]}


def test_t2_is_the_next_imm_date_and_not_a_quarter_after_t1():
    """``T2`` comes from the calendar, checked against rateslib directly.

    Every other test derives its expectation from ``_cvx_model_t1_t2s`` itself,
    so replacing ``T2`` with ``T1 + 0.25`` moves the expectation with the code
    and survives. This one recomputes the IMM dates independently, and asserts
    the accrual is NOT a quarter -- IMM to IMM is 91 or 92 days, never 91.25.
    """
    import rateslib as rl

    as_of = pd.Timestamp(START).date()
    t1s, t2s = M._cvx_model_t1_t2s(as_of, "BLUES")
    ranks = M._cvx_ranks_for_label("BLUES")
    for rank, t1, t2 in zip(ranks, t1s, t2s):
        code = M._cvx_imm_code_from_date_rank(as_of, rank)
        imm = rl.get_imm(code=code)
        imm_d = imm.date() if hasattr(imm, "date") else imm
        nxt = rl.next_imm(imm)
        nxt_d = nxt.date() if hasattr(nxt, "date") else nxt
        assert t1 == pytest.approx((imm_d - as_of).days / 365.0, rel=1e-15)
        assert t2 == pytest.approx((nxt_d - as_of).days / 365.0, rel=1e-15)
        assert (nxt_d - imm_d).days in (91, 92)
    taus = [t2 - t1 for t1, t2 in zip(t1s, t2s)]
    assert all(abs(t - 0.25) > 1e-4 for t in taus), taus


# ---------------------------------------------------------------------------
# 3. which expiry each volatility is read at
# ---------------------------------------------------------------------------
def test_model2_reads_one_vol_per_contract_at_its_own_expiry():
    """The Ho-Lee path reads ONE vol at the mean expiry; this one reads four.

    A constant provider cannot tell the two apart, which is exactly how the
    equivalent defect survived the first mutation run on ``_MODEL``. The
    provider here is linear in the expiry, so the four reads are four different
    numbers and the value depends on all of them.
    """
    seen: List[float] = []

    def _linear(_as_of, t):
        seen.append(t)
        return 80.0 + 5.0 * t

    tb = _tb()
    df = tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END, model_vol_provider=_linear)
    d0 = df.index[0].date()
    t1s, t2s = M._cvx_model_t1_t2s(d0, "BLUES")
    assert len(t1s) == 4
    assert seen[:4] == pytest.approx(t1s, rel=1e-12)
    assert len(set(seen[:4])) == 4                       # four DIFFERENT expiries
    assert seen[0] != pytest.approx(float(np.mean(t1s)))  # and not the mean

    vols = [80.0 + 5.0 * t for t in t1s]
    sig = [H.sigma_from_normal_vol_bp(v, A, t1, 1.0) for v, t1 in zip(vols, t1s)]
    want = float(np.mean([H.futures_ca_bp(s, t1, t2, A)
                          for s, t1, t2 in zip(sig, t1s, t2s)]))
    assert float(df.iloc[0, 0]) == pytest.approx(want, rel=1e-12)


def test_the_holee_path_still_reads_exactly_one_vol_at_the_mean():
    seen: List[float] = []

    def _linear(_as_of, t):
        seen.append(t)
        return 80.0 + 5.0 * t

    tb = _tb()
    tb.sfr_cvx_adj(["BLUES_MODEL"], START, END, model_vol_provider=_linear)
    d0 = pd.Timestamp(START).date()
    t1s = M._cvx_model_t1s(d0, "BLUES")
    assert seen[0] == pytest.approx(float(np.mean(t1s)), rel=1e-12)


def test_a_single_contract_label_reads_its_own_expiry():
    seen: List[float] = []

    def _p(_as_of, t):
        seen.append(t)
        return 90.0

    tb = _tb()
    tb.sfr_cvx_adj(["SFR9_MODEL2"], START, END, model_vol_provider=_p)
    d0 = pd.Timestamp(START).date()
    assert seen[0] == pytest.approx(M._cvx_model_t1s(d0, "SFR9")[0], rel=1e-12)


def test_the_vol_tenor_is_the_straddle_tail_the_mapping_uses():
    """``model_vol_tenor`` is not decoration under mean reversion.

    Ho-Lee is indifferent to the tail; Hull-White converts by ``B(a, tail)``, so
    a 5Y tail and a 1Y tail imply different short-rate vols from the same quote
    and therefore different adjustments.
    """
    tb1, tb5, tb3m = _tb(), _tb(), _tb()
    one = tb1.sfr_cvx_adj(["BLUES_MODEL2"], START, END,
                          model_vol_provider=_fixed(), model_vol_tenor="1Y")
    five = tb5.sfr_cvx_adj(["BLUES_MODEL2"], START, END,
                           model_vol_provider=_fixed(), model_vol_tenor="5Y")
    m3 = tb3m.sfr_cvx_adj(["BLUES_MODEL2"], START, END,
                          model_vol_provider=_fixed(), model_vol_tenor="3M")
    # a longer tail moves less per unit of short-rate vol, so the same quote
    # implies a larger sigma and a larger adjustment
    assert float(five.iloc[0, 0]) > float(one.iloc[0, 0]) > float(m3.iloc[0, 0])


# ---------------------------------------------------------------------------
# 4. the model itself, through the wiring
# ---------------------------------------------------------------------------
def test_zero_mean_reversion_gives_the_compounded_ho_lee_limit():
    tb = _tb()
    df = tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END, model_vol_provider=_fixed(),
                        model2_mean_reversion=0.0)
    d0 = df.index[0].date()
    t1s, t2s = M._cvx_model_t1_t2s(d0, "BLUES")
    lin = float(np.mean([H.holee_limit_ca_bp(SIGMA, t1, t2)
                         for t1, t2 in zip(t1s, t2s)]))
    assert float(df.iloc[0, 0]) == pytest.approx(lin, rel=1e-3)


def test_model2_sits_above_model_because_the_weight_is_T2_squared():
    """The headline difference, measured through the public entry point."""
    tb = _tb()
    df = tb.sfr_cvx_adj(["BLUES_MODEL", "BLUES_MODEL2"], START, END,
                        model_vol_provider=_fixed(), model2_mean_reversion=0.0)
    holee = df[[c for c in df.columns if "BLUES_MODEL " in str(c)][0]]
    hw = df[[c for c in df.columns if "BLUES_MODEL2" in str(c)][0]]
    d0 = df.index[0].date()
    t1s, t2s = M._cvx_model_t1_t2s(d0, "BLUES")
    ratio = float(np.mean(np.asarray(t2s) ** 2) / np.mean(np.asarray(t1s) ** 2))
    assert float(hw.iloc[0]) / float(holee.iloc[0]) == pytest.approx(ratio, rel=2e-3)
    assert 1.10 < ratio < 1.20


def test_mean_reversion_is_a_second_order_knob_through_the_wiring():
    """Through the wiring the vol is RECALIBRATED at each ``a``, so the damping
    and the implied-sigma rise nearly cancel: monotone up, and small. At a fixed
    short-rate vol it damps instead -- that is
    ``test_convexity_rv_hw1f_sofr.py::test_mean_reversion_damps_the_adjustment``.
    Asserting a damping here would be asserting a property the model does not
    have once it is calibrated."""
    vals = []
    for a in (0.0, 0.03, 0.10):
        tb = _tb()
        df = tb.sfr_cvx_adj(["GOLDS_MODEL2"], START, END,
                            model_vol_provider=_fixed(), model2_mean_reversion=a)
        vals.append(float(df.iloc[0, 0]))
    assert vals[0] < vals[1] < vals[2]
    assert vals[1] / vals[0] == pytest.approx(1.025, abs=0.01)
    assert vals[2] / vals[0] < 1.10


def test_the_payoff_knob_reaches_the_model():
    out = {}
    for payoff in ("compounded", "average", "term"):
        tb = _tb()
        df = tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END,
                            model_vol_provider=_fixed(), model2_mean_reversion=0.0,
                            model2_payoff=payoff)
        out[payoff] = float(df.iloc[0, 0])
    assert out["compounded"] > out["average"] > out["term"]


# ---------------------------------------------------------------------------
# 5. cache behaviour and mixed requests
# ---------------------------------------------------------------------------
def test_a_NAMED_provider_is_cached_and_the_second_call_asks_it_nothing():
    calls = {"n": 0}

    def _p(_as_of, _t):
        calls["n"] += 1
        return SIGMA

    tb = _tb()
    kw = dict(model_vol_provider=_p, model_vol_source="test-fixed")
    first = tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END, **kw)
    after_first = calls["n"]
    assert after_first > 0
    second = tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END, **kw)
    assert calls["n"] == after_first
    pd.testing.assert_frame_equal(first, second)

    third = tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END, ignore_cache=True, **kw)
    assert calls["n"] > after_first
    pd.testing.assert_frame_equal(first, third)


def test_an_unnamed_injected_provider_is_never_written():
    """An unnamed provider is computed and returned, and stored nowhere.

    Two different providers under the default source would share
    ``injected:swaption_cube`` -- the same defect one namespace along -- so an
    unnamed one does not persist at all. It still ANSWERS; only the store is
    protected.
    """
    calls = {"n": 0}

    def _p(_as_of, _t):
        calls["n"] += 1
        return SIGMA

    tb = _tb()
    first = tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END, model_vol_provider=_p)
    assert not first.empty
    assert getattr(tb, tb._cache_attr) == {}, "an unnamed provider wrote rows"
    n1 = calls["n"]
    second = tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END, model_vol_provider=_p)
    assert calls["n"] == 2 * n1, "the second call was served from somewhere"
    pd.testing.assert_frame_equal(first, second)


def test_an_unnamed_injected_provider_is_not_SERVED_the_builtin_rows():
    """Reads, not writes, are where the missing namespace bites hardest.

    The write is already blocked for an unnamed provider, so removing the
    ``injected:`` namespace looks harmless -- until the built-in rows are warm.
    Then the lookup hits them, the provider is never called, and the caller gets
    the built-in model's numbers back under their own experiment with nothing
    raising. Planting the rows first is what makes that observable.
    """
    import rateslib as rl

    tb = _tb()
    mapping = getattr(tb, tb._cache_attr)
    date_col = getattr(tb, "_date_col", "date")
    colname = M._cvx_col_name("USD-SOFR-1D", "BLUES_MODEL2")
    planted = -12345.0
    for ts in pd.to_datetime(list(pd.bdate_range(START, END))):
        codes = [M._cvx_imm_code_from_date_rank(ts.date(), r)
                 for r in M._cvx_ranks_for_label("BLUES")]
        q = IRSwapQuery(
            curve="USD-SOFR-1D",
            effective_date=rl.get_imm(code=codes[0]).date(),
            maturity_date=rl.next_imm(rl.get_imm(code=codes[-1])).date(),
            structure=IRSwapStructure.OUTRIGHT, structure_kwargs={"bpv": 1},
            value=IRSwapValue.CVX_ADJ,
            value_kwargs=M.cvx_model2_value_kwargs(vol_source="swaption_cube"))
        mapping[tb._cache_key(ts.to_pydatetime(), "USD-SOFR-1D", q)] = {
            date_col: ts.to_pydatetime(), colname: planted}

    calls = {"n": 0}

    def _p(_as_of, _t):
        calls["n"] += 1
        return SIGMA

    out = tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END, model_vol_provider=_p)
    assert calls["n"] > 0, "the injected provider was never called"
    assert not out.empty
    assert (out.iloc[:, 0] != planted).all(), "served the built-in model's rows"
    assert float(out.iloc[0, 0]) > 0.0


def test_an_injected_provider_cannot_read_or_overwrite_the_builtin_rows():
    """The defect this guard exists for, exercised in both directions.

    A provider run used to write under ``cvx_vol_source="swaption_cube"`` -- the
    BUILT-IN model's own key -- so a fixed-vol verification run silently
    replaced real model rows, and later reads were served the fixed-vol number
    with nothing raising. It is measured: 0.20-0.23bp wrong on five packs, days
    after the run that did it.
    """
    builtin = M.cvx_model2_value_kwargs(vol_source="swaption_cube")
    injected = M.cvx_model2_value_kwargs(vol_source="injected:swaption_cube")
    named = M.cvx_model2_value_kwargs(vol_source="injected:my-capfloor")
    keys = {_query_fingerprint(_q(k)) for k in (builtin, injected, named)}
    assert len(keys) == 3

    # the hole: without the namespace the injected run lands on the built-in key
    assert (_query_fingerprint(_q(M.cvx_model2_value_kwargs(vol_source="swaption_cube")))
            == _query_fingerprint(_q(builtin)))

    # end to end: a named provider's rows do not appear under the built-in key
    tb = _tb()
    tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END, model_vol_provider=_fixed(),
                   model_vol_source="my-capfloor")
    written = set(getattr(tb, tb._cache_attr))
    assert written
    tb2 = _tb()
    setattr(tb2, tb2._cache_attr, dict(getattr(tb, tb._cache_attr)))
    calls = {"n": 0}

    def _count(_a, _t):
        calls["n"] += 1
        return 40.0

    out = tb2.sfr_cvx_adj(["BLUES_MODEL2"], START, END, model_vol_provider=_count,
                          model_vol_source="other-label")
    assert calls["n"] > 0, "a different provider was served the first one's rows"
    assert float(out.iloc[0, 0]) < float(
        tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END, model_vol_provider=_fixed(),
                       model_vol_source="my-capfloor").iloc[0, 0])


def test_the_two_models_do_not_read_each_others_rows():
    """The cache-collision hazard, exercised rather than asserted about."""
    tb = _tb()
    both = tb.sfr_cvx_adj(["BLUES_MODEL", "BLUES_MODEL2"], START, END,
                          model_vol_provider=_fixed())
    assert both.shape[1] == 2
    holee = float(both[[c for c in both.columns if "BLUES_MODEL " in str(c)][0]].iloc[0])
    hw = float(both[[c for c in both.columns if "BLUES_MODEL2" in str(c)][0]].iloc[0])
    assert holee != pytest.approx(hw, rel=1e-6)

    # re-read from the warm cache: still two different numbers, same values
    again = tb.sfr_cvx_adj(["BLUES_MODEL", "BLUES_MODEL2"], START, END,
                           model_vol_provider=_fixed())
    pd.testing.assert_frame_equal(both, again)


def test_a_mixed_request_answers_every_label_family():
    tb = _tb()
    df = tb.sfr_cvx_adj(["SFR1_MODEL2", "GOLDS_MODEL2", "BUNDLE5Y_MODEL2",
                         "SILVERS_MODEL2"], START, END,
                        model_vol_provider=_fixed())
    assert df.shape[1] == 4
    assert not df.isna().any().any()
    assert (df > 0).all().all()


# ---------------------------------------------------------------------------
# 6. refusals
# ---------------------------------------------------------------------------
def test_an_unresolvable_base_raises_rather_than_vanishing():
    tb = _tb()
    with pytest.raises(ValueError, match="not a convexity structure"):
        tb.sfr_cvx_adj(["NOTATHING_MODEL2"], START, END,
                       model_vol_provider=_fixed())


def test_the_intraday_path_refuses_model2_labels_by_name():
    tb = _tb()
    with pytest.raises(ValueError, match="_MODEL2"):
        tb.sfr_cvx_adj_intraday(["BLUES_MODEL2"],
                                [pd.Timestamp("2025-06-02 15:00", tz="America/New_York")])


def test_an_unknown_model_kind_raises():
    tb = _tb()
    with pytest.raises(ValueError, match="unknown model kind"):
        tb._sfr_cvx_adj_model_frames(
            ["BLUES_MODEL2"], [pd.Timestamp(START)], curve="USD-SOFR-1D",
            date_col="Date", ignore_cache=True, use_globex=False,
            vol_provider=_fixed(), vol_source="swaption_cube", vol_tenor="1Y",
            convention="citi", note_failure=lambda *a: None, kind="vasicek")


def test_a_bad_vol_is_recorded_as_a_failure_not_priced():
    tb = _tb()
    df = tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END,
                        model_vol_provider=lambda *_: float("nan"))
    assert df.empty
    assert tb.sfr_cvx_adj_failures
    reasons = set()
    for per_label in tb.sfr_cvx_adj_failures.values():
        reasons.update(per_label.values())
    assert any("bad vol" in r for r in reasons)


def test_an_expired_contract_is_recorded_not_priced():
    tb = _tb()
    df = tb.sfr_cvx_adj(["M20_MODEL2"], START, END, model_vol_provider=_fixed())
    assert df.empty
    reasons = set()
    for per_label in tb.sfr_cvx_adj_failures.values():
        reasons.update(per_label.values())
    assert any("expired" in r for r in reasons)
