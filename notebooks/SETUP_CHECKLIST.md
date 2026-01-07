# ARBS Installation and Setup Checklist

Use this checklist to verify you have completed all necessary setup steps.

## Pre-Installation Phase

- [ ] **System Check**
  - [ ] Running Linux, macOS, or Windows 10/11
  - [ ] 4GB+ RAM available
  - [ ] 5GB+ disk space available
  - [ ] Internet connectivity confirmed

- [ ] **Python Check**
  - [ ] Python 3.13.x installed
    ```bash
    python --version  # Should show 3.13.x
    ```
  - [ ] pip is available
    ```bash
    pip --version
    ```
  - [ ] venv is available
    ```bash
    python -m venv --help
    ```

## Installation Phase

- [ ] **Create Virtual Environment**
  - [ ] Virtual environment created
    ```bash
    python3.13 -m venv arbs_env
    ```
  - [ ] Virtual environment activated
    - Linux/macOS: `source arbs_env/bin/activate`
    - Windows: `.\arbs_env\Scripts\Activate.ps1`
  - [ ] Prompt shows (arbs_env) prefix

- [ ] **Upgrade Base Tools**
  - [ ] pip upgraded
    ```bash
    pip install --upgrade pip
    ```
  - [ ] setuptools upgraded
    ```bash
    pip install --upgrade setuptools wheel
    ```

- [ ] **Clone Repository**
  - [ ] Repository cloned
    ```bash
    git clone https://github.com/yieldcurvemonkey/ARBS.git
    cd ARBS
    ```
  - [ ] Branch is correct (`main` branch)
    ```bash
    git branch
    ```

- [ ] **Install Dependencies**
  - [ ] All dependencies installed
    ```bash
    pip install -r requirements.txt
    ```
  - [ ] Installation completed without errors
  - [ ] All packages listed with `pip list`

## Configuration Phase

- [ ] **Environment Variables**
  - [ ] `.env` file created (or copy `.env.example`)
    ```bash
    cp .env.example .env
    ```
  - [ ] FRED_API_KEY set (optional but recommended)
    ```bash
    # In .env or as environment variable
    export FRED_API_KEY="your_key"
    ```
  - [ ] Check environment variables loaded
    ```python
    import os
    print(os.getenv("FRED_API_KEY"))
    ```

- [ ] **Cache Directory**
  - [ ] Cache directory created
    ```bash
    mkdir -p ~/.cache/arbs/zodb/dump
    ```
  - [ ] Directory is writable
    ```bash
    touch ~/.cache/arbs/zodb/dump/test.txt
    rm ~/.cache/arbs/zodb/dump/test.txt
    ```

- [ ] **Configuration Files**
  - [ ] config/ directory exists
    ```bash
    mkdir -p config
    ```
  - [ ] settings.yaml created (optional)
    ```bash
    cp config/settings.example.yaml config/settings.yaml
    ```

## Verification Phase - Core Dependencies

- [ ] **Test Core Imports**
  ```python
  python -c "import numpy; print('✓ numpy')"
  python -c "import pandas; print('✓ pandas')"
  python -c "import QuantLib; print('✓ QuantLib')"
  python -c "from ZODB import DB; print('✓ ZODB')"
  python -c "import rateslib; print('✓ rateslib')"
  python -c "import transaction; print('✓ transaction')"
  python -c "import tqdm; print('✓ tqdm')"
  ```
  - All imports successful: **[ ]**

## Verification Phase - ARBS Modules

- [ ] **Test ARBS Imports**
  ```python
  python -c "from BT.query_engine import QueryDrivenBacktest; print('✓ BT')"
  python -c "from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP; print('✓ MDP')"
  python -c "from Query.IRSwaps.IRSwapQuery import IRSwapQuery; print('✓ Query')"
  python -c "from Caching.ZODBCacheMixin import ZODBCacheMixin; print('✓ Caching')"
  ```
  - All ARBS imports successful: **[ ]**

## Verification Phase - Functionality

