"""Tests for RVUtils.FlyVsVol.screener."""
import datetime

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from RVUtils.FlyVsVol import ContractMarginal, FlyDefinition
from RVUtils.FlyVsVol.screener import (
    adjacent_triples,
    history_zscores,
    run_fly_screener,
    screener_table,
)


def normal_marginal(sym, mu, sigma, n=4001, span=6.0):
    grid = np.linspace(mu - span * sigma, mu + span * sigma, n)
    return ContractMarginal(
        symbol=sym, grid_rate=grid, cdf=norm.cdf(grid, mu, sigma), forward_rate=mu
    )


SYMS = ["SFRU26", "SFRZ26", "SFRH27", "SFRM27"]
MUS = [3.99, 4.145, 4.225, 4.26]
SIGMAS = [0.30, 0.45, 0.60, 0.82]


def test_adjacent_triples_count_order():
    triples = adjacent_triples(SYMS)
    assert len(triples) == 2
    assert triples[0] == FlyDefinition("SFRU26", "SFRZ26", "SFRH27")
    assert triples[1] == FlyDefinition("SFRZ26", "SFRH27", "SFRM27")
    assert adjacent_triples(SYMS[:2]) == []


def test_run_skips_missing_leg():
    marginals = {
        s: normal_marginal(s, m, sg) for s, m, sg in zip(SYMS[:3], MUS, SIGMAS)
    }
    triples = adjacent_triples(SYMS)  # second triple needs SFRM27 (absent)
    snaps = run_fly_screener(marginals, triples, as_of=datetime.date(2026, 7, 27))
    assert len(snaps) == 1
    assert snaps[0].fly.label == "SFRU26-SFRZ26-SFRH27"


def test_screener_table_index_and_sort():
    marginals = {
        s: normal_marginal(s, m, sg) for s, m, sg in zip(SYMS, MUS, SIGMAS)
    }
    snaps = run_fly_screener(marginals, as_of=datetime.date(2026, 7, 27))
    assert len(snaps) == 2
    table = screener_table(snaps)
    assert list(table.index) == sorted(
        table.index, key=lambda l: -abs(table.loc[l, "tail_rent_bp"])
    )
    assert "heuristic_gap" in table.columns and "fly_bp" in table.columns


def test_run_with_corr_dataframe():
    marginals = {
        s: normal_marginal(s, m, sg) for s, m, sg in zip(SYMS[:3], MUS, SIGMAS)
    }
    corr = pd.DataFrame(0.95, index=SYMS[:3], columns=SYMS[:3])
    np.fill_diagonal(corr.values, 1.0)
    snaps = run_fly_screener(marginals, corr=corr)
    assert snaps[0].copula is not None


def test_history_zscores_synthetic():
    dates = pd.bdate_range("2026-01-01", periods=80).date
    base = np.zeros(80)
    base[-1] = 5.0  # step jump on the last day
    hist = pd.DataFrame({
        "as_of": list(dates), "label": ["A-B-C"] * 80,
        "tail_rent_bp": base, "heuristic_gap": np.ones(80),
    })
    out = history_zscores(hist, ["tail_rent_bp", "heuristic_gap"],
                          window=60, min_periods=20)
    last = out.iloc[-1]
    assert last["tail_rent_bp_z"] > 4
    # constant series -> zero std -> NaN z
    assert np.isnan(last["heuristic_gap_z"])
    assert "tail_rent_bp_z_full" in out.columns


def test_history_zscores_grouped():
    dates = list(pd.bdate_range("2026-01-01", periods=50).date)
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 50)
    b = rng.normal(100, 1, 50)
    hist = pd.DataFrame({
        "as_of": dates * 2,
        "label": ["A-B-C"] * 50 + ["B-C-D"] * 50,
        "fly_bp": np.concatenate([a, b]),
    })
    out = history_zscores(hist, ["fly_bp"], window=40, min_periods=10)
    za = out[out["label"] == "A-B-C"]["fly_bp_z"].dropna()
    zb = out[out["label"] == "B-C-D"]["fly_bp_z"].dropna()
    # grouped z-scores: each label centred on its own history
    assert za.abs().max() < 5 and zb.abs().max() < 5
