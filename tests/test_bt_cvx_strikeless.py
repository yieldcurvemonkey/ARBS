r"""Tests for ``BT/signals/cvx_strikeless.py`` — strat3 tape replay through QDB.

Pure-logic tests drive the REAL QueryDrivenBacktest loop with two fakes:

* the conftest ``MockMDP``/``MockPricer`` for structural wiring (they are the
  house mocks; note their ``resolve_pricable`` MUTATES notional in place and
  double-applies direction, so no economic number is asserted through them);
* a leg-leveled ``FakeMDP`` whose ``resolve_pricable`` mirrors the REAL
  ``RLIRSwapCurve`` semantics (copy, ``abs(notional) * sign(risk_weight)``,
  frozen strike) so engine equity is hand-computable to the dollar — the
  planted answer for the replay test.

Every planted answer has a negative control; load-bearing asserts carry
MUTATION notes naming the defect they kill.
"""

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import copy
import dataclasses
import datetime as dt
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from BT.signals.cvx_strikeless import (
    CurveMapMDP,
    CvxStrikelessConfig,
    CvxStrikelessResult,
    assert_ran,
    build_backtest,
    build_curve_map,
    certify,
    check_probe,
    fee_events,
    run_reference,
    sign_probe,
    strat3_unit_ledger,
    validate_tape,
)

DV01 = 100_000.0


# ---------------------------------------------------------------------------
# Fakes with REAL resolve_pricable semantics (abs * sign, copy, frozen strike)
# ---------------------------------------------------------------------------


class FakeSwap:
    __slots__ = ("key", "strike_bp", "notional")

    def __init__(self, key, strike_bp, notional):
        self.key, self.strike_bp, self.notional = key, float(strike_bp), float(notional)


class FakeCurvePricer:
    """Per-leg levels in bp keyed by (effective, maturity) or (fwd, tenor).

    npv = (level_today - frozen strike) * notional * 1e-4, so a leg built with
    ``bpv=x`` earns exactly ``x`` USD per bp of its own level — engine equity
    is a hand sum of ``bpv * (level_t - level_entry)``.
    """

    def __init__(self, as_of: dt.date, levels: dict, name: str = "USD-SOFR-1D"):
        self._as_of, self._levels, self._name = as_of, dict(levels), name

    def id(self):
        return self._name

    def handle(self):
        return self

    def reference_date(self):
        return self._as_of

    def meta(self):
        return {"from_curve_store": True}

    def _level(self, key):
        if key not in self._levels:
            raise KeyError(f"FakeCurvePricer {self._as_of}: no level for {key!r}")
        return float(self._levels[key])

    def build_irswap(self, fwd=None, tenor=None, effective_date=None,
                     maturity_date=None, fixed_rate=-0.00, notional=None, bpv=None):
        key = (effective_date, maturity_date) if effective_date is not None else (fwd, tenor)
        lvl = self._level(key)
        if notional is None:
            notional = (bpv / 1e-4) if bpv is not None else 1_000_000.0
        strike = lvl if (fixed_rate is None or fixed_rate == 0) else float(fixed_rate)
        return FakeSwap(key, strike, notional)

    def npv(self, s):
        return (self._level(s.key) - s.strike_bp) * s.notional * 1e-4

    def pv01(self, s):
        return s.notional * 1e-4

    def resolve_pricable(self, s, risk_weight=None):
        # REAL RLIRSwapCurve semantics: fresh object, |notional| signed by the
        # risk weight, strike FROZEN. (The conftest MockPricer instead mutates
        # `notional *= w` in place — the double-application rac_backtest warns
        # about — which is why the economic tests use this fake.)
        sign = -1.0 if (risk_weight is not None and float(risk_weight) < 0) else 1.0
        return FakeSwap(s.key, s.strike_bp, abs(s.notional) * sign)

    def effective_date(self, s):
        return s.key[0]

    def maturity_date(self, s):
        return s.key[1]

    def notional(self, s):
        return s.notional


class RegressedPricer(FakeCurvePricer):
    """The L-0012 regression twin: resolve_pricable drops the direction sign."""

    def resolve_pricable(self, s, risk_weight=None):
        return FakeSwap(s.key, s.strike_bp, abs(s.notional))


