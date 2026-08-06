r"""Numerical baseline across a rateslib upgrade.

Builds the repo's real linear-rates objects deterministically and dumps every
number to JSON. Run it BEFORE the upgrade, upgrade, run it again, and diff. A
green test suite is not the same claim: a signature change that silently alters a
schedule, a day count or a fixing method still passes every assertion that only
checks a curve was returned.

Usage::

    <env>/python.exe scripts/rateslib_upgrade_baseline.py before.json
    # ... upgrade rateslib, migrate call sites ...
    <env>/python.exe scripts/rateslib_upgrade_baseline.py after.json
    <env>/python.exe scripts/rateslib_upgrade_baseline.py --diff before.json after.json

Everything here is synthetic and deterministic - no network, no database, no
Excel. The point is reproducibility, not realism.
"""

from __future__ import annotations

import datetime
import json
import math
import pathlib
import sys
import traceback
from typing import Any, Dict

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import rateslib as rl  # noqa: E402

REF = datetime.date(2026, 8, 5)
REF_DT = datetime.datetime(2026, 8, 5)

#: The 44-tenor Citi axis, so the baseline covers the real grid shape.
TENORS = (
    "1D", "1W", "2W", "3W", "1M", "2M", "3M", "4M", "5M", "6M", "7M", "8M", "9M", "10M",
    "11M", "1Y", "15M", "18M", "21M", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y",
    "11Y", "12Y", "13Y", "14Y", "15Y", "16Y", "17Y", "18Y", "19Y", "20Y", "25Y", "30Y",
    "35Y", "40Y", "45Y", "50Y",
)

_UNIT_YEARS = {"D": 1 / 365.25, "W": 7 / 365.25, "M": 30.4375 / 365.25, "Y": 1.0}


def _years(tenor: str) -> float:
    return float(tenor[:-1]) * _UNIT_YEARS[tenor[-1]]


def _par(tenor: str) -> float:
    """A smooth, monotone, solvable par curve. Percent."""
    y = _years(tenor)
    return 3.60 + 0.90 * (1.0 - math.exp(-y / 3.0))


PAR_RATES = {t: _par(t) for t in TENORS}


def _record(out: Dict[str, Any], key: str, fn) -> None:
    try:
        out[key] = fn()
    except Exception as exc:  # noqa: BLE001 - a failure IS a result worth diffing
        out[key] = {"__error__": f"{type(exc).__name__}: {exc}"}
        out.setdefault("__errors__", []).append(f"{key}: {type(exc).__name__}: {exc}")
        traceback.print_exc(file=sys.stderr)


# ------------------------------------------------------------------ #
#                    the repo's own curve builders                   #
# ------------------------------------------------------------------ #


def citivelo_intraday_curve() -> Dict[str, Any]:
    """The canonical par-grid -> rateslib Curve+Solver build in this repo."""
    from MDP.IRSwaps.CITI_VELOCITY_INTRADAY.rl_usd_sofr_intraday_builder import (
        build_rl_usd_sofr_intraday_curve,
        par_reprice_errors_bp,
    )

    rlc = build_rl_usd_sofr_intraday_curve(
        par_rates=PAR_RATES, ref_date=REF, curve_id="USD-SOFR-1D"
    )
    curve = rlc.rl_pricing_curve
    nodes = {str(d.date() if hasattr(d, "date") else d): float(curve[d]) for d in curve.nodes.keys}
    errors = par_reprice_errors_bp(rlc)
    return {
        "n_nodes": len(nodes),
        "discount_factors": nodes,
        "max_abs_reprice_bp": float(errors.abs().max()),
        "reprice_bp": {k: float(v) for k, v in errors.items()},
    }


def citivelo_excel_curves() -> Dict[str, Any]:
    """The new multi-currency builders, both backends."""
    from MDP.CitiVelocityExcel.curves import (
        build_ql_ois_curve,
        build_rl_ois_curve,
        forward_rate,
        par_reprice_errors_bp,
        ql_forward_rate,
    )

    out: Dict[str, Any] = {}
    for index in ("USD_SOFR", "EUR_EUROSTR", "GBP_SONIA", "CAD_CORRA", "ILS_SHIR", "JPY_TONAR_LCH"):
        rlc = build_rl_ois_curve(par_rates=PAR_RATES, ref_date=REF, citi_index=index)
        qlc = build_ql_ois_curve(par_rates=PAR_RATES, ref_date=REF, citi_index=index)
        curve = rlc.rl_pricing_curve
        entry = {
            "rl_max_reprice_bp": float(par_reprice_errors_bp(rlc).abs().max()),
            "rl_dfs": {
                str(d.date() if hasattr(d, "date") else d): float(curve[d])
                for d in curve.nodes.keys
            },
            "forwards": {},
        }
        for fwd, tenor in (("0D", "10Y"), ("1Y", "1Y"), ("5Y", "5Y"), ("10Y", "10Y"), ("20Y", "10Y")):
            entry["forwards"][f"{fwd}x{tenor}"] = {
                "rl": float(forward_rate(rlc, forward=fwd, tenor=tenor)),
                "ql": float(ql_forward_rate(qlc, forward=fwd, tenor=tenor)),
            }
        out[index] = entry
    return out


