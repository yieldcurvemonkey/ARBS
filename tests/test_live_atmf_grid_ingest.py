import datetime as dt
import math

import numpy as np
import pandas as pd

from RVUtils.surface_pca_model import SurfacePCAModel
from SDRUtils._swappulse_scripts import ingest_and_build_live_atmf_grid as live_grid


LEGACY_EXPIRY_LABELS = ["1m", "3m", "6m", "1y", "2y", "3y", "5y", "10y"]


def _make_legacy_grid(
    *,
    level_shift: float,
    expiry_scale: float,
    tenor_scale: float,
) -> dict[str, float]:
    grid: dict[str, float] = {}
    for expiry in LEGACY_EXPIRY_LABELS:
        expiry_years = live_grid._label_to_years(expiry)
        for tenor in live_grid.TAIL_LABELS:
            tenor_years = live_grid._label_to_years(tenor)
            grid[f"{expiry}_{tenor}"] = (
                70.0
                + level_shift
                + expiry_scale * math.log1p(expiry_years)
                + tenor_scale * math.sqrt(tenor_years)
            )
    return grid


def _make_dummy_model(columns: list[str]) -> SurfacePCAModel:
    width = len(columns)
    return SurfacePCAModel(
        columns=list(columns),
        mean=np.zeros(width, dtype=float),
        loadings=np.zeros((width, 1), dtype=float),
        eigenvalues=np.zeros(1, dtype=float),
        n_components=1,
        training_start=dt.date(2026, 3, 3),
        training_end=dt.date(2026, 3, 5),
        training_days=3,
        total_variance=np.zeros(width, dtype=float),
        residual_variance=np.zeros(width, dtype=float),
    )


def _make_flat_grid(level: float = 80.0) -> dict[str, float]:
    return {node_key: level for node_key in live_grid.SURFACE_NODE_KEYS}


def _make_direct_observation(
    *,
    package_id: str,
    expiry_label: str,
    tenor_label: str,
    observed_bpvol: float,
    core_node_key: str | None = None,
    grid_weights: dict[str, float] | None = None,
    execution_timestamp: dt.datetime | None = None,
) -> live_grid.StraddleObservation:
    expiry_token = expiry_label.lower()
    tenor_token = tenor_label.lower()
    node_key = core_node_key or f"{expiry_token}_{tenor_token}"
    return live_grid.StraddleObservation(
        package_id=package_id,
        execution_timestamp=execution_timestamp
        or dt.datetime(2026, 3, 6, 15, 0, 0, tzinfo=dt.timezone.utc),
        forward_label=expiry_label,
        tenor_label=tenor_label,
        forward_years=live_grid._label_to_years(expiry_label),
        tenor_years=live_grid._label_to_years(tenor_label),
        observed_bpvol=observed_bpvol,
        premium=None,
        notional=100_000_000.0,
        platform_identifier="BGCD",
        platform_type="idb",
        event_action="NEWT",
        trade_label=f"{expiry_label}x{tenor_label}",
        core_node_key=node_key,
        display_node_key=node_key,
        mapping_distance=0.0,
        display_mapping_distance=0.0,
        staleness_weight=1.0,
        age_minutes=0.0,
        delta_bpvol=None,
        grid_weights=grid_weights if grid_weights is not None else {node_key: 1.0},
    )


