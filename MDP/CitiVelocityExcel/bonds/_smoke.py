r"""Smoke test for :mod:`MDP.CitiVelocityExcel.bonds`. No Excel, no network.

Run::

    C:/Users/chris/anaconda3/envs/stir/python.exe MDP/CitiVelocityExcel/bonds/_smoke.py

Eight sections, each printing numbers rather than a pass/fail word:

1. **parse** - every one of the 2,162 committed descriptions, with the parse
   rate and EVERY failure printed verbatim.
2. **conventions** - the table against the harvested universe keys.
3. **cross-backend** - one bond per country built in rateslib AND QuantLib from
   the same synthetic clean price, comparing ytm / modified duration / dv01.
   A country that disagrees is printed, not hidden.
4. **sign** - both backends report ``dv01`` positive for a long, and the two
   agree in magnitude.
5. **asset swap** - the par-par spread against ``ql.AssetSwap.fairSpread()``,
   plus the definitional zero test.
6. **universe/ASW legs** - the sparse ``ASW_4_<CCY>`` matrix.
7. **bulk** - every live bond in the universe built in BOTH backends, with the
   yield gap distribution by time to maturity and by country, and every build
   failure printed.
8. **refusals** - the builders raise on a floater, an unknown country and an
   ambiguous price/ytm pair rather than returning a degenerate bond.

The check on the checker: section 3 also runs a *known-answer* case
(T 4.25 05/31/2033 at 99.50, settle 2026-08-06) whose numbers were computed
independently while designing the module, and section 5's zero test has an
answer that is analytically exactly 0.
"""

from __future__ import annotations

import datetime
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:  # smoke script only - never do this in a module
    sys.path.insert(0, str(_REPO_ROOT))

import QuantLib as ql  # noqa: E402
import rateslib as rl  # noqa: E402

from MDP.CitiVelocityExcel.bonds import (  # noqa: E402
    BondUniverse,
    approximate_countries,
    build_ql_bond,
    build_rl_bond,
    conventions_for,
    cross_currency_asw_legs,
    parse_bond_description,
    pseudo_issue_date,
    ql_asset_swap_spread,
    ql_bond_metrics,
    rl_bond_metrics,
    supported_countries,
)
from MDP.CitiVelocityExcel.bonds.conventions import UNIVERSE_COUNTRIES  # noqa: E402
from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog  # noqa: E402

EVAL = datetime.date(2026, 8, 5)
CLEAN = 99.50


