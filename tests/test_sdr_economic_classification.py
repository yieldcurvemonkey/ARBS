"""Phase 3 tests: Economic-vs-Administrative classification matrix.

One test per matrix row + property tests + integration.
"""
from __future__ import annotations

import pandas as pd
import pytest

from SDRUtils.core.economic_classification import (
    MATRIX,
    EconomicKind,
    classify_event,
    enrich_economic_class,
    filter_economic,
)


class TestMatrixRows:
    """Each Action×Event produces the expected kind."""

    def test_NEWT_TRAD(self):
        c = classify_event("NEWT", "TRAD", None)
        assert c.kind == EconomicKind.ECONOMIC_FLOW
        assert c.contributes_to_flow is True
        assert c.contributes_to_volume is True

    def test_NEWT_NOVA(self):
        c = classify_event("NEWT", "NOVA", None)
        assert c.kind == EconomicKind.ADMINISTRATIVE
        assert c.contributes_to_flow is False

    def test_NEWT_CLRG(self):
        c = classify_event("NEWT", "CLRG", None)
        assert c.kind == EconomicKind.ADMINISTRATIVE
        assert c.on_p43 is False

    def test_NEWT_ALOC(self):
        assert classify_event("NEWT", "ALOC", None).kind == EconomicKind.ADMINISTRATIVE

    def test_NEWT_EXER(self):
        c = classify_event("NEWT", "EXER", None)
        assert c.kind == EconomicKind.ECONOMIC_FLOW

    def test_NEWT_PTNG(self):
        c = classify_event("NEWT", "PTNG", None)
        assert c.kind == EconomicKind.ADMINISTRATIVE

    def test_TERM_TRAD(self):
        c = classify_event("TERM", "TRAD", None)
        assert c.kind == EconomicKind.ECONOMIC_UNWIND
        assert c.contributes_to_flow is True

    def test_TERM_ETRM(self):
        assert classify_event("TERM", "ETRM", None).kind == EconomicKind.ECONOMIC_UNWIND

    def test_TERM_NOVA(self):
        assert classify_event("TERM", "NOVA", None).kind == EconomicKind.ADMINISTRATIVE

    def test_TERM_CLRG_alpha(self):
        assert classify_event("TERM", "CLRG", None).kind == EconomicKind.ADMINISTRATIVE

    def test_TERM_COMP(self):
        c = classify_event("TERM", "COMP", None)
        assert c.kind == EconomicKind.ADMINISTRATIVE
        assert c.contributes_to_flow is False

    def test_MODI_TRAD_amend_true(self):
        c = classify_event("MODI", "TRAD", True)
        assert c.kind == EconomicKind.ECONOMIC_AMENDMENT
        assert c.contributes_to_pnl_as_delta is True

    def test_MODI_TRAD_amend_false(self):
        c = classify_event("MODI", "TRAD", False)
        assert c.kind == EconomicKind.ADMINISTRATIVE

    def test_MODI_TRAD_amend_false_schedule_step(self):
        c = classify_event("MODI", "TRAD", False, is_schedule_step=True)
        assert c.kind == EconomicKind.ADMINISTRATIVE
        assert "scheduled amortization" in c.reason.lower()

    def test_MODI_NOVA_partial(self):
        c = classify_event("MODI", "NOVA", None)
        assert c.kind == EconomicKind.ADMINISTRATIVE

    def test_PRTO_PTNG(self):
        c = classify_event("PRTO", "PTNG", None)
        assert c.kind == EconomicKind.ADMINISTRATIVE

    def test_CORR(self):
        c = classify_event("CORR", "TRAD", None)
        assert c.kind == EconomicKind.RESTATEMENT

    def test_EROR(self):
        c = classify_event("EROR", None, None)
        assert c.kind == EconomicKind.ERROR

    def test_REVI(self):
        c = classify_event("REVI", None, None)
        assert c.kind == EconomicKind.ERROR_RECOVERY

    def test_VALU(self):
        c = classify_event("VALU", None, None)
        assert c.kind == EconomicKind.VALUATION
        assert c.on_p43 is False

    def test_MARU(self):
        c = classify_event("MARU", None, None)
        assert c.kind == EconomicKind.VALUATION


