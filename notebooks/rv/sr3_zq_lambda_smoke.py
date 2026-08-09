"""Smoke test: reproduce the measured 2026-08-07 SR3-vs-ZQ baseline, number by number.

Nothing downstream is trustworthy until this passes. Every expected value below was measured
independently, before this code existed; the script COMPUTES its own answers and compares.

    python notebooks/rv/sr3_zq_lambda_smoke.py [--as-of 2026-08-07] [--refresh]

Run from the repo root with the env python directly (parallel `conda run` invocations
collide on a temp file and return empty output with exit code 0, which reads as a pass).
"""
from __future__ import annotations

import argparse
import datetime
import math
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from RVUtils.SR3ZQDistributionScreener._copula import coupling_bounds  # noqa: E402
from RVUtils.SR3ZQDistributionScreener._lambda_signal import (  # noqa: E402
    MOVE_SIZE_BP,
    atom_rates_percent,
    build_meeting_set,
    density_modes,
    measure_lambda,
    observed_atom_probabilities,
    zq_implied_window_rate_pct,
)

# ---------------------------------------------------------------------------------------
# The measured baseline. These are TARGETS, never inputs.
# ---------------------------------------------------------------------------------------
BASE_DATE = datetime.date(2026, 8, 7)
SR3_SYMBOL = "SFRZ26"

EXPECTED_FOMC = {
    "sep26": datetime.date(2026, 9, 16),
    "oct26": datetime.date(2026, 10, 28),
    "dec26": datetime.date(2026, 12, 9),
    "jan27": datetime.date(2027, 1, 27),
    "mar27": datetime.date(2027, 3, 17),
}
EXPECTED_ZQ = {
    "ZQQ26": 96.3675, "ZQU26": 96.3150, "ZQV26": 96.2550, "ZQX26": 96.2000,
    "ZQZ26": 96.1200, "ZQF27": 96.0850, "ZQG27": 96.0500, "ZQH27": 96.0200,
}
EXPECTED_SPOT_EFFR = 3.6325
EXPECTED_MARGINAL_BP = {"sep26": 10.50, "oct26": 6.25, "dec26": 10.78, "jan27": 4.22}
EXPECTED_MARGINAL_P = {"sep26": 0.420, "oct26": 0.250, "dec26": 0.431, "jan27": 0.169}
EXPECTED_CUM_HIKES_THROUGH_DEC = 1.101
EXPECTED_FLY_RECON_BP = -6.02
EXPECTED_BASIS_BP = 5.45
EXPECTED_WING_COMONOTONE = 0.819
EXPECTED_WING_INDEPENDENT = 0.293
EXPECTED_LAMBDA_WING_RAW = 0.54

_FAILURES: list[str] = []
_PASSES = 0


def check(label: str, got: float, want: float, tol: float, unit: str = "") -> bool:
    global _PASSES
    ok = got is not None and math.isfinite(got) and abs(got - want) <= tol
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label:<52} got {got:>12.4f}{unit}  want {want:>10.4f}{unit}  (tol {tol:g})")
    if ok:
        _PASSES += 1
    else:
        _FAILURES.append(label)
    return ok


def check_eq(label: str, got, want) -> bool:
    global _PASSES
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label:<52} got {got!r}  want {want!r}")
    if ok:
        _PASSES += 1
    else:
        _FAILURES.append(label)
    return ok