- [ ] **Test Cache System**
  - [ ] Cache initialization works
    ```python
    python test_cache.py  # See INSTALLATION_AND_SETUP_GUIDE.md
    ```
  - [ ] Cache files created in expected location
    ```bash
    ls -lh ~/.cache/arbs/zodb/dump/
    ```

- [ ] **Test Data Source**
  - [ ] CME data fetcher works
    ```python
    python test_cme_data.py  # See INSTALLATION_AND_SETUP_GUIDE.md
    ```
  - [ ] Can retrieve par rates without error
  - [ ] Cache is populated with curve data

- [ ] **Test Backtest Engine**
  - [ ] Can run minimal backtest
    ```python
    python test_backtest.py  # See INSTALLATION_AND_SETUP_GUIDE.md
    ```
  - [ ] Backtest completes without errors
  - [ ] Results are produced
  - [ ] MTM history is populated

## Documentation Phase

- [ ] **Review Documentation**
  - [ ] Read main README.md
    ```bash
    cat README.md | less
    ```
  - [ ] Review Installation Guide (this document)
  - [ ] Review Quick Start Guide
    ```bash
    cat QUICK_START_GUIDE.md
    ```

- [ ] **Explore Examples**
  - [ ] Jupyter notebook environment set up (optional)
    ```bash
    pip install jupyter
    jupyter notebook month_end_irswaps_backtest.ipynb
    ```
  - [ ] Reviewed example backtest code

## Development Setup (Optional)

For contributors/developers only:

- [ ] **Development Tools**
  - [ ] pytest installed
    ```bash
    pip install pytest pytest-cov
    ```
  - [ ] Code linting tools installed (optional)
    ```bash
    pip install black flake8 mypy
    ```

- [ ] **Git Setup**
  - [ ] Git configured
    ```bash
    git config --global user.name "Your Name"
    git config --global user.email "you@example.com"
    ```
  - [ ] Repository origin set correctly
    ```bash
    git remote -v
    ```

## Post-Setup Actions

- [ ] **Environment Ready Checklist**
  - [ ] All verification tests passed
  - [ ] Documentation read
  - [ ] Cache system operational
  - [ ] Data sources accessible
  - [ ] Ready for first backtest

- [ ] **Backup Important Files**
  - [ ] .env file backed up securely
  - [ ] Configuration files backed up
  - [ ] Any API keys stored securely (not in git!)

- [ ] **Set Reminders**
  - [ ] [ ] Cache pack scheduled (weekly)
  - [ ] [ ] Dependency updates scheduled (monthly)
  - [ ] [ ] Documentation review scheduled (quarterly)

## Troubleshooting Checklist

If you encounter issues, check:

- [ ] Virtual environment is activated (venv prefix in prompt)
- [ ] All dependencies installed: `pip list | grep -E "numpy|pandas|QuantLib|ZODB"`
- [ ] PYTHONPATH includes ARBS: `echo $PYTHONPATH`
- [ ] Cache directory exists and is writable: `touch ~/.cache/arbs/zodb/dump/test && rm $_`
- [ ] Internet connection working: `ping -c 1 github.com`
- [ ] No conflicting packages: `pip check`
- [ ] .env file properly formatted (no quotes, valid format)
- [ ] Python version is 3.13.x: `python --version`

## Final Confirmation

Once all checks are complete:

```bash
python -c "
import sys
print('=' * 60)
print('ARBS Installation Complete!')
print('=' * 60)
print(f'Python: {sys.version}')
print(f'Executable: {sys.executable}')

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
mdp = IRSwapsMDP()
print('✓ MDP initialized successfully')

from BT.query_engine import QueryDrivenBacktest
print('✓ Backtest engine loaded')

print('=' * 60)
print('You are ready to use ARBS!')
print('Next: Read QUICK_START_GUIDE.md')
print('=' * 60)
"
```

**Setup Date**: ___________________

**Setup By**: ___________________

**Notes**: 
___________________________________________________________________________
___________________________________________________________________________

