"""Marker splicing: regenerating must only ever touch the marked region.

Every failure mode this guards against produces the same bad outcome — a document
holding two generations of numbers with nothing to say which is current — so all of
them raise rather than fall back to appending.
"""
import pytest

from BT.dealer_ladder import report

DOC = """# Title

Prose above.

<!-- BEGIN GENERATED TABLES -->

_pending_

<!-- END GENERATED TABLES -->

Prose below.
"""


def test_splice_replaces_only_the_marked_region():
    out = report.splice(DOC, "GENERATED TABLES", "| a |\n|---|\n| 1 |")
    assert out.startswith("# Title\n\nProse above.")
    assert out.rstrip().endswith("Prose below.")
    assert "_pending_" not in out
    assert "| a |" in out


def test_splice_is_idempotent():
    once = report.splice(DOC, "GENERATED TABLES", "BODY-1")
    twice = report.splice(once, "GENERATED TABLES", "BODY-1")
    assert once == twice
    thrice = report.splice(twice, "GENERATED TABLES", "BODY-2")
    assert "BODY-1" not in thrice and "BODY-2" in thrice


def test_a_missing_marker_raises_rather_than_appending():
    """Appending would leave the previous generation above the new one."""
    with pytest.raises(report.MarkerError, match="exactly one"):
        report.splice("# Title\n\nno markers here\n", "GENERATED TABLES", "BODY")


def test_duplicated_markers_raise():
    doubled = DOC + DOC
    with pytest.raises(report.MarkerError, match="exactly one"):
        report.splice(doubled, "GENERATED TABLES", "BODY")


def test_markers_out_of_order_raise():
    swapped = ("<!-- END GENERATED TABLES -->\nbody\n"
               "<!-- BEGIN GENERATED TABLES -->\n")
    with pytest.raises(report.MarkerError, match="before"):
        report.splice(swapped, "GENERATED TABLES", "BODY")


def test_two_independent_regions_do_not_interfere():
    doc = DOC.replace("Prose below.",
                      "<!-- BEGIN GENERATED COMPLETENESS -->\n\n_pending_\n\n"
                      "<!-- END GENERATED COMPLETENESS -->\n")
    a = report.splice(doc, "GENERATED TABLES", "TABLES-BODY")
    b = report.splice(a, "GENERATED COMPLETENESS", "COMPLETENESS-BODY")
    assert "TABLES-BODY" in b and "COMPLETENESS-BODY" in b
    assert b.index("TABLES-BODY") < b.index("COMPLETENESS-BODY")


def test_inject_writes_the_file(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(DOC, encoding="utf-8")
    report.inject(str(path), "GENERATED TABLES", "NEW BODY")
    assert "NEW BODY" in path.read_text(encoding="utf-8")
    assert "_pending_" not in path.read_text(encoding="utf-8")


def test_inject_on_a_missing_file_raises(tmp_path):
    with pytest.raises(report.MarkerError, match="does not exist"):
        report.inject(str(tmp_path / "nope.md"), "GENERATED TABLES", "BODY")


def test_body_whitespace_is_normalised_so_the_diff_stays_small():
    a = report.splice(DOC, "GENERATED TABLES", "BODY")
    b = report.splice(DOC, "GENERATED TABLES", "\n\n  BODY  \n\n")
    assert a == b


def test_the_real_findings_doc_has_both_regions():
    """A guard on the deliverable itself: if either marker pair is lost in an edit,
    the generators would raise at the worst possible moment."""
    import os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "docs", "superpowers", "plans",
        "2026-07-30-dealer-ladder-signal-findings.md")
    text = open(path, encoding="utf-8").read()
    for name in ("GENERATED TABLES", "GENERATED COMPLETENESS"):
        begin, end = report.markers(name)
        assert text.count(begin) == 1, name
        assert text.count(end) == 1, name
        assert text.index(begin) < text.index(end), name
