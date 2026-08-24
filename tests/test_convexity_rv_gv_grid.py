"""GV block — the declared grid, its trial count, and cell execution.

The trial count is the whole point of a pre-registration, so it is asserted
against the numbers written in ``docs/convexityrv/gv-preregistration.md`` and
the doc is parsed rather than paraphrased: if the two drift, this fails.
"""
from __future__ import annotations

import pathlib
import re

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import gv_grid as GG
from RVUtils.ConvexityRV import gv_universe as U
from RVUtils.ConvexityRV.gv_sizing import SIZING_RULES

PREREG = (pathlib.Path(__file__).resolve().parents[1]
          / "docs" / "convexityrv" / "gv-preregistration.md")


# ---------------------------------------------------------------------------
# 1. The declared grid
# ---------------------------------------------------------------------------
def test_declared_cell_count_matches_the_arithmetic():
    cells = GG.declared_cells()
    n_primary = len(U.PRIMARY_STRUCTURES) * len(U.LEGS) * len(SIZING_RULES) * 2
    n_ca = len(U.PRIMARY_STRUCTURES) * 2
    n_var = len(U.PRIMARY_STRUCTURES) * len(GG.VARBASIS_SIZINGS) * 2
    n_sec = (len(U.SECONDARY_STRUCTURES) * len(GG.SECONDARY_LEGS)
             * len(GG.SECONDARY_SIZINGS))
    assert (n_primary, n_ca, n_var, n_sec) == (252, 6, 12, 28)
    assert len(cells) == 298


def test_declared_count_matches_the_preregistration_document():
    """The document is the contract; the code must not quietly outgrow it."""
    txt = PREREG.read_text(encoding="utf-8")
    m = re.search(r"\*\*total declared\*\*\s*\|\s*\*\*(\d+)\*\*", txt)
    assert m, "could not find the declared total in the pre-registration"
    assert int(m.group(1)) == len(GG.declared_cells())


def test_headline_is_exactly_twelve_cells_and_is_a_subset_of_the_grid():
    cells = GG.declared_cells()
    head = [c for c in cells if c.headline]
    assert len(head) == 12
    for c in head:
        assert c.tier == "primary" and c.signal == "z_resid"
        assert c.leg_id in GG.HEADLINE_LEGS
        assert c.sizing in GG.HEADLINE_SIZINGS
        assert c.book_scale == "const_dv01"
    assert {c.structure for c in head} == set(U.PRIMARY_STRUCTURES)


def test_headline_contains_the_briefs_own_regression_and_its_fix():
    ids = {c.cell_id for c in GG.declared_cells() if c.headline}
    assert "A|BLUES|immF_2s5s10s|beta_lvl|const_dv01" in ids
    assert "A|BLUES|immF_2s5s10s|vega_match|const_dv01" in ids


def test_cell_ids_are_unique_and_deterministic():
    a = [c.cell_id for c in GG.declared_cells()]
    b = [c.cell_id for c in GG.declared_cells()]
    assert a == b
    assert len(set(a)) == len(a)


def test_every_structure_has_a_vol_benchmark():
    for lab in U.STRUCTURES:
        assert lab in GG.VOL_BENCH
        assert GG.vol_bench_col(lab).endswith("ATMF NVOL")


def test_vol_benchmark_expiry_rises_with_pack_depth():
    order = ["WHITES", "REDS", "GREENS", "BLUES", "GOLDS"]
    yrs = [int(GG.VOL_BENCH[l].split("Yx")[0]) for l in order]
    assert yrs == sorted(yrs) and len(set(yrs)) == len(yrs)


# ---------------------------------------------------------------------------
# 2. Cell execution on synthetic panels
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def panels():
    idx = pd.bdate_range("2021-01-04", "2026-08-21")
    rng = np.random.default_rng(31)
    n = len(idx)
    ca = pd.DataFrame(index=idx)
    for lab, base in (("GREENS", 4.4), ("BLUES", 9.2), ("GOLDS", 14.0),
                      ("WHITES", 0.5), ("REDS", 1.1)):
        ca[U.ca_col(lab)] = base + rng.normal(0, 0.4, n).cumsum() * 0.05 \
            + rng.normal(0, 0.3, n)
    for lab in ("BUNDLE4Y", "BUNDLE5Y", "SFR12", "SFR16", "SFR20"):
        ca[U.ca_col(lab)] = 6.0 + rng.normal(0, 0.4, n).cumsum() * 0.05

    legs = pd.DataFrame(index=idx)
    for k in (1, 2, 9, 13, 17, 12, 16, 20):
        for t, b in (("1y", 4.0), ("2y", 4.1), ("3y", 4.15),
                     ("5y", 4.3), ("10y", 4.55)):
            legs[f"USD-SOFR-1D IMM_{k}x{t} OUTRIGHT RATE"] = (
                b + 0.002 * k + rng.normal(0, 0.01, n).cumsum() * 0.05)
    for t, b in (("2Y", 4.05), ("5Y", 4.25), ("10Y", 4.5), ("10Yx10Y", 4.7),
                 ("15Yx10Y", 4.6), ("20Yx10Y", 4.4)):
        legs[f"USD-SOFR-1D {t} OUTRIGHT RATE"] = (
            b + rng.normal(0, 0.01, n).cumsum() * 0.05)
    for sh in ("1Yx1Y", "2Yx1Y", "3Yx1Y", "4Yx1Y", "5Yx1Y"):
        legs[f"USD-SOFR-1D {sh} STRADDLE BUY ATMF NVOL"] = (
            100.0 + rng.normal(0, 1.0, n).cumsum() * 0.2)
    hl = {U.ca_col(l): 0.6 for l in U.STRUCTURES}
    return ca, legs, hl


