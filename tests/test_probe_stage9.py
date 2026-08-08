"""Stage 9 Phase 2-4: probe's reconnaissance-analyst report — confidence,
evidence, discovery quality score (with itemized deductions), risks,
missing information, and the discovery-simulator triage fields
(fixture count, engineer time, should-pursue verdict). Offline only,
same monkeypatched-session pattern as tests/test_probe_phase4.py."""

from __future__ import annotations

from oem_radar.core.probe import probe_storefront


class _FakeResponse:
    def __init__(self, url, status_code, text, history=None, headers=None):
        self.url = url
        self.status_code = status_code
        self.text = text
        self.history = history or []
        self.headers = headers or {}


class _FakeSession:
    def __init__(self, routes: dict[str, _FakeResponse]):
        self.routes = routes

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        match = max((p for p in self.routes if url.startswith(p)), key=len, default=None)
        if match is None:
            raise AssertionError(f"unexpected URL in fake session: {url}")
        return self.routes[match]


def _base_routes(base: str, homepage_body: str, **overrides) -> dict[str, _FakeResponse]:
    routes = {
        base: _FakeResponse(base, 200, homepage_body),
        f"{base}/products.json": _FakeResponse(f"{base}/products.json", 404, "not found"),
        f"{base}/wp-json/wc/store/v1/products": _FakeResponse(
            f"{base}/wp-json/wc/store/v1/products", 404, "not found"),
        f"{base}/sitemap.xml": _FakeResponse(f"{base}/sitemap.xml", 404, "not found"),
        f"{base}/robots.txt": _FakeResponse(f"{base}/robots.txt", 404, "not found"),
    }
    routes.update(overrides)
    return routes


_RICH_PRODUCT_JSONLD = '''<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Widget X",
 "sku":"WX-1","mpn":"MX1",
 "offers":{"price":"999","priceCurrency":"USD","availability":"InStock"},
 "image":"https://x/wx1.jpg","brand":{"name":"Acme"}}
</script>'''


def test_confidence_high_for_confirmed_bulk_api():
    base = "https://shop.example.com"
    routes = _base_routes(base, "<html>hi</html>")
    routes[f"{base}/products.json?limit=5"] = _FakeResponse(
        f"{base}/products.json?limit=5", 200, '{"products":[{},{},{}]}')
    r = probe_storefront(base, session=_FakeSession(routes))
    assert r.confidence() >= 95
    assert any("products.json" in e for e in r.evidence())


def test_confidence_low_for_root_with_nothing():
    base = "https://mystery.example.com"
    r = probe_storefront(base, session=_FakeSession(_base_routes(base, "<html>nothing</html>")))
    assert r.confidence() <= 20


def test_evidence_lines_trace_to_observed_fields():
    base = "https://cat.example.com"
    r = probe_storefront(base, session=_FakeSession(_base_routes(base, _RICH_PRODUCT_JSONLD)))
    ev = r.evidence()
    assert any("Product JSON-LD" in e for e in ev)
    assert any("HTTP 200" in e for e in ev)
    assert any("no sitemap found" in e for e in ev)


def test_discovery_quality_full_marks_when_nothing_wrong():
    base = "https://shop.example.com"
    routes = _base_routes(base, "<html>hi</html>")
    routes[f"{base}/products.json?limit=5"] = _FakeResponse(
        f"{base}/products.json?limit=5", 200, '{"products":[{}]}')
    routes[f"{base}/sitemap.xml"] = _FakeResponse(f"{base}/sitemap.xml", 200, "<urlset><url>product</url></urlset>")
    r = probe_storefront(base, session=_FakeSession(routes))
    score, deductions = r.discovery_quality()
    assert score == 100
    assert deductions == []


def test_discovery_quality_deducts_for_bot_block():
    base = "https://blocked.example.com"
    routes = _base_routes(base, "Attention Required! Cloudflare")
    r = probe_storefront(base, session=_FakeSession(routes))
    score, deductions = r.discovery_quality()
    assert score <= 50
    cats = [c for c, _, _ in deductions]
    assert "anti_bot" in cats


