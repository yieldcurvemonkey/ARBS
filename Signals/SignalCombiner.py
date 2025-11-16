# ABOUTME: SignalCombiner for sophisticated multi-signal combination using equal weight, IC-weighted, and orthogonalization
# ABOUTME: Implements Grinold-Kahn framework for maximizing signal diversification and skill-based weighting
"""
SignalCombiner - Sophisticated Multi-Signal Combination

Combines multiple alpha signals using three methods:
1. Equal Weight (baseline): Simple average of signals
2. IC-Weighted (better): Weight by forecasting skill (Information Coefficient)
3. Orthogonalization (best): Remove correlation to maximize diversification

Grinold-Kahn Framework:
    IR = IC × √BR

Where:
    IR = Information Ratio (risk-adjusted return)
    IC = Information Coefficient (forecast skill)
    BR = Breadth (number of independent bets)

Goal: Maximize BR by making signals independent (orthogonal)

Methods:

1. Equal Weight:
   combined[i] = mean(signal1[i], signal2[i], ..., signalN[i])

2. IC-Weighted:
   weight[k] = IC[k] / sum(|IC[j]|)
   combined[i] = sum(weight[k] × signal[k][i])

3. Orthogonalization:
   - Use Gram-Schmidt process to remove correlation
   - Or regression residuals: signal2_orth = signal2 - β × signal1
   - Then combine orthogonalized signals

Example:
    >>> combiner = SignalCombiner()
    >>> signals = {
    ...     'carry': {'SFRZ4': 1.5, 'SFRH5': -0.5},
    ...     'momentum': {'SFRZ4': -1.0, 'SFRH5': 2.0}
    ... }
    >>>
    >>> # Equal weight
    >>> combined = combiner.combine(signals, method='equal')
    >>>
    >>> # IC-weighted
    >>> ic_estimates = {'carry': 0.08, 'momentum': 0.05}
    >>> combined = combiner.combine(signals, method='ic_weighted', ic_estimates=ic_estimates)
    >>>
    >>> # Orthogonalization
    >>> combined = combiner.combine(signals, method='orthogonal')
"""

from typing import Dict, Optional
import numpy as np


