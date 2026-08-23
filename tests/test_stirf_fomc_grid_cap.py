"""The mixed-STIRT grid must not ask for an FOMC meeting that does not exist.

`_MIXED_STIRT_FOMC_COUNT` is 12 and the published FOMC calendar does not always
reach twelve meetings ahead. `resolve_central_bank_tenor` RAISES past the end of
it, and the pricing loop catches that per (tenor, timestamp) — so the grid asked
for a tenor it could never have, once per session minute.

Measured on the 2026-08-21 run: 1,381 pricing failures, every one of them
`fomc_12`, one per minute of the session, on
`USD-OIS-Q12xM12STIRT-SERFFX-MIX23`. The curve then reported
`ts_cols=44 ts_failed=0` — the failures never reached the summary, which is why
it ran nightly and looked clean.
"""

import datetime as dt
import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURVE = "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"


@pytest.fixture(scope="module")
def service():
    spec = importlib.util.spec_from_file_location(
        "stirf_curve_service_under_test",
        os.path.join(REPO_ROOT, "scripts", "stirf_curve_service.py"),
    )
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: the module defines dataclasses, and @dataclass
    # looks its own module up in sys.modules while the class body is executing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "anchor",
    [dt.date(2026, 8, 17), dt.date(2026, 8, 21), dt.date(2026, 12, 1), dt.date(2027, 6, 1)],
)
def test_every_emitted_fomc_tenor_actually_resolves(service, anchor):
    """The property that matters: the grid asks for nothing that will raise."""
    from Query.IRSwaps._CENTRAL_BANK_DATES import resolve_central_bank_tenor

    tenors = service._default_tenors_for_curve(CURVE, anchor_date=anchor)
    fomc = [t for t in tenors if t.lower().startswith("fomc_")]
    assert fomc, "the mixed-STIRT grid should still carry FOMC legs"

    unresolvable = []
    for tenor in fomc:
        try:
            resolve_central_bank_tenor("USD-OIS", tenor, as_of=anchor)
        except Exception as exc:  # noqa: BLE001
            unresolvable.append((tenor, type(exc).__name__))
    assert not unresolvable, (
        f"as of {anchor} the grid asks for {unresolvable}, and each of those "
        "fails once per session minute without reaching the summary"
    )


def test_the_ranks_are_contiguous_from_one(service):
    tenors = service._default_tenors_for_curve(CURVE, anchor_date=dt.date(2026, 8, 21))
    ranks = [int(t.split("_")[1]) for t in tenors if t.lower().startswith("fomc_")]
    assert ranks == list(range(1, len(ranks) + 1)), ranks


def test_the_cap_never_exceeds_the_configured_count(service):
    n = service._resolvable_fomc_ranks(CURVE, dt.date(2026, 8, 21))
    assert 0 < n <= service._MIXED_STIRT_FOMC_COUNT


def test_an_earlier_anchor_never_resolves_fewer(service):
    """Why using the run's anchor for a backfilled day is safe.

    Rank N is the Nth meeting at or after the anchor, so an earlier date has
    MORE meetings ahead of it, never fewer. A cap computed at the run's date is
    therefore conservative for every day in the window.
    """
    later = service._resolvable_fomc_ranks(CURVE, dt.date(2026, 8, 21))
    earlier = service._resolvable_fomc_ranks(CURVE, dt.date(2026, 8, 17))
    assert earlier >= later


def test_the_non_mixed_curves_are_untouched(service):
    """Only the mixed-STIRT grid carries FOMC legs; nothing else should change."""
    plain = service._default_tenors_for_curve(
        "USD-SOFR-1D-Q12STIRT", anchor_date=dt.date(2026, 8, 21)
    )
    assert not [t for t in plain if t.lower().startswith("fomc_")]
