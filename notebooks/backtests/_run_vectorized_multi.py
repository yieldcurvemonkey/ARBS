"""Event-driven multi-structure backtest: flies + dflies + calendar spreads.

No regime filters. Optimized signal (Z>2.0, 120d window, carry ON).
Quarterly rebalancing. Full curve-priced MTM via QueryDrivenBacktest.
"""
import importlib.util, sys, os, datetime, pytz, numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

for mn, mf in [
    ("sfr_cal_spread_rv", "BT/signals/sfr_cal_spread_rv.py"),
    ("sfr_fly_triggers", "BT/signals/sfr_fly_triggers.py"),
]:
    sp = importlib.util.spec_from_file_location(mn, os.path.join(REPO, mf), submodule_search_locations=[])
    m = importlib.util.module_from_spec(sp); m.__package__ = "BT.signals"; m.__name__ = mn
    sys.modules[mn] = m; sys.modules[f"BT.signals.{mn}"] = m; sp.loader.exec_module(m)

import sfr_cal_spread_rv as rv
import sfr_fly_triggers as trg

from BT.data_handler import TimeGrid
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.event import TriggerInfo
from BT.triggers import Trigger, TriggerRequirements
from BT.query_order import QueryOrder, UnwindOrder
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from TB.TimeseriesBuilder import TimeseriesBuilder

NYC = pytz.timezone("America/New_York")

# ══════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════

CONFIG = {
    'data_start': '2020-01-01',
    'bt_start':   '2021-07-01',
    'bt_end':     'live',
    'n_contracts': 12,
    'constant_maturity': True,
    'roll_adjusted': True,
    'source': 'BARCHART_STIRF-RL',
    'curve': 'USD-SOFR-1D-Q12STIRT',

    # Structures
    'structures': {
        'fly_3m':  {'fn': 'fly',    'gap': 1, 'query_type': 'FLY'},
        'fly_6m':  {'fn': 'fly',    'gap': 2, 'query_type': 'FLY'},
        'dfly_3m': {'fn': 'dfly',   'gap': 1, 'query_type': 'DFLY'},
        'spd_3m':  {'fn': 'spread', 'gap': 1, 'query_type': 'CURVE'},
        'spd_6m':  {'fn': 'spread', 'gap': 2, 'query_type': 'CURVE'},
        'spd_12m': {'fn': 'spread', 'gap': 4, 'query_type': 'CURVE'},
    },

    # Signal — optimized from diagnostic
    'zscore_window': 120,
    'vol_window': 20,
    'entry_min_zscore': 2.0,
    'entry_require_carry': True,

    # Rebalance
    'rebalance_freq': 'Q',

    # Exit
    'exit_mean_reversion': True,
    'exit_stop_loss_sd': 1.5,
    'exit_max_holding_days': 66,

    # Portfolio
    'max_positions': 10,
    'belly_bpv': 100_000,
}


# ══════════════════════════════════════════════════════════════════
# MULTI-STRUCTURE SIGNAL TABLE
# ══════════════════════════════════════════════════════════════════

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class MultiSignal:
    """Signal for any structure type."""
    structure_name: str     # e.g. 'fly_3m', 'spd_6m', 'dfly_3m'
    instrument_id: str      # e.g. 'SFR1/SFR2/SFR3'
    query_type: str         # 'FLY', 'CURVE', 'DFLY'
    level: float
    zscore: float
    vol: float
    roll: float
    direction: int          # +1 or -1
    passes_entry: bool
    abs_z: float