class SignalCombiner:
    """
    Combines multiple alpha signals using sophisticated methods.

    Supports three combination approaches:
    - Equal weight: Simple averaging (baseline)
    - IC-weighted: Weight by forecasting skill (better)
    - Orthogonalization: Remove correlation (best)

    Attributes:
        method: Default combination method
        ic_estimates: Dict mapping signal_name -> IC estimate

    Methods:
        combine: Combine signals using specified method
        set_ic_estimates: Update IC estimates for online learning
    """

    def __init__(self, method: str = 'equal', ic_estimates: Optional[Dict[str, float]] = None):
        """
        Initialize SignalCombiner.

        Args:
            method: Default combination method ('equal', 'ic_weighted', 'orthogonal')
            ic_estimates: IC estimates for each signal (optional, can be set later)
                         Example: {'carry': 0.08, 'momentum': 0.05}
        """
        self.method = method
        self.ic_estimates = ic_estimates or {}

    def set_ic_estimates(self, ic_estimates: Dict[str, float]) -> None:
        """
        Update IC estimates (for online learning scenarios).

        Args:
            ic_estimates: Dict mapping signal_name -> IC estimate
        """
        self.ic_estimates = ic_estimates

    def combine(
        self,
        signals: Dict[str, Dict[str, float]],
        method: Optional[str] = None,
        ic_estimates: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        Combine multiple signals using specified method.

        Args:
            signals: Dict of signal_name -> {instrument -> z_score}
                     Example: {'carry': {'SFRZ4': 1.5, 'SFRH5': -0.5},
                               'momentum': {'SFRZ4': -1.0, 'SFRH5': 2.0}}
            method: Override instance method for this call (optional)
                    - 'equal': Equal weight (simple average)
                    - 'ic_weighted': Weight by IC (forecasting skill)
                    - 'orthogonal': Orthogonalization (remove correlation)
            ic_estimates: Override instance IC estimates for this call (optional)
                         Example: {'carry': 0.08, 'momentum': 0.05}

        Returns:
            Dict mapping instrument -> combined_z_score

        Raises:
            ValueError: If method is unknown or ic_estimates missing for ic_weighted

        Example:
            Equal weight:
            >>> combiner = SignalCombiner()
            >>> signals = {'s1': {'A': 1.0, 'B': -1.0},
            ...            's2': {'A': -1.0, 'B': 1.0}}
            >>> combiner.combine(signals, method='equal')
            {'A': 0.0, 'B': 0.0}

            IC-weighted:
            >>> ic_estimates = {'s1': 0.10, 's2': 0.02}
            >>> combiner.combine(signals, method='ic_weighted', ic_estimates=ic_estimates)
            {'A': 0.667, 'B': -0.667}
        """
        # Use instance values if not overridden
        if method is None:
            method = self.method
        if ic_estimates is None:
            ic_estimates = self.ic_estimates

        # Handle empty signals
        if not signals:
            return {}

        # Validate method
        if method not in ['equal', 'ic_weighted', 'orthogonal']:
            raise ValueError(f"Unknown method: {method}. Use 'equal', 'ic_weighted', or 'orthogonal'")

        # Route to appropriate method
        if method == 'equal':
            return self._combine_equal_weight(signals)
        elif method == 'ic_weighted':
            return self._combine_ic_weighted(signals, ic_estimates)
        elif method == 'orthogonal':
            return self._combine_orthogonal(signals)

    def _combine_equal_weight(
        self,
        signals: Dict[str, Dict[str, float]]
    ) -> Dict[str, float]:
        """
        Combine signals using equal weighting.

        Formula:
            combined[i] = mean(signal1[i], signal2[i], ..., signalN[i])

        Args:
            signals: Dict of signal_name -> {instrument -> z_score}

        Returns:
            Dict mapping instrument -> combined z_score

        Note:
            Handles missing instruments gracefully by averaging only
            available signals for each instrument.
        """
        # Get all unique instruments
        all_instruments = set()
        for signal_dict in signals.values():
            all_instruments.update(signal_dict.keys())

        # Combine signals
        combined = {}
        for inst in all_instruments:
            # Collect signal values for this instrument (skip NaN)
            values = []
            for signal_dict in signals.values():
                if inst in signal_dict:
                    value = signal_dict[inst]
                    if not np.isnan(value):
                        values.append(value)

            # Average available values
            if values:
                combined[inst] = np.mean(values)
            else:
                combined[inst] = 0.0  # No valid signals

        return combined

    def _combine_ic_weighted(
        self,
        signals: Dict[str, Dict[str, float]],
        ic_estimates: Optional[Dict[str, float]]
    ) -> Dict[str, float]:
        """
        Combine signals using IC-weighting.

        Formula:
            weight[k] = IC[k] / sum(|IC[j]|)
            combined[i] = sum(weight[k] × signal[k][i])

        Higher IC signals get more weight (better forecasting skill).
        Negative IC signals are inverted (contra-indicator).

        Args:
            signals: Dict of signal_name -> {instrument -> z_score}
            ic_estimates: Dict of signal_name -> IC

        Returns:
            Dict mapping instrument -> combined z_score

        Raises:
            ValueError: If ic_estimates is None or empty, or missing signal names

        Example:
            >>> signals = {'carry': {'A': 1.0}, 'momentum': {'A': 0.0}}
            >>> ic_estimates = {'carry': 0.10, 'momentum': 0.02}
            >>> # Weight: carry = 0.10/0.12 = 0.833, momentum = 0.02/0.12 = 0.167
            >>> # Result: 1.0 * 0.833 + 0.0 * 0.167 = 0.833
        """
        if ic_estimates is None or not ic_estimates:
            raise ValueError("ic_estimates required for ic_weighted method")

        # Validate all signal names have IC estimates
        missing_signals = set(signals.keys()) - set(ic_estimates.keys())
        if missing_signals:
            raise ValueError(f"ic_estimates missing for signals: {missing_signals}")

        # Calculate weights from ICs
        total_ic = sum(abs(ic_estimates[name]) for name in signals.keys())

        if total_ic < 1e-10:
            # All ICs are zero → no predictive power → return zeros
            all_instruments = set()
            for signal_dict in signals.values():
                all_instruments.update(signal_dict.keys())
            return {inst: 0.0 for inst in all_instruments}

        # Normalize ICs to weights (can be negative for contra-indicators)
        weights = {
            name: ic_estimates[name] / total_ic
            for name in signals.keys()
        }

        # Get all unique instruments
        all_instruments = set()
        for signal_dict in signals.values():
            all_instruments.update(signal_dict.keys())

        # Combine signals with IC weights
        combined = {}
        for inst in all_instruments:
            weighted_sum = 0.0
            for signal_name, signal_dict in signals.items():
                if inst in signal_dict:
                    value = signal_dict[inst]
                    if not np.isnan(value):
                        weighted_sum += weights[signal_name] * value

            combined[inst] = weighted_sum

        return combined

    def _combine_orthogonal(
        self,
        signals: Dict[str, Dict[str, float]]
    ) -> Dict[str, float]:
        """
        Combine signals using orthogonalization.

        Uses Gram-Schmidt process to remove correlation between signals,
        maximizing diversification benefit (breadth in Grinold-Kahn).

        Process:
            1. Keep first signal as-is
            2. For each subsequent signal, remove component correlated with previous signals
            3. Average orthogonalized signals

        Formula (for 2 signals):
            v1 = signal1
            v2_orth = signal2 - (signal2 · signal1 / signal1 · signal1) × signal1
            combined = (v1 + v2_orth) / 2

        Args:
            signals: Dict of signal_name -> {instrument -> z_score}

        Returns:
            Dict mapping instrument -> combined z_score

        Note:
            Orthogonalization maximizes BR (breadth) in Fundamental Law:
                IR = IC × √BR
            By making signals independent, we maximize effective number of bets.
        """
        signal_names = list(signals.keys())

        # Single signal → nothing to orthogonalize
        if len(signal_names) == 1:
            return signals[signal_names[0]].copy()

        # Get all instruments
        all_instruments = set()
        for signal_dict in signals.values():
            all_instruments.update(signal_dict.keys())
        all_instruments = sorted(all_instruments)  # Consistent ordering

        # Convert signals to matrix format
        # Rows = instruments, Columns = signals
        signal_matrix = np.zeros((len(all_instruments), len(signal_names)))

        for j, signal_name in enumerate(signal_names):
            signal_dict = signals[signal_name]
            for i, inst in enumerate(all_instruments):
                signal_matrix[i, j] = signal_dict.get(inst, 0.0)

        # Apply Gram-Schmidt orthogonalization
        orthogonal_matrix = self._gram_schmidt(signal_matrix)

        # Average orthogonalized signals
        combined_vector = np.mean(orthogonal_matrix, axis=1)

        # Convert back to dict
        combined = {
            inst: combined_vector[i]
            for i, inst in enumerate(all_instruments)
        }

        return combined

    def _gram_schmidt(self, matrix: np.ndarray) -> np.ndarray:
        """
        Apply Gram-Schmidt orthogonalization to signal matrix.

        Args:
            matrix: N×M matrix (N instruments, M signals)

        Returns:
            N×M orthogonalized matrix where columns are orthogonal

        Note:
            This is the classical Gram-Schmidt process:
            v1 = u1
            v2 = u2 - proj(u2, v1)
            v3 = u3 - proj(u3, v1) - proj(u3, v2)
            etc.

            where proj(u, v) = (u · v / v · v) × v
        """
        n_rows, n_cols = matrix.shape
        orthogonal = np.zeros_like(matrix)

        for j in range(n_cols):
            # Start with original signal
            vec = matrix[:, j].copy()

            # Remove projections onto all previous orthogonal vectors
            for i in range(j):
                prev_vec = orthogonal[:, i]
                # Projection: (vec · prev) / (prev · prev) × prev
                dot_product = np.dot(vec, prev_vec)
                norm_squared = np.dot(prev_vec, prev_vec)

                if norm_squared > 1e-10:  # Avoid division by zero
                    projection = (dot_product / norm_squared) * prev_vec
                    vec = vec - projection

            orthogonal[:, j] = vec

        return orthogonal

    def __repr__(self) -> str:
        """String representation."""
        return "SignalCombiner(methods=['equal', 'ic_weighted', 'orthogonal'])"
