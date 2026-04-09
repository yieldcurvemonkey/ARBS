"""
CCP Basis (CME-LCH) Fair Value Model

Hybrid approach: multi-factor regression with swap curve PCA enrichment.
Based on Benos, Huang, Menkveld, Sherrick (BIS WP826) framework.

Factors:
  - Swap curve PCA scores (PC1=level, PC2=slope, PC3=curvature)
  - SOFR-EFFR spread (dealer funding cost)
  - BGCR-EFFR spread (repo-OIS collateral cost)
  - BBB Corporate OAS (dealer credit / debt overhang proxy)
  - Realized rate volatility (IM cost scaling)
  - Rate level at tenor
  - Quarter-end / year-end dummies (balance sheet effects)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
import datetime

import numpy as np
import pandas as pd
import statsmodels.api as sm

from RVUtils.df_based_pca_risk_model import (
    CurvePCAModel,
    fit_curve_pca_from_timeseries,
)
from RVUtils.mean_reversion import simulate_mean_reversion_ou


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class CCPBasisFairValueResult:
    """Per-tenor regression output."""

    tenor: str
    basis_ts: pd.Series
    fair_value_ts: pd.Series
    residual_ts: pd.Series
    residual_zscore: pd.Series
    regression_result: Any  # statsmodels RegressionResultsWrapper
    factor_df: pd.DataFrame
    ou_forecast: Optional[pd.DataFrame] = None
    first_passage_time: Optional[float] = None


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

# FRED series used as macro factors
_FRED_SERIES: Dict[str, str] = {
    "SOFR": "SOFR",
    "EFFR": "DFF",
    "BGCR": "BGCR",
    "BBB_OAS": "BAMLC0A4CBBB",
}

# Sensible default tenors for the swap-curve PCA
_DEFAULT_PCA_TENORS: List[str] = [
    "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y",
]


class CCPBasisFairValueModel:
    """Fair value model for CME-LCH clearing house basis.

    Parameters
    ----------
    tenors : list[str]
        Basis tenors to model, e.g. ``["5Y", "10Y", "30Y"]``.
    start_date, end_date : datetime.date
        Analysis window.
    index : str
        Floating index, default ``"SOFR"``.
    pca_tenors : list[str] | None
        Tenors fed into the swap-curve PCA.  ``None`` => ``_DEFAULT_PCA_TENORS``.
    n_pcs : int
        Number of principal components to include as regressors.
    window : int | None
        Rolling regression window.  ``None`` => expanding (full sample OLS).
    realized_vol_window : int
        Rolling window for realized rate volatility (business days).
    ou_steps : int
        OU forecast horizon in business days.
    """

    def __init__(
        self,
        tenors: List[str],
        start_date: datetime.date,
        end_date: datetime.date,
        *,
        index: str = "SOFR",
        pca_tenors: Optional[List[str]] = None,
        n_pcs: int = 3,
        window: Optional[int] = None,
        realized_vol_window: int = 20,
        ou_steps: int = 63,
    ):
        self.tenors = tenors
        self.start_date = start_date
        self.end_date = end_date
        self.index = index
        self.pca_tenors = pca_tenors or list(_DEFAULT_PCA_TENORS)
        self.n_pcs = n_pcs
        self.window = window
        self.realized_vol_window = realized_vol_window
        self.ou_steps = ou_steps

        # internal state
        self._raw_data: Optional[pd.DataFrame] = None
        self._factor_df: Optional[pd.DataFrame] = None
        self._pca_model: Optional[CurvePCAModel] = None
        self._pca_scores: Optional[pd.DataFrame] = None
        self._results: Dict[str, CCPBasisFairValueResult] = {}

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def fetch_data(self) -> pd.DataFrame:
        """Fetch CCP basis for all tenors + FRED macro series.

        Returns the combined raw DataFrame (also stored as ``self._raw_data``).
        """
        from MDP.IRClearingHouseBasisSwaps.IRClearingHouseBasisSwapsMDP import (
            IRClearingHouseBasisSwapsMDP,
        )
        from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.FredFetcher import Fred

        # --- 1. CCP basis for each unique tenor ---
        all_tenors = sorted(
            set(self.tenors) | set(self.pca_tenors),
            key=lambda t: _tenor_sort_key(t),
        )

        basis_mdp = IRClearingHouseBasisSwapsMDP()
        basis_frames: Dict[str, pd.Series] = {}
        rate_frames: Dict[str, pd.Series] = {}

        for tenor in all_tenors:
            try:
                pricer = basis_mdp.get_pricer(
                    {
                        "tenor": tenor,
                        "index": self.index,
                        "start_date": self.start_date,
                        "end_date": self.end_date,
                    }
                )
                bd = pricer.basis_data
                basis_frames[tenor] = bd["basis_bps"].rename(f"basis_{tenor}")
                rate_frames[tenor] = bd["rate_a"].rename(f"rate_{tenor}")
            except Exception as exc:
                print(f"[CCPBasisFV] Warning: could not fetch tenor {tenor}: {exc}")

        if not basis_frames:
            raise RuntimeError("No CCP basis data fetched for any tenor.")

        basis_df = pd.concat(basis_frames.values(), axis=1)
        rate_df = pd.concat(rate_frames.values(), axis=1)

        # --- 2. FRED macro data ---
        fred_frames: Dict[str, pd.Series] = {}
        try:
            fred = Fred()
            for name, series_id in _FRED_SERIES.items():
                try:
                    s = fred.get_series(
                        series_id,
                        observation_start=self.start_date,
                        observation_end=self.end_date,
                    )
                    s.index = pd.to_datetime(s.index).normalize()
                    fred_frames[name] = s.rename(name)
                except Exception as exc:
                    print(f"[CCPBasisFV] Warning: FRED {series_id} ({name}): {exc}")
        except Exception as exc:
            print(f"[CCPBasisFV] Warning: Fred client init failed: {exc}")

        fred_df = (
            pd.concat(fred_frames.values(), axis=1) if fred_frames else pd.DataFrame()
        )

        # --- 3. Merge ---
        raw = pd.concat([basis_df, rate_df, fred_df], axis=1)
        raw.index = pd.to_datetime(raw.index).normalize()
        raw = raw.sort_index()

        self._raw_data = raw
        return raw

    # ------------------------------------------------------------------
    # Factor engineering
    # ------------------------------------------------------------------

    def build_factors(self, raw_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Engineer the factor matrix from raw data.

        Returns the aligned factor DataFrame (also stored as ``self._factor_df``).
        """
        if raw_df is None:
            raw_df = self._raw_data
        if raw_df is None:
            raise ValueError("No raw data available. Call fetch_data() first.")

        factors = pd.DataFrame(index=raw_df.index)

        # --- 1. Swap-curve PCA ---
        pca_cols = [
            f"rate_{t}" for t in self.pca_tenors if f"rate_{t}" in raw_df.columns
        ]
        if len(pca_cols) >= 3:
            rate_wide = raw_df[pca_cols].dropna()
            # Relabel to bare tenor strings for the PCA helper
            rate_wide.columns = [c.replace("rate_", "") for c in rate_wide.columns]

            pca_model, pca_scores = fit_curve_pca_from_timeseries(
                rate_wide, use_changes=True, sort_by_tenor=True
            )
            self._pca_model = pca_model
            self._pca_scores = pca_scores

            for i in range(min(self.n_pcs, pca_scores.shape[1])):
                pc_col = f"PC{i + 1}"
                factors[pc_col] = pca_scores[pc_col]

        # --- 2. Funding spread: SOFR - EFFR (bps) ---
        if "SOFR" in raw_df.columns and "EFFR" in raw_df.columns:
            factors["sofr_ois_spread"] = (raw_df["SOFR"] - raw_df["EFFR"]) * 100

        # --- 3. Repo-OIS spread: BGCR - EFFR (bps) ---
        if "BGCR" in raw_df.columns and "EFFR" in raw_df.columns:
            factors["repo_ois_spread"] = (raw_df["BGCR"] - raw_df["EFFR"]) * 100

        # --- 4. BBB Corporate OAS (already in bps from FRED) ---
        if "BBB_OAS" in raw_df.columns:
            factors["bbb_oas"] = raw_df["BBB_OAS"]

        # --- 5. Realized rate volatility per modelled tenor ---
        for tenor in self.tenors:
            rate_col = f"rate_{tenor}"
            if rate_col in raw_df.columns:
                daily_chg_bps = raw_df[rate_col].diff() * 10_000
                factors[f"realized_vol_{tenor}"] = daily_chg_bps.rolling(
                    self.realized_vol_window, min_periods=max(10, self.realized_vol_window // 2)
                ).std()

        # --- 6. Rate level per modelled tenor ---
        for tenor in self.tenors:
            rate_col = f"rate_{tenor}"
            if rate_col in raw_df.columns:
                factors[f"rate_level_{tenor}"] = raw_df[rate_col]

        # --- 7. Calendar dummies ---
        dt_idx = pd.to_datetime(factors.index)
        month = dt_idx.month
        day = dt_idx.day
        is_qtr_month = month.isin([3, 6, 9, 12])
        is_late_month = day >= 25

        factors["qtr_end"] = (is_qtr_month & is_late_month).astype(float)
        factors["yr_end"] = ((month == 12) & is_late_month).astype(float)

        self._factor_df = factors
        return factors

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def _select_factors_for_tenor(self, tenor: str) -> List[str]:
        """Return the column names from ``_factor_df`` relevant for *tenor*."""
        fdf = self._factor_df
        common = [
            c
            for c in fdf.columns
            if not c.startswith(("realized_vol_", "rate_level_"))
        ]
        tenor_specific = [f"realized_vol_{tenor}", f"rate_level_{tenor}"]
        tenor_specific = [c for c in tenor_specific if c in fdf.columns]
        return common + tenor_specific

    def fit(
        self,
        tenor: str,
        factors_df: Optional[pd.DataFrame] = None,
    ) -> CCPBasisFairValueResult:
        """Fit fair-value regression for a single tenor.

        Returns a :class:`CCPBasisFairValueResult` (also stored internally).
        """
        if factors_df is None:
            factors_df = self._factor_df
        if factors_df is None:
            raise ValueError("No factors. Call build_factors() first.")
        if self._raw_data is None:
            raise ValueError("No raw data. Call fetch_data() first.")

        basis_col = f"basis_{tenor}"
        if basis_col not in self._raw_data.columns:
            raise ValueError(f"No basis data for tenor {tenor}")

        y = self._raw_data[basis_col].copy()
        y.name = f"basis_{tenor}"

        x_cols = self._select_factors_for_tenor(tenor)
        X = factors_df[x_cols].copy()

        # Align & drop NaN
        aligned = pd.concat([y, X], axis=1).dropna()
        if aligned.shape[0] < 30:
            raise ValueError(
                f"Not enough observations for {tenor} after alignment: {aligned.shape[0]}"
            )

        y_aligned = aligned.iloc[:, 0]
        X_aligned = aligned.iloc[:, 1:]

        # Drop zero-variance columns
        X_aligned = X_aligned.loc[:, X_aligned.std() > 1e-12]

        # OLS with constant
        X_design = sm.add_constant(X_aligned)
        ols_model = sm.OLS(y_aligned, X_design)
        reg_result = ols_model.fit()

        fair_value = reg_result.fittedvalues
        fair_value.name = f"fair_value_{tenor}"

        residual = y_aligned - fair_value
        residual.name = f"residual_{tenor}"

        # Expanding z-score of residual
        resid_mean = residual.expanding(min_periods=20).mean()
        resid_std = residual.expanding(min_periods=20).std()
        residual_zscore = (residual - resid_mean) / resid_std.replace(0, np.nan)
        residual_zscore.name = f"zscore_{tenor}"

        # OU mean-reversion forecast on residuals
        ou_forecast = None
        fpt = None
        try:
            resid_df = residual.dropna().to_frame()
            if len(resid_df) > 50:
                ou_forecast, fpt = simulate_mean_reversion_ou(
                    resid_df, steps=self.ou_steps
                )
        except Exception:
            pass

        result = CCPBasisFairValueResult(
            tenor=tenor,
            basis_ts=y_aligned,
            fair_value_ts=fair_value,
            residual_ts=residual,
            residual_zscore=residual_zscore,
            regression_result=reg_result,
            factor_df=X_aligned,
            ou_forecast=ou_forecast,
            first_passage_time=fpt,
        )
        self._results[tenor] = result
        return result

    def fit_all(self) -> Dict[str, CCPBasisFairValueResult]:
        """Fetch data (if needed), build factors, fit every tenor.

        Returns ``{tenor: CCPBasisFairValueResult}``.
        """
        if self._raw_data is None:
            self.fetch_data()
        if self._factor_df is None:
            self.build_factors()

        results: Dict[str, CCPBasisFairValueResult] = {}
        for tenor in self.tenors:
            try:
                results[tenor] = self.fit(tenor)
            except Exception as exc:
                print(f"[CCPBasisFV] Warning: fit failed for {tenor}: {exc}")

        self._results = results
        return results

    # ------------------------------------------------------------------
    # Diagnostics & summary
    # ------------------------------------------------------------------

    def summary(self) -> pd.DataFrame:
        """Cross-tenor summary table."""
        rows = []
        for tenor, r in self._results.items():
            reg = r.regression_result
            rows.append(
                {
                    "tenor": tenor,
                    "R2": round(reg.rsquared, 4),
                    "adj_R2": round(reg.rsquared_adj, 4),
                    "n_obs": int(reg.nobs),
                    "current_basis_bps": _last(r.basis_ts),
                    "current_fv_bps": _last(r.fair_value_ts),
                    "current_residual_bps": _last(r.residual_ts),
                    "current_zscore": _last(r.residual_zscore),
                    "residual_mean": round(r.residual_ts.mean(), 4),
                    "residual_std": round(r.residual_ts.std(), 4),
                    "ou_half_life_days": (
                        round(r.first_passage_time, 1)
                        if r.first_passage_time is not None
                        else None
                    ),
                }
            )
        return pd.DataFrame(rows).set_index("tenor")

    def coeff_table(self) -> pd.DataFrame:
        """Regression coefficients for all fitted tenors, side by side."""
        frames = {}
        for tenor, r in self._results.items():
            frames[tenor] = r.regression_result.params
        if not frames:
            return pd.DataFrame()
        return pd.DataFrame(frames)

    # ------------------------------------------------------------------
    # Plotting helpers
    # ------------------------------------------------------------------

    def plot_fair_value(
        self, result: CCPBasisFairValueResult, **kwargs
    ):
        """Actual basis vs fair value (left) with residual (right)."""
        from RVUtils.plt_timeseries import make_secondary_axis_plot
        import matplotlib.pyplot as plt

        plot, fig, ax, ax2, legend = make_secondary_axis_plot(
            ylabel_left="Basis (bps)",
            ylabel_right="Residual (bps)",
            title=f"CCP Basis Fair Value: {result.tenor}",
        )

        plot(result.basis_ts, label=f"Actual {result.tenor}")
        plot(result.fair_value_ts, label=f"Fair Value {result.tenor}")
        plot(result.residual_ts, label="Residual", which="right")

        if result.ou_forecast is not None and ax2 is not None:
            ax2.fill_between(
                result.ou_forecast.index,
                result.ou_forecast["+1_sigma"],
                result.ou_forecast["-1_sigma"],
                alpha=0.15,
                color="gray",
                label="\u00b11\u03c3 OU",
            )

        legend(show_date=True, loc="upper left")
        plt.tight_layout()
        return fig

    def plot_residual_zscore(
        self, result: CCPBasisFairValueResult, **kwargs
    ):
        """Residual z-score with +/-2 sigma bands."""
        from RVUtils.plt_timeseries import make_secondary_axis_plot
        import matplotlib.pyplot as plt

        plot, fig, ax, ax2, legend = make_secondary_axis_plot(
            ylabel_left="Z-Score",
            title=f"CCP Basis Residual Z-Score: {result.tenor}",
        )

        plot(result.residual_zscore, label=f"Residual Z {result.tenor}")

        ax.axhline(y=2, color="red", linestyle="--", alpha=0.5, label="+2\u03c3")
        ax.axhline(y=-2, color="green", linestyle="--", alpha=0.5, label="-2\u03c3")
        ax.axhline(y=0, color="gray", linestyle="-", alpha=0.3)

        legend(show_date=True, loc="upper left")
        plt.tight_layout()
        return fig

    def plot_factor_attribution(
        self, result: CCPBasisFairValueResult, **kwargs
    ):
        """Line chart of factor contributions over time."""
        import matplotlib.pyplot as plt

        params = result.regression_result.params
        non_const = params.drop("const", errors="ignore")
        contributions = result.factor_df[non_const.index].multiply(non_const, axis=1)

        fig, ax = plt.subplots(figsize=(18, 8))
        for col in contributions.columns:
            ax.plot(contributions.index, contributions[col], label=col, alpha=0.7)
        ax.axhline(y=0, color="gray", linestyle="-", alpha=0.3)
        ax.set_title(f"Factor Attribution: {result.tenor}")
        ax.set_ylabel("Contribution to Basis (bps)")
        ax.legend(loc="upper left", fontsize="small")
        plt.tight_layout()
        return fig

    def plot_basis_term_structure(self):
        """Snapshot of current basis vs fair value across tenors."""
        import matplotlib.pyplot as plt

        if not self._results:
            raise ValueError("No results. Call fit_all() first.")

        tenors = list(self._results.keys())
        actual = [_last(self._results[t].basis_ts) for t in tenors]
        fv = [_last(self._results[t].fair_value_ts) for t in tenors]

        fig, ax = plt.subplots(figsize=(12, 6))
        x = range(len(tenors))
        ax.bar([i - 0.15 for i in x], actual, width=0.3, label="Actual", alpha=0.8)
        ax.bar([i + 0.15 for i in x], fv, width=0.3, label="Fair Value", alpha=0.8)
        ax.set_xticks(list(x))
        ax.set_xticklabels(tenors)
        ax.set_ylabel("Basis (bps)")
        ax.set_title("CCP Basis Term Structure: Actual vs Fair Value")
        ax.legend()
        plt.tight_layout()
        return fig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENOR_UNIT_MAP = {"D": 1 / 252, "W": 7 / 252, "M": 1 / 12, "Y": 1.0}

import re as _re

_TENOR_RE = _re.compile(r"^(\d+)([DWMY])$", _re.IGNORECASE)


def _tenor_sort_key(tenor: str) -> float:
    m = _TENOR_RE.match(tenor)
    if not m:
        return 999.0
    n = int(m.group(1))
    unit = m.group(2).upper()
    return n * _TENOR_UNIT_MAP.get(unit, 1.0)


def _last(s: pd.Series):
    if s is None or len(s) == 0:
        return None
    v = s.iloc[-1]
    return round(float(v), 4) if pd.notna(v) else None
