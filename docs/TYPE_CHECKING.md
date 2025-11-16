# Type Checking with MyPy

## Current State
- MyPy configured in lenient mode (`mypy.ini`)
- Focus: Catch obvious type mismatches (pandas vs polars)
- Pre-commit hook runs only on modified files

## Running MyPy

### Check specific file
```bash
mypy path/to/file.py
```

### Check entire module
```bash
mypy Risk/
```

### Check everything
```bash
mypy .
```

## Common Type Hints

### Polars DataFrames
```python
import polars as pl

def process(data: pl.DataFrame) -> pl.DataFrame:
    ...
```

### Numpy Arrays
```python
import numpy as np
from typing import Optional

def calculate(data: np.ndarray) -> Optional[np.ndarray]:
    ...
```

### Signal Types
```python
from typing import Dict, List
from Signals.Base.BaseSignal import BaseSignal

def combine_signals(
    signals: List[BaseSignal],
    weights: Dict[str, float]
) -> Dict[str, float]:
    ...
```

## Ignoring Specific Lines
If MyPy reports false positive:
```python
result = complex_operation()  # type: ignore[error-code]
```

## Roadmap
1. ✅ Setup mypy with lenient config
2. 🔄 Fix critical type mismatches in core modules
3. ⏳ Gradually increase strictness (`disallow_untyped_defs = True`)
4. ⏳ Add type stubs for third-party libraries
