import datetime
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple, Union

from Query.Base.BaseQuery import BaseQuery
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue


@dataclass(frozen=True)
class FixedRateBondQuery(BaseQuery):
    structure: FixedRateBondStructure = FixedRateBondStructure.OUTRIGHT
    value: Union[FixedRateBondValue, List[FixedRateBondValue]] = FixedRateBondValue.YTM

    cusip: Optional[str] = None
    curve: Optional[str] = None  # Maps to the MDP source

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="FRB")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        skw = dict(self.structure_kwargs or {})
        if self.cusip is not None and "cusip" not in skw:
            skw["cusip"] = self.cusip

        object.__setattr__(self, "product", "FRB")
        object.__setattr__(self, "structure_id", self.structure)
        object.__setattr__(self, "structure_kwargs", skw)

        mr = dict(self.market_request or {})
        if self.curve is not None and "curve_name" not in mr:
            mr["curve_name"] = self.curve
        object.__setattr__(self, "market_request", mr)

        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

        cusip_str = self.structure_kwargs.get("cusip") or self.cusip or ""
        slash_count = cusip_str.count("/")

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
            if isinstance(ref_dt, datetime.datetime):
                return ref_dt.date()
            if isinstance(ref_dt, datetime.date):
                return ref_dt
            return None

        def _resolve_on_the_run_token(token: str, as_of: datetime.date) -> str:
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

            m_ct = re.match(r"^CT(\d+)$", token, re.IGNORECASE)
            m_o = re.match(r"^(O{1,3})(\d+)$", token, re.IGNORECASE)
            m_ox = re.match(r"^Ox(?P<rank>\d+)(?P<tenor>10|20|25|30|7|5|3|2)$", token, re.IGNORECASE)

            if not (m_ct or m_o or m_ox):
                if "CTD_" in token:
                    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP

                    ustf_mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
                    return ustf_mdp.get_ctd(as_of=as_of, symbol=token.split("CTD_")[1]).head(1).iloc[0]["cusip"]

                return token

            ref_df = update_reference_data(source="fiscaldata", force_refresh=False)
            ref_df = ref_df[(ref_df["issue_date"] <= as_of) & (ref_df["maturity_date"] >= as_of)].copy()
            if ref_df.empty:
                raise KeyError(f"No UST reference data available for {as_of.isoformat()}")

            ref_df["rank"] = ref_df.groupby("oi")["issue_date"].rank(method="first", ascending=False).astype(int) - 1

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
        skw.setdefault("cusip", resolved_cusip_txt)

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
            req[self.mdp_time_key] = now.date()
        else:
            v = req[self.mdp_time_key]
            if v == "now":
                req[self.mdp_time_key] = now
            # "live" or concrete value: leave as-is

        req["cusips"] = [self.cusip]
        return req

    def default_mtm_value_id(self) -> Any:
        return FixedRateBondValue.NPV