def test_discovery_quality_deducts_for_no_sitemap_no_api():
    base = "https://sparse.example.com"
    r = probe_storefront(base, session=_FakeSession(_base_routes(base, "<html>nothing here</html>")))
    score, deductions = r.discovery_quality()
    cats = {c for c, _, _ in deductions}
    assert "sitemap" in cats
    assert "data_availability" in cats
    assert score < 100


def test_discovery_quality_deducts_for_partial_jsonld_richness():
    base = "https://partial.example.com"
    html = '<script type="application/ld+json">{"@type":"Product","name":"A"}</script>'
    routes = _base_routes(base, html)
    routes[f"{base}/sitemap.xml"] = _FakeResponse(f"{base}/sitemap.xml", 200, "<urlset><url>product</url></urlset>")
    r = probe_storefront(base, session=_FakeSession(routes))
    score, deductions = r.discovery_quality()
    cats = {c for c, _, _ in deductions}
    assert "jsonld_richness" in cats
    assert score < 100


def test_discovery_quality_deducts_for_js_hydration():
    base = "https://spa.example.com"
    html = '<html><script id="__NEXT_DATA__">{}</script></html>'
    r = probe_storefront(base, session=_FakeSession(_base_routes(base, html)))
    score, deductions = r.discovery_quality()
    cats = {c for c, _, _ in deductions}
    assert "js_hydration" in cats
    assert score < 100


def test_every_deduction_has_a_reason_string():
    base = "https://blocked2.example.com"
    r = probe_storefront(base, session=_FakeSession(_base_routes(base, "Just a moment...")))
    _, deductions = r.discovery_quality()
    assert deductions
    for cat, pts, reason in deductions:
        assert cat and isinstance(pts, int) and pts > 0 and reason


def test_should_pursue_true_for_confirmed_rich_jsonld():
    base = "https://richsite.example.com"
    r = probe_storefront(base, session=_FakeSession(_base_routes(base, _RICH_PRODUCT_JSONLD)))
    pursue, reason = r.should_pursue()
    assert pursue is True
    assert reason


def test_should_pursue_false_when_bot_blocked():
    base = "https://gated.example.com"
    r = probe_storefront(base, session=_FakeSession(_base_routes(base, "Checking your browser before accessing")))
    pursue, reason = r.should_pursue()
    assert pursue is False
    assert "identity-spoofing" in reason


def test_should_pursue_false_for_js_hydrated_no_data():
    base = "https://spa2.example.com"
    html = '<html><script id="__NUXT__">{}</script></html>'
    r = probe_storefront(base, session=_FakeSession(_base_routes(base, html)))
    pursue, reason = r.should_pursue()
    assert pursue is False


def test_recommended_fixture_count_reflects_data_source():
    base = "https://shop2.example.com"
    routes = _base_routes(base, "<html>hi</html>")
    routes[f"{base}/products.json?limit=5"] = _FakeResponse(
        f"{base}/products.json?limit=5", 200, '{"products":[{}]}')
    r = probe_storefront(base, session=_FakeSession(routes))
    assert "bulk listing" in r.recommended_fixture_count()


def test_missing_information_flags_no_sitemap():
    base = "https://nomap.example.com"
    r = probe_storefront(base, session=_FakeSession(_base_routes(base, "<html>nothing</html>")))
    assert any("sitemap" in m.lower() for m in r.missing_information())


def test_known_risks_flags_accessory_filtering_when_data_found():
    base = "https://withdata.example.com"
    r = probe_storefront(base, session=_FakeSession(_base_routes(base, _RICH_PRODUCT_JSONLD)))
    assert any("Accessory" in r_ for r_ in r.known_risks())


def test_to_dict_includes_all_stage9_fields():
    base = "https://full.example.com"
    r = probe_storefront(base, session=_FakeSession(_base_routes(base, _RICH_PRODUCT_JSONLD)))
    d = r.to_dict()
    for key in (
        "confidence", "evidence", "known_risks", "recommended_next_step",
        "discovery_quality_score", "discovery_quality_deductions",
        "missing_information", "recommended_fixture_count",
        "recommended_engineer_time", "should_pursue", "should_pursue_reason",
    ):
        assert key in d, key
