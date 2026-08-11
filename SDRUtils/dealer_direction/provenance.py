"""The audit trail: what produced each row, and what happened to the ones that did not.

Two jobs, and they are the same job seen from either end.

**Per row.** A ladder cell is a number with no units of trust attached. The
consumer cannot gate on quality, and a wrong-looking cell cannot be debugged,
unless the row says which curve answered, how stale that answer was, which
clock field the trade time came from, whether the notional was a cap or a
number, which rule made the call, and which code produced all of it.

**Per population.** Every unit is either in the ladder or carries exactly one
``EXCL_*`` reason, and each reason's DV01 share is reported. The written note is
built from that table, so the shares have to sum -- and making them sum is
harder than it looks, which is what :func:`coverage_table` is mostly about.

WHY THE VINTAGE IS NOT ``stir_flow.vintage.code_vintage``
---------------------------------------------------------
That stamp hashes the *repo's own modules* and nothing else, so it is blind to
the changes that actually moved the numbers here. Measured (LEDGER T-7): the
current tree hashes to ``870c71f0698b`` against the persisted ``468474ca6f84``,
but the change that repaired a row from ``UNKNOWN`` to a real direction was the
rateslib 2.1.1 -> 2.7.1 upgrade, which is not in ``VINTAGE_SOURCES`` at all.
Neither is the tape generation, and the tape *was* regenerated under those rows'
feet (T-3: kept-unit overlap collapses to 200/294 on 2026-07-24). The curve
source is a third: D11 holds the code constant and varies barchart -> citi
precisely because that alone shifts the label mix by >=34 pp.

So the stamp here covers code **and** rateslib **and** the tape generation
**and** the curve source. It is still only necessary, never sufficient:
**never reason "same vintage => same rows".** A curve store can be backfilled
under a fixed source name -- the 2026-08-10 Fed Funds backfill repaired the
whole minute tape without changing one byte of ARBS -- and this stamp cannot
see that either. :func:`vintage_components` exists so a consumer can read the
parts rather than only observe that the digest moved.
"""
from __future__ import annotations

import dataclasses
import functools
import hashlib
import math
import pathlib

import pandas as pd

from SDRUtils._swappulse_scripts._tape_tables import TAPE_GENERATION
from SDRUtils.dealer_direction import snapshot
from SDRUtils.dealer_direction import types as T
from SDRUtils.stir_flow import vintage as _stir_vintage

_REPO = pathlib.Path(__file__).resolve().parents[2]

#: The reason label for a unit that DID reach the ladder. Not an ``EXCL_*``
#: constant on purpose -- it is the complement of that vocabulary, and giving it
#: a name is what lets the coverage table be a partition rather than a list of
#: failures with an unstated remainder.
IN_LADDER = "IN_LADDER"

# Output-determining modules of this package. Listed even when they do not exist
# yet: `_hash_sources` hashes a missing file as an explicit marker, so a module
# *appearing* bumps the vintage, which is the correct behaviour while the
# package is still being assembled by several hands.
#
# `health.py` is excluded for the reason `stir_flow` excludes `daylog.py`: it
# reads the output, it does not determine it, and a monitoring edit must not
# invalidate an eight-hour backfill. `provenance.py` IS included, unlike
# `stir_flow/vintage.py` which excludes itself -- this file carries the coverage
# arithmetic and the fallback DV01 proxy, both of which change reported numbers,
# and over-sensitivity is the safe direction for that error.
VINTAGE_SOURCES = (
    "SDRUtils/dealer_direction/conventions.py",
    "SDRUtils/dealer_direction/types.py",
    "SDRUtils/dealer_direction/snapshot.py",
    "SDRUtils/dealer_direction/universe.py",
    "SDRUtils/dealer_direction/midprice.py",
    "SDRUtils/dealer_direction/probability.py",
    "SDRUtils/dealer_direction/upfront.py",
    "SDRUtils/dealer_direction/krd.py",
    "SDRUtils/dealer_direction/lifecycle.py",
    "SDRUtils/dealer_direction/imputation.py",
    "SDRUtils/dealer_direction/lineage.py",
    "SDRUtils/dealer_direction/sanity.py",
    "SDRUtils/dealer_direction/ladder.py",
    "SDRUtils/dealer_direction/provenance.py",
)

#: Flat rate for the fallback annuity. Not a market view -- it is the same
#: 4% ``risk_sanity`` uses, and the proxy is only ever a *relative* size.
_PROXY_FLAT_RATE = 0.04


# --------------------------------------------------------------------------
# the vintage
# --------------------------------------------------------------------------

def _default_curve_source() -> str:
    return snapshot.CURVE_SOURCE


def _rateslib_version() -> str:
    """rateslib's version without importing rateslib.

    ``import rateslib`` costs seconds and emits a licence banner on every
    subprocess; the distribution metadata answers the only question the stamp
    asks. Patched by test.
    """
    try:
        from importlib.metadata import version

        return str(version("rateslib"))
    except Exception:  # noqa: BLE001 - a stamp must never break a backfill
        return _stir_vintage.UNKNOWN_VINTAGE