class FakeMDP:
    source = "FAKE"

    def __init__(self, levels_by_date: dict, pricer_cls=FakeCurvePricer):
        self._levels = {pd.Timestamp(k).date(): v for k, v in levels_by_date.items()}
        self._cls = pricer_cls

    def _lookup(self, timestamp):
        d = timestamp.date() if isinstance(timestamp, dt.datetime) else timestamp
        d = pd.Timestamp(d).date() if not isinstance(d, dt.date) else d
        return self._cls(d, self._levels[d])

    def get_pricer(self, request):
        return self._lookup(request["timestamp"])

    def _get_curve(self, *, curve_name=None, timestamp=None, **_):
        return self._lookup(timestamp)


# ---------------------------------------------------------------------------
# The tiny synthetic tape (two segments, hedges, hand-computable P&L)
# ---------------------------------------------------------------------------

GRID = [d.date() for d in pd.bdate_range("2025-01-06", periods=8)]
SA = (dt.date(2040, 1, 1), dt.date(2045, 1, 1))   # seg0 short leg dates
LA = (dt.date(2045, 1, 1), dt.date(2055, 1, 1))   # seg0 long leg dates
SB = (dt.date(2041, 1, 1), dt.date(2046, 1, 1))   # seg1 short leg dates
LB = (dt.date(2046, 1, 1), dt.date(2056, 1, 1))   # seg1 long leg dates
PROBE_KEYS = {("15Y", "5Y"): 300.0, ("20Y", "10Y"): 320.0}


def _levels_by_date():
    out = {}
    for i, d in enumerate(GRID):
        out[d] = {
            SA: 100.0 + 1.0 * i,
            LA: 200.0 + 2.0 * i,
            SB: 150.0 - 1.0 * i,
            LB: 250.0 + 3.0 * i,
            **PROBE_KEYS,
        }
    return out


def _tiny_tape() -> pd.DataFrame:
    rows = [
        # segment 0: initiate at d0, hedge at d2, unwind at d4
        dict(segment=0, date=GRID[0], kind="initiate", leg="short", bpv=+DV01, effective=SA[0], maturity=SA[1]),
        dict(segment=0, date=GRID[0], kind="initiate", leg="long", bpv=-DV01, effective=LA[0], maturity=LA[1]),
        dict(segment=0, date=GRID[2], kind="hedge", leg="long", bpv=+20_000.0, effective=LA[0], maturity=LA[1]),
        dict(segment=0, date=GRID[4], kind="unwind", leg="both", bpv=np.nan, effective=None, maturity=None),
        # segment 1: roll at d4 (shared date), hedge at d6, unwind at d7
        dict(segment=1, date=GRID[4], kind="roll", leg="short", bpv=+DV01, effective=SB[0], maturity=SB[1]),
        dict(segment=1, date=GRID[4], kind="roll", leg="long", bpv=-DV01, effective=LB[0], maturity=LB[1]),
        dict(segment=1, date=GRID[6], kind="hedge", leg="long", bpv=-10_000.0, effective=LB[0], maturity=LB[1]),
        dict(segment=1, date=GRID[7], kind="unwind", leg="both", bpv=np.nan, effective=None, maturity=None),
    ]
    return pd.DataFrame(rows)


#: Hand-computed GROSS cumulative equity (USD) per grid day: sum over open/closed
#: positions of bpv * (level_t - level_entry), fees excluded.
EXPECTED_GROSS = [0.0, -100_000.0, -200_000.0, -260_000.0, -320_000.0,
                  -720_000.0, -1_120_000.0, -1_550_000.0]

#: Figure-9 tight tier for the default pair at multiplier 1: initiate 0.75bp,
#: hedge/roll 0.30bp per $100k DV01. Segment 0's unwind carries the initiation,
#: the roll opening segment 1 (same date), and its own hedge; segment 1's
#: carries only its hedge (no terminal exit in the strat3 schedule).
FEE_SEG0 = 0.75 * DV01 + 0.30 * DV01 + 0.30 * 20_000.0   # 75k + 30k + 6k = 111k
FEE_SEG1 = 0.30 * 10_000.0                               # 3k


@pytest.fixture
def cfg():
    return CvxStrikelessConfig()


