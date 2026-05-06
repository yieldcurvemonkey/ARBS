"""Prototype: SR3 RND vs ZQ FedWatch tree distribution comparison.

One-off pilot run on 2026-05-04 to confirm the four signals produce
non-trivial residuals in current regime before committing to a
productionized screener.

Scope:
    - One contract: SFRU26 (135 DTE, reference period Sep 16 – Dec 16 2026,
      contains 3 meetings: Sep, Oct, Dec).
    - ZQ contracts: ZQM26..ZQZ26 (Jun..Dec 2026).
    - Constant SOFR-EFFR basis = 0bp (justified: spot SOFR = spot EFFR =
      3.64% on 2026-05-01).
    - No regime classifier, no historical percentiles. Just point-in-time
      residuals.
"""

from __future__ import annotations

import datetime
import math
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from RVUtils.STIRAsymmetricScreener._rnd import extract_per_expiry_rnd
from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig
from SDRUtils.analytics.fomc import load_fomc_schedule


# --- Configuration ---------------------------------------------------------

AS_OF = datetime.date(2026, 5, 4)
SOFR_SPOT = 0.0364  # EFFR/SOFR fixing 2026-05-01 (already verified)
BASIS_BP = 0.0  # SOFR - EFFR mean (≈0bp on this date; both fixed at 3.64%)
SR3_CONTRACT = "SFRU26"
SR3_REF_START = datetime.date(2026, 9, 16)  # SR3U26 reference period start
SR3_REF_END = datetime.date(2026, 12, 16)   # SR3U26 reference period end
SR3_REF_DAYS = (SR3_REF_END - SR3_REF_START).days  # 91

# ZQ contracts to fetch (must cover SR3 ref period + at least one anchor month)
ZQ_CONTRACTS = ["ZQM26", "ZQN26", "ZQQ26", "ZQU26", "ZQV26", "ZQX26", "ZQZ26"]


# --- ZQ FedWatch tree extractor --------------------------------------------


@dataclass(frozen=True)
class MonthState:
    label: str
    contract: str
    avg_effr: float
    has_meeting: bool
    meeting_date: Optional[datetime.date]
    days_in_month: int
    days_before_meeting: int  # N — pre-meeting days
    days_after_meeting: int   # M — post-meeting days
    effr_start: float = float("nan")
    effr_end: float = float("nan")


def _months_in_range(start: datetime.date, end: datetime.date) -> List[Tuple[int, int]]:
    """Yield (year, month) tuples between start..end inclusive."""
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def _contract_for_month(year: int, month: int) -> str:
    code = "FGHJKMNQUVXZ"[month - 1]
    return f"ZQ{code}{year % 100:02d}"


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (datetime.date(year + 1, 1, 1) - datetime.date(year, 12, 1)).days
    return (datetime.date(year, month + 1, 1) - datetime.date(year, month, 1)).days


