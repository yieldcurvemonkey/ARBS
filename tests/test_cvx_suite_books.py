"""Tests for RVUtils.CvxSuite.books — the two-book split truth table.

Every gate is violated individually (one row per gate), boundaries are pinned
to the documented strict-vs-inclusive inequalities, NaN inputs refuse, and the
dislocation-over-harvest precedence is tested explicitly. Pure pandas — no
market data, no marks needed.
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

    zs=1.0 fails harvest (> 0.5) and dislocation (|z| < 2.0); be_over_rv=1.0
    fails harvest; rac_net=-1 fails harvest; edge_bp=0.0 fails dislocation;
    sign_agree=0 and tag="meeting" fail dislocation.
    """
    base = {
        "be_over_rv": 1.0,
        "zs": 1.0,
        "rac_net": -1.0,
        "sign_agree": 0,
        "tag": "meeting",
        "edge_bp": 0.0,
    }
    base.update(over)
    return base


HARVEST_OK = dict(be_over_rv=1.30, zs=0.2, rac_net=0.5)
DISL_OK = dict(zs=-2.5, sign_agree=1, tag=TAG_CLEAN, edge_bp=2.0)


def _classify(rows, gates=None):
    df = pd.DataFrame([_row(**r) for r in rows])
    return classify_books(df, gates or BookGates())


# ------------------------------------------------------------------- defaults


def test_gate_defaults_match_design_section_6():
    """The frozen reference config, verbatim from docs/cvxsuite/DESIGN.md §6.

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
        dict(**DISL_OK, be_over_rv=0.5, rac_net=-1.0),
        {},  # the base row passes neither
    ])
    assert list(out) == [BOOK_HARVEST, BOOK_DISLOCATION, BOOK_NONE]
    assert out.name == "book"


@pytest.mark.parametrize(
    "violation",
    [
        dict(be_over_rv=1.16),   # below the inclusive 1.17 floor
        dict(zs=0.6),            # above the inclusive +0.5 cap ("z not rich")
        dict(rac_net=0.0),       # AT the exclusive floor — strict > per DESIGN §5
        dict(rac_net=-0.5),
        dict(be_over_rv=np.nan),
        dict(zs=np.nan),
        dict(rac_net=np.nan),
    ],
)
def test_each_harvest_gate_individually_violated(violation):
    """Start from a passing harvest row, break ONE gate -> "none".

    MUTATION: rac_net gate written ``>=`` instead of ``>`` — the rac_net=0.0
    row (DESIGN §5 says "rac_net@FPT > 0") classifies harvest and this fails.
    MUTATION: any gate dropped from the conjunction — its violation row
    classifies harvest and fails. NaN rows pin the refusal semantics.
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
    """be_over_rv == 1.17 and zs == +0.5 are documented INCLUSIVE.

    MUTATION: either written strict — these rows fall to "none" and fail.
    """
    out = _classify([
        dict(HARVEST_OK, be_over_rv=1.17),
        dict(HARVEST_OK, zs=0.5),
        dict(HARVEST_OK, rac_net=1e-9),  # just above the exclusive floor
    ])
    assert list(out) == [BOOK_HARVEST] * 3


# ----------------------------------------------------------------- precedence


def test_precedence_dislocation_wins_when_both_books_pass():
    """A very cheap kink (zs=-2.5) with positive rac_net, favourable
    be_over_rv, clean tag, agreement and edge passes BOTH books; the
    documented precedence labels it dislocation.

    MUTATION: swap the np.select condition order (harvest first) — this row
    labels harvest and the assert fails.
    """
    both = dict(be_over_rv=1.5, zs=-2.5, rac_net=0.5,
                sign_agree=1, tag=TAG_CLEAN, edge_bp=2.0)
    out = _classify([both])
    assert out[0] == BOOK_DISLOCATION
    # sanity: it genuinely passes harvest too when the dislocation gates break
    out2 = _classify([dict(both, edge_bp=0.0)])
    assert out2[0] == BOOK_HARVEST


# ------------------------------------------------------------------ mechanics


def test_gate_values_come_from_the_dataclass_not_literals():
    """Tighter custom gates must change the answer.

    MUTATION: any gate read from a hard-coded literal instead of ``gates`` —
    the corresponding flip below fails.
    """
    strict = BookGates(harvest_min_be_over_rv=2.0, harvest_max_z=0.1,
                       harvest_min_rac_net=1.0, disl_min_abs_z=3.0,
                       disl_min_edge_bp=5.0)
    out = _classify([HARVEST_OK, DISL_OK], gates=strict)
    assert list(out) == [BOOK_NONE, BOOK_NONE]

    loose = BookGates(harvest_min_be_over_rv=0.0, harvest_max_z=10.0,
                      harvest_min_rac_net=-10.0, disl_min_abs_z=0.5,
                      disl_min_edge_bp=-1.0)
    out2 = _classify([{}], gates=loose)  # base row: zs=1.0, tag=meeting, agree=0
    assert out2[0] == BOOK_HARVEST  # harvest opens up; dislocation still gated by tag/agreement


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
