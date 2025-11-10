"""
Test trigger mechanisms and custom trigger creation.

These tests document how to create and use various trigger types:
- Date triggers
- Custom trigger requirements
- Conditional triggers
- Risk-based triggers
"""

import pytest
import datetime
from BT.triggers import (
    Trigger,
    DateTrigger,
    DateTriggerRequirements,
    TriggerRequirements,
)
from BT.event import TriggerInfo


class TestDateTriggers:
    """Test date-based triggers."""

    def test_date_trigger_fires_on_specified_date(self):
        """
        EXAMPLE: Create a trigger that fires on a specific date.

        Date triggers are the most common trigger type.
        """
        target_date = datetime.date(2025, 1, 15)

        req = DateTriggerRequirements(dates=[target_date])
        trigger = DateTrigger(req, actions=[])

        # Should fire on target date
        state_on_target = datetime.datetime(2025, 1, 15)
        result = trigger.requirements.has_triggered(state_on_target)

        assert result.triggered is True

    def test_date_trigger_does_not_fire_on_other_dates(self):
        """
        EXAMPLE: Date trigger only fires on specified dates.
        """
        target_date = datetime.date(2025, 1, 15)

        req = DateTriggerRequirements(dates=[target_date])

        # Should not fire on different date
        other_date = datetime.datetime(2025, 1, 16)
        result = req.has_triggered(other_date)

        assert result.triggered is False

    def test_multiple_date_trigger(self):
        """
        EXAMPLE: Trigger that fires on multiple dates.

        Useful for periodic entries (e.g., month-end).
        """
        dates = [
            datetime.date(2025, 1, 31),
            datetime.date(2025, 2, 28),
            datetime.date(2025, 3, 31),
        ]

        req = DateTriggerRequirements(dates=dates)

        # Should fire on each specified date
        for d in dates:
            result = req.has_triggered(datetime.datetime.combine(d, datetime.time()))
            assert result.triggered is True


class TestCustomTriggers:
    """Test custom trigger creation."""

    def test_always_on_trigger(self):
        """
        EXAMPLE: Create a trigger that always fires.

        Useful for continuous strategies or testing.
        """
        class AlwaysOn(TriggerRequirements):
            def has_triggered(self, state, backtest=None):
                return TriggerInfo(True, info={})

        trigger_req = AlwaysOn()

        # Should fire on any date
        result = trigger_req.has_triggered(datetime.datetime(2025, 1, 1))
        assert result.triggered is True

        result = trigger_req.has_triggered(datetime.datetime(2025, 12, 31))
        assert result.triggered is True

    def test_never_fire_trigger(self):
        """
        EXAMPLE: Create a trigger that never fires.

        Useful for disabling strategies temporarily.
        """
        class NeverFire(TriggerRequirements):
            def has_triggered(self, state, backtest=None):
                return TriggerInfo(False, info={})

        trigger_req = NeverFire()

        result = trigger_req.has_triggered(datetime.datetime(2025, 1, 1))
        assert result.triggered is False

    def test_day_of_week_trigger(self):
        """
        EXAMPLE: Trigger that fires on specific days of the week.

        E.g., every Monday for week-start rebalancing.
        """
        class MondayTrigger(TriggerRequirements):
            def has_triggered(self, state, backtest=None):
                # Monday is weekday 0
                is_monday = state.weekday() == 0
                return TriggerInfo(is_monday, info={"day": state.strftime("%A")})

        trigger_req = MondayTrigger()

        # Test on a Monday (2025-01-06 is a Monday)
        monday = datetime.datetime(2025, 1, 6)
        result = trigger_req.has_triggered(monday)
        assert result.triggered is True

        # Test on a Tuesday
        tuesday = datetime.datetime(2025, 1, 7)
        result = trigger_req.has_triggered(tuesday)
        assert result.triggered is False


