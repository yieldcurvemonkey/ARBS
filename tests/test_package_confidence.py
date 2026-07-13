from SDRUtils.analytics.package_confidence import compute_package_confidence


def test_spreadover_curve_not_downgraded():
    conf = compute_package_confidence(
        package_type="SPREADOVER_CURVE", package_indicator=True, n_package_legs=2,
        package_transaction_spread=-0.00325, has_spread=True,
        legs=[
            {"tenor_years": 10, "risk": 40000, "fixed_rate": 0.04139,
             "package_transaction_spread": -0.00325},
            {"tenor_years": 30, "risk": 40000, "fixed_rate": 0.04313,
             "package_transaction_spread": -0.00325},
        ],
    )
    assert conf["inferred_type"] is None
    assert not any(s["name"] == "inferred_base_type" for s in conf["signals"])
