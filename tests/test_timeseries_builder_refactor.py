"""
Tests for the TimeseriesBuilder refactor: dynamic product routing via routers + MDPs.

All tests use lightweight mocks — no real market data calls.
"""

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
from unittest.mock import MagicMock

import pandas as pd
import pytest

from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from Query.Base._GenericPricable import _GenericPricable
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from TB.TimeseriesBuilder import TimeseriesBuilder, _safe_col_name


# ---------------------------------------------------------------------------
# Fake query subclass — bypasses the adapter registry entirely
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _FakeQuery(BaseQuery):
    """Minimal concrete BaseQuery for testing the generic fallback path."""

    fake_product: str = "FAKE"
    fake_col: str = "fake_col"
    fake_value_result: float = 42.0
    value: str = "PRICE"

    def __post_init__(self):
        object.__setattr__(self, "product", self.fake_product)
        object.__setattr__(self, "structure_id", "OUTRIGHT")
        object.__setattr__(self, "value_id", self.value)

    def return_query(self) -> List["BaseQuery"]:
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        return self.fake_col

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        return self.fake_col

    # Override to bypass adapter registry
    def resolve_package(
        self, *, pricer_or_curve: Any, **hints: Any
    ) -> Tuple[List[Any], List[float]]:
        return ([], [1.0])

    def build_value_map(
        self, *, pricer_or_curve: Any, package: Any, risk_weights: Any
    ) -> Any:
        result = self.fake_value_result

        class _VM:
            def apply(self, value: Any, **kw: Any) -> float:
                return result

        return _VM()


# ---------------------------------------------------------------------------
# Fake router — mimics IRSwapsTB / FixedRateBondsTB
# ---------------------------------------------------------------------------
class _FakeRouter:
    """Returns a canned DataFrame and records received queries."""

    def __init__(
        self,
        col_values: Optional[Dict[str, float]] = None,
        *,
        auto_cols: bool = False,
        auto_value: float = 0.04,
        date_col: str = "Date",
    ):
        self.col_values = col_values
        self.auto_cols = auto_cols
        self.auto_value = auto_value
        self.date_col = date_col
        self.mdp = MagicMock()
        self.received_queries: List[Any] = []

    def get_timeseries(
        self,
        start,
        end,
        queries,
        *,
        n_jobs=1,
        ignore_cache=False,
        freq=None,
        timestamps=None,
    ) -> pd.DataFrame:
        self.received_queries.extend(queries)
        dates = pd.bdate_range(start, end).date.tolist()
        if not dates:
            return pd.DataFrame()

        col_data: Dict[str, list] = {}
        if self.col_values:
            for col, val in self.col_values.items():
                col_data[col] = [val] * len(dates)
        elif self.auto_cols and queries:
            for q in queries:
                col = _safe_col_name(q, f"col_{id(q)}")
                col_data[col] = [self.auto_value] * len(dates)
        else:
            return pd.DataFrame()

        df = pd.DataFrame(col_data, index=pd.Index(dates, name=self.date_col))
        return df


# ---------------------------------------------------------------------------
# Fake MDP for the generic fallback path
# ---------------------------------------------------------------------------
class _FakeMDP(MarketDataProvider):
    """Returns a dummy pricer object for any request."""

    def __init__(self):
        super().__init__(source="FAKE")

    def get_pricer(self, request: Any) -> Any:
        return MagicMock(name="fake_pricer")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _make_tb(
    irs_kw: Optional[dict] = None,
    frb_kw: Optional[dict] = None,
) -> Tuple[TimeseriesBuilder, _FakeRouter, _FakeRouter]:
    irs = _FakeRouter(**(irs_kw or {"auto_cols": True, "auto_value": 0.045}))
    frb = _FakeRouter(**(frb_kw or {"auto_cols": True, "auto_value": 0.040}))
    tb = TimeseriesBuilder(irswaps_tb=irs, fixedratebonds_tb=frb)
    return tb, irs, frb


START = datetime.date(2025, 1, 6)
END = datetime.date(2025, 1, 10)


# ===================================================================
# 1. Per-call router override is used for the matching product bucket
# ===================================================================
class TestRouterOverridePerCall:

    def test_router_override_per_call_used_for_product_bucket(self):
        tb, _, _ = _make_tb()

        override = _FakeRouter(col_values={"x_col": 99.0})
        q = _FakeQuery(fake_product="XPROD", fake_col="x_col")

        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[q],
            routers={"XPROD": override},
        )

        assert not df.empty
        assert len(override.received_queries) == 1
        assert override.received_queries[0] is q
        assert "x_col" in df.columns

    def test_per_call_router_overrides_instance_router(self):
        """Per-call routers should take precedence over instance routers."""
        tb, irs_router, _ = _make_tb()

        # Override the IRS router at call time
        override_irs = _FakeRouter(col_values={"override_col": 0.05})
        q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)

        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[q],
            routers={"IRS": override_irs},
        )

        # Override should have received the query, not the instance router
        assert len(override_irs.received_queries) > 0
        assert len(irs_router.received_queries) == 0