def rl_irswap_curve_wrapper() -> Dict[str, Any]:
    """``RLIRSwapCurve`` - the pricer wrapper every RL branch of IRSwapsMDP returns."""
    import pandas as pd

    from MDP.IRSwaps.CITI_VELOCITY_INTRADAY.rl_usd_sofr_intraday_builder import (
        build_rl_usd_sofr_intraday_curve,
    )
    from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

    rlc = build_rl_usd_sofr_intraday_curve(
        par_rates=PAR_RATES, ref_date=REF, curve_id="USD-SOFR-1D"
    )
    fixings = pd.Series(
        [0.0433] * 400,
        index=pd.date_range(end=pd.Timestamp(REF), periods=400, freq="D"),
    )
    curve = RLIRSwapCurve(
        rl_curve_id="USD-SOFR-1D",
        rl_curve_handle=rlc.rl_pricing_curve,
        fixings=fixings,
        meta_data={"timestamp": REF_DT, "id": "USD-SOFR-1D", "requested_curve_name": "USD-SOFR-1D"},
    )
    out: Dict[str, Any] = {"fair_rate": {}, "pv01": {}, "bpv_sized_notional": {}}
    for tenor in ("2Y", "5Y", "10Y", "30Y"):
        swap = curve.build_irswap(fwd="0D", tenor=tenor)
        out["fair_rate"][tenor] = float(curve.fair_rate(swap))
        out["pv01"][tenor] = float(curve.pv01(swap))
    for fwd, tenor in (("1Y", "1Y"), ("5Y", "5Y"), ("10Y", "10Y")):
        swap = curve.build_irswap(fwd=fwd, tenor=tenor)
        out["fair_rate"][f"{fwd}x{tenor}"] = float(curve.fair_rate(swap))
        out["pv01"][f"{fwd}x{tenor}"] = float(curve.pv01(swap))
    # bpv sizing goes through analytic_delta, which 2.7 renamed the argument of.
    for tenor in ("5Y", "10Y"):
        swap = curve.build_irswap(fwd="0D", tenor=tenor, bpv=10_000.0)
        out["bpv_sized_notional"][tenor] = float(_notional(swap))
    return out


def _notional(instrument: Any) -> float:
    """Read a leg's notional across the 2.1 / 2.7 boundary.

    2.1.1 exposes it as ``instrument.leg1.notional``; 2.7 moved the constructor
    arguments behind ``instrument.kwargs.leg1``, a dict, and dropped the
    attribute from the leg. Both are read here so the SAME quantity is compared
    on both sides of the upgrade - a baseline that silently measured two
    different things would be worse than no baseline.
    """
    kwargs = getattr(instrument, "kwargs", None)
    leg1 = getattr(kwargs, "leg1", None)
    if isinstance(leg1, dict) and "notional" in leg1:
        return float(leg1["notional"])
    return float(instrument.leg1.notional)


