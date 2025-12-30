"""
Package Detector Base Class.

Defines the abstract interface for package detection.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Any

import pandas as pd


PackageTypeLiteral = Literal[
    "OUTRIGHT",
    "CURVE",
    "FLY",
    "STRADDLE",
    "STRANGLE",
    "SPREADOVER",
    "CALENDAR",
]


@dataclass
class PackageDetectorConfig:
    """Configuration for package detection."""

    # Time window for matching (seconds)
    time_window_seconds: int = 60

    # PV01 tolerance for matching
    pv01_tolerance: float = 0.10

    # Column names
    product_col: str = "product_type"
    package_col: str = "package_type"
    exec_col: str = "execution_timestamp"
    pv01_col: str = "estimated_pv01"
    tenor_col: str = "tenor_label"
    tenor_years_col: str = "tenor_years"
    trade_id_col: str = "trade_id"
    currency_col: str = "notional_currency"
    effective_date_col: str = "effective_date"
    forward_label_col: str = "forward_label"
    forward_years_col: str = "forward_start_years"
    underlier_col: str = "UPI Underlier Name"
    platform_col: str = "Platform identifier"
    cleared_col: str = "Cleared"

    # Economic filters
    require_same_currency: bool = True
    require_same_effective_date: bool = True
    require_same_forward: bool = True
    require_same_underlier: bool = True
    require_same_platform: bool = True
    require_same_cleared_flag: bool = True

    # Product filters
    product_values: List[str] = field(default_factory=lambda: ["OIS_SWAP"])

    # Additional options
    additional_config: Dict[str, Any] = field(default_factory=dict)


class PackageDetector(ABC):
    """
    Abstract base class for package detectors.

    To implement a new package detector:
    1. Subclass PackageDetector
    2. Set the package_type class attribute
    3. Implement the detect() method
    4. Optionally set priority (lower = runs first)
    5. Register with PackageRegistry

    Example:
        class MyPackageDetector(PackageDetector):
            package_type = "MY_PACKAGE"
            priority = 50

            def detect(self, df: pd.DataFrame, config: PackageDetectorConfig) -> pd.DataFrame:
                # Detection logic
                return df
    """

    # Class attributes to be overridden
    package_type: PackageTypeLiteral = "OUTRIGHT"
    priority: int = 100  # Lower number = runs earlier in pipeline
    operates_on_outrights: bool = True  # Only process OUTRIGHT trades

    @abstractmethod
    def detect(
        self,
        df: pd.DataFrame,
        config: Optional[PackageDetectorConfig] = None,
    ) -> pd.DataFrame:
        """
        Detect packages in the DataFrame.

        This method should:
        1. Identify groups of trades that form packages
        2. Update package_type, package_id, package_legs columns
        3. Return the modified DataFrame

        Args:
            df: DataFrame with classified trades
            config: Detection configuration

        Returns:
            DataFrame with updated package information
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(package_type={self.package_type}, priority={self.priority})"
