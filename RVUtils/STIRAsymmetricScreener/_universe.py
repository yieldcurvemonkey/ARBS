"""Universe resolution for the STIR Options Asymmetric Screener.

Given an ``as_of`` date and a ``ScreenerConfig``, produce a list of
``UniverseEntry`` records — one per ``(underlying, expiry)`` pair —
inside the configured DTE band, with the listed CME strike grid attached.

This module is split into pure helpers (testable in isolation) plus a
``resolve_universe`` orchestrator that wires the smile loader through.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _imm_cutoff, _next_contracts
from MDP.STIRFutures._sofr_option_contracts import (
    _cme_listed_strike_grid_for_contract_forward,
    _contract_expiry_date,
)

from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

logger = logging.getLogger(__name__)


# Root mappings — maps user-facing `config.underlyings` names to actual
# option-root prefixes used by `_next_contracts` / strike-grid helpers.
SR3_OPTION_ROOT = "SFR"
SR1_OPTION_ROOT = "SER"
EUR_OPTION_ROOT = "ER"

_QUARTERLY_MONTHS = (3, 6, 9, 12)
_SERIAL_MONTHS = tuple(m for m in range(1, 13) if m not in _QUARTERLY_MONTHS)
_MIDCURVE_ROOTS_BY_TENOR = (
    ("0Q", 1),  # 1y midcurve
    ("2Q", 2),
    ("3Q", 3),
    ("4Q", 4),
)


@dataclass(frozen=True)
class ContractEntry:
    """Pre-strike-grid universe entry — produced by ``enumerate_contracts``.

    ``contract`` is the option contract identifier (e.g. ``"SFRU6"``,
    ``"0QM6"``, ``"SFRX6"``); ``underlying`` is the future the option is
    written on (same as ``contract`` for quarterlies / serials, but the
    underlying quarterly future for midcurves).
    """

    underlying: str
    contract: str
    option_root: str  # SFR, SER, ER, 0Q, 2Q, 3Q, 4Q, ...
    expiry: datetime.date


@dataclass(frozen=True)
class UniverseEntry:
    """Final universe entry with strike grid attached."""

    underlying: str
    contract: str
    option_root: str
    expiry: datetime.date
    forward_price: float
    atm_strike: float
    strikes: Tuple[float, ...]
    fine_step: float
    coarse_step: float
    dte_calendar: int


def _midcurve_underlying_for_option(option_contract: str, *, tenor_years: int) -> str:
    """Given a midcurve option contract token (e.g. ``0QM6``), return the
    underlying future contract that lies ``tenor_years`` years past the
    option's expiry month.
    """
    # 0QM6 → option month code "M", year "6" → underlying = SFR M (year + tenor)
    root = "0Q" if option_contract.startswith("0Q") else option_contract[:2]
    code = option_contract[len(root):]
    if len(code) < 3:
        return option_contract
    month_code = code[-3]  # e.g. "M"
    year_yy = int(code[-2:])
    underlying_year = (year_yy + tenor_years) % 100
    return f"SFR{month_code}{underlying_year:02d}"


def _quarterly_contracts(*, prefix: str, count: int, as_of: datetime.date) -> List[str]:
    return list(
        _next_contracts(
            start_date=as_of,
            prefix=prefix,
            count=count,
            valid_months=list(_QUARTERLY_MONTHS),
            cutoff_fn=_imm_cutoff,
        )
    )


def _serial_contracts(*, prefix: str, count: int, as_of: datetime.date) -> List[str]:
    return list(
        _next_contracts(
            start_date=as_of,
            prefix=prefix,
            count=count,
            valid_months=list(_SERIAL_MONTHS),
        )
    )


def _safe_expiry(contract: str) -> Optional[datetime.date]:
    """Return ``contract`` expiry (IMM date) or ``None`` if undecodable."""
    try:
        return _contract_expiry_date(contract[-3:])
    except Exception as exc:
        logger.debug("expiry_decode_failed", extra={"contract": contract, "error": str(exc)})
        return None


def enumerate_contracts(
    config: ScreenerConfig,
    *,
    as_of: datetime.date,
) -> Tuple[ContractEntry, ...]:
    """Enumerate all option contracts inside the configured DTE band.

    Quarterlies, serials, midcurves are included based on config flags;
    weeklies are gated by ``config.include_weeklies``.
    """
    out: List[ContractEntry] = []

    # The far-end of the DTE band caps how many contracts we need to enumerate.
    # 800 calendar days / 30 ≈ 27 month buckets, so 16 quarterly contracts is
    # plenty (4 years out). Serial coverage is denser, so 24 fits.
    n_quarterlies = 16
    n_serials = 24
    n_midcurves = 16

    for root in config.underlyings:
        if root in {"SR3"}:
            qfx = SR3_OPTION_ROOT
            sfx = SR3_OPTION_ROOT
            mc_prefix_map = _MIDCURVE_ROOTS_BY_TENOR
        elif root == "SR1":
            qfx = SR1_OPTION_ROOT
            sfx = SR1_OPTION_ROOT
            mc_prefix_map = ()
        elif root == "ER":
            qfx = EUR_OPTION_ROOT
            sfx = EUR_OPTION_ROOT
            mc_prefix_map = ()
        else:
            logger.warning("unknown_underlying_root", extra={"root": root})
            continue

        # Quarterlies
        for c in _quarterly_contracts(prefix=qfx, count=n_quarterlies, as_of=as_of):
            exp = _safe_expiry(c)
            if exp is None:
                continue
            dte = (exp - as_of).days
            if dte < config.dte_floor or dte > config.dte_ceiling:
                continue
            out.append(
                ContractEntry(
                    underlying=c,
                    contract=c,
                    option_root=qfx,
                    expiry=exp,
                )
            )

        # Serials
        if config.include_serials:
            for c in _serial_contracts(prefix=sfx, count=n_serials, as_of=as_of):
                exp = _safe_expiry(c)
                if exp is None:
                    continue
                dte = (exp - as_of).days
                if dte < config.dte_floor or dte > config.dte_ceiling:
                    continue
                out.append(
                    ContractEntry(
                        underlying=c,
                        contract=c,
                        option_root=sfx,
                        expiry=exp,
                    )
                )

        # Midcurves (SR3 only — Euribor and SR1 don't have the same listed structure)
        if config.include_midcurves and mc_prefix_map:
            for mc_root, tenor_years in mc_prefix_map:
                # Midcurves use BBG roots like 0Q, 2Q etc. Use _next_contracts
                # with quarterly months for "standard" midcurves; for serials
                # we'd need monthly months but those tend to be illiquid in v1.
                contracts_q = _next_contracts(
                    start_date=as_of,
                    prefix=mc_root,
                    count=n_midcurves,
                    valid_months=list(_QUARTERLY_MONTHS),
                    cutoff_fn=_imm_cutoff,
                )
                for c in contracts_q:
                    exp = _safe_expiry(c)
                    if exp is None:
                        continue
                    dte = (exp - as_of).days
                    if dte < config.dte_floor or dte > config.dte_ceiling:
                        continue
                    out.append(
                        ContractEntry(
                            underlying=_midcurve_underlying_for_option(
                                c, tenor_years=tenor_years
                            ),
                            contract=c,
                            option_root=mc_root,
                            expiry=exp,
                        )
                    )

        # Weeklies — opt-in. Only return when explicitly enabled.
        if config.include_weeklies:
            # TODO(blocker): weekly chains require a separate root resolver
            # (`SR1W`, `2QW`, etc.) that isn't fully wired in `_sofr_option_contracts`.
            # Skipping in v1; surface a TODO so users see the gap.
            logger.warning(
                "weeklies_requested_but_not_implemented",
                extra={"root": root},
            )

    # Dedup and sort
    seen = set()
    uniq: List[ContractEntry] = []
    for e in out:
        key = (e.contract, e.expiry)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    uniq.sort(key=lambda e: (e.expiry, e.contract))
    return tuple(uniq)


def attach_strike_grid(
    entries: Tuple[ContractEntry, ...],
    *,
    smile_loader: Callable[..., object],
    as_of: datetime.date,
) -> Tuple[UniverseEntry, ...]:
    """Attach the listed CME strike grid to each ``ContractEntry``.

    ``smile_loader(contract=..., as_of=...)`` must return an object with
    ``params.forward_price`` (or ``forward_price``) attached. Failures are
    logged and the entry is silently dropped.
    """
    out: List[UniverseEntry] = []
    for e in entries:
        try:
            smile = smile_loader(contract=e.contract, as_of=as_of)
        except Exception as exc:
            logger.warning(
                "smile_load_failed",
                extra={"contract": e.contract, "error": str(exc)},
            )
            continue

        forward = _read_forward(smile)
        if forward is None:
            continue

        grid = _cme_listed_strike_grid_for_contract_forward(
            contract=e.contract,
            forward=forward,
            as_of=as_of,
        )
        if grid is None:
            logger.warning(
                "no_strike_grid",
                extra={"contract": e.contract, "forward": forward},
            )
            continue

        out.append(
            UniverseEntry(
                underlying=e.underlying,
                contract=e.contract,
                option_root=e.option_root,
                expiry=e.expiry,
                forward_price=float(forward),
                atm_strike=float(grid["atm_strike"]),
                strikes=tuple(float(s) for s in grid["strikes"]),
                fine_step=float(grid["fine_step"]),
                coarse_step=float(grid["coarse_step"]),
                dte_calendar=(e.expiry - as_of).days,
            )
        )
    return tuple(out)


def _read_forward(smile) -> Optional[float]:
    params = getattr(smile, "params", smile)
    fwd = getattr(params, "forward_price", None)
    if fwd is None:
        fwd = getattr(smile, "forward_price", None)
    if fwd is None:
        return None
    try:
        return float(fwd)
    except (TypeError, ValueError):
        return None


def resolve_universe(
    config: ScreenerConfig,
    *,
    as_of: datetime.date,
    smile_loader: Callable[..., object],
) -> Tuple[UniverseEntry, ...]:
    """Top-level entry point. Returns a tuple of ``UniverseEntry``s ready
    for downstream Phase 3+ consumption.
    """
    entries = enumerate_contracts(config, as_of=as_of)
    return attach_strike_grid(entries, smile_loader=smile_loader, as_of=as_of)
