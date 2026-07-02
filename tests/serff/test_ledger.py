"""Residual-ledger identities on synthetic data (fast, offline)."""

import datetime

import numpy as np
import pandas as pd
import pytest

from BT.serff.config import SerffModelConfig
from BT.serff.layers import fit_layers
from BT.serff.ledger import build_ledger
from BT.serff.mechanics import (
    PolicyPath,
    carry_weights,
    contract_window,
    sr3_settlement_rate,
    zq_settlement_rate,
)


def _synthetic_panel(end="2026-06-30", n_days=1400, seed=7):
    """Panel with a known DGP: spread = -3 + noise, +8bp spikes at quarter-end."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=end, periods=n_days)
    spread = pd.Series(-3.0 + rng.normal(0, 0.4, n_days), index=idx)
    ym = idx.to_period("M")
    frame = pd.DataFrame(index=idx)
    frame["ym"] = ym
    last_bd = frame.groupby("ym").apply(lambda g: g.index.max())
    for me in last_bd.values:
        me = pd.Timestamp(me)
        if me.month in (3, 6, 9, 12):
            spread.loc[me] += 8.0
        elif me.month % 2 == 0:
            spread.loc[me] += 6.0

    effr = pd.Series(4.0, index=idx)
    sofr = effr + spread / 100.0

    panel = pd.DataFrame({"sofr": sofr, "effr": effr})
    panel["spread"] = spread
    panel["published_at"] = panel.index + pd.Timedelta(days=1, hours=8)
    panel["liq_gdp"] = np.linspace(14.0, 9.0, n_days)
    panel["tga_gdp"] = 2.5
    panel["ln_liq"] = np.log(panel["liq_gdp"])
    grouped = panel.groupby(ym)
    rank_end = grouped.cumcount(ascending=False)
    rank_beg = grouped.cumcount()
    panel["is_me"] = panel.index.isin(set(last_bd.values))
    panel["is_qe"] = panel["is_me"] & panel.index.month.isin([3, 6, 9, 12])
    panel["is_ye"] = panel["is_me"] & (panel.index.month == 12)
    panel["turn_window"] = (rank_end <= 1) | (rank_beg == 0)
    panel["is_mid"] = panel.index.day.isin([14, 15, 16, 17])
    panel["regime"] = "r_synth"
    base = panel["spread"].where(~panel["turn_window"])
    panel["local_base"] = base.rolling(15, min_periods=5).median().shift(1)
    panel["spike"] = panel["spread"] - panel["local_base"]
    return panel


@pytest.fixture(scope="module")
def synth():
    panel = _synthetic_panel()
    cfg = SerffModelConfig(regime_boundaries=(), regime_labels=("r_synth",))
    fit = fit_layers(panel, cfg)
    return panel, cfg, fit


def _flat_prices(sofr, effr, syms):
    prices = {}
    for s in syms:
        w = contract_window(s)
        fx = sofr if s.startswith("SR3") else effr
        full = pd.Series(fx.reindex(carry_weights(w).index))
        full = full.ffill().bfill()
        if s.startswith("SR3"):
            prices[s] = 100.0 - sr3_settlement_rate(full, w)
        else:
            prices[s] = 100.0 - zq_settlement_rate(full, w)
    return prices


class TestLedger:
    def test_ledger_identities(self, synth):
        panel, cfg, fit = synth
        decision = datetime.date(2026, 6, 30)
        last_pub = datetime.date(2026, 6, 29)

        idx = pd.date_range("2026-03-01", "2026-12-31", freq="D")
        effr = pd.Series(4.0, index=idx)
        sofr = effr - 0.03  # flat -3bp basis, no turns in the "market"

        syms = ["SR3M26", "ZQM26", "ZQN26", "ZQQ26", "ZQU26"]
        prices = _flat_prices(sofr, effr, syms)

        ledger = build_ledger(
            decision,
            sr3_symbol="SR3M26",
            prices=prices,
            sofr_fixings=sofr[sofr.index.date <= last_pub] * 0 + sofr[sofr.index.date <= last_pub],
            effr_fixings=effr[effr.index.date <= last_pub],
            fit=fit,
            covariates={"ln_liq": float(panel["ln_liq"].iloc[-1]), "tga_gdp": 2.5},
            meeting_decisions=[datetime.date(2026, 7, 29), datetime.date(2026, 9, 16)],
            cfg=cfg,
            last_published=last_pub,
        )

        sr3 = ledger.sr3
        # accrued + forward weights = window days
        assert sr3.accrued_days + sr3.remaining_days == contract_window("SR3M26").calendar_days
        # daily frame covers every fixing date once
        assert len(sr3.daily) == len(carry_weights(contract_window("SR3M26")))
        # residual decomposition sums exactly
        assert sr3.residual_total_bp == pytest.approx(sr3.residual_basis_bp + sr3.residual_turn_bp, abs=1e-9)
        # structure signal = basis + turn residual
        assert ledger.structure_residual_bp == pytest.approx(sr3.residual_basis_bp + sr3.residual_turn_bp)
        # forward days tagged basis or turn; realized tagged realized
        fwd = sr3.daily[sr3.daily["status"] == "forward"]
        assert set(fwd["source"]).issubset({"basis", "turn"})
        realized = sr3.daily[sr3.daily["status"] == "realized"]
        assert (realized["source"] == "realized").all()
        # model expects the -3bp-ish basis + turn add-ons; market priced -3bp flat:
        # basis residual should be small, turn residual positive (model prices spikes)
        assert sr3.residual_turn_bp > 0
        assert abs(sr3.residual_basis_bp) < 1.5

    def test_policy_exposure_table(self, synth):
        panel, cfg, fit = synth
        decision = datetime.date(2026, 6, 30)
        last_pub = datetime.date(2026, 6, 29)
        idx = pd.date_range("2026-03-01", "2026-12-31", freq="D")
        effr = pd.Series(4.0, index=idx)
        sofr = effr - 0.03
        syms = ["SR3M26", "ZQM26", "ZQN26", "ZQQ26", "ZQU26"]
        prices = _flat_prices(sofr, effr, syms)
        ledger = build_ledger(
            decision,
            sr3_symbol="SR3M26",
            prices=prices,
            sofr_fixings=sofr[sofr.index.date <= last_pub],
            effr_fixings=effr[effr.index.date <= last_pub],
            fit=fit,
            covariates={"ln_liq": float(panel["ln_liq"].iloc[-1]), "tga_gdp": 2.5},
            meeting_decisions=[datetime.date(2026, 7, 29), datetime.date(2026, 9, 16)],
            cfg=cfg,
            last_published=last_pub,
        )
        pe = ledger.policy_exposure
        jul = pe[pe["decision"] == datetime.date(2026, 7, 29)].iloc[0]
        assert jul["effective"] == datetime.date(2026, 7, 30)
        assert jul["sr3_weight"] == pytest.approx(48 / 91)
        # hedged structure nets most of the policy weight out
        assert abs(jul["net_weight"]) < 0.05
        # September meeting effective after window end: absent from table
        assert (pe["effective"] < datetime.date(2026, 9, 16)).all()
