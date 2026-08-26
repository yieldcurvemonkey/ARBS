"""BT/signals/cvx_fly_dislocation.py — episodes, exits, QDB wiring, tiny real run.

Pure-logic tests plant a known answer in a synthetic (date, point) panel and
assert the exact episode list, with a negative control for every planted
answer; MUTATION notes mark the load-bearing asserts.

The QDB smoke rides the conftest MockMDP/MockPricer, subclassed with explicit
effective/maturity retention, an idempotent resolve_pricable (RL abs()+sign
semantics), and a date-varying leg scale that is CONVEX in the forward start:
a linear scale is annihilated by the fly's (-1,+2,-1) second difference
(reference note "fly sees the second difference") and would fake a dead book.

The @integration test runs ONE synthetic pay-belly episode over 10 business
days of 2026-07 against the offline curve store, self-skipping with the
failing day named when the store cannot serve it.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime

import numpy as np
import pandas as pd
import pytest

from tests.conftest import MockMDP, MockPricer

from BT.signals.cvx_fly_dislocation import (
    CURVE,
    REQUIRED_COLUMNS,
    FlyDislocationConfig,
    FlyEpisode,
    build_backtest,
    episodes_from_panel,
    run_backtest,
    sign_probe,
)

T = pd.Timestamp
POINT = "5y1y"
LEGS = dict(leg_front="4y1y", leg_belly="5y1y", leg_back="6y1y")
W = dict(w_front=-1.0, w_belly=2.0, w_back=-1.0)

#: All gates pass, point RICH (zs +3, both-rich agreement) -> pay belly.
GOOD = dict(zs=3.0, sign_agree=-1.0, tag="clean", edge_bp=2.0, **LEGS, **W)
#: No signal: |zs| < 2, disagreeing, no edge.
QUIET = dict(zs=1.0, sign_agree=0.0, tag="clean", edge_bp=0.0, **LEGS, **W)

D = list(pd.bdate_range("2025-06-02", periods=12))

CFG = FlyDislocationConfig(start=datetime.date(2025, 1, 1),
                           end=datetime.date(2025, 12, 31))


def make_panel(dates, points=(POINT,), default=QUIET, overrides=None, drop=()):
    rows = {(d, p): dict(default) for d in dates for p in points}
    for key, kv in (overrides or {}).items():
        rows[key].update(kv)
    for key in drop:
        rows.pop(key)
    idx = pd.MultiIndex.from_tuples(list(rows), names=["date", "point"])
    return pd.DataFrame([rows[k] for k in idx], index=idx)


def _zs_path(values, start_idx=2):
    """Overrides setting only zs on D[start_idx:].

    With the signal at D[0] the fill is D[1] (whose row the hold loop never
    reads), so the FIRST HELD-DAY mark is D[2] — the default start.
    """
    return {(D[start_idx + i], POINT): dict(zs=v) for i, v in enumerate(values)}


# ---------------------------------------------------------------------------
# Episode extraction
# ---------------------------------------------------------------------------
class TestEpisodes:
    def test_planted_pay_belly_episode(self):
        # Signal at D[0] (zs +3, rich) -> fill D[1], direction +1 (PAY the
        # belly = long local convexity); zs decays and crosses zero at D[3].
        panel = make_panel(D, overrides={(D[0], POINT): GOOD,
                                         **_zs_path([1.5, -0.5])})
        eps = episodes_from_panel(panel, CFG)
        assert eps == [FlyEpisode(POINT, D[1], D[3], +1, "4y1y", "5y1y", "6y1y",
                                  -1.0, 2.0, -1.0, 3.0, "target")]

    def test_receive_belly_polarity(self):
        # zs negative = CHEAP -> RECEIVE the belly (direction -1).
        # MUTATION: flipping the polarity (direction = -sign(zs)) fails both
        # this and the pay-belly test above.
        cheap = {**GOOD, "zs": -3.0, "sign_agree": 1.0}
        panel = make_panel(D, overrides={(D[0], POINT): cheap,
                                         **_zs_path([-1.5, 0.2])})
        eps = episodes_from_panel(panel, CFG)
        assert len(eps) == 1 and eps[0].direction == -1
        assert eps[0].entry_zs == -3.0 and eps[0].exit_reason == "target"

    @pytest.mark.parametrize("bad", [
        dict(zs=1.9),                 # below the two-sided |z| >= 2.0 gate
        dict(zs=np.nan),
        dict(sign_agree=0.0),         # disagreement refuses
        dict(sign_agree=np.nan),
        dict(sign_agree=0.5),         # not a legal {+1,-1} value
        dict(tag="convexity"),        # harvest-only zone, never faded
        dict(tag="meeting"),
        dict(tag=np.nan),
        dict(edge_bp=1.0),            # STRICT floor: == refuses
        dict(edge_bp=np.nan),
        dict(w_front=np.nan),         # cannot size (PCA ramp-in) -> refuse
        dict(leg_belly=np.nan),
        dict(leg_belly=""),
    ])
    def test_each_gate_violated_no_episode(self, bad):
        # Negative control for the planted answer. MUTATION: dropping any one
        # gate check in _entry_signal lets its variant here produce the
        # episode and fails this test.
        panel = make_panel(D, overrides={(D[0], POINT): {**GOOD, **bad}})
        assert episodes_from_panel(panel, CFG) == []

    def test_entry_z_boundary_inclusive(self):
        # |zs| == min_abs_z enters (books.py: dislocation is INCLUSIVE >=).
        # MUTATION: `<` -> `<=` in the refusal makes the boundary refuse.
        panel = make_panel(D, overrides={(D[0], POINT): {**GOOD, "zs": 2.0},
                                         **_zs_path([-0.5])})
        eps = episodes_from_panel(panel, CFG)
        assert len(eps) == 1 and eps[0].entry_zs == 2.0

    def test_lag1_same_day_fill_caught(self):
        # Signal row at D[1] -> fill at D[2], never D[1].
        # MUTATION: reading the fill-day row (drop the `i - 1`) enters at D[1].
        panel = make_panel(D, overrides={(D[1], POINT): GOOD,
                                         **_zs_path([-0.5], start_idx=3)})
        eps = episodes_from_panel(panel, CFG)
        assert len(eps) == 1
        assert eps[0].entry_date == D[2]
        # A signal on the LAST panel date has no fill day -> nothing.
        panel = make_panel(D, overrides={(D[-1], POINT): GOOD})
        assert episodes_from_panel(panel, CFG) == []

    def test_stop_exit_precedence_and_inclusive_boundary(self):
        # D[2]: zs -6.5 both crosses zero AND breaches the 2x stop (entry 3.0
        # -> stop at 6.0): precedence stop > target.
        # MUTATION: swapping the stop/target order labels this "target".
        panel = make_panel(D, overrides={(D[0], POINT): GOOD,
                                         **_zs_path([-6.5])})
        eps = episodes_from_panel(panel, CFG)
        assert eps == [FlyEpisode(POINT, D[1], D[2], +1, "4y1y", "5y1y", "6y1y",
                                  -1.0, 2.0, -1.0, 3.0, "stop")]
        # Same-sign stop exactly AT entry*mult fires (INCLUSIVE >=).
        # MUTATION: `>=` -> `>` misses the boundary and this exits "end".
        panel = make_panel(D, overrides={(D[0], POINT): GOOD,
                                         **_zs_path([6.0])})
        eps = episodes_from_panel(panel, CFG)
        assert len(eps) == 1 and eps[0].exit_reason == "stop" and eps[0].exit_date == D[2]

    def test_target_zero_cross_exact_zero(self):
        panel = make_panel(D, overrides={(D[0], POINT): GOOD,
                                         **_zs_path([2.5, 0.0])})
        eps = episodes_from_panel(panel, CFG)
        assert len(eps) == 1 and eps[0].exit_reason == "target" and eps[0].exit_date == D[3]

    def test_horizon_exit_counts_grid_days(self):
        cfg = FlyDislocationConfig(max_hold_bd=3, start=CFG.start, end=CFG.end)
        # zs steady at 2.9: no cross, below the 5.8 stop -> horizon at held==3.
        # MUTATION: `>=` -> `>` on the horizon exits one day late (D[5]).
        panel = make_panel(D, overrides={(D[0], POINT): GOOD,
                                         **_zs_path([2.9] * 8)})
        eps = episodes_from_panel(panel, cfg)
        assert len(eps) == 1 and eps[0].exit_reason == "horizon"
        assert eps[0].exit_date == D[4]                  # entry D[1] + 3 grid days

    def test_target_beats_horizon_same_day(self):
        cfg = FlyDislocationConfig(max_hold_bd=1, start=CFG.start, end=CFG.end)
        panel = make_panel(D, overrides={(D[0], POINT): GOOD,
                                         **_zs_path([-0.5])})
        eps = episodes_from_panel(panel, cfg)
        assert len(eps) == 1 and eps[0].exit_reason == "target"

    def test_end_of_panel_forced_exit(self):
        panel = make_panel(D, overrides={(D[0], POINT): GOOD,
                                         **_zs_path([2.9] * 10)})
        eps = episodes_from_panel(panel, CFG)
        assert len(eps) == 1 and eps[0].exit_reason == "end"
        assert eps[0].exit_date == D[-1]

    def test_one_position_per_point_and_reentry(self):
        # Persisting signal never stacks a second position; after the target
        # exit a fresh signal re-enters.
        panel = make_panel(D, overrides={
            (D[0], POINT): GOOD, (D[1], POINT): GOOD, (D[2], POINT): GOOD,
            (D[3], POINT): dict(zs=2.5), (D[4], POINT): dict(zs=-0.5),
            (D[5], POINT): GOOD,
            (D[7], POINT): dict(zs=-0.1)})
        eps = episodes_from_panel(panel, CFG)
        assert [(e.entry_date, e.exit_date, e.exit_reason) for e in eps] == [
            (D[1], D[4], "target"), (D[6], D[7], "target")]
        assert eps[0].exit_date <= eps[1].entry_date     # never overlapping

    def test_weights_and_legs_frozen_at_entry(self):
        # The signal row's sizing freezes; later rows changing weights/legs
        # do not touch the held episode. MUTATION: re-reading sizing at exit
        # (or from the fill row) picks up the changed values.
        sized = {**GOOD, "w_front": -1.2, "w_belly": 2.4, "w_back": -1.1,
                 "leg_front": "3y1y", "leg_belly": "4y1y", "leg_back": "5y1y"}
        panel = make_panel(D, overrides={(D[0], POINT): sized,
                                         **_zs_path([2.0, -0.5])})
        eps = episodes_from_panel(panel, CFG)
        assert len(eps) == 1
        e = eps[0]
        assert (e.w_front, e.w_belly, e.w_back) == (-1.2, 2.4, -1.1)
        assert (e.leg_front, e.leg_belly, e.leg_back) == ("3y1y", "4y1y", "5y1y")

    def test_nan_zs_during_hold(self):
        # A NaN mark evaluates no stop/target that day; the horizon clock
        # still runs. MUTATION: treating NaN as a zero-cross exits at D[2].
        panel = make_panel(D, overrides={(D[0], POINT): GOOD,
                                         **_zs_path([np.nan, -0.5])})
        eps = episodes_from_panel(panel, CFG)
        assert len(eps) == 1 and eps[0].exit_date == D[3] and eps[0].exit_reason == "target"
        cfg = FlyDislocationConfig(max_hold_bd=1, start=CFG.start, end=CFG.end)
        panel = make_panel(D, overrides={(D[0], POINT): GOOD,
                                         **_zs_path([np.nan, np.nan])})
        eps = episodes_from_panel(panel, cfg)
        assert len(eps) == 1 and eps[0].exit_reason == "horizon" and eps[0].exit_date == D[2]

    def test_wrong_weight_orientation_raises(self):
        # A gate-passing row with an inverted/degenerate weight pattern is a
        # screen defect that would silently flip or misbuild the book — LOUD.
        # MUTATION: accepting w_belly <= 0 lets a zero weight reach the
        # backend's falsy-bpv branch (silent 1mm-notional default leg).
        for bad in (dict(w_belly=-2.0), dict(w_front=1.0), dict(w_back=1.0),
                    dict(w_belly=0.0)):
            panel = make_panel(D, overrides={(D[0], POINT): {**GOOD, **bad}})
            with pytest.raises(ValueError, match="orientation"):
                episodes_from_panel(panel, CFG)

    def test_loud_failures(self):
        with pytest.raises(KeyError, match="missing required columns"):
            episodes_from_panel(make_panel(D).drop(columns=["edge_bp"]), CFG)
        bad = make_panel(D)
        bad.index = bad.index.set_names(["date", "leg"])
        with pytest.raises(ValueError, match="named"):
            episodes_from_panel(bad, CFG)
        dup = pd.concat([make_panel(D), make_panel(D[:1])])
        with pytest.raises(ValueError, match="duplicate"):
            episodes_from_panel(dup, CFG)
        with pytest.raises(ValueError, match="no panel dates"):
            episodes_from_panel(make_panel(D), FlyDislocationConfig(
                start=datetime.date(2030, 1, 1), end=datetime.date(2030, 2, 1)))
        with pytest.raises(ValueError, match="exit_z_mult"):
            episodes_from_panel(make_panel(D), FlyDislocationConfig(
                exit_z_mult=1.0, start=CFG.start, end=CFG.end))
        with pytest.raises(ValueError, match="max_hold_bd"):
            episodes_from_panel(make_panel(D), FlyDislocationConfig(
                max_hold_bd=0, start=CFG.start, end=CFG.end))

    def test_config_frozen_defaults(self):
        cfg = FlyDislocationConfig()
        assert (cfg.min_abs_z, cfg.min_edge_bp, cfg.max_hold_bd) == (2.0, 1.0, 63)
        assert (cfg.exit_z_mult, cfg.package_dv01_usd, cfg.cost_rt_bp) == (2.0, 50_000.0, 2.3)


# ---------------------------------------------------------------------------
# QDB smoke — conftest mocks, subclassed (see module docstring)
# ---------------------------------------------------------------------------
ANCHOR = datetime.date(2025, 6, 2)
CURV = 0.02


def _scale(eff: datetime.date) -> float:
    fy = (eff - ANCHOR).days / 365.25
    return 1.0 + CURV * fy * fy


class DriftPricer(MockPricer):
    def build_irswap(self, fwd=None, tenor=None, effective_date=None,
                     maturity_date=None, fixed_rate=None, notional=None, bpv=None):
        inst = super().build_irswap(fwd=fwd, tenor=tenor, effective_date=effective_date,
                                    maturity_date=maturity_date, fixed_rate=fixed_rate,
                                    notional=notional, bpv=bpv)
        if effective_date is not None:
            eff = effective_date
        else:
            fy = self._parse_tenor(fwd) if fwd else 0.0
            eff = self.as_of_date + datetime.timedelta(days=round(fy * 365.25))
        if maturity_date is not None:
            mat = maturity_date
        else:
            ty = self._parse_tenor(tenor) if tenor else 1.0
            mat = eff + datetime.timedelta(days=round(ty * 365.25))
        inst.effective, inst.maturity = eff, mat
        return inst

    def effective_date(self, inst):
        return inst.effective

    def maturity_date(self, inst):
        return inst.maturity

    def npv(self, inst):
        days = (self.as_of_date - ANCHOR).days
        return float(inst.notional) * 1e-4 * days * _scale(inst.effective)

    def pv01(self, inst):
        return float(inst.notional) * 1e-4 * _scale(inst.effective)

    def resolve_pricable(self, pricable, risk_weight=1.0):
        # Idempotent |notional| x sign(w) — the RL backend's semantics.
        sign = -1.0 if float(risk_weight) < 0 else 1.0
        pricable.notional = abs(pricable.notional) * sign
        return pricable


class BrokenMirrorPricer(DriftPricer):
    """The L-0012 regression: direction-blind resolve prices +/-bpv identically."""

    def resolve_pricable(self, pricable, risk_weight=1.0):
        pricable.notional = abs(pricable.notional)
        return pricable


def _mdp_with(pricer_cls):
    class _MDP(MockMDP):
        def get_pricer(self, request):
            ts = request.get("timestamp", ANCHOR)
            if isinstance(ts, datetime.datetime):
                ts = ts.date()
            return pricer_cls(curve_name=request.get("curve_name", CURVE),
                              as_of_date=ts, base_rate=self.base_rate)
    return _MDP()


EP = FlyEpisode(POINT, T("2025-06-03"), T("2025-06-10"), +1,
                "4y1y", "5y1y", "6y1y", -1.0, 2.0, -1.0, 3.0, "target")


class TestQDB:
    def test_build_backtest_structure(self):
        bt = build_backtest([EP], D, _mdp_with(DriftPricer), cfg=CFG)
        trig = list(bt.strategy.triggers)
        assert len(trig) == 2
        entry, unwind = trig

        # Trigger dates are plain datetime.date. MUTATION: pd.Timestamp there
        # is a silent no-op (every mark exactly zero).
        for tr in trig:
            for d in tr.trigger_requirements.dates:
                assert type(d) is datetime.date
        assert entry.trigger_requirements.dates == [datetime.date(2025, 6, 3)]
        assert unwind.trigger_requirements.dates == [datetime.date(2025, 6, 10)]

        # bpv_i = direction * w_i * package_dv01: pay-belly (-1,+2,-1) x $50k.
        # MUTATION: dropping `direction` or the w_i scaling breaks these.
        bpvs = [a.query.structure_kwargs["bpv"] for a in entry.actions]
        assert bpvs == [-50_000.0, +100_000.0, -50_000.0]
        effs = [a.query.effective_date for a in entry.actions]
        assert effs[0] < effs[1] < effs[2]               # front < belly < back
        for a in entry.actions:
            q = a.query
            assert q.tenor is None                        # explicit dates only
            assert q.effective_date is not None and q.maturity_date is not None
            assert q.market_request["offline"] is True
            assert q.market_request["curve_name"] == CURVE
            assert "fd0" in q.tags
        # Receive-belly mirror.
        ep2 = EP._replace(direction=-1)
        bt2 = build_backtest([ep2], D, _mdp_with(DriftPricer), cfg=CFG)
        bpvs2 = [a.query.structure_kwargs["bpv"] for a in list(bt2.strategy.triggers)[0].actions]
        assert bpvs2 == [+50_000.0, -100_000.0, +50_000.0]

        # Fee: 2.3bp RT x $50k/bp = $115,000 USD, at unwind only.
        # MUTATION: any /1e4 (fee $11.50) or per-leg multiplication breaks it.
        act = unwind.actions[0]
        assert act.match_tag == "fd0"
        assert act.fee == pytest.approx(115_000.0)

    def test_build_backtest_loud_failures(self):
        mdp = _mdp_with(DriftPricer)
        with pytest.raises(ValueError, match="no episodes"):
            build_backtest([], D, mdp, cfg=CFG)
        with pytest.raises(ValueError, match="not on the time grid"):
            build_backtest([EP._replace(entry_date=T("2025-05-01"))], D, mdp, cfg=CFG)
        with pytest.raises(ValueError, match="!<"):
            build_backtest([EP._replace(exit_date=EP.entry_date)], D, mdp, cfg=CFG)
        with pytest.raises(ValueError, match="direction"):
            build_backtest([EP._replace(direction=0)], D, mdp, cfg=CFG)
        with pytest.raises(ValueError, match="orientation"):
            build_backtest([EP._replace(w_belly=0.0)], D, mdp, cfg=CFG)

    def test_qdb_smoke_panel_to_pnl(self):
        # End to end: panel -> episodes -> QDB. Entry D[1], target exit D[5].
        panel = make_panel(D, overrides={(D[0], POINT): GOOD,
                                         **_zs_path([2.5, 2.4, 2.2, -0.3])})
        eps = episodes_from_panel(panel, CFG)
        assert [(e.entry_date, e.exit_date) for e in eps] == [(D[1], D[5])]
        bt, eq = run_backtest(eps, D, _mdp_with(DriftPricer), cfg=CFG, probe=True)

        assert len(eq) == len(D)
        assert float(eq.abs().max()) > 0.0               # marks are non-zero
        assert float(eq.iloc[0]) == 0.0                  # flat before entry

        closed = bt.portfolio.closed_positions_log
        assert len(closed) == 3                          # 1 episode x 3 legs
        assert sum(c["fee_allocated"] for c in closed) == pytest.approx(115_000.0)
        for c in closed:
            assert c["realized_pnl"] == pytest.approx(
                c["gross_realized_pnl"] - c["fee_allocated"])

        # First-principles expected P&L: gross = sum_i bpv_i * dd * s_i with
        # bpv = (-1,+2,-1) x $50k and s = 1 + CURV*((eff-ANCHOR)/365.25y)^2,
        # eff = entry + round(fwd_years*365.25) days. The fly books the SECOND
        # difference of the leg scale: nonzero ONLY because the scale is
        # convex — a linear scale would cancel exactly (that cancellation is
        # the negative control below).
        def leg_scale(entry, fwd_years):
            eff = entry + datetime.timedelta(days=round(fwd_years * 365.25))
            fy = (eff - ANCHOR).days / 365.25
            return 1.0 + CURV * fy * fy

        e = eps[0]
        dd = (e.exit_date.date() - e.entry_date.date()).days
        s4, s5, s6 = (leg_scale(e.entry_date.date(), f) for f in (4.0, 5.0, 6.0))
        gross = 50_000.0 * dd * (-s4 + 2.0 * s5 - s6)
        assert abs(gross) > 1_000.0                      # curvature keeps it alive
        assert float(eq.iloc[-1]) == pytest.approx(gross - 115_000.0, rel=1e-9)
        assert sum(c["gross_realized_pnl"] for c in closed) == pytest.approx(gross, rel=1e-9)

    def test_sign_probe_and_broken_mirror_negative_control(self):
        pr = sign_probe(_mdp_with(DriftPricer), datetime.date(2025, 6, 3))
        assert pr["is_payer_convention"] is True
        assert pr["pay_pv01"] > 0.0 > pr["receive_pv01"]
        assert abs(pr["sum"]) < 1e-6 * pr["pay_pv01"]

        pr_bad = sign_probe(_mdp_with(BrokenMirrorPricer), datetime.date(2025, 6, 3))
        assert pr_bad["is_payer_convention"] is False
        with pytest.raises(AssertionError, match="sign probe"):
            run_backtest([EP], D, _mdp_with(BrokenMirrorPricer), cfg=CFG, probe=True)


# ---------------------------------------------------------------------------
# Integration — offline curve store, ONE tiny episode
# ---------------------------------------------------------------------------
INT_GRID = list(pd.bdate_range("2026-07-06", "2026-07-17"))  # 10 bdays


def _store_mdp_or_skip(days):
    try:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
        mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    except Exception as e:  # noqa: BLE001 - any import/env failure is a skip
        pytest.skip(f"IRSwapsMDP unavailable: {type(e).__name__}: {e}")
    for d in days:
        try:
            pricer = mdp.get_pricer({"curve_name": CURVE, "timestamp": d.date(),
                                     "offline": True})
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"offline curve store cannot serve {d.date()}: "
                        f"{type(e).__name__}: {e}")
        meta = {}
        try:
            meta = pricer.meta() or {}
        except Exception:  # noqa: BLE001
            meta = {}
        if meta.get("from_curve_store") is not True:
            pytest.skip(f"curve for {d.date()} not served from the curve store "
                        f"(from_curve_store={meta.get('from_curve_store')!r})")
    return mdp


@pytest.mark.integration
class TestIntegrationTiny:
    def test_one_episode_ten_days_real_store(self):
        mdp = _store_mdp_or_skip(INT_GRID)
        ep = FlyEpisode(POINT, INT_GRID[0], INT_GRID[-1], +1,
                        "4y1y", "5y1y", "6y1y", -1.0, 2.0, -1.0, 2.5, "end")
        bt, eq = run_backtest([ep], INT_GRID, mdp, cfg=CFG, probe=True)

        assert len(eq) == len(INT_GRID)
        assert float(eq.abs().max()) > 0.0
        closed = bt.portfolio.closed_positions_log
        assert len(closed) == 3                          # all three legs closed
        assert sum(c["fee_allocated"] for c in closed) == pytest.approx(115_000.0)
        print(f"\n[integration fly] equity end {float(eq.iloc[-1]):,.2f} USD, "
              f"max |mark| {float(eq.abs().max()):,.2f}, "
              f"gross {sum(c['gross_realized_pnl'] for c in closed):,.2f}")