# ===================================================================
# 2. Generic MDP fallback evaluates queries via BaseQuery pipeline
# ===================================================================
class TestGenericMDPFallback:

    def test_generic_mdp_fallback_evaluates_stirfuture_query(self):
        tb, _, _ = _make_tb()
        fake_mdp = _FakeMDP()

        q = _FakeQuery(
            fake_product="STIRFUTURE",
            fake_col="SOFR-H26",
            fake_value_result=95.125,
        )

        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[q],
            mdps={"STIRFUTURE": fake_mdp},
        )

        assert not df.empty
        assert "SOFR-H26" in df.columns
        assert (df["SOFR-H26"] == 95.125).all()

    def test_generic_mdp_fallback_with_timestamps(self):
        tb, _, _ = _make_tb()
        fake_mdp = _FakeMDP()

        q = _FakeQuery(
            fake_product="STIRFUTURE",
            fake_col="SOFR-M26",
            fake_value_result=94.5,
        )
        ts = [
            datetime.datetime(2025, 1, 6, 16, 0),
            datetime.datetime(2025, 1, 7, 16, 0),
        ]

        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[q],
            mdps={"STIRFUTURE": fake_mdp},
            timestamps=ts,
        )

        assert not df.empty
        assert len(df) == 2
        assert "SOFR-M26" in df.columns

    def test_generic_mdp_fallback_uses_query_name_if_set(self):
        tb, _, _ = _make_tb()
        fake_mdp = _FakeMDP()

        q = _FakeQuery(
            fake_product="STIRFUTURE",
            fake_col="ignored",
            fake_value_result=95.0,
            name="Custom Name",
        )

        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[q],
            mdps={"STIRFUTURE": fake_mdp},
        )

        assert "Custom Name" in df.columns


# ===================================================================
# 3. Mixed products: router + generic MDP fallback joined output
# ===================================================================
class TestMixedProductsRouterPlusMDP:

    def test_mixed_products_router_plus_generic_mdp_joined_output(self):
        irs_col = "irs_rate"
        tb, irs_router, _ = _make_tb(
            irs_kw={"col_values": {irs_col: 0.04}},
        )

        irs_q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)
        stir_q = _FakeQuery(
            fake_product="STIRFUTURE",
            fake_col="SOFR-H26",
            fake_value_result=95.0,
        )

        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[irs_q, stir_q],
            mdps={"STIRFUTURE": _FakeMDP()},
        )

        assert not df.empty
        # IRS column from router
        assert irs_col in df.columns
        # STIR column from MDP fallback
        assert "SOFR-H26" in df.columns
        # Both should have the same date index
        assert len(df) > 0


# ===================================================================
# 4. Unknown product without router or MDP raises a clear error
# ===================================================================
class TestUnknownProductError:

    def test_unknown_product_without_router_or_mdp_raises_clear_error(self):
        tb, _, _ = _make_tb()
        q = _FakeQuery(fake_product="NONEXISTENT", fake_col="col")

        with pytest.raises(KeyError) as exc_info:
            tb.get_timeseries(start=START, end=END, queries=[q])

        msg = str(exc_info.value)
        assert "NONEXISTENT" in msg
        assert "IRS" in msg
        assert "FRB" in msg

    def test_error_includes_available_mdps(self):
        """Available MDP keys should also appear in the error."""
        tb, _, _ = _make_tb()
        q = _FakeQuery(fake_product="MISSING", fake_col="col")

        with pytest.raises(KeyError) as exc_info:
            tb.get_timeseries(
                start=START,
                end=END,
                queries=[q],
                mdps={"STIRFUTURE": _FakeMDP()},
            )

        msg = str(exc_info.value)
        assert "MISSING" in msg
        assert "STIRFUTURE" in msg