def build_fedwatch_tree(
    *,
    zq_prices: Dict[str, float],
    fomc_schedule: pd.DataFrame,
    spot_effr: float,
    months_range: Tuple[Tuple[int, int], Tuple[int, int]],
) -> Dict[str, MonthState]:
    """Build FedWatch state per month per CME methodology.

    Anchor non-FOMC month → propagate avg_effr backward (and forward by 1 month
    only) until each FOMC month has start/end EFFR populated.
    """
    fomc_dates = set()
    fomc_lookup = {}
    for _, row in fomc_schedule.iterrows():
        eff = row["effective_date"]
        if isinstance(eff, pd.Timestamp):
            eff = eff.date()
        fomc_dates.add(eff)
        fomc_lookup[(eff.year, eff.month)] = eff

    (y_lo, m_lo), (y_hi, m_hi) = months_range
    months = _months_in_range(datetime.date(y_lo, m_lo, 1), datetime.date(y_hi, m_hi, 1))

    # Initialize states
    states: Dict[Tuple[int, int], MonthState] = {}
    for y, m in months:
        contract = _contract_for_month(y, m)
        avg = 100.0 - zq_prices.get(contract, float("nan"))
        avg /= 100.0  # decimal
        meeting = fomc_lookup.get((y, m))
        days_total = _days_in_month(y, m)
        if meeting is None:
            days_before = days_after = 0
        else:
            days_before = (meeting - datetime.date(y, m, 1)).days
            days_after = days_total - days_before
        states[(y, m)] = MonthState(
            label=f"{datetime.date(y, m, 1):%b%y}".lower(),
            contract=contract,
            avg_effr=avg,
            has_meeting=meeting is not None,
            meeting_date=meeting,
            days_in_month=days_total,
            days_before_meeting=days_before,
            days_after_meeting=days_after,
        )

    # Find first non-FOMC anchor month inside the range
    anchor_idx = None
    for i, (y, m) in enumerate(months):
        if not states[(y, m)].has_meeting:
            anchor_idx = i
            break
    if anchor_idx is None:
        raise ValueError("No anchor non-FOMC month inside range")

    # Forward-propagate from anchor: anchor's avg = end[T-1] = start[T+1]
    # Anchor itself has no meeting so start = end = avg.
    populated: Dict[Tuple[int, int], MonthState] = {}
    anchor_month = months[anchor_idx]
    anchor = states[anchor_month]
    populated[anchor_month] = MonthState(
        **{**anchor.__dict__, "effr_start": anchor.avg_effr, "effr_end": anchor.avg_effr}
    )

    # Walk backward from anchor (T-1, T-2, ...): copy avg into end[T-1] then
    # solve start[T-1] from FOMC formula
    for j in range(anchor_idx - 1, -1, -1):
        cur = states[months[j]]
        next_state = populated[months[j + 1]]
        end = next_state.effr_start  # avg of next_month populated → end of this month
        # If next month is anchor, its start = avg; in general use the populated
        # next-month start.
        if cur.has_meeting:
            n = cur.days_before_meeting
            mm = cur.days_after_meeting
            # avg_T = (n/(n+m))*start_T + (m/(n+m))*end_T
            # → start_T = (avg_T - (m/(n+m))*end_T) / (n/(n+m))
            if (n + mm) <= 0 or n == 0:
                start = cur.avg_effr  # degenerate
            else:
                start = (cur.avg_effr - (mm / (n + mm)) * end) / (n / (n + mm))
        else:
            start = cur.avg_effr
        populated[months[j]] = MonthState(
            **{**cur.__dict__, "effr_start": start, "effr_end": end}
        )

    # Walk forward from anchor by ONE month (per CME methodology footnote 2)
    if anchor_idx + 1 < len(months):
        next_month = months[anchor_idx + 1]
        cur = states[next_month]
        start = anchor.avg_effr
        if cur.has_meeting:
            n = cur.days_before_meeting
            mm = cur.days_after_meeting
            if (n + mm) <= 0 or mm == 0:
                end = cur.avg_effr
            else:
                # avg = (n/(n+m))*start + (m/(n+m))*end → end = (avg - (n/(n+m))*start)/(m/(n+m))
                end = (cur.avg_effr - (n / (n + mm)) * start) / (mm / (n + mm))
        else:
            end = cur.avg_effr
        populated[next_month] = MonthState(
            **{**cur.__dict__, "effr_start": start, "effr_end": end}
        )

    # Find next anchor and repeat the process
    # For the prototype, we can restart from each anchor.
    # We'll iterate: find next anchor after current populated set, then propagate.
    populated_keys = set(populated.keys())
    while True:
        next_anchor_idx = None
        for i in range(anchor_idx + 1, len(months)):
            if not states[months[i]].has_meeting and months[i] not in populated_keys:
                next_anchor_idx = i
                break
        if next_anchor_idx is None:
            break
        # Populate the new anchor
        anchor_month = months[next_anchor_idx]
        anchor = states[anchor_month]
        populated[anchor_month] = MonthState(
            **{**anchor.__dict__, "effr_start": anchor.avg_effr, "effr_end": anchor.avg_effr}
        )
        populated_keys.add(anchor_month)
        # Walk backward from new anchor to fill any unpopulated months
        for j in range(next_anchor_idx - 1, -1, -1):
            if months[j] in populated_keys:
                break
            cur = states[months[j]]
            next_state = populated[months[j + 1]]
            end = next_state.effr_start
            if cur.has_meeting:
                n = cur.days_before_meeting
                mm = cur.days_after_meeting
                if (n + mm) <= 0 or n == 0:
                    start = cur.avg_effr
                else:
                    start = (cur.avg_effr - (mm / (n + mm)) * end) / (n / (n + mm))
            else:
                start = cur.avg_effr
            populated[months[j]] = MonthState(
                **{**cur.__dict__, "effr_start": start, "effr_end": end}
            )
            populated_keys.add(months[j])
        # Walk forward by one
        if next_anchor_idx + 1 < len(months) and months[next_anchor_idx + 1] not in populated_keys:
            nm = months[next_anchor_idx + 1]
            cur = states[nm]
            start = anchor.avg_effr
            if cur.has_meeting:
                n = cur.days_before_meeting
                mm = cur.days_after_meeting
                if (n + mm) <= 0 or mm == 0:
                    end = cur.avg_effr
                else:
                    end = (cur.avg_effr - (n / (n + mm)) * start) / (mm / (n + mm))
            else:
                end = cur.avg_effr
            populated[nm] = MonthState(
                **{**cur.__dict__, "effr_start": start, "effr_end": end}
            )
            populated_keys.add(nm)
        anchor_idx = next_anchor_idx

    # Convert keyed-by-tuple to keyed-by-label
    return {s.label: s for s in populated.values()}