class TestOverrides:
    """Overrides (prime brokerage, AFFL, compression) map to ADMIN."""

    def test_prime_brokerage_forces_admin(self):
        c = classify_event("NEWT", "TRAD", None, prime_brokerage=True)
        assert c.kind == EconomicKind.ADMINISTRATIVE

    def test_affl_clearing_exception_forces_admin(self):
        c = classify_event("NEWT", "TRAD", None, clearing_exception="AFFL")
        assert c.kind == EconomicKind.ADMINISTRATIVE

    def test_compression_newt_becomes_admin(self):
        c = classify_event("NEWT", "COMP", None, is_compression=True)
        assert c.kind == EconomicKind.ADMINISTRATIVE

    def test_unmapped_falls_to_unknown(self):
        c = classify_event("FOO", "BAR", None)
        assert c.kind == EconomicKind.UNKNOWN


class TestInvariants:
    """ADMINISTRATIVE rows never contribute to flow/volume/pnl."""

    @pytest.mark.parametrize(
        "action,event,amendment",
        [
            ("NEWT", "NOVA", None),
            ("NEWT", "CLRG", None),
            ("NEWT", "COMP", None),
            ("TERM", "NOVA", None),
            ("TERM", "CLRG", None),
            ("TERM", "COMP", None),
            ("MODI", "TRAD", False),
            ("PRTO", "PTNG", None),
        ],
    )
    def test_admin_rows_all_false(self, action, event, amendment):
        c = classify_event(action, event, amendment)
        assert c.contributes_to_flow is False
        assert c.contributes_to_volume is False
        assert c.contributes_to_pnl is False
        assert c.contributes_to_pnl_as_delta is False


class TestEnrichDataFrame:
    def _make_df(self, rows: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_enrich_materializes_all_columns(self):
        df = self._make_df(
            [
                {"event_action": "NEWT-TRAD", "amendment_indicator": None},
                {"event_action": "TERM-COMP", "amendment_indicator": None},
                {"event_action": "VALU-", "amendment_indicator": None},
            ]
        )
        df = enrich_economic_class(df)
        assert "economic_class" in df.columns
        assert "contributes_to_flow" in df.columns
        assert "contributes_to_volume" in df.columns
        assert "contributes_to_pnl" in df.columns
        assert "contributes_to_pnl_as_delta" in df.columns
        assert "on_p43" in df.columns
        assert "economic_class_reason" in df.columns

    def test_enrich_compression_row_not_flow(self):
        df = self._make_df(
            [
                {"event_action": "TERM-COMP", "amendment_indicator": None, "is_compression": True},
                {"event_action": "NEWT-TRAD", "amendment_indicator": None, "is_compression": False},
            ]
        )
        df = enrich_economic_class(df)
        assert bool(df.iloc[0]["contributes_to_flow"]) is False
        assert bool(df.iloc[1]["contributes_to_flow"]) is True

    def test_enrich_prime_brokerage_forces_admin(self):
        df = self._make_df(
            [
                {
                    "event_action": "NEWT-TRAD",
                    "amendment_indicator": None,
                    "prime_brokerage_transaction_indicator": True,
                },
            ]
        )
        df = enrich_economic_class(df)
        assert df.iloc[0]["economic_class"] == EconomicKind.ADMINISTRATIVE.value

    def test_enrich_affl_clearing_exception_forces_admin(self):
        df = self._make_df(
            [{"event_action": "NEWT-TRAD", "amendment_indicator": None, "clearing_exception": "AFFL"}]
        )
        df = enrich_economic_class(df)
        assert df.iloc[0]["economic_class"] == EconomicKind.ADMINISTRATIVE.value

    def test_filter_flow(self):
        df = self._make_df(
            [
                {"event_action": "NEWT-TRAD", "amendment_indicator": None},
                {"event_action": "TERM-COMP", "amendment_indicator": None, "is_compression": True},
                {"event_action": "VALU-", "amendment_indicator": None},
            ]
        )
        df = enrich_economic_class(df)
        out = filter_economic(df, "flow")
        assert len(out) == 1
        assert out.iloc[0]["event_action"] == "NEWT-TRAD"

    def test_empty_frame_gets_columns(self):
        df = pd.DataFrame(
            columns=[
                "event_action",
                "amendment_indicator",
            ]
        )
        df = enrich_economic_class(df)
        assert "economic_class" in df.columns


class TestMatrixCompleteness:
    """Every combo we observed in the plan's §5.2 matrix has a mapping."""

    def test_matrix_non_empty(self):
        assert len(MATRIX) >= 20

    def test_every_matrix_admin_row_zero_contribution(self):
        for (act, evt), cls in MATRIX.items():
            if cls.kind == EconomicKind.ADMINISTRATIVE:
                assert cls.contributes_to_flow is False, f"{act}-{evt} admin leaked flow"
                assert cls.contributes_to_volume is False
                assert cls.contributes_to_pnl is False
