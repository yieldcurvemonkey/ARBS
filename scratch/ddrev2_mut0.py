"""No-op mutation plugin -- validates the harness itself before it is trusted."""


def pytest_configure(config):
    from SDRUtils.dealer_direction import ladder  # noqa: F401
    print("\n[mut0] harness live, no mutation applied")
