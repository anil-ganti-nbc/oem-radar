from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_captured_telemetry_identifiers_are_inert() -> None:
    lenovo = (ROOT / "tests/fixtures/lenovo_psref/psref_product_category_tree_trimmed.json").read_text()
    lg = (ROOT / "tests/fixtures/sitemap_jsonld/lg_product_14t90q.html").read_text()
    assert '"ProductKey": "CLANK_FIXTURE_PRODUCT_KEY"' in lenovo
    assert "clientToken: 'CLANK_FIXTURE_RUM_TOKEN'" in lg
    assert 'window.BOOMR_API_key="CLANK_FIXTURE_BOOMR_KEY"' in lg


def test_gitleaks_still_detects_a_credential_shaped_value(tmp_path: Path) -> None:
    scanner = shutil.which("gitleaks")
    if scanner is None:
        pytest.skip("gitleaks is installed only in the security job")
    synthetic_key = "".join(("aB3d", "E7gH1jK5mN9qR2tV6xY8zC4pL7sW"))
    (tmp_path / "credential.txt").write_text(f"api_key={synthetic_key}\n")
    result = subprocess.run(
        [scanner, "dir", "--redact=100", "--no-banner", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
