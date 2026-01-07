# ARBS Installation & Setup Guide - Document Index

Complete documentation for installing and setting up ARBS (Awesome Rates Backtesting System).

## Quick Navigation

### For First-Time Users
1. Start with **[QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)** (5 minutes)
2. Follow **[SETUP_CHECKLIST.md](SETUP_CHECKLIST.md)** to verify installation
3. Refer to **[INSTALLATION_AND_SETUP_GUIDE.md](INSTALLATION_AND_SETUP_GUIDE.md)** for detailed information

### For Developers
1. Complete [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)
2. Install development tools from [INSTALLATION_AND_SETUP_GUIDE.md](INSTALLATION_AND_SETUP_GUIDE.md#3-dependency-installation-and-troubleshooting)
3. Reference [Development vs. Production Deployment](INSTALLATION_AND_SETUP_GUIDE.md#10-development-vs-production-deployment)

### For Production Deployment
1. Read [Production Deployment Section](INSTALLATION_AND_SETUP_GUIDE.md#production-environment)
2. Use `requirements-prod.txt` instead of `requirements.txt`
3. Deploy using Docker: [Dockerfile.example](Dockerfile.example)
4. Or use systemd: [arbs-backtest.service.example](arbs-backtest.service.example)

---

## Document Directory

### Main Installation Guide
| Document | Purpose | Time | Audience |
|----------|---------|------|----------|
| **[QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)** | Get running in 5 minutes | 5 min | Everyone |
| **[INSTALLATION_AND_SETUP_GUIDE.md](INSTALLATION_AND_SETUP_GUIDE.md)** | Comprehensive reference | 30 min | Everyone |
| **[SETUP_CHECKLIST.md](SETUP_CHECKLIST.md)** | Verify installation completeness | 15 min | Everyone |

### Configuration Templates
| File | Purpose | Usage |
|------|---------|-------|
| **[.env.example](.env.example)** | Environment variables template | Copy to `.env` and customize |
| **[config/settings.example.yaml](config/settings.example.yaml)** | Configuration file template | Copy to `config/settings.yaml` |

### Dependency Files
| File | Purpose | When to Use |
|------|---------|------------|
| **[requirements.txt](requirements.txt)** | Base dependencies | Standard installation |
| **[requirements-prod.txt](requirements-prod.txt)** | Production dependencies | Production deployment |
| **[requirements-dev.txt](requirements-dev.txt)** | Development tools | Contributing to ARBS |
| **[requirements-ci.txt](requirements-ci.txt)** | CI/CD testing dependencies | GitHub Actions, etc. |

### Deployment Configuration
| File | Purpose | Scenario |
|------|---------|----------|
| **[Dockerfile.example](Dockerfile.example)** | Docker container definition | Container deployment |
| **[docker-compose.example.yml](docker-compose.example.yml)** | Docker Compose orchestration | Local/staging deployment |
| **[arbs-backtest.service.example](arbs-backtest.service.example)** | Systemd service unit | Linux daemon |
| **[arbs-backtest.timer.example](arbs-backtest.timer.example)** | Systemd timer | Scheduled execution |

---

## Installation Methods Comparison

| Method | Time | Skill | Best For |
|--------|------|-------|----------|
| pip (Local) | 5 min | Beginner | Single machine, development |
| Conda (Local) | 10 min | Beginner | macOS/Windows, data scientists |
| Docker | 10 min | Intermediate | Reproducible environments |
| K8s | 30 min | Advanced | Production clusters |

---

## Key Sections by Topic

### 1. System Requirements
- **[System Requirements](INSTALLATION_AND_SETUP_GUIDE.md#1-system-requirements)**: Hardware, Python, OS, external dependencies
- **Minimum**: Python 3.13, 4GB RAM, 5GB disk
- **Recommended**: Python 3.13, 16GB RAM, 50GB disk

### 2. Installation Methods
- **[pip (User)](INSTALLATION_AND_SETUP_GUIDE.md#method-1-using-pip-recommended-for-users)**
- **[Conda (Data Scientist)](INSTALLATION_AND_SETUP_GUIDE.md#method-2-using-conda-recommended-for-data-scientists)**
- **[Development Editable](INSTALLATION_AND_SETUP_GUIDE.md#method-3-development-installation-for-contributors)**
- **[From Source](INSTALLATION_AND_SETUP_GUIDE.md#method-4-installation-from-source-with-specific-version)**

### 3. Dependency Troubleshooting
- **[QuantLib Issues](INSTALLATION_AND_SETUP_GUIDE.md#quantlib-installation-challenges)**
- **[ZODB Issues](INSTALLATION_AND_SETUP_GUIDE.md#zodb-installation-issues)**
- **[Import Errors](INSTALLATION_AND_SETUP_GUIDE.md#import-errors-for-arbs-modules)**
- **[Proxy Setup](INSTALLATION_AND_SETUP_GUIDE.md#issue-4-behind-corporate-proxy)**
- **[Missing System Dependencies](INSTALLATION_AND_SETUP_GUIDE.md#issue-5-missing-system-dependencies)**

### 4. Data Sources Configuration
- **[CME EOD Data](INSTALLATION_AND_SETUP_GUIDE.md#a-cme-end-of-day-cme_ny_eod_live)**
- **[SDR Intraday Data](INSTALLATION_AND_SETUP_GUIDE.md#b-sdr-intraday-sdr_intraday-rl)**
- **[API Keys](INSTALLATION_AND_SETUP_GUIDE.md#api-keys-and-external-services)**
- **[FRED Setup](INSTALLATION_AND_SETUP_GUIDE.md#federal-reserve-economic-data-fred)**

### 5. ZODB Cache Setup
- **[Basic Configuration](INSTALLATION_AND_SETUP_GUIDE.md#basic-zodb-cache-configuration)**
- **[Advanced Configuration](INSTALLATION_AND_SETUP_GUIDE.md#advanced-zodb-configuration)**
- **[Timeseries Cache](INSTALLATION_AND_SETUP_GUIDE.md#timeseries-cache-configuration)**
- **[Maintenance](INSTALLATION_AND_SETUP_GUIDE.md#cache-maintenance)**
- **[Troubleshooting](INSTALLATION_AND_SETUP_GUIDE.md#cache-troubleshooting)**

### 6. Environment Configuration
- **[.env Variables](INSTALLATION_AND_SETUP_GUIDE.md#required-environment-variables)**
- **[Config Files](INSTALLATION_AND_SETUP_GUIDE.md#configuration-file-configsettingsyaml)**
- **[Logging Setup](INSTALLATION_AND_SETUP_GUIDE.md#logging-configuration)**

### 7. First-Time Setup
- **[Installation Checklist](INSTALLATION_AND_SETUP_GUIDE.md#installation-phase)**
- **[Configuration Checklist](INSTALLATION_AND_SETUP_GUIDE.md#configuration-phase)**
- **[Verification Checklist](INSTALLATION_AND_SETUP_GUIDE.md#verification-phase)**

### 8. Verification & Testing
- **[Test 1: Environment](INSTALLATION_AND_SETUP_GUIDE.md#test-1-verify-python-environment)**
- **[Test 2: Dependencies](INSTALLATION_AND_SETUP_GUIDE.md#test-2-verify-core-dependencies)**
- **[Test 3: Cache](INSTALLATION_AND_SETUP_GUIDE.md#test-3-test-cache-initialization)**
- **[Test 4: Data Source](INSTALLATION_AND_SETUP_GUIDE.md#test-4-test-data-source---cme-eod)**
- **[Test 5: Complete Backtest](INSTALLATION_AND_SETUP_GUIDE.md#test-5-complete-query-driven-backtest)**

### 9. Troubleshooting
- **[QuantLib](INSTALLATION_AND_SETUP_GUIDE.md#issue-1-quantlib-installation-fails)**
- **[ZODB Lock](INSTALLATION_AND_SETUP_GUIDE.md#issue-2-zodb-lock-error)**
- **[Import Errors](INSTALLATION_AND_SETUP_GUIDE.md#issue-3-import-errors-for-arbs-modules)**
- **[Proxy Issues](INSTALLATION_AND_SETUP_GUIDE.md#issue-4-behind-corporate-proxy)**
- **[System Dependencies](INSTALLATION_AND_SETUP_GUIDE.md#issue-5-missing-system-dependencies)**
- **[Data Source Failures](INSTALLATION_AND_SETUP_GUIDE.md#issue-6-data-source-failures-cme)**
- **[Memory Issues](INSTALLATION_AND_SETUP_GUIDE.md#issue-7-memory-issues-large-backtests)**
- **[Version Conflicts](INSTALLATION_AND_SETUP_GUIDE.md#issue-8-dependency-version-conflicts)**

### 10. Deployment
- **[Development Setup](INSTALLATION_AND_SETUP_GUIDE.md#development-environment)**
- **[Production Setup](INSTALLATION_AND_SETUP_GUIDE.md#production-environment)**
- **[Systemd Service](INSTALLATION_AND_SETUP_GUIDE.md#systemd-service-linux)**
- **[Docker Deployment](INSTALLATION_AND_SETUP_GUIDE.md#docker-deployment)**
- **[Kubernetes Deployment](INSTALLATION_AND_SETUP_GUIDE.md#k8s-deployment)**
- **[Monitoring & Alerting](INSTALLATION_AND_SETUP_GUIDE.md#monitoring-and-alerting)**
- **[Performance Tuning](INSTALLATION_AND_SETUP_GUIDE.md#performance-tuning-for-production)**

---

## Quick Reference Tables

### Hardware Recommendations by Use Case

| Use Case | CPU | RAM | Disk | Notes |
|----------|-----|-----|------|-------|
| **Development** | 2+ | 4GB | 10GB | Local testing |
| **Research** | 4+ | 8-16GB | 50GB | Multiple backtests |
| **Production** | 8+ | 16-32GB | 100GB+ | Heavy workloads |

### Installation Time Estimates

| Step | Time | Notes |
|------|------|-------|
| System prep | 5 min | Check Python, git, internet |
| Environment setup | 2 min | Create venv |
| Clone & install | 10 min | Depends on network speed |
| Configuration | 5 min | .env, settings files |
| Verification | 10 min | Run tests |
| **Total** | **~30 min** | First-time setup |

### File Sizes

| Component | Size | Notes |
|-----------|------|-------|
| Python packages | ~1.5GB | numpy, pandas, QuantLib, ZODB, etc. |
| ARBS source | ~50MB | Python code |
| Cache (empty) | ~1MB | Grows with usage |
| Default cache (30 days) | ~500MB | CME EOD data |
| Full cache (1 year) | ~5GB | All historical data |

---

## Common Commands Reference

### Setup
```bash
python3.13 -m venv arbs_env
source arbs_env/bin/activate
pip install -r requirements.txt
```

### Verification
```bash
python test_environment.py
python test_dependencies.py
python test_backtest.py
```

### Configuration
```bash
cp .env.example .env
# Edit .env with your settings
export $(cat .env | xargs)
```

### Docker
```bash
docker build -f Dockerfile.example -t arbs:latest .
docker run -v /mnt/cache:/mnt/arbs_cache arbs:latest
```

### Systemd
```bash
sudo cp arbs-backtest.service.example /etc/systemd/system/arbs-backtest.service
sudo systemctl daemon-reload
sudo systemctl enable arbs-backtest
sudo systemctl start arbs-backtest
```

---

## Related Documentation

- **[Main README.md](README.md)**: Project overview and architecture
- **[Module Docs](docs/)**: Detailed module documentation
- **[Example Notebook](month_end_irswaps_backtest.ipynb)**: Practical backtest example

---

## Support & Help

| Issue | Resource |
|-------|----------|
| Installation questions | [INSTALLATION_AND_SETUP_GUIDE.md](INSTALLATION_AND_SETUP_GUIDE.md) |
| Specific errors | [Troubleshooting section](INSTALLATION_AND_SETUP_GUIDE.md#9-common-installation-issues-and-solutions) |
| Quick answers | [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md) |
| Verify setup | [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) |
| Architecture | [README.md](README.md) |
| API Reference | [docs/](docs/) folder |

---

## Document Maintenance

| Document | Last Updated | Maintainer |
|----------|--------------|-----------|
| QUICK_START_GUIDE.md | 2025-11-10 | ARBS Team |
| INSTALLATION_AND_SETUP_GUIDE.md | 2025-11-10 | ARBS Team |
| SETUP_CHECKLIST.md | 2025-11-10 | ARBS Team |
| .env.example | 2025-11-10 | ARBS Team |
| requirements-*.txt | 2025-11-10 | ARBS Team |
| Docker files | 2025-11-10 | ARBS Team |
| Systemd files | 2025-11-10 | ARBS Team |

---

**Version**: 1.0  
**Status**: Complete  
**Python**: 3.13.x  
**Last Updated**: 2025-11-10

