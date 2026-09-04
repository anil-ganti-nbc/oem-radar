@echo off
setlocal
rem Rebuilds "OEM Radar Dashboard.exe" from launch_dashboard.py via PyInstaller.
rem Run this after changing dashboard/core code; the .exe is not auto-rebuilt.
cd /d "%~dp0"

set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY ( python --version >nul 2>nul && set "PY=python" )
if not defined PY (
    echo Could not find a working Python. Try:  py --version
    pause & exit /b 1
)

%PY% -c "import PyInstaller" >nul 2>nul || (
    echo Installing PyInstaller...
    %PY% -m pip install --quiet pyinstaller
)

%PY% -m PyInstaller --onefile --console --name "OEM Radar Dashboard" --paths src ^
  --add-data "%~dp0src\oem_radar\providers\sqlite\schema.sql;oem_radar\providers\sqlite" ^
  --add-data "%~dp0config;config" ^
  --distpath dist --workpath build --specpath build launch_dashboard.py

if exist "dist\OEM Radar Dashboard.exe" (
    copy /y "dist\OEM Radar Dashboard.exe" "OEM Radar Dashboard.exe" >nul
    echo.
    echo Built: "OEM Radar Dashboard.exe" (project root)
    rmdir /s /q build 2>nul
    rmdir /s /q dist 2>nul
    del /q "OEM Radar Dashboard.spec" 2>nul
) else (
    echo Build failed — see the PyInstaller output above.
)
pause
