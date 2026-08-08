<#
Registers the "OEM Radar Hourly Crawl" Windows Scheduled Task.

Invoked by install-hourly-task.cmd, not meant to be run standalone (though
it's harmless to -- it just needs the two parameters below). Kept as its
own .ps1 rather than an inline PowerShell one-liner embedded in the .cmd:
building a multi-clause PowerShell command as an escaped string inside a
batch variable turned out to be exactly the kind of cross-shell quoting
problem that caused the bug this script fixes (see the .cmd's own comment
for the root cause). A real .ps1 file with named parameters sidesteps that
entirely -- there is no PowerShell source text for cmd.exe to re-quote.

Uses Register-ScheduledTask with Execute/Argument as separate fields,
never a single combined "program args" string -- that is the actual fix.
schtasks.exe's own /tr interface takes one combined string and, for a
folder path containing a space (this project's does: "oem-radar v 2.0"),
either mis-splits it into the wrong Execute/Arguments or stores literal
quote characters inside Execute, which silently no-ops instead of running
the script. Both failure modes were reproduced and confirmed before this
became the shipped path -- see docs/DATABASE_LIFECYCLE.md's changelog or
docs/CURRENT_STATUS.md for the specific Epoch 2 activation entry.
#>

param(
    [Parameter(Mandatory = $true)][string]$VbsPath,
    [Parameter(Mandatory = $true)][string]$TaskName
)

$ErrorActionPreference = "Stop"

try {
    if (-not (Test-Path -LiteralPath $VbsPath)) {
        Write-Error "crawl-silent.vbs not found at: $VbsPath"
        exit 1
    }

    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$VbsPath`""
    # A one-time trigger with an hourly repetition is the standard
    # PowerShell equivalent of schtasks's "/sc hourly /mo 1". There is no
    # literal "forever" duration for New-ScheduledTaskTrigger --
    # [TimeSpan]::MaxValue serializes to a duration string the Task
    # Scheduler XML schema rejects outright ("out of range"). 10 years is
    # the standard practical stand-in for "indefinitely" here.
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Hours 1) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    # Interactive logon, Limited run level, current user: no stored
    # password, no elevation -- runs only while this user is logged in,
    # same posture the original schtasks-based install had.
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
        -LogonType Interactive -RunLevel Limited

    Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger $trigger -Principal $principal -Force | Out-Null

    Write-Output "SUCCESS: registered scheduled task '$TaskName'"
    exit 0
} catch {
    Write-Error "FAILED to register scheduled task: $_"
    exit 1
}
