# PyInstaller spec for the OEM Radar dashboard launcher.
#
# Entry point is launch_dashboard.py (repo root), which opens the local
# review dashboard (src/oem_radar/dashboard) in the default browser. The
# dashboard is a plain http.server app (ThreadingHTTPServer + hand-rolled
# render.py templates) — there is no FastAPI/uvicorn, no Jinja templates
# directory, and no static/ dir to bundle. The only non-code runtime asset
# it needs is providers/sqlite/schema.sql, used to initialize a fresh
# SQLite DB. This mirrors the --add-data used by build_dashboard_exe.cmd.
#
# Bundles ONLY code + schema — never data/, config/, or .env. The built
# .exe must be run from (or copied next to) a real OEM Radar project root
# so it operates on the operator's live config/radar.yaml and data/ db.
#
# Build (from repo root):
#   pyinstaller "native/windows/OEM Radar.spec" --distpath dist --workpath build --noconfirm

from pathlib import Path

block_cipher = None

# specpath is native/windows/; repo root is two levels up.
ROOT = Path(SPECPATH).resolve().parent.parent

a = Analysis(
    [str(ROOT / 'launch_dashboard.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    datas=[
        (str(ROOT / 'src' / 'oem_radar' / 'providers' / 'sqlite' / 'schema.sql'),
         'oem_radar/providers/sqlite'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='OEM Radar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
