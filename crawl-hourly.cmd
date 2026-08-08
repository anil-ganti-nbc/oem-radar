@echo off
setlocal
rem Headless hourly crawl — invoked by Task Scheduler (or run manually to test).
rem No dashboard, no lingering window. Appends a line to data\crawl-runs.log.
cd /d "%~dp0"
set PYTHONPATH=src

rem Reuse start-radar's Python detection by finding a working interpreter.
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY ( python --version >nul 2>nul && set "PY=python" )
if not defined PY ( python3 --version >nul 2>nul && set "PY=python3" )
if not defined PY ( echo [%date% %time%] ERROR: no Python found >> "%~dp0data\crawl-runs.log" & exit /b 1 )

rem Unattended scheduled run: fail clearly if the environment is broken
rem instead of silently mutating dependencies in the background.
%PY% -c "import pydantic, yaml, requests" >nul 2>nul || (
    echo [%date% %time%] ERROR: missing dependencies (pydantic/PyYAML/requests^) - run "%PY% -m pip install -e .[dev]" manually, then retry >> "%~dp0data\crawl-runs.log"
    exit /b 1
)

rem Webhook: prefer env var, else the file-based one start-radar uses. The CLI
rem already reads config\discord_webhook.txt, so nothing to set here.
echo [%date% %time%] crawl start >> "%~dp0data\crawl-runs.log"
%PY% -m oem_radar.cli run >> "%~dp0data\crawl-runs.log" 2>&1
echo [%date% %time%] crawl done (exit %errorlevel%) >> "%~dp0data\crawl-runs.log"
