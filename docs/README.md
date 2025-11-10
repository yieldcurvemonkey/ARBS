# ARBS Documentation

Welcome to the ARBS documentation hub. This directory contains comprehensive guides and references for using the Awesome Rates Backtesting System.

## 📖 Documentation Structure

### For New Users

1. **[EXAMPLES.md](EXAMPLES.md)** - Start here!
   - 16 practical examples with working code
   - Query creation, backtests, portfolio management, custom triggers
   - Copy-paste ready code snippets
   - Real-world use cases

2. **[../README.md](../README.md)** - System overview
   - Architecture and design patterns
   - Module descriptions
   - Installation instructions

3. **[../tests/README.md](../tests/README.md)** - Test suite guide
   - How to run tests
   - Test fixtures and mocks
   - Contributing test cases

### For Developers

4. **[TEST_REPORT.md](TEST_REPORT.md)** - TDD analysis
   - Test coverage analysis (57% passing)
   - Failing test explanations
   - API gaps and improvements
   - Recommended fixes

### For Advanced Users

5. **Example Scripts**
   - [`fomc_fly_backtest.py`](../fomc_fly_backtest.py) - Complete FOMC butterfly strategy
   - [`month_end_irswaps_backtest.ipynb`](../month_end_irswaps_backtest.ipynb) - Month-end rebalancing

6. **Reference Implementation**
   - [`tests/`](../tests/) - 47 tests serving as live documentation
   - Each test demonstrates a specific feature

---

## 🎯 Quick Navigation

### I want to...

#### Learn the basics
→ Read [EXAMPLES.md](EXAMPLES.md) sections 1-2 (Query Creation, Simple Backtests)

