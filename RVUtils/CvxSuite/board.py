"""The cross-wrapper breakeven board: every wrapper's rent on one bp/day axis.

``build_breakeven_board(asof, *, cfg)`` returns ONE frame, one row per
structure, columns :data:`BOARD_COLUMNS`::

    structure | wrapper | theta_bp_yr | gamma_usd_bp2 | sigma_be | sigma_impl
    | sigma_rlzd | be_over_rv | impl_over_rv | z | tag

**Every vol column is bp/day** (DESIGN.md section 1); the only sqrt(252)
crossings are ``vols.bp_year_to_day`` at the two implied-vol sources (cube
bp/yr, CA-implied bp/yr). ``be_over_rv = sigma_be / sigma_rlzd`` and
``impl_over_rv = sigma_impl / sigma_rlzd`` are computed uniformly at the end,
so NaN inputs propagate and a zero realized shows up as ``inf``, never as a
silent zero.

Wrappers (DESIGN.md section 4)
------------------------------
* **W1 — long-end forward-curve pairs (strikeless vol).** One
  ``strat3_strikeless_vol.screen_frame`` call on the offline CITIVELO pricer,
  pairs ``cfg.w1_pairs``. Column map (task contract): ``carry_1y_bp ->
  theta_bp_yr`` (bp of package DV01 per year; negative = the long-gamma
  flattener pays rent), ``gamma_usd_bp2`` kept, ``be_daily_exact -> sigma_be``
  (so ``be_over_rv`` here is the screen's ``be_over_rv_exact``, not the
  published-formula ``be_over_rv``), ``rlzd_vol_bp -> sigma_rlzd`` (trailing
  1y daily vol of the LONGER rate — Citi's own ruler), ``zs_3y -> z``.
  ``level_hist``/``rate_hist`` are composed from the leg history
  (``docs/cvxsuite/leg_history.parquet``, lowercase CurveFlyScreener labels,
  bp): ``level[pair] = rate(long) - rate(short)``.

  ``sigma_impl`` (documented matching choice, crude on purpose): the cube ATM
  vol at ``(expiry = FRONT leg forward start, tail = FRONT leg tenor)`` — a
  ``15Yx5Y`` front leg reads the 15Yx5Y swaption ATM node. The swaption on the
  ``t``-tail struck ``e`` forward IS the vol of the ``e``-forward ``t``-tenor
  par rate, so the point itself is the right analogue — the crudeness is that
  the PAIR trades the *difference* of two forward rates, and one leg's vol is
  a level proxy for a spread instrument; ``impl_over_rv`` additionally divides
  the FRONT leg's implied by the BACK leg's realized (the strat3 ruler). The
  W1 payload is ``be_over_rv``; ``impl_over_rv`` is context only.

  ``cfg.w1_pairs`` default includes ``10Yx10Y/15Yx10Y``, which is NOT a member
  of ``strat3.PAIRS_15`` (task-specified default; ``screen_frame`` prices
  arbitrary pairs — only the Figure-9 cost table, irrelevant to the board,
  distinguishes members).

* **W2 — SR3 pack CA**, quoted from the SHORT-CA side (buy futures + pay the
  matched swap — Citi's short-convexity harvest; short CA = short convexity,
  collects the CA roll). Per pack rank in ``cfg.w2_ranks`` (1/5/9/13 =
  Whites/Reds/Greens/Blues) from one ``strat2_sofr_convexity.ca_snapshot`` on
  cached BARCHART settles (``listed_cache_guard`` — a miss never fetches):

  - ``sigma_impl = holee.implied_vol_from_ca_bp(ca_bp, [sqrt(time_weight)],
    convention="citi")`` converted bp/yr -> bp/day. The pseudo-T1
    ``sqrt(M)`` reproduces the stored ``M = mean(T1^2)`` exactly through
    ``pack_time_weight`` (the recorded identity; ``convention=`` explicit at
    the call site because the module default was once observed drifting).
    Negative CA -> NaN (holee's own refusal; Citi prints n/a).
  - ``sigma_be == sigma_impl`` **by model identity**, stated rather than
    hidden: the CA-implied vol is ``sqrt(2e4 * CA / M)``, exactly the realized
    vol at which the convexity sold for CA costs what it collected — the same
    closed form ``rent.sigma_be_bp_day`` would solve. Consequently
    ``be_over_rv == impl_over_rv`` on every W2 row.
  - ``theta_bp_yr = 4 * (CA(rank) - CA(rank-1))`` — the CA term-structure roll
    identity (the 3m roll of a pack is measured against the window one
    contract nearer; annualised x4; roll ~ quarter-theta measured at ratio
    1.024 on Blues). Positive = the short-CA side collects. Whites (rank 1)
    have no nearer window -> NaN, documented.
  - ``sigma_rlzd``: trailing ``cfg.w2_realized_window`` std of daily changes
    of the pack rate composed from the SAME four contracts (constant-contract
    by construction, so no IMM-roll jump), from per-date cached settles; NaN
    with a printed note when the cache cannot supply
    ``cfg.w2_realized_min_periods`` daily changes.
  - ``gamma_usd_bp2`` NaN: the board quotes the CA in bp, not a sized
    package; ``z`` NaN (a CA z-score needs the label's history panel — that
    is strat2's ``panel_timeseries``, out of board scope).

  When the asof date has no cached settles at all (the machine cache ends
  ~2026-08-13) the wrapper prints ``=== W2 SKIPPED: ... ===`` and the board
  ships the other wrappers.

* **W3 — micro-flies on adjacent KINK_GRID triples** (belly = +2). For each
  ``cfg.w3_triples`` (validated: members of ``grids.KINK_GRID`` and
  consecutive in grid order):

  - ``theta_bp_yr = carry.carry_roll_bp`` of the rate-space ``(-1, +2, -1)``
    fly ``Structure`` — bp of the quoted ``2b - a - c`` level per year,
    positive = a LONG-belly fly earns it. (Deviation from the kink screen's
    ``neutral_weights`` DV01-neutral weights, deliberate and task-specified:
    the board prices the plain belly=+2 rate fly; bpv sizing below makes the
    dollar package DV01-neutral to annuity precision.)
  - ``gamma_usd_bp2`` + ``sigma_be`` via ``rent.rent_row`` on the repriced
    ``build_irswap`` package (wings ``bpv = -package_dv01_usd/2``, belly
    ``bpv = +package_dv01_usd``; legs go STRAIGHT to the payoff profile,
    never ``resolve_pricable``). ``dv01_usd = package_dv01_usd / 2`` is the
    USD per bp of the quoted ``2b - a - c`` level: package P&L per bp =
    ``+N*db - N/2*da - N/2*dc = N/2 * d(2b - a - c)``, so
    ``theta_usd_day = carry_bp_yr/252 * N/2`` is exactly the package's USD
    roll per day.
  - ``sigma_impl``: the BELLY-point cube ATM vol (bp/day) — the ``6y1y``
    belly reads the 6yx1y swaption node.
  - ``sigma_rlzd``: realized vol of the COMPOSED fly level history
    (``compose_levels`` on the leg history). **Unit caveat, documented:**
    ``sigma_be`` is a breakeven on the PARALLEL shift while this realized is
    the fly's own level vol (the kink-ledger sigma_rlzd convention), so W3's
    ``be_over_rv`` mixes two different underlyings and is systematically
    larger than W1's like-for-like ratio. It is a screen statistic, not a
    priced edge — hence the anchor label below.
  - ``z``: trailing ``cfg.z_window`` z-score of the composed fly level;
    ``tag = grids.classify_point(belly)``.

* **W5 — options (cube ATM vs realized swap-rate vol)** at ``cfg.w5_points``
  ``(expiry_y, tail_y)``: ``sigma_impl`` = cube ATM bp/day; ``sigma_rlzd`` =
  realized bp/day of the MATCHING forward par rate from the leg history — the
  ``(e, t)`` swaption's underlying is the ``e``-forward ``t``-tenor par swap,
  leg label ``f"{e:g}y{t:g}y"`` (``(1,10) -> "1y10y"``; all three default
  points match a stored leg exactly). A point whose label is absent gets NaN
  with a printed note — nearest-label substitution is refused (a silent
  neighbour swap is how a board acquires a vol nobody measured).
  ``theta``/``gamma``/``sigma_be``/``z`` NaN: the options wrapper prices vol
  only here; ``impl_over_rv`` is the payload.

Support discipline: every cube read uses ``clamp=False`` — outside the day's
own quoted envelope the answer is NaN, never the clamped edge (the
support-gate rule; a 40y expiry must not price).

Units guard (the w3 pattern, split by population)
-------------------------------------------------
Two separate ``vols.units_median_guard`` calls, each raising loudly:
``sigma_impl`` across all rows (cube + CA-implied — all rate-level implied
vols), and ``sigma_rlzd`` over W1/W2/W5 rows (rate-level realized). W3's
``sigma_rlzd`` is EXCLUDED: a micro-fly's own level vol is legitimately below
the 0.5 bp/day floor of a SOFR rate-level series. ``sigma_be`` is not guarded
here: 0.0 (always_cheap) and inf (never_cheap) are legal taxonomy values, and
a date with positive-carry rows would trip the floor on correct data. An
EMPTY population is skipped rather than raised — a cube-absent day must
degrade that column to NaN, not kill the wrappers that did price (the guard
certifies the unit of numbers that exist; wrapper skip lines already report
absence loudly).

Reference anchors (printed by the CLI, exported here)
-----------------------------------------------------
:data:`CITI_ANCHOR_NOTE` — Citi's published curve-pair thresholds: be/rv <=
~0.8 buys convexity (strat3 Doc C entry 0.42-0.45, exit 0.80), be/rv >=
1.17-1.38 sells it (the harvest gate). They were derived on DV01-neutral
forward-curve PAIRS with the longer rate as ruler; the label says exactly
that: **not validated on micro-flies** (whose be_over_rv here is not even the
same ratio — see the W3 unit caveat).

What this module is NOT
-----------------------
Not a backtest, not an aliveness claim (DESIGN.md section 0: no family is
registered here), and not a hedge model — vol prices rent on this board; it
is never the hedge pair (measured partial R^2 <= 0.044). The W4 UST-basis
wrapper is deliberately absent: it lives in the USTFutureBasis stack
(``BT/signals/ustf_basis.py``) and is mapped, not rebuilt (DESIGN section 0).
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV import holee
from RVUtils.ConvexityRV.listed_cache_guard import try_cached
from RVUtils.ConvexityRV.strat2_sofr_convexity import (
    Strat2Config,
    ca_snapshot,
    pack_windows,
)
from RVUtils.ConvexityRV.strat3_strikeless_vol import parse_fwd, screen_frame
from RVUtils.CurveFlyScreener.screener import Leg, Structure, compose_levels
from RVUtils.CvxSuite import vols
from RVUtils.CvxSuite.carry import carry_roll_bp
from RVUtils.CvxSuite.grids import KINK_GRID, KinkPoint, classify_point, leg_label
from RVUtils.CvxSuite.rent import rent_row

__all__ = [
    "BOARD_COLUMNS",
    "CITI_ANCHOR_NOTE",
    "CITI_ANCHOR_LINES",
    "BoardConfig",
    "build_breakeven_board",
    "board_priced",
]

#: The board's column contract, in order (DESIGN.md section 4).
BOARD_COLUMNS: Tuple[str, ...] = (
    "structure",
    "wrapper",
    "theta_bp_yr",
    "gamma_usd_bp2",
    "sigma_be",
    "sigma_impl",
    "sigma_rlzd",
    "be_over_rv",
    "impl_over_rv",
    "z",
    "tag",
)

#: Task-specified label, verbatim — pinned by a test.
CITI_ANCHOR_NOTE = (
    "curve-pair anchors (0.8 long / 1.17-1.38 short) - not validated on micro-flies"
)

#: The reference lines the CLI prints under the board.
CITI_ANCHOR_LINES: Tuple[str, ...] = (
    "reference: be_over_rv <= 0.80 buys convexity (long-gamma entry; Citi Doc C entry 0.42-0.45, exit 0.80)",
    "reference: be_over_rv >= 1.17-1.38 sells convexity (harvest gate; kink_ledger BookGates 1.17)",
    CITI_ANCHOR_NOTE,
)

_NAN = float("nan")


def _default_leg_hist_path() -> Path:
    """``docs/cvxsuite/leg_history.parquet`` at the repo root of THIS checkout."""
    return Path(__file__).resolve().parents[2] / "docs" / "cvxsuite" / "leg_history.parquet"


@dataclass(frozen=True, eq=False)
class BoardConfig:
    """Every knob of the board. Frozen; ``eq=False`` (frame fields).

    The ``leg_hist`` / ``pricer`` / ``cube_store`` / ``futures_mdp`` /
    ``futures_prices`` / ``w2_snapshot`` / ``w2_pack_history`` fields are
    injection points so pure-logic tests run hermetically; ``None`` means
    "build the real thing" (parquet read, offline CITIVELO pricer,
    ``SwaptionCubeStore.default()``, ``STIRFutureMDP`` under the cache guard).
    """

    # -------------------------------------------------------------- universes
    w1_pairs: Tuple[Tuple[str, str], ...] = (
        ("15Yx5Y", "20Yx10Y"),
        ("10Yx10Y", "20Yx10Y"),
        ("10Yx10Y", "15Yx10Y"),  # task default; NOT in strat3.PAIRS_15 (documented)
    )
    w2_ranks: Tuple[int, ...] = (1, 5, 9, 13)  # Whites / Reds / Greens / Blues
    w3_triples: Tuple[Tuple[KinkPoint, KinkPoint, KinkPoint], ...] = (
        (KinkPoint(5.0, 1.0), KinkPoint(6.0, 1.0), KinkPoint(7.0, 1.0)),
        (KinkPoint(10.0, 2.0), KinkPoint(12.0, 3.0), KinkPoint(15.0, 5.0)),
        (KinkPoint(15.0, 5.0), KinkPoint(20.0, 5.0), KinkPoint(25.0, 5.0)),
    )
    w5_points: Tuple[Tuple[float, float], ...] = ((1.0, 10.0), (5.0, 10.0), (10.0, 10.0))

    # ---------------------------------------------------------------- sizing
    package_dv01_usd: float = 100_000.0
    curve_name: str = "USD-SOFR-1D"
    swap_source: str = "CITIVELO_EXCEL"
    futures_source: str = "BARCHART_STIRF_SETTLE-RL"  # class default is WEBULL — never rely on it
    """The CME settle (Barchart daily bars), keyed 15:00 ET. Was
    ``BARCHART_STIRF-RL`` -- the 15:59 CT Globex close -- until 2026-08-27; that
    marked the futures leg two hours after the swap leg. Its cache is a separate
    namespace, so a board built before the switch cannot be silently reused."""

    # ------------------------------------------------------------- windows
    realized_window: int = 252
    realized_min_periods: int = 100
    z_window: int = 756
    z_min_obs: int = 100
    w2_n_contracts: int = 16          # rank 13 (Blues) needs contracts 13..16
    w2_realized_window: int = 63      # strat2's realized_window_days
    w2_realized_min_periods: int = 42
    w2_fetch_history: bool = True     # False -> sigma_rlzd NaN with a printed note

    # ----------------------------------------------------------- injections
    leg_hist: Optional[pd.DataFrame] = None
    leg_hist_path: Optional[str] = None
    pricer: Any = None
    cube_store: Any = None
    futures_mdp: Any = None
    futures_prices: Optional[Mapping[str, float]] = None
    w2_snapshot: Optional[pd.DataFrame] = None      # rank/pack/colour/ca_bp/time_weight
    w2_pack_history: Optional[pd.DataFrame] = None  # dates x pack label, pack rate bp


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _as_date(asof) -> _dt.date:
    if isinstance(asof, _dt.datetime):
        return asof.date()
    if isinstance(asof, _dt.date):
        return asof
    return pd.Timestamp(asof).date()


def _load_leg_hist(cfg: BoardConfig, asof: _dt.date) -> pd.DataFrame:
    """The bp leg history trimmed to ``index <= asof``; loud on absence."""
    if cfg.leg_hist is not None:
        h = cfg.leg_hist
    else:
        path = Path(cfg.leg_hist_path) if cfg.leg_hist_path else _default_leg_hist_path()
        if not path.exists():
            raise FileNotFoundError(
                f"leg history parquet not found at {path} - run scripts/cvxsuite_warm_legs.py "
                "or pass cfg.leg_hist")
        h = pd.read_parquet(path)
    if not isinstance(h.index, pd.DatetimeIndex):
        h = h.copy()
        h.index = pd.DatetimeIndex(pd.to_datetime(h.index))
    h = h.sort_index()
    out = h[h.index <= pd.Timestamp(asof)]
    if len(out) == 0:
        raise ValueError(
            f"leg history has no rows at or before {asof} (history spans "
            f"{h.index.min().date()}..{h.index.max().date()})")
    return out


def _build_pricer(asof: _dt.date, cfg: BoardConfig):
    """Offline store-backed CITIVELO pricer for ``asof``; raises loudly otherwise."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    pricer = IRSwapsMDP(source=cfg.swap_source).get_data(
        {"curve_name": cfg.curve_name, "timestamp": asof, "offline": True})
    if pricer is None:
        raise RuntimeError(
            f"IRSwapsMDP.get_data returned None for {cfg.curve_name} @ {asof} offline "
            "(curve store miss)")
    meta = pricer.meta()
    if meta.get("from_curve_store") is not True:
        raise RuntimeError(
            f"pricer for {asof} is not store-backed (from_curve_store="
            f"{meta.get('from_curve_store')!r}); offline discipline forbids using it")
    ref = pd.Timestamp(pricer.reference_date()).date()
    if ref != asof:
        raise RuntimeError(
            f"pricer reference date {ref} != requested asof {asof} - a substituted "
            "curve day would silently shift every board number")
    return pricer