class TestConditionalTriggers:
    """Test triggers with conditions."""

    def test_time_window_trigger(self):
        """
        EXAMPLE: Trigger that only fires within a date range.

        Useful for limiting strategy to specific periods.
        """
        class DateRangeTrigger(TriggerRequirements):
            def __init__(self, start_date, end_date):
                self.start_date = start_date
                self.end_date = end_date

            def has_triggered(self, state, backtest=None):
                state_date = state.date() if isinstance(state, datetime.datetime) else state
                in_range = self.start_date <= state_date <= self.end_date
                return TriggerInfo(in_range, info={})

        start = datetime.date(2025, 1, 1)
        end = datetime.date(2025, 1, 31)

        trigger_req = DateRangeTrigger(start, end)

        # Inside range
        result = trigger_req.has_triggered(datetime.datetime(2025, 1, 15))
        assert result.triggered is True

        # Outside range
        result = trigger_req.has_triggered(datetime.datetime(2025, 2, 1))
        assert result.triggered is False

    def test_first_occurrence_trigger(self):
        """
        EXAMPLE: Trigger that fires once then deactivates.

        Useful for one-time initialization.
        """
        class FirstOccurrenceTrigger(TriggerRequirements):
            def __init__(self):
                self.has_fired = False

            def has_triggered(self, state, backtest=None):
                if not self.has_fired:
                    self.has_fired = True
                    return TriggerInfo(True, info={})
                return TriggerInfo(False, info={})

        trigger_req = FirstOccurrenceTrigger()

        # First call: fires
        result = trigger_req.has_triggered(datetime.datetime(2025, 1, 1))
        assert result.triggered is True

        # Subsequent calls: don't fire
        result = trigger_req.has_triggered(datetime.datetime(2025, 1, 2))
        assert result.triggered is False


class TestRiskBasedTriggers:
    """Test triggers that depend on portfolio risk."""

    def test_risk_threshold_trigger(self):
        """
        EXAMPLE: Trigger that fires when risk exceeds a threshold.

        Useful for position limits or hedging.
        """
        class RiskThresholdTrigger(TriggerRequirements):
            def __init__(self, risk_name: str, threshold: float):
                self.risk_name = risk_name
                self.threshold = threshold

            def has_triggered(self, state, backtest=None):
                if backtest is None:
                    return TriggerInfo(False, info={})

                # Get risk from backtest
                current_risk = backtest.get_strategy_risk(self.risk_name)
                exceeds = abs(current_risk) > self.threshold

                return TriggerInfo(
                    exceeds,
                    info={
                        "risk_name": self.risk_name,
                        "current": current_risk,
                        "threshold": self.threshold,
                    }
                )

        # This is a documentation test - actual behavior depends on backtest implementation
        trigger_req = RiskThresholdTrigger("dv01", 1_000_000)

        # Without backtest, should not fire
        result = trigger_req.has_triggered(datetime.datetime(2025, 1, 1), backtest=None)
        assert result.triggered is False


class TestTriggerInfo:
    """Test TriggerInfo metadata."""

    def test_trigger_info_carries_metadata(self):
        """
        EXAMPLE: Triggers can pass information to actions.

        Useful for dynamic parameter adjustment.
        """
        class MetadataTrigger(TriggerRequirements):
            def has_triggered(self, state, backtest=None):
                return TriggerInfo(
                    True,
                    info={
                        "timestamp": state,
                        "signal_strength": 0.75,
                        "reason": "carry positive",
                    }
                )

        trigger_req = MetadataTrigger()
        result = trigger_req.has_triggered(datetime.datetime(2025, 1, 15))

        assert result.triggered is True
        assert "timestamp" in result.info
        assert result.info["signal_strength"] == 0.75
        assert result.info["reason"] == "carry positive"


