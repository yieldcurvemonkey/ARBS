r"""The object ``CitiVelocityMDP.get_pricer`` returns: a market snapshot that builds.

A Velocity snapshot is not a curve. It is a *set of quotes at an instant* plus the
machinery to turn any subset of them into a rateslib or QuantLib object on demand -
a stripped OIS curve, a swaption cube, a bond, an inflation index curve, a
cross-currency collateral curve. Nothing is built until something asks for it,
because a query for a 10y par rate should not pay for a vol cube.

That shape is forced by the entitlements. Velocity's own pricers (``CVDSWAP``,
``CVDSWAPTION``, ``CVCALCDERIVATIVES``, ``CVLADDER``, ``CVSCENARIOANALYSIS``) are
**not entitled** - calling them returns an entitlement failure, not data. So the
only two things a Velocity query can ever ask for are the published quote and a
model we built ourselves from those quotes. Both are exposed here, deliberately
side by side: ``quote(tag)`` and ``rl_par_rate(leg)`` on an outright must agree to
solver tolerance, because the curve was calibrated to that very quote, and a test
asserts it. Without that equivalence the timeseries fast path would be an
unaudited shortcut.

Every builder this delegates to raises rather than returning a degenerate object,
and this class does not soften that: a curve that will not solve, a cube with a
hole in it, or a leg with no quote surfaces as an exception. The repo precedent is
``_assert_risk_populated`` - an all-NaN risk column once shipped as "success".
"""

from __future__ import annotations

import datetime
import logging
import re
import threading
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog
from MDP.CitiVelocityExcel.errors import CitiVelocityError, UnknownTagError
from MDP.CitiVelocityExcel.frequencies import DateLike, normalise_frequency
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
from Query.CitiVelocity._CitiVeloLeg import CitiVeloKind, CitiVeloLeg

__all__ = ["CitiVeloPricer", "classify_tag"]

_logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#                          tag classification                        #
# ------------------------------------------------------------------ #

#: ``(regex, kind, named-group -> leg field)``. Ordered: the first match wins, so
#: the more specific patterns come first.
_TAG_PATTERNS: Tuple[Tuple[re.Pattern[str], CitiVeloKind], ...] = (
    (re.compile(r"^RATES\.OIS\.(?P<citi_index>[^.]+)\.PAR\.(?P<tenor>[^.]+)$"), CitiVeloKind.OIS_PAR),
    (
        re.compile(r"^RATES\.OIS\.(?P<citi_index>[^.]+)\.FWD\.(?P<forward>[^.]+)\.(?P<tenor>[^.]+)$"),
        CitiVeloKind.OIS_FWD,
    ),
    (
        re.compile(r"^RATES\.OIS\.(?P<citi_index>[^.]+)\.SWAP_SPREAD\.(?P<tenor>[^.]+)$"),
        CitiVeloKind.SWAP_SPREAD,
    ),
    (
        re.compile(r"^RATES\.OIS_MEETING\.(?P<currency>[^.]+)\.\d{4}\.(?P<measure>\d{8})$"),
        CitiVeloKind.OIS_MEETING,
    ),
    (
        re.compile(r"^RATES\.SWAP_LIBOR\.(?P<currency>[^.]+)\.PAR\.(?P<tenor>[^.]+)$"),
        CitiVeloKind.SWAP_LIBOR_PAR,
    ),
    (
        re.compile(r"^RATES\.INVOICESPREAD\.(?P<currency>[^.]+)\.(?P<tenor>[^.]+)$"),
        CitiVeloKind.INVOICE_SPREAD,
    ),
    (
        re.compile(r"^RATES\.BASIS_SWAPS\.(?P<measure>[^.]+)\.(?P<currency>[^.]+)\.(?P<tenor>[^.]+)$"),
        CitiVeloKind.BASIS_SWAP,
    ),
    (
        re.compile(
            r"^RATES\.VOL\.(?P<currency>[^.]+)\.ATM(?:_RFR)?\.(?P<measure>[^.]+)"
            r"(?:\.(?:ANNUAL|DAILY))?\.(?P<expiry>[^.]+)\.(?P<tenor>[^.]+)$"
        ),
        CitiVeloKind.VOL_ATM,
    ),
    (
        re.compile(
            r"^RATES\.VOL\.(?P<currency>[^.]+)\.OTM(?:_RFR)?\.(?P<measure>[^.]+)"
            r"(?:\.(?:ANNUAL|DAILY))?\.(?P<offset>OTM_[MN]?\d+)\.(?P<expiry>[^.]+)\.(?P<tenor>[^.]+)$"
        ),
        CitiVeloKind.VOL_OTM,
    ),
    (re.compile(r"^RATES\.BOND\.(?P<isin>[^.]+)\.(?P<measure>[^.]+)$"), CitiVeloKind.BOND),
    (
        re.compile(
            r"^RATES\.XCCY_OIS_SWAP\.(?P<currency>[^.]+)\.(?P<counter_currency>[^.]+)"
            r"\.(?P<forward>[^.]+)\.(?P<tenor>[^.]+)\.(?P<measure>[^.]+)\.BASIS_SPREAD$"
        ),
        CitiVeloKind.XCCY_BASIS,
    ),
    (
        re.compile(r"^RATES\.INFLATION\.SWAP\.(?P<measure>[^.]+)\.(?P<tenor>[^.]+)$"),
        CitiVeloKind.INFLATION_SWAP,
    ),
    (re.compile(r"^RATES\.INFLATION\.INDEX\.(?P<measure>.+)$"), CitiVeloKind.INFLATION_INDEX),
    (
        re.compile(r"^RATES\.TSY\.[^.]+\.[^.]+\.(?P<tenor>[^.]+)\.(?P<measure>[^.]+)$"),
        CitiVeloKind.TSY,
    ),
    (
        re.compile(r"^RATES\.FUTURES\.(?P<measure>[^.]+)\.(?P<tenor>NEXT_\d+)\.[^.]+$"),
        CitiVeloKind.FUTURES,
    ),
    (
        re.compile(
            r"^RATES\.SPREAD_OPTIONS\.(?P<currency>[^.]+)\.(?P<measure>[^.]+)\.[^.]+"
            r"\.(?P<expiry>[^.]+)\.(?P<tenor>[^.]+)$"
        ),
        CitiVeloKind.SPREAD_OPTION,
    ),
    (
        re.compile(
            r"^RATES\.MIDCURVES\.(?P<currency>[^.]+)\.(?P<measure>[^.]+)\.[^.]+"
            r"\.(?P<expiry>[^.]+)\.(?P<tenor>[^.]+)$"
        ),
        CitiVeloKind.MIDCURVE,
    ),
)