def build_multi_signal_table(all_ts, all_zs, all_vo, all_ro, config):
    """Build signal table across all structures. Only emit on rebalance dates."""
    bt_start = pd.Timestamp(config['bt_start'], tz=NYC)
    # Get all dates
    first_ts = list(all_ts.values())[0]
    all_dates = first_ts.index[first_ts.index >= bt_start]

    # Use .date() for tz-safe comparison
    if config['rebalance_freq'] == 'Q':
        rebal_ts = all_dates.to_series().groupby(all_dates.to_period('Q')).first()
        rebal = set(pd.Timestamp(v).date() for v in rebal_ts.values)
    elif config['rebalance_freq'] == 'M':
        rebal_ts = all_dates.to_series().groupby(all_dates.to_period('M')).first()
        rebal = set(pd.Timestamp(v).date() for v in rebal_ts.values)
    else:
        rebal = set(d.date() if hasattr(d, 'date') else pd.Timestamp(d).date() for d in all_dates.values)

    # Also need signals on non-rebalance dates for exit checks
    signal_table = {}
    for dt in all_dates:
        dt_ts = pd.Timestamp(dt)
        is_rebal = (dt_ts.date() if hasattr(dt_ts, 'date') else pd.Timestamp(dt_ts).date()) in rebal
        signals = []

        for sname, spec in config['structures'].items():
            ts = all_ts[sname]
            zs = all_zs[sname]
            vo = all_vo[sname]
            ro = all_ro[sname]

            if dt_ts not in zs.index:
                continue

            for col in ts.columns:
                z = zs.loc[dt_ts, col]
                level = ts.loc[dt_ts, col]
                vol = vo.loc[dt_ts, col] if dt_ts in vo.index else np.nan
                roll = ro.loc[dt_ts, col] if dt_ts in ro.index else np.nan

                if np.isnan(z) or np.isnan(level):
                    continue

                direction = -1 if z > 0 else 1

                passes = is_rebal  # only enter on rebalance dates
                if passes and abs(z) < config['entry_min_zscore']:
                    passes = False
                if passes and config.get('entry_require_carry') and not np.isnan(roll):
                    carry_aligned = (direction == 1 and roll > 0) or (direction == -1 and roll < 0)
                    if not carry_aligned:
                        passes = False

                signals.append(MultiSignal(
                    structure_name=sname, instrument_id=col,
                    query_type=spec['query_type'], level=float(level),
                    zscore=float(z), vol=float(vol) if not np.isnan(vol) else 0.0,
                    roll=float(roll) if not np.isnan(roll) else 0.0,
                    direction=direction, passes_entry=passes,
                    abs_z=abs(float(z)),
                ))

        if signals:
            signal_table[dt_ts] = signals

    return signal_table


def _multi_tag(sig: MultiSignal) -> str:
    return f"sfr_{sig.structure_name}_{sig.instrument_id.replace('/', '_')}"


def _make_multi_query(sig: MultiSignal, config: dict) -> List[QueryOrder]:
    """Build query orders for any structure type.

    FLY: 3 legs via IRSwapStructure.FLY
    CURVE: 2 legs via IRSwapStructure.CURVE
    DFLY: 2 overlapping flies (fly[i] + opposite fly[i+gap])
    """
    curve = config.get('curve', 'USD-SOFR-1D-Q12STIRT')
    bpv = config.get('belly_bpv', 100_000)
    parts = sig.instrument_id.split("/")
    tag = _multi_tag(sig)

    if sig.query_type == 'FLY' and len(parts) == 3:
        front = trg._sfr_to_imm_tenor(parts[0])
        belly = trg._sfr_to_imm_tenor(parts[1])
        back = trg._sfr_to_imm_tenor(parts[2])
        dir_sign = float(sig.direction)
        q = IRSwapQuery(
            structure=IRSwapStructure.FLY, curve=curve,
            structure_kwargs={"front_tenor": front, "belly_tenor": belly, "back_tenor": back,
                              "bpv": dir_sign * bpv},
            tags=[tag],
        )
        return [q]

    elif sig.query_type == 'CURVE' and len(parts) == 2:
        front = trg._sfr_to_imm_tenor(parts[0])
        back = trg._sfr_to_imm_tenor(parts[1])
        dir_sign = float(sig.direction)
        q = IRSwapQuery(
            structure=IRSwapStructure.CURVE, curve=curve,
            structure_kwargs={"front_tenor": front, "back_tenor": back,
                              "bpv": dir_sign * bpv},
            tags=[tag],
        )
        return [q]

    elif sig.query_type == 'DFLY':
        # DFly label: "SFR1/SFR2/SFR3|SFR2/SFR3/SFR4"
        fly_parts = sig.instrument_id.split("|")
        if len(fly_parts) != 2:
            return []
        queries = []
        for i, fp in enumerate(fly_parts):
            legs = fp.split("/")
            if len(legs) != 3:
                continue
            front = trg._sfr_to_imm_tenor(legs[0])
            belly = trg._sfr_to_imm_tenor(legs[1])
            back = trg._sfr_to_imm_tenor(legs[2])
            # DFly = fly[0] - fly[1], so first fly has same sign, second opposite
            leg_sign = float(sig.direction) if i == 0 else float(-sig.direction)
            q = IRSwapQuery(
                structure=IRSwapStructure.FLY, curve=curve,
                structure_kwargs={"front_tenor": front, "belly_tenor": belly, "back_tenor": back,
                                  "bpv": leg_sign * bpv},
                tags=[tag, f"{tag}_leg{i}"],
            )
            queries.append(q)
        return queries

    return []