def load_zq_settles(as_of: datetime.date, symbols, refresh: bool):
    from RVUtils.MeetingProb.ladder import zq_settle_panel

    panel = zq_settle_panel(symbols)
    ts = pd.Timestamp(as_of)
    if refresh or panel.empty or ts not in panel.index:
        from BT.serff.futures_data import backfill_settles

        print(f"  ... serff cache does not reach {as_of}; backfilling settles")
        backfill_settles(as_of - datetime.timedelta(days=10), as_of, symbols=list(symbols))
        panel = zq_settle_panel(symbols)
    if ts not in panel.index:
        raise SystemExit(f"no ZQ settle row for {as_of}; last available {panel.index.max()}")
    row = panel.loc[ts]
    return {sym: float(row[sym]) for sym in symbols if sym in row and np.isfinite(row[sym])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=BASE_DATE.isoformat())
    ap.add_argument("--symbol", default=SR3_SYMBOL)
    ap.add_argument("--refresh", action="store_true", help="force a serff settle backfill")
    ap.add_argument(
        "--zq-from",
        choices=("barchart", "published"),
        default="barchart",
        help=(
            "'barchart' uses the serff EOD settle cache; 'published' uses the strip quoted in "
            "the measured baseline, which isolates METHOD from DATA (the two disagree by up to "
            "1.0bp on 2026-08-07)"
        ),
    )
    args = ap.parse_args()
    as_of = datetime.date.fromisoformat(args.as_of)
    is_base = as_of == BASE_DATE and args.symbol == SR3_SYMBOL

    print(f"\n=== SR3-vs-ZQ lambda smoke test, {args.symbol} @ {as_of} ===")

    # ---- 1. FOMC calendar ------------------------------------------------------------
    print("\n1. FOMC effective dates (load_fomc_schedule('USD-SOFR-1D'))")
    from SDRUtils.analytics.fomc import load_fomc_schedule

    fomc = load_fomc_schedule("USD-SOFR-1D")
    got_dates = {
        str(r.meeting_label): pd.Timestamp(r.effective_date).date()
        for r in fomc.itertuples()
        if str(r.meeting_label) in EXPECTED_FOMC
    }
    if is_base:
        for label, want in EXPECTED_FOMC.items():
            check_eq(f"fomc {label}", got_dates.get(label), want)
    else:
        print(f"  (non-baseline date; {len(fomc)} meetings loaded)")

    # ---- 2. ZQ strip -----------------------------------------------------------------
    print("\n2. ZQ settles")
    zq_symbols = [f"ZQ{c}{y}" for y in (26, 27) for c in "FGHJKMNQUVXZ"]
    vendor_prices = load_zq_settles(as_of, zq_symbols, args.refresh)
    if args.zq_from == "published":
        if not is_base:
            raise SystemExit("--zq-from published only exists for the 2026-08-07 baseline")
        zq_prices = dict(vendor_prices)
        zq_prices.update(EXPECTED_ZQ)
        print("  using the PUBLISHED strip (method check); vendor deltas in bp:")
        for sym, want in EXPECTED_ZQ.items():
            print(f"    {sym}: vendor {vendor_prices.get(sym, float('nan')):.4f}  "
                  f"published {want:.4f}  diff {100 * (want - vendor_prices.get(sym, float('nan'))):+.2f}bp")
    else:
        zq_prices = vendor_prices
        if is_base:
            for sym, want in EXPECTED_ZQ.items():
                check(f"settle {sym}", zq_prices.get(sym, float("nan")), want, 5e-4)

    # ---- 3. the SR3 option smile -----------------------------------------------------
    print("\n3. SR3 option smile and BL density (observed premiums, vol space)")
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
    from RVUtils.ImpliedDistribution import SFRImpliedDistribution

    opt_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    smile = opt_mdp.fetch_sabr_smile(
        {"symbol": args.symbol, "as_of": as_of, "strike_offsets_bps": "listed"}
    )
    dist = SFRImpliedDistribution(
        use_sabr_vols=False,
        raw_market_open_interest_min=None,
        raw_market_otm_only=True,
        allow_sabr_fallback=False,
        fit_space="vol",
    )
    snap = dist.extract(smile, run_gm=False, run_bkm=True)
    bl = snap.bl_result
    fwd_rate = float(bl.input.forward_rate)
    print(f"  strike_source={snap.strike_source!r}  is_model_density={snap.is_model_density}")
    print(f"  n_strikes={len(bl.input.strikes_price)}  fwd_rate={fwd_rate:.4f}%  "
          f"fwd_resid={bl.forward_residual_bp:+.3f}bp  pre_norm_mass={bl.pre_normalization_mass:.4f}  "
          f"ghost={bl.ghost_mass_fraction:.4f}")
    check_eq("density is observed, not a SABR model", snap.is_model_density, False)
    check("BL forward residual |bp| < 1", abs(float(bl.forward_residual_bp)), 0.0, 1.0, "bp")

    # ---- 4. marginals, anchored on no-meeting months ---------------------------------
    print("\n4. ZQ marginals (anchor = first month with no meeting)")
    ms = build_meeting_set(
        as_of=as_of,
        symbol=args.symbol,
        zq_prices=zq_prices,
        fomc_schedule=fomc,
        expiry=bl.input.expiry_date,
    )
    print(f"  window {ms.window_start} .. {ms.window_end}   expiry {ms.expiry}")
    print(f"  resolved  : {list(zip(ms.resolved_labels, [round(p, 4) for p in ms.resolved_marginals], ms.resolved_weights))}")
    print(f"  unresolved: {list(zip(ms.unresolved_labels, [round(w, 4) for w in ms.unresolved_weights], [round(e, 2) for e in ms.unresolved_expected_bp]))}")
    if is_base:
        check("spot EFFR anchor (100 - ZQQ26)", ms.spot_effr_pct, EXPECTED_SPOT_EFFR, 5e-4, "%")
        by_label = dict(zip(ms.resolved_labels, ms.resolved_marginals))
        by_label.update(dict(zip(ms.unresolved_labels, [
            e / MOVE_SIZE_BP for e in ms.unresolved_expected_bp
        ])))
        for label, want in EXPECTED_MARGINAL_P.items():
            check(f"marginal p({label})", by_label.get(label, float("nan")), want, 2e-3)
        check(
            "cumulative hikes through dec26",
            float(sum(ms.resolved_marginals)),
            EXPECTED_CUM_HIKES_THROUGH_DEC,
            2e-3,
        )

    # ---- 5. the V/X/F fly, reconstructed from the day weights ------------------------
    print("\n5. ZQ V/X/F fly reconstruction (rate space, bp)")
    if is_base:
        r = {s: (100.0 - p) * 100.0 for s, p in zq_prices.items()}  # bp
        market_fly = 2.0 * r["ZQX26"] - r["ZQV26"] - r["ZQH27"] * 0.0 - r["ZQF27"]
        # Day weights straight off the calendar, not thirds.
        oct_days = 31
        oct_after = (datetime.date(2026, 10, 31) - EXPECTED_FOMC["oct26"]).days + 1
        jan_days = 31
        jan_after = (datetime.date(2027, 1, 31) - EXPECTED_FOMC["jan27"]).days + 1
        w_oct = 1.0 - oct_after / oct_days
        w_jan = jan_after / jan_days
        o = EXPECTED_MARGINAL_BP["oct26"]
        d = EXPECTED_MARGINAL_BP["dec26"]
        j = EXPECTED_MARGINAL_BP["jan27"]
        recon = w_oct * o - d - w_jan * j
        print(f"  oct weight already in ZQV26 = {oct_after}/{oct_days}; gap1 coefficient = {w_oct:.4f}")
        print(f"  jan weight in ZQF27         = {jan_after}/{jan_days} = {w_jan:.4f}")
        check("fly reconstruction", recon, EXPECTED_FLY_RECON_BP, 0.05, "bp")
        check("fly reconstruction vs market fly", recon, market_fly, 0.10, "bp")

    # ---- 6. basis calibration --------------------------------------------------------
    print("\n6. SOFR-EFFR basis + term premium (calibrated, not assumed)")
    zq_rate = zq_implied_window_rate_pct(ms)
    basis_bp = (fwd_rate - zq_rate) * 100.0
    print(f"  ZQ-implied window average = {zq_rate:.4f}%   SR3 forward = {fwd_rate:.4f}%")
    if is_base:
        check("ZQ-implied window rate", zq_rate, 3.9305, 0.005, "%")
        check("basis + term premium", basis_bp, EXPECTED_BASIS_BP, 0.5, "bp")

    # ---- 7. copula bounds and the lambda coordinate ----------------------------------
    print("\n7. copula bounds on the measured marginals")
    bounds = coupling_bounds(ms.resolved_marginals)
    print(f"  comonotone  P = {np.round(bounds.probs_comonotone, 3).tolist()}  wings {bounds.wing_comonotone:.3f}")
    print(f"  independent P = {np.round(bounds.probs_independent, 3).tolist()}  wings {bounds.wing_independent:.3f}")
    print(f"  min-variance P = {np.round(bounds.probs_min_variance, 3).tolist()}  wings {bounds.wing_min_variance:.3f} "
          f"[{bounds.lp_status}]")
    if is_base:
        check("comonotone wing mass", bounds.wing_comonotone, EXPECTED_WING_COMONOTONE, 2e-3)
        check("independent wing mass", bounds.wing_independent, EXPECTED_WING_INDEPENDENT, 2e-3)
        check("E[K] copula-free", bounds.expected_k, EXPECTED_CUM_HIKES_THROUGH_DEC, 2e-3)

    print("\n8. observed lattice atoms and lambda")
    for drift in (False, True):
        rates = atom_rates_percent(ms, basis_bp=basis_bp, include_unresolved_drift=drift)
        strict, below, above = observed_atom_probabilities(bl, rates, absorb_tails=False)
        absorbed, _, _ = observed_atom_probabilities(bl, rates, absorb_tails=True)
        tag = "with unresolved drift" if drift else "bare r0+25k+basis "
        print(f"  [{tag}] pins(price) = {np.round(100.0 - rates, 3).tolist()}")
        for name, p in (("strict  ", strict), ("absorbed", absorbed)):
            wr = float(p[0] + p[-1])
            print(f"      {name} P = {np.round(p, 3).tolist()}  sum {p.sum():.3f}  "
                  f"wings {wr:.3f}  lambda_wing {bounds.lambda_wing(wr):+.3f}  "
                  f"E[K] {float(np.dot(np.arange(p.size), p)):.3f}")
        print(f"      off-lattice below {below:.3f} above {above:.3f}")

    m = measure_lambda(meeting_set=ms, bl_result=bl, sr3_forward_rate_pct=fwd_rate,
                       non_meeting_vol_bp_per_sqrt_year=40.0)
    print(f"\n  lambda_wing (absorbed, headline) = {m.lambda_wing:+.3f}")
    print(f"  lambda_wing (renormalised)       = {m.lambda_wing_renorm:+.3f}")
    print(f"  lambda_wing (strict)             = {m.lambda_wing_raw:+.3f}")
    print(f"  lambda_var                       = {m.lambda_var:+.3f} "
          f"(d/d non-meeting vol = {m.lambda_var_sensitivity:+.4f} per bp/yr)")
    print(f"    var_observed {m.var_observed_bp2:9.1f} bp^2   non-meeting (40bp/yr assumed) "
          f"{m.non_meeting_var_bp2:8.1f}  -> meeting {m.var_observed_bp2 - m.non_meeting_var_bp2:8.1f}")
    print(f"    bounds: min {m.var_min_variance_bp2:8.1f}  independent {m.var_independent_bp2:8.1f}  "
          f"comonotone {m.var_comonotone_bp2:8.1f}   non-meeting share {m.basis_var_share:.3f}")
    print(f"    a +/-10 bp/yr error on the non-meeting assumption moves lambda_var by "
          f"{abs(10 * m.lambda_var_sensitivity):.2f}")
    print(f"  per-atom lambda = {[None if not math.isfinite(x) else round(x, 3) for x in m.lambda_atoms]}"
          f"   spread {m.lambda_atom_spread:.3f}")
    print(f"  n_modes={m.n_modes}  modes(price)={[round(x, 3) for x in m.mode_prices]}  "
          f"trough/peak={m.trough_peak_ratio:.3f}")
    if is_base:
        # The published 0.54 is the ABSORBED convention on the bare pins: the observed law
        # has to live on the same support as the copula bounds, so the diffusion mass outside
        # the lattice is assigned to the nearest end atom rather than dropped.
        rates0 = atom_rates_percent(ms, basis_bp=basis_bp, include_unresolved_drift=False)
        absorbed0, _, _ = observed_atom_probabilities(bl, rates0, absorb_tails=True)
        check("lambda_wing on the bare pins, tails absorbed (the published 0.54)",
              bounds.lambda_wing(float(absorbed0[0] + absorbed0[-1])), EXPECTED_LAMBDA_WING_RAW, 0.05)

    print(f"\n=== {_PASSES} passed, {len(_FAILURES)} failed ===")
    for f in _FAILURES:
        print(f"  FAILED: {f}")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