def stir_futures() -> Dict[str, Any]:
    """``rl.STIRFuture`` construction and pricing off a solved curve."""
    from MDP.IRSwaps.CITI_VELOCITY_INTRADAY.rl_usd_sofr_intraday_builder import (
        build_rl_usd_sofr_intraday_curve,
    )

    rlc = build_rl_usd_sofr_intraday_curve(
        par_rates=PAR_RATES, ref_date=REF, curve_id="USD-SOFR-1D"
    )
    import pandas as pd

    out: Dict[str, Any] = {"rate": {}, "with_fixings": {}}
    fixings = pd.Series(
        [0.0433] * 400,
        index=pd.date_range(end=pd.Timestamp(REF), periods=400, freq="D"),
    )
    # The repo's own shape: IMM start, next IMM end, spec='usd_stir'.
    for code in ("U26", "Z26", "H27", "M27"):
        start = rl.scheduling.get_imm(code=code)
        end = rl.scheduling.next_imm(start)
        fut = rl.STIRFuture(
            effective=start, termination=end, spec="usd_stir", curves="USD-SOFR-1D"
        )
        out["rate"][code] = float(fut.rate(curves=rlc.rl_pricing_curve))
        # analytic_delta is the contract BPV, and it is convention-sensitive:
        # rateslib 2.7 changed usd_stir from act360 to actacticma, which moved a
        # 3M SOFR future from -25.2778 to exactly -25.0 - the exchange-defined
        # $25/bp. The RATE is unchanged, so only a risk-side check catches it.
        out.setdefault("analytic_delta", {})[code] = float(
            fut.analytic_delta(curves=rlc.rl_pricing_curve).real
        )
        # leg2_rate_fixings= is the kwarg the STIR complex passes everywhere
        # (it was leg2_fixings= before rateslib 2.7).
        fut_f = rl.STIRFuture(
            effective=start,
            termination=end,
            spec="usd_stir",
            curves="USD-SOFR-1D",
            leg2_rate_fixings=fixings,
        )
        out["with_fixings"][code] = float(fut_f.rate(curves=rlc.rl_pricing_curve))
    return out


def fixed_rate_bonds() -> Dict[str, Any]:
    """rateslib ``FixedRateBond`` through the repo's own spec."""
    out: Dict[str, Any] = {}
    for label, spec, coupon, maturity in (
        ("UST_10Y", "us_gb_tsy", 1.25, datetime.datetime(2031, 8, 15)),
        ("UKT_10Y", "uk_gb", 4.25, datetime.datetime(2032, 6, 7)),
        ("DBR_10Y", "de_gb", 2.60, datetime.datetime(2033, 8, 15)),
    ):
        bond = rl.FixedRateBond(
            effective=datetime.datetime(2021, 8, 15),
            termination=maturity,
            fixed_rate=coupon,
            spec=spec,
        )
        settle = rl.add_tenor(REF_DT, "1B", "f", rl.get_calendar("nyc"))
        out[label] = {
            # The number of coupon periods catches a stub-convention change:
            # rateslib 2.7 flipped uk_gb from shortfront to longfront, which
            # changes the SCHEDULE without moving a yield-based metric.
            "n_periods": len(bond.leg1.schedule.aschedule) - 1,
            "first_period_end": str(bond.leg1.schedule.aschedule[1].date()),
            "ytm": float(bond.ytm(price=99.50, settlement=settle)),
            "accrued": float(bond.accrued(settlement=settle)),
            "duration": float(bond.duration(ytm=4.0, settlement=settle, metric="modified")),
            "risk": float(bond.duration(ytm=4.0, settlement=settle, metric="risk")),
        }
    return out


def scheduling_and_calendars() -> Dict[str, Any]:
    """Calendars, tenor arithmetic and day counts - the quiet ones."""
    out: Dict[str, Any] = {"add_tenor": {}, "dcf": {}, "calendars": {}, "imm": {}}
    for name in ("nyc", "tgt", "ldn", "tyo", "zur", "tro", "syd", "wlg", "osl", "stk", "bus", "all"):
        cal = rl.get_calendar(name)
        out["calendars"][name] = [
            rl.add_tenor(REF_DT, "1Y", "mf", cal).isoformat(),
            rl.add_tenor(REF_DT, "10Y", "mf", cal).isoformat(),
            rl.add_tenor(REF_DT, "2B", "f", cal).isoformat(),
        ]
    for tenor in ("1D", "1W", "1M", "3M", "6M", "1Y", "18M", "5Y", "10Y", "30Y"):
        for modifier in ("f", "mf", "p"):
            key = f"{tenor}|{modifier}"
            out["add_tenor"][key] = rl.add_tenor(
                REF_DT, tenor, modifier, rl.get_calendar("nyc")
            ).isoformat()
    end = datetime.datetime(2027, 8, 5)
    for convention in ("act360", "act365f", "actacticma", "30e360", "1+"):
        try:
            out["dcf"][convention] = float(rl.dcf(REF_DT, end, convention))
        except Exception as exc:  # noqa: BLE001
            out["dcf"][convention] = f"__error__ {type(exc).__name__}"
    out["imm"]["get_imm_2026_09"] = rl.get_imm(month=9, year=2026).isoformat()
    out["imm"]["next_imm"] = rl.next_imm(REF_DT).isoformat()
    return out


