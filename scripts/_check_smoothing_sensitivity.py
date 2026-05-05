"""Probe smoothing-sensitivity Δp on the 5 backfill dates."""
from __future__ import annotations

import datetime

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from RVUtils.STIRAsymmetricScreener._rnd import _build_observed_rnd_input, _refit_payoff_zone_prob
from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig


DATES = [
    (datetime.date(2023, 2, 21), "SFRM23"),
    (datetime.date(2023, 3, 13), "SFRM23"),
    (datetime.date(2024, 8, 15), "SFRZ24"),
    (datetime.date(2024, 9, 19), "SFRZ24"),
    (datetime.date(2026, 5, 4), "SFRU26"),
]


def main():
    cfg = ScreenerConfig()
    opt_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    print("date         contract  λ_base   λ÷10     λ×10     order-1   order+1")
    for as_of, contract in DATES:
        smile = opt_mdp.fetch_sabr_smile(
            {"symbol": contract, "as_of": as_of, "strike_offsets_bps": "listed"}
        )
        rnd_input, _, _ = _build_observed_rnd_input(smile, {}, as_of=as_of)
        fwd_rate = float(smile.params.forward_rate)

        p_base = _refit_payoff_zone_prob(
            rnd_input=rnd_input, config=cfg,
            smoothing_param=cfg.rnd_smoothing_param,
            spline_order=cfg.rnd_spline_order, fwd_rate=fwd_rate,
        )
        p_low = _refit_payoff_zone_prob(
            rnd_input=rnd_input, config=cfg,
            smoothing_param=cfg.rnd_smoothing_param / 10.0,
            spline_order=cfg.rnd_spline_order, fwd_rate=fwd_rate,
        )
        p_high = _refit_payoff_zone_prob(
            rnd_input=rnd_input, config=cfg,
            smoothing_param=cfg.rnd_smoothing_param * 10.0,
            spline_order=cfg.rnd_spline_order, fwd_rate=fwd_rate,
        )
        p_o_lo = _refit_payoff_zone_prob(
            rnd_input=rnd_input, config=cfg,
            smoothing_param=cfg.rnd_smoothing_param,
            spline_order=cfg.rnd_spline_order - 1, fwd_rate=fwd_rate,
        )
        p_o_hi = _refit_payoff_zone_prob(
            rnd_input=rnd_input, config=cfg,
            smoothing_param=cfg.rnd_smoothing_param,
            spline_order=cfg.rnd_spline_order + 1, fwd_rate=fwd_rate,
        )
        print(f"{as_of}  {contract}    "
              f"{p_base:6.4f}  {p_low:6.4f}  {p_high:6.4f}  "
              f"{p_o_lo:6.4f}   {p_o_hi:6.4f}")
        d_smooth = max(abs(p_low - p_base), abs(p_high - p_base)) * 100.0
        d_order = max(abs(p_o_lo - p_base), abs(p_o_hi - p_base)) * 100.0
        print(f"             |Δp| smoothing={d_smooth:.2f}pp  order={d_order:.2f}pp")


if __name__ == "__main__":
    main()
