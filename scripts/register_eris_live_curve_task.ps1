param(
    [string]$TaskName = 'ARBS-ErisLiveCurve-Intraday',
    [switch]$WhatIf
)

$repo = 'C:\Users\chris\clee\ARBS'
$wrapper = Join-Path $repo 'scripts\eris_live_curve_service.ps1'

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $wrapper) `
    -WorkingDirectory $repo

# Continuous (~23/5) daemon: it runs around the clock and self-gates to US
# business days + freshness, so we just need to keep ONE instance alive.
#   - AtStartup / AtLogOn: start on boot / login.
#   - A repeating trigger every 10 min (long duration) is relaunch insurance:
#     with MultipleInstances=IgnoreNew it is a no-op while running, and starts a
#     fresh instance within <=10 min if the process ever died and the fast
#     restart-on-failure window was exhausted.
$startup   = New-ScheduledTaskTrigger -AtStartup
$logon     = New-ScheduledTaskTrigger -AtLogOn
$repeating = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

if ($WhatIf) {
    Write-Host "WhatIf: would register '$TaskName' -> $wrapper (AtStartup + AtLogOn + repeat/10min, continuous)"
    return
}

Register-ScheduledTask -TaskName $TaskName -Action $action `
    -Trigger @($startup, $logon, $repeating) -Settings $settings `
    -Description 'Continuously polls the live ERIS SOFR curve (~23/5 CME hours, business-day gated) and persists per-minute snapshots to Supabase (asset USD-SOFR-1D-ERISLIVE).' `
    -Force
Write-Host "Registered scheduled task '$TaskName' (continuous)."