def classify_tag(tag: str) -> Tuple[CitiVeloKind, Dict[str, Any]]:
    """Read a tag's kind and its structural fields straight off the string.

    A pass-through tag is therefore just as well understood as one built through
    :mod:`MDP.CitiVelocityExcel.tags` - it gets the right unit, the right
    repricing route and the right column label. An unrecognised tag classifies as
    ``RAW``, which is quote-only and unit-less rather than an error: a tag newer
    than the committed catalog must never be blocked.

    >>> kind, fields = classify_tag("RATES.OIS.USD_SOFR.PAR.10Y")
    >>> kind.name, fields["citi_index"], fields["tenor"]
    ('OIS_PAR', 'USD_SOFR', '10Y')
    """
    text = str(tag).strip()
    for pattern, kind in _TAG_PATTERNS:
        m = pattern.match(text)
        if m is None:
            continue
        fields: Dict[str, Any] = {k: v for k, v in m.groupdict().items() if v is not None}
        offset = fields.pop("offset", None)
        if offset is not None:
            body = offset[len("OTM_") :]
            fields["offset_bp"] = -float(body[1:]) if body[:1] in {"M", "N"} else float(body)
        if kind in {CitiVeloKind.VOL_ATM, CitiVeloKind.VOL_OTM} and "currency" not in fields:
            fields["currency"] = None
        return kind, fields
    return CitiVeloKind.RAW, {}


# ------------------------------------------------------------------ #
#                              the pricer                            #
# ------------------------------------------------------------------ #