def _cube_bp_day(expiry_y: float, tail_y: float, asof: _dt.date, cfg: BoardConfig,
                 notes: List[str], what: str) -> float:
    """Cube ATM at (expiry, tail) in bp/day; ``clamp=False`` = support-gated NaN.

    A cube-store failure (no store on this machine) degrades to NaN WITH a
    printed note — sigma_impl is one column of a row whose be_over_rv payload
    must still ship; an absent day already comes back NaN from ``vols``.
    """
    try:
        v_yr = vols.cube_atm_bp_year(expiry_y, tail_y, asof, store=cfg.cube_store,
                                     clamp=False)
    except Exception as exc:  # noqa: BLE001 — store absence, reported not fatal
        notes.append(f"cube note: {what}: swaption cube store unavailable ({exc!r}) "
                     "- sigma_impl NaN")
        return _NAN
    return float(vols.bp_year_to_day(v_yr))


def _trailing_realized(series: pd.Series, *, window: int, min_periods: int) -> float:
    """Last value of the trailing bp/day realized vol of a bp level series."""
    s = pd.Series(series).dropna()
    if len(s) < 2:
        return _NAN
    rv = vols.realized_vol_bp_day(s, window=window, min_periods=min_periods)
    return float(rv.iloc[-1]) if len(rv) else _NAN


