#!/usr/bin/env python
"""Test datetime fix for BT module"""
import sys
sys.path.insert(0, '.')

import datetime
import QuantLib as ql
from BT.misc import ql_cal_date_range
from BT.triggers import DateTrigger, DateTriggerRequirements

print("=" * 60)
print("Testing Datetime Fix")
print("=" * 60)

# Test 1: ql_cal_date_range returns datetime.datetime
print("\n1. Testing ql_cal_date_range returns datetime.datetime...")
CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
start = datetime.datetime(2024, 1, 1)
end = datetime.datetime(2024, 1, 10)

result = ql_cal_date_range(CAL, start, end, freq="1b")

assert len(result) > 0, "Should return some dates"
assert all(isinstance(d, datetime.datetime) for d in result), \
    f"All elements should be datetime.datetime, got types: {set(type(d) for d in result)}"
print(f"✓ Returns {len(result)} datetime.datetime objects")
print(f"  First: {result[0]} (type: {type(result[0]).__name__})")

# Test 2: DateTriggerRequirements handles datetime
print("\n2. Testing DateTriggerRequirements with datetime.datetime...")
trigger_dates = [datetime.date(2024, 1, 5)]
trigger_req = DateTriggerRequirements(dates=trigger_dates)

# Should trigger when datetime matches
state_datetime = datetime.datetime(2024, 1, 5, 7, 0, 0)
info = trigger_req.has_triggered(state_datetime, backtest=None)
assert info.triggered, "Should trigger on matching datetime"
print(f"✓ Triggers correctly with datetime.datetime")

# Should not trigger when date doesn't match
state_no_match = datetime.datetime(2024, 1, 6, 7, 0, 0)
info = trigger_req.has_triggered(state_no_match, backtest=None)
assert not info.triggered, "Should not trigger on non-matching datetime"
print(f"✓ Correctly ignores non-matching datetime")

# Test 3: DateTriggerRequirements handles date (defensive)
print("\n3. Testing DateTriggerRequirements with datetime.date (defensive)...")
state_date = datetime.date(2024, 1, 5)
info = trigger_req.has_triggered(state_date, backtest=None)
assert info.triggered, "Should trigger on matching date"
print(f"✓ Handles datetime.date defensively")

# Test 4: Integration test - realistic backtest scenario
print("\n4. Testing realistic backtest scenario...")
from BT.data_handler import TimeGrid

# Create time grid from date range (as backtest would)
time_grid_states = ql_cal_date_range(CAL, start, end, freq="1b")
tg = TimeGrid(time_grid_states)

# Create trigger for Jan 5
entry_date = datetime.date(2024, 1, 5)
trigger = DateTrigger(
    DateTriggerRequirements(dates=[entry_date]),
    actions=[]
)

# Simulate backtest iteration
triggered_count = 0
for state in tg:
    assert isinstance(state, datetime.datetime), \
        f"TimeGrid should yield datetime.datetime, got {type(state)}"
    info = trigger.has_triggered(state, backtest=None)
    if info.triggered:
        triggered_count += 1
        print(f"  Triggered on: {state}")

assert triggered_count == 1, f"Should trigger exactly once, triggered {triggered_count} times"
print(f"✓ Integration test passed - triggered {triggered_count} time(s)")

print("\n" + "=" * 60)
print("✅ All datetime fix tests passed!")
print("=" * 60)