@pytest.fixture
def fake_mdp():
    return FakeMDP(_levels_by_date())


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_frozen_and_validated(self):
        c = CvxStrikelessConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.short_leg = "10Yx10Y"
        with pytest.raises(ValueError):
            CvxStrikelessConfig(package_dv01_usd=0.0)
        with pytest.raises(ValueError):
            CvxStrikelessConfig(roll_months=0)
        with pytest.raises(ValueError):
            CvxStrikelessConfig(start=dt.date(2024, 1, 2), end=dt.date(2023, 1, 2))

    def test_maps_to_strat3(self):
        c = CvxStrikelessConfig(hedge_threshold_bp=30.0, roll_months=6,
                                start=dt.date(2023, 1, 2), end=dt.date(2024, 12, 31))
        s3 = c.to_strat3()
        assert s3.short_leg == "15Yx5Y" and s3.long_leg == "20Yx10Y"
        assert s3.hedge_threshold_bp == 30.0 and s3.roll_months == 6
        # MUTATION: entry_rule anything but "always" gates the reference tape.
        assert s3.entry_rule == "always"
        assert s3.start == dt.date(2023, 1, 2) and s3.end == dt.date(2024, 12, 31)

    def test_fee_curve_fig9_and_override(self):
        # published tight pair
        cs = CvxStrikelessConfig().cost_schedule()
        assert (cs.initiate_bp, cs.hedge_bp, cs.roll_bp) == (0.75, 0.30, 0.30)
        # unpublished pair -> conservative wide tier
        cs2 = CvxStrikelessConfig(short_leg="15Yx10Y", long_leg="25Yx5Y").cost_schedule()
        assert (cs2.initiate_bp, cs2.hedge_bp) == (1.00, 0.40)
        # multiplier flows into the schedule
        assert CvxStrikelessConfig(cost_multiplier=2.0).cost_schedule().multiplier == 2.0
        # explicit schedule wins
        from RVUtils.StrikelessVol.costs import CostSchedule

        own = CostSchedule(initiate_bp=0.1, hedge_bp=0.1, roll_bp=0.1)
        assert CvxStrikelessConfig(costs=own).cost_schedule() is own


# ---------------------------------------------------------------------------
# Tape validation
# ---------------------------------------------------------------------------


class TestValidateTape:
    def test_good_tape_passes(self):
        validate_tape(_tiny_tape())

    def test_rejects_timestamp_dates(self):
        # MUTATION: a validator using bare isinstance(d, datetime.date) waves a
        # pd.Timestamp through (Timestamp c datetime c date) and the trigger
        # becomes the silent zero-mark no-op. The WHOLE column is planted as
        # Timestamps — a single mixed cell would make pandas raise TypeError
        # incidentally in the segment max() comparison and mask a broken guard
        # (measured: the bare-isinstance mutant survived the mixed-cell form).
        tape = _tiny_tape()
        tape["date"] = [pd.Timestamp(d) for d in tape["date"]]
        with pytest.raises(TypeError, match="SILENT|no-op"):
            validate_tape(tape)

    def test_rejects_timestamp_leg_dates(self):
        tape = _tiny_tape()
        tape.loc[1, "effective"] = pd.Timestamp(LA[0])
        with pytest.raises(TypeError, match="effective"):
            validate_tape(tape)

    def test_rejects_bad_bpv_and_kinds(self):
        tape = _tiny_tape()
        tape.loc[2, "bpv"] = np.nan
        with pytest.raises(ValueError, match="bpv"):
            validate_tape(tape)
        tape2 = _tiny_tape()
        tape2.loc[2, "kind"] = "resize"
        with pytest.raises(ValueError, match="unknown kinds"):
            validate_tape(tape2)

    def test_rejects_missing_or_double_unwind(self):
        tape = _tiny_tape().drop(index=[3])
        with pytest.raises(ValueError, match="unwind"):
            validate_tape(tape)
        # unwind rows are EXEMPT from the bpv/date checks (NaN/None is their contract)
        good = _tiny_tape()
        assert good.loc[3, "effective"] is None and pd.isna(good.loc[3, "bpv"])
        validate_tape(good)

    def test_rejects_roll_labelled_initiate(self):
        tape = _tiny_tape()
        tape.loc[4, "kind"] = "initiate"
        tape.loc[5, "kind"] = "initiate"
        with pytest.raises(ValueError, match="roll"):
            validate_tape(tape)


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------


