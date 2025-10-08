from __future__ import annotations

import datetime
import re
from dataclasses import replace
from typing import Any, Dict, List, Tuple

from MDP.FixedRateBonds.FixedRateBondsMDP import _alias_to_cusip
from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps._IRSwapGenericObject import _IRSwapGenericObject
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure, IRSwapStructureFunctionMap
from Query.IRSwaps.IRSwapValue import IRSwapValueFunctionMap

_ALIAS_PATTERNS = (
    re.compile(r"^CT(\d+)$", re.IGNORECASE),  # on-the-run N-year
    re.compile(r"^(O{1,3})(\d+)$", re.IGNORECASE),  # O, OO, OOO + tenor
    re.compile(r"^Ox(\d+?)(\d+)$", re.IGNORECASE),  # rank x tenor
    re.compile(r"^\d{2}\d{2}(?:/\d{1,2})?$", re.IGNORECASE),  # MMYY[/OI]
)
_CUSIP_RE = re.compile(r"^[0-9A-Z]{9}$", re.IGNORECASE)


def _looks_like_alias_or_cusip(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if _CUSIP_RE.match(s):
        return True
    return any(p.match(s) for p in _ALIAS_PATTERNS)


def _resolve_cusip_or_alias(
    token: str,
    as_of: datetime.date,
) -> Tuple[str, datetime.date]:
    """
    Return (cusip, maturity_date) for:
      - CUSIP (9-char): verify & read its maturity
      - Alias: CTN / O... / Ox.. / MMYY[/OI]
    """
    ref = update_reference_data(source="fiscaldata", force_refresh=False)
    # Keep currently outstanding around 'as_of'
    ref = ref[(ref["issue_date"] <= as_of) & (ref["maturity_date"] >= as_of)].copy()

    # Rank newest by OI bucket to support CT / O / OO / OOO selection
    ref["rank"] = ref.groupby("oi")["issue_date"].rank(method="first", ascending=False).astype(int) - 1

    tok = token.strip().upper()

    # Direct CUSIP?
    if _CUSIP_RE.match(tok):
        row = ref[ref["cusip"].str.upper() == tok]
        if row.empty:
            raise KeyError(f"CUSIP '{tok}' not found in reference data as of {as_of.isoformat()}")
        r = row.iloc[0]
        return r["cusip"], r["maturity_date"]

    # CT / O / Ox?
    m_ct = re.match(r"^CT(\d+)$", tok, re.IGNORECASE)
    m_o = re.match(r"^(O{1,3})(\d+)$", tok, re.IGNORECASE)
    m_ox = re.match(r"^Ox(\d+?)(\d+)$", tok, re.IGNORECASE)

    if m_ct or m_o or m_ox:
        if m_ct:
            rank, tenor = 0, int(m_ct.group(1))
        elif m_o:
            rank, tenor = len(m_o.group(1)), int(m_o.group(2))
        else:
            rank, tenor = int(m_ox.group(1)), int(m_ox.group(2))

        oi_str = f"{tenor}-Year"
        hit = ref[(ref["oi"] == oi_str) & (ref["rank"] == rank)]
        if hit.empty:
            raise KeyError(f"Could not resolve '{tok}' to an on-the-run/off-the-run UST at tenor {tenor} (rank {rank})")
        r = hit.iloc[0]
        return r["cusip"], r["maturity_date"]

    # MMYY[/OI] family -> use your existing helper
    resolved = _alias_to_cusip(tok, ref)
    if not resolved:
        raise KeyError(f"Alias '{tok}' did not resolve to a CUSIP")
    row = ref[ref["cusip"].str.upper() == resolved.upper()]
    if row.empty:
        # If _alias_to_cusip found an historical CUSIP that is not active 'as_of', fall back to any ref row
        row = update_reference_data(source="fiscaldata", force_refresh=False)
        row = row[row["cusip"].str.upper() == resolved.upper()]
        if row.empty:
            raise KeyError(f"Resolved alias '{tok}' -> '{resolved}', but CUSIP not found in reference data table")
    r = row.iloc[0]
    return r["cusip"], r["maturity_date"]


def _inject_mms_leg(skw: Dict[str, Any], leg_prefix: str, token: str, as_of: datetime.date, pricer_or_curve: _IRSwapGenericCurve) -> None:
    """
    Replace <leg_prefix>_tenor with explicit effective/maturity dates for a matched-maturity swap.
      - effective_date = '2D' (SOFR spot)
      - maturity_date = UST maturity from token (alias/CUSIP)
    
    TODO
     - support forwards e.g. Z25x0832/7 -> TYZ5 invoice swap leg rate
    """
    _, mat = _resolve_cusip_or_alias(token, as_of)
    skw.pop(f"{leg_prefix}_tenor", None)
    skw["tenor"] = None
    if leg_prefix == "":
        skw[f"effective_date"] = pricer_or_curve.calendar_advance(as_of, "2D")
        skw[f"maturity_date"] = mat
    else:
        skw[f"{leg_prefix}_effective_date"] = pricer_or_curve.calendar_advance(as_of, "2D")
        skw[f"{leg_prefix}_maturity_date"] = mat


class IRSProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        # For IRS you’ve been passing a curve wrapper here (QL/RL curve impl works)
        return IRSwapStructureFunctionMap(curve=pricer_or_curve)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_IRSwapGenericObject],
        risk_weights: List[float],
    ) -> Any:
        return IRSwapValueFunctionMap(curve=pricer_or_curve, package=package, risk_weights=risk_weights)

    def edit_query(self, *, q: IRSwapQuery, pricer_or_curve: _IRSwapGenericCurve):
        if q.curve not in ["USD-SOFR-1D", "USD-FEDFUNDS", "USD-OIS"]:
            return q
        if q.tenor is None:
            return q

        mr = dict(q.market_request or {})
        ts = mr.get(q.mdp_time_key)
        if isinstance(ts, datetime.datetime):
            as_of = ts.date()
        elif isinstance(ts, datetime.date):
            as_of = ts
        else:
            as_of = datetime.date.today()

        skw = dict(q.structure_kwargs or {})

        if q.structure == IRSwapStructure.OUTRIGHT:
            # Outright MMS if tenor is an alias/CUSIP token
            if isinstance(q.tenor, str) and _looks_like_alias_or_cusip(q.tenor):
                _inject_mms_leg(skw, "", q.tenor, as_of, pricer_or_curve)
                return replace(q, tenor=None, effective_date=None, maturity_date=None, is_mms=True, structure_kwargs=skw)

            # Explicit MMS via skw["mms"] / q.is_mms
            token = skw.get("mms") or skw.get("mms_token")
            if q.is_mms and token:
                _inject_mms_leg(skw, "", str(token), as_of, pricer_or_curve)
                return replace(q, tenor=None, effective_date=None, maturity_date=None, is_mms=True, structure_kwargs=skw)

            return q  # plain outright

        if q.structure == IRSwapStructure.CURVE:
            ft = skw.get("front_tenor")
            bt = skw.get("back_tenor")
            if isinstance(ft, str) and _looks_like_alias_or_cusip(ft):
                _inject_mms_leg(skw, "front", ft, as_of, pricer_or_curve)
            if isinstance(bt, str) and _looks_like_alias_or_cusip(bt):
                _inject_mms_leg(skw, "back", bt, as_of, pricer_or_curve)
            return replace(q, structure_kwargs=skw)

        if q.structure == IRSwapStructure.FLY:
            ft = skw.get("front_tenor")
            bt = skw.get("belly_tenor")
            kt = skw.get("back_tenor")
            if isinstance(ft, str) and _looks_like_alias_or_cusip(ft):
                _inject_mms_leg(skw, "front", ft, as_of, pricer_or_curve)
            if isinstance(bt, str) and _looks_like_alias_or_cusip(bt):
                _inject_mms_leg(skw, "belly", bt, as_of, pricer_or_curve)
            if isinstance(kt, str) and _looks_like_alias_or_cusip(kt):
                _inject_mms_leg(skw, "back", kt, as_of, pricer_or_curve)
            return replace(q, structure_kwargs=skw)

        return q


# Register on import
register_product("IRS", IRSProductAdapter)
