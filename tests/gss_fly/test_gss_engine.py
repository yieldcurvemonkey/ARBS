"""The GSS book's QueryDrivenBacktest wiring, on a synthetic curve.

These do not test whether the strategy makes money. They test the thing that is easy to get wrong
and hard to notice: that the trigger fires, that the orders reach the engine, that positions are
marked and closed, and that the run refuses to return quietly when none of that happened.

The panel is synthetic on purpose — a curve with one bond deliberately dislocated and then pulled
back — so the entry and the exit are both forced and the assertions are about mechanism.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from BT.gss_fly.backtest import run_gss_backtest
from BT.gss_fly.config import BacktestConfig, BondSignalConfig, CostConfig, FlyConfig, GSSConfig, UniverseConfig
from BT.gss_fly.data import CurvePanel
from BT.gss_fly.signals import build_bond_signals
from BT.gss_fly.strategy import GSSSignalEngine


N_DAYS = 320


def _synthetic_panel(dislocation_bp: float = 14.0) -> CurvePanel:
    """A flat curve of nine bonds; one belly goes rich mid-sample, then reverts."""
    dates = pd.bdate_range("2025-01-02", periods=N_DAYS)
    cusips = [f"B{i:02d}" for i in range(9)]
    ttms = np.array([3.0, 4.0, 5.0, 6.0, 7.0, 9.0, 11.0, 13.0, 15.0])

    rng = np.random.default_rng(17)
    s2c = pd.DataFrame(rng.normal(scale=0.6, size=(N_DAYS, len(cusips))), index=dates, columns=cusips)

    # B04 is pushed rich over 60 days and then pulled back over the next 60.
    ramp = np.zeros(N_DAYS)
    ramp[120:180] = np.linspace(0, -dislocation_bp, 60)
    ramp[180:240] = np.linspace(-dislocation_bp, 0, 60)
    s2c["B04"] = s2c["B04"] + ramp

    base = 4.0 + 0.02 * ttms
    ytm = pd.DataFrame(
        base[None, :] + np.cumsum(rng.normal(scale=0.004, size=(N_DAYS, len(cusips))), axis=0)
        + s2c.to_numpy() / 100.0,
        index=dates, columns=cusips,
    )
    ttm_df = pd.DataFrame(np.tile(ttms, (N_DAYS, 1)), index=dates, columns=cusips)

    ref = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": d, "cusip": cusips, "ttm": ttms, "maturity": ttms,
                    "cpn": 3.0, "rank": 5, "seasoning_days": 400.0,
                }
            )
            for d in dates
        ],
        ignore_index=True,
    )
    return CurvePanel(
        s2c=s2c, ytm=ytm, ttm=ttm_df, reference=ref,
        rmse=pd.Series(1.5, index=dates),
    )


class _NullMDP:
    """The engine only needs a pricer object; these positions are valued from the panel."""

    def get_pricer(self, request):
        return {}


def _cfg(**over) -> GSSConfig:
    base = dict(
        signal=BondSignalConfig(),
        universe=UniverseConfig(exclude_ranks=()),
        fly=FlyConfig(),
        costs=CostConfig(),
        backtest=BacktestConfig(max_concurrent=4, reentry_cooldown_days=3),
    )
    base.update(over)
    return GSSConfig(**base)


def test_signal_engine_fires_an_entry_on_a_dislocation():
    panel = _synthetic_panel()
    cfg = _cfg(backtest=BacktestConfig(entry_zsig_bp=0.5, max_concurrent=4, reentry_cooldown_days=3))
    sig = build_bond_signals(panel.s2c, cfg.signal)
    eng = GSSSignalEngine(panel, sig["signal"], cfg)

    fired = 0
    for d in panel.dates:
        info = eng(d, None)
        if info and info.info.get("entries"):
            fired += 1
    assert fired > 0, "no entry fired on a curve with a deliberate 14bp dislocation"
    assert any(r["event"] == "ENTER" for r in eng.log)


def test_engine_never_holds_a_bond_in_two_live_flies():
    """Overlapping legs would double the real position without doubling the recorded risk."""
    panel = _synthetic_panel()
    cfg = _cfg(backtest=BacktestConfig(entry_zsig_bp=0.2, max_concurrent=6, reentry_cooldown_days=1))
    sig = build_bond_signals(panel.s2c, cfg.signal)
    eng = GSSSignalEngine(panel, sig["signal"], cfg)
    for d in panel.dates:
        eng(d, None)
        legs = [leg for p in eng.open.values() for leg in p.legs]
        assert len(legs) == len(set(legs)), f"a bond is in two live flies on {d.date()}"


def test_concurrency_cap_is_respected():
    panel = _synthetic_panel()
    cfg = _cfg(backtest=BacktestConfig(entry_zsig_bp=0.1, max_concurrent=2, reentry_cooldown_days=1))
    sig = build_bond_signals(panel.s2c, cfg.signal)
    eng = GSSSignalEngine(panel, sig["signal"], cfg)
    for d in panel.dates:
        eng(d, None)
        assert len(eng.open) <= 2


def test_exit_fires_when_the_signal_decays_below_the_repo_hurdle():
    panel = _synthetic_panel()
    cfg = _cfg(
        backtest=BacktestConfig(entry_zsig_bp=0.3, max_concurrent=4, reentry_cooldown_days=1),
        costs=CostConfig(repo_penalty_bp=1.0),
    )
    sig = build_bond_signals(panel.s2c, cfg.signal)
    eng = GSSSignalEngine(panel, sig["signal"], cfg)
    for d in panel.dates:
        eng(d, None)
    exits = [r for r in eng.log if r["event"] == "EXIT"]
    assert exits, "nothing ever exited over 320 days"
    assert {"zsig_below_repo", "z_rollover"} & {r["reason"] for r in exits}


def test_backtest_refuses_to_return_a_book_that_never_traded():
    """The assertion that matters: an unreachable entry gate must fail loudly, not look flat."""
    panel = _synthetic_panel()
    cfg = _cfg(backtest=BacktestConfig(entry_zsig_bp=1e9, max_concurrent=4))
    with pytest.raises(AssertionError, match="never fired an entry"):
        run_gss_backtest(panel, _NullMDP(), cfg=cfg, show_progress=False, strict=True)


def test_strict_false_downgrades_the_refusal_to_a_warning():
    panel = _synthetic_panel()
    cfg = _cfg(backtest=BacktestConfig(entry_zsig_bp=1e9, max_concurrent=4))
    res = run_gss_backtest(panel, _NullMDP(), cfg=cfg, show_progress=False, strict=False)
    assert res.diagnostics["signal_entries"] == 0


def test_cost_deviation_changes_the_charge_not_the_signal():
    """Switching to the original's belly-only rule must move costs and nothing else."""
    panel = _synthetic_panel()
    sig = build_bond_signals(panel.s2c, BondSignalConfig())
    a = GSSSignalEngine(panel, sig["signal"], _cfg(backtest=BacktestConfig(entry_zsig_bp=0.4, max_concurrent=4)))
    b = GSSSignalEngine(
        panel, sig["signal"],
        _cfg(backtest=BacktestConfig(entry_zsig_bp=0.4, max_concurrent=4),
             costs=CostConfig(cost_legs="belly_only")),
    )
    for d in panel.dates:
        a(d, None)
        b(d, None)
    ea = [r for r in a.log if r["event"] == "ENTER"]
    eb = [r for r in b.log if r["event"] == "ENTER"]
    assert [r["fly_id"] for r in ea] == [r["fly_id"] for r in eb]      # same trades
    assert all(x["rt_cost_bp"] > y["rt_cost_bp"] for x, y in zip(ea, eb))  # different cost