#### Run my first backtest
→ [EXAMPLES.md - Example 6](EXAMPLES.md#example-6-single-trade-entry)

#### Create custom triggers
→ [EXAMPLES.md - Custom Triggers](EXAMPLES.md#custom-triggers)

#### Manage positions
→ [EXAMPLES.md - Portfolio Management](EXAMPLES.md#portfolio-management)

#### Understand architecture
→ [../README.md - Architecture](../README.md#architecture)

#### Write tests
→ [../tests/README.md](../tests/README.md)

#### See what needs fixing
→ [TEST_REPORT.md](TEST_REPORT.md)

#### Run a real strategy
→ [`fomc_fly_backtest.py`](../fomc_fly_backtest.py)

---

## 📊 Documentation Coverage

| Topic | Coverage | Status |
|-------|----------|--------|
| Query Creation | ✅ Excellent | 12 examples + tests |
| Basic Backtests | ✅ Good | 7 examples + tests |
| Triggers | ✅ Excellent | 11 examples + tests |
| Portfolio Mgmt | ⚠️ Partial | Examples written, tests need fixes |
| Event-Driven | ❌ Missing | No examples yet |
| Caching | ❌ Missing | No examples yet |
| MDP Sources | ⚠️ Partial | Overview only |
| Product Adapters | ⚠️ Partial | IRS only |

**Legend**:
- ✅ Excellent: Complete with examples and passing tests
- ⚠️ Partial: Examples exist but incomplete or tests failing
- ❌ Missing: No documentation yet

---

## 🔍 Finding Information

### By Component

- **Queries**: [EXAMPLES.md](EXAMPLES.md#query-creation) + `Query/Base/BaseQuery.py`
- **Backtests**: [EXAMPLES.md](EXAMPLES.md#simple-backtests) + `BT/query_engine.py`
- **Triggers**: [EXAMPLES.md](EXAMPLES.md#custom-triggers) + `BT/triggers.py`
- **Portfolio**: [EXAMPLES.md](EXAMPLES.md#portfolio-management) + `BT/query_portfolio.py`
- **MDP**: [../README.md](../README.md#market-data-providers-mdp) + `MDP/MarketDataProvider.py`
- **Adapters**: [../README.md](../README.md#product-adapters-irs) + `Query/IRSwaps/adapter.py`

### By Use Case

- **Event-driven strategies**: See `fomc_fly_backtest.py`
- **Carry trades**: See `fomc_fly_backtest.py` (carry calculation)
- **Curve trades**: [EXAMPLES.md - Example 3](EXAMPLES.md#example-3-butterfly-fly-query)
- **Risk management**: [EXAMPLES.md - Example 14](EXAMPLES.md#example-14-risk-based-trigger)
- **Month-end rebalancing**: See notebook + [EXAMPLES.md - Example 13](EXAMPLES.md#example-13-month-end-trigger)

---

## 🧪 Testing & Validation

All examples in [EXAMPLES.md](EXAMPLES.md) are validated through the test suite:

```bash
# Validate Query examples
pytest tests/test_query_basics.py -v

# Validate Trigger examples
pytest tests/test_triggers.py -v

# Validate Backtest examples (some failing - see TEST_REPORT.md)
pytest tests/test_backtest_simple.py -v

# Run all tests
pytest tests/ -v
```

Test results: **27/47 passing (57%)** - See [TEST_REPORT.md](TEST_REPORT.md) for details.

---

## 📝 Contributing to Documentation

### Adding Examples

1. Write a test in `tests/` demonstrating the feature
2. Run test to ensure it works
3. Extract example into [EXAMPLES.md](EXAMPLES.md)
4. Add to this index

### Reporting Issues

If documentation is:
- **Unclear**: Open issue with "docs: unclear - [topic]"
- **Incorrect**: Open issue with "docs: error - [topic]"
- **Missing**: Open issue with "docs: missing - [topic]"

### Style Guide

- **Examples**: Start with "EXAMPLE:" in docstrings
- **Use cases**: Explain "when to use this"
- **Code**: Runnable, copy-paste ready
- **Tests**: Each test is live documentation

---

## 🗺️ Documentation Roadmap

### Completed ✅
- [x] Core examples (queries, triggers, basic backtests)
- [x] Test infrastructure
- [x] TDD analysis report
- [x] README improvements

### In Progress 🚧
- [ ] Mock provider fixes (enables more tests)
- [ ] Integration test examples
- [ ] Troubleshooting guide

### Planned 📋
- [ ] Event-driven backtest examples
- [ ] Caching guide
- [ ] Performance optimization guide
- [ ] MDP implementation guide
- [ ] Custom product adapter guide
- [ ] API reference (auto-generated)
- [ ] Video tutorials
- [ ] Architecture diagrams

---

## 💡 Tips for Learning

1. **Start Simple**: Begin with passing tests (27 of them!)
2. **Read Tests as Docs**: Each test is a mini-tutorial
3. **Copy-Paste**: All examples are designed to be copied
4. **Experiment**: Modify examples and see what happens
5. **Test Driven**: Write a test describing what you want, then implement

---

## 📞 Getting Help

1. **Check examples**: [EXAMPLES.md](EXAMPLES.md)
2. **Read tests**: `tests/test_*.py`
3. **Review architecture**: [../README.md](../README.md)
4. **See real code**: `fomc_fly_backtest.py`
5. **Open issue**: If still stuck

---

## 📈 Status

- **Documentation Coverage**: 65%
- **Test Coverage**: 57% (27/47 tests passing)
- **Example Coverage**: Excellent for core features
- **Last Updated**: 2025-11-10

---

## Next Steps

**For New Users**:
1. Read [EXAMPLES.md](EXAMPLES.md) sections 1-3
2. Try Example 6 (single trade backtest)
3. Experiment with custom triggers (Examples 11-14)

**For Contributors**:
1. Review [TEST_REPORT.md](TEST_REPORT.md)
2. Pick a failing test to fix
3. Write documentation for your fixes

**For Advanced Users**:
1. Study `fomc_fly_backtest.py`
2. Implement your own strategy
3. Add tests for your use cases