class TestFees:
    def test_fee_placement_exact_dollars(self, cfg):
        fees = fee_events(_tiny_tape(), cfg)
        # MUTATION: swapping initiate/roll/hedge rates, charging per leg row,
        # scaling openings by beta, or adding a terminal exit all move these
        # exact dollar pins.
        assert fees.index.tolist() == [GRID[4], GRID[7]]
        assert fees.loc[GRID[4]] == pytest.approx(FEE_SEG0)          # 75k + 30k + 6k
        assert fees.loc[GRID[7]] == pytest.approx(FEE_SEG1)          # 3k, no terminal exit
        # total == 1x initiate + (S-1)x roll + sum hedge, the strat3 schedule
        assert fees.sum() == pytest.approx(0.75 * DV01 + 0.30 * DV01 + 0.30 * 30_000.0)

    def test_fee_multiplier_scales(self):
        c2 = CvxStrikelessConfig(cost_multiplier=2.0)
        assert fee_events(_tiny_tape(), c2).sum() == pytest.approx(2.0 * (FEE_SEG0 + FEE_SEG1))


# ---------------------------------------------------------------------------
# Trigger construction (structural, on the conftest mocks)
# ---------------------------------------------------------------------------


def _date_triggers(bt):
    from BT.triggers import DateTriggerRequirements

    out = []
    for tr in bt.strategy.triggers:
        req = tr.trigger_requirements
        assert isinstance(req, DateTriggerRequirements)
        out.append((tr, req))
    return out


class TestTriggerConstruction:
    def test_trigger_dates_are_plain_datetime_date(self, cfg, mock_mdp):
        bt = build_backtest(_tiny_tape(), mock_mdp, cfg=cfg, grid_dates=GRID)
        for _, req in _date_triggers(bt):
            for d in req.dates:
                # MUTATION: building triggers with pd.Timestamp(d) passes a bare
                # isinstance check and every mark is silently zero; the exact
                # type check here and the analytic-equity test both kill it.
                assert type(d) is dt.date, f"trigger date {d!r} is {type(d).__name__}"

    def test_per_segment_tags_unique_and_matched(self, cfg, mock_mdp):
        from BT.query_actions import AddQueryAction, UnwindPositionsAction

        bt = build_backtest(_tiny_tape(), mock_mdp, cfg=cfg, grid_dates=GRID)
        add_tags, unwind_tags = set(), []
        for tr, _ in _date_triggers(bt):
            for a in tr.actions:
                if isinstance(a, AddQueryAction):
                    (tag,) = a.query.tags
                    add_tags.add(tag)
                    assert a.meta["tags"] == [tag]
                elif isinstance(a, UnwindPositionsAction):
                    unwind_tags.append(a.match_tag)
        # MUTATION: a shared tag across segments makes the roll-date unwind close
        # the package the roll just opened (entries fill BEFORE unwinds).
        assert add_tags == {"s0", "s1"}
        assert sorted(unwind_tags) == ["s0", "s1"]

    def test_queries_carry_explicit_dates_and_offline(self, cfg, mock_mdp):
        from BT.query_actions import AddQueryAction
        from Query.IRSwaps.IRSwapStructure import IRSwapStructure

        tape = _tiny_tape()
        bt = build_backtest(tape, mock_mdp, cfg=cfg, grid_dates=GRID)
        events = tape[tape["kind"] != "unwind"].reset_index(drop=True)
        seen = []
        for tr, _ in _date_triggers(bt):
            for a in tr.actions:
                if isinstance(a, AddQueryAction):
                    q = a.query
                    assert q.structure == IRSwapStructure.OUTRIGHT
                    # MUTATION: a relative tenor here re-resolves at every mark
                    # to a fresh at-market package (NPV~0 forever, flat equity).
                    assert q.tenor is None
                    assert type(q.effective_date) is dt.date
                    assert type(q.maturity_date) is dt.date
                    # DESIGN 1: curve requests carry offline
                    assert q.market_request.get("offline") is True
                    seen.append((q.effective_date, q.maturity_date, q.structure_kwargs["bpv"]))
        want = [(r["effective"], r["maturity"], float(r["bpv"])) for _, r in events.iterrows()]
        assert sorted(map(repr, seen)) == sorted(map(repr, want))

    def test_off_grid_tape_date_refused(self, cfg, mock_mdp):
        with pytest.raises(ValueError, match="not in the time grid"):
            build_backtest(_tiny_tape(), mock_mdp, cfg=cfg, grid_dates=GRID[:4])

    def test_mock_mdp_smoke_run_closes_every_event(self, cfg, mock_mdp):
        """The conftest mocks drive the full engine loop end to end.

        No economic assertion here (MockPricer.resolve_pricable double-applies
        direction by design); coverage and closed-count only.
        """
        tape = _tiny_tape()
        bt = build_backtest(tape, mock_mdp, cfg=cfg, grid_dates=GRID)
        bt.run()
        assert len(bt.mtm_history) == len(GRID)
        assert len(bt.portfolio.closed_positions_log) == int((tape["kind"] != "unwind").sum())


