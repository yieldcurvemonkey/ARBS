import datetime
import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union
from pathlib import Path

import pandas as pd
import pytz
import rateslib as rl
from pandas.tseries.offsets import DateOffset
from itertools import islice

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import RLSTIRFuturePricer

_STIR_ROOT_CODE_RE = re.compile(r"^(SR1|SER|SL|SR3|SFR|SQ|ZQ|FF|RA|EB)([FGHJKMNQUVXZ]\d{2})$", re.IGNORECASE)

try:
    from platformdirs import user_cache_dir as _user_cache_dir
except Exception:
    _user_cache_dir = None


def _flatten_pricers(pricers: Dict[str, List["RLSTIRFuturePricer"]]) -> List["RLSTIRFuturePricer"]:
    # Each key maps to a list (often length 1). Keep all, preserve order.
    out: List["RLSTIRFuturePricer"] = []
    for lst in pricers.values():
        if lst:
            out.extend(lst)
    return out


def _sort_pricers_for_solver(
    pricers: Dict[str, List["RLSTIRFuturePricer"]],
) -> List["RLSTIRFuturePricer"]:
    """
    Deterministic ordering for solver:
      1) by effective date
      2) then by maturity date
      3) then by rl_stirf_id (or symbol) as a stable tie-breaker
    """
    flat = _flatten_pricers(pricers)
    return sorted(
        flat,
        key=lambda p: (
            getattr(p, "_effective_date", None),
            getattr(p, "_maturity_date", None),
            getattr(p, "_rl_stirf_id", None) or getattr(p, "_meta_data", {}).get("symbol", ""),
        ),
    )


def _sort_nodes(nodes: Dict) -> Dict:
    # nodes keys are rateslib dt (datetime-like); dict insertion order matters
    return dict(sorted(nodes.items(), key=lambda kv: kv[0]))


def _as_node_ts(d: datetime.date, *, base_ts: pd.Timestamp) -> pd.Timestamp:
    """
    Create a timezone-aware pd.Timestamp for date `d` using the SAME time-of-day + tz as `base_ts`.
    """
    tod = base_ts.to_pydatetime().timetz()
    naive = rl.dt(d.year, d.month, d.day, tod.hour, tod.minute, tod.second, tod.microsecond)
    return naive
    # ts = pd.Timestamp(naive)
    # # localize to base tz (works for pytz/dateutil tz and tz strings)
    # if ts.tzinfo is None:
    #     return ts.tz_localize(base_ts.tz)
    # return ts.tz_convert(base_ts.tz)


def _build_stirf_nodes(
    *,
    timestamp: datetime.datetime,
    pricers: Dict[str, List["RLSTIRFuturePricer"]],
    central_bank_dates: Dict[str, Dict[str, Tuple[datetime.date, datetime.date]]],
    reference_key: str,
    max_tenor_from_timestamp_months: int,
) -> Dict[pd.Timestamp, float]:
    assert isinstance(timestamp, datetime.datetime)
    assert timestamp.tzinfo is not None and timestamp.tzinfo.utcoffset(timestamp) is not None

    base_ts = pd.Timestamp(timestamp)
    base_date = timestamp.date()
    horizon_date = (base_ts + DateOffset(months=max_tenor_from_timestamp_months)).date()

    # --- central bank end dates (period boundaries) ---
    cb_map = central_bank_dates.get(reference_key, {})
    all_cb_ends: List[datetime.date] = sorted({end for (_start, end) in cb_map.values()})

    cb_extends_beyond_horizon = bool(all_cb_ends) and (max(all_cb_ends) > horizon_date)

    # take CB ends in (base_date, horizon_date]
    cb_ends_in_range = [d for d in all_cb_ends if (d > base_date and d <= horizon_date)]

    # if horizon is before the next CB end (rare, but handle), include the next end after base_date
    if not cb_ends_in_range:
        next_end = min((d for d in all_cb_ends if d > base_date), default=None)
        if next_end is not None:
            cb_ends_in_range = [next_end]

    node_dates: List[datetime.date] = list(cb_ends_in_range)
    last_cb_date: Optional[datetime.date] = max(node_dates) if node_dates else None

    # --- extend with pricer maturities only if CB schedule does NOT cover the horizon ---
    if (not cb_extends_beyond_horizon) and pricers:
        flat = _flatten_pricers(pricers)
        pricer_mats = sorted({p._maturity_date for p in flat if getattr(p, "_maturity_date", None) is not None})

        cutoff = last_cb_date or base_date
        extra = [d for d in pricer_mats if (d > cutoff and d <= horizon_date)]
        node_dates.extend(extra)

    # de-dupe + sort
    node_dates = sorted(set(node_dates))

    # build nodes dict (values are placeholders / initial guesses)
    nodes: Dict[pd.Timestamp, float] = {_as_node_ts(base_ts, base_ts=base_ts): 1.0}
    for d in node_dates:
        nodes[_as_node_ts(d, base_ts=base_ts)] = 1.0

    return nodes


