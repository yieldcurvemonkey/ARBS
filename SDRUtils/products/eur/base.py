"""
Base class for EUR product modules.

Provides EUR-specific conventions and common functionality
for all EUR derivative products.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

import pandas as pd
import QuantLib as ql

from SDRUtils.config import EUR_CONVENTIONS, CurrencyConventions
from SDRUtils.core.classification import TradeClassification
from SDRUtils.products.base import ProductModule


class EURProductBase(ProductModule):
    """
    Base class for EUR product implementations.

    Provides:
    - TARGET calendar
    - ACT/360 day counter
    - Modified Following business day convention
    - T+2 spot lag
    """

    currency: str = "EUR"
    conventions: CurrencyConventions = EUR_CONVENTIONS

    @property
    def calendar(self) -> ql.Calendar:
        """TARGET calendar."""
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

    @abstractmethod
    def classify_trade(
        self, row: pd.Series, trade_id: int, **kwargs: Any
    ) -> TradeClassification:
        """Classify a single SDR trade row."""
        pass
