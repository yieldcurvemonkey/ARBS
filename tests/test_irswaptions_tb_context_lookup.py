r"""``IRSwaptionsTB`` must find the context whichever date type the two sides used.

``IRSwaptionMDP.bulk_get_data`` keys its result by ``datetime.date``.
``build_reference_points`` returns ``datetime.date`` for the ordinary
``start``/``end`` path but ``datetime.datetime`` when the caller passes
``timestamps=``. ``datetime(2026, 7, 27) != date(2026, 7, 27)`` and the two hash
differently, so ``built_map.get(d)`` missed every row on that path - silently,
as one "No swaption context" warning per date and an empty frame.

Found by running a value warm that passed ``timestamps=``: every cube was built
(each logged its round-trip) and every lookup missed.
"""

from __future__ import annotations

import datetime as dt

import pytest

from TB.IRSwaptionsTB import _context_for

D = dt.date(2026, 7, 27)
DT_MIDNIGHT = dt.datetime(2026, 7, 27, 0, 0)
DT_INTRADAY = dt.datetime(2026, 7, 27, 14, 30)
SENTINEL = object()


class TestContextFor:
    def test_exact_date_key(self):
        assert _context_for({D: SENTINEL}, D) is SENTINEL

    def test_datetime_lookup_against_a_date_keyed_map(self):
        """The case that was broken: timestamps= gives datetimes, the MDP gives dates."""
        assert _context_for({D: SENTINEL}, DT_MIDNIGHT) is SENTINEL

    def test_an_intraday_datetime_still_finds_its_day(self):
        assert _context_for({D: SENTINEL}, DT_INTRADAY) is SENTINEL

    def test_date_lookup_against_a_datetime_keyed_map(self):
        """The mirror case, in case a provider ever keys the other way."""
        assert _context_for({DT_MIDNIGHT: SENTINEL}, D) is SENTINEL

    def test_pandas_timestamp_lookup(self):
        pd = pytest.importorskip("pandas")
        assert _context_for({D: SENTINEL}, pd.Timestamp("2026-07-27")) is SENTINEL

    def test_a_genuine_miss_is_still_None(self):
        """The normalisation must not turn 'no data' into 'any data'."""
        assert _context_for({D: SENTINEL}, dt.date(2026, 7, 28)) is None
        assert _context_for({}, D) is None

    def test_it_does_not_match_a_different_day_of_the_same_month(self):
        other = object()
        got = _context_for({D: SENTINEL, dt.date(2026, 7, 28): other}, dt.datetime(2026, 7, 28, 9, 0))
        assert got is other

    def test_the_exact_key_wins_over_the_normalised_one(self):
        exact = object()
        loose = object()
        assert _context_for({DT_INTRADAY: exact, D: loose}, DT_INTRADAY) is exact


class TestGetTimeseriesUsesIt:
    def test_timestamps_argument_no_longer_yields_an_empty_frame(self, monkeypatch, tmp_path):
        """End to end through get_timeseries with a stub MDP that keys by DATE."""
        from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery
        from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure
        from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue
        from TB import IRSwaptionsTB as mod

        days = [dt.date(2026, 7, 27), dt.date(2026, 7, 28)]

        class _StubMDP:
            source = "STUB-QL"

            def bulk_get_data(self, request):
                # exactly what IRSwaptionMDP does: normalise to dates
                return {d: f"ctx-{d}" for d in days}

        built: list = []

        def _row(ctx, q, d):
            built.append((ctx, d))
            return (d, "col", 1.0)

        monkeypatch.setattr(mod, "_build_row_for_query", _row)

        tb = mod.IRSwaptionsTB.__new__(mod.IRSwaptionsTB)
        tb._logger = mod.logging.getLogger("test")
        tb._show_tqdm = False
        tb._date_col = "Date"
        tb.mdp = _StubMDP()
        tb._cache_attr = "_stub_cache"
        setattr(tb, "_stub_cache", {})
        monkeypatch.setattr(mod.IRSwaptionsTB, "batched", lambda self: _NullCtx())
        monkeypatch.setattr(
            mod.IRSwaptionsTB,
            "_build_reference_points",
            lambda self, **kw: [dt.datetime.combine(d, dt.time.min) for d in days],
        )
        monkeypatch.setattr(
            mod.IRSwaptionsTB,
            "_rows_to_frame",
            lambda self, rows: _FakeFrame(rows),
        )

        query = IRSwaptionQuery(
            curve="USD-SOFR-1D",
            shorthand="1Yx10Y",
            strike="ATMF",
            structure=IRSwaptionStructure.PAYER,
            value=IRSwaptionValue.NVOL,
        )
        out = mod.IRSwaptionsTB.get_timeseries(
            tb, start=days[0], end=days[-1], queries=[query],
            timestamps=[dt.datetime.combine(d, dt.time.min) for d in days],
        )
        # the assertion that was false before the fix
        assert len(built) == 2, f"contexts were built but not matched: {built}"
        assert out is not None


class _NullCtx:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


class _FakeFrame:
    def __init__(self, rows):
        self.rows = rows

    def sort_index(self):
        return self