def _hash_sources(h) -> None:
    for rel in VINTAGE_SOURCES:                       # tuple order is hash order
        h.update(rel.encode("utf-8"))
        try:
            # normalise line endings: a CRLF/LF checkout difference is not a
            # logic change, and this repo converts on checkout
            h.update((_REPO / rel).read_bytes().replace(b"\r\n", b"\n"))
        except OSError:
            h.update(b"<missing>")


def vintage_components(curve_source: str | None = None) -> dict:
    """The parts the digest is built from, so the digest is auditable.

    A changed hash tells a reader that *something* moved. This tells them
    what -- which is the difference between "re-run everything" and "rateslib
    went 2.1.1 to 2.7.1, expect the pricing-error repairs".
    """
    return {
        "dealer_direction": _dd_source_digest(),
        "stir_flow": _stir_vintage.code_vintage(),
        "rateslib": _rateslib_version(),
        "tape_generation": TAPE_GENERATION,
        "curve_source": curve_source or _default_curve_source(),
    }


@functools.lru_cache(maxsize=1)
def _dd_source_digest() -> str:
    h = hashlib.sha256()
    _hash_sources(h)
    return h.hexdigest()[:12]


@functools.lru_cache(maxsize=8)
def code_vintage(curve_source: str | None = None) -> str:
    """12-hex stamp over the code, rateslib, the tape generation and the curve.

    ``curve_source`` is an argument rather than a constant because D11 runs the
    same code against two curves on purpose, and those two runs must not carry
    the same stamp -- the whole point of that measurement is that the curve
    alone moves the label mix by tens of percentage points.
    """
    h = hashlib.sha256()
    for key, val in vintage_components(curve_source).items():
        h.update(key.encode("utf-8"))
        h.update(str(val).encode("utf-8"))
    return h.hexdigest()[:12]


# --------------------------------------------------------------------------
# per-row provenance
# --------------------------------------------------------------------------

def build(unit, pricing, call, *, pricing_clock_field: str,
          notional_imputed: bool = False,
          notional_impute_factor: float | None = None,
          risk_sanity_reason: str | None = None,
          failure_reason: str | None = None,
          curve_source: str | None = None) -> T.Provenance:
    """Materialise :class:`types.Provenance` for one unit.

    Works for a unit that never priced -- ``pricing`` may be ``None`` -- because
    those are exactly the rows the coverage table has to account for, and a
    provenance record that only exists for successes explains nothing.

    ``failure_reason`` defaults to the call's own exclusion rather than being
    required separately, so the two cannot disagree.
    """
    if failure_reason is None and call is not None:
        failure_reason = call.exclusion
    return T.Provenance(
        unit_key=unit.unit_key,
        curve_name=getattr(pricing, "curve_name", "") or "",
        curve_timestamp=getattr(pricing, "curve_timestamp", pd.NaT),
        snapshot_lag_seconds=getattr(pricing, "snapshot_lag_seconds", None),
        snapshot_policy=getattr(pricing, "snapshot_policy", "") or "",
        pricing_clock_field=pricing_clock_field,
        rule=None if call is None else call.rule,
        notional_imputed=bool(notional_imputed),
        notional_impute_factor=notional_impute_factor,
        risk_sanity_reason=risk_sanity_reason,
        tau_bucket=None if call is None else call.tau_bucket,
        code_vintage=code_vintage(curve_source),
        failure_reason=failure_reason,
    )


def to_frame(rows) -> pd.DataFrame:
    """Provenance records as a frame, in the dataclass's own field order."""
    cols = [f.name for f in dataclasses.fields(T.Provenance)]
    rows = list(rows)
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([dataclasses.asdict(r) for r in rows], columns=cols)


# --------------------------------------------------------------------------
# the fallback size
# --------------------------------------------------------------------------

def annuity_dv01_proxy(*, notional: float, start_years: float,
                       tenor_years: float, flat_rate: float = _PROXY_FLAT_RATE) -> float:
    """A DV01 scale that exists for a unit that never priced.

    ``E = N * (A(f+T) - A(f)) * 1e-4`` with ``A(x) = (1 - exp(-r x)) / r``.

    **Not ``notional * tenor * 1e-4``.** F-16 measured that form: 37% of flow
    legs are forward-starting, and the naive bound mis-flags 58.1% of deep
    forward starts while the annuity form holds a median ratio flat at 1.00 in
    every tenor band. A 5y5y is not a 10y; it is the difference of two
    annuities, and sizing it as a 10y roughly doubles it.
    """
    if tenor_years < 0 or start_years < 0:
        raise ValueError(f"negative tenor {tenor_years!r} / start {start_years!r}")

    def _a(x: float) -> float:
        return (1.0 - math.exp(-flat_rate * x)) / flat_rate

    return float(notional) * (_a(start_years + tenor_years) - _a(start_years)) * 1e-4


