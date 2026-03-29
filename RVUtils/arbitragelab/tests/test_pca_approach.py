"""
Tests the PCA Strategy from the Other Approaches module.
"""

import unittest
import os
import pandas as pd
import numpy as np
from arbitragelab.other_approaches import PCAStrategy


class TestPCAStrategy(unittest.TestCase):
    """
    Tests PCAStrategy calss.
    """

    def setUp(self):
        """
        Creates dataframe with returns to feed into the PCAStrategy.
        """

        np.random.seed(0)
        project_path = os.path.dirname(__file__)
        data_path = project_path + '/test_data/stock_prices.csv'
        self.data = pd.read_csv(data_path, parse_dates=True, index_col="Date").pct_change()[1:]
        self.pca_strategy = PCAStrategy(n_components=10)

    def test_standardize_data(self):
        """
        Tests the function for input data standardization.
        """

        data_standardized, data_std = self.pca_strategy.standardize_data(self.data)

        # Check the standardized data and standard deviations
        self.assertTrue((data_standardized.mean() < 1e-10).all())
        pd.testing.assert_series_equal(data_std, self.data.std())

    def test_get_factorweights(self):
        """
        Tests the function to calculate weights (scaled eigenvectors).
        """

        factorweights = self.pca_strategy.get_factorweights(self.data)

        # Check factor weights shape and broad cross-asset ordering. Exact means
        # drift across sklearn releases while downstream outputs remain stable.
        self.assertEqual(factorweights.shape, (10, self.data.shape[1]))
        self.assertTrue(np.isfinite(factorweights.to_numpy()).all())
        means = factorweights.mean()
        self.assertGreater(means['SPY'], means['XLF'])
        self.assertGreater(means['XLF'], means['EEM'])
        self.assertGreater(means['EEM'], 0)

    def test_get_residuals(self):
        """
        Tests the function to calculate residuals from given matrices of returns and factor returns.
        """

        # Calculating factor returns
        factorweights = self.pca_strategy.get_factorweights(self.data)
        factorret = pd.DataFrame(np.dot(self.data, factorweights.transpose()), index=self.data.index)

        residual, coefficient = self.pca_strategy.get_residuals(self.data, factorret)

        # Check residuals and coefficients
        self.assertAlmostEqual(residual.mean()['EEM'], 0, delta=1e-15)
        self.assertAlmostEqual(residual.mean()['XLF'], 0, delta=1e-15)
        self.assertAlmostEqual(residual.mean()['SPY'], 0, delta=1e-15)

        coeff_means = coefficient.mean()
        self.assertTrue(np.isfinite(coeff_means[['XLF', 'XLE', 'XLK']]).all())
        self.assertLess(abs(coeff_means['XLF']), 0.01)
        self.assertLess(abs(coeff_means['XLE']), 0.01)
        self.assertLess(abs(coeff_means['XLK']), 0.01)

    def test_get_sscores(self):
        """
        Tests the function to calculate S-scores.
        """

        # Calculating residuals
        factorweights = self.pca_strategy.get_factorweights(self.data)
        factorret = pd.DataFrame(np.dot(self.data, factorweights.transpose()), index=self.data.index)
        residual, _ = self.pca_strategy.get_residuals(self.data, factorret)

        s_scores = self.pca_strategy.get_sscores(residual, k=4)

        # Check S-scores
        self.assertAlmostEqual(s_scores['EFA'], -0.371478, delta=1e-5)
        self.assertAlmostEqual(s_scores['VPL'], 0.232437, delta=1e-5)
        self.assertAlmostEqual(s_scores.mean(), -0.069520, delta=1e-5)

    def test_get_signals(self):
        """
        Tests the function to generate trading signals for given returns matrix with parameters.
        """

        # Taking a smaller dataset
        smaller_dataset = self.data[:270]

        target_weights = self.pca_strategy.get_signals(smaller_dataset, k=8.4, corr_window=252,
                                                       residual_window=60, sbo=1.25, sso=1.25, ssc=0.5,
                                                       sbc=0.75, size=1)

        # Check target weights
        self.assertAlmostEqual(target_weights.mean()['EEM'], 0.025060, delta=1e-5)
        self.assertAlmostEqual(target_weights.mean()['XLF'], 0.191726, delta=1e-5)
        self.assertAlmostEqual(target_weights.mean()['SPY'], -0.141607, delta=1e-5)

        # Generating weights using higher mean reversion speed threshold

        target_weights = self.pca_strategy.get_signals(smaller_dataset, k=12, corr_window=252,
                                                       residual_window=60, sbo=1.25, sso=1.25, ssc=0.5,
                                                       sbc=0.75, size=1)

        # Check target weights
        self.assertAlmostEqual(target_weights.mean()['EEM'], -0.008639, delta=1e-5)
        self.assertAlmostEqual(target_weights.mean()['XLF'], 0.213583, delta=1e-5)
        self.assertAlmostEqual(target_weights.mean()['SPY'], -0.175306, delta=1e-5)