# ══════════════════════════════════════════════════════════════════
# TRIGGERS
# ══════════════════════════════════════════════════════════════════

def _match_dt(signal_table, state):
    """Find signals matching datetime (handles tz)."""
    ts = pd.Timestamp(state)
    for key, val in signal_table.items():
        if pd.Timestamp(key).date() == ts.date():
            return val
    return []


class _MultiEntryAction:
    risk = None
    def __call__(self, *, now, backtest, info):
        return info.get(_MultiEntryAction, [])


class _MultiExitAction:
    risk = None
    def __call__(self, *, now, backtest, info):
        return info.get(_MultiExitAction, [])


@dataclass
class _MultiEntryReqs(TriggerRequirements):
    signal_table: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    def has_triggered(self, state, backtest=None):
        signals = _match_dt(self.signal_table, state)
        passing = [s for s in signals if s.passes_entry]
        if not passing:
            return TriggerInfo(False)

        # Sort by |z| descending
        passing.sort(key=lambda s: s.abs_z, reverse=True)

        # Filter duplicates already in portfolio
        if backtest:
            open_tags = set()
            for pos in backtest.portfolio.positions:
                open_tags.update((pos.meta or {}).get("tags", []))
            passing = [s for s in passing if _multi_tag(s) not in open_tags]

            slots = self.config.get('max_positions', 10) - len(backtest.portfolio.positions)
            if slots <= 0:
                return TriggerInfo(False)
            passing = passing[:slots]

        if not passing:
            return TriggerInfo(False)

        orders = []
        for s in passing:
            try:
                queries = _make_multi_query(s, self.config)
                for q in queries:
                    orders.append(QueryOrder(
                        timestamp=state, query=q,
                        meta={"action": "multi_entry", "tags": [_multi_tag(s)],
                              "structure": s.structure_name, "direction": s.direction,
                              "entry_zscore": s.zscore, "entry_level": s.level},
                    ))
            except Exception:
                pass

        if not orders:
            return TriggerInfo(False)
        return TriggerInfo(True, {_MultiEntryAction: orders})


