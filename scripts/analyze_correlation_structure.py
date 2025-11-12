# ABOUTME: Analyzes correlation structure of futures returns to validate sector/currency mental model
# ABOUTME: Validates block-diagonal covariance hypothesis for multi-currency portfolios
"""
Correlation Structure Analysis for Futures Portfolios

Validates the hypothesis that futures returns have block structure:
- Currency = Sector (high intra-currency correlation)
- Maturity = Stock (instruments within currency)

Usage:
    python scripts/analyze_correlation_structure.py

To use real data instead of synthetic:
    1. Edit main() function
    2. Change: provider = SyntheticFuturesProvider()
       To:     provider = RealFuturesProvider(data_path="your_data.csv")
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import polars as pl
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, List, Tuple
from datetime import datetime

from scripts.data_providers import FuturesDataProvider, SyntheticFuturesProvider


class CorrelationAnalyzer:
    """
    Analyzes correlation structure of futures returns.

    Validates block-diagonal structure hypothesis.
    """

    def __init__(self, returns: pl.DataFrame):
        """
        Initialize analyzer.

        Args:
            returns: DataFrame with futures returns
                - Index: DatetimeIndex
                - Columns: "{currency}_{maturity}" format
                - Values: Returns (decimal)
        """
        self.returns = returns
        # Compute correlation matrix using numpy
        # Polars doesn't have DataFrame.corr(), so we use numpy
        returns_array = returns.select(pl.all().exclude("date")).to_numpy()
        corr_array = np.corrcoef(returns_array.T)
        corr_columns = [col for col in returns.columns if col != "date"]
        self.corr_matrix = pl.DataFrame(corr_array, schema=corr_columns)

        # Parse currency/maturity from column names
        self.instruments = self._parse_instruments()

    def _parse_instruments(self) -> pl.DataFrame:
        """
        Parse currency and maturity from column names.

        Returns:
            DataFrame with columns: instrument, currency, maturity
        """
        instruments = []

        for col in self.returns.columns:
            if col == "date":
                continue
            if "_" in col:
                currency, maturity = col.split("_", 1)
            else:
                # If no underscore, assume it's all currency or all maturity
                currency = col
                maturity = "Unknown"

            instruments.append({
                "instrument": col,
                "currency": currency,
                "maturity": maturity
            })

        return pl.DataFrame(instruments)

    def calculate_block_statistics(self) -> Dict[str, float]:
        """
        Calculate correlation statistics for within-currency and cross-currency blocks.

        Returns:
            Dict with keys:
                - within_currency_mean: Mean correlation within same currency
                - within_currency_std: Std dev within same currency
                - cross_currency_mean: Mean correlation across currencies
                - cross_currency_std: Std dev across currencies
        """
        within_corrs = []
        cross_corrs = []

        n = len(self.instruments)

        for i in range(n):
            curr_i = self.instruments.row(i, named=True)["currency"]

            for j in range(i + 1, n):  # Upper triangle only
                curr_j = self.instruments.row(j, named=True)["currency"]

                corr_val = self.corr_matrix.row(i)[j]

                if curr_i == curr_j:
                    within_corrs.append(corr_val)
                else:
                    cross_corrs.append(corr_val)

        return {
            "within_currency_mean": np.mean(within_corrs) if within_corrs else 0.0,
            "within_currency_std": np.std(within_corrs) if within_corrs else 0.0,
            "within_currency_min": np.min(within_corrs) if within_corrs else 0.0,
            "within_currency_max": np.max(within_corrs) if within_corrs else 0.0,
            "cross_currency_mean": np.mean(cross_corrs) if cross_corrs else 0.0,
            "cross_currency_std": np.std(cross_corrs) if cross_corrs else 0.0,
            "cross_currency_min": np.min(cross_corrs) if cross_corrs else 0.0,
            "cross_currency_max": np.max(cross_corrs) if cross_corrs else 0.0,
        }

    def validate_hypotheses(self) -> Dict[str, bool]:
        """
        Validate block structure hypotheses.

        Hypotheses:
            H1: Within-currency correlation >= 85%
            H2: Cross-currency correlation between 20-70%
            H3: Within-currency correlation > Cross-currency correlation

        Returns:
            Dict with hypothesis names as keys, validation results as bools
        """
        stats = self.calculate_block_statistics()

        h1 = stats["within_currency_mean"] >= 0.85
        h2 = 0.20 <= stats["cross_currency_mean"] <= 0.70
        h3 = stats["within_currency_mean"] > stats["cross_currency_mean"]

        return {
            "H1_within_currency_high": h1,
            "H2_cross_currency_medium": h2,
            "H3_block_structure_exists": h3,
        }

    def plot_correlation_heatmap(
        self,
        figsize: Tuple[int, int] = (12, 10),
        save_path: str = None
    ):
        """
        Plot correlation matrix heatmap with block structure highlighted.

        Args:
            figsize: Figure size (width, height)
            save_path: Optional path to save figure
        """
        # Sort instruments by currency then maturity for clear blocks
        sorted_instruments = self.instruments.sort(["currency", "maturity"])
        sorted_cols = sorted_instruments["instrument"].to_list()

        # Reorder correlation matrix
        # Select columns in sorted order
        sorted_corr = self.corr_matrix.select(sorted_cols)
        # Reorder rows by converting to numpy and back
        col_to_idx = {col: idx for idx, col in enumerate(self.corr_matrix.columns)}
        row_order = [col_to_idx[col] for col in sorted_cols]
        sorted_corr_array = sorted_corr.to_numpy()[row_order, :]
        sorted_corr = pl.DataFrame(sorted_corr_array, schema=sorted_cols)

        # Create plot
        fig, ax = plt.subplots(figsize=figsize)

        # Heatmap
        sns.heatmap(
            sorted_corr.to_numpy(),
            annot=False,
            cmap="RdYlGn",
            center=0.5,
            vmin=0,
            vmax=1,
            cbar_kws={"label": "Correlation"},
            square=True,
            ax=ax
        )

        # Add block boundaries
        currencies = sorted_instruments["currency"].unique().to_list()
        cumulative = 0
        for currency in currencies:
            n_instruments = sorted_instruments.filter(pl.col("currency") == currency).height
            cumulative += n_instruments

            # Draw boundary lines
            ax.axhline(y=cumulative, color='black', linewidth=2)
            ax.axvline(x=cumulative, color='black', linewidth=2)

        # Labels
        ax.set_title("Futures Returns Correlation Matrix (Sorted by Currency)", fontsize=14, pad=20)
        ax.set_xlabel("")
        ax.set_ylabel("")

        # Rotate labels
        ax.set_xticklabels(ax.get_xticklabels(), rotation=45, ha="right")
        ax.set_yticklabels(ax.get_yticklabels(), rotation=0)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            print(f"Heatmap saved to: {save_path}")

        return fig

    def plot_block_comparison(
        self,
        figsize: Tuple[int, int] = (10, 6),
        save_path: str = None
    ):
        """
        Plot histogram comparing within-currency vs cross-currency correlations.

        Args:
            figsize: Figure size
            save_path: Optional path to save figure
        """
        # Extract correlations
        within_corrs = []
        cross_corrs = []

        n = len(self.instruments)
        for i in range(n):
            curr_i = self.instruments.row(i, named=True)["currency"]
            for j in range(i + 1, n):
                curr_j = self.instruments.row(j, named=True)["currency"]
                corr_val = self.corr_matrix.row(i)[j]

                if curr_i == curr_j:
                    within_corrs.append(corr_val)
                else:
                    cross_corrs.append(corr_val)

        # Create plot
        fig, ax = plt.subplots(figsize=figsize)

        # Histograms
        ax.hist(within_corrs, bins=20, alpha=0.6, label="Within-Currency", color="green")
        ax.hist(cross_corrs, bins=20, alpha=0.6, label="Cross-Currency", color="blue")

        # Add mean lines
        ax.axvline(np.mean(within_corrs), color="darkgreen", linestyle="--",
                   linewidth=2, label=f"Within Mean: {np.mean(within_corrs):.2f}")
        ax.axvline(np.mean(cross_corrs), color="darkblue", linestyle="--",
                   linewidth=2, label=f"Cross Mean: {np.mean(cross_corrs):.2f}")

        # Labels
        ax.set_xlabel("Correlation", fontsize=12)
        ax.set_ylabel("Frequency", fontsize=12)
        ax.set_title("Distribution of Correlations: Within vs Cross Currency", fontsize=14)
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            print(f"Histogram saved to: {save_path}")

        return fig

    def generate_report(self) -> str:
        """
        Generate text report of findings.

        Returns:
            Formatted string report
        """
        stats = self.calculate_block_statistics()
        hypotheses = self.validate_hypotheses()

        report = []
        report.append("=" * 70)
        report.append("CORRELATION STRUCTURE ANALYSIS REPORT")
        report.append("=" * 70)
        report.append("")

        # Dataset info
        num_instruments = len([col for col in self.returns.columns if col != "date"])
        report.append("Dataset:")
        report.append(f"  Instruments: {num_instruments}")
        report.append(f"  Observations: {len(self.returns)}")
        if "date" in self.returns.columns:
            date_col = self.returns["date"]
            report.append(f"  Date range: {date_col[0]} to {date_col[-1]}")
        report.append("")

        # Currency breakdown
        currency_counts = self.instruments.group_by("currency").agg(pl.len().alias("count"))
        report.append("Instruments by Currency:")
        for row in currency_counts.iter_rows(named=True):
            report.append(f"  {row['currency']}: {row['count']} instruments")
        report.append("")

        # Block statistics
        report.append("Correlation Statistics:")
        report.append("")
        report.append("Within-Currency (same currency, different maturities):")
        report.append(f"  Mean:  {stats['within_currency_mean']:.3f}")
        report.append(f"  Std:   {stats['within_currency_std']:.3f}")
        report.append(f"  Range: [{stats['within_currency_min']:.3f}, {stats['within_currency_max']:.3f}]")
        report.append("")
        report.append("Cross-Currency (different currencies):")
        report.append(f"  Mean:  {stats['cross_currency_mean']:.3f}")
        report.append(f"  Std:   {stats['cross_currency_std']:.3f}")
        report.append(f"  Range: [{stats['cross_currency_min']:.3f}, {stats['cross_currency_max']:.3f}]")
        report.append("")

        # Hypothesis validation
        report.append("Hypothesis Validation:")
        report.append("")
        report.append(f"H1: Within-currency correlation >= 85%")
        report.append(f"    Result: {'✓ PASS' if hypotheses['H1_within_currency_high'] else '✗ FAIL'}")
        report.append(f"    Actual: {stats['within_currency_mean']:.1%}")
        report.append("")
        report.append(f"H2: Cross-currency correlation between 20-70%")
        report.append(f"    Result: {'✓ PASS' if hypotheses['H2_cross_currency_medium'] else '✗ FAIL'}")
        report.append(f"    Actual: {stats['cross_currency_mean']:.1%}")
        report.append("")
        report.append(f"H3: Clear block structure exists (within > cross)")
        report.append(f"    Result: {'✓ PASS' if hypotheses['H3_block_structure_exists'] else '✗ FAIL'}")
        report.append(f"    Difference: {stats['within_currency_mean'] - stats['cross_currency_mean']:.1%}")
        report.append("")

        # Recommendation
        report.append("Recommendation:")
        if all(hypotheses.values()):
            report.append("  ✓ Block-diagonal covariance structure is VALIDATED")
            report.append("  ✓ Proceed with BlockDiagonalCovariance implementation")
            report.append("  ✓ Expected benefits:")
            report.append("    - Better condition number (more stable)")
            report.append("    - Computational efficiency (parallel blocks)")
            report.append("    - Better out-of-sample performance")
        else:
            report.append("  ✗ Block structure NOT clearly present")
            report.append("  → Stick with full Ledoit-Wolf shrinkage")
            report.append("  → Re-evaluate with real data")
        report.append("")

        report.append("=" * 70)

        return "\n".join(report)


def main():
    """
    Main analysis workflow.

    To use real data: Change provider to RealFuturesProvider
    """
    print("="*70)
    print("Phase 1: Correlation Structure Validation")
    print("="*70)
    print()

    # =========================================================================
    # STEP 1: Load Data
    # =========================================================================

    print("STEP 1: Loading futures returns data...")
    print()

    # Use synthetic data for now
    # TO USE REAL DATA, uncomment and modify:
    # from scripts.data_providers import RealFuturesProvider
    # provider = RealFuturesProvider(data_path="path/to/your/data.csv")

    provider = SyntheticFuturesProvider(
        within_currency_corr=0.92,
        cross_currency_corr=0.40,
        volatility=0.0005,
        seed=42
    )

    returns = provider.get_returns(
        currencies=["USD", "EUR", "GBP", "JPY"],
        maturities=["3M", "6M", "1Y", "2Y", "5Y", "10Y"],
        start_date="2023-01-01",
        end_date="2024-12-31",
        frequency="D"
    )

    num_instruments = len([col for col in returns.columns if col != "date"])
    print(f"✓ Loaded {returns.height} observations for {num_instruments} instruments")
    if "date" in returns.columns:
        date_col = returns["date"]
        print(f"  Date range: {date_col[0].date()} to {date_col[-1].date()}")
    print()

    # =========================================================================
    # STEP 2: Analyze Correlation Structure
    # =========================================================================

    print("STEP 2: Analyzing correlation structure...")
    print()

    analyzer = CorrelationAnalyzer(returns)

    # Calculate statistics
    stats = analyzer.calculate_block_statistics()
    print(f"Within-currency correlation: {stats['within_currency_mean']:.1%} ± {stats['within_currency_std']:.1%}")
    print(f"Cross-currency correlation:  {stats['cross_currency_mean']:.1%} ± {stats['cross_currency_std']:.1%}")
    print()

    # =========================================================================
    # STEP 3: Validate Hypotheses
    # =========================================================================

    print("STEP 3: Validating hypotheses...")
    print()

    hypotheses = analyzer.validate_hypotheses()
    for hyp_name, result in hypotheses.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {hyp_name}")
    print()

    # =========================================================================
    # STEP 4: Generate Visualizations
    # =========================================================================

    print("STEP 4: Generating visualizations...")
    print()

    # Heatmap
    analyzer.plot_correlation_heatmap(
        save_path="docs/research/correlation_heatmap.png"
    )
    print("✓ Correlation heatmap created")

    # Histogram
    analyzer.plot_block_comparison(
        save_path="docs/research/correlation_distribution.png"
    )
    print("✓ Distribution plot created")
    print()

    # =========================================================================
    # STEP 5: Generate Report
    # =========================================================================

    print("STEP 5: Generating report...")
    print()

    report = analyzer.generate_report()
    print(report)

    # Save report to file
    report_path = "docs/research/arbs_correlation_structure.md"
    with open(report_path, "w") as f:
        f.write("# ARBS Futures Correlation Structure Analysis\n\n")
        f.write("**Generated**: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
        f.write("```\n")
        f.write(report)
        f.write("\n```\n")

    print(f"✓ Report saved to: {report_path}")
    print()

    # =========================================================================
    # STEP 6: Decision Point
    # =========================================================================

    print("="*70)
    print("DECISION POINT")
    print("="*70)
    print()

    if all(hypotheses.values()):
        print("✓ All hypotheses validated")
        print("✓ Block structure confirmed")
        print()
        print("NEXT STEP: Proceed to Phase 2")
        print("  → Implement BlockDiagonalCovariance")
        print("  → Expected timeline: 2-3 days")
    else:
        print("✗ Hypotheses not fully validated")
        print()
        print("NEXT STEP: Options")
        print("  A) Use real data and re-run analysis")
        print("  B) Adjust hypothesis thresholds")
        print("  C) Stick with current Ledoit-Wolf approach")

    print()
    print("="*70)


if __name__ == "__main__":
    main()
