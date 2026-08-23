"""`ignore_cache_miss` is an IRS-only flag, and every other route drops it.

It reads like a guarantee — "do not go live on a cache miss" — and on a
non-IRS route it does nothing at all. Three warm jobs pass it on FRB routes.
They ARE protected from a live fall-through, but by a different mechanism
entirely: `FixedRateBondsMDP(offline=True)` read off the CONSTRUCTOR, because
`FixedRateBondsTB.bulk_get_data` forwards a fixed kwarg set and nothing
product-specific.

Correct about the outcome, wrong about the reason. That is the kind of
correct-by-accident that stops being correct quietly, so the drop is now said
out loud — once per product, because a warm passes the flag on every query in
every batch.
"""

import logging

import pandas as pd
import pytest

import TB.TimeseriesBuilder as tb_mod


@pytest.fixture(autouse=True)
def _reset_warned():
    tb_mod._IGNORE_CACHE_MISS_WARNED.clear()
    yield
    tb_mod._IGNORE_CACHE_MISS_WARNED.clear()


def test_it_warns_for_a_non_irs_product(caplog):
    with caplog.at_level(logging.WARNING):
        tb_mod._warn_ignore_cache_miss_dropped("FRB")
    messages = [r.getMessage() for r in caplog.records]
    assert any("ignore_cache_miss" in m and "FRB" in m for m in messages), messages


def test_the_message_names_the_mechanism_that_does_work(caplog):
    """A warning that only says 'no' sends the reader looking in the wrong place."""
    with caplog.at_level(logging.WARNING):
        tb_mod._warn_ignore_cache_miss_dropped("FRB")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "offline=True" in text
    assert "DROPPED" in text


def test_it_warns_once_per_product_not_once_per_call(caplog):
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            tb_mod._warn_ignore_cache_miss_dropped("FRB")
        tb_mod._warn_ignore_cache_miss_dropped("USTFUTURE")
    hits = [r for r in caplog.records if "ignore_cache_miss" in r.getMessage()]
    assert len(hits) == 2, [r.getMessage()[:60] for r in hits]


def test_the_product_name_is_normalised():
    tb_mod._warn_ignore_cache_miss_dropped("frb")
    assert "FRB" in tb_mod._IGNORE_CACHE_MISS_WARNED
    # ...and a second spelling of the same product does not warn again.
    before = set(tb_mod._IGNORE_CACHE_MISS_WARNED)
    tb_mod._warn_ignore_cache_miss_dropped("FRB")
    assert tb_mod._IGNORE_CACHE_MISS_WARNED == before


def test_a_missing_product_does_not_raise():
    """Bookkeeping must never be able to break a read."""
    tb_mod._warn_ignore_cache_miss_dropped(None)
    tb_mod._warn_ignore_cache_miss_dropped("")


def test_the_irs_route_still_receives_the_flag(monkeypatch, caplog):
    """The whole point is that IRS is unaffected — no warning, flag forwarded."""
    seen = {}

    class _StubTB:
        def get_timeseries(self, start, end, qs, **kwargs):
            seen.update(kwargs)
            return pd.DataFrame()

    builder = tb_mod.TimeseriesBuilder()
    monkeypatch.setattr(
        builder, "_resolve_product_handles",
        lambda **kw: ("IRS", _StubTB(), None),
    )
    monkeypatch.setattr(
        builder, "_probe_routed_product_computed_cache",
        lambda **kw: (None, None),
    )
    monkeypatch.setattr(
        builder, "_prepare_product_intraday_timestamps", lambda **kw: None
    )
    with caplog.at_level(logging.WARNING):
        builder._route_product_timeseries(
            product="IRS", qs=[], merged_routers={}, merged_mdps={},
            start=None, end=None, n_jobs=1, ignore_cache=False,
            ignore_cache_miss=True, freq=None, timestamps=None,
        )
    assert seen.get("ignore_cache_miss") is True
    assert not [r for r in caplog.records if "ignore_cache_miss" in r.getMessage()]
