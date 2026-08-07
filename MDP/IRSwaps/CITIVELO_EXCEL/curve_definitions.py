r"""Curve definitions for the twenty Citi Velocity curves, derived not duplicated.

``RLIRSwapCurve`` and ``QLIRSwapCurve`` look their conventions up in
``RATESLIB_CURVE_DEFINITIONS`` / ``QUANTLIB_CURVE_DEFINITIONS`` - the rateslib
wrapper builds its NPV swap from ``curve_def["ReferenceRate"]`` as a ``spec=``
string, and both wrappers read ``Calendar`` / ``BusinessConvention`` /
``DayCounter``. A curve name absent from those maps raises ``KeyError`` the first
time anything downstream prices, so all twenty have to be registered.

Why they are generated rather than written out
----------------------------------------------
Every field here already exists, once, in
:mod:`MDP.CitiVelocityExcel.curves.conventions` - which is what
``build_rl_ois_curve`` and ``build_ql_ois_curve`` calibrate with. Hand-copying
twenty blocks into each of three maps creates sixty places for the *pricing*
conventions to drift away from the *calibration* conventions, and that drift is
silent: the curve still solves, the swap still prices, and the number is wrong.
So the definitions are projected from ``conventions.py`` and a test asserts the
projection agrees with it field by field.

The five currencies rateslib has no spec for
--------------------------------------------
DKK, ILS, SGD, THB and ZAR have no rateslib named spec, but
``RLIRSwapCurve.npv`` *requires* one. Rather than substitute a near-neighbour's
spec - which is how a Copenhagen curve ends up rolling on the TARGET calendar -
a spec is **registered at runtime** under ``<ccy>_ois_citivelo``, built from the
same ``CurveConvention`` fields that ``make_rl_irs`` uses in its no-spec branch.
The two paths are then the same conventions by construction. Verified on
rateslib 2.7.1: ``rl.defaults.spec`` is a plain dict, an entry added to it is
honoured by ``rl.IRS(spec=...)``, a ``rl.Cal`` object is accepted as the
``calendar`` value (which is what the five synthesised calendars are), and an
unknown spec name raises rather than silently defaulting.

Registration never overwrites
-----------------------------
``USD-SOFR-1D`` is already defined in this repo and is referenced 597 times. If a
name is present, the existing definition wins and ours is discarded - a source
being added must not redefine a curve that other sources already price against.
The report returned by :func:`register` names what was added and what was kept.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from MDP.CitiVelocityExcel.curves.conventions import CurveConvention, conventions_for
from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import CITIVELO_EXCEL_CURVES, CurveNameEntry

__all__ = [
    "RegistrationReport",
    "register",
    "rateslib_spec_for",
    "rateslib_definition",
    "quantlib_definition",
    "generic_definition",
    "DERIVED_SPEC_SUFFIX",
]

_logger = logging.getLogger(__name__)
_LOCK = threading.RLock()
_REPORT: Optional["RegistrationReport"] = None

#: Suffix for specs this package registers into ``rl.defaults.spec``. Namespaced
#: so it can never collide with a rateslib-supplied name, present or future.
DERIVED_SPEC_SUFFIX = "_ois_citivelo"

#: rateslib fixed-leg frequency letter -> the ``PaymentFrequency`` spelling the
#: rateslib definition map uses, and the QuantLib frequency constant name.
_FREQUENCY_TOKENS: Dict[str, Tuple[str, str, str]] = {
    # letter: (rl map PaymentFrequency, generic map Frequency, ql.Frequency name)
    "a": ("1y", "Annual", "Annual"),
    "s": ("6m", "Semiannual", "Semiannual"),
    "q": ("3m", "Quarterly", "Quarterly"),
    "m": ("1m", "Monthly", "Monthly"),
    "28d": ("28d", "EveryFourthWeek", "EveryFourthWeek"),
}

_DAY_COUNT_TOKENS: Dict[str, Tuple[str, str]] = {
    # rateslib convention: (generic spelling, QuantLib class name)
    "act360": ("ACT/360", "Actual360"),
    "act365f": ("ACT/365F", "Actual365Fixed"),
}

#: rateslib STIR specs, for the three currencies that have listed STIR futures in
#: this repo. Absent elsewhere rather than guessed - a wrong ReferenceRate2 would
#: silently misprice anything sizing off a futures leg.
_STIR_SPECS: Dict[str, Tuple[str, str]] = {
    "USD": ("usd_stir", "usd_stir1"),
    "EUR": ("eur_stir", "eur_stir1"),
    "GBP": ("gbp_stir", "gbp_stir1"),
}


@dataclass
class RegistrationReport:
    """What :func:`register` did, so it can be asserted rather than assumed."""

    rateslib_added: List[str] = field(default_factory=list)
    rateslib_kept: List[str] = field(default_factory=list)
    quantlib_added: List[str] = field(default_factory=list)
    quantlib_kept: List[str] = field(default_factory=list)
    generic_added: List[str] = field(default_factory=list)
    generic_kept: List[str] = field(default_factory=list)
    specs_registered: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"citivelo_excel curve definitions: rateslib +{len(self.rateslib_added)} "
            f"(kept {len(self.rateslib_kept)}), quantlib +{len(self.quantlib_added)} "
            f"(kept {len(self.quantlib_kept)}), derived rateslib specs "
            f"{len(self.specs_registered)}"
        )


# ------------------------------------------------------------------ #
#                        rateslib named specs                        #
# ------------------------------------------------------------------ #


def rateslib_spec_for(citi_index: str) -> str:
    """The rateslib spec name for a Citi index, registering one if needed.

    Returns rateslib's own spec (``usd_irs``, ``gbp_irs``, ...) for the fifteen
    currencies that have one, and a derived ``<ccy>_ois_citivelo`` for the five
    that do not.
    """
    conv = conventions_for(citi_index)
    if conv.rl_spec:
        return conv.rl_spec
    return _register_derived_spec(conv)


def _register_derived_spec(conv: CurveConvention) -> str:
    """Add a spec built from ``conv`` to ``rl.defaults.spec`` and return its name.

    The field set is deliberately exactly the keys rateslib's own ``*_irs`` specs
    carry - ``frequency stub eom modifier calendar payment_lag currency
    convention leg2_spread_compound_method leg2_fixing_method`` - so an
    ``rl.IRS(spec=...)`` built from it is indistinguishable in shape from one
    built off a shipped spec. Anything extra would be silently dropped and give a
    false sense that it had been honoured.
    """
    import rateslib as rl

    from MDP.CitiVelocityExcel.curves.rl_builder import end_of_month_for, payment_lag_for

    name = f"{conv.currency.lower()}{DERIVED_SPEC_SUFFIX}"
    spec_table = rl.defaults.spec
    if name in spec_table:
        return name
    spec_table[name] = {
        "frequency": conv.fixed_frequency,
        "stub": "shortfront",
        "eom": bool(end_of_month_for(conv.citi_index)),
        "modifier": "mf",
        "calendar": conv.rl_calendar_object(),
        "payment_lag": int(payment_lag_for(conv.citi_index)),
        "currency": conv.currency.lower(),
        "convention": conv.convention,
        "leg2_spread_compound_method": "none_simple",
        "leg2_fixing_method": "rfr_payment_delay",
    }
    _logger.info(
        "citivelo_excel: registered rateslib spec %r for %s (no library spec exists; "
        "conventions are market standard - %s)",
        name,
        conv.citi_index,
        conv.note or "see MDP/CitiVelocityExcel/curves/conventions.py",
    )
    return name


# ------------------------------------------------------------------ #
#                            the projections                         #
# ------------------------------------------------------------------ #


def _tokens(conv: CurveConvention) -> Tuple[Tuple[str, str, str], Tuple[str, str]]:
    freq = _FREQUENCY_TOKENS.get(conv.fixed_frequency)
    if freq is None:
        raise KeyError(
            f"citivelo_excel: no PaymentFrequency spelling for rateslib frequency "
            f"{conv.fixed_frequency!r} ({conv.citi_index}). Add it to _FREQUENCY_TOKENS."
        )
    dcc = _DAY_COUNT_TOKENS.get(conv.convention)
    if dcc is None:
        raise KeyError(
            f"citivelo_excel: no day-count spelling for rateslib convention "
            f"{conv.convention!r} ({conv.citi_index}). Add it to _DAY_COUNT_TOKENS."
        )
    return freq, dcc


def rateslib_definition(entry: CurveNameEntry) -> Dict[str, Any]:
    """The ``RATESLIB_CURVE_DEFINITIONS`` row for one curve."""
    from MDP.CitiVelocityExcel.curves.rl_builder import payment_lag_for

    conv = conventions_for(entry.citi_index)
    (pay_freq, _generic_freq, _ql_freq), (_generic_dcc, _ql_dcc) = _tokens(conv)
    stir, stir1 = _STIR_SPECS.get(conv.currency, (None, None))
    out: Dict[str, Any] = {
        "UseCase": "Fixed_Float_OIS",
        "SingleorMultiCurrency": "Single Currency",
        "ReferenceRate": rateslib_spec_for(entry.citi_index),
        "NotionalCurrency": conv.currency.lower(),
        "ReferenceRateTermValue": 1,
        "ReferenceRateTermUnit": "days",
        "NotionalSchedule": "Constant",
        "DeliveryType": "PHYS",
        "DayCounter": conv.convention,
        # A name where rateslib ships one, otherwise the Cal synthesised from
        # QuantLib's holiday list. rl.add_tenor accepts either, and substituting
        # a proxy calendar is what this avoids.
        "Calendar": conv.rl_calendar or conv.rl_calendar_object(),
        "BusinessConvention": "mf",
        "PaymentFrequency": pay_freq,
        "PaymentLag": int(payment_lag_for(conv.citi_index)),
        "SettlementDays": int(conv.spot_lag),
        "SDR_UPIs": [],
        "CitiIndex": conv.citi_index,
        "Provenance": conv.provenance,
    }
    if stir:
        out["ReferenceRate2"] = stir
        out["ReferenceRate3"] = stir1
    return out


def quantlib_definition(entry: CurveNameEntry) -> Dict[str, Any]:
    """The ``QUANTLIB_CURVE_DEFINITIONS`` row for one curve."""
    import QuantLib as ql

    from MDP.CitiVelocityExcel.curves.rl_builder import payment_lag_for

    conv = conventions_for(entry.citi_index)
    (_pay_freq, _generic_freq, ql_freq), (_generic_dcc, ql_dcc) = _tokens(conv)
    return {
        "UseCase": "Fixed_Float_OIS",
        "SingleorMultiCurrency": "Single Currency",
        "ReferenceRate": conv.ql_index,
        "NotionalCurrency": getattr(ql, f"{conv.currency}Currency")(),
        "ReferenceRateTermValue": 1,
        "ReferenceRateTermUnit": ql.Days,
        "NotionalSchedule": "Constant",
        "DeliveryType": "PHYS",
        "DayCounter": getattr(ql, ql_dcc)(),
        "Calendar": conv.ql_calendar(),
        "BusinessConvention": ql.ModifiedFollowing,
        "PaymentFrequency": getattr(ql, ql_freq),
        "PaymentLag": int(payment_lag_for(conv.citi_index)),
        "SettlementDays": int(conv.spot_lag),
        "SDR_UPIs": [],
        "CitiIndex": conv.citi_index,
        "Provenance": conv.provenance,
    }


def generic_definition(entry: CurveNameEntry) -> Dict[str, Any]:
    """The ``definitions.IRSwaps.CURVE_DEFINITIONS`` row for one curve.

    Registered because ``ql_curve_definitions_map`` asserts, at import, that every
    QuantLib curve name also exists in the generic map. Keeping that invariant
    true is cheaper than deciding it does not apply to us.
    """
    conv = conventions_for(entry.citi_index)
    (_pay_freq, generic_freq, _ql_freq), (generic_dcc, _ql_dcc) = _tokens(conv)
    return {
        "UseCase": "Fixed_Float_OIS",
        "SingleorMultiCurrency": "Single Currency",
        "ReferenceRate": f"{conv.currency}-{entry.curve_name.split('-')[1]}-OIS Compound",
        "NotionalCurrency": conv.currency,
        "ReferenceRateTermValue": 1,
        "ReferenceRateTermUnit": "DAYS",
        "NotionalSchedule": "Constant",
        "DeliveryType": "PHYS",
        "DayCounter": generic_dcc,
        "Calendar": conv.currency,
        "BusinessConvention": "Modified Following",
        "Frequency": generic_freq,
        "PaymentLag": None,
        "SettlementDays": int(conv.spot_lag),
        "SDR_UPIs": [],
    }


# ------------------------------------------------------------------ #
#                            registration                            #
# ------------------------------------------------------------------ #


def register(*, quantlib: bool = True) -> RegistrationReport:
    """Insert the twenty definitions into the repo's maps. Idempotent.

    Parameters
    ----------
    quantlib
        Register the QuantLib map too. Importing QuantLib and materialising its
        holiday lists is the expensive part; a rateslib-only caller can skip it.

    Notes
    -----
    An existing name is never overwritten. That is not politeness: ``USD-SOFR-1D``
    is referenced 597 times in this repo and other sources price against it, so a
    new source silently redefining it would move numbers nothing in this work
    touched.
    """
    global _REPORT
    with _LOCK:
        if _REPORT is not None and (not quantlib or _REPORT.quantlib_added or _REPORT.quantlib_kept):
            return _REPORT

        from definitions.IRSwaps import CURVE_DEFINITIONS
        from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import (
            RATESLIB_CURVE_DEFINITIONS,
        )

        report = _REPORT or RegistrationReport()

        for entry in CITIVELO_EXCEL_CURVES:
            name = entry.curve_name
            if name in CURVE_DEFINITIONS:
                if name not in report.generic_kept:
                    report.generic_kept.append(name)
            else:
                CURVE_DEFINITIONS[name] = generic_definition(entry)
                report.generic_added.append(name)

            if name in RATESLIB_CURVE_DEFINITIONS:
                if name not in report.rateslib_kept:
                    report.rateslib_kept.append(name)
            else:
                RATESLIB_CURVE_DEFINITIONS[name] = rateslib_definition(entry)
                report.rateslib_added.append(name)

        if quantlib:
            from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import (
                QUANTLIB_CURVE_DEFINITIONS,
            )

            for entry in CITIVELO_EXCEL_CURVES:
                name = entry.curve_name
                if name in QUANTLIB_CURVE_DEFINITIONS:
                    if name not in report.quantlib_kept:
                        report.quantlib_kept.append(name)
                else:
                    QUANTLIB_CURVE_DEFINITIONS[name] = quantlib_definition(entry)
                    report.quantlib_added.append(name)

        import rateslib as rl

        report.specs_registered = sorted(
            k for k in rl.defaults.spec if k.endswith(DERIVED_SPEC_SUFFIX)
        )
        _REPORT = report
        _logger.info("%s", report.summary())
        return report
