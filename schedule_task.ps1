# Sets up (or removes) the Windows scheduled task that checks stock every 3 hours
# and pushes the results to GitHub.
#
#   powershell -ExecutionPolicy Bypass -File schedule_task.ps1           # install / update
#   powershell -ExecutionPolicy Bypass -File schedule_task.ps1 -Remove   # remove
#
# The task runs while you are logged in, hidden (pythonw), and catches up on a missed
# check as soon as the PC wakes. Output goes to logs\tracker.log.
param([switch]$Remove)

$name = "Carrot juice tracker"
if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Output "Removed scheduled task '$name'."
    return
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    Write-Error "Run run_local.bat once first to set up .venv"
    exit 1
}

$now = Get-Date
$start = $now.Date.AddHours($now.Hour + 1).AddMinutes(17)   # next hh:17
$action = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "-m tracker --publish --log logs\tracker.log" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Hours 3)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Description "Checks carrot juice stock at Walmart and IGA Saint-Hyacinthe and pushes the results to GitHub Pages." `
    -Force | Out-Null
Write-Output "Scheduled '$name' every 3 hours, first run $($start.ToString('yyyy-MM-dd HH:mm'))."
