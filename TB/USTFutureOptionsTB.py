import datetime
import json
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_for_request, resolve_query
from Query.USTFutureOptions.USTFutureOptionQuery import USTFutureOptionQuery
from TB.BaseTimeseriesTB import BaseTimeseriesTB
from TB.utils import DateLike, _canonicalize_value

if TYPE_CHECKING:
    from MDP.USTFutures.USTFutureOptionMDP import USTFutureOptionMDP


class USTFutureOptionsTB(BaseTimeseriesTB):
    _DEFAULT_PRICING_MESSAGE = "PRICING UST FUTURE OPTIONS."
    _SUPPORTED_ENDPOINT = "option_snapshot"

    def __init__(
        self,
        mdp: "USTFutureOptionMDP",
        *,
        date_col: str = "Date",
        show_tqdm: bool = True,
        timeseries_window_days: int = 62,
    ):
        super().__init__(mdp=mdp, date_col=date_col, show_tqdm=show_tqdm)
        # For ranges longer than this, fetches are chunked into rolling windows.
        self._timeseries_window_days = max(1, int(timeseries_window_days))

    def _flatten_queries(
        self,
        queries: List[Union[BaseQuery, List[BaseQuery]]],
    ) -> List[USTFutureOptionQuery]:
        flat = super()._flatten_queries(queries)
        bad = [q for q in flat if not isinstance(q, USTFutureOptionQuery)]
        if bad:
            raise TypeError(
                f"USTFutureOptionsTB requires USTFutureOptionQuery inputs, got: {type(bad[0]).__name__}"
            )
        return flat

    @staticmethod
    def _ref_date(ref_point: DateLike) -> datetime.date:
        if isinstance(ref_point, datetime.datetime):
            return ref_point.date()
        return ref_point

    @staticmethod
    def _dedupe_symbols(symbols: List[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for s in symbols:
            tok = str(s).strip()
            if not tok:
                continue
            if tok in seen:
                continue
            seen.add(tok)
            out.append(tok)
        return out

    def _extract_query_symbols(self, q: USTFutureOptionQuery, now: datetime.datetime) -> List[str]:
        req = q.build_mdp_request(now)
        raw = req.get("symbols") or []
        if isinstance(raw, (list, tuple)):
            return self._dedupe_symbols([str(x) for x in raw])
        if raw:
            return [str(raw)]
        return []

    def _query_group_spec(
        self,
        q: USTFutureOptionQuery,
        now: datetime.datetime,
    ) -> Optional[Tuple[str, Dict[str, Any], str, str, Any, List[str]]]:
        req = dict(q.build_mdp_request(now))
        endpoint = str(req.get("endpoint", self._SUPPORTED_ENDPOINT)).strip().lower()
        if endpoint != self._SUPPORTED_ENDPOINT:
            return None

        symbols = self._extract_query_symbols(q, now)
        time_key = str(getattr(q, "mdp_time_key", "timestamp"))
        market_request = dict(getattr(q, "market_request", {}) or {})
        if time_key not in market_request:
            time_mode = "dynamic_date"
            fixed_time = None
        else:
            raw = market_request.get(time_key)
            if raw == "now":
                time_mode = "dynamic_now"
                fixed_time = None
            else:
                time_mode = "fixed"
                fixed_time = raw

        base_req = dict(req)
        for k in ("symbols", "show_tqdm", "force_refresh", "window_start", "window_end", time_key):
            base_req.pop(k, None)
        base_req["endpoint"] = endpoint

        payload = {
            "request": _canonicalize_value(base_req),
            "time_key": time_key,
            "time_mode": time_mode,
            "fixed_time": _canonicalize_value(fixed_time),
        }
        group_key = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return group_key, base_req, time_key, time_mode, fixed_time, symbols

    def _window_map(
        self,
        reference_points: List[DateLike],
    ) -> Tuple[Dict[DateLike, Tuple[datetime.date, datetime.date]], "OrderedDict[Tuple[datetime.date, datetime.date], List[DateLike]]"]:
        out_by_ref: Dict[DateLike, Tuple[datetime.date, datetime.date]] = {}
        by_window: "OrderedDict[Tuple[datetime.date, datetime.date], List[DateLike]]" = OrderedDict()
        if not reference_points:
            return out_by_ref, by_window

        ref_dates = [self._ref_date(rp) for rp in reference_points]
        global_start = min(ref_dates)
        global_end = max(ref_dates)
        span_days = max(1, (global_end - global_start).days + 1)
        chunk_days = min(int(self._timeseries_window_days), span_days)

        for rp, d in zip(reference_points, ref_dates):
            offset = (d - global_start).days
            chunk_idx = offset // chunk_days
            window_start = global_start + datetime.timedelta(days=chunk_idx * chunk_days)
            window_end = min(window_start + datetime.timedelta(days=chunk_days - 1), global_end)
            w = (window_start, window_end)
            out_by_ref[rp] = w
            by_window.setdefault(w, []).append(rp)

        return out_by_ref, by_window

    def _bulk_fetch(
        self,
        *,
        reference_points: List[DateLike],
        queries: List[USTFutureOptionQuery],
        n_jobs: Optional[int],
        ignore_cache: Optional[bool],
    ) -> Any:
        _ = n_jobs
        if not reference_points or not queries:
            return {}

        anchor_now = self._to_now(reference_points[0])
        groups: Dict[str, Dict[str, Any]] = {}
        query_group_key: Dict[int, str] = {}

        for q in queries:
            spec = self._query_group_spec(q, anchor_now)
            if spec is None:
                continue
            group_key, base_req, time_key, time_mode, fixed_time, symbols = spec
            query_group_key[id(q)] = group_key
            grp = groups.get(group_key)
            if grp is None:
                grp = {
                    "base_req": base_req,
                    "time_key": time_key,
                    "time_mode": time_mode,
                    "fixed_time": fixed_time,
                    "symbols": [],
                }
                groups[group_key] = grp
            grp["symbols"].extend(symbols)

        if not groups:
            return {}

        for grp in groups.values():
            grp["symbols"] = self._dedupe_symbols(grp["symbols"])

        window_by_ref, refs_by_window = self._window_map(reference_points)
        result_by_ref_group: Dict[Tuple[DateLike, str], Any] = {}

        for group_key, grp in groups.items():
            symbols = list(grp["symbols"])
            if not symbols:
                continue

            base_req = dict(grp["base_req"])
            time_key = str(grp["time_key"])
            time_mode = str(grp["time_mode"])
            fixed_time = grp["fixed_time"]

            for (window_start, window_end), refs in refs_by_window.items():
                for rp in refs:
                    now = self._to_now(rp)
                    req = dict(base_req)
                    req["symbols"] = symbols
                    if time_mode == "dynamic_now":
                        req[time_key] = now
                    elif time_mode == "fixed":
                        req[time_key] = fixed_time
                    else:
                        req[time_key] = now.date()
                    req["window_start"] = window_start
                    req["window_end"] = window_end
                    req["bulk_timeseries"] = True
                    # req["show_tqdm"] = self._show_tqdm
                    req["show_tqdm"] = False
                    req["use_ql_calculator"] = True 
                    if ignore_cache:
                        req["force_refresh"] = True
                    result_by_ref_group[(rp, group_key)] = self.mdp.get_pricer(req)

        return {
            "result_by_ref_group": result_by_ref_group,
            "query_group_key": query_group_key,
            "window_by_ref": window_by_ref,
        }

    def _price_one(
        self,
        q: USTFutureOptionQuery,
        *,
        ref_point: DateLike,
        now: datetime.datetime,
        bulk_data: Any,
        n_jobs: Optional[int],
        ignore_cache: Optional[bool],
    ) -> Optional[Tuple[USTFutureOptionQuery, float]]:
        if isinstance(bulk_data, dict):
            query_group_key = bulk_data.get("query_group_key") or {}
            result_by_ref_group = bulk_data.get("result_by_ref_group") or {}
            group_key = query_group_key.get(id(q))
            if group_key is not None:
                pricer = result_by_ref_group.get((ref_point, group_key))
                if pricer is not None:
                    try:
                        q_resolved = resolve_for_request(q, timestamp=now, pricer_or_curve=pricer)
                        q_eff = resolve_query(q_resolved, timestamp=now, pricer_or_curve=pricer)
                        package, risk_weights = q_eff.resolve_package(
                            pricer_or_curve=pricer,
                            is_for_timeseries=True,
                        )
                        vmap = q_eff.build_value_map(
                            pricer_or_curve=pricer,
                            package=package,
                            risk_weights=risk_weights,
                        )
                        value_key = getattr(q_eff, "value", None) or q_eff.default_mtm_value_id()
                        value_kwargs = getattr(q_eff, "value_kwargs", {}) or {}
                        value = vmap.apply(value=value_key, **value_kwargs)
                        return q_eff, float(value)
                    except Exception:
                        # Fall through to base path for behavioral parity.
                        pass

        return super()._price_one(
            q,
            ref_point=ref_point,
            now=now,
            bulk_data=bulk_data,
            n_jobs=n_jobs,
            ignore_cache=ignore_cache,
        )