def _make_package_row(
    *,
    package_id: str,
    package_type: str,
    forward_label: str,
    tenor_label: str,
    execution_timestamp: dt.datetime,
    total_notional: float,
    total_premium: float,
    platform_identifier: str,
    event_action: str,
    legs_json: list[dict[str, object]],
    package_metrics: dict[str, object] | None = None,
    package_source: str = "AUTO",
    manual_link_id: str | None = None,
    expiration_date: dt.date | None = None,
    underlying_expiration_date: dt.date | None = None,
) -> dict[str, object]:
    return {
        "package_id": package_id,
        "package_type": package_type,
        "package_source": package_source,
        "manual_link_id": manual_link_id,
        "as_of_date": execution_timestamp.date(),
        "execution_start": execution_timestamp,
        "expiration_date": expiration_date or dt.date(2027, 3, 9),
        "underlying_expiration_date": underlying_expiration_date or dt.date(2032, 3, 9),
        "forward_label": forward_label,
        "tenor_label": tenor_label,
        "forward_start_years": live_grid._label_to_years(forward_label),
        "tenor_years": live_grid._label_to_years(tenor_label),
        "total_notional": total_notional,
        "total_premium": total_premium,
        "package_metrics": package_metrics or {},
        "platform_identifier": platform_identifier,
        "event_action": event_action,
        "legs_json": legs_json,
    }


def test_complete_surface_grid_upgrades_legacy_rows_for_new_expiries():
    legacy_grid = _make_legacy_grid(
        level_shift=0.0,
        expiry_scale=3.0,
        tenor_scale=0.75,
    )

    completed = live_grid._complete_surface_grid(legacy_grid)

    assert list(completed) == live_grid.SURFACE_NODE_KEYS
    assert all(np.isfinite(list(completed.values())))
    for node_key, node_value in legacy_grid.items():
        assert completed[node_key] == node_value
    assert np.isfinite(completed["7y_10y"])
    # "15y" was deliberately removed from EXPIRY_LABELS in commit e944c2d8 ("new strats")
    assert np.isfinite(completed["20y_10y"])


def test_ensure_history_and_model_force_refresh_fetches_full_window(monkeypatch):
    anchor_eod_date = dt.date(2026, 3, 5)
    start_date = (pd.Timestamp(anchor_eod_date) - pd.tseries.offsets.BDay(2)).date()
    required_dates = live_grid._business_dates(start_date, anchor_eod_date)

    completed_rows = [
        live_grid._complete_surface_grid(
            _make_legacy_grid(
                level_shift=float(index),
                expiry_scale=2.5 + index,
                tenor_scale=0.5 + 0.1 * index,
            )
        )
        for index in range(len(required_dates))
    ]
    full_df = pd.DataFrame(completed_rows, index=pd.to_datetime(required_dates))
    partial_df = full_df.iloc[:-1]

    load_calls = {"count": 0}
    captured: dict[str, list[dt.date]] = {}
    dummy_model = _make_dummy_model(live_grid.SURFACE_NODE_KEYS)

    def fake_load_eod_history_df(*args, **kwargs):
        load_calls["count"] += 1
        return partial_df if load_calls["count"] == 1 else full_df

    def fake_fetch_eod_grids(curve_name, dates, *, surface_type, force_refresh=False):
        captured["dates"] = list(dates)
        return {}

    monkeypatch.setattr(live_grid, "load_eod_history_df", fake_load_eod_history_df)
    monkeypatch.setattr(live_grid, "fetch_eod_grids", fake_fetch_eod_grids)
    monkeypatch.setattr(live_grid, "upsert_eod_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(live_grid, "load_pca_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        live_grid,
        "fit_surface_pca_from_eod_grids",
        lambda levels_df, n_components=5: (dummy_model, pd.DataFrame()),
    )
    monkeypatch.setattr(live_grid, "store_pca_model", lambda *args, **kwargs: 0.42)

    model, explained_ratio = live_grid.ensure_history_and_model(
        engine=object(),
        curve_name="USD-SOFR-1D",
        surface_type="atmf_normal",
        anchor_eod_date=anchor_eod_date,
        lookback_business_days=2,
        n_components=1,
        force_refresh=True,
    )

    assert captured["dates"] == required_dates
    assert model is dummy_model
    assert explained_ratio == 0.42


