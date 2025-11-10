# ARBS Test Suite

This test suite serves dual purposes:
1. **Documentation**: Each test demonstrates a real-world usage pattern
2. **Validation**: Tests verify the system works as expected

## TDD Approach

These tests were written using Test-Driven Development (TDD):

1. **RED**: Write tests that describe how the system *should* work
2. **GREEN**: Implement features to make tests pass
3. **REFACTOR**: Improve code while keeping tests green

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and mock providers
├── test_query_basics.py     # Query creation and manipulation
├── test_backtest_simple.py  # Basic backtest workflows
├── test_portfolio.py        # Portfolio management and unwinding
└── test_triggers.py         # Trigger mechanisms
```

## Running Tests

### All tests
```bash
pytest tests/
```

### Specific test file
```bash
pytest tests/test_query_basics.py
```

### Specific test
```bash
pytest tests/test_query_basics.py::TestQueryCreation::test_create_simple_outright_query
```

### With verbose output
```bash
pytest tests/ -v
```

### With coverage
```bash
pytest tests/ --cov=BT --cov=Query --cov=MDP
```

## Mock Data Providers

Tests use `MockMDP` from `conftest.py` to avoid external dependencies:

```python
def test_example(mock_mdp):
    # mock_mdp provides predictable test data
    bt = QueryDrivenBacktest(
        time_grid=simple_time_grid,
        mdp=mock_mdp,  # Use mock instead of real data
        strategy=strategy,
    )
    bt.run()
```

## Test Categories

### 1. Query Basics (`test_query_basics.py`)

Documents how to:
- Create queries for different structures (outright, curve, fly)
- Use BPV for position sizing
- Tag queries for portfolio management
- Build market data requests
- Generate stable signatures

### 2. Simple Backtests (`test_backtest_simple.py`)

Documents how to:
- Run an empty backtest
- Enter a single position
- Use different trigger types
- Resolve queries to instruments
- Calculate values (NPV, par rate, etc.)

### 3. Portfolio Management (`test_portfolio.py`)

Documents how to:
- Unwind positions by tag
- Apply transaction costs
- Track realized vs. unrealized P&L
- Iterate open positions
- Count trades in windows

### 4. Triggers (`test_triggers.py`)

Documents how to:
- Create date triggers
- Build custom trigger logic
- Use conditional triggers
- Implement risk-based triggers
- Compose multiple triggers

## Example Test Pattern

Each test follows this pattern:

```python
def test_example_workflow(self, simple_time_grid, mock_mdp):
    """
    EXAMPLE: Brief description of what this demonstrates.

    Longer explanation of the use case and why you'd use this pattern.
    """
    # Setup
    query = IRSwapQuery(...)
    strategy = QueryStrategy(...)

    # Execute
    bt = QueryDrivenBacktest(...)
    bt.run()

    # Assert expected behavior
    assert some_expected_condition
```

## Known Limitations

Some tests may fail because:

1. **Not yet implemented**: Feature exists in design but not code
2. **Mock limitations**: Mock providers don't fully simulate QuantLib/RatesLib
3. **API changes**: Tests document desired API that may differ from current

Failing tests are **documentation of needed improvements**, not bugs.

## Test Fixtures

### `mock_mdp`
Mock market data provider that returns `MockPricer` instances with predictable rates.

### `simple_time_grid`
5 business days in January 2025.

### `monthly_time_grid`
Month-end dates for Q1 2025.

### `sample_curve_names`
List of common curve identifiers.

## Contributing Tests

When adding new features:

1. **Write the test first** (TDD red phase)
2. **Document the use case** in the docstring
3. **Use clear variable names** that explain intent
4. **Add assertions** that verify behavior
5. **Run the test** to see it fail
6. **Implement the feature** (TDD green phase)
7. **Verify test passes** (TDD green)
8. **Refactor if needed** (keep tests green)

## Questions or Issues

If tests are unclear or incorrect, please:
- Open an issue with the test name
- Suggest better examples
- Add clarifying comments
