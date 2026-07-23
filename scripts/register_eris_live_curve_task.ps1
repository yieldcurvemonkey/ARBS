param(
    [string]$TaskName = 'ARBS-ErisLiveCurve-Intraday',
    [switch]$WhatIf
)

$repo = 'C:\Users\chris\clee\ARBS'
$wrapper = Join-Path $repo 'scripts\eris_live_curve_service.ps1'

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $wrapper) `
    -WorkingDirectory $repo

# Two triggers: daily just before the session, and at startup (reboot recovery).
$daily   = New-ScheduledTaskTrigger -Daily -At 6:55am
$startup = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 18) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

if ($WhatIf) {
    Write-Host "WhatIf: would register '$TaskName' -> $wrapper (Daily 06:55 + AtStartup)"
    return
}

Register-ScheduledTask -TaskName $TaskName -Action $action `
    -Trigger @($daily, $startup) -Settings $settings `
    -Description 'Polls live ERIS SOFR curve every minute during the US session and persists snapshots to Supabase.' `
    -Force
Write-Host "Registered scheduled task '$TaskName'."