def test_build_live_grid_anchors_direct_long_end_nodes(monkeypatch):
    model = _make_dummy_model(live_grid.SURFACE_NODE_KEYS)
    eod_grid = _make_flat_grid(80.0)
    # "15y" was removed from EXPIRY_LABELS in commit e944c2d8 ("new strats"); use "7Y" instead.
    observations = [
        _make_direct_observation(
            package_id="pkg-10",
            expiry_label="10Y",
            tenor_label="10Y",
            observed_bpvol=79.0,
            execution_timestamp=dt.datetime(2026, 3, 6, 18, 20, 0, tzinfo=dt.timezone.utc),
        ),
        _make_direct_observation(
            package_id="pkg-7",
            expiry_label="7Y",
            tenor_label="10Y",
            observed_bpvol=77.0,
            execution_timestamp=dt.datetime(2026, 3, 6, 18, 10, 0, tzinfo=dt.timezone.utc),
        ),
        _make_direct_observation(
            package_id="pkg-20",
            expiry_label="20Y",
            tenor_label="10Y",
            observed_bpvol=75.0,
            execution_timestamp=dt.datetime(2026, 3, 6, 18, 0, 0, tzinfo=dt.timezone.utc),
        ),
    ]

    monkeypatch.setattr(
        live_grid,
        "compute_straddle_premiums",
        lambda grid_data, **kwargs: {
            node_key: live_grid.PremiumQuote(premium=0.0, premium_bps=0.0)
            for node_key in grid_data
        },
    )

    update, node_metadata, _, last_observation_ts = live_grid.build_live_grid(
        model,
        eod_grid,
        observations,
        base_noise_bpvol=0.5,
        curve_name="USD-SOFR-1D",
        surface_type="atmf_normal",
        pricing_date=dt.date(2026, 3, 6),
        use_continuous_observations=True,
    )

    assert update.live_grid["10y_10y"] == 79.0
    assert update.live_grid["7y_10y"] == 77.0
    assert update.live_grid["20y_10y"] == 75.0
    assert update.delta_grid["7y_10y"] == -3.0
    assert update.delta_grid["20y_10y"] == -5.0
    assert update.live_grid["7y_1y"] != update.live_grid["10y_1y"]
    assert update.live_grid["20y_1y"] != update.live_grid["7y_1y"]
    assert update.live_grid["7y_1y"] < 80.0
    assert update.live_grid["20y_1y"] < 80.0
    assert node_metadata["7y_10y"]["source"] == "direct_observation"
    assert node_metadata["20y_10y"]["source"] == "direct_observation"
    assert node_metadata["7y_10y"]["last_observation"]["tradeLabel"] == "7Yx10Y"
    assert node_metadata["20y_10y"]["last_observation"]["tradeLabel"] == "20Yx10Y"
    assert node_metadata["7y_1y"]["source"] == "propagated"
    assert node_metadata["20y_1y"]["source"] == "propagated"
    assert node_metadata["7y_1y"]["last_propagated_from"] is not None
    assert node_metadata["20y_1y"]["last_propagated_from"] is not None
    assert node_metadata["7y_1y"]["propagation_factor"] > 0
    assert node_metadata["20y_1y"]["propagation_factor"] > 0
    assert last_observation_ts == dt.datetime(2026, 3, 6, 18, 20, 0, tzinfo=dt.timezone.utc)


