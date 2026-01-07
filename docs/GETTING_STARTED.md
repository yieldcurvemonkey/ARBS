# Getting Started with ARBS

Welcome to the Awesome Rates Backtesting System! This is your entry point to installing and using ARBS.

## What is ARBS?

ARBS is a comprehensive backtesting framework for:
- Building and managing yield curves
- Pricing interest rate derivatives (especially IRS)
- Running event-driven and query-driven backtests
- Managing market data from multiple sources
- Persistent caching of expensive computations

Perfect for quant researchers, traders, and risk managers working with interest rate products.

## The Five-Minute Start

### For Linux/macOS:

```bash
# 1. Create virtual environment
python3.13 -m venv arbs_env
source arbs_env/bin/activate

# 2. Get ARBS
git clone https://github.com/yieldcurvemonkey/ARBS.git
cd ARBS

# 3. Install
pip install --upgrade pip
pip install -r requirements.txt

# 4. Verify
python -c "from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP; print('✓ Ready!')"

# 5. Run a test
python -c "
import datetime as dt
from BT.data_handler import TimeGrid
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

dates = [dt.date(2025, 9, d) for d in range(15, 20)]
grid = TimeGrid(dates)
mdp = IRSwapsMDP()
print('✓ First backtest initialized!')
"
```

### For Windows PowerShell:

```powershell
python -m venv arbs_env
.\arbs_env\Scripts\Activate.ps1
git clone https://github.com/yieldcurvemonkey/ARBS.git
cd ARBS
pip install --upgrade pip
pip install -r requirements.txt
```

### For Conda Users:

```bash
conda create -n arbs python=3.13 -y
conda activate arbs
conda install -c conda-forge quantlib -y
git clone https://github.com/yieldcurvemonkey/ARBS.git
cd ARBS
pip install -r requirements.txt
```

## Next: Complete Your Setup

Choose your learning path:

### Path 1: User (Non-Developer)
1. ✓ Run five-minute start above
2. [ ] Read [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md) - 5 minutes
3. [ ] Check [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) - verify installation
4. [ ] Copy `.env.example` → `.env` and set FRED_API_KEY (optional)
5. [ ] Review [README.md](README.md) - understand architecture
6. [ ] Run example notebook: `jupyter notebook month_end_irswaps_backtest.ipynb`

**Time: 30 minutes total**