# ---------------------------------------------------------------------------
# The engine replay against the planted analytic answer
# ---------------------------------------------------------------------------


class TestEngineReplay:
    def _run(self, cfg, fake_mdp):
        tape = _tiny_tape()
        bt = build_backtest(tape, fake_mdp, cfg=cfg, grid_dates=GRID)
        bt.run()
        assert_ran(bt, expect_days=len(GRID),
                   expect_closed=int((tape["kind"] != "unwind").sum()))
        equity = pd.Series({ts.date(): float(v) for ts, v in bt.mtm_history.items()}).sort_index()
        fees = fee_events(tape, cfg)
        gross = equity + fees.reindex(equity.index).fillna(0.0).cumsum()
        return bt, tape, equity, gross, fees

    def test_gross_equity_matches_hand_computation(self, cfg, fake_mdp):
        _, _, equity, gross, fees = self._run(cfg, fake_mdp)
        # MUTATION KILLS: pd.Timestamp trigger dates (all marks zero), bpv sign
        # flips, wrong leg dates, shared tags (seg1 closed at the roll date),
        # fee placed on the wrong unwind (net path shifts), hedge rows dropped.
        assert equity.index.tolist() == GRID
        np.testing.assert_allclose(gross.to_numpy(), EXPECTED_GROSS, rtol=1e-9, atol=1e-6)
        # net = gross - cumulative fees, fees exactly at the two unwind dates
        np.testing.assert_allclose(
            equity.to_numpy(),
            np.asarray(EXPECTED_GROSS) - fees.reindex(equity.index).fillna(0.0).cumsum().to_numpy(),
            rtol=1e-9, atol=1e-6,
        )

    def test_timestamp_triggers_are_silent_noop_and_battery_catches(self, cfg, fake_mdp):
        """Negative control for the planted answer: the documented trap, live."""
        from BT.data_handler import TimeGrid
        from BT.query_engine import QueryDrivenBacktest
        from BT.query_strategy import QueryStrategy
        from BT.triggers import DateTrigger, DateTriggerRequirements

        tape = _tiny_tape()
        good = build_backtest(tape, fake_mdp, cfg=cfg, grid_dates=GRID)
        bad_triggers = [
            DateTrigger(
                DateTriggerRequirements(dates=[pd.Timestamp(d) for d in tr.trigger_requirements.dates]),
                actions=tr.actions,
            )
            for tr in good.strategy.triggers
        ]
        bt = QueryDrivenBacktest(
            time_grid=TimeGrid([pd.Timestamp(d) for d in GRID]),
            strategy=QueryStrategy(name="mutant", triggers=bad_triggers),
            mdp=fake_mdp,
            show_progress=False,
        )
        bt.run()
        # the run "succeeds": full coverage, no holes, zero everywhere
        assert len(bt.mtm_history) == len(GRID)
        assert all(v == 0.0 for v in bt.mtm_history.values())
        assert len(bt.portfolio.closed_positions_log) == 0
        with pytest.raises(AssertionError, match="pd.Timestamp"):
            assert_ran(bt, expect_days=len(GRID), expect_closed=6)