def test_build_live_grid_spillover_nodes_remain_propagated(monkeypatch):
    model = _make_dummy_model(live_grid.SURFACE_NODE_KEYS)
    eod_grid = _make_flat_grid(80.0)
    observations = [
        # "15y" was removed from EXPIRY_LABELS in commit e944c2d8; spillover uses "20y" instead.
        _make_direct_observation(
            package_id="pkg-10",
            expiry_label="10Y",
            tenor_label="10Y",
            observed_bpvol=79.0,
            core_node_key="10y_10y",
            grid_weights={
                "10y_10y": 0.995,
                "20y_10y": 0.005,
            },
        ),
    ]

    monkeypatch.setattr(
        live_grid,
        "compute_straddle_premiums",
        lambda grid_data, **kwargs: {
            node_key: live_grid.PremiumQuote(premium=0.0, premium_bps=0.0)
            for node_key in grid_data
        },
    )

    update, node_metadata, _, _ = live_grid.build_live_grid(
        model,
        eod_grid,
        observations,
        base_noise_bpvol=0.5,
        curve_name="USD-SOFR-1D",
        surface_type="atmf_normal",
        pricing_date=dt.date(2026, 3, 6),
        use_continuous_observations=True,
    )

    assert update.live_grid["10y_10y"] == 79.0
    assert update.live_grid["20y_10y"] < 80.0
    assert node_metadata["10y_10y"]["source"] == "direct_observation"
    assert node_metadata["20y_10y"]["source"] == "propagated"
    assert node_metadata["20y_10y"]["direct_observation_count"] == 0
    assert node_metadata["20y_10y"]["last_propagated_from"] == "10y_10y"


def test_build_straddle_observations_infers_broken_idb_straddles():
    execution_reference = dt.datetime(2026, 3, 9, 14, 0, 0, tzinfo=dt.timezone.utc)
    execution_broken = dt.datetime(2026, 3, 9, 14, 5, 0, tzinfo=dt.timezone.utc)

    rows = [
        _make_package_row(
            package_id="pkg-ref",
            package_type="STRADDLE",
            forward_label="1y",
            tenor_label="5y",
            execution_timestamp=execution_reference,
            total_notional=150_000_000.0,
            total_premium=120_000.0,
            platform_identifier="BGCD",
            event_action="NEWT-TRAD",
            package_metrics={"straddle_bpvol_yr": 60.0},
            legs_json=[
                {
                    "product_type": "SWAPTION_PAYER",
                    "trade_label": "1Yx5Y EURO VANILLA PHYS PAYER",
                    "notional": 150_000_000.0,
                    "premium": 120_000.0,
                    "platform_identifier": "BGCD",
                    "leg_metrics": {"straddle_bpvol_yr": 60.0},
                },
                {
                    "product_type": "SWAPTION_RECEIVER",
                    "trade_label": "1Yx5Y EURO VANILLA PHYS RECEIVER",
                    "notional": 150_000_000.0,
                    "premium": 120_000.0,
                    "platform_identifier": "BGCD",
                    "leg_metrics": {"straddle_bpvol_yr": 60.0},
                },
            ],
        ),
        _make_package_row(
            package_id="pkg-broken",
            package_type="OUTRIGHT",
            forward_label="1y",
            tenor_label="5y",
            execution_timestamp=execution_broken,
            total_notional=100_000_000.0,
            total_premium=200_000.0,
            platform_identifier="BGCD",
            event_action="NEWT-TRAD",
            legs_json=[
                {
                    "product_type": "SWAPTION_PAYER",
                    "trade_label": "1Yx5Y EURO VANILLA PHYS PAYER",
                    "notional": 100_000_000.0,
                    "premium": 200_000.0,
                    "platform_identifier": "BGCD",
                    "leg_metrics": {
                        "outright_moneyness": "ATM",
                        "outright_bpvol_yr": 120.0,
                    },
                }
            ],
        ),
    ]

    observations = live_grid._build_straddle_observations_from_package_rows(rows)

    assert [observation.package_id for observation in observations] == [
        "pkg-ref",
        "pkg-broken",
    ]

    inferred = next(observation for observation in observations if observation.package_id == "pkg-broken")
    assert inferred.is_inferred_incomplete is True
    assert inferred.is_manual_straddle is False
    assert inferred.source_package_type == "OUTRIGHT"
    assert inferred.observed_bpvol == 60.0
    assert inferred.premium == 100_000.0
    assert inferred.notional == 100_000_000.0
    assert inferred.platform_type == "idb"
    assert inferred.inferred_reason is not None
    assert "most recent 1yx5y straddle bpvol" in inferred.inferred_reason