def _trailing_z(series: pd.Series, *, window: int, min_obs: int) -> float:
    """z of the last observation vs the trailing ``window`` observations."""
    s = pd.Series(series).dropna()
    if len(s) < int(min_obs):
        return _NAN
    tail = s.iloc[-int(window):]
    sd = float(tail.std(ddof=1))
    if not math.isfinite(sd) or sd <= 0:
        return _NAN
    return float((tail.iloc[-1] - tail.mean()) / sd)


def _row(structure: str, wrapper: str, *, theta_bp_yr=_NAN, gamma_usd_bp2=_NAN,
         sigma_be=_NAN, sigma_impl=_NAN, sigma_rlzd=_NAN, z=_NAN, tag="") -> Dict[str, Any]:
    return {
        "structure": structure,
        "wrapper": wrapper,
        "theta_bp_yr": float(theta_bp_yr),
        "gamma_usd_bp2": float(gamma_usd_bp2),
        "sigma_be": float(sigma_be),
        "sigma_impl": float(sigma_impl),
        "sigma_rlzd": float(sigma_rlzd),
        "z": float(z),
        "tag": str(tag),
    }


def _strat3_to_cfs(label: str) -> str:
    """``"15Yx5Y" -> "15y5y"`` — the leg-history (CurveFlyScreener) column key."""
    f, t = parse_fwd(label)
    return f"{f:g}y{t:g}y" if f else f"{t:g}y"