class TestAssertRan:
    def _bt(self, marks, n_closed):
        return SimpleNamespace(
            mtm_history=dict(marks),
            portfolio=SimpleNamespace(closed_positions_log=[{}] * n_closed),
        )

    def test_battery(self):
        ts = [pd.Timestamp(d) for d in GRID[:3]]
        ok = self._bt({t: v for t, v in zip(ts, [0.0, 5.0, -3.0])}, 2)
        assert_ran(ok, expect_days=3, expect_closed=2)
        with pytest.raises(AssertionError, match="empty"):
            assert_ran(self._bt({}, 0), expect_days=3, expect_closed=2)
        # MUTATION: dropping the coverage check hides swallowed steps (run()
        # prints exceptions and keeps going).
        with pytest.raises(AssertionError, match="marks"):
            assert_ran(self._bt({ts[0]: 1.0}, 2), expect_days=3, expect_closed=2)
        with pytest.raises(AssertionError, match="non-finite"):
            assert_ran(self._bt({ts[0]: np.nan, ts[1]: 1.0, ts[2]: 1.0}, 2),
                       expect_days=3, expect_closed=2)
        with pytest.raises(AssertionError, match="identically zero"):
            assert_ran(self._bt({t: 0.0 for t in ts}, 0), expect_days=3, expect_closed=2)
        with pytest.raises(AssertionError, match="closed"):
            assert_ran(self._bt({t: v for t, v in zip(ts, [0.0, 5.0, -3.0])}, 1),
                       expect_days=3, expect_closed=2)


# ---------------------------------------------------------------------------
# Sign probe
# ---------------------------------------------------------------------------


class TestSignProbe:
    def test_good_seam_passes(self, fake_mdp):
        probe = sign_probe(fake_mdp, GRID[0], package_dv01_usd=DV01)
        assert probe["is_flattener"] is True
        assert probe["mirror_ok"] is True
        assert probe["front_pv01"] == pytest.approx(+DV01)
        assert probe["back_pv01"] == pytest.approx(-DV01)
        assert abs(probe["sum"]) < 1e-6 * DV01
        check_probe(probe)  # no raise

    def test_regressed_seam_fails(self):
        # MUTATION: the L-0012 abs() regression prices +bpv and -bpv as the
        # identical all-payer package; the probe must refuse, loudly.
        mdp = FakeMDP(_levels_by_date(), pricer_cls=RegressedPricer)
        probe = sign_probe(mdp, GRID[0], package_dv01_usd=DV01)
        assert probe["is_flattener"] is False
        assert probe["mirror_ok"] is False
        with pytest.raises(RuntimeError, match="L-0012"):
            check_probe(probe)

    def test_check_probe_mirror_branch_is_independent(self):
        # MUTATION: dropping check_probe's mirror branch alone (is_flattener
        # still true) must still refuse — the two failures are separable.
        with pytest.raises(RuntimeError, match="mirror"):
            check_probe({"is_flattener": True, "mirror_ok": False, "mirror": {}})


# ---------------------------------------------------------------------------
# certify
# ---------------------------------------------------------------------------


def _result_from(cfg, fake_mdp) -> CvxStrikelessResult:
    tape = _tiny_tape()
    bt = build_backtest(tape, fake_mdp, cfg=cfg, grid_dates=GRID)
    bt.run()
    equity = pd.Series({ts.date(): float(v) for ts, v in bt.mtm_history.items()}).sort_index()
    fees = fee_events(tape, cfg)
    gross = equity + fees.reindex(equity.index).fillna(0.0).cumsum()
    return CvxStrikelessResult(
        config=cfg, tape=tape, equity=equity, equity_gross=gross, fees=fees,
        closed_positions=pd.DataFrame(list(bt.portfolio.closed_positions_log)),
        probe={}, backtest=bt, n_segments=2, n_hedges=2, n_rolls=1,
    )


def _ledger_like(daily: pd.Series, n_hedges=2, n_rolls=1) -> pd.DataFrame:
    led = pd.DataFrame(index=pd.DatetimeIndex([pd.Timestamp(d) for d in daily.index]))
    led["carry"] = 0.0
    led["harvest"] = 0.0
    led["mtm"] = daily.to_numpy()
    led["cross"] = 0.0
    led["n_hedges"] = 0
    led["n_rolls"] = 0
    led.iloc[2, led.columns.get_loc("n_hedges")] = 1
    led.iloc[-2, led.columns.get_loc("n_hedges")] = 1
    led.iloc[4, led.columns.get_loc("n_rolls")] = n_rolls
    return led