class CitiVeloPricer:
    """A Citi Velocity market snapshot that builds models on demand.

    >>> pricer = mdp.get_pricer({"timestamp": date(2026, 8, 4),          # doctest: +SKIP
    ...                          "citi_index": "USD_SOFR"})
    >>> pricer.quote("RATES.OIS.USD_SOFR.PAR.10Y")                       # doctest: +SKIP
    4.22537
    >>> leg = pricer.resolve_leg(citi_index="USD_SOFR", tenor="10Y")     # doctest: +SKIP
    >>> pricer.rl_par_rate(leg)                                          # doctest: +SKIP
    4.225370...

    Parameters
    ----------
    quotes
        The cached-then-live tag reader.
    as_of
        The instant this snapshot represents. ``None`` means "the latest row
        available", which is what ``timestamp='live'`` resolves to.
    method
        How a timestamp is resolved against the served rows: ``asof`` (default,
        backward-only), ``nearest`` or ``exact``. ``asof`` is the default for the
        same reason it is elsewhere in this repo - ``nearest`` is
        direction-unbounded and was measured answering an early-morning request
        with a snapshot from the future.
    """

    def __init__(
        self,
        *,
        quotes: CitiVeloQuotes,
        as_of: Optional[DateLike] = None,
        freq: str = "DAILY",
        price_point: str = "CLOSE",
        method: str = "asof",
        citi_index: Optional[str] = None,
        currency: Optional[str] = None,
        catalog: Optional[CitiVeloCatalog] = None,
        prefetch: Sequence[str] = (),
        lookback: Optional[datetime.timedelta] = None,
    ):
        self._quotes = quotes
        self.as_of = None if as_of is None else pd.Timestamp(as_of)
        self.freq = normalise_frequency(freq)
        self.price_point = str(price_point).upper()
        self.method = str(method)
        self.default_citi_index = citi_index
        self.default_currency = currency
        self.catalog = catalog or CitiVeloCatalog.default()
        self._lookback = lookback
        self._quote_cache: Dict[str, float] = {}
        self._missing: set[str] = set()
        self._models: Dict[Tuple[str, ...], Any] = {}
        self._lock = threading.RLock()
        if prefetch:
            self.prefetch(prefetch)

    # -- identity -------------------------------------------------------

    def id(self) -> str:
        stamp = "live" if self.as_of is None else self.as_of.isoformat()
        return f"citivelo_excel@{stamp}"

    def reference_date(self) -> datetime.date:
        if self.as_of is not None:
            return self.as_of.date()
        return datetime.date.today()

    def __repr__(self) -> str:  # pragma: no cover - display only
        return f"CitiVeloPricer({self.id()}, {len(self._quote_cache)} quotes)"

    # -- quotes ---------------------------------------------------------

    def prefetch(self, tags: Iterable[str]) -> Dict[str, float]:
        """Fetch many tags in as few ``CVTSHIST`` calls as the chunk size allows.

        Batching is the whole performance story for this source: a 44-tenor par
        grid, a vol slice and a bond yield asked for together cost one call, not
        forty-six.
        """
        wanted = [t for t in dict.fromkeys(str(t) for t in tags) if t not in self._quote_cache]
        wanted = [t for t in wanted if t not in self._missing]
        if not wanted:
            return {}
        with self._lock:
            served = self._quotes.snapshot(
                wanted,
                self.as_of,
                self.freq,
                method=self.method,
                price_point=self.price_point,
                lookback=self._lookback,
            )
            self._quote_cache.update(served)
            self._missing.update(t for t in wanted if t not in served)
        return served

    def quote(self, tag: str) -> float:
        """The number Citi publishes for ``tag`` at this snapshot's instant.

        Raises
        ------
        CitiVelocityError
            When the tag serves no row at or before the snapshot. It raises
            rather than returning NaN: a fly quietly priced with one missing wing
            is a plausible number that is wrong.
        """
        text = str(tag)
        if text in self._quote_cache:
            return self._quote_cache[text]
        served = self.prefetch([text])
        if text in served:
            return served[text]
        raise CitiVelocityError(
            f"No Citi Velocity quote for {text!r} at {self.id()} (freq={self.freq}, "
            f"method={self.method}). The tag may be invalid, outside its history, or "
            "outside the fetched window - validate it with client.validate_with_controls([...])."
        )

    def quotes_for(self, tags: Sequence[str]) -> Dict[str, float]:
        """Quotes for many tags, fetched in one batch; missing tags are absent."""
        self.prefetch(tags)
        return {t: self._quote_cache[t] for t in tags if t in self._quote_cache}

    def has_quote(self, tag: str) -> bool:
        try:
            self.quote(tag)
        except CitiVelocityError:
            return False
        return True

    # -- leg resolution -------------------------------------------------

    def resolve_leg(self, **spec: Any) -> CitiVeloLeg:
        """Turn a leg spec into a concrete :class:`CitiVeloLeg`.

        This is the single place that knows how a query's fields become a tag, so
        no structure builder ever spells a tag itself.
        """
        from MDP.CitiVelocityExcel import tags as T

        explicit = spec.get("tag")
        if explicit:
            kind, fields = classify_tag(str(explicit))
            merged = {**fields, **{k: v for k, v in spec.items() if k != "tag" and v is not None}}
            return _leg_from_fields(str(explicit), kind, merged)

        family = str(spec.get("family") or "").upper() or None
        citi_index = spec.get("citi_index") or self.default_citi_index
        currency = spec.get("currency") or self.default_currency
        tenor = spec.get("tenor")
        forward = spec.get("forward")
        expiry = spec.get("expiry")
        offset_bp = spec.get("offset_bp")
        isin = spec.get("isin")
        counter = spec.get("counter_currency")
        measure = spec.get("measure")

        if family is None:
            family = _infer_family(
                citi_index=citi_index,
                currency=currency,
                expiry=expiry,
                isin=isin,
                counter_currency=counter,
                forward=forward,
            )

        if family in {"OIS", "OIS_PAR"}:
            _require(citi_index, "citi_index", family)
            _require(tenor, "tenor", family)
            tag = T.ois_par(citi_index, tenor, catalog=self.catalog)
        elif family in {"OIS_FWD", "FWD"}:
            _require(citi_index, "citi_index", family)
            tag = T.ois_fwd(citi_index, forward, tenor, catalog=self.catalog)
        elif family == "SWAP_SPREAD":
            _require(citi_index, "citi_index", family)
            tag = T.ois_swap_spread(citi_index, tenor, catalog=self.catalog)
        elif family == "SWAP_LIBOR":
            _require(currency, "currency", family)
            tag = T.swap_libor(currency, "PAR", tenor, catalog=self.catalog, warn=True)
        elif family in {"VOL", "VOL_ATM"} and offset_bp in (None, 0, 0.0):
            _require(currency, "currency", family)
            tag = T.vol_atm(
                currency, expiry, tenor, measure=measure or "NORMAL", catalog=self.catalog
            )
        elif family in {"VOL", "VOL_OTM"}:
            _require(currency, "currency", family)
            tag = T.vol_otm(
                currency,
                expiry,
                tenor,
                offset_bp,
                measure=measure or "NORMALABSOLUTE",
                catalog=self.catalog,
            )
        elif family == "BOND":
            _require(isin, "isin", family)
            tag = T.bond(isin, measure or "YIELD", catalog=self.catalog)
        elif family in {"XCCY", "XCCY_BASIS"}:
            _require(currency, "currency", family)
            _require(counter, "counter_currency", family)
            tag = T.xccy_basis(
                currency,
                counter,
                tenor,
                forward=forward or "SPOT",
                leg=measure or "SPREAD_LEG",
                catalog=self.catalog,
            )
        elif family in {"INFLATION", "INFLATION_SWAP"}:
            _require(measure or currency, "measure (the inflation index token)", family)
            tag = T.inflation_swap(measure or currency, tenor, catalog=self.catalog)
        elif family == "TSY":
            tag = T.tsy_otr(tenor, measure or "YIELD", catalog=self.catalog)
        elif family == "OIS_MEETING":
            _require(currency, "currency", family)
            tag = T.ois_meeting(currency, measure, catalog=self.catalog)
        elif family == "INVOICESPREAD":
            tag = T.invoice_spread(currency or "USD", tenor, catalog=self.catalog)
        elif family == "BASIS_SWAPS":
            tag = T.basis_swap(measure, currency, tenor, catalog=self.catalog)
        else:
            raise UnknownTagError(
                f"Cannot resolve a Citi Velocity leg for family={family!r}. Pass tag= explicitly, "
                "or use one of: OIS, OIS_FWD, SWAP_SPREAD, SWAP_LIBOR, VOL, BOND, XCCY, INFLATION, "
                "TSY, OIS_MEETING, INVOICESPREAD, BASIS_SWAPS."
            )

        kind, fields = classify_tag(tag)
        merged = {
            **fields,
            **{
                k: v
                for k, v in {
                    "citi_index": citi_index,
                    "currency": currency,
                    "counter_currency": counter,
                    "tenor": tenor,
                    "forward": forward,
                    "expiry": expiry,
                    "offset_bp": offset_bp,
                    "isin": isin,
                    "measure": measure,
                    "notional": spec.get("notional"),
                }.items()
                if v is not None
            },
        }
        return _leg_from_fields(tag, kind, merged)

    # -- model cache ----------------------------------------------------

    def _model(self, key: Tuple[str, ...], build: Callable[[], Any]) -> Any:
        with self._lock:
            if key not in self._models:
                self._models[key] = build()
            return self._models[key]

    # -- swap curves ----------------------------------------------------

    def par_grid(self, citi_index: Optional[str] = None) -> Dict[str, float]:
        """``{tenor: par_rate_percent}`` for one Citi OIS curve at this instant.

        The whole 44-tenor axis goes out as one ``CVTSHIST`` call - the add-in's
        own curve export is a single call, which is where the chunk size comes
        from.
        """
        from MDP.CitiVelocityExcel import tags as T

        index = self._resolve_index(citi_index)
        grid_tags = T.ois_par_grid(index, catalog=self.catalog)
        served = self.quotes_for(grid_tags)
        out: Dict[str, float] = {}
        for tag, value in served.items():
            _, fields = classify_tag(tag)
            tenor = fields.get("tenor")
            if tenor:
                out[tenor] = float(value)
        if not out:
            raise CitiVelocityError(
                f"No par rates served for {index} at {self.id()}. Nothing can be stripped from an "
                "empty grid."
            )
        return out

    def rl_curve(self, citi_index: Optional[str] = None, **build_kwargs: Any) -> Any:
        """The rateslib curve stripped from this instant's par grid."""
        from MDP.CitiVelocityExcel.curves.rl_builder import build_rl_ois_curve

        index = self._resolve_index(citi_index)
        key = ("rl_curve", index, _kwargs_key(build_kwargs))
        return self._model(
            key,
            lambda: build_rl_ois_curve(
                par_rates=self.par_grid(index),
                ref_date=self.reference_date(),
                citi_index=index,
                timestamp=self.as_of,
                **build_kwargs,
            ),
        )

    def ql_curve(self, citi_index: Optional[str] = None, **build_kwargs: Any) -> Any:
        """The QuantLib curve bootstrapped from this instant's par grid."""
        from MDP.CitiVelocityExcel.curves.ql_builder import build_ql_ois_curve

        index = self._resolve_index(citi_index)
        key = ("ql_curve", index, _kwargs_key(build_kwargs))
        return self._model(
            key,
            lambda: build_ql_ois_curve(
                par_rates=self.par_grid(index),
                ref_date=self.reference_date(),
                citi_index=index,
                **build_kwargs,
            ),
        )

    def rl_par_rate(self, leg: CitiVeloLeg) -> float:
        """Par rate off the locally-stripped rateslib curve, in percent."""
        from MDP.CitiVelocityExcel.curves.rl_builder import forward_rate

        index, forward, tenor = self._rate_leg_parts(leg)
        return float(forward_rate(self.rl_curve(index), forward=forward, tenor=tenor))

    def ql_par_rate(self, leg: CitiVeloLeg) -> float:
        """Par rate off the locally-bootstrapped QuantLib curve, in percent."""
        from MDP.CitiVelocityExcel.curves.ql_builder import ql_forward_rate

        index, forward, tenor = self._rate_leg_parts(leg)
        return float(ql_forward_rate(self.ql_curve(index), forward=forward, tenor=tenor))

    def rl_forward_rate(self, leg: CitiVeloLeg) -> float:
        return self.rl_par_rate(leg)

    def ql_forward_rate(self, leg: CitiVeloLeg) -> float:
        return self.ql_par_rate(leg)

    def rl_zero_rate(self, leg: CitiVeloLeg) -> float:
        """Continuously-compounded zero rate at the leg's maturity, in percent."""
        import rateslib as rl

        index, _forward, tenor = self._rate_leg_parts(leg)
        rlc = self.rl_curve(index)
        curve = rlc.rl_pricing_curve
        maturity = rl.add_tenor(
            _to_datetime(curve.nodes.initial), tenor, "mf", _calendar_for(index)
        )
        df = float(curve[maturity])
        years = (maturity - _to_datetime(curve.nodes.initial)).days / 365.25
        if years <= 0 or df <= 0:
            raise CitiVelocityError(f"Cannot compute a zero rate at {tenor} on {index}.")
        import math

        return -math.log(df) / years * 100.0

    def ql_zero_rate(self, leg: CitiVeloLeg) -> float:
        index, _forward, tenor = self._rate_leg_parts(leg)
        qlc = self.ql_curve(index)
        import QuantLib as ql

        with qlc.pinned():
            period = _ql_period(tenor)
            ref = qlc.curve.referenceDate()
            date = qlc.conventions.ql_calendar().advance(ref, period)
            return float(
                qlc.curve.zeroRate(date, ql.Actual365Fixed(), ql.Continuous, ql.Annual).rate()
            ) * 100.0

    def rl_discount(self, leg: CitiVeloLeg) -> float:
        import rateslib as rl

        index, _forward, tenor = self._rate_leg_parts(leg)
        curve = self.rl_curve(index).rl_pricing_curve
        maturity = rl.add_tenor(
            _to_datetime(curve.nodes.initial), tenor, "mf", _calendar_for(index)
        )
        return float(curve[maturity])

    def ql_discount(self, leg: CitiVeloLeg) -> float:
        index, _forward, tenor = self._rate_leg_parts(leg)
        qlc = self.ql_curve(index)
        with qlc.pinned():
            ref = qlc.curve.referenceDate()
            date = qlc.conventions.ql_calendar().advance(ref, _ql_period(tenor))
            return float(qlc.curve.discount(date))

    def rl_npv(self, leg: CitiVeloLeg, **kwargs: Any) -> float:
        """NPV of a unit-notional swap struck at ``fixed_rate`` (percent)."""
        import rateslib as rl

        from MDP.CitiVelocityExcel.curves.rl_builder import make_rl_irs
        from MDP.CitiVelocityExcel.curves.conventions import conventions_for

        index, forward, tenor = self._rate_leg_parts(leg)
        rlc = self.rl_curve(index)
        meta = getattr(rlc, "meta", {}) or {}
        conv = conventions_for(index)
        calendar = conv.rl_calendar_object()
        effective = rl.add_tenor(meta["spot"], forward, "f", calendar)
        fixed_rate = float(kwargs.get("fixed_rate", self.quote(leg.tag)))
        notional = float(leg.notional or kwargs.get("notional") or 1_000_000.0)
        irs = make_rl_irs(
            conv=conv,
            calendar=calendar,
            effective=effective,
            tenor=tenor,
            curve_id=meta["curve_id"],
            fixed_rate=fixed_rate,
        )
        irs.notional = notional
        return float(irs.npv(curves=rlc.rl_pricing_curve))

    def rl_pv01(self, leg: CitiVeloLeg) -> float:
        """Analytic delta per basis point for a unit notional of this leg."""
        import rateslib as rl

        from MDP.CitiVelocityExcel.curves.rl_builder import make_rl_irs
        from MDP.CitiVelocityExcel.curves.conventions import conventions_for

        index, forward, tenor = self._rate_leg_parts(leg)
        rlc = self.rl_curve(index)
        meta = getattr(rlc, "meta", {}) or {}
        conv = conventions_for(index)
        calendar = conv.rl_calendar_object()
        effective = rl.add_tenor(meta["spot"], forward, "f", calendar)
        irs = make_rl_irs(
            conv=conv,
            calendar=calendar,
            effective=effective,
            tenor=tenor,
            curve_id=meta["curve_id"],
            fixed_rate=0.0,
        )
        irs.notional = float(leg.notional or 1_000_000.0)
        return float(irs.analytic_delta(curves=rlc.rl_pricing_curve))

    def rl_dv01(self, leg: CitiVeloLeg) -> float:
        """Alias for :meth:`rl_pv01`.

        rateslib's ``analytic_delta`` is the exact first-order sensitivity for a
        linear swap, so a bumped DV01 would differ only by the second-order term.
        Both names are exposed because the repo uses both.
        """
        return self.rl_pv01(leg)

    # -- vol ------------------------------------------------------------

    def cube_data(self, currency: Optional[str] = None, **kwargs: Any) -> Any:
        """The Citi swaption cube for one currency at this instant."""
        from MDP.CitiVelocityExcel.vol.cube_data import cube_from_quotes, cube_tags

        ccy = str(currency or self.default_currency or "").upper()
        if not ccy:
            raise CitiVelocityError("cube_data needs a currency (e.g. 'USD').")
        key = ("cube", ccy, _kwargs_key(kwargs))

        def build() -> Any:
            tag_map = cube_tags(currency=ccy, catalog=self.catalog, **kwargs)
            served = self.quotes_for(list(tag_map))
            return cube_from_quotes(
                quotes=served,
                currency=ccy,
                as_of=self.reference_date(),
                catalog=self.catalog,
                strict=False,
                **kwargs,
            )

        return self._model(key, build)

    def rl_vol_cube(self, currency: Optional[str] = None, **kwargs: Any) -> Any:
        from MDP.CitiVelocityExcel.vol.rl_cube import build_rl_vol_cube

        ccy = str(currency or self.default_currency or "").upper()
        cube = self.cube_data(ccy, **kwargs)
        index = _ois_index_for_currency(ccy)
        key = ("rl_cube", ccy, _kwargs_key(kwargs))
        return self._model(
            key,
            lambda: build_rl_vol_cube(cube=cube, rl_curve=self.rl_curve(index), citi_index=index),
        )

    def ql_vol_cube(self, currency: Optional[str] = None, **kwargs: Any) -> Any:
        from MDP.CitiVelocityExcel.vol.ql_cube import build_ql_swaption_cube

        ccy = str(currency or self.default_currency or "").upper()
        cube = self.cube_data(ccy, **kwargs)
        index = _ois_index_for_currency(ccy)
        key = ("ql_cube", ccy, _kwargs_key(kwargs))
        return self._model(
            key,
            lambda: build_ql_swaption_cube(
                cube=cube, curve=self.ql_curve(index), citi_index=index
            ),
        )

    def rl_vol(self, leg: CitiVeloLeg, *, strike: Optional[float] = None) -> float:
        """Normal vol in basis points, off the rateslib-backed cube."""
        cube = self.rl_vol_cube(leg.currency)
        return float(
            cube.normal_vol(leg.expiry, leg.tenor, strike=strike, offset_bp=leg.offset_bp or 0.0)
        )

    def ql_vol(self, leg: CitiVeloLeg, *, strike: Optional[float] = None) -> float:
        """Normal vol in basis points, off the QuantLib cube."""
        cube = self.ql_vol_cube(leg.currency)
        return float(cube.vol(leg.expiry, leg.tenor, strike, offset_bp=leg.offset_bp))

    def rl_option_premium(self, leg: CitiVeloLeg, **kwargs: Any) -> float:
        cube = self.rl_vol_cube(leg.currency)
        strike = kwargs.get("strike")
        if strike is None:
            strike = cube.forward(leg.expiry, leg.tenor)
        return float(
            cube.price(
                leg.expiry,
                leg.tenor,
                float(strike),
                right=str(kwargs.get("right", "payer")),
                notional=kwargs.get("notional"),
            )
        )

    def ql_option_premium(self, leg: CitiVeloLeg, **kwargs: Any) -> float:
        """Bachelier premium off the QuantLib cube's vol and the QuantLib curve."""
        from Query.Base.bachelier import bachelier_price

        cube = self.ql_vol_cube(leg.currency)
        rl_cube = self.rl_vol_cube(leg.currency)
        forward = float(kwargs.get("forward", rl_cube.forward(leg.expiry, leg.tenor)))
        strike = float(kwargs.get("strike", forward))
        vol_bp = cube.vol(leg.expiry, leg.tenor, strike)
        tte = float(rl_cube.time_to_expiry(leg.expiry))
        annuity = float(rl_cube.annuity(leg.expiry, leg.tenor))
        notional = float(leg.notional or kwargs.get("notional") or 1.0)
        right = "C" if str(kwargs.get("right", "payer")).lower().startswith("p") else "P"
        return (
            bachelier_price(
                right,
                strike / 100.0,
                forward / 100.0,
                vol_bp / 10_000.0,
                tte,
                1.0,
            )
            * annuity
            * notional
        )

    # -- bonds ----------------------------------------------------------

    def bond_descriptor(self, isin: str) -> Any:
        from MDP.CitiVelocityExcel.bonds.universe import BondUniverse

        key = ("bond_universe",)
        universe = self._model(key, lambda: BondUniverse.from_catalog(catalog=self.catalog))
        descriptor = universe.lookup(str(isin).upper())
        if descriptor is None:
            raise CitiVelocityError(
                f"{isin!r} is not in the harvested CVCURVEBOND universe (2,162 ISINs). "
                "Fetch its curve first with client.curve_bond(...), or pass a descriptor."
            )
        return descriptor

    def rl_bond(self, isin: str) -> Any:
        from MDP.CitiVelocityExcel.bonds.rl_bonds import build_rl_bond

        return self._model(
            ("rl_bond", str(isin).upper()),
            lambda: build_rl_bond(descriptor=self.bond_descriptor(isin)),
        )

    def ql_bond(self, isin: str) -> Any:
        from MDP.CitiVelocityExcel.bonds.ql_bonds import build_ql_bond

        return self._model(
            ("ql_bond", str(isin).upper()),
            lambda: build_ql_bond(
                descriptor=self.bond_descriptor(isin), evaluation_date=self.reference_date()
            ),
        )

    def bond_clean_price(self, isin: str) -> float:
        """The bond's published clean price, which every metric is computed from."""
        from MDP.CitiVelocityExcel import tags as T

        return self.quote(T.bond(isin, "PRICE", catalog=self.catalog))

    def rl_bond_metric(self, leg: CitiVeloLeg, metric: str) -> float:
        from MDP.CitiVelocityExcel.bonds.rl_bonds import rl_bond_metrics, rl_settlement_date

        isin = _require(leg.isin, "isin", "BOND")
        bond = self.rl_bond(isin)
        settle = rl_settlement_date(
            descriptor=self.bond_descriptor(isin), as_of=self.reference_date()
        )
        metrics = rl_bond_metrics(bond=bond, settlement=settle, price=self.bond_clean_price(isin))
        return _metric(metrics, metric, isin)

    def ql_bond_metric(self, leg: CitiVeloLeg, metric: str) -> float:
        from MDP.CitiVelocityExcel.bonds.ql_bonds import ql_bond_metrics

        isin = _require(leg.isin, "isin", "BOND")
        metrics = ql_bond_metrics(
            bond=self.ql_bond(isin),
            evaluation_date=self.reference_date(),
            clean_price=self.bond_clean_price(isin),
        )
        return _metric(metrics, metric, isin)

    def ql_bond_asw(self, leg: CitiVeloLeg) -> float:
        from MDP.CitiVelocityExcel.bonds.ql_bonds import ql_asset_swap_spread

        isin = _require(leg.isin, "isin", "BOND")
        descriptor = self.bond_descriptor(isin)
        index = _ois_index_for_currency(descriptor.currency)
        return float(
            ql_asset_swap_spread(
                bond=self.ql_bond(isin),
                clean_price=self.bond_clean_price(isin),
                curve_handle=self.ql_curve(index).handle,
                evaluation_date=self.reference_date(),
            )
        )

    # -- cross-currency -------------------------------------------------

    def xccy_basis_curve(self, ccy1: str, ccy2: str, **kwargs: Any) -> Any:
        from MDP.CitiVelocityExcel import tags as T
        from MDP.CitiVelocityExcel.xccy.basis_data import basis_from_quotes
        from MDP.CitiVelocityExcel.xccy import XCCY_TENORS

        a, b = str(ccy1).upper(), str(ccy2).upper()
        key = ("xccy_basis", a, b, _kwargs_key(kwargs))

        def build() -> Any:
            tenors = kwargs.get("tenors") or XCCY_TENORS
            tag_map = {
                t: T.xccy_basis(
                    a,
                    b,
                    t,
                    forward=kwargs.get("forward", "SPOT"),
                    leg=kwargs.get("leg", "SPREAD_LEG"),
                    catalog=self.catalog,
                )
                for t in tenors
            }
            served = self.quotes_for(list(tag_map.values()))
            quotes = {t: served[tag] for t, tag in tag_map.items() if tag in served}
            return basis_from_quotes(
                quotes=quotes,
                ccy1=a,
                ccy2=b,
                as_of=self.reference_date(),
                forward=kwargs.get("forward", "SPOT"),
                leg=kwargs.get("leg", "SPREAD_LEG"),
            )

        return self._model(key, build)

    def rl_xccy_basis(self, leg: CitiVeloLeg) -> float:
        """The fair basis at this leg's tenor, from a solved collateral curve.

        Requires an FX spot rate: pass it through ``value_kwargs['fx_rate']`` or
        via the query's ``market_request``. There is no FX source in Velocity's
        rates namespace, so this cannot be inferred and is not guessed.
        """
        raise CitiVelocityError(
            "rl_xccy_basis needs an FX spot rate, which the RATES.* namespace does not publish. "
            "Solve the collateral curve explicitly with "
            "MDP.CitiVelocityExcel.xccy.solve_rl_collateral_curve(basis=..., fx_rate=...) and read "
            "the fair basis off it. The published quote is available as CitiVeloValue.QUOTE."
        )

    def ql_xccy_basis(self, leg: CitiVeloLeg) -> float:
        raise CitiVelocityError(
            "ql_xccy_basis needs an FX spot rate, which the RATES.* namespace does not publish. "
            "Use MDP.CitiVelocityExcel.xccy.bootstrap_ql_xccy_discount_curve(..., fx_spot=...) "
            "directly. The published quote is available as CitiVeloValue.QUOTE."
        )

    # -- inflation ------------------------------------------------------

    def inflation_curve(self, citi_index: str, *, backend: str = "rl", **kwargs: Any) -> Any:
        from MDP.CitiVelocityExcel import tags as T
        from MDP.CitiVelocityExcel.inflation import (
            DEFAULT_CALIBRATION_TENORS,
            INDEX_LEVEL_TOKEN_FOR_SWAP_INDEX,
        )

        token = str(citi_index).upper()
        key = ("infl", backend, token, _kwargs_key(kwargs))

        def rates() -> Dict[str, float]:
            tenors = kwargs.get("tenors") or DEFAULT_CALIBRATION_TENORS
            tag_map = {t: T.inflation_swap(token, t, catalog=self.catalog) for t in tenors}
            served = self.quotes_for(list(tag_map.values()))
            return {t: served[tag] for t, tag in tag_map.items() if tag in served}

        def index_base() -> float:
            level_token = INDEX_LEVEL_TOKEN_FOR_SWAP_INDEX.get(token)
            if level_token is None:
                raise CitiVelocityError(
                    f"No RATES.INFLATION.INDEX level is mapped for {token}; pass index_base= "
                    "explicitly. The index base cannot be inferred from swap rates alone."
                )
            return self.quote(T.inflation_index(level_token, catalog=self.catalog))

        def build() -> Any:
            if backend == "rl":
                from MDP.CitiVelocityExcel.inflation.rl_inflation import build_rl_index_curve

                return build_rl_index_curve(
                    zc_swap_rates=rates(),
                    ref_date=self.reference_date(),
                    citi_index=token,
                    index_base=float(kwargs.get("index_base") or index_base()),
                )
            from MDP.CitiVelocityExcel.inflation.ql_inflation import build_ql_zero_inflation_curve

            return build_ql_zero_inflation_curve(
                zc_swap_rates=rates(),
                ref_date=self.reference_date(),
                citi_index=token,
                index_base=kwargs.get("index_base"),
            )

        return self._model(key, build)

    def rl_breakeven(self, leg: CitiVeloLeg) -> float:
        from MDP.CitiVelocityExcel.inflation.rl_inflation import rl_breakeven

        token = _require(leg.measure or leg.currency, "measure (inflation index token)", "INFLATION")
        return float(rl_breakeven(self.inflation_curve(token, backend="rl"), leg.tenor))

    def ql_breakeven(self, leg: CitiVeloLeg) -> float:
        from MDP.CitiVelocityExcel.inflation.ql_inflation import ql_breakeven

        token = _require(leg.measure or leg.currency, "measure (inflation index token)", "INFLATION")
        return float(ql_breakeven(self.inflation_curve(token, backend="ql"), leg.tenor))

    # -- internals ------------------------------------------------------

    def _resolve_index(self, citi_index: Optional[str]) -> str:
        index = citi_index or self.default_citi_index
        if not index:
            raise CitiVelocityError(
                "No Citi OIS index. Pass citi_index= on the query or on the MDP request "
                "(e.g. 'USD_SOFR')."
            )
        return str(index).upper()

    @staticmethod
    def _rate_leg_parts(leg: CitiVeloLeg) -> Tuple[str, str, str]:
        if leg.kind is CitiVeloKind.SWAP_LIBOR_PAR:
            raise CitiVelocityError(
                "RATES.SWAP_LIBOR cannot be repriced locally: its shape has never been confirmed "
                "against CVTSHIST and its legs are IBOR-indexed, so the OIS conventions in "
                "curves/conventions.py would be the wrong ones. Use CitiVeloValue.QUOTE."
            )
        if leg.kind not in {CitiVeloKind.OIS_PAR, CitiVeloKind.OIS_FWD}:
            raise CitiVelocityError(
                f"A {leg.kind.value} leg has no local par-rate model. "
                "Citi's own pricers are not entitled, so only the published quote exists for it. "
                "Use CitiVeloValue.QUOTE."
            )
        if not leg.citi_index or not leg.tenor:
            raise CitiVelocityError(f"Leg {leg.tag!r} is missing citi_index or tenor.")
        return str(leg.citi_index), str(leg.forward or "0D"), str(leg.tenor)