# ---------------------------------------------------------------------------
# W1 — strikeless-vol forward pairs
# ---------------------------------------------------------------------------
def _w1_histories(leg_hist: pd.DataFrame, pairs: Sequence[Tuple[str, str]]
                  ) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(level_hist, rate_hist) for ``screen_frame``, composed from the leg history.

    ``level_hist`` columns are the pair strings ``"short/long"`` (bp, long
    minus short); ``rate_hist`` columns are the strat3 leg labels. Missing leg
    columns raise KeyError naming them — a pair with one absent leg must not
    price on a part-composed level.
    """
    level: Dict[str, pd.Series] = {}
    rate: Dict[str, pd.Series] = {}
    for short, long_ in pairs:
        s_key, l_key = _strat3_to_cfs(short), _strat3_to_cfs(long_)
        missing = [k for k in (s_key, l_key) if k not in leg_hist.columns]
        if missing:
            raise KeyError(
                f"leg history is missing column(s) {missing} needed for pair "
                f"{short}/{long_}")
        rate[short] = leg_hist[s_key]
        rate[long_] = leg_hist[l_key]
        level[f"{short}/{long_}"] = leg_hist[l_key] - leg_hist[s_key]
    return pd.DataFrame(level), pd.DataFrame(rate)


def _w1_rows(asof: _dt.date, cfg: BoardConfig, pricer, leg_hist: pd.DataFrame,
             notes: List[str]) -> List[Dict[str, Any]]:
    level_hist, rate_hist = _w1_histories(leg_hist, cfg.w1_pairs)
    sf = screen_frame(
        pricer,
        cfg.w1_pairs,
        asof=asof,
        package_dv01_usd=cfg.package_dv01_usd,
        level_hist=level_hist,
        rate_hist=rate_hist,
    )
    rows: List[Dict[str, Any]] = []
    for _, r in sf.iterrows():
        front_f, front_t = parse_fwd(r["short_leg"])
        rows.append(_row(
            structure=str(r["pair"]),
            wrapper="W1",
            theta_bp_yr=r["carry_1y_bp"],
            gamma_usd_bp2=r["gamma_usd_bp2"],
            sigma_be=r["be_daily_exact"],
            sigma_impl=_cube_bp_day(front_f, front_t, asof, cfg, notes,
                                    f"W1 {r['pair']}"),
            sigma_rlzd=r["rlzd_vol_bp"],
            z=r["zs_3y"],
            tag="flattener",
        ))
    return rows


# ---------------------------------------------------------------------------
# W2 — SR3 pack CA (short-CA orientation)
# ---------------------------------------------------------------------------
def _extract_prices(out: Optional[Mapping[str, Any]], symbols: Sequence[str]
                    ) -> Dict[str, float]:
    prices: Dict[str, float] = {}
    if not out:
        return prices
    for sym in symbols:
        lst = out.get(sym) or []
        if not lst:
            continue
        try:
            px = float(lst[0].price())
        except Exception:  # noqa: BLE001 — a broken cached pricer is absence, not a price
            continue
        if np.isfinite(px) and px > 0:
            prices[sym] = px
    return prices


def _cached_settles(mdp, symbols: Sequence[str], day: _dt.date) -> Dict[str, float]:
    """Cached EOD settles for ``symbols`` at ``day``; partial coverage allowed.

    One bulk ``try_cached`` first; when the bulk call dies on a single missing
    symbol (a miss raises inside ``get_data`` under the guard and ``try_cached``
    swallows the WHOLE call), fall back to per-symbol calls so the cached part
    of the strip still prices. Never fetches — the guard blackholes HTTP.
    """
    out = try_cached(mdp, {"symbols": list(symbols), "timestamp": day})
    prices = _extract_prices(out, symbols)
    if prices or out is not None:
        return prices
    for sym in symbols:
        one = try_cached(mdp, {"symbols": [sym], "timestamp": day})
        prices.update(_extract_prices(one, [sym]))
    return prices


def _w2_implied_bp_day(ca_bp: float, time_weight: float) -> float:
    """CA-implied Ho-Lee vol, bp/day, via the pseudo-T1 sqrt(M) identity."""
    if not (np.isfinite(ca_bp) and np.isfinite(time_weight)) or time_weight <= 0:
        return _NAN
    v_yr = holee.implied_vol_from_ca_bp(
        float(ca_bp), [math.sqrt(float(time_weight))], convention="citi")
    return float(vols.bp_year_to_day(v_yr))


def _w2_rows(asof: _dt.date, cfg: BoardConfig, pricer, skips: Dict[str, str],
             notes: List[str]) -> List[Dict[str, Any]]:
    snap = cfg.w2_snapshot
    pack_hist = cfg.w2_pack_history

    if snap is None:
        s2 = Strat2Config(
            curve=cfg.curve_name,
            swap_source=cfg.swap_source,
            futures_source=cfg.futures_source,
            n_contracts=cfg.w2_n_contracts,
        )
        specs = pack_windows(asof, s2)
        symbols = list(dict.fromkeys(sym for sp in specs for sym in sp.symbols))

        prices = dict(cfg.futures_prices) if cfg.futures_prices is not None else None
        if prices is None:
            mdp = cfg.futures_mdp
            if mdp is None:
                from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

                mdp = STIRFutureMDP(source=cfg.futures_source)
            prices = _cached_settles(mdp, symbols, asof)
            if not prices:
                skips["W2"] = (
                    f"no cached SR3 EOD settles for {asof} under {cfg.futures_source} "
                    "(machine cache ends ~2026-08-13; refresh via the guarded fetcher, "
                    "never from the board)")
                return []
        else:
            mdp = cfg.futures_mdp

        if pricer is None:
            skips["W2"] = "no swap pricer (curve store miss) - the CA needs the matched swap leg"
            return []
        snap = ca_snapshot(asof, s2, futures_prices=prices, swap_pricer=pricer)
        if snap is None or len(snap) == 0:
            skips["W2"] = (
                f"cached settles cover no complete pack window on {asof} "
                f"({len(prices)}/{len(symbols)} contracts priced)")
            return []

        if pack_hist is None and cfg.w2_fetch_history and mdp is not None:
            days = pd.bdate_range(end=pd.Timestamp(asof),
                                  periods=cfg.w2_realized_window + 1)
            by_day: Dict[pd.Timestamp, Dict[str, float]] = {}
            for d in days:
                px = _cached_settles(mdp, symbols, d.date())
                if px:
                    by_day[d] = px
            if by_day:
                price_df = pd.DataFrame.from_dict(by_day, orient="index").sort_index()
                cols: Dict[str, pd.Series] = {}
                for sp in specs:
                    if all(s in price_df.columns for s in sp.symbols):
                        sub = price_df[list(sp.symbols)].dropna()
                        if len(sub):
                            cols[sp.label] = (100.0 - sub.mean(axis=1)) * 100.0
                pack_hist = pd.DataFrame(cols) if cols else None
    else:
        need = {"rank", "pack", "ca_bp", "time_weight"}
        missing = sorted(need - set(snap.columns))
        if missing:
            raise KeyError(f"injected w2_snapshot is missing columns {missing}")

    by_rank = snap.set_index("rank")
    if by_rank.index.has_duplicates:
        raise ValueError("w2 snapshot has duplicate pack ranks - refusing to price on it")

    rows: List[Dict[str, Any]] = []
    for rank in cfg.w2_ranks:
        if rank not in by_rank.index:
            notes.append(f"W2 note: pack rank {rank} not quoted on {asof} (missing settles)")
            continue
        r = by_rank.loc[rank]
        label = str(r["pack"])
        colour = str(r["colour"]) if "colour" in by_rank.columns and pd.notna(r.get("colour")) else f"rank{rank}"
        ca = float(r["ca_bp"])
        sigma_impl = _w2_implied_bp_day(ca, float(r["time_weight"]))

        if (rank - 1) in by_rank.index:
            theta = 4.0 * (ca - float(by_rank.loc[rank - 1, "ca_bp"]))
        else:
            theta = _NAN
            notes.append(
                f"W2 note: {colour} (rank {rank}) has no one-nearer window - "
                "theta (CA roll) is NaN")

        sigma_rlzd = _NAN
        if pack_hist is not None and label in pack_hist.columns:
            series = pack_hist[label]
            if isinstance(pack_hist.index, pd.DatetimeIndex):
                series = series[series.index <= pd.Timestamp(asof)]
            sigma_rlzd = _trailing_realized(
                series,
                window=cfg.w2_realized_window,
                min_periods=cfg.w2_realized_min_periods,
            )
        if not np.isfinite(sigma_rlzd):
            notes.append(
                f"W2 note: no usable settle history for pack {label} "
                f"(need {cfg.w2_realized_min_periods}+ daily changes) - sigma_rlzd NaN")

        rows.append(_row(
            structure=f"sr3-{colour.lower()}-pack-ca",
            wrapper="W2",
            theta_bp_yr=theta,
            gamma_usd_bp2=_NAN,   # CA quoted in bp, not a sized package (docstring)
            sigma_be=sigma_impl,  # model identity: CA-implied IS the breakeven (docstring)
            sigma_impl=sigma_impl,
            sigma_rlzd=sigma_rlzd,
            z=_NAN,
            tag=f"short-ca {label}",
        ))
    if not rows:
        skips["W2"] = f"none of the requested pack ranks {list(cfg.w2_ranks)} priced on {asof}"
    return rows


# ---------------------------------------------------------------------------
# W3 — adjacent-triple micro-flies
# ---------------------------------------------------------------------------
def _validate_triple(triple: Sequence[KinkPoint]) -> Tuple[KinkPoint, KinkPoint, KinkPoint]:
    pts = tuple(KinkPoint(float(p[0]), float(p[1])) for p in triple)
    if len(pts) != 3:
        raise ValueError(f"a micro-fly triple needs exactly 3 grid points, got {triple!r}")
    try:
        idx = [KINK_GRID.index(p) for p in pts]
    except ValueError as exc:
        raise ValueError(
            f"triple {tuple(leg_label(p) for p in pts)} is not made of KINK_GRID "
            f"points: {exc}") from None
    if idx != [idx[0], idx[0] + 1, idx[0] + 2]:
        raise ValueError(
            f"triple {tuple(leg_label(p) for p in pts)} is not three ADJACENT "
            f"KINK_GRID points (grid indices {idx}); the board's micro-flies are "
            "adjacent-triple structures by design")
    return pts


def _w3_rows(asof: _dt.date, cfg: BoardConfig, pricer, leg_hist: pd.DataFrame,
             notes: List[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    cache: Dict = {}
    half = cfg.package_dv01_usd / 2.0
    for triple in cfg.w3_triples:
        a, b, c = _validate_triple(triple)
        labels = (leg_label(a), leg_label(b), leg_label(c))
        name = "/".join(labels)
        struct = Structure(
            name,
            (Leg(a.fwd, a.tenor), Leg(b.fwd, b.tenor), Leg(c.fwd, c.tenor)),
            (-1.0, 2.0, -1.0),
            "fly",
        )
        try:
            theta = carry_roll_bp(pricer, struct, 1.0, cache)
            pkg = [
                pricer.build_irswap(fwd=f"{a.fwd:g}Y", tenor=f"{a.tenor:g}Y", bpv=-half),
                pricer.build_irswap(fwd=f"{b.fwd:g}Y", tenor=f"{b.tenor:g}Y",
                                    bpv=+cfg.package_dv01_usd),
                pricer.build_irswap(fwd=f"{c.fwd:g}Y", tenor=f"{c.tenor:g}Y", bpv=-half),
            ]
            rr = rent_row(pricer, pkg, dv01_usd=half, carry_bp_yr=theta)
        except Exception as exc:  # noqa: BLE001 — one unpriceable triple must not kill the rest
            notes.append(f"W3 note: {name} failed to price: {exc!r}")
            continue

        fly_hist = compose_levels(leg_hist, [struct])
        if name in fly_hist.columns:
            series = fly_hist[name]
            sigma_rlzd = _trailing_realized(
                series, window=cfg.realized_window, min_periods=cfg.realized_min_periods)
            z = _trailing_z(series, window=cfg.z_window, min_obs=cfg.z_min_obs)
        else:
            sigma_rlzd, z = _NAN, _NAN
            notes.append(
                f"W3 note: leg history cannot compose {name} "
                f"(missing one of {labels}) - sigma_rlzd/z are NaN")

        rows.append(_row(
            structure=name,
            wrapper="W3",
            theta_bp_yr=theta,
            gamma_usd_bp2=rr.gamma_usd_per_bp2,
            sigma_be=rr.sigma_be_bp_day,
            sigma_impl=_cube_bp_day(b.fwd, b.tenor, asof, cfg, notes, f"W3 {name}"),
            sigma_rlzd=sigma_rlzd,
            z=z,
            tag=classify_point(b),
        ))
    return rows


# ---------------------------------------------------------------------------
# W5 — cube ATM vs realized forward par rate
# ---------------------------------------------------------------------------
def _w5_rows(asof: _dt.date, cfg: BoardConfig, leg_hist: pd.DataFrame,
             notes: List[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for e, t in cfg.w5_points:
        e, t = float(e), float(t)
        label = vols.point_label(e, t)
        leg_key = f"{e:g}y{t:g}y" if e else f"{t:g}y"
        sigma_rlzd = _NAN
        if leg_key in leg_hist.columns:
            sigma_rlzd = _trailing_realized(
                leg_hist[leg_key], window=cfg.realized_window,
                min_periods=cfg.realized_min_periods)
        else:
            notes.append(
                f"W5 note: no leg history column {leg_key!r} for cube point {label} - "
                "sigma_rlzd is NaN (nearest-label substitution refused)")
        rows.append(_row(
            structure=label,
            wrapper="W5",
            sigma_impl=_cube_bp_day(e, t, asof, cfg, notes, f"W5 {label}"),
            sigma_rlzd=sigma_rlzd,
            tag="atm-vol",
        ))
    return rows


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def _guard_units(df: pd.DataFrame) -> None:
    """Split-population w3-pattern unit guards (module docstring). Raises loudly."""
    impl = df["sigma_impl"]
    impl_pop = impl[np.isfinite(impl)]
    if len(impl_pop):
        vols.units_median_guard(impl_pop)
    rate_level = df.loc[df["wrapper"].isin(("W1", "W2", "W5")), "sigma_rlzd"]
    rlzd_pop = rate_level[np.isfinite(rate_level)]
    if len(rlzd_pop):
        vols.units_median_guard(rlzd_pop)


def build_breakeven_board(asof, *, cfg: BoardConfig) -> pd.DataFrame:
    """The cross-wrapper breakeven board for one date. See the module docstring.

    Returns a frame with columns :data:`BOARD_COLUMNS` (one row per structure;
    empty with the full column set when nothing priced). Wrapper-level
    failures never abort the board: each failing wrapper records a reason in
    ``df.attrs["skips"]`` and prints ``=== Wx SKIPPED: reason ===``; per-row
    degradations are printed and collected in ``df.attrs["notes"]``.
    ``df.attrs["asof"]`` carries the date.
    """
    asof = _as_date(asof)
    skips: Dict[str, str] = {}
    notes: List[str] = []
    rows: List[Dict[str, Any]] = []

    try:
        leg_hist = _load_leg_hist(cfg, asof)
    except Exception as exc:  # noqa: BLE001 — every leg-history consumer skips with the reason
        leg_hist = None
        skips["leg_history"] = repr(exc)

    pricer = cfg.pricer
    if pricer is None:
        try:
            pricer = _build_pricer(asof, cfg)
        except Exception as exc:  # noqa: BLE001 — curve-dependent wrappers skip with the reason
            pricer = None
            skips["curve"] = repr(exc)

    # ---- W1 ---------------------------------------------------------------
    if pricer is None:
        skips.setdefault("W1", f"no offline curve pricer for {asof}: {skips.get('curve', '?')}")
    elif leg_hist is None:
        skips.setdefault("W1", f"no leg history: {skips.get('leg_history', '?')}")
    else:
        try:
            rows.extend(_w1_rows(asof, cfg, pricer, leg_hist, notes))
        except Exception as exc:  # noqa: BLE001
            skips["W1"] = repr(exc)

    # ---- W2 ---------------------------------------------------------------
    try:
        rows.extend(_w2_rows(asof, cfg, pricer, skips, notes))
    except Exception as exc:  # noqa: BLE001
        skips["W2"] = repr(exc)

    # ---- W3 ---------------------------------------------------------------
    if pricer is None:
        skips.setdefault("W3", f"no offline curve pricer for {asof}: {skips.get('curve', '?')}")
    elif leg_hist is None:
        skips.setdefault("W3", f"no leg history: {skips.get('leg_history', '?')}")
    else:
        try:
            w3 = _w3_rows(asof, cfg, pricer, leg_hist, notes)
            if not w3:
                skips["W3"] = "no micro-fly triple priced (see notes)"
            rows.extend(w3)
        except Exception as exc:  # noqa: BLE001
            skips["W3"] = repr(exc)

    # ---- W5 ---------------------------------------------------------------
    if leg_hist is None:
        skips.setdefault("W5", f"no leg history: {skips.get('leg_history', '?')}")
    else:
        try:
            rows.extend(_w5_rows(asof, cfg, leg_hist, notes))
        except Exception as exc:  # noqa: BLE001
            skips["W5"] = repr(exc)

    df = pd.DataFrame(rows, columns=[c for c in BOARD_COLUMNS if c not in ("be_over_rv", "impl_over_rv")])
    df["be_over_rv"] = df["sigma_be"] / df["sigma_rlzd"]
    df["impl_over_rv"] = df["sigma_impl"] / df["sigma_rlzd"]
    df = df[list(BOARD_COLUMNS)]

    _guard_units(df)

    for name in ("W1", "W2", "W3", "W5"):
        if name in skips:
            print(f"=== {name} SKIPPED: {skips[name]} ===")
    for note in notes:
        print(note)

    df.attrs["asof"] = asof
    df.attrs["skips"] = dict(skips)
    df.attrs["notes"] = list(notes)
    return df


def board_priced(df: pd.DataFrame) -> bool:
    """True when ANY wrapper actually priced something.

    "Priced" = at least one finite value among sigma_be / sigma_impl /
    sigma_rlzd across rows (0.0 counts — an always-cheap breakeven is a
    price; inf and NaN do not). The CLI exits 2 when this is False — a board
    that priced nothing is a failure, not a flat answer (famb convention).
    """
    if df is None or len(df) == 0:
        return False
    vals = df[["sigma_be", "sigma_impl", "sigma_rlzd"]].to_numpy(dtype=float)
    return bool(np.isfinite(vals).any())
