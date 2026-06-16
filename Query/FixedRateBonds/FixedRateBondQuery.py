import datetime
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from Query.Base.BaseQuery import BaseQuery
from Query.FixedRateBonds import adapter as _frb_adapter  # noqa: F401
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue


def _request_date(now: Any) -> datetime.date | str:
    if isinstance(now, str) and now.lower() == "live":
        return "live"
    if isinstance(now, datetime.datetime):
        return now.date()
    if isinstance(now, datetime.date):
        return now
    raise TypeError(f"Unsupported request timestamp type for FixedRateBondQuery: {type(now)!r}")


def _request_datetime(now: Any) -> datetime.datetime:
    if isinstance(now, datetime.datetime):
        return now
    if isinstance(now, datetime.date):
        return datetime.datetime.combine(now, datetime.time())
    raise TypeError(f"Unsupported request timestamp type for FixedRateBondQuery: {type(now)!r}")


@dataclass(frozen=True)
class FixedRateBondQuery(BaseQuery):
    structure: FixedRateBondStructure = FixedRateBondStructure.OUTRIGHT
    value: Union[FixedRateBondValue, List[FixedRateBondValue]] = FixedRateBondValue.YTM

    cusip: Optional[str] = None
    curve: Optional[str] = None  # Maps to the MDP source

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    value_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="FRB")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        skw = dict(self.structure_kwargs or {})
        if self.cusip is not None and "cusip" not in skw:
            skw["cusip"] = self.cusip
        if skw.get("cpn") is None and skw.get("coupon") is not None:
            skw["cpn"] = skw["coupon"]
        if skw.get("front_cpn") is None and skw.get("front_coupon") is not None:
            skw["front_cpn"] = skw["front_coupon"]
        if skw.get("belly_cpn") is None and skw.get("belly_coupon") is not None:
            skw["belly_cpn"] = skw["belly_coupon"]
        if skw.get("back_cpn") is None and skw.get("back_coupon") is not None:
            skw["back_cpn"] = skw["back_coupon"]

        object.__setattr__(self, "product", "FRB")
        object.__setattr__(self, "structure_id", self.structure)
        object.__setattr__(self, "structure_kwargs", skw)

        mr = dict(self.market_request or {})
        if self.curve is not None and "curve_name" not in mr:
            mr["curve_name"] = self.curve
        object.__setattr__(self, "market_request", mr)
        object.__setattr__(self, "value_kwargs", dict(self.value_kwargs or {}))

        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

        cusip_str = self.structure_kwargs.get("cusip") or self.cusip or ""
        slash_count = cusip_str.count("/")
        explicit_multi_leg = self.structure in {FixedRateBondStructure.CURVE, FixedRateBondStructure.FLY} or any(
            skw.get(key) is not None
            for key in (
                "front_cusip",
                "belly_cusip",
                "back_cusip",
                "front_issue_date",
                "belly_issue_date",
                "back_issue_date",
                "front_maturity_date",
                "belly_maturity_date",
                "back_maturity_date",
            )
        )

        if not explicit_multi_leg:
            if slash_count == 1:
                object.__setattr__(self, "structure", FixedRateBondStructure.CURVE)
                object.__setattr__(self, "structure_id", FixedRateBondStructure.CURVE)
            elif slash_count == 2:
                object.__setattr__(self, "structure", FixedRateBondStructure.FLY)
                object.__setattr__(self, "structure_id", FixedRateBondStructure.FLY)
            else:
                object.__setattr__(self, "structure", FixedRateBondStructure.OUTRIGHT)
                object.__setattr__(self, "structure_id", FixedRateBondStructure.OUTRIGHT)

    def return_query(self) -> List["FixedRateBondQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def _all_value_ids(self) -> Tuple[FixedRateBondValue, ...]:
        if isinstance(self.value, list):
            return tuple(self.value)
        return (self.value,)

    def _uses_carry_roll_universe(self) -> bool:
        carry_roll_values = {
            getattr(FixedRateBondValue, "CARRY_BPS_RUNNING", None),
            getattr(FixedRateBondValue, "ROLL_BPS_RUNNING", None),
            getattr(FixedRateBondValue, "CARRY_AND_ROLL_BPS_RUNNING", None),
        }
        carry_roll_values.discard(None)
        return any(value in carry_roll_values for value in self._all_value_ids())

    def _uses_spline_universe(self) -> bool:
        spline_values = {
            getattr(FixedRateBondValue, "SPLINE_SPREAD", None),
            getattr(FixedRateBondValue, "SPLINE_Z_SCORE", None),
            getattr(FixedRateBondValue, "SPLINE_RMSE", None),
            getattr(FixedRateBondValue, "SPLINE_RMSE_BUCKET", None),
        }
        spline_values.discard(None)
        return any(value in spline_values for value in self._all_value_ids())

    def col_name(self, cube_name: Optional[str] = None) -> str:
        curve_label = cube_name or self.curve or ""
        struct_name = self.structure.name
        val_name = self.value.name
        rws = "/".join([str(rw) for rw in self.structure_kwargs.get("risk_weights", [])])

        cusip_str = self.structure_kwargs.get("cusip", "")
        if self.structure == FixedRateBondStructure.CURVE and self.structure_kwargs.get("front_cusip") is not None:
            cusip_str = f"{self.structure_kwargs.get('front_cusip')}v{self.structure_kwargs.get('back_cusip')}"
        elif self.structure == FixedRateBondStructure.FLY and self.structure_kwargs.get("front_cusip") is not None:
            cusip_str = f"{self.structure_kwargs.get('front_cusip')}v{self.structure_kwargs.get('belly_cusip')}v{self.structure_kwargs.get('back_cusip')}"

        if cusip_str.count("/") == 1:
            struct_name = FixedRateBondStructure.CURVE.name
        elif cusip_str.count("/") == 2:
            struct_name = FixedRateBondStructure.FLY.name

        if curve_label.strip() == cusip_str.strip():
            return re.sub(r"\s\s+", " ", f"{cusip_str} {struct_name} {val_name}".strip())

        if rws not in ["1/-1", "0.5/-0.5", "0.50/-0.50", "-1/2/-1", "-0.50/1.00/-0.50", "-0.5/1/-0.5"]:
            return re.sub(r"\s\s+", " ", f"{curve_label} {cusip_str} {rws} {struct_name} {val_name}".strip())

        return re.sub(r"\s\s+", " ", f"{curve_label} {cusip_str} {struct_name} {val_name}".strip())

    def eval_expression(self, cube_name: Optional[str] = None, ignore_risk_weight: bool = False) -> str:
        col = self.col_name(cube_name=cube_name)
        if self.risk_weight is not None and not ignore_risk_weight:
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    def resolve_query(self, ref_dt, pricer_or_curve):  # noqa: ARG002 - kept for API symmetry
        import copy

        q = copy.deepcopy(self)

        cusip_txt = str(getattr(q, "cusip", "") or "").strip()

        def _as_of_date() -> Optional[datetime.date]:
            if isinstance(ref_dt, str) and ref_dt.lower() == "live":
                return datetime.date.today()
            if isinstance(ref_dt, datetime.datetime):
                return ref_dt.date()
            if isinstance(ref_dt, datetime.date):
                return ref_dt
            return None

        def _can_resolve_from_pricer_keys(txt: str) -> bool:
            if not isinstance(pricer_or_curve, Mapping):
                return False

            token = str(txt or "").strip()
            if not token:
                return False

            if ("x" in token) and ("Ox" not in token):
                parts = [part.strip() for part in token.split("x") if part.strip()]
            elif ("/" in token) and (not re.match(r"^\d{2}\d{2}/\d{1,2}$", token)):
                parts = [part.strip() for part in token.split("/") if part.strip()]
            else:
                parts = [token]

            try:
                return all(part in pricer_or_curve for part in parts)
            except Exception:
                return False

        def _resolve_on_the_run_token(token: str, as_of: datetime.date) -> str:
            from MDP.FixedRateBonds.FixedRateBondsMDP import _filter_and_rank_ref_df
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

            m_ct = re.match(r"^CT(\d+)$", token, re.IGNORECASE)
            m_o = re.match(r"^(O{1,3})(\d+)$", token, re.IGNORECASE)
            m_ox = re.match(r"^Ox(?P<rank>\d+)(?P<tenor>10|20|25|30|7|5|3|2)$", token, re.IGNORECASE)

            if not (m_ct or m_o or m_ox):
                # "CTD_LD_US" or "CTD_ED_US"
                if "CTD_" in token:
                    import pytz
                    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP

                    delivery = "A" if "CTD_LD_" in token else "D"
                    token_substr = "CTD_LD_" if "CTD_LD_" in token else "CTD_ED_"

                    for m_code, month_nums in {
                        "H": [1, 2, 3],
                        "M": [4, 5, 6],
                        "U": [7, 8, 9],
                        "Z": [10, 11, 12],
                    }.items():
                        if as_of.month in month_nums:
                            full_symbol = f"{token.split(token_substr)[1]}{m_code}{int(as_of.strftime("%y"))}"

                    ustf_mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
                    close_2pm = pytz.timezone("America/Chicago").localize(datetime.datetime(as_of.year, as_of.month, as_of.day, 14, 00))
                    ustf_pricer = ustf_mdp.get_pricer(request=dict(symbols=[full_symbol], timestamp=close_2pm, include_basket=True))
                    ctd_pricer = ustf_pricer[full_symbol].ctd(delivery)
                    return ctd_pricer._meta_data["cusip"]

                return token

            ref_df = update_reference_data(source="fiscaldata", force_refresh=False)
            ref_df = _filter_and_rank_ref_df(ref_df, as_of)
            if ref_df.empty:
                raise KeyError(f"No UST reference data available for {as_of.isoformat()}")

            if m_ct:
                rank, tenor = 0, int(m_ct.group(1))
            elif m_o:
                rank, tenor = len(m_o.group(1)), int(m_o.group(2))
            else:
                rank, tenor = int(m_ox.group("rank")), int(m_ox.group("tenor"))

            oi_str = f"{tenor}-Year"
            target = ref_df[(ref_df["oi"] == oi_str) & (ref_df["rank"] == rank)]
            if target.empty:
                raise KeyError(f"Could not resolve constant maturity alias '{token}' for {as_of.isoformat()}")
            return str(target.iloc[0]["cusip"])

        def _resolve_cusip_aliases(txt: str) -> str:
            as_of = _as_of_date()
            if not as_of:
                return txt
            if _can_resolve_from_pricer_keys(txt):
                return txt
            tokens = re.split(r"([/x])", txt)
            resolved = []
            for tok in tokens:
                if tok in ["/", "x"]:
                    resolved.append(tok)
                else:
                    resolved.append(_resolve_on_the_run_token(tok.strip(), as_of) if tok.strip() else tok)
            return "".join(resolved)

        structure = getattr(q, "structure", None)

        if ("x" in cusip_txt) or ("/" in cusip_txt):
            if cusip_txt.count("x") == 1 or cusip_txt.count("/") == 1:
                structure = FixedRateBondStructure.CURVE
            elif cusip_txt.count("x") == 2 or cusip_txt.count("/") == 2:
                structure = FixedRateBondStructure.FLY
        else:
            structure = FixedRateBondStructure.OUTRIGHT if structure is None else structure

        resolved_cusip_txt = _resolve_cusip_aliases(cusip_txt)

        skw = dict(getattr(q, "structure_kwargs", None) or {})
        skw["cusip"] = resolved_cusip_txt
        for leg_key in ("front_cusip", "belly_cusip", "back_cusip"):
            if skw.get(leg_key) is not None:
                skw[leg_key] = _resolve_cusip_aliases(str(skw[leg_key]))

        if structure == FixedRateBondStructure.OUTRIGHT:
            if all(skw.get(k) is None for k in ("notional", "bpv")):
                skw["bpv"] = 1.0
        else:
            if all(skw.get(k) is None for k in ("front_notional", "belly_notional", "back_notional", "bpv")):
                skw["bpv"] = 1.0

        try:
            q_eff = replace(q, cusip=resolved_cusip_txt, structure=structure, structure_kwargs=skw)
        except TypeError:
            q_eff = replace(q, cusip=resolved_cusip_txt, structure=structure, structure_id=structure, structure_kwargs=skw)

        return q_eff

    # --- Arithmetic ---
    def __pos__(self) -> "FixedRateBondQuery":
        return self

    def __neg__(self) -> "FixedRateBondQuery":
        return replace(self, risk_weight=-(self.risk_weight or 1.0))

    def __mul__(self, scalar: object) -> "FixedRateBondQuery":
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        return replace(self, risk_weight=(self.risk_weight or 1.0) * float(scalar))

    def __rmul__(self, scalar: object) -> "FixedRateBondQuery":
        return self.__mul__(scalar)

    def __truediv__(self, scalar: object) -> "FixedRateBondQuery":
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        return self * (1.0 / float(scalar))

    def build_mdp_request(self, now) -> Dict[str, Any]:
        """
        Build the request dict for MDP.get_pricer(request) at time 'now'.
        Policy:
          - If mdp_time_key missing -> inject 'now.date()'
          - If mdp_time_key == "live" or already set -> pass through unchanged
          - If mdp_time_key == "now" -> inject full datetime
        """
        req = dict(self.market_request or {})
        if self.mdp_time_key not in req:
            req[self.mdp_time_key] = _request_date(now)
        else:
            v = req[self.mdp_time_key]
            if v == "now":
                req[self.mdp_time_key] = _request_datetime(now)
            # "live" or concrete value: leave as-is

        if self._uses_carry_roll_universe() or self._uses_spline_universe():
            from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

            ts_value = req[self.mdp_time_key]
            if isinstance(ts_value, str) and ts_value.lower() == "live":
                as_of_date = datetime.date.today()
            elif isinstance(ts_value, datetime.datetime):
                as_of_date = ts_value.date()
            elif isinstance(ts_value, datetime.date):
                as_of_date = ts_value
            else:
                raise TypeError(f"Unsupported timestamp for FRB carry/roll universe expansion: {type(ts_value)!r}")

            min_ttm = float((self.value_kwargs or {}).get("min_ttm", 1.0))
            ref_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
            ref_df = ref_mdp.get_bond_reference_data(as_of_date=as_of_date).copy()
            ref_df = ref_df.drop(columns=["record_date"], errors="ignore")
            if "ttm" in ref_df.columns:
                ref_df["ttm"] = pd.to_numeric(ref_df["ttm"], errors="coerce")
                ref_df = ref_df[ref_df["ttm"] >= min_ttm].copy()
            ref_df["cusip"] = ref_df["cusip"].astype(str)
            try:
                resolved_query = self.resolve_query(as_of_date, {})
                requested_cusip_text = str(resolved_query.cusip or self.cusip or "")
            except Exception:
                requested_cusip_text = str(self.cusip or "")

            requested_cusips = {
                token.strip()
                for token in requested_cusip_text.split("/")
                if token.strip()
            }
            if "rank" in ref_df.columns:
                rank = pd.to_numeric(ref_df["rank"], errors="coerce")
                ref_df = ref_df.loc[~rank.isin([0, 1, 2]) | ref_df["cusip"].isin(requested_cusips)].copy()
            ref_df = ref_df.drop_duplicates(subset=["cusip"], keep="last")
            req["cusips"] = ref_df["cusip"].tolist() or [self.cusip]
        else:
            req["cusips"] = [self.cusip]
        return req

    def default_mtm_value_id(self) -> Any:
        return FixedRateBondValue.NPV
