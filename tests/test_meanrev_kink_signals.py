"""Synthetic, no-network tests for the kink-lab signal functions.

``scale_only_zscore``, ``meeting_residual_signal`` and ``calendar_adjusted_signal``
are the three functions the SFR kink-fade lab's conclusions rest on, and the
distinction between the first and a plain z-score is load-bearing: one keeps a
fitted model's zero and the other throws it away for a trailing mean.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.MeanRev.meetings import (
    calendar_fly_panel, calendar_tilted_fly, fomc_decisions, meeting_residual_panel,
    meeting_weight_matrix,
)
from RVUtils.MeanRev.panel import add_strip_slots, enumerate_structures, pivot_levels
from RVUtils.MeanRev.signals import (
    calendar_adjusted_signal, meeting_residual_signal, scale_only_zscore,
    zscore_signal,
)

D = datetime.date


def _panel(n=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.DataFrame({
        "a": rng.normal(0, 2.0, n),
        "b": 6.0 + rng.normal(0, 2.0, n),      # same shape, shifted off zero
    }, index=idx)


# ---------------------------------------------------------------------------
# scale_only_zscore
# ---------------------------------------------------------------------------

def test_scale_only_zscore_divides_by_the_trailing_sd():
    idx = pd.bdate_range("2022-01-03", periods=200)
    x = pd.DataFrame({"a": np.r_[np.zeros(199), 5.0]}, index=idx)
    s = scale_only_zscore(x, window=100, min_periods=50)
    sd = float(x["a"].iloc[-100:].std(ddof=0))
    assert s["a"].iloc[-1] == pytest.approx(5.0 / sd)


def test_scale_only_zscore_keeps_the_models_zero_and_a_zscore_does_not():
    """The discriminating property, on two series with identical dynamics.

    ``b`` is ``a`` shifted +6. ``scale_only`` must report ``b`` as persistently
    rich; a full z-score must report both as centred, because it subtracts each
    series' own trailing mean.
    """
    x = _panel()
    s = scale_only_zscore(x, window=120)
    z = zscore_signal(x, window=120)
    assert abs(s["a"].dropna().mean()) < 0.4
    assert s["b"].dropna().mean() > 2.0
    assert abs(z["a"].dropna().mean()) < 0.4
    assert abs(z["b"].dropna().mean()) < 0.4


def test_scale_only_zscore_is_causal():
    """A spike at bar t must not change the signal at any bar before t."""
    x = _panel()
    y = x.copy()
    y.iloc[-1, 0] += 50.0
    a, b = scale_only_zscore(x, window=60), scale_only_zscore(y, window=60)
    pd.testing.assert_series_equal(a["a"].iloc[:-1], b["a"].iloc[:-1])


def test_scale_only_zscore_returns_nan_on_a_constant_column():
    """A zero-sd window is not a zero signal -- it is no signal.

    Returning 0.0 would look like "fairly valued" and quietly suppress entries;
    NaN makes the engine skip the bar, which is the honest behaviour.
    """
    idx = pd.bdate_range("2022-01-03", periods=120)
    x = pd.DataFrame({"flat": np.full(120, 3.0)}, index=idx)
    s = scale_only_zscore(x, window=60)
    assert s["flat"].isna().all()


def test_scale_only_zscore_min_periods_burn_in():
    x = _panel(n=100)
    s = scale_only_zscore(x, window=90, min_periods=40)
    assert s["a"].iloc[:39].isna().all()
    assert s["a"].iloc[39:].notna().all()


# ---------------------------------------------------------------------------
# the toy strip both structure signals need
# ---------------------------------------------------------------------------

def _toy_lab(n_dates=260, n_contracts=8, bump=None, seed=1):
    start = D(2026, 1, 1)
    meetings = fomc_decisions(D(2025, 6, 1), D(2031, 12, 31))
    windows = [(start + datetime.timedelta(days=91 * i),
                start + datetime.timedelta(days=91 * (i + 1)))
               for i in range(n_contracts)]
    W = meeting_weight_matrix(windows, meetings)
    delta = np.linspace(-6.0, 6.0, len(meetings))
    base_bp = 400.0 + W @ delta
    rng = np.random.default_rng(seed)
    rows = []
    for t in range(n_dates):
        d = pd.Timestamp(D(2025, 11, 3)) + pd.Timedelta(days=t)
        wob = rng.normal(0, 1.5, n_contracts)
        if bump is not None:
            wob[bump] += 8.0
        for i, (a, b) in enumerate(windows):
            rows.append({"as_of": d, "code": f"C{i}", "imm_start": a, "imm_end": b,
                         "rate_pct": (base_bp[i] + wob[i]) / 100.0})
    c = pd.DataFrame(rows)
    sl = add_strip_slots(c, order_col="imm_start", start_col="imm_start")
    st = enumerate_structures(sl, spacing=1, max_slot=16)
    return c, st, meetings


# ---------------------------------------------------------------------------
# meeting_residual_signal
# ---------------------------------------------------------------------------

def test_meeting_residual_signal_is_the_fly_of_the_residual_in_bp():
    c, st, mt = _toy_lab()
    levels = pivot_levels(st)
    resid = meeting_residual_panel(c, meetings=mt, lam=100.0, max_slot=16)
    sig = meeting_residual_signal(levels, resid_panel=resid, struct=st,
                                  standardise="raw")
    # hand-compute one cell from the per-slot residuals
    row = st.iloc[0]
    d = pd.Timestamp(row["as_of"])
    hand = (2.0 * resid.at[d, row["leg1_slot"]]
            - resid.at[d, row["leg0_slot"]] - resid.at[d, row["leg2_slot"]])
    assert sig.at[d, row["key"]] == pytest.approx(hand, abs=1e-9)


def test_meeting_residual_signal_is_not_scaled_by_a_hundred():
    """The residual panel is already in bp; scaling it again would be a 100x bug."""
    c, st, mt = _toy_lab()
    levels = pivot_levels(st)
    resid = meeting_residual_panel(c, meetings=mt, lam=100.0, max_slot=16)
    sig = meeting_residual_signal(levels, resid_panel=resid, struct=st,
                                  standardise="raw")
    assert float(sig.stack().abs().max()) < 5.0 * float(resid.stack().abs().max())


def test_meeting_residual_signal_standardisations_differ():
    c, st, mt = _toy_lab()
    levels = pivot_levels(st)
    resid = meeting_residual_panel(c, meetings=mt, lam=100.0, max_slot=16)
    kw = dict(resid_panel=resid, struct=st, window=120)
    raw = meeting_residual_signal(levels, standardise="raw", **kw)
    sc = meeting_residual_signal(levels, standardise="scale", **kw)
    z = meeting_residual_signal(levels, standardise="z", **kw)
    assert raw.shape == sc.shape == z.shape == levels.shape
    assert not np.allclose(sc.fillna(0).to_numpy(), z.fillna(0).to_numpy())
    with pytest.raises(ValueError, match="standardise"):
        meeting_residual_signal(levels, standardise="nope", **kw)


def test_meeting_residual_signal_finds_an_injected_dislocation():
    c, st, mt = _toy_lab(bump=3)
    levels = pivot_levels(st)
    resid = meeting_residual_panel(c, meetings=mt, lam=1e4, max_slot=16)
    sig = meeting_residual_signal(levels, resid_panel=resid, struct=st,
                                  standardise="raw")
    # slot 4 is contract C3; the fly whose BELLY is slot 4 must be most extreme
    belly4 = [k for k in sig.columns
              if int(st[st["key"] == k]["leg1_slot"].iloc[0]) == 4]
    others = [k for k in sig.columns if k not in belly4]
    assert belly4
    assert sig[belly4].abs().mean().mean() > 2.0 * sig[others].abs().mean().mean()


# ---------------------------------------------------------------------------
# calendar_adjusted_signal
# ---------------------------------------------------------------------------

def test_calendar_adjusted_signal_standardises_the_panel_it_is_given():
    c, st, mt = _toy_lab()
    levels = pivot_levels(st)
    cal = calendar_fly_panel(st, c, meetings=mt)
    adj = calendar_tilted_fly(st, cal)["level"]
    raw = calendar_adjusted_signal(levels, adjusted=adj, standardise="raw")
    pd.testing.assert_frame_equal(
        raw, adj.reindex(index=levels.index, columns=levels.columns))
    sc = calendar_adjusted_signal(levels, adjusted=adj, standardise="scale",
                                  window=120)
    pd.testing.assert_frame_equal(
        sc, scale_only_zscore(raw, window=120), check_names=False)


def test_calendar_adjusted_signal_takes_its_grid_from_levels():
    """`levels` fixes index and columns even when `adjusted` is wider."""
    c, st, mt = _toy_lab()
    levels = pivot_levels(st)
    cal = calendar_fly_panel(st, c, meetings=mt)
    adj = calendar_tilted_fly(st, cal)["level"]
    trimmed = levels.iloc[10:, :2]
    out = calendar_adjusted_signal(trimmed, adjusted=adj, standardise="raw")
    assert out.index.equals(trimmed.index)
    assert list(out.columns) == list(trimmed.columns)


def test_calendar_adjusted_signal_rejects_an_unknown_standardisation():
    c, st, mt = _toy_lab()
    levels = pivot_levels(st)
    cal = calendar_fly_panel(st, c, meetings=mt)
    adj = calendar_tilted_fly(st, cal)["level"]
    with pytest.raises(ValueError, match="standardise"):
        calendar_adjusted_signal(levels, adjusted=adj, standardise="nope")
