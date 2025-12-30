"""
Base class for USD product modules.

Provides USD-specific conventions and common functionality
for all USD derivative products.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Optional

import pandas as pd
import QuantLib as ql

from SDRUtils.config import USD_CONVENTIONS, CurrencyConventions
from SDRUtils.core.classification import TradeClassification
from SDRUtils.products.base import ProductModule


class USDProductBase(ProductModule):
    """
    Base class for USD product implementations.

    Provides:
    - USD calendar (GovBond)
    - ACT/360 day counter
    - Modified Following business day convention
    - T+2 spot lag
    """

    currency: str = "USD"
    conventions: CurrencyConventions = USD_CONVENTIONS

    @property
    def calendar(self) -> ql.Calendar:
        """USD Government Bond calendar."""
        return self.conventions.calendar

    @property
    def day_counter(self) -> ql.DayCounter:
        """ACT/360 day counter."""
        return self.conventions.day_counter

    @property
    def business_day_convention(self) -> int:
        """Modified Following convention."""
        return self.conventions.business_day_convention

    @property
    def spot_lag_days(self) -> int:
        """T+2 settlement."""
        return self.conventions.spot_lag_days

    def get_spot_date(self, trade_date: ql.Date) -> ql.Date:
        """Calculate spot date from trade date."""
        return self.calendar.advance(trade_date, self.spot_lag_days, ql.Days)

    def is_business_day(self, date: ql.Date) -> bool:
        """Check if date is a business day."""
        return self.calendar.isBusinessDay(date)

    def adjust_to_business_day(self, date: ql.Date) -> ql.Date:
        """Adjust date to next business day if needed."""
        if not self.is_business_day(date):
            return self.calendar.adjust(date, self.business_day_convention)
        return date

    @abstractmethod
    def classify_trade(
        self, row: pd.Series, trade_id: int, **kwargs: Any
    ) -> TradeClassification:
        """Classify a single SDR trade row."""
        pass