def spec_table() -> Dict[str, Any]:
    """Every named spec the repo reads, flattened, so a convention change shows up."""
    keep = (
        "frequency", "convention", "calendar", "modifier", "payment_lag", "currency", "stub",
        "eom", "settle", "ex_div", "calc_mode", "leg2_frequency", "leg2_convention",
        "leg2_fixing_method", "leg2_spread_compound_method", "leg2_index_method",
        "leg2_index_lag", "index_method", "index_lag",
    )
    names = (
        "usd_irs", "eur_irs", "gbp_irs", "jpy_irs", "chf_irs", "cad_irs", "aud_irs", "nzd_irs",
        "nok_irs", "sek_irs", "usd_zcis", "eur_zcis", "gbp_zcis", "us_gb_tsy", "us_gb", "uk_gb",
        "de_gb", "fr_gb", "it_gb", "nl_gb", "ch_gb", "se_gb", "no_gb", "ca_gb", "uk_gbi",
        "eurusd_xcs", "gbpusd_xcs", "jpyusd_xcs", "audusd_xcs", "usd_stir", "eur_stir", "gbp_stir",
    )
    out: Dict[str, Any] = {}
    for name in names:
        spec = rl.defaults.spec.get(name)
        if spec is None:
            out[name] = "__missing__"
            continue
        out[name] = {k: str(spec[k]) for k in keep if k in spec}
    return out


def citivelo_inflation() -> Dict[str, Any]:
    """rateslib index curve + ZCIS breakevens."""
    import pandas as pd

    from MDP.CitiVelocityExcel.inflation import build_rl_index_curve, rl_breakeven

    months = pd.date_range("2016-01-01", "2026-08-01", freq="MS")
    fixings = pd.Series(
        [320.0 / (1.025 ** ((months[-1] - m).days / 365.25)) for m in months], index=months
    )
    quotes = {t: 2.45 + 0.10 * (1 - 1 / (1 + i / 3)) for i, t in enumerate(
        ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y")
    )}
    curve = build_rl_index_curve(
        zc_swap_rates=quotes,
        ref_date=REF,
        citi_index="USD_CPURNSA",
        index_base=320.0,
        index_fixings=fixings,
    )
    return {
        "max_reprice_bp": float(curve.max_repricing_error_bp),
        "breakevens": {t: float(rl_breakeven(curve, t)) for t in quotes},
    }


def citivelo_vol_cube() -> Dict[str, Any]:
    """The rateslib-side normal vol cube: forwards, annuities and node vols."""
    from MDP.CitiVelocityExcel.curves import build_rl_ois_curve
    from MDP.CitiVelocityExcel.vol.cube_data import cube_from_quotes, cube_tags
    from MDP.CitiVelocityExcel.vol.rl_cube import build_rl_vol_cube

    expiries = ("1M", "1Y", "5Y")
    tenors = ("2Y", "10Y", "30Y")
    offsets = (-50.0, -25.0, 25.0, 50.0)
    tag_map = cube_tags(
        currency="USD", expiries=expiries, tenors=tenors, offsets_bp=offsets,
        measure="NORMAL", skew_measure="NORMALABSOLUTE",
    )
    quotes = {}
    for tag, (kind, expiry, tenor, offset) in tag_map.items():
        base = 55.0 + 60.0 * math.exp(-_years(tenor) / 8.0) + 20.0 * math.exp(-_years(expiry) / 2.0)
        quotes[tag] = base if kind == "ATM" else base + 6.0 * (offset / 100.0) ** 2 - 3.0 * (offset / 100.0)
    cube = cube_from_quotes(
        quotes=quotes, currency="USD", as_of=REF, expiries=expiries, tenors=tenors,
        offsets_bp=offsets, served_unit="bp",
    )
    rlc = build_rl_ois_curve(par_rates=PAR_RATES, ref_date=REF, citi_index="USD_SOFR")
    built = build_rl_vol_cube(cube=cube, rl_curve=rlc)
    out: Dict[str, Any] = {"forward": {}, "annuity": {}, "vol": {}}
    for expiry in expiries:
        for tenor in tenors:
            key = f"{expiry}x{tenor}"
            out["forward"][key] = float(built.forward(expiry, tenor))
            out["annuity"][key] = float(built.annuity(expiry, tenor))
            out["vol"][key] = float(built.normal_vol(expiry, tenor))
    return out


