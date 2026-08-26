"""Tests for RVUtils.CvxSuite.vols — cube ATM reads, realized vol, units.

Pure tests run against a duck-typed fake store (planted grids with exact
bilinear answers); the integration class reads the real
``USD-SWAPTIONVOL-CITIVELOEXCEL`` store (2,711 days on this machine) and
self-skips when absent. Every planted answer carries a negative control.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")  # before any repo import

import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.CvxSuite import vols

SQRT252 = math.sqrt(252.0)


# ---------------------------------------------------------------------------
# Fake store
# ---------------------------------------------------------------------------
class FakeStore:
    """Duck-typed SwaptionCubeStore: ``read_day(asset, day, *, _allow_l2)``."""

    def __init__(self, frames):
        # frames: {datetime.date: DataFrame | None}
        self.frames = dict(frames)
        self.calls = []

    def read_day(self, asset, day, *, _allow_l2=True):
        d = pd.Timestamp(day).date()
        self.calls.append({"asset": asset, "day": d, "_allow_l2": _allow_l2})
        return self.frames.get(d)


def stored_frame(nodes, extra_offset_rows=()):
    """Stored-schema long frame: (expiry, tenor, offset_bp, vol_bp)."""
    rows = [{"expiry": e, "tenor": t, "offset_bp": 0.0, "vol_bp": v}
            for (e, t, v) in nodes]
    rows += [{"expiry": e, "tenor": t, "offset_bp": o, "vol_bp": v}
             for (e, t, o, v) in extra_offset_rows]
    f = pd.DataFrame(rows)
    f["vol_unit"] = "bp"
    return f


D1 = dt.date(2026, 8, 21)
D2 = dt.date(2026, 8, 22)   # deliberately absent day
D3 = dt.date(2026, 8, 24)

GRID_2X2 = [("1Y", "5Y", 100.0), ("1Y", "10Y", 110.0),
            ("2Y", "5Y", 120.0), ("2Y", "10Y", 130.0)]
# 999/1 vols at non-zero offsets: poison that the ATM filter must ignore.
OFFSET_POISON = [("1Y", "5Y", 25.0, 999.0), ("1Y", "5Y", -25.0, 1.0)]
GRID_3EXP = GRID_2X2 + [("5Y", "5Y", 200.0), ("5Y", "10Y", 210.0)]


def make_store():
    return FakeStore({D1: stored_frame(GRID_2X2, OFFSET_POISON),
                      D3: stored_frame(GRID_3EXP)})


# ---------------------------------------------------------------------------
# Unit converters
# ---------------------------------------------------------------------------
class TestConversions:
    def test_known_anchor(self):
        """100 bp/yr = 100/sqrt(252) = 6.299407883487121 bp/day.

        MUTATION: sqrt(252) -> 252 (or a no-op) — the anchor assert catches
        it; the negative controls pin the two nearby wrong constants.
        """
        got = vols.bp_year_to_day(100.0)
        assert got == pytest.approx(6.299407883487121, rel=1e-12)
        # negative controls: the classic wrong denominators must NOT match
        assert abs(got - 100.0 / 252.0) > 1e-3          # divided by 252
        assert abs(got - 100.0) > 1e-3                   # no conversion
        assert abs(got - 100.0 / 16.0) > 1e-3            # sqrt(256) slip

    def test_round_trip_identity(self):
        assert vols.bp_day_to_year(vols.bp_year_to_day(84.727)) == pytest.approx(84.727, rel=1e-12)
        assert vols.bp_day_to_year(1.0) == pytest.approx(SQRT252, rel=1e-12)

    def test_w3_band_maps_into_guard_band(self):
        """w3 evidence: 50-200 bp/yr is 3.15-12.60 bp/day, inside 0.5-40."""
        lo, hi = vols.bp_year_to_day(50.0), vols.bp_year_to_day(200.0)
        assert lo == pytest.approx(3.1497039417435605, rel=1e-12)
        assert hi == pytest.approx(12.598815766974242, rel=1e-12)
        assert 0.5 <= lo <= hi <= 40.0

    def test_series_passthrough(self):
        s = pd.Series([SQRT252, 2 * SQRT252])
        out = vols.bp_year_to_day(s)
        assert isinstance(out, pd.Series)
        assert out.tolist() == pytest.approx([1.0, 2.0], rel=1e-12)


# ---------------------------------------------------------------------------
# Realized vol (bp/day)
# ---------------------------------------------------------------------------
class TestRealizedVol:
    def test_known_answer_ddof1_not_annualised(self):
        """diffs [1,-1,1,-1]: std(ddof=1) = sqrt(4/3) = 1.1547005383792515.

        MUTATION: ddof=1 -> ddof=0 — caught (would give exactly 1.0).
        MUTATION: multiply by sqrt(252) (citi_screen's bp/yr form) — caught
        (would give 18.33).
        """
        idx = pd.bdate_range("2024-01-01", periods=5)
        x = pd.Series([0.0, 1.0, 0.0, 1.0, 0.0], index=idx)
        out = vols.realized_vol_bp_day(x, window=4, min_periods=4)
        got = out.iloc[-1]
        assert got == pytest.approx(math.sqrt(4.0 / 3.0), abs=1e-12)
        # negative controls
        assert abs(got - 1.0) > 1e-3                       # ddof=0 mutation
        assert abs(got - math.sqrt(4.0 / 3.0) * SQRT252) > 1.0   # annualised
        # ramp-in: not enough diffs before the window fills
        assert out.iloc[:-1].isna().all()

    def test_ex_dates_list_masks_the_jump(self):
        """A level shift INTO the ex date must vanish from the vol.

        Flat at 100, jumps to 110 at idx[5]. With ex_dates=[idx[5]] every
        surviving diff is 0.0 so the trailing std is exactly 0.0.
        MUTATION: mask the day after (idx[6]) instead — the +10 diff at
        idx[5] survives and the assert == 0.0 fails.
        MUTATION: drop the mask entirely — the without-mask control shows a
        strictly positive vol, and the masked assert fails.
        """
        idx = pd.bdate_range("2024-01-01", periods=10)
        lv = pd.Series([100.0] * 5 + [110.0] * 5, index=idx)
        masked = vols.realized_vol_bp_day(lv, window=6, min_periods=3,
                                          ex_dates=[idx[5]])
        assert masked.iloc[-1] == 0.0
        unmasked = vols.realized_vol_bp_day(lv, window=6, min_periods=3)
        assert unmasked.iloc[-1] > 1.0  # the roll jump measured, not the market

    def test_ex_dates_accepts_datetime_date(self):
        """datetime.date entries must match a Timestamp index (normalised)."""
        idx = pd.bdate_range("2024-01-01", periods=10)
        lv = pd.Series([100.0] * 5 + [110.0] * 5, index=idx)
        out = vols.realized_vol_bp_day(lv, window=6, min_periods=3,
                                       ex_dates=[idx[5].date()])
        assert out.iloc[-1] == 0.0

    def test_ex_dates_boolean_series(self):
        """citi_screen's is_roll idiom: boolean Series, reindexed, NaN->False."""
        idx = pd.bdate_range("2024-01-01", periods=10)
        lv = pd.Series([100.0] * 5 + [110.0] * 5, index=idx)
        flag = pd.Series(False, index=idx)
        flag.iloc[5] = True
        out = vols.realized_vol_bp_day(lv, window=6, min_periods=3, ex_dates=flag)
        assert out.iloc[-1] == 0.0
        # a partial series (missing labels) must behave as False, not raise
        out2 = vols.realized_vol_bp_day(lv, window=6, min_periods=3,
                                        ex_dates=flag.iloc[4:7])
        assert out2.iloc[-1] == 0.0

    def test_min_periods_gate(self):
        idx = pd.bdate_range("2024-01-01", periods=50)
        lv = pd.Series(np.linspace(0, 10, 50), index=idx)
        out = vols.realized_vol_bp_day(lv)   # window=252, min_periods=100
        assert out.isna().all()


# ---------------------------------------------------------------------------
# Units guard
# ---------------------------------------------------------------------------
class TestUnitsMedianGuard:
    def test_passes_in_band_and_returns_none(self):
        s = pd.Series([4.0, 5.0, 6.0])
        assert vols.units_median_guard(s) is None

    def test_boundaries_inclusive(self):
        assert vols.units_median_guard(pd.Series([0.5, 0.5])) is None
        assert vols.units_median_guard(pd.Series([40.0, 40.0])) is None

    def test_raises_naming_median_on_bp_year_leak(self):
        """A bp/yr series (median 84.70) must raise and NAME the median.

        MUTATION: drop the raise, or flip the comparison — pytest.raises
        fails. MUTATION: stop naming the median — the '84.70' substring
        assert fails (the w3 pattern names the number so the log is
        diagnosable).
        """
        s = pd.Series([80.0, 84.7, 90.0])
        with pytest.raises(ValueError) as ei:
            vols.units_median_guard(s)
        msg = str(ei.value)
        assert "84.70" in msg
        assert "bp/DAY" in msg
        assert "sqrt(252)" in msg

    def test_raises_below_band(self):
        with pytest.raises(ValueError):
            vols.units_median_guard(pd.Series([0.1, 0.2, 0.1]))

    def test_raises_on_empty_and_all_nan(self):
        """Deliberate divergence from w3: no evidence is not a pass."""
        with pytest.raises(ValueError):
            vols.units_median_guard(pd.Series(dtype=float))
        with pytest.raises(ValueError):
            vols.units_median_guard(pd.Series([np.nan, np.nan]))

    def test_nan_head_is_skipped(self):
        """The min_periods ramp of a realized-vol series must not trip it."""
        s = pd.Series([np.nan] * 100 + [5.0] * 10)
        assert vols.units_median_guard(s) is None


# ---------------------------------------------------------------------------
# Cube interpolation on a fake store
# ---------------------------------------------------------------------------
class TestCubeAtmInterp:
    def test_bilinear_center_exact(self):
        """Planted grid 100/110/120/130: (1.5y, 7.5y) -> 115.0 exactly.

        MUTATION: nearest-node instead of bilinear — 115.0 differs from all
        four nodes and both single-axis midpoints (100/110/120/130/105/125),
        each pinned as a negative control.
        """
        got = vols.cube_atm_bp_year(1.5, 7.5, D1, store=make_store())
        assert got == pytest.approx(115.0, abs=1e-12)
        for wrong in (100.0, 110.0, 120.0, 130.0, 105.0, 125.0):
            assert abs(got - wrong) > 1.0

    def test_node_read_is_exact(self):
        got = vols.cube_atm_bp_year(1.0, 5.0, D1, store=make_store())
        assert got == 100.0

    def test_offset_rows_are_filtered(self):
        """The 999/1-vol rows at +-25bp offsets must not move the ATM node.

        MUTATION: drop the offset_bp ATM filter — the poisoned rows enter
        the grid and the node no longer reads 100.0.
        """
        got = vols.cube_atm_bp_year(1.0, 5.0, D1, store=make_store())
        assert got == 100.0
        assert abs(got - 999.0) > 1.0 and abs(got - 1.0) > 1.0

    def test_clamped_at_edges_never_extrapolated(self):
        """Outside the envelope, clamp=True returns the edge, not a line fit.

        (0.5y, 7.5y): expiry below min clamps to 1Y -> 105.0. A linear
        EXTRAPOLATION would give 95.0 — pinned as the negative control.
        (3.0y, 20y): both axes past max clamp to (2Y, 10Y) -> 130.0
        (extrapolation would give 150.0).
        """
        st = make_store()
        low = vols.cube_atm_bp_year(0.5, 7.5, D1, store=st)
        assert low == pytest.approx(105.0, abs=1e-12)
        assert abs(low - 95.0) > 1.0          # extrapolation mutation
        high = vols.cube_atm_bp_year(3.0, 20.0, D1, store=st)
        assert high == pytest.approx(130.0, abs=1e-12)
        assert abs(high - 150.0) > 1.0

    def test_clamp_false_is_nan_outside_identical_inside(self):
        """clamp=False: NaN outside the envelope, same number inside.

        MUTATION: clamp=False silently behaving like clamp=True — the two
        isnan asserts fail.
        """
        st = make_store()
        assert np.isnan(vols.cube_atm_bp_year(0.5, 7.5, D1, store=st, clamp=False))
        assert np.isnan(vols.cube_atm_bp_year(3.0, 20.0, D1, store=st, clamp=False))
        inside = vols.cube_atm_bp_year(1.5, 7.5, D1, store=st, clamp=False)
        assert inside == pytest.approx(115.0, abs=1e-12)

    def test_interior_non_node_interpolates(self):
        """The no-25Y-node analogue: expiry 3.5y between quoted 2Y and 5Y.

        (3.5, 10.0) -> midpoint of 130 and 210 = 170.0 in BOTH clamp modes
        (inside the envelope even though 3.5y is not a node).
        MUTATION: node-membership support instead of envelope support —
        clamp=False would return NaN here and the assert fails.
        """
        st = make_store()
        got = vols.cube_atm_bp_year(3.5, 10.0, D3, store=st)
        assert got == pytest.approx(170.0, abs=1e-12)
        strict = vols.cube_atm_bp_year(3.5, 10.0, D3, store=st, clamp=False)
        assert strict == pytest.approx(170.0, abs=1e-12)
        assert abs(got - 130.0) > 1.0 and abs(got - 210.0) > 1.0

    def test_absent_day_and_degenerate_frames_are_nan(self):
        st = FakeStore({D1: None,
                        D2: stored_frame([]),                     # empty frame
                        D3: stored_frame([], OFFSET_POISON)})     # no ATM rows
        assert np.isnan(vols.cube_atm_bp_year(1.5, 7.5, D1, store=st))
        assert np.isnan(vols.cube_atm_bp_year(1.5, 7.5, D2, store=st))
        assert np.isnan(vols.cube_atm_bp_year(1.5, 7.5, D3, store=st))
        # a date the fake store never heard of
        assert np.isnan(vols.cube_atm_bp_year(1.5, 7.5, dt.date(2001, 1, 1), store=st))

    def test_nan_coordinates_are_nan(self):
        st = make_store()
        assert np.isnan(vols.cube_atm_bp_year(float("nan"), 5.0, D1, store=st))
        assert np.isnan(vols.cube_atm_bp_year(1.0, float("nan"), D1, store=st))

    def test_l2_read_is_pinned_off(self):
        """Reads must pass _allow_l2=False (0.0002s vs 0.172s per miss,
        v3_panel.py:106-107).

        MUTATION: drop the _allow_l2=False kwarg — the recorded call shows
        the default True and this assert fails.
        """
        st = make_store()
        vols.cube_atm_bp_year(1.5, 7.5, D1, store=st)
        assert st.calls[-1]["_allow_l2"] is False


class TestCubeAtmPanel:
    POINTS = [(1.5, 7.5), (1.0, 5.0), (3.0, 20.0)]

    def test_panel_matches_pointwise_and_reads_each_day_once(self):
        """3 points x 3 dates must cost exactly 3 read_day calls.

        MUTATION: read inside the point loop — 9 calls, the count assert
        fails.
        """
        st = make_store()
        panel = vols.cube_atm_panel(self.POINTS, [D1, D2, D3], store=st)
        assert len(st.calls) == 3
        assert list(panel.columns) == ["1.5yx7.5y", "1yx5y", "3yx20y"]
        assert list(panel.index) == [pd.Timestamp(D1), pd.Timestamp(D2), pd.Timestamp(D3)]
        # D1 row: planted answers
        assert panel.loc[pd.Timestamp(D1), "1.5yx7.5y"] == pytest.approx(115.0, abs=1e-12)
        assert panel.loc[pd.Timestamp(D1), "1yx5y"] == 100.0
        assert panel.loc[pd.Timestamp(D1), "3yx20y"] == pytest.approx(130.0, abs=1e-12)
        # absent day keeps its row, all-NaN — never dropped
        assert panel.loc[pd.Timestamp(D2)].isna().all()
        # cellwise agreement with the scalar reader
        for (e, t) in self.POINTS:
            for d in (D1, D3):
                a = panel.loc[pd.Timestamp(d), vols.point_label(e, t)]
                b = vols.cube_atm_bp_year(e, t, d, store=make_store())
                assert (np.isnan(a) and np.isnan(b)) or a == pytest.approx(b, abs=1e-12)

    def test_clamp_false_propagates(self):
        st = make_store()
        panel = vols.cube_atm_panel([(3.0, 20.0), (1.5, 7.5)], [D1], store=st,
                                    clamp=False)
        assert np.isnan(panel.iloc[0, 0])
        assert panel.iloc[0, 1] == pytest.approx(115.0, abs=1e-12)

    def test_point_label_is_not_the_leg_label(self):
        """Swaption shorthand '5yx10y', never CurveFlyScreener's '5y10y'."""
        assert vols.point_label(5.0, 10.0) == "5yx10y"
        assert vols.point_label(1.5, 7.5) == "1.5yx7.5y"
        assert vols.point_label(5.0, 10.0) != "5y10y"


class TestQuotedAxes:
    def test_axes_from_the_days_own_frame(self):
        st = make_store()
        axes = vols.quoted_axes(D1, store=st)
        assert axes == ((1.0, 2.0), (5.0, 10.0))
        axes3 = vols.quoted_axes(D3, store=st)
        assert axes3 == ((1.0, 2.0, 5.0), (5.0, 10.0))

    def test_absent_day_is_none(self):
        assert vols.quoted_axes(D2, store=make_store()) is None

    def test_tenor_years_grammar(self):
        assert vols.tenor_years("18M") == pytest.approx(1.5)
        assert vols.tenor_years("1M") == pytest.approx(1.0 / 12.0)
        assert vols.tenor_years("30Y") == 30.0
        assert vols.tenor_years(2.5) == 2.5
        assert np.isnan(vols.tenor_years("ATM"))


# ---------------------------------------------------------------------------
# Integration: the real store (self-skips when absent)
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestCubeStoreIntegration:
    """Real reads of USD-SWAPTIONVOL-CITIVELOEXCEL (2,711 days on this
    machine, 2015-10-08..2026-08-24). Node/neighbour values are derived from
    the day's OWN frame — the quoted axes vary by day (2026-08-24 serves 8
    tenors, not the historical 9), so nothing here hardcodes the grid."""

    @staticmethod
    def _store_day_grid():
        from Caching.swaption_cube_store import SwaptionCubeStore
        store = SwaptionCubeStore.default()
        days = store.available_dates(vols.ASSET)
        if not days:
            pytest.skip(f"swaption cube store has no {vols.ASSET} partitions "
                        f"under {store.base_dir}")
        day = days[-1]
        raw = store.read_day(vols.ASSET, day, _allow_l2=False)
        if raw is None or len(raw) == 0:
            pytest.skip(f"latest partition {day} unreadable")
        off = pd.to_numeric(raw["offset_bp"], errors="coerce").fillna(9e9)
        atm = raw[np.isclose(off, 0.0)].copy()
        if len(atm) == 0:
            pytest.skip(f"latest partition {day} has no ATM rows")
        atm["e_y"] = [vols.tenor_years(x) for x in atm["expiry"]]
        atm["t_y"] = [vols.tenor_years(x) for x in atm["tenor"]]
        atm["v"] = pd.to_numeric(atm["vol_bp"], errors="coerce")
        return store, day, atm

    def _node(self, atm, e_y, t_y):
        s = atm[(atm["e_y"] == e_y) & (atm["t_y"] == t_y)]
        return float(s["v"].iloc[0]) if len(s) else None

    def test_node_value_equals_raw_frame_exactly(self):
        """cube_atm_bp_year at a quoted node == the raw stored float, ==.

        MUTATION: any resampling/renormalisation of the stored vol (a x100,
        a sqrt(252)) — exact equality fails.
        """
        _, day, atm = self._store_day_grid()
        v = self._node(atm, 5.0, 10.0)
        if v is None:   # day-varying axes: fall back to the first node
            row = atm.iloc[0]
            e_y, t_y, v = float(row["e_y"]), float(row["t_y"]), float(row["v"])
        else:
            e_y, t_y = 5.0, 10.0
        got = vols.cube_atm_bp_year(e_y, t_y, day)
        assert got == v
        # sanity on the unit: an annualised USD normal vol, not a daily one
        assert 10.0 < got < 500.0

    def test_mid_grid_interp_lies_between_neighbours(self):
        """Midpoint of two adjacent quoted expiries lies strictly between
        their node vols (and equals neither) at a common quoted tenor.

        MUTATION: nearest-node lookup — the strict inequalities fail.
        """
        _, day, atm = self._store_day_grid()
        exps = np.sort(atm["e_y"].unique())
        tens = np.sort(atm["t_y"].unique())
        for t0 in tens[::-1]:
            for e1, e2 in zip(exps, exps[1:]):
                v1, v2 = self._node(atm, e1, t0), self._node(atm, e2, t0)
                if v1 is None or v2 is None or v1 == v2:
                    continue
                mid = vols.cube_atm_bp_year((e1 + e2) / 2.0, t0, day)
                lo, hi = min(v1, v2), max(v1, v2)
                assert lo < mid < hi
                assert mid != v1 and mid != v2
                return
        pytest.skip("no adjacent expiry pair with distinct vols (flat surface?)")

    def test_25y_expiry_is_interior_not_a_node(self):
        """The recon fact: the expiry axis has no 25Y node, yet 25y prices
        as an INTERIOR interpolation between 20Y and 30Y."""
        _, day, atm = self._store_day_grid()
        exps = set(np.sort(atm["e_y"].unique()).tolist())
        if not ({20.0, 30.0} <= exps) or 25.0 in exps:
            pytest.skip("day's expiry axis changed shape; 20/30 bracketing "
                        "assumption gone")
        t0 = float(np.sort(atm["t_y"].unique())[-1])
        v20, v30 = self._node(atm, 20.0, t0), self._node(atm, 30.0, t0)
        got = vols.cube_atm_bp_year(25.0, t0, day, clamp=False)
        assert np.isfinite(got)
        assert min(v20, v30) - 1e-9 <= got <= max(v20, v30) + 1e-9

    def test_envelope_edge_and_beyond(self):
        """Past the axis end: clamp=True returns the edge NODE exactly,
        clamp=False returns NaN. Never a value beyond the quoted grid."""
        _, day, atm = self._store_day_grid()
        e_max = float(atm["e_y"].max())
        t0 = float(np.sort(atm["t_y"].unique())[0])
        edge = self._node(atm, e_max, t0)
        got = vols.cube_atm_bp_year(e_max + 20.0, t0, day, clamp=True)
        assert got == edge
        assert np.isnan(vols.cube_atm_bp_year(e_max + 20.0, t0, day, clamp=False))

    def test_panel_matches_scalar_on_real_days(self):
        store, day, atm = self._store_day_grid()
        days = store.available_dates(vols.ASSET)[-2:]
        pts = [(5.0, 10.0), (2.0, 5.0)]
        panel = vols.cube_atm_panel(pts, days)
        assert panel.shape == (len(days), 2)
        for d in days:
            for (e, t) in pts:
                a = panel.loc[pd.Timestamp(d), vols.point_label(e, t)]
                b = vols.cube_atm_bp_year(e, t, d)
                assert (np.isnan(a) and np.isnan(b)) or a == b

    def test_units_chain_on_real_vols(self):
        """The stored vols are bp/yr: raw fails the bp/day guard, converted
        passes. A real-data negative control of the whole unit chain."""
        _, day, atm = self._store_day_grid()
        v_year = atm["v"].dropna()
        med_year = float(v_year.median())
        assert vols.units_median_guard(vols.bp_year_to_day(v_year)) is None
        if med_year > 40.0:
            with pytest.raises(ValueError):
                vols.units_median_guard(v_year)
        else:
            pytest.skip(f"median ATM vol {med_year:.1f} bp/yr no longer "
                        "exceeds the daily band; regime changed")
