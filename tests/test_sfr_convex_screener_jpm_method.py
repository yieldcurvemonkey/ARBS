"""Tests for the ``jpm_method=True`` flag wired through to BL extraction."""

from unittest.mock import patch

from RVUtils.SFRConvexScreener._distributions import extract_bl_marginals


def test_extract_bl_marginals_jpm_method_uses_raw_vols():
    """When ``jpm_method=True`` and no extractor passed, the constructor must
    receive ``use_sabr_vols=False`` and ``sabr_extrapolation=False``."""
    seen_kwargs = {}

    class _RecordingExtractor:
        def __init__(self, **kwargs):
            seen_kwargs.update(kwargs)

        def extract(self, smile):
            from RVUtils.ImpliedDistribution import ImpliedDistributionSnapshot
            return ImpliedDistributionSnapshot(
                symbol="X", as_of=None, bl_result=None, gm_result=None,
            )

    with patch(
        "RVUtils.SFRConvexScreener._distributions.SFRImpliedDistribution",
        _RecordingExtractor,
    ):
        extract_bl_marginals({"SFRZ26": object()}, jpm_method=True)

    assert seen_kwargs.get("use_sabr_vols") is False
    assert seen_kwargs.get("sabr_extrapolation") is False
    assert seen_kwargs.get("spline_order") == 4
    assert seen_kwargs.get("n_ghost_points") == 10
    assert seen_kwargs.get("bin_width_bps") == 25.0


def test_extract_bl_marginals_default_uses_sabr_vols():
    """Default path constructs SFRImpliedDistribution without overriding
    use_sabr_vols (which defaults to True in that class)."""
    seen_kwargs = {}

    class _RecordingExtractor:
        def __init__(self, **kwargs):
            seen_kwargs.update(kwargs)

        def extract(self, smile):
            from RVUtils.ImpliedDistribution import ImpliedDistributionSnapshot
            return ImpliedDistributionSnapshot(
                symbol="X", as_of=None, bl_result=None, gm_result=None,
            )

    with patch(
        "RVUtils.SFRConvexScreener._distributions.SFRImpliedDistribution",
        _RecordingExtractor,
    ):
        extract_bl_marginals({"SFRZ26": object()}, jpm_method=False)

    assert "use_sabr_vols" not in seen_kwargs
    assert "sabr_extrapolation" not in seen_kwargs
