"""The CA label vocabulary the CA-vs-fly block trades from.

Two bundle vocabularies coexist and MUST NOT collapse into each other:

* legacy ``BUNDLE{b}`` -- a 16-quarter window starting at rank ``1+4(b-1)``
  (``BUNDLE2`` = ranks 5..20). Panels were built against it.
* CME ``BUNDLE{N}Y`` -- the front-anchored strip of the first ``4N``
  quarterlies (CME: "integer multiples of 4 contracts spanning 2 to 5 years").

A notebook that says "bundle" and silently means the other object measures a
different instrument, so these tests pin both vocabularies side by side.
"""
import datetime

import pytest

from TB.IRSwapsTB import (
    CVX_PACK_MAP,
    _cvx_col_name,
    _cvx_imm_code_from_date_rank,
    _cvx_pack_span,
    _cvx_ranks_for_label,
    _cvx_structure_tag,
)


class TestCmeBundleVocabulary:
    @pytest.mark.parametrize("label,span", [
        ("BUNDLE1Y", (1, 4)),
        ("BUNDLE2Y", (1, 8)),
        ("BUNDLE3Y", (1, 12)),
        ("BUNDLE4Y", (1, 16)),
        ("BUNDLE5Y", (1, 20)),
    ])
    def test_front_anchored_span(self, label, span):
        assert _cvx_pack_span(label) == span
        assert _cvx_ranks_for_label(label) == list(range(span[0], span[1] + 1))

    def test_case_insensitive(self):
        assert _cvx_pack_span("bundle3y") == (1, 12)

    def test_structure_tag_is_bundles(self):
        assert _cvx_structure_tag("BUNDLE2Y") == "BUNDLES"
        assert _cvx_col_name("USD-SOFR-1D", "BUNDLE2Y") == (
            "USD-SOFR-1D BUNDLE2Y BUNDLES CVX_ADJ")

    def test_bundle1y_is_the_whites_window(self):
        """The 1y bundle and the Whites pack are the same four contracts."""
        assert _cvx_pack_span("BUNDLE1Y") == CVX_PACK_MAP["WHITES"]


class TestLegacyBundleVocabularyUnchanged:
    """The CME labels must not have moved the legacy windows."""

    @pytest.mark.parametrize("label,span", [
        ("BUNDLE1", (1, 16)),
        ("BUNDLE2", (5, 20)),
        ("BUNDLE3", (9, 24)),
    ])
    def test_legacy_span(self, label, span):
        assert _cvx_pack_span(label) == span

    def test_the_two_vocabularies_disagree_where_they_must(self):
        """BUNDLE2 and BUNDLE2Y are DIFFERENT windows -- the whole reason the
        second vocabulary exists. If this ever passes with equal spans, one
        label has silently absorbed the other."""
        assert _cvx_pack_span("BUNDLE2") != _cvx_pack_span("BUNDLE2Y")
        assert _cvx_pack_span("BUNDLE2") == (5, 20)
        assert _cvx_pack_span("BUNDLE2Y") == (1, 8)


class TestVocabularyRejectsJunk:
    @pytest.mark.parametrize("label", [
        "BUNDLE0Y",     # zero-length bundle is not a thing
        "BUNDLE10Y",    # beyond the single-digit CME ladder
        "BUNDLE2X",     # not a vocabulary
        "PACK3",        # never was one
        "",
    ])
    def test_unknown_labels_return_none(self, label):
        assert _cvx_pack_span(label) is None
        assert _cvx_ranks_for_label(label) is None


class TestRankToContractMap:
    def test_bundle2y_contracts_tile_the_first_two_years(self):
        """Ranks 1..8 on a fixed date resolve to 8 consecutive quarterlies."""
        d = datetime.date(2024, 7, 1)
        codes = [_cvx_imm_code_from_date_rank(d, r) for r in range(1, 9)]
        assert len(set(codes)) == 8
        assert codes[0] == "U24"
        assert codes[-1] == "M26"