# ------------------------------------------------------------------ #
#                              helpers                               #
# ------------------------------------------------------------------ #


def _leg_from_fields(tag: str, kind: CitiVeloKind, fields: Mapping[str, Any]) -> CitiVeloLeg:
    allowed = {
        "citi_index",
        "currency",
        "counter_currency",
        "tenor",
        "forward",
        "expiry",
        "offset_bp",
        "isin",
        "measure",
        "notional",
    }
    kwargs = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "offset_bp" in kwargs:
        kwargs["offset_bp"] = float(kwargs["offset_bp"])
    if "notional" in kwargs:
        kwargs["notional"] = float(kwargs["notional"])
    return CitiVeloLeg(tag=tag, kind=kind, **kwargs)


def _infer_family(
    *,
    citi_index: Optional[str],
    currency: Optional[str],
    expiry: Optional[str],
    isin: Optional[str],
    counter_currency: Optional[str],
    forward: Optional[str],
) -> str:
    if isin:
        return "BOND"
    if counter_currency:
        return "XCCY"
    if expiry and currency:
        return "VOL"
    if citi_index and forward:
        return "OIS_FWD"
    if citi_index:
        return "OIS"
    raise UnknownTagError(
        "Cannot infer a Citi Velocity family from the leg spec. Pass family= explicitly, "
        "or give one of: citi_index (OIS), currency+expiry (VOL), isin (BOND), "
        "currency+counter_currency (XCCY)."
    )


