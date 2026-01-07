# ARBS Quick Start Guide

Get up and running with ARBS in under 5 minutes.

## Prerequisites

- Python 3.13.x installed
- pip and venv available
- ~2GB disk space

## Option 1: Linux/macOS (5 min)

```bash
# 1. Create environment (1 min)
python3.13 -m venv arbs_env
source arbs_env/bin/activate

# 2. Clone and install (3 min)
git clone https://github.com/yieldcurvemonkey/ARBS.git
cd ARBS
pip install --upgrade pip
pip install -r requirements.txt

# 3. Verify (1 min)
python -c "from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP; print('✓ ARBS ready!')"
```

## Option 2: Windows PowerShell (5 min)

```powershell
# 1. Create environment
python -m venv arbs_env
.\arbs_env\Scripts\Activate.ps1

# 2. Clone and install
git clone https://github.com/yieldcurvemonkey/ARBS.git
cd ARBS
python -m pip install --upgrade pip
pip install -r requirements.txt

# 3. Verify
python -c "from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP; print('✓ ARBS ready!')"
```

## Option 3: With Conda (Recommended for macOS/Windows)

```bash
# 1. Create environment
conda create -n arbs python=3.13 -y
conda activate arbs

# 2. Install critical packages from conda-forge
conda install -c conda-forge quantlib -y

# 3. Install remainder from pip
git clone https://github.com/yieldcurvemonkey/ARBS.git
cd ARBS
pip install -r requirements.txt

# 4. Verify
python -c "import quantlib; from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP; print('✓ Ready!')"
```

## First Run: Query-Driven Backtest

Create `test_run.py`:

```python
import datetime as dt
from BT.data_handler import TimeGrid
from BT.query_strategy import QueryStrategy
from BT.triggers import Trigger, TriggerRequirements
from BT.query_actions import AddQueryAction
from BT.query_engine import QueryDrivenBacktest
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from BT.event import TriggerInfo

# Define time grid
dates = [dt.date(2025, 9, d) for d in [15, 16, 17, 18, 19]]  # Mon-Fri
grid = TimeGrid(dates)

# Define query: 5Y par rate
query = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.RATE,
    tenor="5Y",
    curve="USD-SOFR-1D",
    structure_kwargs={"bpv": 1_000_000},
)

# Trigger: always fire
class AlwaysOn(TriggerRequirements):
    def has_triggered(self, state, backtest=None):
        return TriggerInfo(True, info={})

strategy = QueryStrategy(
    name="Demo",
    triggers=[Trigger(AlwaysOn(), actions=[AddQueryAction(query=query)])],
)

# Run backtest
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")
bt = QueryDrivenBacktest(time_grid=grid, mdp=mdp, strategy=strategy)
bt.run()

# Results
print("\nMTM History:")
for date, mtm in sorted(bt.mtm_history.items()):
    print(f"  {date}: ${mtm:,.0f}")

print("\nDone!")
```

Run it:
```bash
python test_run.py
```

Expected output:
```
MTM History:
  2025-09-15: $0
  2025-09-16: $[some value]
  ...
Done!
```

## Next Steps

1. Read the full [Installation Guide](INSTALLATION_AND_SETUP_GUIDE.md)
2. Explore [README.md](README.md) for architecture
3. Check out `month_end_irswaps_backtest.ipynb` for a real example
4. Review documentation in `docs/` folder

## Common Issues

**QuantLib not found?** Use conda:
```bash
conda install -c conda-forge quantlib
```

**Module not found?** Add to path:
```bash
export PYTHONPATH="/path/to/ARBS:$PYTHONPATH"
```

**Need help?** See [Troubleshooting](INSTALLATION_AND_SETUP_GUIDE.md#9-common-installation-issues-and-solutions)