class TestPeriodicTriggers:
    """Test periodic/recurring triggers."""

    def test_monthly_trigger(self):
        """
        EXAMPLE: Trigger that fires on last business day of month.

        Common for month-end rebalancing.
        """
        class MonthEndTrigger(TriggerRequirements):
            def has_triggered(self, state, backtest=None):
                # Simplified: check if last day of month
                state_date = state.date() if isinstance(state, datetime.datetime) else state

                # Check if this is the last day of the month
                next_day = state_date + datetime.timedelta(days=1)
                is_month_end = next_day.month != state_date.month

                return TriggerInfo(is_month_end, info={})

        trigger_req = MonthEndTrigger()

        # Test on month-end (Jan 31)
        month_end = datetime.datetime(2025, 1, 31)
        result = trigger_req.has_triggered(month_end)
        assert result.triggered is True

        # Test on non-month-end (Jan 15)
        mid_month = datetime.datetime(2025, 1, 15)
        result = trigger_req.has_triggered(mid_month)
        assert result.triggered is False

    def test_every_n_days_trigger(self):
        """
        EXAMPLE: Trigger that fires every N days.

        Useful for periodic rebalancing.
        """
        class EveryNDaysTrigger(TriggerRequirements):
            def __init__(self, start_date, interval_days):
                self.start_date = start_date
                self.interval_days = interval_days

            def has_triggered(self, state, backtest=None):
                state_date = state.date() if isinstance(state, datetime.datetime) else state
                days_since_start = (state_date - self.start_date).days

                # Fire if days since start is a multiple of interval
                should_fire = (days_since_start % self.interval_days) == 0

                return TriggerInfo(should_fire, info={"days_since_start": days_since_start})

        start = datetime.date(2025, 1, 1)
        trigger_req = EveryNDaysTrigger(start, interval_days=5)

        # Day 0: fires
        result = trigger_req.has_triggered(datetime.datetime(2025, 1, 1))
        assert result.triggered is True

        # Day 5: fires
        result = trigger_req.has_triggered(datetime.datetime(2025, 1, 6))
        assert result.triggered is True

        # Day 3: doesn't fire
        result = trigger_req.has_triggered(datetime.datetime(2025, 1, 4))
        assert result.triggered is False


class TestTriggerComposition:
    """Test combining triggers."""

    def test_and_trigger(self):
        """
        EXAMPLE: Trigger that requires multiple conditions (AND).

        Both sub-triggers must fire.
        """
        class AndTrigger(TriggerRequirements):
            def __init__(self, trigger1, trigger2):
                self.trigger1 = trigger1
                self.trigger2 = trigger2

            def has_triggered(self, state, backtest=None):
                result1 = self.trigger1.has_triggered(state, backtest)
                result2 = self.trigger2.has_triggered(state, backtest)

                both_fired = result1.triggered and result2.triggered

                return TriggerInfo(
                    both_fired,
                    info={
                        "trigger1": result1.triggered,
                        "trigger2": result2.triggered,
                    }
                )

        # Example: Monday AND within January
        class IsMondayTrigger(TriggerRequirements):
            def has_triggered(self, state, backtest=None):
                return TriggerInfo(state.weekday() == 0, info={})

        class IsJanuaryTrigger(TriggerRequirements):
            def has_triggered(self, state, backtest=None):
                return TriggerInfo(state.month == 1, info={})

        combined = AndTrigger(IsMondayTrigger(), IsJanuaryTrigger())

        # Monday in January: fires
        result = combined.has_triggered(datetime.datetime(2025, 1, 6))
        assert result.triggered is True

        # Monday in February: doesn't fire
        result = combined.has_triggered(datetime.datetime(2025, 2, 3))
        assert result.triggered is False

    def test_or_trigger(self):
        """
        EXAMPLE: Trigger that requires any condition (OR).

        Either sub-trigger can fire.
        """
        class OrTrigger(TriggerRequirements):
            def __init__(self, trigger1, trigger2):
                self.trigger1 = trigger1
                self.trigger2 = trigger2

            def has_triggered(self, state, backtest=None):
                result1 = self.trigger1.has_triggered(state, backtest)
                result2 = self.trigger2.has_triggered(state, backtest)

                either_fired = result1.triggered or result2.triggered

                return TriggerInfo(
                    either_fired,
                    info={
                        "trigger1": result1.triggered,
                        "trigger2": result2.triggered,
                    }
                )

        class AlwaysTrue(TriggerRequirements):
            def has_triggered(self, state, backtest=None):
                return TriggerInfo(True, info={})

        class AlwaysFalse(TriggerRequirements):
            def has_triggered(self, state, backtest=None):
                return TriggerInfo(False, info={})

        # True OR False = True
        combined = OrTrigger(AlwaysTrue(), AlwaysFalse())
        result = combined.has_triggered(datetime.datetime(2025, 1, 1))
        assert result.triggered is True
