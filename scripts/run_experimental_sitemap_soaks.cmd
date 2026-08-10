@echo off
setlocal
cd /d "%~dp0.."
python scripts\lenovo_regional_sitemap_soak.py
python scripts\asus_regional_sitemap_soak.py
