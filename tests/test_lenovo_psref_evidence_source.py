"""Stage 11: the LenovoPsrefEvidenceSource — the first real
EvidenceSource implementation. Real fixture for the happy path (a
trimmed real capture of psref.lenovo.com's ProductCategoryTree, see
tests/fixtures/lenovo_psref/PROVENANCE.md); a hand-written malformed
variant only for parser-robustness checks, per this project's fixture
convention.
"""

from __future__ import annotations

from pathlib import Path

from oem_radar.core.models import EvidenceDocument, EvidenceKind, EvidenceProvenance
from oem_radar.evidence_sources.lenovo_psref import LenovoPsrefConfig, LenovoPsrefEvidenceSource

FIXTURES = Path(__file__).parent / "fixtures" / "lenovo_psref"
REAL_TREE = (FIXTURES / "psref_product_category_tree_trimmed.json").read_text(encoding="utf-8")
BASE = "https://psref.lenovo.com"


class _StaticFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str):
        from oem_radar.core.models import FetchedDocument
        self.calls.append(url)
        body = self.pages.get(url)
        if body is None:
            raise ConnectionError(f"unexpected URL: {url}")
        return FetchedDocument(url=url, status=200, body=body, content_type="application/json")


def _source(**cfg) -> LenovoPsrefEvidenceSource:
    return LenovoPsrefEvidenceSource(LenovoPsrefConfig(**cfg))


# ============================================================================
# discovery: real trimmed PSREF fixture
# ============================================================================

def test_discovery_real_fixture_yields_refs():
    src = _source()
    fetcher = _StaticFetcher({f"{BASE}/api/ph/ProductCategoryTree": REAL_TREE})
    refs = list(src.discover(fetcher))
    assert len(refs) == 5  # 2 real series, first up to 3 products each (one had only 2)
    assert fetcher.calls == [f"{BASE}/api/ph/ProductCategoryTree"]  # one bulk request


def test_discovery_single_request_bulk_inline():
    src = _source()
    fetcher = _StaticFetcher({f"{BASE}/api/ph/ProductCategoryTree": REAL_TREE})
    list(src.discover(fetcher))
    assert len(fetcher.calls) == 1


def test_discovery_refs_carry_inline_payload():
    src = _source()
    fetcher = _StaticFetcher({f"{BASE}/api/ph/ProductCategoryTree": REAL_TREE})
    refs = list(src.discover(fetcher))
    ref = next(r for r in refs if r.external_id == "1523")
    assert ref.inline_payload["ProductName"] == "ThinkPad C13 Yoga Gen 1 Chromebook"
    assert ref.inline_payload["_series"] == "C Series"
    assert ref.inline_payload["_line"] == "ThinkPad"


def test_discovery_malformed_json_yields_nothing():
    src = _source()
    fetcher = _StaticFetcher({f"{BASE}/api/ph/ProductCategoryTree": "not json{{{"})
    refs = list(src.discover(fetcher))
    assert refs == []


def test_discovery_missing_data_key_yields_nothing():
    src = _source()
    fetcher = _StaticFetcher({f"{BASE}/api/ph/ProductCategoryTree": '{"code": 1}'})
    refs = list(src.discover(fetcher))
    assert refs == []


# ============================================================================
# fetch + extract
# ============================================================================

def test_fetch_wraps_inline_payload():
    src = _source()
    fetcher = _StaticFetcher({f"{BASE}/api/ph/ProductCategoryTree": REAL_TREE})
    ref = next(r for r in src.discover(fetcher) if r.external_id == "1523")
    doc = src.fetch(ref, fetcher)
    assert doc.status == 200
    assert "ThinkPad C13" in doc.body


def test_extract_real_product_full_fields():
    src = _source()
    fetcher = _StaticFetcher({f"{BASE}/api/ph/ProductCategoryTree": REAL_TREE})
    ref = next(r for r in src.discover(fetcher) if r.external_id == "1523")
    doc = src.fetch(ref, fetcher)
    items = src.extract(doc)
    assert len(items) == 1
    item = items[0]
    assert item.manufacturer == "Lenovo"
    assert item.source_id == "lenovo-psref"
    assert item.evidence_kind == EvidenceKind.PRODUCT_DATABASE
    assert item.provenance == EvidenceProvenance.OFFICIAL_PRODUCT_DATABASE
    assert item.external_id == "1523"
    assert item.model == "ThinkPad C13 Yoga Gen 1 Chromebook"
    assert item.family == "C Series"
    assert "discontinued" in item.description  # real fixture: Withdraw=1


def test_extract_no_sku_or_mpn_yet_by_design():
    """PSREF's ProductCategoryTree confirmed no MTM/SKU-level field this
    stage (docs/PSREF_RECON.md) — extract() must not invent one."""
    src = _source()
    fetcher = _StaticFetcher({f"{BASE}/api/ph/ProductCategoryTree": REAL_TREE})
    ref = next(r for r in src.discover(fetcher) if r.external_id == "1523")
    doc = src.fetch(ref, fetcher)
    item = src.extract(doc)[0]
    assert item.sku is None
    assert item.mpn is None


def test_extract_withdrawn_excluded_when_configured():
    src = _source(include_withdrawn=False)
    fetcher = _StaticFetcher({f"{BASE}/api/ph/ProductCategoryTree": REAL_TREE})
    ref = next(r for r in src.discover(fetcher) if r.external_id == "1523")
    doc = src.fetch(ref, fetcher)
    assert src.extract(doc) == []  # real fixture: this product has Withdraw=1


def test_extract_withdrawn_included_by_default():
    src = _source()  # include_withdrawn defaults True
    fetcher = _StaticFetcher({f"{BASE}/api/ph/ProductCategoryTree": REAL_TREE})
    ref = next(r for r in src.discover(fetcher) if r.external_id == "1523")
    doc = src.fetch(ref, fetcher)
    assert len(src.extract(doc)) == 1


def test_extract_malformed_document_yields_nothing():
    src = _source()
    doc = EvidenceDocument(url="x", status=200, body="not json")
    assert src.extract(doc) == []


def test_extract_missing_product_key_yields_nothing():
    src = _source()
    doc = EvidenceDocument(url="x", status=200, body='{"ProductID": 1}')
    assert src.extract(doc) == []


def test_config_schema_rejects_nothing_required_all_defaults():
    cfg = LenovoPsrefConfig()
    assert cfg.base_url == "https://psref.lenovo.com"
    assert cfg.include_withdrawn is True
