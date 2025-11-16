# ARBS Analysis Scripts

## Phase 1: Correlation Structure Analysis

### Quick Start

```bash
# Install dependencies (if not already installed)
pip install numpy pandas matplotlib seaborn

# Run analysis with synthetic data
python scripts/analyze_correlation_structure.py
```

### Using Real Data

Edit `analyze_correlation_structure.py` line 376:

```python
# Change from:
provider = SyntheticFuturesProvider(...)

# To:
provider = RealFuturesProvider(
    data_path="path/to/your/futures_prices.csv",
    file_format="csv"  # or "parquet" or "wide"
)
```

### Expected Data Format

**Option 1: Long Format CSV**
```csv
date,contract,price
2023-01-03,USD_3M,99.150
2023-01-03,USD_6M,98.920
2023-01-03,EUR_3M,97.450
...
```

**Option 2: Wide Format CSV**
```csv
date,USD_3M,USD_6M,EUR_3M,EUR_6M,GBP_3M,...
2023-01-03,99.150,98.920,97.450,97.220,98.100,...
2023-01-04,99.148,98.918,97.448,97.218,98.098,...
...
```

**Option 3: Parquet** (same structure as CSV, but .parquet format)

### Output Files

After running, you'll get:

1. **docs/research/arbs_correlation_structure.md** - Text report with findings
2. **docs/research/correlation_heatmap.png** - Correlation matrix heatmap
3. **docs/research/correlation_distribution.png** - Within vs cross-currency histogram

### ETL Architecture

```
FuturesDataProvider (abstract)
├── SyntheticFuturesProvider (testing)
└── RealFuturesProvider (production)

Both return standardized format:
- DataFrame with DatetimeIndex
- Columns: "{currency}_{maturity}" (e.g., "USD_3M", "EUR_1Y")
- Values: Returns (decimal)
```

**Swap data sources** by changing one line - no other code changes needed.

### Dependencies

```bash
pip install polars numpy matplotlib seaborn
```

- Python 3.8+
- **polars** (high-performance DataFrames)
- numpy (for correlation calculations)
- matplotlib (for visualizations)
- seaborn (for heatmaps)

---

## Research Paper Integration

### download_research_pdfs.sh

Downloads 16 research papers from arXiv for the portfolio management research library.

**Usage**:
```bash
./scripts/download_research_pdfs.sh
```

**Papers downloaded**:
- Ledoit-Wolf covariance estimators (4 papers)
- Advanced portfolio optimization methods (5 papers)
- Multi-asset risk models (4 papers)
- Performance analysis techniques (3 papers)

Papers are saved to `docs/references/papers/` directory.

**Dependencies**:
- `curl` or `wget`
- Internet connection

### convert_grinold_kahn_to_markdown.py

Converts Grinold-Kahn PDF to structured markdown for easier reference.

**Dependencies**:
- PyMuPDF (`pip install PyMuPDF`)

**Usage**:
```bash
python scripts/convert_grinold_kahn_to_markdown.py
```

**Input**: PDF file in `docs/books/` directory
**Output**: `docs/references/Grinold-Kahn-Active-Portfolio-Management.md`

**Features**:
- Extracts text with formatting preserved
- Creates section headers
- Maintains table structures
- Adds navigation links

