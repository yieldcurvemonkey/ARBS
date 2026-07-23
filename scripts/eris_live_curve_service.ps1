$ErrorActionPreference = 'Continue'
$repo = 'C:\Users\chris\clee\ARBS'
Set-Location $repo

& 'C:\Users\chris\anaconda3\shell\condabin\conda-hook.ps1'
conda activate stir

$env:PYTHONUNBUFFERED = '1'
$env:ARBS_SUPABASE_ENABLED = '1'

$logDir = Join-Path $repo 'logs\eris_live_curve_service'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$outLog = Join-Path $logDir ('wrapper_{0}.log' -f (Get-Date -Format 'yyyyMMdd'))

& python scripts/eris_live_curve_service.py run *> $outLog
exit $LASTEXITCODE