def test_build_straddle_observations_skips_broken_leg_when_complete_signature_exists():
    execution_reference = dt.datetime(2026, 3, 9, 14, 0, 0, tzinfo=dt.timezone.utc)
    execution_broken = dt.datetime(2026, 3, 9, 14, 5, 0, tzinfo=dt.timezone.utc)

    rows = [
        _make_package_row(
            package_id="pkg-ref",
            package_type="STRADDLE",
            forward_label="1y",
            tenor_label="5y",
            execution_timestamp=execution_reference,
            total_notional=100_000_000.0,
            total_premium=120_000.0,
            platform_identifier="BGCD",
            event_action="NEWT-TRAD",
            package_metrics={"straddle_bpvol_yr": 60.0},
            legs_json=[
                {
                    "product_type": "SWAPTION_PAYER",
                    "trade_label": "1Yx5Y EURO VANILLA PHYS PAYER",
                    "notional": 100_000_000.0,
                    "premium": 120_000.0,
                    "platform_identifier": "BGCD",
                    "leg_metrics": {"straddle_bpvol_yr": 60.0},
                },
                {
                    "product_type": "SWAPTION_RECEIVER",
                    "trade_label": "1Yx5Y EURO VANILLA PHYS RECEIVER",
                    "notional": 100_000_000.0,
                    "premium": 120_000.0,
                    "platform_identifier": "BGCD",
                    "leg_metrics": {"straddle_bpvol_yr": 60.0},
                },
            ],
        ),
        _make_package_row(
            package_id="pkg-broken",
            package_type="OUTRIGHT",
            forward_label="1y",
            tenor_label="5y",
            execution_timestamp=execution_broken,
            total_notional=100_000_000.0,
            total_premium=200_000.0,
            platform_identifier="BGCD",
            event_action="NEWT-TRAD",
            legs_json=[
                {
                    "product_type": "SWAPTION_PAYER",
                    "trade_label": "1Yx5Y EURO VANILLA PHYS PAYER",
                    "notional": 100_000_000.0,
                    "premium": 200_000.0,
                    "platform_identifier": "BGCD",
                    "leg_metrics": {
                        "outright_moneyness": "ATM",
                        "outright_bpvol_yr": 120.0,
                    },
                }
            ],
        ),
    ]

    observations = live_grid._build_straddle_observations_from_package_rows(rows)

    assert [observation.package_id for observation in observations] == ["pkg-ref"]


def test_build_straddle_observations_honors_manual_straddle_override():
    execution_timestamp = dt.datetime(2026, 3, 9, 15, 0, 0, tzinfo=dt.timezone.utc)
    rows = [
        _make_package_row(
            package_id="pkg-manual",
            package_type="OUTRIGHT",
            forward_label="10y",
            tenor_label="5y",
            execution_timestamp=execution_timestamp,
            total_notional=50_000_000.0,
            total_premium=90_000.0,
            platform_identifier="BILT",
            event_action="NEWT-TRAD",
            legs_json=[
                {
                    "product_type": "SWAPTION_PAYER",
                    "trade_label": "10Yx5Y PAYER",
                    "notional": 50_000_000.0,
                    "premium": 90_000.0,
                    "platform_identifier": "BILT",
                    "leg_metrics": {
                        "outright_bpvol_yr": 80.0,
                    },
                }
            ],
        )
    ]

    observations = live_grid._build_straddle_observations_from_package_rows(
        rows,
        manual_straddle_ids={"pkg-manual"},
    )

    assert len(observations) == 1
    manual = observations[0]
    assert manual.package_id == "pkg-manual"
    assert manual.is_inferred_incomplete is True
    assert manual.is_manual_straddle is True
    assert manual.platform_type == "custy"
    assert manual.observed_bpvol == 40.0
    assert manual.premium == 45_000.0
    assert manual.inferred_reason == (
        "Manually marked as intraday incomplete straddle from the trade-selection toolbar."
    )