@dataclass
class _MultiExitReqs(TriggerRequirements):
    signal_table: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    def has_triggered(self, state, backtest=None):
        if not backtest or not backtest.portfolio.positions:
            return TriggerInfo(False)

        ts = pd.Timestamp(state)
        signals = _match_dt(self.signal_table, state)
        sig_by_tag = {}
        for s in signals:
            sig_by_tag[_multi_tag(s)] = s

        unwinds = []
        seen_tags = set()  # avoid duplicate unwinds for dfly legs

        for pos in backtest.portfolio.positions:
            tags = set((pos.meta or {}).get("tags", []))
            # Find the primary tag (sfr_fly_3m_... or sfr_spd_... etc)
            primary = [t for t in tags if t.startswith("sfr_") and "_leg" not in t]
            if not primary:
                continue
            tag = primary[0]
            if tag in seen_tags:
                continue

            entry_meta = pos.meta or {}
            exit_reason = None

            if tag in sig_by_tag:
                sig = sig_by_tag[tag]
                entry_z = entry_meta.get("entry_zscore", 0)
                direction = entry_meta.get("direction", sig.direction)
                current_z = sig.zscore

                # Mean reversion
                if self.config.get("exit_mean_reversion"):
                    if direction == 1 and current_z >= 0:
                        exit_reason = "mean_reversion"
                    elif direction == -1 and current_z <= 0:
                        exit_reason = "mean_reversion"

                # Stop loss
                stop_sd = self.config.get("exit_stop_loss_sd")
                if not exit_reason and stop_sd:
                    if abs(current_z) - abs(entry_z) > stop_sd:
                        exit_reason = "stop_zscore"

            # Max holding
            if not exit_reason and hasattr(pos, "opened"):
                max_hold = self.config.get("exit_max_holding_days", 66)
                if max_hold:
                    days = (ts - pd.Timestamp(pos.opened)).days
                    if days >= max_hold:
                        exit_reason = "max_holding"

            if exit_reason:
                seen_tags.add(tag)
                _t = tag
                unwinds.append(UnwindOrder(
                    timestamp=state,
                    selector=lambda p, _tag=_t: _tag in set((p.meta or {}).get("tags", [])),
                    meta={"action": "multi_exit", "reason": exit_reason},
                ))

        if not unwinds:
            return TriggerInfo(False)
        return TriggerInfo(True, {_MultiExitAction: unwinds})


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def main():
    C = CONFIG
    print("=" * 100)
    print("EVENT-DRIVEN MULTI-STRUCTURE BACKTEST")
    print(f"Structures: {list(C['structures'].keys())}")
    print(f"Z>{C['entry_min_zscore']} | {C['zscore_window']}d window | carry ON | rebalance {C['rebalance_freq']} | no regime filters")
    print("=" * 100)

    sfr_cfg = rv.SFRCalSpreadRVConfig(
        n_contracts=C['n_contracts'], zscore_window=C['zscore_window'],
        vol_window=C['vol_window'], constant_maturity=C['constant_maturity'],
        roll_adjusted=C['roll_adjusted'],
    )
    mdp = IRSwapsMDP(source=C['source'])
    start = NYC.localize(datetime.datetime.fromisoformat(C['data_start']).replace(hour=18))

    print("\nLoading rates...")
    rates = rv.load_rate_panel(sfr_cfg, start=start, end=C['bt_end'],
                                curve_mdp=mdp, ts_builder=TimeseriesBuilder())
    print(f"  {rates.shape[0]} dates x {rates.shape[1]} contracts")

    # Compute all structures
    all_ts, all_zs, all_vo, all_ro = {}, {}, {}, {}
    for sname, spec in C['structures'].items():
        fn = spec['fn']
        gap = spec['gap']
        if fn == 'fly':
            ts = rv.compute_fly_curve(rates, gap=gap)
        elif fn == 'dfly':
            ts = rv.compute_dfly_curve(rates, gap=gap)
        elif fn == 'spread':
            ts = rv.compute_spread_curve(rates, gap=gap)
        else:
            continue

        zs = rv.compute_zscore_ts(ts, window=C['zscore_window'])
        vo = ts.diff().rolling(C['vol_window'], min_periods=10).std() * np.sqrt(252)
        ro = pd.DataFrame(np.nan, index=ts.index, columns=ts.columns)
        for i in range(len(ts)):
            row = ts.iloc[i]
            for j in range(1, len(ts.columns)):
                ro.iloc[i, j] = row.iloc[j - 1] - row.iloc[j]

        all_ts[sname] = ts; all_zs[sname] = zs; all_vo[sname] = vo; all_ro[sname] = ro
        print(f"  {sname:12s}: {ts.shape[1]} instruments")

    # Build signal table
    print("\nBuilding signal table...")
    sig_table = build_multi_signal_table(all_ts, all_zs, all_vo, all_ro, C)
    rebal_count = sum(1 for sigs in sig_table.values() if any(s.passes_entry for s in sigs))
    print(f"  {len(sig_table)} dates with signals, {rebal_count} with passing entries")

    # Time grid
    bt_start_dt = NYC.localize(datetime.datetime.fromisoformat(C['bt_start']).replace(hour=17))
    bt_end_dt = NYC.localize(datetime.datetime.now()) if C['bt_end'] == 'live' else \
                NYC.localize(datetime.datetime.fromisoformat(C['bt_end']).replace(hour=17))
    bt_dates = pd.bdate_range(bt_start_dt, bt_end_dt, tz=NYC)
    bt_datetimes = [d.to_pydatetime() for d in bt_dates]
    print(f"  BT: {bt_start_dt.date()} to {bt_end_dt.date()} ({len(bt_datetimes)} steps)")

    # Wire triggers
    entry_trigger = Trigger(
        trigger_requirements=_MultiEntryReqs(signal_table=sig_table, config=C),
        actions=[_MultiEntryAction()],
    )
    exit_trigger = Trigger(
        trigger_requirements=_MultiExitReqs(signal_table=sig_table, config=C),
        actions=[_MultiExitAction()],
    )
    strategy = QueryStrategy(name="multi_struct", triggers=[entry_trigger, exit_trigger], default_mdp=mdp)

    # Run
    print("\nRunning backtest...")
    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(bt_datetimes),
        strategy=strategy,
        mdp=mdp,
        show_progress=True,
    )
    bt.run()

    # Results
    mtm = pd.Series(bt.mtm_history).sort_index()
    daily = mtm.diff().dropna()
    s = daily.std()
    dd = mtm - mtm.cummax()

    print(f"\n{'='*100}")
    print(f"RESULTS")
    print(f"{'='*100}")
    print(f"  Period:         {bt_start_dt.date()} to {bt_end_dt.date()}")
    print(f"  Entries:        {len(bt.portfolio.trades_log)}")
    print(f"  Open:           {len(bt.portfolio.positions)}")
    print(f"  Final MTM:      ${mtm.iloc[-1]:+,.0f}" if len(mtm) else "  MTM: N/A")
    print(f"  Realized:       ${bt.realized_pnl:+,.0f}")
    print(f"  Sharpe:         {daily.mean()/s*np.sqrt(252):.2f}" if s > 0 else "  Sharpe: N/A")
    print(f"  Max DD:         ${dd.min():+,.0f}")
    print(f"  Daily Hit Rate: {(daily>0).mean():.1%}")

    # Unwind reasons
    if hasattr(bt.portfolio, 'unwind_log') and bt.portfolio.unwind_log:
        print(f"\n--- Exit Reasons ---")
        reasons = {}
        for u in bt.portfolio.unwind_log:
            r = (u.meta or {}).get("reason", "unknown")
            reasons[r] = reasons.get(r, 0) + 1
        for r, c in sorted(reasons.items()):
            print(f"  {r:20s} {c}")

    # Yearly
    if len(daily) > 0:
        print(f"\n--- Yearly ---")
        print(f"  {'Year':>6s} {'P&L ($)':>12s} {'Sharpe':>8s} {'HR':>6s} {'Max DD ($)':>12s}")
        for yr, grp in daily.groupby(daily.index.year):
            gs = grp.std()
            sharpe = grp.mean() / gs * np.sqrt(252) if gs > 0 else 0
            cum = grp.cumsum()
            ydd = (cum - cum.cummax()).min()
            print(f"  {yr:6d} {grp.sum():+12,.0f} {sharpe:+8.2f} {(grp>0).mean():6.1%} {ydd:+12,.0f}")

    # By structure
    if bt.portfolio.trades_log:
        print(f"\n--- Entries by Structure ---")
        struct_counts = {}
        for o in bt.portfolio.trades_log:
            sn = (o.meta or {}).get("structure", "unknown")
            struct_counts[sn] = struct_counts.get(sn, 0) + 1
        for sn, c in sorted(struct_counts.items()):
            print(f"  {sn:12s} {c}")

    # Realized P&L timeline (major events)
    if bt.realized_pnl_history:
        rpnl = pd.Series(bt.realized_pnl_history).sort_index()
        changes = rpnl.diff().dropna()
        big = changes[changes.abs() > 50_000]
        if len(big) > 0:
            print(f"\n--- Major P&L Events (|change| > $50k) ---")
            for dt_idx, chg in big.items():
                print(f"  {str(dt_idx)[:10]}: {chg:+,.0f}  (cum: {rpnl[dt_idx]:+,.0f})")


if __name__ == "__main__":
    main()