def _require(value: Any, name: str, family: str) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise UnknownTagError(f"{family} legs require {name}.")
    return value


def _metric(metrics: Mapping[str, Any], name: str, isin: str) -> float:
    if name not in metrics:
        raise CitiVelocityError(
            f"Bond metric {name!r} not available for {isin}. Available: {sorted(metrics)}."
        )
    value = metrics[name]
    if value is None:
        raise CitiVelocityError(f"Bond metric {name!r} is None for {isin}.")
    return float(value)


def _kwargs_key(kwargs: Mapping[str, Any]) -> str:
    return repr(sorted((k, repr(v)) for k, v in kwargs.items()))


def _calendar_for(citi_index: str) -> Any:
    from MDP.CitiVelocityExcel.curves.conventions import conventions_for

    return conventions_for(citi_index).rl_calendar_object()


def _to_datetime(value: Any) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value
    return datetime.datetime(value.year, value.month, value.day)


def _ql_period(tenor: str) -> Any:
    import QuantLib as ql

    token = str(tenor).strip().upper()
    unit = {"D": ql.Days, "W": ql.Weeks, "M": ql.Months, "Y": ql.Years}[token[-1]]
    return ql.Period(int(token[:-1]), unit)


def _ois_index_for_currency(currency: str) -> str:
    """The Citi OIS index token this package uses for a currency by default."""
    from MDP.CitiVelocityExcel.curves.conventions import CITI_OIS_CONVENTIONS

    ccy = str(currency).upper()
    preferred = {
        "USD": "USD_SOFR",
        "EUR": "EUR_EUROSTR",
        "GBP": "GBP_SONIA",
        "JPY": "JPY_TONAR_LCH",
        "CHF": "CHF_SARON",
        "CAD": "CAD_CORRA",
        "AUD": "AUD_AONIA",
        "NZD": "NZD_NZIONA",
        "NOK": "NOK_NOWA",
        "SEK": "SEK_STINA",
        "DKK": "DKK_TNDKK",
        "ILS": "ILS_SHIR",
        "MXN": "MXN_T_FONDEO",
        "SGD": "SGD_SORA",
        "THB": "THB_THOR",
        "ZAR": "ZAR_ZARONIA",
    }
    index = preferred.get(ccy)
    if index is None or index not in CITI_OIS_CONVENTIONS:
        raise CitiVelocityError(
            f"No default Citi OIS curve for currency {currency!r}. "
            f"Known currencies: {', '.join(sorted(preferred))}. Pass citi_index= explicitly."
        )
    return index
