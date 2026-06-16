"""Roll calendar + runner for the UST futures basis backtest."""
import datetime

import QuantLib as ql

CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)


def test_front_contract_known_dates():
    from BT.signals.ustf_basis import front_contract

    # mid-Oct 2024 -> hold the Dec 2024 contract
    assert front_contract("TY", datetime.date(2024, 10, 15), roll_days=6, cal=CAL) == "TYZ24"
    # Dec contract in delivery -> front rolled to Mar 2025
    assert front_contract("TY", datetime.date(2024, 12, 2), roll_days=6, cal=CAL) == "TYH25"
    assert front_contract("TY", datetime.date(2025, 1, 15), roll_days=6, cal=CAL) == "TYH25"
    # just before the late-Feb roll -> still Mar
    assert front_contract("TY", datetime.date(2025, 2, 10), roll_days=6, cal=CAL) == "TYH25"
    # after the Mar roll -> Jun
    assert front_contract("TY", datetime.date(2025, 3, 10), roll_days=6, cal=CAL) == "TYM25"


def test_front_contract_respects_root():
    from BT.signals.ustf_basis import front_contract

    assert front_contract("US", datetime.date(2025, 1, 15), roll_days=6, cal=CAL) == "USH25"
    assert front_contract("FV", datetime.date(2025, 7, 1), roll_days=6, cal=CAL) == "FVU25"


def test_segments_cover_grid_contiguously_and_match_front():
    import pandas as pd

    from BT.signals.ustf_basis import contract_segments, front_contract

    dates = [d.date() for d in pd.bdate_range("2024-06-03", "2025-06-02")]
    segs = contract_segments("TY", dates, roll_days=6, cal=CAL)

    # contiguous, gap-free, non-overlapping coverage of the whole grid
    covered = []
    for s in segs:
        covered.extend(d for d in dates if s.start <= d <= s.end)
    assert covered == dates
    assert segs[0].start == dates[0]
    assert segs[-1].end == dates[-1]

    # each segment's symbol is the front contract on its start date
    for s in segs:
        assert s.symbol == front_contract("TY", s.start, roll_days=6, cal=CAL)

    # symbols are all distinct (one segment per contract over a year)
    syms = [s.symbol for s in segs]
    assert len(syms) == len(set(syms))


def test_run_short_window_has_no_mtm_gaps():
    from BT.signals.ustf_basis import UstfBasisConfig, run_ustf_basis_backtest

    # pre-roll window -> the front (TYZ25) is held the whole time, no roll boundary
    cfg = UstfBasisConfig(
        tenors=["TY"],
        start=datetime.date(2025, 11, 3),
        end=datetime.date(2025, 11, 19),
        bond_face=100_000_000.0,
        direction=1,
        show_progress=False,
    )
    res = run_ustf_basis_backtest(cfg)
    mtm = res.mtm_by_tenor["TY"]
    grid = res.time_grid_dates

    # the engine swallows per-day pricing errors with print+continue, so the only way to
    # know every day priced is to assert full-grid coverage of the MTM series.
    assert len(mtm) == len(grid), f"gaps on: {sorted(set(grid) - set(mtm.index))}"
    assert mtm.notna().all()
    # a real position is on -> cumulative PnL is non-trivial, and long-basis financing is a cost
    assert mtm.abs().max() > 0.0
    assert res.components_by_tenor["TY"]["financing"].iloc[-1] < 0.0

