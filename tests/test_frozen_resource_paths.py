"""Frozen vs source resource resolution for the packaged dashboard.

A --onefile PyInstaller build does not put --add-data content next to the
executable: it extracts it to a temp directory exposed as sys._MEIPASS.
launch_dashboard.py previously used the exe's own directory for both the
bundled config and the persistent data root, so a frozen dashboard died
with FileNotFoundError on "<exe dir>/config/radar.yaml".
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The module chdir()s and imports the world at import time, so probe it in a
# child process with the frozen attributes faked, and only read back the two
# roots it computed.
PROBE = textwrap.dedent(
    """
    import sys, types, runpy, json
    from pathlib import Path
    sys.frozen = {frozen!r}
    if {frozen!r}:
        sys.executable = {exe!r}
        sys._MEIPASS = {meipass!r}
    src = Path({repo!r}) / "launch_dashboard.py"
    code = src.read_text(encoding="utf-8")
    # Stop before main() runs: we only want the module-level path decisions.
    head = code.split("def main(")[0]
    ns = {{"__file__": str(src)}}
    exec(compile(head, str(src), "exec"), ns)
    print(json.dumps({{"root": str(ns["ROOT"]), "config": str(ns["CONFIG_DIR"])}}))
    """
)


def _probe(frozen, exe=None, meipass=None):
    code = PROBE.format(frozen=frozen, exe=exe, meipass=meipass, repo=str(REPO))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    import json
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_source_execution_resolves_config_from_the_checkout():
    got = _probe(False)
    assert Path(got["config"]) == REPO / "config"
    assert (Path(got["config"]) / "radar.yaml").exists()
    assert Path(got["root"]) == REPO


def test_frozen_reads_bundled_config_from_meipass_not_beside_the_exe(tmp_path):
    """The regression: config must come out of the bundle."""
    exe_dir = tmp_path / "dist"
    exe_dir.mkdir()
    meipass = tmp_path / "_MEI12345"
    (meipass / "config").mkdir(parents=True)
    (meipass / "config" / "radar.yaml").write_text("store: sqlite\n", encoding="utf-8")

    got = _probe(True, exe=str(exe_dir / "OEM Radar.exe"), meipass=str(meipass))

    # Config resolves into the bundle, NOT the (config-less) exe directory.
    assert Path(got["config"]) == meipass / "config"
    assert Path(got["config"]) != exe_dir / "config"
    # The persistent data root stays real storage — never the temp bundle,
    # which PyInstaller deletes on exit.
    assert Path(got["root"]) == exe_dir
    assert Path(got["root"]) != meipass


def test_a_real_config_beside_the_exe_overrides_the_bundled_copy(tmp_path):
    exe_dir = tmp_path / "app"
    (exe_dir / "config").mkdir(parents=True)
    (exe_dir / "config" / "radar.yaml").write_text("store: sqlite\n", encoding="utf-8")
    meipass = tmp_path / "_MEI999"
    (meipass / "config").mkdir(parents=True)
    (meipass / "config" / "radar.yaml").write_text("store: sqlite\n", encoding="utf-8")

    got = _probe(True, exe=str(exe_dir / "OEM Radar.exe"), meipass=str(meipass))
    assert Path(got["config"]) == exe_dir / "config"


def test_build_script_actually_bundles_the_config_directory():
    """Resolution is useless if the build never ships config/."""
    script = (REPO / "build_dashboard_exe.cmd").read_text(encoding="utf-8")
    assert "--add-data" in script
    assert "config;config" in script.replace('"', "")


def test_launcher_never_hands_serve_a_crawl_controller():
    """COM-001 / Phase 0: `serve` rejects crawl controllers outright, so the
    frozen entry point must not build one. It used to, which made every
    packaged launch die with "Phase 0 dashboard is read-only" the moment it
    got past config loading."""
    from oem_radar.cli import build_dashboard_crawl_kwargs
    from oem_radar.core.config import load_radar_config

    radar = load_radar_config(REPO / "config" / "radar.yaml")
    kwargs = build_dashboard_crawl_kwargs(radar, REPO / "config")
    assert kwargs["crawl"] is None
    assert kwargs["auto_crawl"] is False
    assert kwargs["auto_crawl_force"] is False

    # The launcher must defer to that authority, not re-decide it locally.
    # Ignore comments: only real code counts.
    src = (REPO / "launch_dashboard.py").read_text(encoding="utf-8")
    code = chr(10).join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "build_dashboard_crawl_kwargs" in code
    assert "CrawlController" not in code
    assert "crawl_service" not in code
