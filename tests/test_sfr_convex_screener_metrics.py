import numpy as np
import pytest

from RVUtils.SFRConvexScreener._metrics import (
    PayoffMetrics,
    metrics_from_pdf,
    metrics_from_samples,
)


def test_metrics_from_samples_symmetric_normal_has_unit_asymmetry():
    rng = np.random.default_rng(0)
    samples = rng.standard_normal(50_000) * 10.0
    m = metrics_from_samples(samples)
    assert abs(m.mean_bp) < 0.5
    assert 9 < m.std_bp < 11
    assert abs(m.skew) < 0.05
    assert 0.95 < m.asymmetry_ratio < 1.05
    assert 0.85 < m.tail_ratio < 1.15
    assert abs(m.p_profit - 0.5) < 0.01


def test_metrics_from_samples_skewed_has_asymmetry_above_one():
    """Right-skewed distribution with positive mean: upside partial expectation
    exceeds downside, so asymmetry > 1."""
    rng = np.random.default_rng(0)
    # exp(10) shifted by -5 → mean +5, still right-skewed
    samples = (rng.exponential(scale=10.0, size=50_000) - 5.0)
    m = metrics_from_samples(samples)
    assert m.asymmetry_ratio > 1.5


def test_metrics_percentile_fields():
    rng = np.random.default_rng(0)
    samples = rng.standard_normal(100_000) * 10.0
    m = metrics_from_samples(samples)
    assert -18 < m.percentiles_bp["p5"] < -14
    assert 14 < m.percentiles_bp["p95"] < 18


def test_metrics_from_pdf_matches_sampled_metrics_uniform():
    grid = np.linspace(-50.0, 50.0, 2001)
    probs = np.full_like(grid, 1.0 / len(grid))
    m_pdf = metrics_from_pdf(grid, probs)
    rng = np.random.default_rng(0)
    samples = rng.uniform(-50, 50, size=200_000)
    m_samp = metrics_from_samples(samples)
    assert abs(m_pdf.mean_bp - m_samp.mean_bp) < 1.0
    assert abs(m_pdf.std_bp - m_samp.std_bp) < 1.0
