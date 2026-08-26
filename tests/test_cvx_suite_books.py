"""Tests for RVUtils.CvxSuite.books — the two-book split truth table.

Every gate is violated individually (one row per gate), boundaries are pinned
to the documented strict-vs-inclusive inequalities, NaN inputs refuse, and the
dislocation-over-harvest precedence is tested explicitly. Pure pandas — no
market data, no marks needed.

HARVEST IS THE RECEIVE-BELLY SIDE (DESIGN section 6a item 5, rev_4 finding
1): the gate reads the level-long-signed columns for the SHORT-the-level
holder — ``-rac_net > harvest_min_rac_net`` and ``zs >= -harvest_max_z``.
The pre-fix pair-shape gate ((rac_net > 0) & (zs <= +max_z)) selected rows
where the harvest trade bleeds; the planted-row regression pair from the
review is pinned in ``test_rev4_planted_rows_re_signed_gate``.
"""

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
import pytest

from RVUtils.CvxSuite.books import (
    BOOK_DISLOCATION,
    BOOK_HARVEST,
    BOOK_NONE,
    BookGates,
    REQUIRED_COLUMNS,
    TAG_CLEAN,
    classify_books,
)


def _row(**over):
    """A row that passes NEITHER book; tests flip exactly what they need.

    be_over_rv=1.0 fails harvest (< 1.17); rac_net=+1.0 fails harvest (the
    RECEIVE-belly holder earns -1, §6a item 5); zs=1.0 passes the harvest z
    gate (1.0 >= -0.5) but fails dislocation (|z| < 2.0); edge_bp=0.0 fails
    dislocation; sign_agree=0 and tag="meeting" fail dislocation.
    """
    base = {
        "be_over_rv": 1.0,
        "zs": 1.0,
        "rac_net": 1.0,
        "sign_agree": 0,
        "tag": "meeting",
        "edge_bp": 0.0,
    }
    base.update(over)
    return base


#: Passes harvest on the RECEIVE-belly side: not rich (zs=0.2 >= -0.5), the
#: receive holder earns -rac_net = +0.5 > 0, rent line 1.30 >= 1.17.
HARVEST_OK = dict(be_over_rv=1.30, zs=0.2, rac_net=-0.5)
DISL_OK = dict(zs=-2.5, sign_agree=1, tag=TAG_CLEAN, edge_bp=2.0)


def _classify(rows, gates=None):
    df = pd.DataFrame([_row(**r) for r in rows])
    return classify_books(df, gates or BookGates())


# ------------------------------------------------------------------- defaults


def test_gate_defaults_match_design_section_6():
    """The frozen reference config, verbatim from docs/cvxsuite/DESIGN.md §6.

    §6a item 5 re-signed the harvest gate ORIENTATION (zs >= -max_z,
    -rac_net > min) — the frozen VALUES are unchanged and stay pinned here.

    MUTATION: any default drifting (e.g. harvest_min_be_over_rv 1.17 -> 0.8)
    — the equality asserts fail; these numbers are pre-registered and every
    QDB reference run reads them from here.
    """
    g = BookGates()
    assert g.harvest_min_be_over_rv == 1.17
    assert g.harvest_max_z == 0.5
    assert g.harvest_min_rac_net == 0.0
    assert g.disl_min_abs_z == 2.0
    assert g.disl_min_edge_bp == 1.0
    # field ORDER is contractual — positional construction must land correctly
    pos = BookGates(1.17, 0.5, 0.0, 2.0, 1.0)
    assert pos == g


def test_required_columns_are_the_documented_contract():
    assert REQUIRED_COLUMNS == ("be_over_rv", "zs", "rac_net", "sign_agree", "tag", "edge_bp")


# ---------------------------------------------------------------- truth table


def test_classic_rows_classify_as_documented():
    """One clean exemplar per label.

    The harvest row deliberately carries tag="convexity" and sign_agree=0:
    the convexity zone is harvest-eligible (kink_ledger §2.4 — harvest-only,
    no fades) and harvest has NO tag or agreement gate. MUTATION: adding a
    tag=="clean" condition to the harvest book — the first assert fails.
    """
    out = _classify([
        dict(**HARVEST_OK, tag="convexity", sign_agree=0, edge_bp=np.nan),
        dict(**DISL_OK, be_over_rv=0.5, rac_net=1.0),
        {},  # the base row passes neither
    ])
    assert list(out) == [BOOK_HARVEST, BOOK_DISLOCATION, BOOK_NONE]
    assert out.name == "book"