# --- Per-meeting probability and variance from FedWatch tree ---------------


@dataclass
class MeetingNode:
    label: str
    date: datetime.date
    prior_effr: float       # start-of-month rate (= EFFR going in)
    next_effr: float        # end-of-month rate (= EFFR after meeting)
    expected_change_bp: float
    char_25bp: int          # integer multiple of 25bp the move is "centered" on
    mantissa: float         # remainder
    p_lower: float          # prob(char × 25bp move)
    p_upper: float          # prob((char + sign) × 25bp move)
    variance_bp2: float     # binomial variance (in bp²)


def _meeting_nodes_from_states(
    states: Dict[str, MonthState], meetings: List[datetime.date]
) -> List[MeetingNode]:
    out = []
    for meeting in meetings:
        label = f"{meeting:%b%y}".lower()
        if label not in states:
            continue
        s = states[label]
        if not s.has_meeting:
            continue
        change = s.effr_end - s.effr_start  # decimal (e.g., 0.0025 for +25bp)
        change_bp = change * 10000.0
        n_25bp = change_bp / 25.0
        char = int(math.floor(n_25bp)) if change_bp >= 0 else int(math.ceil(n_25bp))
        mantissa = abs(n_25bp - char)
        # Two outcomes: char × 25bp (prob = 1 - mantissa) and (char + sign) × 25bp (prob = mantissa)
        p_lower = 1.0 - mantissa
        p_upper = mantissa
        # Outcome rates (in bp from prior)
        if change_bp >= 0:
            outcome_lo_bp = char * 25.0
            outcome_hi_bp = (char + 1) * 25.0
        else:
            outcome_lo_bp = char * 25.0
            outcome_hi_bp = (char - 1) * 25.0
        mean_bp = p_lower * outcome_lo_bp + p_upper * outcome_hi_bp
        var_bp2 = (
            p_lower * (outcome_lo_bp - mean_bp) ** 2
            + p_upper * (outcome_hi_bp - mean_bp) ** 2
        )
        out.append(
            MeetingNode(
                label=label,
                date=meeting,
                prior_effr=s.effr_start,
                next_effr=s.effr_end,
                expected_change_bp=change_bp,
                char_25bp=char,
                mantissa=mantissa,
                p_lower=p_lower,
                p_upper=p_upper,
                variance_bp2=var_bp2,
            )
        )
    return out


