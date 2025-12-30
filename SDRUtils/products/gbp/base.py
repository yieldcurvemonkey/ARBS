"""
Base class for GBP product modules.

Provides GBP-specific conventions and common functionality
for all GBP derivative products.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

import pandas as pd
import QuantLib as ql

from SDRUtils.config import GBP_CONVENTIONS, CurrencyConventions
from SDRUtils.core.classification import TradeClassification
from SDRUtils.products.base import ProductModule


class GBPProductBase(ProductModule):
    """
    Base class for GBP product implementations.

    Provides:
    - UK calendar
    - ACT/365 Fixed day counter
    - Modified Following business day convention
    - T+0 spot lag (SONIA convention)
    """

    currency: str = "GBP"
    conventions: CurrencyConventions = GBP_CONVENTIONS

    @property
    def calendar(self) -> ql.Calendar:
        """UK calendar."""
        return self.conventions.calendar

    @property
    def day_counter(self) -> ql.DayCounter:
        """ACT/365 Fixed day counter."""
        return self.conventions.day_counter

    @property
    def business_day_convention(self) -> int:
        """Modified Following convention."""
        return self.conventions.business_day_convention

    @property
    def spot_lag_days(self) -> int:
        """T+0 settlement (SONIA)."""
        return self.conventions.spot_lag_days

    def get_spot_date(self, trade_date: ql.Date) -> ql.Date:
        """Calculate spot date from trade date (same day for SONIA)."""
        return self.calendar.advance(trade_date, self.spot_lag_days, ql.Days)

    @abstractmethod
    def classify_trade(
        self, row: pd.Series, trade_id: int, **kwargs: Any
    ) -> TradeClassification:
        """Classify a single SDR trade row."""
        pass