def rule(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


# ------------------------------------------------------------------ #
#                        1. description parsing                      #
# ------------------------------------------------------------------ #


def section_parse() -> None:
    rule("1. parse_bond_description over the whole committed universe")
    cat = CitiVeloCatalog.default()
    refs = cat.bonds()
    print(f"descriptions: {len(refs)}")

    ok = 0
    coupon_fail = []
    date_fail = []
    ticker_fail = []
    for r in refs:
        ticker, coupon, maturity = parse_bond_description(
            r.description, country=r.country, reference=EVAL
        )
        if maturity is None:
            date_fail.append(r)
        if coupon is None:
            coupon_fail.append(r)
        if not ticker:
            ticker_fail.append(r)
        if ticker and coupon is not None and maturity is not None:
            ok += 1
    print(f"fully parsed (ticker + coupon + maturity): {ok}/{len(refs)} = {ok / len(refs):.4%}")
    print(f"coupon not read: {len(coupon_fail)}   maturity not read: {len(date_fail)}   "
          f"ticker not read: {len(ticker_fail)}")

    print("\n-- every coupon failure, verbatim --")
    for r in coupon_fail:
        t, c, m = parse_bond_description(r.description, country=r.country, reference=EVAL)
        print(f"  {r.country}.{r.asset_type:<8} {r.isin:<14} {r.description!r:<50} -> ({t!r}, {c}, {m})")
    print("\n-- every maturity failure, verbatim --")
    for r in date_fail:
        print(f"  {r.country} {r.isin} {r.description!r}")
    if not date_fail:
        print("  (none)")
    print("\n-- every ticker failure, verbatim --")
    for r in ticker_fail:
        print(f"  {r.country} {r.isin} {r.description!r}")
    if not ticker_fail:
        print("  (none)")

    # cross-check the parsed maturity against the universe's own maturity column
    mismatch = []
    for r in refs:
        _, _, m = parse_bond_description(r.description, country=r.country, reference=EVAL)
        if m is None or not r.maturity:
            continue
        try:
            mm, dd, yy = str(r.maturity).split("/")
            other = datetime.date(int(yy), int(mm), int(dd))
        except Exception:
            continue
        if other != m:
            mismatch.append((r, m, other))
    print(f"\ndescription-vs-maturity-column disagreements: {len(mismatch)}")
    for r, m, other in mismatch[:20]:
        print(f"  {r.isin} {r.description!r} desc={m} col={other}")

    print("\n-- 40 real descriptions, spot check across all countries --")
    seen: dict[str, int] = {}
    shown = 0
    for r in refs:
        if shown >= 40:
            break
        n = seen.get(r.country, 0)
        if n >= 3:
            continue
        seen[r.country] = n + 1
        t, c, m = parse_bond_description(r.description, country=r.country, reference=EVAL)
        print(f"  {r.country} {r.description!r:<40} -> ticker={t!r:<10} cpn={c} mat={m}")
        shown += 1


# ------------------------------------------------------------------ #
#                          2. conventions                            #
# ------------------------------------------------------------------ #


def section_conventions() -> None:
    rule("2. convention table vs the harvested universe")
    cat = CitiVeloCatalog.default()
    keys = cat.bond_universe_keys()
    countries = sorted({k.split(".")[0] for k in keys})
    print(f"universe keys: {len(keys)}   countries: {len(countries)}")
    print(f"table covers  : {len(supported_countries())}")
    missing = [c for c in countries if c not in supported_countries()]
    extra = [c for c in supported_countries() if c not in countries]
    print(f"universe countries with NO convention: {missing or '(none)'}")
    print(f"convention entries not in the universe: {extra or '(none)'}")
    print(f"UNIVERSE_COUNTRIES constant matches   : {tuple(countries) == UNIVERSE_COUNTRIES}")
    print(f"approximate (market_standard)         : {approximate_countries()}")
    print()
    hdr = (f"{'ctry':<5}{'ccy':<5}{'frq':<4}{'yfrq':<5}{'ql accrual dc':<26}{'ql yield dc':<26}"
           f"{'cal':<28}{'set':<4}{'xdiv':<5}{'spec':<12}prov")
    print(hdr)
    print("-" * len(hdr))
    for c in supported_countries():
        conv = conventions_for(c)
        print(
            f"{conv.country:<5}{conv.currency:<5}{conv.frequency:<4}"
            f"{conv.yield_frequency or conv.frequency:<5}"
            f"{conv.ql_day_count(None).name():<26}{conv.ql_yield_day_counter(None).name():<26}"
            f"{conv.ql_calendar().name():<28}"
            f"{conv.settlement_days:<4}{conv.ex_div_days:<5}{str(conv.rl_spec):<12}{conv.provenance}"
        )


# ------------------------------------------------------------------ #
#                        3. cross-backend build                      #
# ------------------------------------------------------------------ #


def _pick_bond(country: str):
    """A representative, priceable, 5y-20y bond for one country."""
    uni = BondUniverse.from_catalog(country=country).filter(priceable=True)
    lo = datetime.date(EVAL.year + 4, 1, 1)
    hi = datetime.date(EVAL.year + 20, 1, 1)
    candidates = [b for b in uni if b.maturity and lo <= b.maturity <= hi and b.coupon]
    if not candidates:
        candidates = [b for b in uni if b.maturity and b.maturity > EVAL]
    if not candidates:
        return None
    govt = [b for b in candidates if b.asset_type == "GOVT"]
    pool = govt or candidates
    return sorted(pool, key=lambda b: (b.maturity, b.isin))[len(pool) // 2]


def section_cross_backend() -> list[tuple[str, float, float, float]]:
    rule("3. one bond per country, both backends, clean=99.50, eval 2026-08-05")
    print("  known-answer control (T 4.25 05/31/2033, clean 99.50, settle 2026-08-06):")
    print("    rateslib us_gb_tsy ytm should be 4.333684051098, QuantLib ICMA 4.334598875046")
    ctl = BondUniverse.from_catalog(country="USA").lookup("US91282CQT17")
    if ctl is not None:
        rb = build_rl_bond(descriptor=ctl, settlement_date=EVAL)
        qb = build_ql_bond(descriptor=ctl, evaluation_date=EVAL)
        settle = datetime.date(2026, 8, 6)
        rm = rl_bond_metrics(bond=rb, settlement=settle, price=CLEAN)
        qm = ql_bond_metrics(bond=qb, evaluation_date=EVAL, clean_price=CLEAN)
        print(f"    measured    rateslib {rm['ytm']:.12f}   QuantLib {qm['ytm']:.12f}")
        print(f"    settlements rateslib {rm['settlement']}     QuantLib {qm['settlement']}")
    else:
        print("    CONTROL BOND NOT FOUND - the catalog changed")

    print("\n  pseudo-issue invariance (the schedule start is rolled back, not known):")
    for country, isin in (("USA", "US91282CQT17"), ("DEU", "DE000BU2Z023"),
                          ("GBR", "GB00BMF9LG83"), ("ITA", "IT0005083057")):
        desc = BondUniverse.from_catalog(country=country).lookup(isin)
        conv = conventions_for(country)
        base = None
        spread = 0.0
        for backstop in (0, 1, 2, 8, 40):
            start = pseudo_issue_date(
                maturity=desc.maturity, anchor=EVAL, conv=conv, backstop=backstop
            )
            rb = build_rl_bond(descriptor=desc, settlement_date=EVAL, issue_date=start)
            qb = build_ql_bond(descriptor=desc, evaluation_date=EVAL, issue_date=start)
            qm = ql_bond_metrics(bond=qb, evaluation_date=EVAL, clean_price=CLEAN)
            rm = rl_bond_metrics(bond=rb, settlement=qm["settlement"], price=CLEAN)
            got = (rm["ytm"], rm["accrued"], qm["ytm"], qm["accrued"], qm["dv01"])
            if base is None:
                base = got
            spread = max(spread, max(abs(a - b) for a, b in zip(got, base)))
        print(f"    {country} {isin}: max spread over backstops 0/1/2/8/40 periods = {spread:.3e}")

    # negative control - the check above only means something if a BAD schedule
    # start actually moves the numbers. It does, by a lot.
    desc = BondUniverse.from_catalog(country="USA").lookup("US91282CQT17")
    conv = conventions_for("USA")
    for label, start in (
        ("rolled back correctly", pseudo_issue_date(maturity=desc.maturity, anchor=EVAL, conv=conv)),
        ("start INSIDE the current coupon period", EVAL - datetime.timedelta(days=10)),
        ("start AFTER settlement", EVAL + datetime.timedelta(days=30)),
    ):
        rb = build_rl_bond(descriptor=desc, settlement_date=EVAL, issue_date=start)
        qb = build_ql_bond(descriptor=desc, evaluation_date=EVAL, issue_date=start)
        qm = ql_bond_metrics(bond=qb, evaluation_date=EVAL, clean_price=CLEAN)
        rm = rl_bond_metrics(bond=rb, settlement=qm["settlement"], price=CLEAN)
        print(f"    negative control [{label:<38}] rl acc {rm['accrued']:>11.8f} "
              f"ql acc {qm['accrued']:>11.8f} rl ytm {rm['ytm']:.8f}")

    hdr = (f"\n{'ctry':<5}{'isin':<15}{'description':<26}"
           f"{'rl ytm':>12}{'ql ytm':>12}{'d(bp)':>9}"
           f"{'rl mdur':>10}{'ql mdur':>10}{'d':>9}"
           f"{'rl dv01':>10}{'ql dv01':>10}{'d%':>9}{'d acc':>11}")
    print(hdr)
    print("-" * len(hdr))
    rows = []
    accrued_gaps: list[tuple[str, float]] = []
    for country in supported_countries():
        desc = _pick_bond(country)
        if desc is None:
            print(f"{country:<5}NO PRICEABLE BOND IN THE UNIVERSE")
            continue
        try:
            rb = build_rl_bond(descriptor=desc, settlement_date=EVAL)
            qb = build_ql_bond(descriptor=desc, evaluation_date=EVAL)
            qm = ql_bond_metrics(bond=qb, evaluation_date=EVAL, clean_price=CLEAN)
            rm = rl_bond_metrics(bond=rb, settlement=qm["settlement"], price=CLEAN)
        except Exception as exc:  # noqa: BLE001 - a failure is a result, print it
            print(f"{country:<5}{desc.isin:<15}{desc.description[:24]:<26}FAILED {type(exc).__name__}: {exc}")
            rows.append((country, float("nan"), float("nan"), float("nan")))
            continue
        dy = (rm["ytm"] - qm["ytm"]) * 100.0
        dd = rm["mod_duration"] - qm["mod_duration"]
        dv = (rm["dv01"] - qm["dv01"]) / qm["dv01"] * 100.0 if qm["dv01"] else float("nan")
        da = rm["accrued"] - qm["accrued"]
        accrued_gaps.append((country, da))
        print(
            f"{country:<5}{desc.isin:<15}{desc.description[:24]:<26}"
            f"{rm['ytm']:>12.6f}{qm['ytm']:>12.6f}{dy:>9.4f}"
            f"{rm['mod_duration']:>10.5f}{qm['mod_duration']:>10.5f}{dd:>9.5f}"
            f"{rm['dv01']:>10.6f}{qm['dv01']:>10.6f}{dv:>9.4f}{da:>11.2e}"
        )
        rows.append((country, dy, dd, dv))
    finite = [r for r in rows if r[1] == r[1]]
    if finite:
        worst_y = max(finite, key=lambda r: abs(r[1]))
        worst_d = max(finite, key=lambda r: abs(r[2]))
        print(f"\nmax |ytm| discrepancy : {worst_y[1]:+.5f} bp   ({worst_y[0]})")
        print(f"max |mdur| discrepancy: {worst_d[2]:+.6f} yr   ({worst_d[0]})")
    bad_acc = [(c, a) for c, a in accrued_gaps if abs(a) > 1e-9]
    print(f"countries whose ACCRUED disagrees by >1e-9: "
          f"{[(c, round(a, 9)) for c, a in bad_acc] or '(none)'}")
    return rows


# ------------------------------------------------------------------ #
#                            4. sign check                           #
# ------------------------------------------------------------------ #


def section_sign() -> None:
    rule("4. sign convention: dv01 positive for a long, both backends")
    desc = BondUniverse.from_catalog(country="USA").lookup("US91282CQT17")
    qb = build_ql_bond(descriptor=desc, evaluation_date=EVAL)
    qm = ql_bond_metrics(bond=qb, evaluation_date=EVAL, clean_price=CLEAN)
    rb = build_rl_bond(descriptor=desc, settlement_date=EVAL)
    rm = rl_bond_metrics(bond=rb, settlement=qm["settlement"], price=CLEAN)
    freq = qb.citivelo_conventions.ql_yield_frequency()
    raw = ql.BondFunctions.basisPointValue(
        qb,
        ql.InterestRate(qm["ytm"] / 100.0, qb.dayCounter(), ql.Compounded, freq),
        qb.settlementDate(),
    )
    print(f"  QuantLib raw basisPointValue        : {raw:+.9f}   (negative for a long - the trap)")
    print(f"  ql_bond_metrics dv01                : {qm['dv01']:+.9f}")
    print(f"  rl_bond_metrics dv01                : {rm['dv01']:+.9f}")
    print(f"  both positive                       : {qm['dv01'] > 0 and rm['dv01'] > 0}")
    print(f"  relative gap                        : {(rm['dv01'] / qm['dv01'] - 1) * 100:+.5f}%")
    print(f"  bps (per 100 face, per bp)  rl/ql   : {rm['bps']:.9f} / {qm['bps']:.9f}")
    print(f"  convexity (textbook)        rl/ql   : {rm['convexity']:.6f} / {qm['convexity']:.6f}")
    print(f"  rateslib raw convexity              : {rm['convexity_rl_raw']:.9f}")
    # finite-difference control on the QuantLib bond: this is the check on the check
    dc = qb.dayCounter()
    s = qb.settlementDate()
    y = qm["ytm"] / 100.0
    up = ql.BondFunctions.cleanPrice(qb, y + 1e-4, dc, ql.Compounded, freq, s)
    dn = ql.BondFunctions.cleanPrice(qb, y - 1e-4, dc, ql.Compounded, freq, s)
    print(f"  finite-difference bps ((P- - P+)/2) : {(dn - up) / 2:.9f}")


# ------------------------------------------------------------------ #
#                          5. asset swap                             #
# ------------------------------------------------------------------ #


def section_asw() -> None:
    rule("5. par-par asset swap vs ql.AssetSwap.fairSpread()")
    desc = BondUniverse.from_catalog(country="USA").lookup("US91282CQT17")
    print(f"  bond: {desc.isin} {desc.description!r}")
    bond = build_ql_bond(descriptor=desc, evaluation_date=EVAL)
    curve = ql.FlatForward(
        ql.Date(EVAL.day, EVAL.month, EVAL.year),
        ql.QuoteHandle(ql.SimpleQuote(0.04)),
        ql.Actual365Fixed(),
        ql.Continuous,
    )
    handle = ql.YieldTermStructureHandle(curve)
    settle = bond.settlementDate()

    mine = ql_asset_swap_spread(
        bond=bond, clean_price=CLEAN, curve_handle=handle, evaluation_date=EVAL
    )
    print(f"  ql_asset_swap_spread                : {mine:.11f} bp")

    index = ql.USDLibor(ql.Period(3, ql.Months), handle)
    probe = ql.AssetSwap(True, bond, CLEAN, index, 0.0, ql.Schedule(), ql.Actual360(), True)
    coupons = [c for c in (ql.as_floating_rate_coupon(cf) for cf in probe.leg(1)) if c is not None]
    c0 = coupons[0]
    d0, d1 = c0.accrualStartDate(), c0.accrualEndDate()
    tau = c0.dayCounter().yearFraction(d0, d1)
    fwd = (handle.discount(d0) / handle.discount(d1) - 1.0) / tau

    # a STALE first fixing is what breaks ql.AssetSwap - price it first, then
    # overwrite (the fixing history is global per index NAME, not per object).
    index.addFixing(c0.fixingDate(), 0.04)
    stale = ql.AssetSwap(True, bond, CLEAN, index, 0.0, ql.Schedule(), ql.Actual360(), True)
    stale.setPricingEngine(ql.DiscountingSwapEngine(handle))
    stale_bp = stale.fairSpread() * 1e4

    index.addFixing(c0.fixingDate(), fwd, True)
    asw = ql.AssetSwap(True, bond, CLEAN, index, 0.0, ql.Schedule(), ql.Actual360(), True)
    asw.setPricingEngine(ql.DiscountingSwapEngine(handle))
    theirs = asw.fairSpread() * 1e4
    print(f"  ql.AssetSwap.fairSpread()           : {theirs:.11f} bp")
    print(f"  difference (default float schedule) : {mine - theirs:.3e} bp")

    # exact reconciliation: hand QuantLib's OWN leg schedule to the formula
    leg_dates = [c0.accrualStartDate()] + [c.accrualEndDate() for c in coupons]
    exact = ql_asset_swap_spread(
        bond=bond,
        clean_price=CLEAN,
        curve_handle=handle,
        evaluation_date=EVAL,
        float_schedule=leg_dates,
        float_day_count=c0.dayCounter(),
    )
    print(f"  same formula, ql.AssetSwap's own leg : {exact:.11f} bp")
    print(f"  difference (identical leg)          : {exact - theirs:.3e} bp")
    print(f"  with a STALE 4% first fixing        : {stale_bp:.6f} bp "
          f"({stale_bp - theirs:+.6f} bp - a ql.AssetSwap property, not the formula)")

    metrics = ql_bond_metrics(
        bond=bond, evaluation_date=EVAL, clean_price=CLEAN, curve_handle=handle
    )
    on_curve = metrics["curve_clean"]
    zero = ql_asset_swap_spread(
        bond=bond, clean_price=on_curve, curve_handle=handle, evaluation_date=EVAL
    )
    print(f"  curve-implied clean price           : {on_curve:.9f}")
    print(f"  zero test (price the bond ON curve) : {zero:.3e} bp  (must be ~0)")
    print(f"  z-spread from BondFunctions.zSpread : {metrics['zspread'] * 1e4:.6f} bp")

    print("\n  spread vs clean price (must be linear, slope -1/annuity):")
    for px in (95.0, 99.5, 104.0):
        s = ql_asset_swap_spread(bond=bond, clean_price=px, curve_handle=handle, evaluation_date=EVAL)
        print(f"    clean {px:>6.2f} -> {s:>12.5f} bp")

    print("\n  rateslib curve-space path (npv + oaspread), flat 4% log-linear curve:")
    rb = build_rl_bond(descriptor=desc, settlement_date=EVAL, notional=100.0)
    dates = [rl.dt(EVAL.year, EVAL.month, EVAL.day)] + [
        rl.dt(EVAL.year + k, EVAL.month, EVAL.day) for k in (1, 3, 5, 10, 20, 30)
    ]
    nodes = {}
    for i, d in enumerate(dates):
        t = (d - dates[0]).days / 365.0
        nodes[d] = 1.0 if i == 0 else float(pow(2.718281828459045, -0.04 * t))
    rcurve = rl.Curve(nodes=nodes, interpolation="log_linear", convention="act365f", calendar="nyc")
    rmet = rl_bond_metrics(bond=rb, settlement=metrics["settlement"], price=CLEAN, curve=rcurve)
    print(f"    npv (long positive)                : {rmet['npv']:.6f}")
    print(f"    rateslib raw npv (issuer's leg)    : {rmet['npv_rl_raw']:.6f}")
    print(f"    curve_dirty  rl / ql               : {rmet['curve_dirty']:.6f} / {metrics['curve_dirty']:.6f}"
          "   (different curves - flat log-linear vs flat continuous)")
    print(f"    oaspread (z-spread)                : "
          f"{rmet['zspread'] if rmet['zspread'] is None else round(rmet['zspread'], 6)} bp")
    if rmet.get("zspread_error"):
        print(f"    oaspread error                     : {rmet['zspread_error']}")


# ------------------------------------------------------------------ #
#                     6. universe / ASW legs                         #
# ------------------------------------------------------------------ #


def section_universe() -> None:
    rule("6. BondUniverse and the sparse ASW_4_<CCY> matrix")
    uni = BondUniverse.from_catalog()
    print(f"  {uni!r}")
    print(f"  priceable: {len(uni.filter(priceable=True))}   not priceable: {len(uni.parse_failures())}")
    usa = uni.filter(country="USA", asset_type="GOVT")
    print(f"  USA GOVT: {len(usa)}   maturing before 2030: "
          f"{len(usa.filter(maturity_before=datetime.date(2030, 1, 1)))}")
    df = usa.to_frame()
    print(f"  to_frame columns: {list(df.columns)}")
    print(df.head(4).to_string(index=False))

    print("\n  ASW legs (the matrix is sparse and has no derivable rule):")
    probes = [
        ("USA", "T", None),
        ("DEU", "DBR", None),
        ("GBR", "UKT", None),
        ("JPN", "JGB", None),
        ("ITA", "BTPS", None),
        ("CHE", "SWISS", None),
    ]
    for country, ticker, _ in probes:
        pool = uni.filter(country=country, ticker=ticker, priceable=True)
        if not len(pool):
            print(f"    {country} {ticker}: no bond")
            continue
        for b in list(pool)[:2]:
            legs = cross_currency_asw_legs(b)
            vals = pool.available_values(b.isin)
            print(f"    {country} {b.isin} {b.description!r:<26} ASW legs={legs}  values={vals}")

    print("\n  fetch_universe against the FAKE COM surface:")
    try:
        from MDP.CitiVelocityExcel.bonds.universe import fetch_universe

        class _FakeClient:
            def curve_bond(self, tag: str):
                import pandas as pd

                print(f"    tag requested: {tag}")
                return pd.DataFrame(
                    {
                        "Date": [datetime.date(2026, 8, 5)] * 2,
                        "ISIN": ["US91282CCS89", "US91282CNJ61"],
                        "Description": ["T 1.25 08/15/2031", "T 4.0 06/30/2032"],
                        "YIELD": [4.11, 4.02],
                    }
                )

        live = fetch_universe(
            client=_FakeClient(), country="USA", currency="USD", asset_type="GOVT", when=EVAL
        )
        print(f"    {live!r}  sources={sorted({b.source for b in live})}")
        print(f"    {live.lookup('US91282CCS89')}")
    except Exception as exc:  # noqa: BLE001
        print(f"    FAILED {type(exc).__name__}: {exc}")


# ------------------------------------------------------------------ #
#                    7. bulk build of the whole universe              #
# ------------------------------------------------------------------ #


def section_bulk() -> None:
    rule("7. build EVERY live bond in the universe, both backends")
    import statistics
    from collections import defaultdict

    uni = BondUniverse.from_catalog().filter(priceable=True)
    cutoff = datetime.date(EVAL.year, EVAL.month, EVAL.day) + datetime.timedelta(days=15)
    alive = [b for b in uni if b.maturity and b.maturity > cutoff]
    print(f"  priceable: {len(uni)}   still alive at {cutoff}: {len(alive)}")

    failures: list[tuple[str, str, str]] = []
    buckets: dict[str, list[float]] = defaultdict(list)
    per_country: dict[str, list[tuple[float, float]]] = defaultdict(list)
    priced = 0
    for b in alive:
        try:
            rb = build_rl_bond(descriptor=b, settlement_date=EVAL)
            qb = build_ql_bond(descriptor=b, evaluation_date=EVAL)
            qm = ql_bond_metrics(bond=qb, evaluation_date=EVAL, clean_price=CLEAN)
            rm = rl_bond_metrics(bond=rb, settlement=qm["settlement"], price=CLEAN)
        except Exception as exc:  # noqa: BLE001 - collected and printed
            failures.append((b.isin, b.description, f"{type(exc).__name__}: {exc}"))
            continue
        priced += 1
        gap = abs(rm["ytm"] - qm["ytm"]) * 100.0
        ttm = (b.maturity - EVAL).days / 365.25
        key = "<1y" if ttm < 1 else ("1-2y" if ttm < 2 else ("2-5y" if ttm < 5 else ">5y"))
        buckets[key].append(gap)
        per_country[b.country].append((gap, ttm))

    print(f"  priced in BOTH backends: {priced}   failed: {len(failures)}")
    for isin, d, err in failures[:40]:
        print(f"    {isin} {d!r}: {err}")

    print("\n  |ytm| gap by time to maturity:")
    for key in ("<1y", "1-2y", "2-5y", ">5y"):
        v = sorted(buckets[key])
        if not v:
            continue
        print(f"    {key:<6} n={len(v):<5} median={statistics.median(v):>10.5f}bp "
              f"p90={v[int(0.9 * len(v))]:>10.5f}bp max={v[-1]:>10.5f}bp")
    print("  The <1y tail is the LAST COUPON PERIOD: rateslib's us_gb_tsy / it_gb / de_gb /")
    print("  nl_gb / se_gb calc modes use SIMPLE interest there while QuantLib compounds.")
    print("  Outside the final period the two backends agree to ~5e-5 bp.")

    print(f"\n  {'ctry':<6}{'n':<6}{'median|d| bp':>14}{'max|d| bp':>12}{'max|d| ttm>=1y':>16}")
    for c in sorted(per_country):
        v = [g for g, _ in per_country[c]]
        over = [g for g, t in per_country[c] if t >= 1.0]
        print(f"    {c:<4}{len(v):<6}{statistics.median(v):>14.5f}{max(v):>12.5f}"
              f"{(max(over) if over else float('nan')):>16.5f}")


# ------------------------------------------------------------------ #
#                        8. refusal paths                             #
# ------------------------------------------------------------------ #


def section_refusals() -> None:
    rule("8. the builders REFUSE rather than return a degenerate bond")
    uni = BondUniverse.from_catalog()
    floater = next(b for b in uni if b.coupon is None and b.maturity is not None)
    checks = [
        (
            f"build_rl_bond on a floater ({floater.description!r})",
            lambda: build_rl_bond(descriptor=floater, settlement_date=EVAL),
        ),
        (
            f"build_ql_bond on a floater ({floater.description!r})",
            lambda: build_ql_bond(descriptor=floater, evaluation_date=EVAL),
        ),
        ("conventions_for('XXX')", lambda: conventions_for("XXX")),
        (
            "rl_bond_metrics with neither price nor ytm",
            lambda: rl_bond_metrics(
                bond=build_rl_bond(
                    descriptor=BondUniverse.from_catalog().lookup("US91282CQT17"),
                    settlement_date=EVAL,
                ),
                settlement=datetime.date(2026, 8, 6),
            ),
        ),
        (
            "ql_bond_metrics with BOTH clean_price and ytm",
            lambda: ql_bond_metrics(
                bond=build_ql_bond(
                    descriptor=BondUniverse.from_catalog().lookup("US91282CQT17"),
                    evaluation_date=EVAL,
                ),
                evaluation_date=EVAL,
                clean_price=99.5,
                ytm=4.3,
            ),
        ),
    ]
    for label, fn in checks:
        try:
            fn()
            print(f"  DID NOT RAISE (bad): {label}")
        except Exception as exc:  # noqa: BLE001 - raising is the expected result
            first = str(exc).split("\n")[0]
            print(f"  {type(exc).__name__:<18} {label}\n      {first[:150]}")


def main() -> int:
    print(f"rateslib {rl.__version__}   QuantLib {ql.__version__}")
    section_parse()
    section_conventions()
    section_cross_backend()
    section_sign()
    section_asw()
    section_universe()
    section_bulk()
    section_refusals()
    print("\nSMOKE COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
