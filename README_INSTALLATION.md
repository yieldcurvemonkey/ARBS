# ARBS Installation & Setup - Quick Reference

**Complete documentation for getting ARBS up and running.**

## Start Here: Choose Your Path

### 1. I just want to use ARBS (5 minutes)
```bash
python3.13 -m venv arbs_env
source arbs_env/bin/activate
git clone https://github.com/yieldcurvemonkey/ARBS.git
cd ARBS
pip install -r requirements.txt
python -c "from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP; print('✓ Ready!')"
```
→ **Next:** Read [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)

### 2. I'm setting this up for my team (30 minutes)
→ **Start:** [GETTING_STARTED.md](GETTING_STARTED.md) (entry point)  
→ **Then:** [INSTALLATION_AND_SETUP_GUIDE.md](INSTALLATION_AND_SETUP_GUIDE.md) (comprehensive)  
→ **Configure:** Copy `.env.example` to `.env`  
→ **Deploy:** Use [Dockerfile.example](Dockerfile.example) or [systemd service](arbs-backtest.service.example)

### 3. I'm contributing code (1 hour)
```bash
# Same as #1 plus:
pip install -r requirements-dev.txt
```
→ **Read:** [Development Setup Section](INSTALLATION_AND_SETUP_GUIDE.md#development-environment)

### 4. I need this in production (2-3 hours)
→ **Read:** [Production Deployment Section](INSTALLATION_AND_SETUP_GUIDE.md#production-environment)  
→ **Use:** `requirements-prod.txt`  
→ **Deploy:** Docker or systemd

## Documentation Files

### Main Guides (Read These)
| Guide | Time | For Whom |
|-------|------|---------|
| **[GETTING_STARTED.md](GETTING_STARTED.md)** | 15 min | Everyone (entry point) |
| **[QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)** | 5 min | Quick setup |
| **[INSTALLATION_AND_SETUP_GUIDE.md](INSTALLATION_AND_SETUP_GUIDE.md)** | 2 hours | Complete reference |
| **[SETUP_CHECKLIST.md](SETUP_CHECKLIST.md)** | 15 min | Verify installation |
| **[INSTALLATION_GUIDE_INDEX.md](INSTALLATION_GUIDE_INDEX.md)** | 10 min | Navigation guide |

### Configuration & Deployment (Copy These)
| File | Purpose |
|------|---------|
| **[.env.example](.env.example)** | Environment variables (copy to `.env`) |
| **[config/settings.example.yaml](config/settings.example.yaml)** | Config file (copy to `config/settings.yaml`) |
| **[requirements-prod.txt](requirements-prod.txt)** | Production dependencies |
| **[requirements-dev.txt](requirements-dev.txt)** | Development tools |
| **[Dockerfile.example](Dockerfile.example)** | Docker container |
| **[docker-compose.example.yml](docker-compose.example.yml)** | Docker Compose |
| **[arbs-backtest.service.example](arbs-backtest.service.example)** | Systemd service |
| **[arbs-backtest.timer.example](arbs-backtest.timer.example)** | Systemd scheduler |

## Key Topics Covered

### Installation
- 4 methods: pip, conda, editable, from source
- Step-by-step for each platform
- Dependency troubleshooting

### Configuration
- Environment variables (.env file)
- Data sources (CME, SDR, GSQUANT)
- API keys (FRED)
- ZODB caching
- Logging and monitoring

### Verification
- 5 test suites with code
- Cache verification
- Data source testing
- Complete backtest test

### Troubleshooting
- 8 common issues with solutions
- Platform-specific help
- Proxy/firewall setup
- Memory and performance issues

### Deployment
- Development environment setup
- Production environment setup
- Docker containerization
- Systemd scheduling
- Kubernetes deployment
- Monitoring and alerting

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|------------|
| Python | 3.13.x | 3.13.x |
| RAM | 4 GB | 16 GB |
| Disk | 5 GB | 50 GB |
| CPU | 2 cores | 4+ cores |
| OS | Linux/macOS/Windows | Linux |

## Common Commands

```bash
# Setup
python3.13 -m venv arbs_env
source arbs_env/bin/activate
pip install -r requirements.txt

# Verify
python test_environment.py
python test_dependencies.py
python test_backtest.py

# Configuration
cp .env.example .env
# Edit .env with your settings

# Cache
du -sh ~/.cache/arbs/zodb/dump/
rm -rf ~/.cache/arbs/zodb/dump/*.fs*

# Docker
docker build -f Dockerfile.example -t arbs:latest .
docker run -v /mnt/cache:/mnt/arbs_cache arbs:latest

# Systemd
sudo cp arbs-backtest.service.example /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable arbs-backtest
sudo systemctl start arbs-backtest
```

## What Gets Installed?

Core packages (from `requirements.txt`):
- `numpy`, `pandas` - Data handling
- `QuantLib`, `rateslib` - Pricing engines
- `ZODB`, `BTrees` - Persistent caching
- `requests`, `httpx` - Data fetching
- Plus 16 more packages

Total: ~1.5 GB when installed

## First Test

After installation:
```python
import datetime as dt
from BT.data_handler import TimeGrid
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from BT.triggers import Trigger, TriggerRequirements
from BT.query_actions import AddQueryAction
from BT.query_strategy import QueryStrategy
from BT.query_engine import QueryDrivenBacktest
from BT.event import TriggerInfo

# Build time grid
dates = [dt.date(2025, 9, d) for d in [15, 16, 17, 18, 19]]
grid = TimeGrid(dates)

# Create query
query = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.RATE,
    tenor="5Y",
    curve="USD-SOFR-1D",
    structure_kwargs={"bpv": 1_000_000},
)

# Create strategy
class AlwaysOn(TriggerRequirements):
    def has_triggered(self, state, backtest=None):
        return TriggerInfo(True, info={})

strategy = QueryStrategy(
    name="Test",
    triggers=[Trigger(AlwaysOn(), actions=[AddQueryAction(query=query)])]
)

# Run backtest
mdp = IRSwapsMDP()
bt = QueryDrivenBacktest(time_grid=grid, mdp=mdp, strategy=strategy)
bt.run()

print("MTM History:", bt.mtm_history)
print("✓ Backtest completed!")
```

## Troubleshooting Quick Links

| Issue | Solution |
|-------|----------|
| QuantLib won't install | Use conda: `conda install -c conda-forge quantlib` |
| ZODB lock error | `rm ~/.cache/arbs/zodb/dump/*.lock` |
| Import errors | `export PYTHONPATH="/path/to/ARBS:$PYTHONPATH"` |
| Behind proxy | Set in `.env`: `HTTP_PROXY=...` |
| Missing dependencies | `pip install --upgrade pip && pip install -r requirements.txt` |

See [INSTALLATION_AND_SETUP_GUIDE.md Section 9](INSTALLATION_AND_SETUP_GUIDE.md#9-common-installation-issues-and-solutions) for detailed solutions.

## Next Steps

1. **Read** → [GETTING_STARTED.md](GETTING_STARTED.md)
2. **Install** → Run 5-minute setup above
3. **Verify** → [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md)
4. **Configure** → Copy `.env.example` to `.env`
5. **Test** → Run verification tests
6. **Deploy** → Choose development or production path
7. **Use** → Start running backtests!

## Getting Help

| Question | Resource |
|----------|----------|
| General setup | [GETTING_STARTED.md](GETTING_STARTED.md) |
| Quick questions | [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md) |
| Detailed info | [INSTALLATION_AND_SETUP_GUIDE.md](INSTALLATION_AND_SETUP_GUIDE.md) |
| Verify setup | [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) |
| Find topics | [INSTALLATION_GUIDE_INDEX.md](INSTALLATION_GUIDE_INDEX.md) |
| Specific errors | [Troubleshooting Section](INSTALLATION_AND_SETUP_GUIDE.md#9-common-installation-issues-and-solutions) |
| Architecture | [README.md](README.md) |

## Documentation Map

```
README_INSTALLATION.md (you are here)
├── GETTING_STARTED.md (start here)
├── QUICK_START_GUIDE.md (5 min setup)
├── INSTALLATION_AND_SETUP_GUIDE.md (comprehensive)
├── SETUP_CHECKLIST.md (verify)
├── INSTALLATION_GUIDE_INDEX.md (navigate)
├── Configuration files
│   ├── .env.example
│   └── config/settings.example.yaml
├── Dependencies
│   ├── requirements.txt
│   ├── requirements-prod.txt
│   ├── requirements-dev.txt
│   └── requirements-ci.txt
└── Deployment
    ├── Dockerfile.example
    ├── docker-compose.example.yml
    ├── arbs-backtest.service.example
    └── arbs-backtest.timer.example
```

## Version Info

- **Documentation Version**: 1.0
- **Python Required**: 3.13.x
- **Created**: 2025-11-10
- **Status**: Complete

---

**Ready to start?** → [GETTING_STARTED.md](GETTING_STARTED.md)