class TestCertify:
    def test_planted_pass_and_terminal_gap(self, cfg, fake_mdp):
        res = _result_from(cfg, fake_mdp)
        daily = res.equity_gross.diff()
        daily.iloc[0] = res.equity_gross.iloc[0]
        report = certify(res, _ledger_like(daily))
        # MUTATION: comparing NET equity, cumulative levels instead of dailies,
        # or a date-normalisation slip all break corr==1/gap==0 here.
        assert report["pass"] is True
        assert report["corr"] == pytest.approx(1.0)
        assert report["terminal_gap_usd"] == pytest.approx(0.0, abs=1e-6)
        assert report["n_common_days"] == len(GRID)

    def test_gap_is_stated_not_gated(self, cfg, fake_mdp):
        # A ledger scaled by 0.9 keeps corr == 1 (pass) but must STATE the gap.
        res = _result_from(cfg, fake_mdp)
        daily = res.equity_gross.diff()
        daily.iloc[0] = res.equity_gross.iloc[0]
        report = certify(res, _ledger_like(daily * 0.9))
        assert report["pass"] is True
        # gap = engine - 0.9*engine = 0.1 * engine terminal (= -155k here)
        assert report["terminal_gap_usd"] == pytest.approx(0.1 * EXPECTED_GROSS[-1])

    def test_negative_control_fails(self, cfg, fake_mdp):
        # MUTATION: a certify that ignores corr_min (or hardcodes pass=True)
        # dies here — the sign-flipped ledger anti-correlates exactly.
        res = _result_from(cfg, fake_mdp)
        daily = res.equity_gross.diff()
        daily.iloc[0] = res.equity_gross.iloc[0]
        report = certify(res, _ledger_like(-daily))
        assert report["corr"] == pytest.approx(-1.0)
        assert report["pass"] is False

    def test_refuses_empty_overlap(self, cfg, fake_mdp):
        res = _result_from(cfg, fake_mdp)
        other = pd.Series(1.0, index=[dt.date(2030, 1, i + 1) for i in range(5)])
        with pytest.raises(RuntimeError, match="common days"):
            certify(res, _ledger_like(other))

    def test_missing_bucket_is_loud(self, cfg, fake_mdp):
        res = _result_from(cfg, fake_mdp)
        daily = res.equity_gross.diff()
        daily.iloc[0] = res.equity_gross.iloc[0]
        with pytest.raises(KeyError, match="harvest"):
            certify(res, _ledger_like(daily).drop(columns=["harvest"]))


# ---------------------------------------------------------------------------
# build_curve_map guards + CurveMapMDP (stubbed MDP — no store access)
# ---------------------------------------------------------------------------


class _StubBulkMDP:
    def __init__(self, served):
        self.served = served
        self.requests = []

    def bulk_get_data(self, request):
        self.requests.append(dict(request))
        return dict(self.served)


class TestBuildCurveMap:
    def test_refuses_today_and_future(self):
        with pytest.raises(ValueError, match="live"):
            build_curve_map([dt.date.today()], mdp=_StubBulkMDP({}))
        with pytest.raises(ValueError, match="live"):
            build_curve_map([dt.date.today() + dt.timedelta(days=1)], mdp=_StubBulkMDP({}))

    def test_offline_flag_and_filters(self):
        d1, d2, d3 = GRID[0], GRID[1], GRID[2]
        levels = _levels_by_date()
        ok = FakeCurvePricer(d1, levels[d1])
        wrong_ref = FakeCurvePricer(d1, levels[d1])   # reference_date d1 but requested d3
        stub = _StubBulkMDP({d1: ok, d2: None, d3: wrong_ref})
        cm = build_curve_map([d1, d2, d3], mdp=stub)
        # MUTATION: dropping the reference-date match keeps d3 (a neighbouring-day
        # serve booked under the wrong label); dropping the offline flag lets a
        # store miss reach the live wire on a real MDP.
        assert list(cm) == [d1]
        assert stub.requests[0]["offline"] is True

    def test_non_store_backed_pricer_raises(self):
        class NotStore(FakeCurvePricer):
            def meta(self):
                return {}

        d1 = GRID[0]
        stub = _StubBulkMDP({d1: NotStore(d1, _levels_by_date()[d1])})
        with pytest.raises(RuntimeError, match="store"):
            build_curve_map([d1], mdp=stub)

    def test_all_missing_is_loud(self):
        with pytest.raises(ValueError, match="no curve served"):
            build_curve_map([GRID[0]], mdp=_StubBulkMDP({GRID[0]: None}))


