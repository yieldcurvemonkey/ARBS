# ARBS Installation and Setup Guide

**Awesome Rates Backtesting System (ARBS) - Complete Getting Started Documentation**

## Table of Contents

1. [System Requirements](#system-requirements)
2. [Installation Methods](#installation-methods)
3. [Dependency Installation and Troubleshooting](#dependency-installation-and-troubleshooting)
4. [Data Sources and API Configuration](#data-sources-and-api-configuration)
5. [ZODB Cache Setup and Configuration](#zodb-cache-setup-and-configuration)
6. [Environment Variables and Settings](#environment-variables-and-settings)
7. [First-Time Setup Checklist](#first-time-setup-checklist)
8. [Verification Steps and Test Runs](#verification-steps-and-test-runs)
9. [Common Installation Issues and Solutions](#common-installation-issues-and-solutions)
10. [Development vs. Production Deployment](#development-vs-production-deployment)

---

## 1. System Requirements

### Minimum Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|------------|
| **CPU** | 2 cores | 4+ cores (parallel processing) |
| **RAM** | 4 GB | 16 GB (for large backtests) |
| **Disk Space** | 5 GB | 50+ GB (depends on historical data cache) |
| **Network** | Stable connection | High-speed (for data fetching) |

### Python Version

- **Required**: Python 3.13.x
- **Minimum Python 3.11** may work but is not officially tested
- **Python 3.14+** not yet tested (bleeding edge)

To check your Python version:
```bash
python --version
# Expected: Python 3.13.x
```

### Operating System Support

| OS | Status | Notes |
|----|--------|-------|
| **Linux** (Ubuntu 20.04+, Debian 11+, CentOS 7+) | Fully Supported | Primary development platform |
| **macOS** (Intel/Apple Silicon, 10.14+) | Fully Supported | Some dependencies may require homebrew |
| **Windows** (10/11) | Fully Supported | Use Windows PowerShell or WSL2; wheel availability important |

### External Dependencies (System-Level)

Some Python packages have C/C++ extensions requiring compilation:

**Linux (Ubuntu/Debian)**:
```bash
sudo apt-get update
sudo apt-get install -y \
  python3.13 \
  python3.13-dev \
  python3.13-venv \
  build-essential \
  libboost-all-dev \
  libboost-python-dev
```

**macOS** (using Homebrew):
```bash
brew install python@3.13 boost boost-python3
```

**Windows** (using conda recommended):
- Visual Studio Build Tools 2019+ or MinGW-w64
- Or use pre-built wheels via conda

---

## 2. Installation Methods

### Method 1: Using pip (Recommended for Users)

This is the standard method for end users and developers.

#### Step 1: Create and Activate Virtual Environment

```bash
# Create virtual environment
python3.13 -m venv arbs_env

# Activate (Linux/macOS)
source arbs_env/bin/activate

# Activate (Windows PowerShell)
.\arbs_env\Scripts\Activate.ps1

# Activate (Windows cmd.exe)
arbs_env\Scripts\activate.bat
```

#### Step 2: Upgrade pip, setuptools, and wheel

```bash
pip install --upgrade pip setuptools wheel
```

#### Step 3: Clone the Repository

```bash
git clone https://github.com/yieldcurvemonkey/ARBS.git
cd ARBS
```

#### Step 4: Install from requirements.txt

```bash
pip install -r requirements.txt
```

**Expected output**:
```
Successfully installed numpy-2.3.2 pandas-2.3.1 ... zope.interface-7.2
```

#### Step 5: Verify Installation

```bash
python -c "import ARBS; print('ARBS imported successfully')"
python -c "import QuantLib; print('QuantLib version:', QuantLib.__version__)"
```

### Method 2: Using Conda (Recommended for Data Scientists)

Conda often has better pre-compiled binaries for scientific packages.

#### Step 1: Create Conda Environment

```bash
# Create environment from scratch
conda create -n arbs python=3.13 -y

# Activate
conda activate arbs
```

#### Step 2: Install Core Dependencies via Conda

```bash
# Install packages that benefit from conda's binary optimization
conda install -c conda-forge -y \
  numpy \
  pandas \
  pyarrow \
  quantlib \
  matplotlib \
  scikit-learn
```

#### Step 3: Clone and Install Remaining Dependencies

```bash
git clone https://github.com/yieldcurvemonkey/ARBS.git
cd ARBS

# Install pip-only packages
pip install -r requirements.txt
```

#### Step 4: Verify

```bash
python -c "import quantlib as ql; print('QuantLib:', ql.__version__)"
python -c "from ZODB import DB; print('ZODB OK')"
```

### Method 3: Development Installation (For Contributors)

If you plan to modify ARBS itself:

#### Step 1: Fork and Clone

```bash
# Fork on GitHub, then clone your fork
git clone https://github.com/<YOUR_USERNAME>/ARBS.git
cd ARBS
```

#### Step 2: Create Development Environment

```bash
python3.13 -m venv arbs_dev_env
source arbs_dev_env/bin/activate  # or .bat on Windows
```

#### Step 3: Install in Editable Mode

```bash
# Upgrade pip first
pip install --upgrade pip setuptools wheel

# Install ARBS and dependencies in editable mode
pip install -e .
pip install -r requirements.txt

# Optional: install development tools
pip install pytest pytest-cov black flake8 mypy
```

#### Step 4: Verify Development Setup

```bash
python -c "import sys; sys.path.insert(0, '.'); from BT import query_engine; print('Dev setup OK')"
```

### Method 4: Installation from Source with Specific Version

For reproducible deployments:

```bash
git clone https://github.com/yieldcurvemonkey/ARBS.git
cd ARBS

# Checkout specific release (if available)
git tag  # list available tags
git checkout v1.0.0  # if a tag exists

# Create environment
python3.13 -m venv venv
source venv/bin/activate

# Install with pinned versions
pip install -r requirements.txt
```

---

## 3. Dependency Installation and Troubleshooting

### Core Dependencies Overview

| Package | Version | Purpose | Notes |
|---------|---------|---------|-------|
| `numpy` | 2.3.2 | Numerical computing | Critical |
| `pandas` | 2.3.1 | Data manipulation | Critical |
| `QuantLib` | 1.39 | Interest rate modeling | Core pricing engine |
| `rateslib` | 2.1.1 | Alternative curve building | RatesLib backend |
| `ZODB` | 6.0.1 | Persistent caching | Cache storage |
| `BTrees` | 6.1 | ZODB B-tree structures | Cache indexing |
| `transaction` | 5.0 | ZODB transactions | Cache consistency |
| `tqdm` | 4.67.1 | Progress bars | UI enhancement |
| `requests` | 2.32.4 | HTTP client | Data fetching |
| `httpx` | 0.28.1 | Async HTTP client | Concurrent data fetching |

### Handling Binary Package Issues

#### QuantLib Installation Challenges

**Problem**: QuantLib fails to compile or wheel not found for your platform

**Solution 1: Use conda** (Recommended)
```bash
conda install -c conda-forge quantlib=1.39
```

**Solution 2: Install pre-built wheel**
```bash
# For common platforms
pip install QuantLib==1.39 --only-binary=:all:
```

**Solution 3: Compile from source** (Expert)
```bash
# This requires Boost libraries
pip install QuantLib==1.39 --no-binary=QuantLib
```

#### ZODB Installation Issues

**Problem**: ZODB or BTrees installation fails

**Solution**:
```bash
# Ensure setuptools is up to date
pip install --upgrade setuptools wheel
# Then retry
pip install ZODB==6.0.1 BTrees==6.1
```

### Testing Individual Dependencies

```bash
# Test numpy
python -c "import numpy as np; print('numpy', np.__version__)"

# Test pandas
python -c "import pandas as pd; print('pandas', pd.__version__)"

# Test QuantLib
python -c "import QuantLib as ql; print('QuantLib', ql.__version__)"

# Test ZODB
python -c "from ZODB import DB; from BTrees.OOBTree import OOBTree; print('ZODB OK')"

# Test rateslib
python -c "import rateslib; print('rateslib OK')"

# Test transaction
python -c "import transaction; print('transaction OK')"
```

### Dependency Conflicts

If you encounter version conflicts:

```bash
# Create fresh environment
python3.13 -m venv fresh_env
source fresh_env/bin/activate

# Install requirements in order of stability
pip install numpy pandas pyarrow
pip install QuantLib rateslib
pip install ZODB BTrees persistent transaction zc.lockfile
pip install requests httpx aiohttp
pip install tqdm matplotlib plotly scikit-learn

# Verify
pip list
```

### Optional Development Dependencies

If modifying the codebase:

```bash
# Testing
pip install pytest pytest-cov pytest-asyncio

# Code quality
pip install black flake8 mypy pylint

# Documentation
pip install sphinx sphinx-rtd-theme

# Notebooks
pip install jupyter ipykernel
```

---

## 4. Data Sources and API Configuration

ARBS supports multiple market data sources, each with different requirements.

### Supported Data Sources

#### A. CME End-of-Day (CME_NY_EOD_LIVE)

**Availability**: Public data, no credentials required

**Data Coverage**:
- USD interest rate swaps (SOFR, LIBOR-based)
- 3M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y tenors
- Daily closing snapshots (16:00 ET)

**Configuration**:
```python
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

# Initialize with CME source
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")
```

**Usage**:
```python
import datetime as dt

request = {
    "curve_name": "USD-SOFR-1D",
    "timestamp": dt.date(2025, 9, 15),
}

pricer = mdp.get_pricer(request)
print(pricer.par_rate("5Y"))  # Get 5Y par rate
```

#### B. SDR Intraday (SDR_INTRADAY-RL)

**Availability**: Requires SDR data files or API access

**Data Coverage**:
- Tick-level trade data from CFTC SDR
- Multiple tenors and currencies
- Intraday resolution (reconstructed curves)

**Configuration**:
```python
# Requires SDR data builder setup (see Section 4.B.1)
mdp = IRSwapsMDP(source="SDR_INTRADAY-RL")
```

**Data File Location**: 
```
./data/sdr/  # Expected local SDR files
```

#### C. GSQUANT RatesLib (GSQUANT-RL)

**Availability**: Requires GSQuant library (optional)

**Configuration**:
```python
mdp = IRSwapsMDP(source="GSQUANT-RL")
```

### API Keys and External Services

#### Federal Reserve Economic Data (FRED)

Some builders fetch US Treasury rates from FRED.

**Optional API Key**:
```bash
# Set environment variable
export FRED_API_KEY="your_api_key_here"
```

**Get API Key**:
1. Visit https://fredaccount.stlouisfed.org/account/api
2. Sign up for free account
3. Copy your API key

**Configuration in Code**:
```python
import os
os.environ["FRED_API_KEY"] = "your_key"

# Or in .env file (see Section 6)
# FRED_API_KEY=your_key
```

#### CME FTP Access (Optional for Futures)

CME futures data is fetched via public FTP. No authentication required in most cases.

**Behind Corporate Proxy?**
```python
from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.CMEFetcherV2 import CMEFetcherV2

# Pass proxy settings
fetcher = CMEFetcherV2(
    proxy="http://proxy.company.com:8080",
    proxy_auth=("username", "password")
)
```

### Data Source Configuration File

Create `config/data_sources.yaml` in your project root:

```yaml
# config/data_sources.yaml
data_sources:
  cme:
    source: "CME_NY_EOD_LIVE-ql_basic"
    enabled: true
    
  sdr:
    source: "SDR_INTRADAY-RL"
    enabled: false
    sdr_data_dir: "./data/sdr"
    
  fred:
    api_key: ${FRED_API_KEY}
    enabled: true

cache:
  use_btree: true
  force_refresh: false
```

**Load in Python**:
```python
import yaml
from pathlib import Path

config_path = Path("config/data_sources.yaml")
with open(config_path) as f:
    config = yaml.safe_load(f)

# Use config
mdp_source = config["data_sources"]["cme"]["source"]
mdp = IRSwapsMDP(source=mdp_source)
```

---

## 5. ZODB Cache Setup and Configuration

ARBS uses ZODB (Zope Object Database) for persistent caching of expensive computations.

### ZODB Overview

ZODB is an object-oriented database that persists Python objects to disk:

- **Location**: `~/.cache/arbs/zodb/` (Linux/macOS) or `%LOCALAPPDATA%\ARBS\zodb\` (Windows)
- **File**: `.fs` files (FileStorage format)
- **Purpose**: Cache pricer/curve objects, valuations, and time-series data

### Basic ZODB Cache Configuration

#### Option 1: Default Cache Location (Recommended for Most Users)

```python
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

# Uses default cache path: ~/.cache/arbs/zodb/dump/cme_ny_eod_live-ql_basic.fs
mdp = IRSwapsMDP(
    source="CME_NY_EOD_LIVE-ql_basic",
    use_btree=True,  # Use B-tree indexing (faster for large caches)
    force_refresh=False  # Don't invalidate cache
)
```

#### Option 2: Custom Cache Location

```python
from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

# Set custom cache root before instantiation
ZODBCacheMixin.CACHE_ROOT = "/mnt/large_ssd/arbs_cache"

mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")
```

#### Option 3: Disable Cache (Development Only)

```python
# Use in-memory cache only (no persistence)
from ZODB.DemoStorage import DemoStorage

mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic", use_cache=False)
```

### Advanced ZODB Configuration

#### Cache with Custom Codecs

```python
import pickle
from Caching.ZODBCacheMixin import ZODBCacheMixin

class MyCachedMDP(ZODBCacheMixin):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Define encoding/decoding functions
        def encode_pricer(obj):
            return pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
        
        def decode_pricer(data):
            return pickle.loads(data)
        
        # Open cache with custom codec
        self.zodb_open_cache(
            cache_attr="pricer_cache",
            path="/path/to/cache.fs",
            encode=encode_pricer,
            decode=decode_pricer
        )

# Usage
mdp = MyCachedMDP()
```

#### Batched Writes for Performance

```python
with mdp.batched():
    # All cache writes within this context are batched
    for date in date_range:
        request = {"curve_name": "USD-SOFR-1D", "timestamp": date}
        pricer = mdp.get_pricer(request)
        # Writes are accumulated
    # Committed at context exit
```

#### Cache Diagnostics

```python
from Caching.ZODBCacheMixin import ZODBCacheMixin

# View active cache handles
diagnostics = ZODBCacheMixin.diagnostics()
print(diagnostics)
# Output: {'/path/to/cache1.fs': 2, '/path/to/cache2.fs': 1}
```

### Timeseries Cache Configuration

ARBS also supports a specialized timeseries cache using Parquet files:

#### Setup Timeseries Cache

```python
from Caching.timeseries_cache import append_timeseries, read_timeseries, WriteOptions
import pandas as pd
from ZODB import DB
from ZODB.FileStorage import FileStorage

# Open ZODB connection
storage = FileStorage("./cache/timeseries.fs")
db = DB(storage)
connection = db.open()
root = connection.root()

# Define write options
opts = WriteOptions(
    base_dir="./data/timeseries",
    compression="zstd",  # or "snappy", "gzip"
    row_group_size=256_000,
    partition_fmt="date=%Y-%m-%d"
)

# Append timeseries data
df = pd.DataFrame({
    "rate": [2.5, 2.51, 2.52],
}, index=pd.date_range("2025-09-15", periods=3, freq="D"))

metas = append_timeseries(
    root,
    symbol="USD-SOFR-5Y",
    df=df,
    opts=opts
)
```

#### Read Timeseries from Cache

```python
import datetime as dt

df = read_timeseries(
    root,
    symbol="USD-SOFR-5Y",
    start=dt.date(2025, 9, 15),
    end=dt.date(2025, 9, 30),
    base_dir="./data/timeseries"
)

print(df)
```

### Cache Maintenance

#### Clean Stale Entries

```python
from Caching.timeseries_cache import vacuum_catalog

# Remove catalog entries for missing files
removed = vacuum_catalog(
    root,
    base_dir="./data/timeseries",
    delete_stale_files=True  # Also delete orphaned files
)

print(f"Removed {removed} stale entries")
```

#### Manual Cache Cleanup

```bash
# List cache files
ls -lh ~/.cache/arbs/zodb/dump/

# Delete specific cache (if needed)
rm ~/.cache/arbs/zodb/dump/cme_ny_eod_live-ql_basic.fs*

# Or use Python
import shutil
from Caching.ZODBCacheMixin import ZODBCacheMixin

cache_root = ZODBCacheMixin._user_cache_root()
shutil.rmtree(cache_root / "dump")
```

#### Pack ZODB Database (Reclaim Space)

```python
from ZODB import DB
from ZODB.FileStorage import FileStorage

# Compact the cache file
storage = FileStorage("/path/to/cache.fs")
db = DB(storage)
db.pack()  # Remove old object revisions
db.close()
```

### Cache Troubleshooting

**Issue**: "Lock file exists" error
```python
# Force read-only mode
from ZODB.DemoStorage import DemoStorage
from ZODB.FileStorage import FileStorage

try:
    storage = FileStorage("cache.fs")
except LockError:
    # Fallback to read-only
    ro = FileStorage("cache.fs", read_only=True)
    storage = DemoStorage(base=ro)
```

**Issue**: Cache grows unbounded
```python
# Periodic pack operation
import schedule
from ZODB import DB
from ZODB.FileStorage import FileStorage

def pack_cache():
    storage = FileStorage("cache.fs")
    db = DB(storage)
    db.pack()
    db.close()
    print("Cache packed successfully")

schedule.every(1).days.do(pack_cache)
```

---

## 6. Environment Variables and Settings

### Required Environment Variables

#### FRED_API_KEY (Optional but Recommended)

```bash
export FRED_API_KEY="your_api_key_here"
```

Get from: https://fredaccount.stlouisfed.org/account/api

#### Python Path (If Running from Outside Repo)

```bash
export PYTHONPATH="/path/to/ARBS:$PYTHONPATH"
```

### .env File Configuration

Create a `.env` file in your project root:

```bash
# .env

# Data API Keys
FRED_API_KEY=your_fred_key_here

# Cache Configuration
ARBS_CACHE_ROOT=/mnt/cache/arbs
ARBS_FORCE_REFRESH_FIXINGS=false
ARBS_USE_BTREE=true

# Data Sources
CME_SOURCE=CME_NY_EOD_LIVE-ql_basic
SDR_DATA_DIR=./data/sdr

# Proxy (if behind corporate firewall)
HTTP_PROXY=http://proxy.company.com:8080
HTTPS_PROXY=http://proxy.company.com:8080

# Development Settings
DEBUG=false
LOG_LEVEL=INFO
```

### Load Environment Variables in Python

```python
import os
from pathlib import Path
from dotenv import load_dotenv

# Load from .env file
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# Access variables
fred_key = os.getenv("FRED_API_KEY")
cache_root = os.getenv("ARBS_CACHE_ROOT")
```

**Install python-dotenv** (if not already installed):
```bash
pip install python-dotenv
```

### Configuration File: config/settings.yaml

```yaml
# config/settings.yaml

app:
  name: ARBS
  version: 1.0.0
  debug: false
  
data:
  sources:
    primary: "CME_NY_EOD_LIVE-ql_basic"
    fallback: "SDR_INTRADAY-RL"
  
  apis:
    fred:
      enabled: true
      key: "${FRED_API_KEY}"
    cme:
      enabled: true
      timeout: 30
  
cache:
  backend: "zodb"
  root_path: "${ARBS_CACHE_ROOT:~/.cache/arbs/zodb}"
  use_btree: true
  force_refresh: false
  max_size_gb: 100
  pack_interval_days: 7

backtest:
  default_time_grid_resolution: "1D"
  max_portfolio_size: 10000
  log_all_transactions: true

logging:
  level: "INFO"
  format: "[%(asctime)s] %(name)s - %(levelname)s - %(message)s"
  file: "logs/arbs.log"
```

### Load Settings in Code

```python
import yaml
from pathlib import Path

def load_settings(config_path="config/settings.yaml"):
    path = Path(config_path)
    with open(path) as f:
        return yaml.safe_load(f)

settings = load_settings()

# Use settings
PRIMARY_SOURCE = settings["data"]["sources"]["primary"]
CACHE_ROOT = settings["cache"]["root_path"]
```

### Logging Configuration

```python
# config/logging.yaml
version: 1
disable_existing_loggers: false

formatters:
  standard:
    format: "[%(asctime)s] %(name)s - %(levelname)s - %(message)s"
  detailed:
    format: "[%(asctime)s] %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] %(message)s"

handlers:
  console:
    class: logging.StreamHandler
    level: INFO
    formatter: standard
    stream: ext://sys.stdout
  
  file:
    class: logging.FileHandler
    level: DEBUG
    formatter: detailed
    filename: logs/arbs.log

root:
  level: DEBUG
  handlers: [console, file]

loggers:
  BT:
    level: INFO
  MDP:
    level: INFO
  Query:
    level: DEBUG
```

**Use in code**:
```python
import logging.config
import yaml

with open("config/logging.yaml") as f:
    config = yaml.safe_load(f)
    logging.config.dictConfig(config)

logger = logging.getLogger(__name__)
logger.info("Application started")
```

---

## 7. First-Time Setup Checklist

Complete the following steps to set up ARBS for the first time:

### Installation Phase

- [ ] **Verify Python version** (3.13.x)
  ```bash
  python --version
  ```

- [ ] **Create virtual environment**
  ```bash
  python3.13 -m venv arbs_env
  source arbs_env/bin/activate
  ```

- [ ] **Clone repository**
  ```bash
  git clone https://github.com/yieldcurvemonkey/ARBS.git
  cd ARBS
  ```

- [ ] **Upgrade pip/setuptools/wheel**
  ```bash
  pip install --upgrade pip setuptools wheel
  ```

- [ ] **Install dependencies**
  ```bash
  pip install -r requirements.txt
  ```

### Configuration Phase

- [ ] **Create .env file**
  ```bash
  cp .env.example .env  # if available
  # Or create manually with FRED_API_KEY, etc.
  ```

- [ ] **Set FRED API key** (optional)
  ```bash
  export FRED_API_KEY="your_key"
  ```

- [ ] **Create cache directory**
  ```bash
  mkdir -p ~/.cache/arbs/zodb/dump
  # or custom location
  mkdir -p /custom/cache/arbs/zodb/dump
  ```

- [ ] **Configure data sources** (optional)
  ```bash
  mkdir -p config
  # Create config/data_sources.yaml (see Section 4)
  ```

### Verification Phase

- [ ] **Test core imports**
  ```bash
  python -c "import QuantLib; print('QuantLib OK')"
  python -c "from ZODB import DB; print('ZODB OK')"
  python -c "from BT.query_engine import QueryDrivenBacktest; print('BT OK')"
  ```

- [ ] **Run quick CME data fetch** (see Section 8)
  ```bash
  python -c "from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP; mdp = IRSwapsMDP(); print('MDP OK')"
  ```

- [ ] **Verify cache creation**
  ```bash
  ls -lh ~/.cache/arbs/zodb/dump/
  ```

### Documentation Phase

- [ ] **Read main README.md**
  ```bash
  cat README.md
  ```

- [ ] **Review example notebook**
  ```bash
  jupyter notebook month_end_irswaps_backtest.ipynb
  ```

- [ ] **Explore Query module documentation**
  ```bash
  cat docs/QUERY_MODULE_COMPREHENSIVE_GUIDE.md
  ```

### Optional: Development Setup

- [ ] **Install development tools** (if contributing)
  ```bash
  pip install pytest black flake8 mypy
  ```

- [ ] **Run tests**
  ```bash
  pytest tests/
  ```

- [ ] **Check code formatting**
  ```bash
  black --check .
  flake8 .
  ```

---

## 8. Verification Steps and Test Runs

### Test 1: Verify Python Environment

```python
# test_environment.py
import sys
import platform

print("=" * 60)
print("ARBS Environment Verification")
print("=" * 60)

# Python version
print(f"\nPython Version: {sys.version}")
print(f"Platform: {platform.platform()}")
print(f"Architecture: {platform.machine()}")

# Check venv
if hasattr(sys, 'real_prefix'):
    print("Virtual Environment: Active (old-style)")
elif hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix:
    print("Virtual Environment: Active (venv)")
else:
    print("WARNING: Virtual environment not detected!")

print("=" * 60)
```

Run it:
```bash
python test_environment.py
```

Expected output:
```
Python Version: 3.13.x ...
Virtual Environment: Active (venv)
```

### Test 2: Verify Core Dependencies

```python
# test_dependencies.py
import importlib

REQUIRED_PACKAGES = [
    "numpy",
    "pandas",
    "pyarrow",
    "QuantLib",
    "rateslib",
    "ZODB",
    "BTrees",
    "persistent",
    "transaction",
    "zc.lockfile",
    "tqdm",
    "requests",
    "httpx",
]

print("Checking core dependencies...\n")

failed = []
for package in REQUIRED_PACKAGES:
    try:
        mod = importlib.import_module(package)
        version = getattr(mod, "__version__", "unknown")
        print(f"✓ {package:20s} {version}")
    except ImportError as e:
        print(f"✗ {package:20s} MISSING")
        failed.append(package)

print("\n" + "=" * 60)
if failed:
    print(f"FAILED: {len(failed)} package(s) missing")
    print(f"Install with: pip install {' '.join(failed)}")
else:
    print("SUCCESS: All dependencies installed")
print("=" * 60)
```

Run it:
```bash
python test_dependencies.py
```

### Test 3: Test Cache Initialization

```python
# test_cache.py
import tempfile
from pathlib import Path
from Caching.ZODBCacheMixin import ZODBCacheMixin

print("Testing ZODB Cache...\n")

# Test default cache path
default_path = ZODBCacheMixin.default_cache_path("test_cache")
print(f"Default cache path: {default_path}")

# Test custom cache path
with tempfile.TemporaryDirectory() as tmpdir:
    custom_path = Path(tmpdir) / "test.fs"
    
    try:
        ZODBCacheMixin.CACHE_ROOT = Path(tmpdir)
        path = ZODBCacheMixin.default_cache_path("test")
        print(f"Custom cache path: {path}")
        
        # Try to open cache
        from ZODB import DB
        from ZODB.FileStorage import FileStorage
        
        storage = FileStorage(str(custom_path))
        db = DB(storage)
        root = db.root()
        root["test_key"] = "test_value"
        
        import transaction
        transaction.commit()
        
        print("\n✓ Cache read/write test PASSED")
        
        db.close()
    except Exception as e:
        print(f"\n✗ Cache test FAILED: {e}")
```

Run it:
```bash
python test_cache.py
```

### Test 4: Test Data Source - CME EOD

```python
# test_cme_data.py
import datetime as dt
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

print("Testing CME EOD Data Source...\n")

try:
    # Initialize MDP
    mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")
    print("✓ IRSwapsMDP initialized")
    
    # Get a recent business day
    today = dt.date.today()
    # Go back to find a business day
    test_date = today
    while test_date.weekday() >= 5:  # Skip weekends
        test_date -= dt.timedelta(days=1)
    
    # Test getting a pricer
    request = {
        "curve_name": "USD-SOFR-1D",
        "timestamp": test_date
    }
    
    print(f"✓ Fetching curve for {test_date}...")
    pricer = mdp.get_pricer(request)
    print(f"✓ Pricer obtained")
    
    # Get a par rate
    try:
        rate_5y = pricer.par_rate("5Y")
        print(f"✓ USD-SOFR 5Y rate: {rate_5y:.4f}%")
    except Exception as e:
        print(f"! Could not compute par rate: {e}")
    
    print("\n✓ CME EOD data source test PASSED")
    
except Exception as e:
    print(f"\n✗ CME EOD test FAILED: {e}")
    import traceback
    traceback.print_exc()
```

Run it:
```bash
python test_cme_data.py
```

### Test 5: Complete Query-Driven Backtest

This is the key test - a minimal working backtest:

```python
# test_backtest.py
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

print("=" * 60)
print("Running Minimal Query-Driven Backtest")
print("=" * 60)

try:
    # 1. Build a short time grid (last 5 business days)
    today = dt.date.today()
    dates = []
    current = today
    while len(dates) < 5:
        if current.weekday() < 5:  # Business day
            dates.insert(0, current)
        current -= dt.timedelta(days=1)
    
    grid = TimeGrid(dates)
    print(f"\n✓ Time grid created: {len(dates)} business days")
    
    # 2. Define a simple query
    query = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        value=IRSwapValue.RATE,
        tenor="5Y",
        curve="USD-SOFR-1D",
        structure_kwargs={"bpv": 1_000_000},
    )
    print(f"✓ Query created: 5Y USD-SOFR-1D rate")
    
    # 3. Define a trigger that always fires
    class AlwaysOn(TriggerRequirements):
        def has_triggered(self, state, backtest=None):
            return TriggerInfo(True, info={})
    
    strategy = QueryStrategy(
        name="TestStrategy",
        triggers=[Trigger(AlwaysOn(), actions=[AddQueryAction(query=query)])],
    )
    print(f"✓ Strategy created: AlwaysOn trigger")
    
    # 4. Initialize MDP
    mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")
    print(f"✓ MDP initialized")
    
    # 5. Run backtest
    print(f"\nRunning backtest...\n")
    bt = QueryDrivenBacktest(time_grid=grid, mdp=mdp, strategy=strategy)
    bt.run()
    
    # 6. Inspect results
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    
    print(f"\nMTM History ({len(bt.mtm_history)} entries):")
    for date, mtm in sorted(bt.mtm_history.items()):
        print(f"  {date}: ${mtm:,.2f}")
    
    print(f"\nRealized PNL History ({len(bt.realized_pnl_history)} entries):")
    for date, pnl in sorted(bt.realized_pnl_history.items()):
        print(f"  {date}: ${pnl:,.2f}")
    
    print(f"\nPortfolio ({len(bt.portfolio.positions)} positions):")
    for pos in bt.portfolio.positions:
        print(f"  Opened: {pos.opened_at}, Notional: {pos.source_query.structure_kwargs.get('bpv', 'N/A')}")
    
    print("\n✓ Backtest test PASSED")
    
except Exception as e:
    print(f"\n✗ Backtest test FAILED: {e}")
    import traceback
    traceback.print_exc()
```

Run it:
```bash
python test_backtest.py
```

### Running All Tests at Once

```bash
# Create test_all.sh
cat > test_all.sh << 'EOF'
#!/bin/bash

echo "Running ARBS Verification Tests"
echo "================================"
echo ""

echo "1. Environment Test"
python test_environment.py
echo ""

echo "2. Dependencies Test"
python test_dependencies.py
echo ""

echo "3. Cache Test"
python test_cache.py
echo ""

echo "4. CME Data Test"
python test_cme_data.py
echo ""

echo "5. Backtest Test"
python test_backtest.py
echo ""

echo "All tests complete!"
