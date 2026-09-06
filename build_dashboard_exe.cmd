@echo off
setlocal
rem Rebuilds "OEM Radar Dashboard.exe" from launch_dashboard.py via PyInstaller.
rem Run this after changing dashboard/core code; the .exe is not auto-rebuilt.
rem
rem Every literal parenthesis in an echo below is caret-escaped on purpose.
rem An unescaped closing paren inside an if-block terminates that block where
rem it appears, so the lines after it run unconditionally and the trailing
rem else arm becomes a syntax error -- which is why this script used to leave
rem its build and dist directories behind on a successful build.
cd /d "%~dp0"

rem Prefer the repo's own virtualenv. A system interpreter can resolve a
rem different oem_radar (or none), so the bundle it freezes need not be the
rem code in this checkout -- which is the whole failure this script exists
rem to avoid.
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set PY="%~dp0.venv\Scripts\python.exe"
if not defined PY ( py -3 --version >nul 2>nul && set "PY=py -3" )
if not defined PY ( python --version >nul 2>nul && set "PY=python" )
if not defined PY (
    echo Could not find a working Python. Try:  py --version
    pause & exit /b 1
)

%PY% -c "import PyInstaller" >nul 2>nul || (
    echo Installing PyInstaller...
    %PY% -m pip install --quiet pyinstaller
)

rem --clean discards PyInstaller's cached Analysis. Without it a rebuild can
rem reuse the previous graph and silently reship stale code -- exactly how a
rem frozen dashboard kept serving a superseded build after its source changed.
%PY% -m PyInstaller --clean --noconfirm --onefile --console --name "OEM Radar Dashboard" --paths src ^
  --add-data "%~dp0src\oem_radar\providers\sqlite\schema.sql;oem_radar\providers\sqlite" ^
  --add-data "%~dp0config;config" ^
  --distpath dist --workpath build --specpath build launch_dashboard.py

if exist "dist\OEM Radar Dashboard.exe" (
    copy /y "dist\OEM Radar Dashboard.exe" "OEM Radar Dashboard.exe" >nul
    echo.
    echo Built: "OEM Radar Dashboard.exe" ^(project root^)
    rmdir /s /q build 2>nul
    rmdir /s /q dist 2>nul
    del /q "OEM Radar Dashboard.spec" 2>nul
) else (
    echo Build failed — see the PyInstaller output above.
)
pause