@pytest.mark.parametrize(
    "violation",
    [
        dict(be_over_rv=1.16),   # below the inclusive 1.17 floor
        dict(zs=-0.6),           # below the inclusive -0.5 LOWER bound
                                 # ("rich for the short" — §6a item 5)
        dict(rac_net=0.0),       # AT the exclusive floor: -0.0 not > 0 —
                                 # strict > per DESIGN §5
        dict(rac_net=0.5),       # the receive side earns -0.5: it bleeds
        dict(be_over_rv=np.nan),
        dict(zs=np.nan),
        dict(rac_net=np.nan),
    ],
)
def test_each_harvest_gate_individually_violated(violation):
    """Start from a passing harvest row, break ONE gate -> "none".

    MUTATION (the rev_4 finding-1 defect, DESIGN §6a item 5): zs gate
    written as the pair-shape UPPER bound (``zs <= +max_z``) — the zs=-0.6
    row passes it (-0.6 <= 0.5) and classifies harvest; fails here.
    MUTATION (same defect): rac gate on the LONG side (``rac_net > min``) —
    the rac_net=+0.5 row classifies harvest AND the control (rac_net=-0.5)
    stops passing; both asserts fail. MUTATION: ``-rac_net > min`` written
    ``>=`` — the rac_net=0.0 row (DESIGN §5 says the harvest holder's carry
    must be STRICTLY positive) classifies harvest and this fails. MUTATION:
    any gate dropped from the conjunction — its violation row classifies
    harvest and fails. NaN rows pin the refusal semantics (a NaN rac_net
    negates to NaN and must still refuse).
    """
    assert _classify([HARVEST_OK])[0] == BOOK_HARVEST  # the control must pass
    assert _classify([dict(HARVEST_OK, **violation)])[0] == BOOK_NONE


@pytest.mark.parametrize(
    "violation",
    [
        dict(zs=-1.9),           # |z| below the inclusive 2.0 floor
        dict(zs=1.9),
        dict(sign_agree=0),      # methods disagree / too small
        dict(sign_agree=np.nan), # missing agreement must NOT pass
        dict(tag="meeting"),     # only "clean" is fadeable
        dict(tag="convexity"),
        dict(edge_bp=1.0),       # AT the exclusive floor — strict > per DESIGN §5
        dict(edge_bp=0.9),
        dict(edge_bp=np.nan),
        dict(zs=np.nan),
    ],
)
def test_each_dislocation_gate_individually_violated(violation):
    """Start from a passing dislocation row, break ONE gate -> "none".

    MUTATION: sign_agree gate written ``!= 0`` — NaN != 0 evaluates True in
    pandas, the sign_agree=NaN row classifies dislocation, and that case
    fails. MUTATION: edge gate written ``>=`` — the edge_bp=1.0 row classifies
    dislocation and fails. MUTATION: ``zs >= disl_min_abs_z`` without abs() —
    the base DISL_OK row (zs=-2.5) stops classifying and its control fails.
    """
    assert _classify([DISL_OK])[0] == BOOK_DISLOCATION  # the control must pass
    assert _classify([dict(DISL_OK, **violation)])[0] == BOOK_NONE


def test_dislocation_boundary_and_both_z_signs_pass():
    """|zs| is two-sided and inclusive: -2.0 and +2.0 both qualify."""
    out = _classify([
        dict(DISL_OK, zs=-2.0),
        dict(DISL_OK, zs=2.0),
        dict(DISL_OK, sign_agree=-1),   # both-rich agreement also qualifies
        dict(DISL_OK, sign_agree=1.0),  # float-typed agreement column
    ])
    assert list(out) == [BOOK_DISLOCATION] * 4


def test_harvest_inclusive_boundaries_pass():
    """be_over_rv == 1.17 and zs == -0.5 (the receive-side lower bound,
    §6a item 5) are documented INCLUSIVE.

    MUTATION: either written strict — these rows fall to "none" and fail.
    MUTATION: the zs bound left at the pre-fix +0.5 UPPER cap — zs=-0.5
    still passes it, but the zs=+0.6 row below (fine for the receive side:
    an even-cheaper belly) would classify none and its assert fails.
    """
    out = _classify([
        dict(HARVEST_OK, be_over_rv=1.17),
        dict(HARVEST_OK, zs=-0.5),       # AT the inclusive lower bound
        dict(HARVEST_OK, zs=0.6),        # above the OLD cap: fine for a short
        dict(HARVEST_OK, rac_net=-1e-9), # -rac_net just above the exclusive floor
    ])
    assert list(out) == [BOOK_HARVEST] * 4


# ----------------------------------------------------------------- precedence


def test_precedence_dislocation_wins_when_both_books_pass():
    """A very cheap belly (zs=+2.5, fly far ABOVE its mean) with receive-side
    carry (+0.5 = -rac_net), favourable be_over_rv, clean tag, agreement and
    edge passes BOTH books; the documented precedence labels it dislocation.
    Under the §6a-item-5 signs the overlap row is economically COHERENT:
    both books take the SAME receive-belly side (the fade of a cheap belly
    IS the harvest direction) — the pre-fix overlap row (zs=-2.5,
    rac_net=+0.5) had the two books on opposite sides of one level.

    MUTATION: swap the np.select condition order (harvest first) — this row
    labels harvest and the assert fails.
    """
    both = dict(be_over_rv=1.5, zs=2.5, rac_net=-0.5,
                sign_agree=1, tag=TAG_CLEAN, edge_bp=2.0)
    out = _classify([both])
    assert out[0] == BOOK_DISLOCATION
    # sanity: it genuinely passes harvest too when the dislocation gates break
    out2 = _classify([dict(both, edge_bp=0.0)])
    assert out2[0] == BOOK_HARVEST