class TestCurveMapMDP:
    def test_lookup_and_miss(self):
        levels = _levels_by_date()
        cm = {d: FakeCurvePricer(d, levels[d]) for d in GRID[:3]}
        mdp = CurveMapMDP(cm)
        assert mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": GRID[1]}) is cm[GRID[1]]
        # datetime and Timestamp keys resolve to the same day
        assert mdp._get_curve(timestamp=pd.Timestamp(GRID[2])) is cm[GRID[2]]
        assert mdp.get_data({"timestamp": dt.datetime(2025, 1, 6, 17, 0)}) is cm[GRID[0]]
        with pytest.raises(KeyError, match="no curve for"):
            mdp.get_pricer({"timestamp": GRID[5]})
        with pytest.raises(ValueError, match="empty"):
            CurveMapMDP({})


# ---------------------------------------------------------------------------
# Integration: the 2023-2024 certification window (real curve store)
# ---------------------------------------------------------------------------

CERT_START, CERT_END = dt.date(2023, 1, 2), dt.date(2024, 12, 31)


def _real_curve_map(start, end):
    """Build the store-backed curve map or skip with the store's own reason.

    Skips ONLY on the specific store-absence signal (build_curve_map's
    ValueError); anything else — an import error, a contract break — re-raises.
    """
    days = [d.date() for d in pd.bdate_range(start, end)]
    try:
        return build_curve_map(days)
    except ValueError as exc:
        pytest.skip(f"offline curve store unavailable for {start}..{end}: {exc}")


@pytest.mark.integration
def test_sign_probe_on_real_store():
    cm = _real_curve_map(dt.date(2024, 6, 3), dt.date(2024, 6, 7))
    probe = sign_probe(CurveMapMDP(cm), sorted(cm)[0])
    assert probe["is_flattener"] is True, probe
    assert probe["mirror_ok"] is True, probe
    assert abs(probe["sum"]) < 1e-6 * DV01


@pytest.mark.integration
@pytest.mark.slow
def test_certification_2023_2024():
    """DESIGN 6 reference certification: 15Yx5Y/20Yx10Y, 25bp, roll 12m.

    The QDB replay of strat3's hedge tape must reproduce the strat3 unit
    ledger's daily gross P&L at corr >= 0.99 on the same curve_map, with the
    terminal gap stated. Hedge/roll counts must be EXACTLY equal — the tape and
    the ledger run the same simulate_strat3 on the same curves, so a mismatch
    is a divergence bug, not noise.
    """
    curve_map = _real_curve_map(CERT_START, CERT_END)
    cfg = CvxStrikelessConfig(start=CERT_START, end=CERT_END)
    result = run_reference(cfg, curve_map=curve_map)
    ledger = strat3_unit_ledger(curve_map, cfg)
    report = certify(result, ledger)

    print(
        f"\nCERTIFICATION {cfg.pair_name} {CERT_START}..{CERT_END}: "
        f"n_days={report['n_common_days']} corr={report['corr']:.6f} "
        f"terminal_gap={report['terminal_gap_usd']:+,.0f} USD "
        f"({report['terminal_gap_bp']:+.2f}bp) "
        f"engine_gross={report['engine_gross_usd']:+,.0f} "
        f"panel_gross={report['panel_gross_usd']:+,.0f} "
        f"mad={report['median_abs_daily_diff_bp']:.4f}bp "
        f"hedges eng/led={report['n_hedges_engine']}/{report['n_hedges_ledger']} "
        f"rolls eng/led={report['n_rolls_engine']}/{report['n_rolls_ledger']}",
        flush=True,
    )

    # MUTATION: same-code tie-out — a count mismatch means tape and ledger
    # priced different books and the corr below is meaningless.
    assert report["n_hedges_engine"] == report["n_hedges_ledger"]
    assert report["n_rolls_engine"] == report["n_rolls_ledger"]
    assert report["pass"], report

    # negative control: a scrambled ledger must NOT certify against the same run
    rng = np.random.default_rng(20260826)
    scrambled = ledger.copy()
    perm = rng.permutation(len(scrambled))
    scrambled[["carry", "harvest", "mtm", "cross"]] = (
        scrambled[["carry", "harvest", "mtm", "cross"]].to_numpy()[perm]
    )
    bad = certify(result, scrambled)
    assert not bad["pass"], f"scrambled ledger certified: corr={bad['corr']:.4f}"