### Path 2: Developer (Contributing Code)
1. ✓ Run five-minute start above
2. [ ] Install dev tools: `pip install -r requirements-dev.txt`
3. [ ] Read [Development Setup Section](INSTALLATION_AND_SETUP_GUIDE.md#development-environment)
4. [ ] Fork repository and set up git branches
5. [ ] Review [architecture documentation](docs/)
6. [ ] Start with module tests: `pytest tests/`

**Time: 1 hour total**

### Path 3: Production Deployment
1. ✓ Run five-minute start above
2. [ ] Read [Production Deployment Section](INSTALLATION_AND_SETUP_GUIDE.md#production-environment)
3. [ ] Use `requirements-prod.txt` instead
4. [ ] Set up `.env` with production settings
5. [ ] Choose deployment: [Docker](Dockerfile.example) or [Systemd](arbs-backtest.service.example)
6. [ ] Configure monitoring/alerting

**Time: 2-3 hours depending on infrastructure**

## Documentation Map

```
Getting Started (You are here)
├── QUICK_START_GUIDE.md (5 min)
├── SETUP_CHECKLIST.md (verify setup)
├── INSTALLATION_AND_SETUP_GUIDE.md (comprehensive)
├── INSTALLATION_GUIDE_INDEX.md (document index)
│
├── Configuration Files
│   ├── .env.example (copy to .env)
│   ├── config/settings.example.yaml
│   ├── requirements.txt (dependencies)
│   ├── requirements-prod.txt (production)
│   ├── requirements-dev.txt (development)
│   └── requirements-ci.txt (CI/CD)
│
├── Deployment
│   ├── Dockerfile.example (Docker)
│   ├── docker-compose.example.yml (Compose)
│   ├── arbs-backtest.service.example (Systemd)
│   └── arbs-backtest.timer.example (Scheduler)
│
├── README.md (architecture overview)
└── docs/ (detailed module docs)
```

## Key Features

### 1. Query-Driven Backtesting
```python
from BT.query_engine import QueryDrivenBacktest
from Query.IRSwaps.IRSwapQuery import IRSwapQuery

query = IRSwapQuery(tenor="5Y", curve="USD-SOFR-1D", value=IRSwapValue.RATE)
bt = QueryDrivenBacktest(time_grid=grid, mdp=mdp, strategy=strategy)
bt.run()
```

### 2. Multiple Data Sources
```python
# CME End-of-Day (public, no auth)
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")

# SDR Intraday (requires data files)
mdp = IRSwapsMDP(source="SDR_INTRADAY-RL")

# GSQuant RatesLib
mdp = IRSwapsMDP(source="GSQUANT-RL")
```

### 3. Persistent Caching (ZODB)
```python
from Caching.ZODBCacheMixin import ZODBCacheMixin

# Automatically caches expensive computations
# Survives across Python sessions
# Located at: ~/.cache/arbs/zodb/dump/
```

### 4. Event-Driven Strategies
```python
strategy = Strategy(
    triggers=[
        DateTrigger(...),
        RiskTrigger(...),
    ],
    actions=[
        AddQueryAction(...),
        HedgeAction(...),
        UnwindPositionsAction(...),
    ]
)
```

## Common First Steps

### 1. Fetch Some Data
```python
import datetime as dt
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")

request = {
    "curve_name": "USD-SOFR-1D",
    "timestamp": dt.date(2025, 9, 15),
}

pricer = mdp.get_pricer(request)
rate = pricer.par_rate("5Y")
print(f"5Y USD-SOFR rate: {rate:.4f}%")
```

### 2. Run a Mini Backtest
```python
import datetime as dt
from BT.data_handler import TimeGrid
from BT.query_engine import QueryDrivenBacktest
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

dates = [dt.date(2025, 9, d) for d in [15, 16, 17, 18, 19]]
grid = TimeGrid(dates)

query = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.RATE,
    tenor="5Y",
    curve="USD-SOFR-1D",
    structure_kwargs={"bpv": 1_000_000},
)

# (Create strategy with triggers...)

mdp = IRSwapsMDP()
bt = QueryDrivenBacktest(time_grid=grid, mdp=mdp, strategy=strategy)
bt.run()

print(bt.mtm_history)
```

### 3. Check Your Cache
```bash
# View cache location and size
du -sh ~/.cache/arbs/zodb/dump/

# List cached files
ls -lh ~/.cache/arbs/zodb/dump/

# Clear cache if needed
rm -rf ~/.cache/arbs/zodb/dump/*.fs*
```

## Troubleshooting

### Python version wrong?
```bash
python3.13 --version  # Should be 3.13.x
```

### QuantLib won't install?
```bash
# Use conda (better binary support)
conda install -c conda-forge quantlib
```

### Import errors?
```bash
# Add ARBS to Python path
export PYTHONPATH="/path/to/ARBS:$PYTHONPATH"
python your_script.py
```

### Cache locked?
```bash
# Delete lock file
rm ~/.cache/arbs/zodb/dump/*.lock
```

### Need help?
- See [INSTALLATION_AND_SETUP_GUIDE.md](INSTALLATION_AND_SETUP_GUIDE.md#9-common-installation-issues-and-solutions) for detailed troubleshooting
- Check [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) to verify your installation
- Review [README.md](README.md) for architecture overview

## System Requirements

| Requirement | Minimum | Recommended |
|------------|---------|------------|
| Python | 3.13.x | 3.13.x |
| RAM | 4 GB | 16 GB |
| Disk | 5 GB | 50 GB |
| CPU | 2 cores | 4+ cores |
| OS | Linux, macOS, Windows | Linux |

## What's Installed?

Core packages:
- `numpy`, `pandas` - Data handling
- `QuantLib` - Interest rate models
- `rateslib` - Alternative curve building
- `ZODB` - Persistent caching
- `requests`, `httpx` - Data fetching
- `tqdm` - Progress bars

See [requirements.txt](requirements.txt) for complete list.

## Next: Explore ARBS

1. **Architecture**: [README.md](README.md) - System design and components
2. **Modules**: [docs/](docs/) - Detailed module documentation
3. **Examples**: [month_end_irswaps_backtest.ipynb](month_end_irswaps_backtest.ipynb) - Working example
4. **API Reference**: Module docs for function signatures
5. **Advanced**: [Development vs Production](INSTALLATION_AND_SETUP_GUIDE.md#10-development-vs-production-deployment)

## Development Workflow (Optional)

If you plan to contribute:

```bash
# Install dev tools
pip install -r requirements-dev.txt

# Create feature branch
git checkout -b feature/my-feature

# Make changes and test
black .
flake8 .
pytest tests/

# Commit and push
git add .
git commit -m "Add my feature"
git push origin feature/my-feature

# Create pull request on GitHub
```

## Production Deployment (Advanced)

For production use:

1. Use [Dockerfile.example](Dockerfile.example) for containerization
2. Use [systemd service](arbs-backtest.service.example) for scheduling
3. Set up monitoring with [Prometheus metrics](INSTALLATION_AND_SETUP_GUIDE.md#monitoring-and-alerting)
4. Configure [ZODB cache maintenance](INSTALLATION_AND_SETUP_GUIDE.md#cache-maintenance)
5. Enable [audit logging](config/settings.example.yaml)

See [Production Deployment Section](INSTALLATION_AND_SETUP_GUIDE.md#production-environment) for details.

## Staying Updated

```bash
# Check for updates
cd ARBS
git pull origin main

# Reinstall updated dependencies
pip install --upgrade -r requirements.txt
```

## Community & Support

- **Issues**: GitHub Issues (when available)
- **Discussions**: GitHub Discussions (when available)
- **Email**: Check repository for contact info

## Success Checklist

You're ready to use ARBS when:

- [ ] Python 3.13.x installed
- [ ] Virtual environment activated (prompt shows venv name)
- [ ] `pip install -r requirements.txt` completed without errors
- [ ] `python -c "from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP; print('✓')"` works
- [ ] Cache directory exists and is writable
- [ ] You can run the mini backtest example above
- [ ] You've read this document and README.md

## Final Words

ARBS is designed to be:
- **Modular**: Swap components (curves, data sources, products)
- **Extensible**: Add new products, metrics, and data sources
- **Deterministic**: Same inputs always produce same results
- **Auditable**: All trades and valuations logged

Start small (single date, single query), then expand to larger grids and more complex strategies.

Happy backtesting!

---

**Questions?** See [INSTALLATION_GUIDE_INDEX.md](INSTALLATION_GUIDE_INDEX.md) for document map.

**Version**: 1.0  
**Updated**: 2025-11-10  
**Python**: 3.13.x