def annuity_dv01_proxy_from_dates(*, notional: float, as_of, effective,
                                  maturity, flat_rate: float = _PROXY_FLAT_RATE) -> float:
    """:func:`annuity_dv01_proxy` from the three dates a leg actually carries.

    A past-start leg is measured from today, not from its own effective date --
    the risk that remains is the stub, and 36,763 ``ECONOMIC_UNWIND`` rows are
    past-effective by construction (F-8).
    """
    as_of = pd.Timestamp(as_of)
    start = max(0.0, (pd.Timestamp(effective) - as_of).days / 365.25)
    end = max(start, (pd.Timestamp(maturity) - as_of).days / 365.25)
    return annuity_dv01_proxy(notional=notional, start_years=start,
                              tenor_years=end - start, flat_rate=flat_rate)


# --------------------------------------------------------------------------
# the coverage accounting
# --------------------------------------------------------------------------

def coverage_table(prov, *, dv01, dv01_fallback=None) -> pd.DataFrame:
    """DV01 share by outcome: one row per reason plus :data:`IN_LADDER`.

    Three ways this accounting lies if it is written the obvious way, all
    guarded here:

    1. **A unit appearing twice.** Two rows for one unit inflate one reason and
       the shares still sum to 1. Raised, not deduplicated -- a duplicate means
       the caller's two halves disagree about what happened to that unit.
    2. **An excluded unit with no size.** ``EXCL_NO_CURVE`` and
       ``EXCL_PRICING_ERROR`` units have no repriced DV01 *by definition*, so
       taking the size from the repricing drops exactly the failures being
       reported and leaves the shares summing to 1 over the population that did
       not fail. That is the self-flattering version of this table, and it is
       the one a reader would believe. Hence ``dv01_fallback``
       (:func:`annuity_dv01_proxy`), and a hard error when a unit has neither.
    3. **Tape ``risk`` as the fallback.** Never. F-4/F-16: 55 sentinel rows are
       99.99994% of ``sum(abs(risk))``.

    ``dv01`` and ``dv01_fallback`` are mappings from ``unit_key`` to a
    magnitude; the sign is irrelevant to a share and is taken out with ``abs``.
    ``n_fallback_dv01`` reports how much of each row's size came from the proxy,
    because a reason whose share rests entirely on a model is a weaker claim
    than one measured off repriced risk.
    """
    cols = ["reason", "n_units", "dv01", "dv01_share", "n_fallback_dv01"]
    prov = pd.DataFrame(prov)
    if prov.empty:
        return pd.DataFrame(columns=cols)

    dup = prov["unit_key"].duplicated()
    if dup.any():
        offenders = sorted(set(prov.loc[dup, "unit_key"].astype(str)))[:5]
        raise ValueError(
            f"{int(dup.sum())} unit(s) appear more than one time in the coverage "
            f"population, e.g. {offenders}; every unit is in the ladder or "
            "carries exactly one reason, never both and never two"
        )

    dv01 = pd.Series(dv01, dtype="float64")
    fallback = (pd.Series(dtype="float64") if dv01_fallback is None
                else pd.Series(dv01_fallback, dtype="float64"))

    keys = prov["unit_key"]
    primary = keys.map(dv01).astype("float64").abs()
    backup = keys.map(fallback).astype("float64").abs()
    used_fallback = ~primary.notna() & backup.notna()
    size = primary.where(primary.notna(), backup)

    missing = size.isna()
    if missing.any():
        offenders = sorted(set(keys[missing].astype(str)))[:5]
        raise ValueError(
            f"{int(missing.sum())} unit(s) have no DV01 and no fallback, e.g. "
            f"{offenders}; a sizeless unit contributes zero to every share "
            "while the shares still sum to 1, so the gap would be invisible"
        )

    total = float(size.sum())
    if total <= 0.0:
        raise ValueError("total DV01 over the coverage population is zero; "
                         "a share table over no size reports nothing")

    work = pd.DataFrame({
        "reason": prov["failure_reason"].where(prov["failure_reason"].notna(), IN_LADDER),
        "dv01": size.to_numpy(),
        "from_fallback": used_fallback.to_numpy(),
    })
    out = (work.groupby("reason", dropna=False)
               .agg(n_units=("dv01", "size"), dv01=("dv01", "sum"),
                    n_fallback_dv01=("from_fallback", "sum"))
               .reset_index())
    out["dv01_share"] = out["dv01"] / total
    out["n_fallback_dv01"] = out["n_fallback_dv01"].astype(int)
    out = out.sort_values("dv01_share", ascending=False).reset_index(drop=True)

    # the table's whole claim, asserted rather than assumed
    if abs(float(out["dv01_share"].sum()) - 1.0) > 1e-9:
        raise AssertionError(
            f"coverage shares sum to {float(out['dv01_share'].sum())!r}, not 1"
        )
    return out[cols]


__all__ = [
    "IN_LADDER", "VINTAGE_SOURCES", "annuity_dv01_proxy",
    "annuity_dv01_proxy_from_dates", "build", "code_vintage",
    "coverage_table", "to_frame", "vintage_components",
]