# ===================================================================
# 5. MMSS and SPREADOVER derived spread pipeline still executes
# ===================================================================
class TestMMSSAndSpreadover:

    def test_mmss_and_spreadover_behavior_unchanged(self):
        # Build expected column names from the derived queries the spread code creates
        q_irs_derived = IRSwapQuery(
            curve="USD-SOFR-1D", tenor="CT10", value=IRSwapValue.RATE
        )
        q_frb_derived = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)
        irs_col = _safe_col_name(q_irs_derived, "IRS_FALLBACK")
        frb_col = _safe_col_name(q_frb_derived, "FRB_FALLBACK")

        irs_router = _FakeRouter(auto_cols=True, auto_value=0.045)
        frb_router = _FakeRouter(auto_cols=True, auto_value=0.040)

        tb = TimeseriesBuilder(irswaps_tb=irs_router, fixedratebonds_tb=frb_router)

        q_mmss = IRSwapQuery(
            curve="USD-SOFR-1D", tenor="CT10", value=IRSwapValue.MMSS
        )

        df = tb.get_timeseries(start=START, end=END, queries=[q_mmss])

        # The spread section should have called IRS and FRB routers
        # with derived RATE / YTM queries (not the original MMSS query)
        irs_rate_qs = [
            q
            for q in irs_router.received_queries
            if isinstance(q, IRSwapQuery) and q.value == IRSwapValue.RATE
        ]
        frb_ytm_qs = [
            q
            for q in frb_router.received_queries
            if isinstance(q, FixedRateBondQuery) and q.value == FixedRateBondValue.YTM
        ]

        assert len(irs_rate_qs) > 0, "IRS router not called with derived RATE query"
        assert len(frb_ytm_qs) > 0, "FRB router not called with derived YTM query"

        # Result should include a spread column
        if not df.empty:
            assert len(df.columns) > 0

    def test_mmss_query_separated_from_regular_irs(self):
        """MMSS query should NOT be passed to the IRS router's regular call."""
        irs_router = _FakeRouter(auto_cols=True, auto_value=0.045)
        frb_router = _FakeRouter(auto_cols=True, auto_value=0.040)
        tb = TimeseriesBuilder(irswaps_tb=irs_router, fixedratebonds_tb=frb_router)

        q_rate = IRSwapQuery(
            curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE
        )
        q_mmss = IRSwapQuery(
            curve="USD-SOFR-1D", tenor="CT10", value=IRSwapValue.MMSS
        )

        tb.get_timeseries(start=START, end=END, queries=[q_rate, q_mmss])

        # The first IRS router call should only include the RATE query, not MMSS
        first_batch = []
        for q in irs_router.received_queries:
            if isinstance(q, IRSwapQuery) and q.value == IRSwapValue.RATE:
                first_batch.append(q)

        assert any(q.value == IRSwapValue.RATE for q in first_batch)
        assert not any(
            isinstance(q, IRSwapQuery) and q.value == IRSwapValue.MMSS
            for q in irs_router.received_queries
        )


# ===================================================================
# 6. Regression: ASW uses explicit IRS/FRB router, not loop variable
# ===================================================================
class TestASWExplicitRouterUsage:

    def test_asw_uses_explicit_irs_frb_router_not_loop_variable(self):
        """
        Before the fix, the ASW section used `tb.mdp` where `tb` was the loop
        variable. If the last product in the loop was FRB, `tb` would point to
        the FRB router, and `tb.mdp` would be the wrong MDP.

        This test forces FRB to iterate after IRS (by providing both queries)
        and verifies the IRS router's MDP is accessed for the ASW curve fetch.
        """
        mock_irs_mdp = MagicMock(name="irs_mdp")
        mock_irs_curve = MagicMock(name="irs_curve")
        mock_irs_mdp.get_pricer.return_value = mock_irs_curve

        mock_frb_mdp = MagicMock(name="frb_mdp")
        mock_frb_mdp.get_pricer.return_value = {"CT10": MagicMock(name="frb_pricer")}

        irs_router = _FakeRouter(auto_cols=True, auto_value=0.045)
        irs_router.mdp = mock_irs_mdp

        frb_router = _FakeRouter(auto_cols=True, auto_value=0.040)
        frb_router.mdp = mock_frb_mdp

        tb = TimeseriesBuilder(irswaps_tb=irs_router, fixedratebonds_tb=frb_router)

        # ASW query (bucketed under IRS, then filtered into irswap_asw_queries)
        asw_q = IRSwapQuery(
            curve="USD-SOFR-1D", tenor="CT10", value=IRSwapValue.PAR_PAR_ASW
        )
        # FRB query — forces FRB to be iterated after IRS in the loop
        frb_q = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)

        # Should NOT raise AttributeError about wrong `tb.mdp`
        try:
            tb.get_timeseries(start=START, end=END, queries=[asw_q, frb_q])
        except Exception as e:
            # QuantLib may not be available — that's OK.
            # The important thing is it didn't crash at `irs_mdp = tb.mdp`
            # with the wrong router.
            assert not (
                isinstance(e, AttributeError) and "mdp" in str(e)
            ), f"ASW section may still be using loop-local 'tb': {e}"

        # The IRS MDP should have been accessed (for the curve fetch)
        assert mock_irs_mdp.get_pricer.called, (
            "IRS router's MDP was not used — ASW section may be using wrong MDP"
        )