def test_a_headline_cell_runs_end_to_end(panels):
    ca, legs, hl = panels
    spec = next(c for c in GG.declared_cells()
                if c.cell_id == "A|BLUES|immF_2s5s10s|beta_lvl|const_dv01")
    r = GG.run_cell(spec, ca, legs, halflives=hl)
    assert r.n_dates == len(ca)
    assert r.n_episodes > 0
    assert set(r.daily_by_mult) == set(GG.COST_MULTS)
    for m, d in r.daily_by_mult.items():
        assert len(d) == len(ca)
    # costs can only reduce P&L
    assert float(r.daily_by_mult[2.0].sum()) <= float(r.daily_by_mult[0.0].sum())


def test_no_episode_of_any_run_cell_straddles_a_roll(panels):
    ca, legs, hl = panels
    rolls = set(U.ca_roll_dates(ca.index)) | set(U.leg_roll_dates(ca.index))
    for cid in ("A|BLUES|immF_2s5s10s|beta_lvl|const_dv01",
                "A|GOLDS|immM_2s5s10s|vol_ratio|inv_vol",
                "C|GREENS|caonly|const_dv01"):
        spec = next(c for c in GG.declared_cells() if c.cell_id == cid)
        r = GG.run_cell(spec, ca, legs, halflives=hl)
        for e in r.episodes:
            span = ca.index[(ca.index >= e.entry) & (ca.index <= e.exit)]
            assert not (rolls & set(span)), f"{cid}: {e.entry}..{e.exit}"


def test_blackout_off_changes_the_episode_set(panels):
    """The blackout must be load-bearing, not decorative."""
    ca, legs, hl = panels
    spec = next(c for c in GG.declared_cells()
                if c.cell_id == "A|BLUES|immF_2s5s10s|beta_lvl|const_dv01")
    on = GG.run_cell(spec, ca, legs, halflives=hl, blackout=True)
    off = GG.run_cell(spec, ca, legs, halflives=hl, blackout=False)
    assert on.n_episodes != off.n_episodes or \
        [e.exit for e in on.episodes] != [e.exit for e in off.episodes]
    assert any(e.exit_reason == "segment_end" for e in on.episodes)


def test_ca_only_control_carries_no_hedge(panels):
    ca, legs, hl = panels
    spec = next(c for c in GG.declared_cells()
                if c.cell_id == "C|BLUES|caonly|const_dv01")
    r = GG.run_cell(spec, ca, legs, halflives=hl)
    assert all(e.beta_entry == 0.0 for e in r.episodes)


def test_vega_match_refusals_are_counted(panels):
    ca, legs, hl = panels
    spec = next(c for c in GG.declared_cells()
                if c.cell_id == "A|BLUES|immF_2s5s10s|vega_match|const_dv01")
    r = GG.run_cell(spec, ca, legs, halflives=hl)
    assert r.n_gate_refusals >= 0
    assert r.n_gate_refusals <= r.n_dates


def test_grid_stats_frame_has_the_reported_columns(panels):
    ca, legs, hl = panels
    cells = [c for c in GG.declared_cells() if c.headline][:3]
    res = GG.run_grid(cells, ca, legs, halflives=hl)
    df = GG.grid_stats_frame(res, span_years=5.6)
    for col in ("cell_id", "n_episodes", "n_eff", "hit_rate", "mean_beta",
                "mean_leg_dv01", "gross_dv01_traded", "breakeven_bp",
                "net_0.0", "sharpe_0.0", "net_1.0", "sharpe_1.0"):
        assert col in df.columns, col
    assert len(df) == 3


# ---------------------------------------------------------------------------
# 3. Nulls
# ---------------------------------------------------------------------------
def test_null_bar_rises_with_trials_and_the_two_clocks_differ():
    a = GG.null_bars(12, n_eff=40.0, span_years=5.6)
    b = GG.null_bars(298, n_eff=40.0, span_years=5.6)
    assert b["emax_perhold"] > a["emax_perhold"] > 0
    assert b["emax_annualised"] > a["emax_annualised"] > 0
    # with quarterly-capped holds the annualised bar is the LARGER one -- the
    # w2b discipline this package adopted after quoting only the smaller.
    assert a["emax_annualised"] > a["emax_perhold"]


def test_vol_proxy_matrix_reports_r2_and_gate_pass(panels):
    ca, legs, hl = panels
    m = GG.vol_proxy_matrix(legs, structures=list(U.PRIMARY_STRUCTURES))
    assert not m.empty
    for c in ("leg_id", "vol", "beta_bp_per_bpyr", "r2", "t",
              "roll_gate_pass_frac"):
        assert c in m.columns
    assert m["r2"].between(0.0, 1.0).all()
    assert m["roll_gate_pass_frac"].between(0.0, 1.0).all()