# --- Day-weighted variance decomposition for SR3 reference period ----------


def day_weighted_meeting_variance_bp2(
    nodes: List[MeetingNode],
    *,
    ref_start: datetime.date,
    ref_end: datetime.date,
) -> Tuple[float, List[Tuple[str, float, float, float]]]:
    """Return (total_variance_bp2, per_meeting_breakdown).

    Each meeting's contribution is weighted by ((ref_end - meeting) / T)²
    because a meeting on day t contributes (T - t) / T to terminal compounded
    rate, and variance scales with the square.
    """
    T = (ref_end - ref_start).days
    if T <= 0:
        return 0.0, []
    total = 0.0
    breakdown = []
    for n in nodes:
        if n.date < ref_start or n.date > ref_end:
            continue
        days_after = (ref_end - n.date).days
        weight = days_after / T
        contribution_bp2 = (weight ** 2) * n.variance_bp2
        total += contribution_bp2
        breakdown.append((n.label, weight, n.variance_bp2, contribution_bp2))
    return total, breakdown


# --- Main pipeline ---------------------------------------------------------


def main():
    sys.stdout.reconfigure(line_buffering=True)
    print(f"=== SR3 vs ZQ Distribution Comparison Prototype — as_of={AS_OF} ===\n", flush=True)

    # 1. ZQ prices
    print("Fetching ZQ prices...", flush=True)
    fut_mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    snap = fut_mdp.get_data({"symbols": ZQ_CONTRACTS, "timestamp": AS_OF})
    zq_prices = {}
    for c in ZQ_CONTRACTS:
        pricers = snap.get(c) or []
        if pricers:
            p = pricers[0]
            price = getattr(p, "_price", None) or getattr(p, "price", None)
            if price is not None:
                zq_prices[c] = float(price)
    print("ZQ prices:", flush=True)
    for c, p in zq_prices.items():
        print(f"  {c}: {p:.4f}  (implied avg EFFR={100.0 - p:.4f}%)", flush=True)

    # 2. FOMC schedule
    print("\nFetching FOMC schedule...", flush=True)
    fomc = load_fomc_schedule("USD-SOFR-1D")
    fomc["effective_date"] = pd.to_datetime(fomc["effective_date"]).dt.date
    fomc_in_range = fomc[
        (fomc["effective_date"] >= AS_OF) & (fomc["effective_date"] <= datetime.date(2027, 1, 1))
    ]
    print(fomc_in_range[["meeting_label", "effective_date"]].to_string(index=False), flush=True)

    # 3. Build FedWatch tree
    print("\nBuilding FedWatch tree...", flush=True)
    states = build_fedwatch_tree(
        zq_prices=zq_prices,
        fomc_schedule=fomc_in_range,
        spot_effr=SOFR_SPOT,
        months_range=((2026, 5), (2026, 12)),
    )
    print("Per-month state (sorted):", flush=True)
    for label in sorted(states.keys(), key=lambda l: states[l].contract):
        s = states[label]
        print(
            f"  {s.label} ({s.contract}): avg={s.avg_effr * 100:.4f}%  "
            f"start={s.effr_start * 100:.4f}%  end={s.effr_end * 100:.4f}%  "
            f"meeting={s.meeting_date}",
            flush=True,
        )

    # 4. Meeting nodes inside SFRU26 reference period
    meetings_in_period = [
        m for m in fomc_in_range["effective_date"]
        if SR3_REF_START <= m <= SR3_REF_END
    ]
    print(f"\nMeetings inside SFRU26 reference period [{SR3_REF_START}–{SR3_REF_END}]:", flush=True)
    for m in meetings_in_period:
        print(f"  {m}", flush=True)

    nodes = _meeting_nodes_from_states(states, meetings_in_period)
    print("\nFedWatch per-meeting nodes:", flush=True)
    for n in nodes:
        sign = "+" if n.expected_change_bp >= 0 else "-"
        print(
            f"  {n.label} {n.date}: prior={n.prior_effr * 100:.4f}% "
            f"→ next={n.next_effr * 100:.4f}%  "
            f"E[Δ]={sign}{abs(n.expected_change_bp):.2f}bp  "
            f"char={n.char_25bp}×25bp  mantissa={n.mantissa:.4f}  "
            f"p_lo={n.p_lower:.3f}  p_hi={n.p_upper:.3f}  var={n.variance_bp2:.2f}bp²",
            flush=True,
        )

    # 5. Day-weighted ZQ tree variance
    zq_var_bp2, zq_breakdown = day_weighted_meeting_variance_bp2(
        nodes, ref_start=SR3_REF_START, ref_end=SR3_REF_END
    )
    print(f"\nDay-weighted ZQ tree variance over SFRU26 period: {zq_var_bp2:.4f} bp²", flush=True)
    print("Per-meeting breakdown:", flush=True)
    for label, weight, raw_var, weighted in zq_breakdown:
        print(f"  {label}: weight={weight:.4f}  raw={raw_var:.2f}bp²  weighted={weighted:.4f}bp²", flush=True)

    # 6. SR3 RND for SFRU26
    print(f"\nFetching SABR smile for {SR3_CONTRACT}...", flush=True)
    opt_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    smile = opt_mdp.fetch_sabr_smile(
        {"symbol": SR3_CONTRACT, "as_of": AS_OF, "strike_offsets_bps": "listed"}
    )
    print(f"  forward={smile.params.forward_price:.4f}  ttE={smile.params.time_to_expiry:.3f}", flush=True)

    print(f"\nExtracting RND...", flush=True)
    rnd = extract_per_expiry_rnd(
        smile=smile, leg_market={}, config=ScreenerConfig(), as_of=AS_OF
    )
    print(
        f"  stability={rnd.stability_flag}  modes={rnd.mode_count}  "
        f"mean_rate={rnd.mean_rate:.4f}%  std_rate={rnd.std_rate:.4f}%  "
        f"skew={rnd.skew:.3f}  kurt={rnd.kurt:.3f}",
        flush=True,
    )

    # 7. SR3 ATM-implied total variance over reference period
    # Bachelier total variance = (ATM normal vol)² × T, where T = time_to_expiry of the option
    # But we want variance over the REFERENCE PERIOD (post-expiry), not option TTE.
    # The RND at expiry already encodes the terminal compounded SOFR distribution.
    # Its variance (in rate-space, bp²) IS the answer.
    sr3_total_var_bp2 = (rnd.std_rate * 100.0) ** 2  # std in % → bp; var in bp²
    print(f"\nSR3 RND total variance (rate space): {sr3_total_var_bp2:.4f} bp²", flush=True)

    # 8. Variance residual
    # Naive: SR3 var = day-weighted ZQ var + basis var + intermeeting drift var
    # For the prototype, basis_var = 0 (constant basis assumed)
    # Intermeeting drift var: estimate from typical SOFR daily vol
    # Realized daily SOFR vol ~0.5-1bp/day → 1bp²/day × 91 days = 91bp²
    # But SOFR daily vol is dominated by month/quarter ends; mid-quarter is much
    # quieter. For prototype, use 0.3bp/day average → ~8bp² total, or 0
    intermeeting_drift_var_bp2 = (0.3 ** 2) * SR3_REF_DAYS  # ~8bp²
    basis_var_bp2 = 0.0  # constant basis assumption

    explained = zq_var_bp2 + basis_var_bp2 + intermeeting_drift_var_bp2
    residual = sr3_total_var_bp2 - explained
    print(f"\n=== VARIANCE DECOMPOSITION (bp²) ===", flush=True)
    print(f"  SR3 RND total variance:          {sr3_total_var_bp2:>10.2f}", flush=True)
    print(f"  ZQ day-weighted meeting var:     {zq_var_bp2:>10.2f}", flush=True)
    print(f"  Basis variance (assumed const):  {basis_var_bp2:>10.2f}", flush=True)
    print(f"  Intermeeting drift variance:     {intermeeting_drift_var_bp2:>10.2f}", flush=True)
    print(f"  --------------------------------- ----------", flush=True)
    print(f"  Explained:                       {explained:>10.2f}", flush=True)
    print(f"  Residual (= SR3 - explained):    {residual:>10.2f}", flush=True)
    print(f"  Residual / explained ratio:      {residual/explained:>10.3f}" if explained > 0 else "  (explained = 0)", flush=True)

    # 9. Skew residual (raw, no floor adjustment in prototype)
    # SR3 RND skew vs zero. Floor effect should produce dovish skew (positive
    # skew in rate space = right tail heavy = market prices upward rate surprises),
    # negative skew in price space (left tail heavy = market prices upward rate surprises).
    print(f"\n=== SKEW DIAGNOSTIC ===", flush=True)
    print(f"  SR3 RND skew (rate space): {rnd.skew:+.4f}", flush=True)
    print(f"  Sign convention: positive = right-tailed in rate space "
          f"(= dovish skew in price space, i.e., dovish surprises priced)", flush=True)

    # 10. Tail mass at ±50/75/100bp from SR3 forward rate
    fwd_rate_pct = 100.0 - smile.params.forward_price
    print(f"\n=== TAIL DIAGNOSTIC ===", flush=True)
    print(f"  SR3 forward rate: {fwd_rate_pct:.4f}%", flush=True)
    grid = rnd.strike_grid_rate
    pdf = rnd.density_pdf
    for delta_bp in [-100, -75, -50, 50, 75, 100]:
        threshold_rate = fwd_rate_pct + delta_bp / 100.0
        if delta_bp >= 0:
            mask = grid >= threshold_rate
        else:
            mask = grid <= threshold_rate
        prob = float(trapezoid(pdf[mask], grid[mask])) if mask.any() else 0.0
        # ZQ tree assigns ~zero probability to exactly that displacement (binary tree limited
        # to char × 25bp ± 25bp). Compute by summing tree branches.
        # For prototype: ZQ "tail" prob at ±50bp+ from spot ≈ 0 unless multiple-meeting compounded
        zq_prob = "≈0 (tree mechanically limited to char×25bp ± 25bp per meeting)"
        print(f"  ±{delta_bp:+d}bp ({threshold_rate:.4f}%):  SR3 RND={prob:.4f}  ZQ tree={zq_prob}", flush=True)

    # Cumulative SR3 tail mass at ±50bp+ for compact summary
    fwd_rate_pct = 100.0 - smile.params.forward_price
    tail_lower_50 = float(trapezoid(
        rnd.density_pdf[grid <= fwd_rate_pct - 0.50],
        grid[grid <= fwd_rate_pct - 0.50],
    )) if (grid <= fwd_rate_pct - 0.50).any() else 0.0
    tail_upper_50 = float(trapezoid(
        rnd.density_pdf[grid >= fwd_rate_pct + 0.50],
        grid[grid >= fwd_rate_pct + 0.50],
    )) if (grid >= fwd_rate_pct + 0.50).any() else 0.0

    print("\n=== SUMMARY ===", flush=True)
    if explained > 0:
        print(f"Residual variance: {residual:.2f}bp² ({residual / explained * 100:.0f}% of explained)", flush=True)
    print(f"RND skew (rate space): {rnd.skew:+.4f}", flush=True)
    print(f"RND tail mass ≤ fwd-50bp: {tail_lower_50:.4f}", flush=True)
    print(f"RND tail mass ≥ fwd+50bp: {tail_upper_50:.4f}", flush=True)
    print(f"ZQ tree tail mass at ±50bp+: ~0 (binary tree by construction)", flush=True)


if __name__ == "__main__":
    main()