def test_rev4_planted_rows_re_signed_gate():
    """THE rev_4 finding-1 regression pair (DESIGN §6a item 5): the pre-fix
    pair-shape gate ``(rac_net > 0) & (zs <= +0.5)`` labelled "harvest"
    exactly where the RECEIVE-belly harvest trade bleeds and refused where
    it earns.

    Row A ``{zs=-3, rac_net=+5}`` (the review's planted row, tag=convexity
    so dislocation cannot rescue it): shorting a level 3 sigma BELOW its
    own mean with receive-side carry -5bp — the pre-fix gate classified
    this HARVEST; it must now classify NONE. With the dislocation gates
    opened instead (clean tag, both-rich agreement, real edge) the same
    numbers are DISLOCATION-eligible — the pay-belly fade is the only book
    allowed to touch a rich extreme.

    Row B ``{zs=+0.4, rac_net=-5}``: the receive side earns +5bp on a
    not-rich level — the pre-fix gate refused it (rac_net=-5 < 0); it must
    now classify HARVEST.

    MUTATION: reverting either re-signed gate (``zs <= +max_z`` or
    ``rac_net > min``) makes row A classify harvest and/or row B classify
    none — the asserts fail. This is the planted-row construction from the
    verified review evidence, kept verbatim.
    """
    out = _classify([
        dict(be_over_rv=1.5, zs=-3.0, rac_net=5.0, tag="convexity"),
        dict(be_over_rv=1.5, zs=-3.0, rac_net=5.0, tag=TAG_CLEAN,
             sign_agree=-1, edge_bp=2.0),
        dict(be_over_rv=1.5, zs=0.4, rac_net=-5.0),
    ])
    assert list(out) == [BOOK_NONE, BOOK_DISLOCATION, BOOK_HARVEST]


# ------------------------------------------------------------------ mechanics


def test_gate_values_come_from_the_dataclass_not_literals():
    """Tighter custom gates must change the answer.

    MUTATION: any gate read from a hard-coded literal instead of ``gates`` —
    the corresponding flip below fails (harvest_max_z and harvest_min_rac_net
    each get a DEDICATED flip: the all-strict rows fail on be/rac already,
    so a literal 0.5 or 0.0 in those two would otherwise survive).
    """
    strict = BookGates(harvest_min_be_over_rv=2.0, harvest_max_z=0.1,
                       harvest_min_rac_net=1.0, disl_min_abs_z=3.0,
                       disl_min_edge_bp=5.0)
    out = _classify([HARVEST_OK, DISL_OK], gates=strict)
    assert list(out) == [BOOK_NONE, BOOK_NONE]

    # harvest_max_z is read from gates, as the MAGNITUDE of the lower bound:
    # zs=-0.3 passes the default (-0.3 >= -0.5) and fails a tightened 0.2
    z_edge = dict(HARVEST_OK, zs=-0.3)
    assert _classify([z_edge])[0] == BOOK_HARVEST
    assert _classify([z_edge], gates=BookGates(harvest_max_z=0.2))[0] == BOOK_NONE

    # harvest_min_rac_net floors the RECEIVE side's -rac_net: HARVEST_OK
    # earns +0.5 there — above 0.0 (default), not above 0.6
    assert _classify([HARVEST_OK],
                     gates=BookGates(harvest_min_rac_net=0.6))[0] == BOOK_NONE

    loose = BookGates(harvest_min_be_over_rv=0.0, harvest_max_z=10.0,
                      harvest_min_rac_net=-10.0, disl_min_abs_z=0.5,
                      disl_min_edge_bp=-1.0)
    out2 = _classify([{}], gates=loose)  # base row: zs=1.0, tag=meeting, agree=0
    assert out2[0] == BOOK_HARVEST  # harvest opens up (zs >= -10, -rac_net=-1 > -10); dislocation still gated by tag/agreement


def test_missing_column_raises_keyerror_naming_it():
    df = pd.DataFrame([_row()]).drop(columns=["edge_bp"])
    with pytest.raises(KeyError, match="edge_bp"):
        classify_books(df, BookGates())


def test_index_is_preserved_and_dtype_is_object():
    df = pd.DataFrame([_row(**HARVEST_OK), _row(**DISL_OK)],
                      index=["10y1y", "25y5y"])
    out = classify_books(df, BookGates())
    assert list(out.index) == ["10y1y", "25y5y"]
    assert out.dtype == object
    assert out.name == "book"
    assert set(out.unique()) <= {BOOK_HARVEST, BOOK_DISLOCATION, BOOK_NONE}


def test_empty_frame_returns_empty_book_series():
    df = pd.DataFrame(columns=list(REQUIRED_COLUMNS))
    out = classify_books(df, BookGates())
    assert isinstance(out, pd.Series)
    assert len(out) == 0
    assert out.name == "book"


def test_gates_dataclass_is_frozen():
    g = BookGates()
    with pytest.raises(Exception):
        g.harvest_max_z = 99.0
