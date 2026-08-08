@echo off
setlocal
rem One-time setup: registers a Windows Scheduled Task that runs the crawler
rem silently every hour. Run this ONCE (double-click is fine).
cd /d "%~dp0"
set TASK=OEM Radar Hourly Crawl

rem Registration itself lives in install-hourly-task.ps1 (Register-
rem ScheduledTask, Execute/Argument as separate fields) rather than
rem schtasks.exe's "/tr <one combined string>" here. Root cause:
rem this project's folder name has a space in it ("oem-radar v 2.0"),
rem and every way of quoting that space for schtasks's /tr either got
rem the value mis-split into the wrong Execute/Arguments (Task Scheduler
rem then tries to run "...\oem-radar" as the program) or stored literal
rem quote characters inside Execute, which silently no-ops instead of
rem running the script -- schtasks reports success either way, so this
rem was only visible by inspecting the registered Action afterward.
rem Verified end-to-end (a probe script's real side effect observed after
rem a manual trigger) before this became the shipped path.
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass ^
    -File "%~dp0install-hourly-task.ps1" ^
    -VbsPath "%~dp0crawl-silent.vbs" -TaskName "%TASK%"

if %errorlevel%==0 (
    echo.
    echo Installed. The crawler now runs silently every hour.
    echo   - See results anytime:   dashboard.cmd  ^(or: oem-radar dashboard^)
    echo   - Watch the run log:     data\crawl-runs.log
    echo   - Run one now to test:   schtasks /run /tn "%TASK%"
    echo   - Remove it later:       uninstall-hourly-task.cmd
) else (
    echo.
    echo Install failed. Try running this file as Administrator
    echo   ^(right-click ^> Run as administrator^), or see the README.
)
echo.
pause
