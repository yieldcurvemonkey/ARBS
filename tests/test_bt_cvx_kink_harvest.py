"""BT/signals/cvx_kink_harvest.py — episode extraction, QDB wiring, tiny real run.

Pure-logic tests plant a known answer in a synthetic (date, pair) panel and
assert the exact episode list, with a negative control for every planted
answer. MUTATION notes mark the load-bearing asserts: the code line each one
kills if reverted.

The QDB smoke rides the conftest MockMDP/MockPricer, subclassed with:
- explicit effective/maturity retention (the rac resolve pattern reads them),
- a date-varying, CURVED leg scale so marks move (a linear scale would
  annihilate a fly's (-1,+2,-1) second difference — reference note
  "fly sees the second difference" — and the same subclass serves both suites),
- an IDEMPOTENT resolve_pricable mirroring the RL backend's abs()+sign (the
  conftest base mutates ``notional *= w`` per call, flipping every mark).

The @integration test runs ONE synthetic episode over 10 business days of
2026-07 against the offline curve store and self-skips, naming the day, when
the store cannot serve it.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime

import numpy as np
import pandas as pd
import pytest

from tests.conftest import MockMDP, MockPricer

from BT.signals.cvx_kink_harvest import (
    CURVE,
    REQUIRED_COLUMNS,
    HarvestEpisode,
    KinkHarvestConfig,
    build_backtest,
    episodes_from_panel,
    run_backtest,
    sign_probe,
)

T = pd.Timestamp
PAIR_A = "10y10y/15y10y"
PAIR_B = "10y10y/20y10y"

# Three panel dates in each of Jan/Feb/Mar/Apr 2025 (all genuine bdays).
J = [T("2025-01-06"), T("2025-01-07"), T("2025-01-08")]
F = [T("2025-02-03"), T("2025-02-04"), T("2025-02-05")]
M = [T("2025-03-03"), T("2025-03-04"), T("2025-03-05")]
A = [T("2025-04-01"), T("2025-04-02"), T("2025-04-03")]

FAIL = dict(be_over_rv=1.0, zs=0.0, rac_net=1.0)   # be gate fails; others pass
PASS = dict(be_over_rv=1.3, zs=0.0, rac_net=1.0)   # all three gates pass

CFG = KinkHarvestConfig(pairs=(PAIR_A,), start=datetime.date(2025, 1, 1),
                        end=datetime.date(2025, 12, 31))


def make_panel(dates, pairs=(PAIR_A,), default=FAIL, overrides=None, drop=()):
    rows = {(d, p): dict(default) for d in dates for p in pairs}
    for key, kv in (overrides or {}).items():
        rows[key].update(kv)
    for key in drop:
        rows.pop(key)
    idx = pd.MultiIndex.from_tuples(list(rows), names=["date", "pair"])
    return pd.DataFrame([rows[k] for k in idx], index=idx)


# ---------------------------------------------------------------------------
# Episode extraction — planted answers with negative controls
# ---------------------------------------------------------------------------
class TestEpisodes:
    def test_planted_single_episode(self):
        # Signal rows: last-of-Jan and last-of-Feb pass -> enter at the Feb
        # reform, hold at the Mar reform, exit at panel end.
        panel = make_panel(J + F + M, overrides={(J[2], PAIR_A): PASS,
                                                 (F[2], PAIR_A): PASS})
        eps = episodes_from_panel(panel, CFG)
        assert eps == [HarvestEpisode(PAIR_A, F[0], M[2])]
        # Unpackable as the spec's (pair, entry_date, exit_date) tuple.
        pair, entry, exit_ = eps[0]
        assert (pair, entry, exit_) == (PAIR_A, F[0], M[2])

    @pytest.mark.parametrize("bad", [
        dict(be_over_rv=1.16),        # below the 1.17 floor
        dict(zs=0.51),                # above the +0.5 cap
        dict(rac_net=0.0),            # rac gate is a STRICT floor
        dict(be_over_rv=np.nan),      # NaN refuses
        dict(zs=np.nan),
        dict(rac_net=np.nan),
    ])
    def test_each_gate_violated_no_episode(self, bad):
        # Negative control for the planted answer: the same panel with ONE
        # gate broken on BOTH signal rows produces nothing.
        # MUTATION: dropping any single gate comparison in _gates_pass makes
        # its variant here return the planted episode and fail this test.
        panel = make_panel(J + F + M, overrides={(J[2], PAIR_A): {**PASS, **bad},
                                                 (F[2], PAIR_A): {**PASS, **bad}})
        assert episodes_from_panel(panel, CFG) == []

    def test_gate_boundaries_inclusive_and_strict(self):
        # be_over_rv INCLUSIVE >=, zs INCLUSIVE <=, rac_net STRICT > (the
        # books.py contract). MUTATION: `>=` -> `>` on be, `<=` -> `<` on zs,
        # or `>` -> `>=` on rac each flips exactly one of these two asserts.
        edge = dict(be_over_rv=1.17, zs=0.5, rac_net=1e-9)
        panel = make_panel(J + F, overrides={(J[2], PAIR_A): edge})
        assert episodes_from_panel(panel, CFG) == [HarvestEpisode(PAIR_A, F[0], F[2])]
        panel = make_panel(J + F, overrides={(J[2], PAIR_A): {**PASS, "rac_net": 0.0}})
        assert episodes_from_panel(panel, CFG) == []

    def test_lag1_same_day_fill_caught(self):
        # Gates pass ONLY on the reform dates' own rows; every t-1 row fails.
        # MUTATION: reading the reform-day row instead of the t-1 row (drop
        # the `i - 1`) manufactures an entry at F[0] and fails this test.
        panel = make_panel(J + F + M, overrides={(F[0], PAIR_A): PASS,
                                                 (M[0], PAIR_A): PASS})
        assert episodes_from_panel(panel, CFG) == []

    def test_midmonth_gate_changes_ignored(self):
        # Monthly reform, not a daily stop: failing hard on non-reform dates
        # changes nothing while both reform signal rows pass.
        # MUTATION: evaluating gates daily would exit at F[1].
        panel = make_panel(
            J + F + M,
            overrides={(J[2], PAIR_A): PASS, (F[2], PAIR_A): PASS,
                       (F[0], PAIR_A): dict(be_over_rv=0.1, zs=9.0, rac_net=-9.0),
                       (F[1], PAIR_A): dict(be_over_rv=0.1, zs=9.0, rac_net=-9.0)})
        assert episodes_from_panel(panel, CFG) == [HarvestEpisode(PAIR_A, F[0], M[2])]

    def test_exit_decision_reads_t_minus_1_not_reform_day(self):
        # Holding into March: the Mar-reform signal row is F[2].
        # (a) F[2] fails, M[0]'s own row passes -> exit AT M[0].
        panel = make_panel(J + F + M, overrides={(J[2], PAIR_A): PASS,
                                                 (M[0], PAIR_A): PASS})
        assert episodes_from_panel(panel, CFG) == [HarvestEpisode(PAIR_A, F[0], M[0])]
        # (b) F[2] passes, M[0]'s own row fails -> still holding, exit at end.
        # MUTATION: a same-day exit read exits at M[0] in (b) and holds in (a).
        panel = make_panel(J + F + M, overrides={(J[2], PAIR_A): PASS,
                                                 (F[2], PAIR_A): PASS})
        assert episodes_from_panel(panel, CFG) == [HarvestEpisode(PAIR_A, F[0], M[2])]

    def test_missing_signal_row_refuses(self):
        # A dropped (t-1, pair) row is a refusal, not a pass: no entry while
        # flat, exit at the reform while holding.
        # MUTATION: defaulting a missing row to "pass" holds to panel end.
        panel = make_panel(J + F + M, overrides={(J[2], PAIR_A): PASS},
                           drop=[(F[2], PAIR_A)])
        assert episodes_from_panel(panel, CFG) == [HarvestEpisode(PAIR_A, F[0], M[0])]

    def test_reentry_after_exit_and_no_overlap(self):
        panel = make_panel(J + F + M + A, overrides={(J[2], PAIR_A): PASS,
                                                     (M[2], PAIR_A): PASS})
        eps = episodes_from_panel(panel, CFG)
        assert eps == [HarvestEpisode(PAIR_A, F[0], M[0]),
                       HarvestEpisode(PAIR_A, A[0], A[2])]
        # One position per pair: strictly sequential, never overlapping.
        assert eps[0].exit_date <= eps[1].entry_date
        assert all(e.entry_date < e.exit_date for e in eps)

    def test_multiple_pairs_independent(self):
        cfg = KinkHarvestConfig(pairs=(PAIR_A, PAIR_B), start=CFG.start, end=CFG.end)
        panel = make_panel(J + F + M, pairs=(PAIR_A, PAIR_B),
                           overrides={(J[2], PAIR_A): PASS, (F[2], PAIR_B): PASS})
        eps = episodes_from_panel(panel, cfg)
        assert eps == [HarvestEpisode(PAIR_A, F[0], M[0]),
                       HarvestEpisode(PAIR_B, M[0], M[2])]

    def test_entry_refused_at_final_date(self):
        # The last in-range date is a reform date here; an entry there has no
        # time to hold. MUTATION: without the last-date guard a zero-length
        # (F[0], F[0]) episode appears.
        panel = make_panel(J + [F[0]], overrides={(J[2], PAIR_A): PASS})
        assert episodes_from_panel(panel, CFG) == []

    def test_window_filters_and_prior_history_is_legal_signal(self):
        # cfg.start at F[0]: the Jan rows are outside the window but J[2]
        # remains the legitimate t-1 signal row for the F[0] reform.
        cfg = KinkHarvestConfig(pairs=(PAIR_A,), start=datetime.date(2025, 2, 1),
                                end=datetime.date(2025, 12, 31))
        panel = make_panel(J + F + M, overrides={(J[2], PAIR_A): PASS,
                                                 (F[2], PAIR_A): PASS})
        assert episodes_from_panel(panel, cfg) == [HarvestEpisode(PAIR_A, F[0], M[2])]

    def test_loud_failures(self):
        with pytest.raises(KeyError, match="missing required columns"):
            episodes_from_panel(make_panel(J).drop(columns=["rac_net"]), CFG)
        bad = make_panel(J)
        bad.index = bad.index.set_names(["asof", "pair"])
        with pytest.raises(ValueError, match="named"):
            episodes_from_panel(bad, CFG)
        dup = pd.concat([make_panel(J), make_panel(J[:1])])
        with pytest.raises(ValueError, match="duplicate"):
            episodes_from_panel(dup, CFG)
        with pytest.raises(ValueError, match="never appear"):
            episodes_from_panel(make_panel(J), KinkHarvestConfig(
                pairs=("15y5y/20y10y",), start=CFG.start, end=CFG.end))
        with pytest.raises(ValueError, match="no panel dates"):
            episodes_from_panel(make_panel(J), KinkHarvestConfig(
                pairs=(PAIR_A,), start=datetime.date(2030, 1, 1),
                end=datetime.date(2030, 2, 1)))
        with pytest.raises(ValueError, match="unparseable leg label"):
            episodes_from_panel(make_panel(J), KinkHarvestConfig(
                pairs=("10q10q/15y10y",), start=CFG.start, end=CFG.end))

    def test_config_frozen_defaults(self):
        cfg = KinkHarvestConfig()
        assert cfg.pairs == ("10y10y/15y10y", "10y10y/20y10y", "15y5y/20y10y")
        assert (cfg.min_be_over_rv, cfg.max_z, cfg.min_rac_net) == (1.17, 0.5, 0.0)
        assert (cfg.reform, cfg.package_dv01_usd, cfg.half_spread_bp) == ("M", 100_000.0, 0.25)


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
        # Idempotent |notional| x sign(w) — the RL backend's semantics. The
        # conftest base does `notional *= w`, which flips the leg on every
        # mark for w = -1.
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


GRID = list(pd.bdate_range("2025-06-02", periods=10))  # 2025-06-02..2025-06-13


class TestQDB:
    def test_build_backtest_structure(self):
        eps = [HarvestEpisode(PAIR_A, T("2025-06-03"), T("2025-06-10"))]
        bt = build_backtest(eps, GRID, _mdp_with(DriftPricer), cfg=CFG)
        trig = list(bt.strategy.triggers)
        assert len(trig) == 2
        entry, unwind = trig

        # Trigger dates are plain datetime.date. MUTATION: leaving them as
        # pd.Timestamp makes DateTriggerRequirements a silent no-op (every
        # mark exactly zero) — this assert is the cheap structural catch.
        for tr in trig:
            for d in tr.trigger_requirements.dates:
                assert type(d) is datetime.date
        assert entry.trigger_requirements.dates == [datetime.date(2025, 6, 3)]
        assert unwind.trigger_requirements.dates == [datetime.date(2025, 6, 10)]

        # Steepener = the harvest (short-convexity) side: receive front
        # (-dv01), pay back (+dv01). MUTATION: flipping the harvest side (or
        # swapping the pair parse) flips these signs / the maturity ordering.
        bpvs = [a.query.structure_kwargs["bpv"] for a in entry.actions]
        assert bpvs == [-100_000.0, +100_000.0]
        q_front, q_back = (a.query for a in entry.actions)
        assert q_front.maturity_date < q_back.maturity_date
        for q in (q_front, q_back):
            assert q.tenor is None                      # explicit dates only
            assert q.effective_date is not None and q.maturity_date is not None
            assert q.market_request["offline"] is True
            assert q.market_request["curve_name"] == CURVE
            assert "kh0" in q.tags
        # Fee: 2 legs x 2 sides x 0.25bp x $100k/bp = $100,000 USD.
        # MUTATION: any /1e4 or a dropped factor breaks the equality.
        act = unwind.actions[0]
        assert act.match_tag == "kh0"
        assert act.fee == 100_000.0

    def test_build_backtest_loud_failures(self):
        mdp = _mdp_with(DriftPricer)
        with pytest.raises(ValueError, match="no episodes"):
            build_backtest([], GRID, mdp, cfg=CFG)
        off = [HarvestEpisode(PAIR_A, T("2025-05-01"), T("2025-06-10"))]
        with pytest.raises(ValueError, match="not on the time grid"):
            build_backtest(off, GRID, mdp, cfg=CFG)
        zero = [HarvestEpisode(PAIR_A, T("2025-06-03"), T("2025-06-03"))]
        with pytest.raises(ValueError, match="!<"):
            build_backtest(zero, GRID, mdp, cfg=CFG)

    def test_qdb_smoke_marks_positions_fees(self):
        eps = [HarvestEpisode(PAIR_A, T("2025-06-03"), T("2025-06-10")),
               HarvestEpisode(PAIR_B, T("2025-06-04"), T("2025-06-12"))]
        bt, eq = run_backtest(eps, GRID, _mdp_with(DriftPricer), cfg=CFG, probe=True)

        assert len(eq) == len(GRID)
        assert float(eq.abs().max()) > 0.0              # marks are non-zero
        assert float(eq.iloc[0]) == 0.0                 # flat before first entry

        closed = bt.portfolio.closed_positions_log
        assert len(closed) == 4                         # 2 episodes x 2 legs
        # Fees land: $100k per episode, split across its 2 legs.
        assert sum(c["fee_allocated"] for c in closed) == pytest.approx(200_000.0)
        for c in closed:
            assert c["realized_pnl"] == pytest.approx(
                c["gross_realized_pnl"] - c["fee_allocated"])

        # Direction: under this rising-payer drift the steepener (pay the
        # LONGER-effective leg) earns gross on both episodes. MUTATION: a
        # flipped harvest side turns both sums negative.
        by_tag = {}
        for c in closed:
            tag = [t for t in c["position_meta"]["tags"] if t.startswith("kh")][0]
            by_tag.setdefault(tag, 0.0)
            by_tag[tag] += c["gross_realized_pnl"]
        assert set(by_tag) == {"kh0", "kh1"}
        assert all(v > 0.0 for v in by_tag.values())

        # First-principles expected P&L (same arithmetic, written out):
        # per episode, gross = dv01 * (delta calendar days) * (s_back - s_front)
        # with s = 1 + CURV * ((eff - ANCHOR).days / 365.25)^2 and
        # eff = entry + round(fwd_years * 365.25) days.
        def leg_scale(entry, fwd_years):
            eff = entry + datetime.timedelta(days=round(fwd_years * 365.25))
            fy = (eff - ANCHOR).days / 365.25
            return 1.0 + CURV * fy * fy

        exp = 0.0
        for e, (f_fwd, b_fwd) in zip(eps, [(10.0, 15.0), (10.0, 20.0)]):
            entry_d, exit_d = e.entry_date.date(), e.exit_date.date()
            dd = (exit_d - entry_d).days
            exp += 100_000.0 * dd * (leg_scale(entry_d, b_fwd) - leg_scale(entry_d, f_fwd))
        exp -= 2 * 100_000.0                            # two unwind fees
        assert float(eq.iloc[-1]) == pytest.approx(exp, rel=1e-9)

    def test_sign_probe_and_broken_mirror_negative_control(self):
        pr = sign_probe(_mdp_with(DriftPricer), datetime.date(2025, 6, 3))
        assert pr["is_payer_convention"] is True
        assert pr["pay_pv01"] > 0.0 > pr["receive_pv01"]
        assert abs(pr["sum"]) < 1e-6 * pr["pay_pv01"]

        # Negative control: a direction-blind resolve (the L-0012 seam) must
        # FAIL the probe and abort run_backtest before the engine runs.
        # MUTATION: a probe that never re-resolves direction passes here.
        pr_bad = sign_probe(_mdp_with(BrokenMirrorPricer), datetime.date(2025, 6, 3))
        assert pr_bad["is_payer_convention"] is False
        eps = [HarvestEpisode(PAIR_A, T("2025-06-03"), T("2025-06-10"))]
        with pytest.raises(AssertionError, match="sign probe"):
            run_backtest(eps, GRID, _mdp_with(BrokenMirrorPricer), cfg=CFG, probe=True)


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
        eps = [HarvestEpisode(PAIR_A, INT_GRID[0], INT_GRID[-1])]
        bt, eq = run_backtest(eps, INT_GRID, mdp, cfg=CFG, probe=True)

        assert len(eq) == len(INT_GRID)
        assert float(eq.abs().max()) > 0.0
        closed = bt.portfolio.closed_positions_log
        assert len(closed) == 2                          # both legs closed
        assert sum(c["fee_allocated"] for c in closed) == pytest.approx(100_000.0)
        print(f"\n[integration kink] equity end {float(eq.iloc[-1]):,.2f} USD, "
              f"max |mark| {float(eq.abs().max()):,.2f}, "
              f"gross {sum(c['gross_realized_pnl'] for c in closed):,.2f}")
