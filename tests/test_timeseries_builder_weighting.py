"""``TimeseriesBuilder`` end of the ``weighting=`` seam.

Fake routers only - no network, no DB, no pricer. What is pinned here is the
plumbing: that a weighted package is fetched as legs and rebuilt as one column,
that the identity schema reproduces the ordinary package arithmetic exactly,
that leg tokens are normalised the way the pricer expects, and that a request
carrying no ``weighting=`` is untouched.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import pytest

import RVUtils.fly as fly
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, normalize_tenor_token
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.Unified.UnifiedQuery import UnifiedQuery
from Query.Unified.registry import UnifiedValue
from TB.TimeseriesBuilder import TimeseriesBuilder
from RVUtils.fly.estimators import combine
from TB.weighting import PACKAGE_MULTIPLIER, expand_package, plan_weighted_queries

START = datetime.date(2024, 1, 2)
END = datetime.date(2025, 6, 30)

FLY_TENOR = "1y5y/1y10y/1y30y"
LEG_TOKENS = ("1Yx5Y", "1Yx10Y", "1Yx30Y")


class _PanelRouter:
    """Serves a fixed per-column path, and records what it was asked for."""

    def __init__(self, panel_by_column: Dict[str, np.ndarray], date_col: str = "Date"):
        self.panel_by_column = panel_by_column
        self.date_col = date_col
        self.mdp = None
        self.received_queries: List[Any] = []

    def get_timeseries(
        self,
        start,
        end,
        queries,
        *,
        n_jobs=1,
        ignore_cache=False,
        ignore_cache_miss=False,
        freq=None,
        timestamps=None,
        _prefetched_ts_rows_by_symbol=None,
    ) -> pd.DataFrame:
        _ = n_jobs, ignore_cache, ignore_cache_miss, freq, timestamps, _prefetched_ts_rows_by_symbol
        self.received_queries.extend(queries)
        dates = pd.bdate_range(start, end).date.tolist()
        data: Dict[str, List[float]] = {}
        for q in queries:
            column = q.col_name()
            if column not in self.panel_by_column:
                raise KeyError(f"fake router has no path for {column!r}")
            data[column] = list(self.panel_by_column[column][: len(dates)])
        if not data:
            return pd.DataFrame()
        return pd.DataFrame(data, index=pd.Index(dates, name=self.date_col))


def _paths(n: int, seed: int = 5) -> Dict[str, np.ndarray]:
    """Three forward-swap rate paths, in PERCENT, with a dominant level factor."""
    rng = np.random.default_rng(seed)
    level = np.cumsum(rng.normal(0.0, 0.04, n))
    slope = np.cumsum(rng.normal(0.0, 0.015, n))
    out = {}
    for token, (b_level, b_slope, anchor) in zip(
        LEG_TOKENS, [(1.00, -1.0, 3.60), (0.93, 0.0, 3.95), (0.80, 1.0, 4.30)]
    ):
        out[f"USD-SOFR-1D {token} OUTRIGHT RATE"] = (
            anchor + b_level * level + b_slope * slope + rng.normal(0.0, 0.006, n)
        )
    return out


def _n_business_days() -> int:
    return len(pd.bdate_range(START, END))


def _builder(seed: int = 5):
    paths = _paths(_n_business_days(), seed=seed)
    router = _PanelRouter(paths)
    return TimeseriesBuilder(irswaps_tb=router), router, paths


def _fly(**kwargs) -> UnifiedQuery:
    return UnifiedQuery(curve="USD-SOFR-1D", tenor=FLY_TENOR, value=UnifiedValue.IRS_RATE, **kwargs)


# --------------------------------------------------------------------------- #
# expansion
# --------------------------------------------------------------------------- #


def test_a_fly_expands_to_three_normalised_outright_legs():
    legs, base = expand_package(_fly(weighting=fly.pca_chgs))

    assert base == (-1.0, 2.0, -1.0)
    assert [leg.tenor for leg in legs] == list(LEG_TOKENS)
    assert all(leg.structure == IRSwapStructure.OUTRIGHT for leg in legs)
    assert all(leg.value == IRSwapValue.RATE for leg in legs)
    assert all(leg.curve == "USD-SOFR-1D" for leg in legs)
    assert all(getattr(leg, "weighting", None) is None for leg in legs)


def test_leg_tokens_get_the_same_normalisation_the_package_gives_them():
    """``1y5y`` has to become ``1Yx5Y`` or the outright prices as a spot swap."""
    assert normalize_tenor_token("1y5y") == "1Yx5Y"
    assert normalize_tenor_token(" 1Y 10Y ") == "1Yx10Y"
    assert normalize_tenor_token("5y") == "5Y"
    assert normalize_tenor_token("IMM_1xIMM_2") == "IMM_1xIMM_2"

    legs, _ = expand_package(_fly(weighting=fly.pca_chgs))
    assert legs[0].structure_kwargs["tenor"] == "1Yx5Y"


def test_a_curve_expands_to_two_legs_with_the_pricers_signs():
    legs, base = expand_package(
        UnifiedQuery(curve="USD-SOFR-1D", tenor="5y/10y", value=UnifiedValue.IRS_RATE, weighting=fly.pca_chgs)
    )
    assert base == (-1.0, 1.0)
    assert [leg.tenor for leg in legs] == ["5Y", "10Y"]


def test_a_bond_package_expands_on_its_own_delimiters():
    legs, base = expand_package(
        UnifiedQuery(cusip="CT2/CT5/CT10", value=UnifiedValue.FRB_YTM, weighting=fly.pca_chgs)
    )
    assert base == (-1.0, 2.0, -1.0)
    assert [leg.cusip for leg in legs] == ["CT2", "CT5", "CT10"]
    assert all(leg.value == FixedRateBondValue.YTM for leg in legs)


def test_an_outright_or_an_unsupported_value_is_refused_clearly():
    with pytest.raises(ValueError, match="multi-leg"):
        expand_package(
            UnifiedQuery(curve="USD-SOFR-1D", tenor="10Y", value=UnifiedValue.IRS_RATE, weighting=fly.pca_chgs)
        )
    with pytest.raises(NotImplementedError, match="RATE"):
        expand_package(
            UnifiedQuery(curve="USD-SOFR-1D", tenor=FLY_TENOR, value=UnifiedValue.IRS_DV01, weighting=fly.pca_chgs)
        )


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #


def test_a_request_without_weighting_is_returned_untouched():
    plain = _fly()
    rewritten, plans = plan_weighted_queries([plain])
    assert plans == []
    assert rewritten[0] is plain


def test_two_schemas_on_one_package_share_one_set_of_leg_fetches():
    rewritten, plans = plan_weighted_queries(
        [_fly(weighting=fly.pca_chgs_1m), _fly(weighting=fly.beta_chgs_1m)]
    )
    assert len(plans) == 2
    assert len(rewritten) == 3  # not six
    assert len({p.column for p in plans}) == 2


def test_a_leg_the_caller_also_asked_for_by_name_is_not_dropped():
    leg = UnifiedQuery(curve="USD-SOFR-1D", tenor="1Yx10Y", value=UnifiedValue.IRS_RATE)
    _, plans = plan_weighted_queries([_fly(weighting=fly.pca_chgs_1m), leg])
    assert "USD-SOFR-1D 1Yx10Y OUTRIGHT RATE" not in plans[0].private_leg_columns
    assert "USD-SOFR-1D 1Yx5Y OUTRIGHT RATE" in plans[0].private_leg_columns


# --------------------------------------------------------------------------- #
# end to end through TimeseriesBuilder
# --------------------------------------------------------------------------- #


def test_the_identity_schema_reproduces_the_package_arithmetic_exactly():
    """The round trip that makes the whole approach legitimate."""
    tb, router, paths = _builder()
    out = tb.get_timeseries(start=START, end=END, queries=[_fly(weighting=fly.base)])

    column = "USD-SOFR-1D 1y5y/1y10y/1y30y FLY RATE [base]"
    assert list(out.columns) == [column]

    front, belly, back = (paths[f"USD-SOFR-1D {t} OUTRIGHT RATE"] for t in LEG_TOKENS)
    # Literal 100.0, not PACKAGE_MULTIPLIER: the constant's VALUE is the claim.
    expected = (2.0 * belly - front - back)[: len(out)] * 100.0
    assert out[column].to_numpy() == pytest.approx(expected, abs=1e-9)
    # ...and the fly is basis points off percent legs, so it is single-digit.
    assert 0.5 < out[column].abs().median() < 60.0
    assert 3.0 < np.median(belly) < 5.0

    # The router was asked for three OUTRIGHTS and never for the fly.
    assert all(q.structure == IRSwapStructure.OUTRIGHT for q in router.received_queries)
    assert len(router.received_queries) == 3


def test_the_percent_to_bp_factor_is_the_pricers_own_ratio():
    """100 = (fly multiplier 10,000) / (outright multiplier 100). Not a guess."""
    from Query.FixedRateBonds.FixedRateBondValue import _frb_structure_legs_mapper
    from Query.IRSwaps.IRSwapValue import _swap_structure_legs_mapper

    assert PACKAGE_MULTIPLIER == 100.0
    assert _swap_structure_legs_mapper[3][1] / _swap_structure_legs_mapper[1][1] == PACKAGE_MULTIPLIER
    assert _swap_structure_legs_mapper[2][1] / _swap_structure_legs_mapper[1][1] == PACKAGE_MULTIPLIER
    assert _frb_structure_legs_mapper[3][1] / _frb_structure_legs_mapper[1][1] == PACKAGE_MULTIPLIER
    assert _frb_structure_legs_mapper[2][1] / _frb_structure_legs_mapper[1][1] == PACKAGE_MULTIPLIER


def test_the_base_weights_are_the_pricers_own_signed_vectors():
    """(-1, +2, -1) and (-1, +1) come from the sign map, not from taste."""
    from Query.IRSwaps.IRSwapValue import _swap_structure_sign_mapper
    from TB.weighting import BASE_WEIGHTS

    fly_signed = _swap_structure_sign_mapper[IRSwapStructure.FLY]([1.0, 2.0, 1.0])
    assert list(fly_signed) == list(BASE_WEIGHTS[3]) == [-1.0, 2.0, -1.0]
    # CURVE's map is identity; the signs come from _build_curve's copysign block
    # under the bpv=1 that resolve_query plants, i.e. back minus front.
    assert list(BASE_WEIGHTS[2]) == [-1.0, 1.0]


def test_a_weighted_fly_differs_from_the_plain_one_but_stays_a_fly():
    tb, _, paths = _builder()
    out = tb.get_timeseries(
        start=START,
        end=END,
        queries=[_fly(weighting=fly.base), _fly(weighting=fly.pca_chgs_3m)],
    )
    plain = out["USD-SOFR-1D 1y5y/1y10y/1y30y FLY RATE [base]"]
    hedged = out["USD-SOFR-1D 1y5y/1y10y/1y30y FLY RATE [pca_chgs_3m]"]

    both = pd.concat([plain, hedged], axis=1).dropna()
    assert len(both) > 100
    assert not np.allclose(both.iloc[:, 0].to_numpy(), both.iloc[:, 1].to_numpy())

    weights = out.attrs["fly_weights"]["USD-SOFR-1D 1y5y/1y10y/1y30y FLY RATE [pca_chgs_3m]"]
    fitted = weights.dropna()
    assert not fitted.empty
    assert np.allclose(fitted.iloc[:, 1].to_numpy(), 2.0)           # belly pinned
    assert (fitted.iloc[:, 0] < 0).all() and (fitted.iloc[:, 2] < 0).all()


def test_the_hedged_fly_is_less_correlated_to_the_level_than_the_plain_one():
    """The point of the exercise, stated as a property rather than a formula."""
    tb, _, paths = _builder()
    out = tb.get_timeseries(
        start=START,
        end=END,
        queries=[_fly(weighting=fly.base), _fly(weighting=fly.pca_chgs)],
    )
    belly = out.attrs["fly_legs"]["USD-SOFR-1D 1y5y/1y10y/1y30y FLY RATE [pca_chgs]"].iloc[:, 1]

    def beta_to_level(series):
        d = pd.concat([series.diff(), belly.diff()], axis=1).dropna()
        return abs(np.corrcoef(d.iloc[:, 0], d.iloc[:, 1])[0, 1])

    plain = beta_to_level(out["USD-SOFR-1D 1y5y/1y10y/1y30y FLY RATE [base]"])
    hedged = beta_to_level(out["USD-SOFR-1D 1y5y/1y10y/1y30y FLY RATE [pca_chgs]"])
    assert hedged < plain


def test_leg_columns_are_dropped_unless_asked_for():
    tb, _, _ = _builder()
    out = tb.get_timeseries(start=START, end=END, queries=[_fly(weighting=fly.pca_chgs_1m)])
    assert not [c for c in out.columns if "OUTRIGHT" in str(c)]

    kept = tb.get_timeseries(start=START, end=END, queries=[_fly(weighting=fly.pca_chgs_1m.with_legs())])
    assert len([c for c in kept.columns if "OUTRIGHT" in str(c)]) == 3


def test_emit_weights_adds_one_column_per_leg():
    tb, _, _ = _builder()
    schema = fly.pca_chgs_1m.with_weights()
    out = tb.get_timeseries(start=START, end=END, queries=[_fly(weighting=schema)])
    base = f"USD-SOFR-1D {FLY_TENOR} FLY RATE [{schema.label}]"
    assert [f"{base} W1", f"{base} W2", f"{base} W3"] == [c for c in out.columns if c.endswith(("W1", "W2", "W3"))]
    assert np.allclose(out[f"{base} W2"].dropna().to_numpy(), 2.0)
    assert (out[f"{base} W1"].dropna() < 0).all()


def test_a_plain_request_is_byte_identical_to_what_it_was():
    """The seam must be invisible when nobody uses it."""
    paths = _paths(_n_business_days())
    router = _PanelRouter({"USD-SOFR-1D 10Y OUTRIGHT RATE": next(iter(paths.values()))})
    tb = TimeseriesBuilder(irswaps_tb=router)
    q = UnifiedQuery(curve="USD-SOFR-1D", tenor="10Y", value=UnifiedValue.IRS_RATE)

    out = tb.get_timeseries(start=START, end=END, queries=[q])

    assert list(out.columns) == ["USD-SOFR-1D 10Y OUTRIGHT RATE"]
    assert out.index.name == "Date"
    assert "fly_weights" not in out.attrs


def test_the_multilevel_column_form_still_works():
    tb, _, _ = _builder()
    out = tb.get_timeseries(
        start=START, end=END, queries=[_fly(weighting=fly.base)], drop_multilevel_cols=False
    )
    assert isinstance(out.columns, pd.MultiIndex)
    assert ("IRS", "USD-SOFR-1D 1y5y/1y10y/1y30y FLY RATE [base]") in out.columns


def test_a_legacy_irswapquery_can_carry_a_weighting_too():
    tb, _, _ = _builder()
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor=FLY_TENOR, value=IRSwapValue.RATE, weighting="pca_chgs_1m")
    assert q.weighting == fly.pca_chgs_1m
    out = tb.get_timeseries(start=START, end=END, queries=[q])
    assert f"USD-SOFR-1D {FLY_TENOR} FLY RATE [pca_chgs_1m]" in out.columns


def test_a_bad_preset_name_fails_at_the_call_site_not_mid_fetch():
    with pytest.raises(AttributeError):
        _fly(weighting="pca_bananas_1m")


def test_rolling_weights_are_nan_until_the_window_fills():
    tb, _, _ = _builder()
    out = tb.get_timeseries(start=START, end=END, queries=[_fly(weighting=fly.minvar_chgs_3m)])
    series = out[f"USD-SOFR-1D {FLY_TENOR} FLY RATE [minvar_chgs_3m]"]
    assert series.iloc[:10].isna().all()
    assert series.iloc[-10:].notna().all()


def test_the_result_survives_the_first_thing_anybody_does_with_it():
    """``attrs`` holding DataFrames used to make ``pd.concat`` raise."""
    tb, _, _ = _builder()
    out = tb.get_timeseries(
        start=START, end=END, queries=[_fly(weighting=fly.base), _fly(weighting=fly.pca_chgs_3m)]
    )
    a, b = (out[c] for c in out.columns)

    joined = pd.concat([a, b], axis=1)
    assert joined.shape[1] == 2
    assert pd.concat([out, out]).shape[0] == 2 * len(out)
    assert out.join(b.rename("copy")).shape[1] == 3
    assert (a.diff().dropna() * 2).notna().all()


def test_attrs_carry_the_schema_and_the_weight_path():
    tb, _, _ = _builder()
    out = tb.get_timeseries(start=START, end=END, queries=[_fly(weighting=fly.beta_chgs_6m)])
    column = f"USD-SOFR-1D {FLY_TENOR} FLY RATE [beta_chgs_6m]"

    assert out.attrs["fly_schemas"][column] is fly.beta_chgs_6m
    weights = out.attrs["fly_weights"][column]
    legs = out.attrs["fly_legs"][column]
    assert list(weights.columns) == list(legs.columns)
    assert weights.index.equals(out.index)

    # And the column really is what combine() makes of the legs it names.
    schema = out.attrs["fly_schemas"][column]
    assert schema.resolved_combine_mode == "pnl"  # rolling window
    rebuilt = combine(legs, weights, multiplier=PACKAGE_MULTIPLIER, mode="pnl")
    assert out[column].to_numpy() == pytest.approx(rebuilt.to_numpy(), nan_ok=True, abs=1e-9)


def test_a_rolling_weighting_does_not_inherit_the_weight_drift():
    """The measured defect: level recombination made a 1m PCA fly 230x noisier."""
    tb, _, _ = _builder()
    out = tb.get_timeseries(
        start=START,
        end=END,
        queries=[
            _fly(weighting=fly.base),
            _fly(weighting=fly.pca_chgs_1m),
            _fly(weighting=fly.pca_chgs_1m.but(combine_mode="level")),
        ],
    )
    plain = out[f"USD-SOFR-1D {FLY_TENOR} FLY RATE [base]"].diff().std()
    auto = out[f"USD-SOFR-1D {FLY_TENOR} FLY RATE [pca_chgs_1m]"].diff().std()
    level = out[f"USD-SOFR-1D {FLY_TENOR} FLY RATE [pca_chgs_1m_level]"].diff().std()

    assert auto < 3 * plain
    assert level > 5 * plain
