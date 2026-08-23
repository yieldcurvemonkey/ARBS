"""A vendor serving less is a report, not a failed store warm.

`_report_coverage_regression` fires when bonds that answered last night have
gone quiet. It used to RAISE, and because the job it runs in is a STORE
provider, the runner then marked its asset blocking and skipped every consumer.

Measured on the 2026-08-23 catch-up: 7 bonds of 877, all losing ASW_4_GBP /
ASW_4_CHF / ASW_4_EUR — the cross-currency asset-swap matrix, the thinnest
family Citi publishes. On the strength of that, both UST value jobs were
skipped. The warm had COMPLETED; the tag cache is cumulative; the consumers had
everything they needed.

So: record it, name it in SUMMARY, move the run to exit 2, and leave the asset
alone. A genuinely outage-sized regression still fails, because the consumers
build offline and a wide gap becomes empty columns that read as days the vendor
served nothing.
"""

import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def warmer():
    spec = importlib.util.spec_from_file_location(
        "daily_cache_warmer_coverage_under_test",
        os.path.join(REPO_ROOT, "scripts", "daily_cache_warmer.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clear_skips(warmer):
    warmer._SUBPROCESS_SKIPS.clear()
    yield
    warmer._SUBPROCESS_SKIPS.clear()


def _out(n_regressed, universe=877):
    return {
        "of": universe,
        "done": universe,
        "regressed": {
            f"US91282C{i:04d}": ["ASW_4_GBP"] for i in range(n_regressed)
        },
    }


def test_no_regression_records_nothing(warmer):
    warmer._report_coverage_regression({"of": 877, "regressed": {}}, "EOD")
    assert warmer._SUBPROCESS_SKIPS == []


def test_a_thin_regression_is_recorded_not_raised(warmer):
    """The measured case: 7 of 877."""
    warmer._report_coverage_regression(_out(7), "EOD")
    assert len(warmer._SUBPROCESS_SKIPS) == 1
    step = warmer._SUBPROCESS_SKIPS[0]
    assert step.returncode == "COVERAGE"
    assert "7 of 877" in step.detail


def test_the_recorded_step_renders_readably(warmer):
    warmer._report_coverage_regression(_out(7), "EOD")
    text = warmer._describe_step_failure(warmer._SUBPROCESS_SKIPS[0])
    assert "thinned" in text, text
    assert "was not run" not in text, "a completed warm did not fail to run"


def test_an_outage_sized_regression_still_fails(warmer):
    """At some size it stops being noise: the consumers build OFFLINE."""
    with pytest.raises(RuntimeError, match="past the point"):
        warmer._report_coverage_regression(_out(400), "EOD")


def test_the_324_of_877_false_alarm_would_have_been_a_failure(warmer):
    """Sanity on where the line sits, against the case that started this."""
    with pytest.raises(RuntimeError):
        warmer._report_coverage_regression(_out(324), "EOD")


def test_the_boundary_is_the_configured_fraction(warmer, monkeypatch):
    monkeypatch.setattr(warmer, "_CV_COVERAGE_FAIL_FRACTION", 0.5)
    warmer._report_coverage_regression(_out(400), "EOD")   # 45.6%, under 50%
    assert len(warmer._SUBPROCESS_SKIPS) == 1
    with pytest.raises(RuntimeError):
        warmer._report_coverage_regression(_out(500), "EOD")  # 57%


def test_an_unknown_universe_size_fails_closed(warmer):
    """If the size is unknowable, treat it as an outage rather than as noise."""
    with pytest.raises(RuntimeError):
        warmer._report_coverage_regression({"of": 0, "regressed": {"X": ["ASW"]}}, "EOD")


def test_the_store_asset_is_not_disowned_by_a_thin_regression(warmer):
    """The whole point: consumers must still run.

    A SKIPPED STEP moves the run to exit 2 without touching `unmet`, which is
    what the runner reads to decide whether to skip a consumer. A raise from
    inside the job body is what marks the asset blocking.
    """
    warmer._report_coverage_regression(_out(7), "EOD")
    # No exception propagated, so the job returns normally and `provides` stays
    # satisfied. The step is still visible.
    assert warmer._SUBPROCESS_SKIPS
    assert all(s.returncode == "COVERAGE" for s in warmer._SUBPROCESS_SKIPS)
