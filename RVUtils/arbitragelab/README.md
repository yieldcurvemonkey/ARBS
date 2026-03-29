# arbitragelab

Vendored `arbitragelab` package source used inside the ARBS repository.

## Install

From the ARBS repo root:

```powershell
conda run -n stir python -m pip install -e RVUtils\arbitragelab
```

## Test

```powershell
$env:ARBS_SUPABASE_ENABLED="0"
$env:ARBS_CACHE_DIR="$PWD\.cache"
conda run -n stir python -m pytest RVUtils\arbitragelab\tests -q
```

## Docs

- Package index: <https://hudson-and-thames-arbitragelab.readthedocs-hosted.com/en/latest/index.html>
- Hedge ratios: <https://hudson-and-thames-arbitragelab.readthedocs-hosted.com/en/latest/hedge_ratios/hedge_ratios.html>
- Bollinger bands trading: <https://hudson-and-thames-arbitragelab.readthedocs-hosted.com/en/latest/trading/z_score.html>
