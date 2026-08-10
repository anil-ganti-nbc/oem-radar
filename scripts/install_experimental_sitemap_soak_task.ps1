param([switch]$Install)

# Deliberately opt-in.  This never touches the production hourly task; its
# scripts use only data/experimental/*.db and contain no notifier path.
if (-not $Install) {
    Write-Host "Dry run only. Re-run with -Install to create OEM Radar Experimental Sitemap Soak (every 6 hours)."
    exit 0
}
$root = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$root\scripts\run_experimental_sitemap_soaks.cmd`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(5)
$trigger.Repetition.Interval = 'PT6H'
$trigger.Repetition.Duration = 'P1D'
Register-ScheduledTask -TaskName "OEM Radar Experimental Sitemap Soak" -Action $action -Trigger $trigger -Description "Isolated Lenovo/ASUS sitemap experiments; no product DB or Discord" -Force | Out-Null
Write-Host "Installed OEM Radar Experimental Sitemap Soak. Disable with: Disable-ScheduledTask -TaskName 'OEM Radar Experimental Sitemap Soak'"