def build_rl_stirf_turn_flies(
    turn_nodes: List[Union[datetime.date, datetime.datetime]], curve_id: str, spec: str, one_step: Optional[bool] = False
) -> Dict[str, rl.Fly]:
    args = {"termination": "1d", "spec": spec, "curves": curve_id}

    rl_irs = [rl.IRS(effective=node, **args) for node in turn_nodes]
    flies = {}
    if len(rl_irs) < 3:
        return flies

    if one_step:
        for i in range(0, len(rl_irs) - 2):
            fly = rl.Fly(rl_irs[i], rl_irs[i + 1], rl_irs[i + 2])
            flies[f"{i}/{i+1}/{i+2}"] = fly
    else:
        for i in range(3, len(rl_irs) - 2, 2):
            fly = rl.Fly(rl_irs[i], rl_irs[i + 1], rl_irs[i + 2])
            flies[f"{i}/{i+1}/{i+2}"] = fly

    return flies


class BARCHART_STIRF_CURVE:
    _CURVE_CACHE_MAX_ITEMS = 4096
    _CURVE_CACHE_SCHEMA = 1
    _CURVE_STATE: Dict[str, Any] = {}

    def __init__(self, curve_cache_dir: Optional[Union[str, Path]] = None):
        self.stirf_mdp = STIRFutureMDP(source="BARCHART_TOS_LIVE_STIRF-RL")
        self.stirf_mdp_schwab_app = STIRFutureMDP(source="SCHWAB_APP_STIRF-RL")
        self.stirf_mdp_barchart = STIRFutureMDP(source="BARCHART_STIRF-RL")
        self._curve_cache_dir = self._resolve_curve_cache_dir(base_cache_dir=curve_cache_dir)
        if not BARCHART_STIRF_CURVE._CURVE_STATE:
            BARCHART_STIRF_CURVE._CURVE_STATE = {
                "curve_cache": {},
                "lock": threading.RLock(),
            }

        self._STIRF_CURVE_CONFIGS = {
            "USD-SOFR-1D-Q8": {
                "fetch_pricers_func": self.stirf_mdp.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp.get_bulk_data,
                "instruments": [
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                ],
                "reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "usd_irs_lt_2y",
            },
            "USD-SOFR-1D-Q12x3": {
                "fetch_pricers_func": self.stirf_mdp.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp.get_bulk_data,
                "instruments": [
                    "SERCM1",
                    "SERCM2",
                    "SERCM3",
                    "SERCM4",
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                ],
                "reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "usd_irs_lt_2y",
            },
            "USD-OIS-Q8xM12": {
                "fetch_pricers_func": self.stirf_mdp_schwab_app.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_schwab_app.get_bulk_data,
                "instruments": [
                    "SERCM1",
                    "SERCM2",
                    "SERCM3",
                    "SERCM4",
                    "SERCM5",
                    "SERCM6",
                    "SERCM7",
                    "SERCM8",
                    "SERCM9",
                    "SERCM10",
                    "SERCM11",
                    "SERCM12",
                    "FFCM1",
                    "FFCM2",
                    "FFCM3",
                    "FFCM4",
                    "FFCM5",
                    "FFCM6",
                    "FFCM7",
                    "FFCM8",
                    "FFCM9",
                    "FFCM10",
                    "FFCM11",
                    "FFCM12",
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    # "SFRCM9",
                    # "SFRCM10",
                    # "SFRCM11",
                    # "SFRCM12",
                ],
                "reference_key": "USD-OIS",
                "node_reference_key": "USD-FEDFUNDS",
                "sofr_reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "usd_irs_lt_2y",
                "serff_skew": True,
            },
            "EUR-ESTR-LONDON-Q12": {
                "fetch_pricers_func": self.stirf_mdp_barchart.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_barchart.get_bulk_data,
                "instruments": [
                    "RACM1",
                    "RACM2",
                    "RACM3",
                    "RACM4",
                    "RACM5",
                    "RACM6",
                    "RACM7",
                    "RACM8",
                    "RACM9",
                    "RACM10",
                    "RACM11",
                    "RACM12",
                ],
                "reference_key": "EUR-ESTR",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "eur_irs",
            },
            "EUR-ESTR-NYC-Q12": {
                "fetch_pricers_func": self.stirf_mdp_barchart.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_barchart.get_bulk_data,
                "instruments": [
                    "EBCM1",
                    "EBCM2",
                    "EBCM3",
                    "EBCM4",
                    "EBCM5",
                    "EBCM6",
                    "EBCM7",
                    "EBCM8",
                    "EBCM9",
                    "EBCM10",
                    "EBCM11",
                    "EBCM12",
                ],
                "reference_key": "EUR-ESTR",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "eur_irs",
            },
        }

    @staticmethod
    def _resolve_curve_cache_dir(base_cache_dir: Optional[Union[str, Path]] = None) -> Path:
        if base_cache_dir:
            base = Path(base_cache_dir)
        elif os.getenv("ARBS_CACHE_DIR"):
            base = Path(os.getenv("ARBS_CACHE_DIR")) / "IRSwaps" / "BARCHART_STIRF"
        elif _user_cache_dir:
            base = Path(_user_cache_dir(appname="ARBS/MDP/IRSwaps/BARCHART_STIRF"))
        else:
            base = Path.home() / ".cache" / "arbs" / "MDP" / "IRSwaps" / "BARCHART_STIRF"

        cache_dir = base / "curve_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @staticmethod
    def _curve_cfg_hash(cfg: Dict[str, Any]) -> str:
        cfg_blob = "|".join(
            [
                str(cfg.get("reference_key", "")),
                str(cfg.get("node_reference_key", cfg.get("reference_key", ""))),
                str(cfg.get("sofr_reference_key", "")),
                str(cfg.get("rl_irs_spec", "")),
                str(int(bool(cfg.get("serff_skew", False)))),
                str(cfg.get("max_tenor_from_timestamp_months", "")),
                ",".join(str(x) for x in cfg.get("instruments", [])),
            ]
        )
        return hashlib.sha1(cfg_blob.encode()).hexdigest()[:16]

    @classmethod
    def _curve_cache_key(cls, curve_name: str, timestamp: datetime.datetime, cfg: Dict[str, Any]) -> str:
        ts_utc = timestamp.astimezone(pytz.utc).replace(microsecond=0)
        ts_str = ts_utc.strftime("%Y%m%dT%H%M%SZ")
        cfg_hash = cls._curve_cfg_hash(cfg)
        return re.sub(r"[^A-Za-z0-9_.-]", "_", f"v{cls._CURVE_CACHE_SCHEMA}_{curve_name}_{ts_str}_{cfg_hash}")

    def _curve_cache_path(self, curve_name: str, timestamp: datetime.datetime, cfg: Dict[str, Any]) -> Path:
        return self._curve_cache_dir / f"{self._curve_cache_key(curve_name, timestamp, cfg)}.json"

    def _curve_cache_get(self, curve_name: str, timestamp: datetime.datetime, cfg: Dict[str, Any]) -> Optional[rl.Curve]:
        key = self._curve_cache_key(curve_name, timestamp, cfg)
        S = BARCHART_STIRF_CURVE._CURVE_STATE
        with S["lock"]:
            curve_cache = S["curve_cache"]
            cached = curve_cache.get(key)
            if cached is not None:
                return cached

        cache_file = self._curve_cache_path(curve_name, timestamp, cfg)
        if not cache_file.exists():
            return None

        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            curve_json = payload["curve_json"]
            curve = rl.from_json(curve_json)
            with S["lock"]:
                curve_cache = S["curve_cache"]
                curve_cache[key] = curve
                while len(curve_cache) > self._CURVE_CACHE_MAX_ITEMS:
                    curve_cache.pop(next(iter(curve_cache)))
            return curve
        except Exception:
            return None

    def _curve_cache_put(self, curve_name: str, timestamp: datetime.datetime, cfg: Dict[str, Any], curve: rl.Curve) -> None:
        key = self._curve_cache_key(curve_name, timestamp, cfg)
        S = BARCHART_STIRF_CURVE._CURVE_STATE

        with S["lock"]:
            curve_cache = S["curve_cache"]
            curve_cache[key] = curve
            while len(curve_cache) > self._CURVE_CACHE_MAX_ITEMS:
                curve_cache.pop(next(iter(curve_cache)))

            cache_file = self._curve_cache_path(curve_name, timestamp, cfg)
            ts_utc = timestamp.astimezone(pytz.utc).replace(microsecond=0)
            payload = {
                "schema": self._CURVE_CACHE_SCHEMA,
                "curve_name": curve_name,
                "timestamp_utc": ts_utc.isoformat(),
                "curve_json": curve.to_json(),
            }
            tmp_file = cache_file.with_suffix(f"{cache_file.suffix}.tmp-{threading.get_ident()}")
            try:
                tmp_file.write_text(json.dumps(payload), encoding="utf-8")
                tmp_file.replace(cache_file)
            finally:
                if tmp_file.exists():
                    try:
                        tmp_file.unlink()
                    except Exception:
                        pass

    @staticmethod
    def _pricer_symbol(pricer: "RLSTIRFuturePricer") -> str:
        sym = getattr(pricer, "_rl_stirf_id", None) or getattr(pricer, "_meta_data", {}).get("symbol", "")
        return str(sym).strip().upper().replace("/", "")

    @classmethod
    def _pricer_root_and_code(cls, pricer: "RLSTIRFuturePricer") -> Optional[Tuple[str, str]]:
        m = _STIR_ROOT_CODE_RE.match(cls._pricer_symbol(pricer))
        if not m:
            return None

        root, code = m.group(1).upper(), m.group(2).upper()
        root = {"SER": "SR1", "SL": "SR1", "SFR": "SR3", "SQ": "SR3", "FF": "ZQ"}.get(root, root)
        return root, code

    @classmethod
    def _build_pricable_for_curve(cls, pricer: "RLSTIRFuturePricer", curve_key: str) -> rl.STIRFuture:
        root_and_code = cls._pricer_root_and_code(pricer)
        is_ser = bool(root_and_code and root_and_code[0] == "SR1")
        if root_and_code and root_and_code[0] in {"RA", "EB"}:
            spec = "eur_stir"
        else:
            spec_key = "ReferenceRate3" if is_ser else "ReferenceRate2"
            spec = RATESLIB_CURVE_DEFINITIONS[curve_key].get(spec_key, RATESLIB_CURVE_DEFINITIONS[curve_key]["ReferenceRate"])

        meta = getattr(pricer, "_meta_data", {}) or {}
        kwargs = {
            "effective": rl.dt(pricer._effective_date.year, pricer._effective_date.month, pricer._effective_date.day),
            "termination": rl.dt(pricer._maturity_date.year, pricer._maturity_date.month, pricer._maturity_date.day),
            "spec": spec,
            "price": float(pricer._price),
            "contracts": int(getattr(pricer, "_contracts", 1) or 1),
            "curves": curve_key,
        }
        if is_ser and meta.get("fixings") is not None:
            kwargs["leg2_fixings"] = meta["fixings"]

        return rl.STIRFuture(**kwargs)

    @staticmethod
    def _normalize_timestamp(timestamp: Union[datetime.datetime, pd.Timestamp, str]) -> datetime.datetime:
        if isinstance(timestamp, str) and timestamp.lower() == "live":
            return datetime.datetime.now(tz=pytz.timezone("America/New_York"))

        if isinstance(timestamp, pd.Timestamp):
            timestamp = timestamp.to_pydatetime()

        assert isinstance(timestamp, datetime.datetime), "timestamp must be datetime.datetime, pd.Timestamp, or 'live'"
        assert timestamp.tzinfo is not None and timestamp.tzinfo.utcoffset(timestamp) is not None, "timestamp must be timezone aware"
        assert timestamp.astimezone(pytz.utc) < datetime.datetime.now(tz=pytz.utc), "timestamp cannot be in the future"
        return timestamp

    @staticmethod
    def _cme_session_open_chi(timestamp: datetime.datetime) -> datetime.datetime:
        chi = pytz.timezone("America/Chicago")
        ts_chi = timestamp.astimezone(chi)
        session_open = ts_chi.replace(hour=17, minute=0, second=0, microsecond=0)
        if ts_chi < session_open:
            session_open = session_open - datetime.timedelta(days=1)
        return session_open

    def _build_curve_from_pricers(
        self,
        *,
        curve_name: str,
        timestamp: datetime.datetime,
        cfg: Dict[str, Any],
        pricers: Dict[str, List[RLSTIRFuturePricer]],
    ) -> Tuple[rl.Curve, rl.Solver]:
        sorted_pricers = _sort_pricers_for_solver(pricers)
        node_reference_key = cfg.get("node_reference_key", cfg["reference_key"])

        def one_day_irs(eff_date, curve_key):
            return rl.IRS(
                effective=eff_date,
                termination="1b",
                spec=cfg["rl_irs_spec"],
                curves=curve_key,
            )

        def butterfly(d0, d1, d2, curve_key):
            return rl.Spread(
                rl.Spread(one_day_irs(d0, curve_key), one_day_irs(d1, curve_key)),
                rl.Spread(one_day_irs(d1, curve_key), one_day_irs(d2, curve_key)),
            )

        if cfg.get("serff_skew", False):
            ff_pricers_by_code: Dict[str, RLSTIRFuturePricer] = {}
            ser_pricers_by_code: Dict[str, RLSTIRFuturePricer] = {}
            base_pricers: List[RLSTIRFuturePricer] = []

            for p in sorted_pricers:
                root_and_code = self._pricer_root_and_code(p)
                if root_and_code is None:
                    base_pricers.append(p)
                    continue

                root, code = root_and_code
                if root == "ZQ":
                    ff_pricers_by_code[code] = p
                    continue

                base_pricers.append(p)
                if root == "SR1":
                    ser_pricers_by_code[code] = p

            serff_basis = {
                code: float(ser_pricers_by_code[code]._price - ff_pricers_by_code[code]._price) for code in ser_pricers_by_code if code in ff_pricers_by_code
            }

            nodes = _build_stirf_nodes(
                timestamp=timestamp,
                pricers={"BASE": base_pricers},
                central_bank_dates=_CENTRAL_BANK_DATES,
                reference_key=node_reference_key,
                max_tenor_from_timestamp_months=cfg["max_tenor_from_timestamp_months"],
            )
            nodes = _sort_nodes(nodes)

            sofr_reference_key = cfg["sofr_reference_key"]
            rl_sofr_curve = rl.Curve(
                nodes=nodes,
                id=sofr_reference_key,
                convention=RATESLIB_CURVE_DEFINITIONS[sofr_reference_key]["DayCounter"],
                calendar=RATESLIB_CURVE_DEFINITIONS[sofr_reference_key]["Calendar"],
                modifier=RATESLIB_CURVE_DEFINITIONS[sofr_reference_key]["BusinessConvention"],
                interpolation="log_linear",
            )

            sofr_meeting_dates = sorted(k for k in nodes.keys())
            sofr_bflies = [
                butterfly(sofr_meeting_dates[i - 1], sofr_meeting_dates[i], sofr_meeting_dates[i + 1], sofr_reference_key)
                for i in range(1, len(sofr_meeting_dates) - 1)
            ]
            sofr_solver = rl.Solver(
                curves=[rl_sofr_curve],
                instruments=[self._build_pricable_for_curve(p, curve_key=sofr_reference_key) for p in base_pricers] + sofr_bflies,
                s=[p._rate for p in base_pricers] + [0.0] * len(sofr_bflies),
                id=f"{curve_name}-SOFR-ANCHOR",
                weights=[1.0] * len(base_pricers) + [1e-8] * len(sofr_bflies),
                func_tol=1e-5,
                conv_tol=1e-5,
            )

            skew_s: List[float] = []
            skew_w: List[float] = []
            for p in base_pricers:
                root_and_code = self._pricer_root_and_code(p)
                if root_and_code and root_and_code[0] == "SR1" and root_and_code[1] in serff_basis:
                    sofr_pricable = self._build_pricable_for_curve(p, curve_key=sofr_reference_key)
                    skew_s.append(float(sofr_pricable.rate(solver=sofr_solver).real) + serff_basis[root_and_code[1]])
                    skew_w.append(1e7)
                else:
                    skew_s.append(float(p._rate))
                    skew_w.append(1.0)

            rl_curve = rl.Curve(
                nodes=nodes,
                id=cfg["reference_key"],
                convention=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["DayCounter"],
                calendar=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["Calendar"],
                modifier=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["BusinessConvention"],
                interpolation="log_linear",
            )

            meeting_dates = sorted(k for k in nodes.keys())
            bflies = [butterfly(meeting_dates[i - 1], meeting_dates[i], meeting_dates[i + 1], cfg["reference_key"]) for i in range(1, len(meeting_dates) - 1)]
            rl_solver = rl.Solver(
                curves=[rl_curve],
                instruments=[self._build_pricable_for_curve(p, curve_key=cfg["reference_key"]) for p in base_pricers] + bflies,
                s=skew_s + [0.0] * len(bflies),
                id=curve_name,
                weights=skew_w + [1e-8] * len(bflies),
                func_tol=1e-5,
                conv_tol=1e-5,
            )

            return rl_curve, rl_solver

        nodes = _build_stirf_nodes(
            timestamp=timestamp,
            pricers=pricers,
            central_bank_dates=_CENTRAL_BANK_DATES,
            reference_key=node_reference_key,
            max_tenor_from_timestamp_months=cfg["max_tenor_from_timestamp_months"],
        )
        nodes = _sort_nodes(nodes)

        rl_curve = rl.Curve(
            nodes=nodes,
            id=cfg["reference_key"],
            convention=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["DayCounter"],
            calendar=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["Calendar"],
            modifier=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["BusinessConvention"],
            interpolation="log_linear",
        )

        instruments = [self._build_pricable_for_curve(p, curve_key=cfg["reference_key"]) for p in sorted_pricers]
        s = [p._rate for p in sorted_pricers]

        meeting_dates = sorted(k for k in nodes.keys())
        bflies = [butterfly(meeting_dates[i - 1], meeting_dates[i], meeting_dates[i + 1], cfg["reference_key"]) for i in range(1, len(meeting_dates) - 1)]
        pseudo_targets = [0.0] * len(bflies)

        instruments = instruments + bflies
        s = s + pseudo_targets
        weights = [1.0] * len(sorted_pricers) + [1e-8] * len(bflies)

        rl_solver = rl.Solver(
            curves=[rl_curve],
            instruments=instruments,
            s=s,
            id=curve_name,
            weights=weights,
            func_tol=1e-5,
            conv_tol=1e-5,
        )

        return rl_curve, rl_solver

    def build_curve(
        self,
        curve_name: str,
        timestamp: Union[datetime.datetime, pd.Timestamp, str, Sequence[Union[datetime.datetime, pd.Timestamp]]],
        kwargs: Optional[Dict[str, Any]] = None,
        curve_only: bool = True,
    ) -> Union[
        rl.Curve,
        Tuple[rl.Curve, rl.Solver],
        Dict[datetime.datetime, rl.Curve],
        Dict[datetime.datetime, Tuple[rl.Curve, rl.Solver]],
    ]:
        if kwargs is None:
            kwargs = {}

        assert curve_name in self._STIRF_CURVE_CONFIGS, f"{curve_name} not defined in configs"
        cfg = self._STIRF_CURVE_CONFIGS[curve_name]

        is_bulk = isinstance(timestamp, Sequence) and not isinstance(timestamp, (str, bytes, datetime.datetime))
        if is_bulk:
            raw_timestamps = list(timestamp)
            assert raw_timestamps, "timestamp list is empty"
            normalized_timestamps = [self._normalize_timestamp(ts) for ts in raw_timestamps]
            local_kwargs = dict(kwargs)
            show_tqdm = bool(local_kwargs.pop("show_tqdm", True))
            auto_prime_bulk = bool(local_kwargs.pop("auto_prime_bulk", True))
            stirf_fetch_max_workers = local_kwargs.pop("stirf_fetch_max_workers", None)
            calibration_max_workers = local_kwargs.pop("calibration_max_workers", None)
            force_refresh = bool(local_kwargs.get("force_refresh", False))
            use_curve_cache = bool(curve_only) and not force_refresh

            # Seed output from curve-cache and only process missing timestamps.
            out: Dict[datetime.datetime, Any] = {}
            pending_timestamps: List[datetime.datetime] = []
            seen_pending: Set[datetime.datetime] = set()
            for ts in normalized_timestamps:
                if use_curve_cache:
                    cached_curve = self._curve_cache_get(curve_name, ts, cfg)
                    if cached_curve is not None:
                        out[ts] = cached_curve
                        continue
                if ts not in seen_pending:
                    seen_pending.add(ts)
                    pending_timestamps.append(ts)

            if not pending_timestamps:
                return out

            tqdm_mod = None
            if show_tqdm:
                try:
                    import tqdm as tqdm_mod  # type: ignore[no-redef]
                except Exception:
                    tqdm_mod = None

            # Phase 1: optional auto-prime to minimize Barchart calls on bulk runs.
            if auto_prime_bulk:
                prime_kwargs = dict(local_kwargs)
                prime_kwargs["cache_full_intraday_fetch"] = bool(prime_kwargs.get("cache_full_intraday_fetch", True))
                prime_kwargs.setdefault("show_tqdm", False)

                session_rep_timestamps: List[datetime.datetime] = []
                seen_sessions: Set[datetime.datetime] = set()
                for ts in pending_timestamps:
                    session_open = self._cme_session_open_chi(ts)
                    if session_open not in seen_sessions:
                        seen_sessions.add(session_open)
                        session_rep_timestamps.append(ts)

                prime_iter: Iterable[datetime.datetime] = session_rep_timestamps
                if tqdm_mod is not None and len(session_rep_timestamps) > 1:
                    prime_iter = tqdm_mod.tqdm(session_rep_timestamps, desc=f"PRIMING {curve_name} STIR CACHE")

                for ts_prime in prime_iter:
                    prime_req = dict(symbols=cfg["instruments"], timestamp=ts_prime, **prime_kwargs)
                    cfg["fetch_pricers_func"](request=prime_req)

            # Phase 2: fetch STIR pricers for all requested timestamps (prefer cache).
            pricers_by_ts: Dict[datetime.datetime, Dict[str, List[RLSTIRFuturePricer]]] = {}
            fetch_pricers_bulk_func = cfg.get("fetch_pricers_bulk_func", None)
            if fetch_pricers_bulk_func is not None:
                bulk_kwargs = dict(local_kwargs)
                if auto_prime_bulk:
                    bulk_kwargs["force_refresh"] = False
                    bulk_kwargs["cache_full_intraday_fetch"] = True
                    if "max_workers" not in bulk_kwargs:
                        bulk_kwargs["max_workers"] = int(stirf_fetch_max_workers or 1)
                elif stirf_fetch_max_workers is not None and "max_workers" not in bulk_kwargs:
                    bulk_kwargs["max_workers"] = int(stirf_fetch_max_workers)

                bulk_req = dict(symbols=cfg["instruments"], timestamps=pending_timestamps, **bulk_kwargs)
                pricers_by_ts = fetch_pricers_bulk_func(request=bulk_req)

            calibration_jobs: List[Tuple[datetime.datetime, Dict[str, List[RLSTIRFuturePricer]]]] = []
            for ts in pending_timestamps:
                ts_pricers = pricers_by_ts.get(ts, None)
                if ts_pricers is None:
                    fetch_kwargs = dict(local_kwargs)
                    if auto_prime_bulk:
                        fetch_kwargs["force_refresh"] = False
                        fetch_kwargs["cache_full_intraday_fetch"] = True
                    pricer_req = dict(symbols=cfg["instruments"], timestamp=ts, **fetch_kwargs)
                    ts_pricers = cfg["fetch_pricers_func"](request=pricer_req)
                calibration_jobs.append((ts, ts_pricers))

            # Phase 3: parallel curve calibrations + tqdm progress.
            cal_workers = int(calibration_max_workers or len(calibration_jobs))
            cal_workers = max(1, min(cal_workers, len(calibration_jobs)))

            if cal_workers == 1:
                cal_iter: Iterable[Tuple[datetime.datetime, Dict[str, List[RLSTIRFuturePricer]]]] = calibration_jobs
                if tqdm_mod is not None:
                    cal_iter = tqdm_mod.tqdm(calibration_jobs, desc=f"CALIBRATING {curve_name}")
                for ts, ts_pricers in cal_iter:
                    built = self._build_curve_from_pricers(curve_name=curve_name, timestamp=ts, cfg=cfg, pricers=ts_pricers)
                    self._curve_cache_put(curve_name, ts, cfg, built[0])
                    out[ts] = built[0] if curve_only else built
            else:
                with ThreadPoolExecutor(max_workers=cal_workers, thread_name_prefix="stir-curve-calib") as pool:
                    futures = {
                        pool.submit(self._build_curve_from_pricers, curve_name=curve_name, timestamp=ts, cfg=cfg, pricers=ts_pricers): ts
                        for ts, ts_pricers in calibration_jobs
                    }
                    completed = as_completed(futures)
                    if tqdm_mod is not None:
                        completed = tqdm_mod.tqdm(completed, total=len(futures), desc=f"CALIBRATING {curve_name}")
                    for fut in completed:
                        ts = futures[fut]
                        built = fut.result()
                        self._curve_cache_put(curve_name, ts, cfg, built[0])
                        out[ts] = built[0] if curve_only else built

            return out

        normalized_timestamp = self._normalize_timestamp(timestamp)
        force_refresh = bool(kwargs.get("force_refresh", False))
        if curve_only and not force_refresh:
            cached_curve = self._curve_cache_get(curve_name, normalized_timestamp, cfg)
            if cached_curve is not None:
                return cached_curve

        pricer_req = dict(symbols=cfg["instruments"], timestamp=normalized_timestamp, **kwargs)
        pricers: Dict[str, List[RLSTIRFuturePricer]] = cfg["fetch_pricers_func"](request=pricer_req)
        built = self._build_curve_from_pricers(curve_name=curve_name, timestamp=normalized_timestamp, cfg=cfg, pricers=pricers)
        self._curve_cache_put(curve_name, normalized_timestamp, cfg, built[0])
        return built[0] if curve_only else built
