import argparse
import datetime
import json
import os
from typing import Any, Dict

import QuantLib as ql

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import get_nodes_dict, get_fixings_dict
from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date, ql_date_to_pydate


def _parse_timestamp(value: str | None):
    if value is None:
        return datetime.date.today()
    raw = value.strip()
    if not raw:
        return datetime.date.today()
    if raw.lower() == "live":
        return "live"
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        # Accept full datetime strings, but coerce to date
        try:
            parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid timestamp '{value}'. Expected YYYY-MM-DD or 'live'.") from exc
        return parsed.date()


def _adjust_to_business_day(curve_name: str, timestamp: datetime.date | str):
    if timestamp == "live":
        probe = datetime.date.today()
    else:
        probe = timestamp

    if not isinstance(probe, datetime.date):
        return timestamp

    calendar = QUANTLIB_CURVE_DEFINITIONS[curve_name]["Calendar"]
    ql_date = datetime_to_ql_date(probe)

    if not calendar.isHoliday(ql_date):
        return timestamp

    while calendar.isHoliday(ql_date):
        ql_date = calendar.advance(ql_date, ql.Period(-1, ql.Days))

    adjusted = ql_date_to_pydate(ql_date)
    return adjusted


def _to_iso(val: Any):
    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.isoformat()
    return val


def _jsonify_meta(meta: Any) -> Any:
    if meta is None:
        return None
    if isinstance(meta, dict):
        return {k: _jsonify_meta(v) for k, v in meta.items()}
    return _to_iso(meta)


def _normalize_nodes(nodes: Dict[Any, Any]):
    out = []
    for k, v in nodes.items():
        if isinstance(k, (datetime.datetime, datetime.date)):
            key = k.isoformat()
        else:
            key = str(k)
        try:
            df = float(v)
        except Exception:
            continue
        out.append({"date": key, "df": df})
    out.sort(key=lambda x: x["date"])
    return out


def _normalize_fixings(fixings: Dict[Any, Any]):
    out = []
    for k, v in fixings.items():
        if isinstance(k, (datetime.datetime, datetime.date)):
            key = k.isoformat()
        else:
            key = str(k)
        try:
            rate = float(v)
        except Exception:
            continue
        out.append({"date": key, "rate": rate})
    out.sort(key=lambda x: x["date"])
    return out


def main():
    parser = argparse.ArgumentParser(description="Fetch SOFR discount curve via IRSwapsMDP.")
    parser.add_argument("--source", default="ERIS_EOD_LIVE-QL_BASIC")
    parser.add_argument("--curve-name", default="USD-SOFR-1D")
    parser.add_argument("--timestamp", default=None)
    args = parser.parse_args()

    requested_timestamp = _parse_timestamp(args.timestamp)
    adjusted_timestamp = _adjust_to_business_day(args.curve_name, requested_timestamp)

    mdp = IRSwapsMDP(source=args.source)
    pricer = mdp.get_pricer({"curve_name": args.curve_name, "timestamp": adjusted_timestamp})

    nodes_dict = None
    if hasattr(pricer, "nodes"):
        try:
            nodes_dict = pricer.nodes()
        except Exception:
            nodes_dict = None
    if nodes_dict is None and hasattr(pricer, "handle"):
        try:
            ql_curve = pricer.handle().currentLink()
            nodes_dict = get_nodes_dict(ql_curve, to_iso=True)
        except Exception:
            nodes_dict = None

    if nodes_dict is None:
        raise RuntimeError("Unable to extract curve nodes from pricer.")

    fixings_dict = None
    try:
        idx = pricer.index()
        if hasattr(idx, "to_dict"):
            fixings_dict = idx.to_dict()
        else:
            fixings_dict = get_fixings_dict(idx)
    except Exception:
        fixings_dict = None

    payload = {
        "curve_name": args.curve_name,
        "source": args.source,
        "timestamp": _to_iso(adjusted_timestamp),
        "reference_date": _to_iso(pricer.reference_date()),
        "meta": {
            "requested_timestamp": _to_iso(requested_timestamp),
            "adjusted_timestamp": _to_iso(adjusted_timestamp),
            "curve_meta": _jsonify_meta(pricer.meta()),
        },
        "nodes": _normalize_nodes(nodes_dict),
        "fixings": _normalize_fixings(fixings_dict) if fixings_dict else [],
    }

    print(json.dumps(payload, ensure_ascii=True))


if __name__ == "__main__":
    main()
