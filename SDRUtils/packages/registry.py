"""
Package Registry - Central registry for package detectors.

Manages registration and orchestration of package detection.
"""

from typing import Dict, List, Optional

import pandas as pd

from SDRUtils.packages.base import PackageDetector, PackageDetectorConfig


class PackageRegistry:
    """
    Central registry for package detectors.

    Detectors are run in priority order (lowest priority number first).
    Each detector only processes trades that haven't been assigned
    to a package yet (OUTRIGHT trades).
    """

    _detectors: List[PackageDetector] = []
    _by_type: Dict[str, PackageDetector] = {}

    @classmethod
    def register(cls, detector: PackageDetector) -> None:
        """
        Register a package detector.

        Args:
            detector: PackageDetector instance to register
        """
        cls._detectors.append(detector)
        cls._by_type[detector.package_type] = detector
        # Keep sorted by priority
        cls._detectors.sort(key=lambda d: d.priority)

    @classmethod
    def unregister(cls, package_type: str) -> Optional[PackageDetector]:
        """
        Unregister a package detector by type.

        Args:
            package_type: The package type to unregister

        Returns:
            The removed detector, or None if not found
        """
        if package_type in cls._by_type:
            detector = cls._by_type.pop(package_type)
            cls._detectors = [d for d in cls._detectors if d.package_type != package_type]
            return detector
        return None

    @classmethod
    def get(cls, package_type: str) -> Optional[PackageDetector]:
        """Get a detector by package type."""
        return cls._by_type.get(package_type)

    @classmethod
    def list_detectors(cls) -> List[PackageDetector]:
        """Get list of all registered detectors in priority order."""
        return list(cls._detectors)

    @classmethod
    def detect_all(
        cls,
        df: pd.DataFrame,
        config: Optional[PackageDetectorConfig] = None,
    ) -> pd.DataFrame:
        """
        Run all registered detectors in priority order.

        Args:
            df: DataFrame with classified trades
            config: Detection configuration (uses defaults if None)

        Returns:
            DataFrame with all package detections applied
        """
        if config is None:
            config = PackageDetectorConfig()

        result = df.copy()

        # Initialize package columns if not present
        if config.package_col not in result.columns:
            result[config.package_col] = "OUTRIGHT"
        if "package_id" not in result.columns:
            result["package_id"] = None
        if "package_legs" not in result.columns:
            result["package_legs"] = None

        # Run each detector in priority order
        for detector in cls._detectors:
            result = detector.detect(result, config)

        return result

    @classmethod
    def clear(cls) -> None:
        """Clear all registered detectors."""
        cls._detectors.clear()
        cls._by_type.clear()


def detect_packages(
    df: pd.DataFrame,
    config: Optional[PackageDetectorConfig] = None,
    detectors: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Detect packages in a DataFrame of classified trades.

    This is the main entry point for package detection.
    Runs all registered detectors (or specified subset) in priority order.

    Args:
        df: DataFrame with classified trades
        config: Detection configuration (uses defaults if None)
        detectors: Optional list of detector types to run (runs all if None)

    Returns:
        DataFrame with package information added
    """
    if config is None:
        config = PackageDetectorConfig()

    if detectors is None:
        return PackageRegistry.detect_all(df, config)

    # Run only specified detectors
    result = df.copy()

    # Initialize package columns if not present
    if config.package_col not in result.columns:
        result[config.package_col] = "OUTRIGHT"
    if "package_id" not in result.columns:
        result["package_id"] = None
    if "package_legs" not in result.columns:
        result["package_legs"] = None

    for detector_type in detectors:
        detector = PackageRegistry.get(detector_type)
        if detector:
            result = detector.detect(result, config)

    return result
