"""Smoke tests for RVUtils.FlyVsVol.plotting (Agg backend, no display)."""
import matplotlib

matplotlib.use("Agg")

import datetime

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from RVUtils.FlyVsVol import ContractMarginal
from RVUtils.FlyVsVol.metrics import build_fly_snapshot
from RVUtils.FlyVsVol.plotting import (
    plot_fly_distribution,
    plot_history_panel,
    plot_move_table,
)


def normal_marginal(sym, mu, sigma, n=3001, span=6.0):
    grid = np.linspace(mu - span * sigma, mu + span * sigma, n)
    return ContractMarginal(
        symbol=sym, grid_rate=grid, cdf=norm.cdf(grid, mu, sigma), forward_rate=mu
    )


@pytest.fixture()
def snapshot():
    legs = [
        normal_marginal(s, m, sg)
        for s, m, sg in zip(("F", "B", "K"), (3.99, 4.145, 4.225), (0.30, 0.45, 0.82))
    ]
    return build_fly_snapshot(*legs, as_of=datetime.date(2026, 7, 27))


def test_plot_fly_distribution(snapshot):
    ax = plot_fly_distribution(snapshot, entry_bp=7.5)
    assert ax.get_xlabel() == "fly settlement (bp)"
    plt.close(ax.figure)


def test_plot_move_table(snapshot):
    ax = plot_move_table(snapshot)
    assert "P(N1-N2=j)" in ax.get_title()
    plt.close(ax.figure)


def test_plot_history_panel():
    dates = list(pd.bdate_range("2026-05-01", periods=40).date)
    hist = pd.DataFrame({
        "as_of": dates,
        "label": ["F-B-K"] * 40,
        "fly_bp": np.linspace(5, 9, 40),
        "fly_median_path_bp": np.linspace(8, 12, 40),
        "tail_rent_bp": np.linspace(-3, -4, 40),
        "heuristic_gap": np.zeros(40),
        "tail_rent_bp_z": np.linspace(-1, 2.5, 40),
    })
    fig = plot_history_panel(
        hist, "F-B-K",
        cols=("fly_bp", "fly_median_path_bp", "tail_rent_bp", "tail_rent_bp_z"),
    )
    assert len(fig.axes) == 3  # overlay + 2 singles
    plt.close(fig)


def test_plot_history_panel_missing_label():
    hist = pd.DataFrame({"as_of": [], "label": [], "fly_bp": []})
    with pytest.raises(ValueError):
        plot_history_panel(hist, "NOPE")