def citivelo_xccy() -> Dict[str, Any]:
    """The cross-currency collateral solve."""
    from MDP.CitiVelocityExcel.curves import build_rl_ois_curve
    from MDP.CitiVelocityExcel.xccy import (
        basis_from_quotes,
        rl_xccy_reprice_errors_bp,
        solve_rl_collateral_curve,
    )

    tenors = ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y")
    basis = basis_from_quotes(
        quotes={t: -12.0 + 0.4 * i for i, t in enumerate(tenors)},
        ccy1="EUR", ccy2="USD", as_of=REF,
    )
    usd = build_rl_ois_curve(par_rates=PAR_RATES, ref_date=REF, citi_index="USD_SOFR")
    eur = build_rl_ois_curve(
        par_rates={t: v - 1.6 for t, v in PAR_RATES.items()}, ref_date=REF, citi_index="EUR_EUROSTR"
    )
    curves = solve_rl_collateral_curve(
        basis=basis,
        domestic_curve=eur.rl_pricing_curve,
        foreign_curve=usd.rl_pricing_curve,
        fx_rate=1.09,
        ref_date=REF_DT,
        pre_solvers=[eur.rl_pricing_curve_solver, usd.rl_pricing_curve_solver],
    )
    errors = rl_xccy_reprice_errors_bp(curves, basis)
    return {
        "max_abs_error_bp": float(errors.abs().max()),
        "errors_bp": {k: float(v) for k, v in errors.items()},
    }


# ------------------------------------------------------------------ #
#                                diff                                #
# ------------------------------------------------------------------ #


def _walk(prefix: str, node: Any, flat: Dict[str, Any]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _walk(f"{prefix}.{k}" if prefix else str(k), v, flat)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk(f"{prefix}[{i}]", v, flat)
    else:
        flat[prefix] = node


def diff(before_path: str, after_path: str, *, tol: float = 1e-9) -> int:
    before = json.loads(pathlib.Path(before_path).read_text())
    after = json.loads(pathlib.Path(after_path).read_text())
    a, b = {}, {}
    _walk("", before, a)
    _walk("", after, b)

    print(f"rateslib {before.get('rateslib_version')} -> {after.get('rateslib_version')}")
    print(f"{len(a)} baseline values")

    missing = [k for k in a if k not in b]
    added = [k for k in b if k not in a]
    changed_num, changed_other = [], []
    for k, va in a.items():
        if k not in b:
            continue
        vb = b[k]
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool):
            if va == vb:
                continue
            scale = max(abs(va), abs(vb), 1e-12)
            if abs(va - vb) / scale > tol:
                changed_num.append((k, va, vb, abs(va - vb), abs(va - vb) / scale))
        elif va != vb:
            changed_other.append((k, va, vb))

    print(f"\nMISSING in after : {len(missing)}")
    for k in missing[:20]:
        print(f"  - {k}")
    print(f"ADDED in after   : {len(added)}")
    for k in added[:10]:
        print(f"  + {k}")
    print(f"\nNUMERIC CHANGES beyond {tol:g} relative: {len(changed_num)}")
    for k, va, vb, absd, reld in sorted(changed_num, key=lambda r: -r[4])[:40]:
        print(f"  {k}\n      {va!r} -> {vb!r}   (abs {absd:.3e}, rel {reld:.3e})")
    print(f"\nNON-NUMERIC CHANGES: {len(changed_other)}")
    for k, va, vb in changed_other[:40]:
        print(f"  {k}\n      {va!r} -> {vb!r}")

    ok = not missing and not changed_num and not changed_other
    print("\n" + ("IDENTICAL" if ok else "DIFFERENCES FOUND"))
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--diff":
        return diff(sys.argv[2], sys.argv[3])

    out: Dict[str, Any] = {"rateslib_version": rl.__version__}
    _record(out, "citivelo_intraday_curve", citivelo_intraday_curve)
    _record(out, "citivelo_excel_curves", citivelo_excel_curves)
    _record(out, "rl_irswap_curve_wrapper", rl_irswap_curve_wrapper)
    _record(out, "stir_futures", stir_futures)
    _record(out, "fixed_rate_bonds", fixed_rate_bonds)
    _record(out, "scheduling_and_calendars", scheduling_and_calendars)
    _record(out, "spec_table", spec_table)
    _record(out, "citivelo_inflation", citivelo_inflation)
    _record(out, "citivelo_vol_cube", citivelo_vol_cube)
    _record(out, "citivelo_xccy", citivelo_xccy)

    dest = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "rateslib_baseline.json")
    dest.write_text(json.dumps(out, indent=1, sort_keys=True, default=str), encoding="utf-8")
    errors = out.get("__errors__", [])
    print(f"rateslib {rl.__version__}: wrote {dest} ({len(errors)} section error(s))")
    for e in errors:
        print(f"  ERROR {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
