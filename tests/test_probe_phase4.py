"""Stage 7 Phase 4: probe reconnaissance-assistant upgrades — framework
detection, GraphQL/Magento/Adobe Commerce/Salesforce Commerce hints,
sitemap compression, JSON-LD richness scoring, and the derived
recommendation/effort-estimate fields. Offline only (no network), using
the same monkeypatched-session pattern as tests/test_probe.py."""

from __future__ import annotations

from oem_radar.core.probe import _jsonld_richness_score, probe_storefront


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


def _base_routes(base: str, homepage_body: str) -> dict[str, _FakeResponse]:
    return {
        base: _FakeResponse(base, 200, homepage_body),
        f"{base}/products.json": _FakeResponse(f"{base}/products.json", 404, "not found"),
        f"{base}/wp-json/wc/store/v1/products": _FakeResponse(
            f"{base}/wp-json/wc/store/v1/products", 404, "not found"),
        f"{base}/sitemap.xml": _FakeResponse(f"{base}/sitemap.xml", 404, "not found"),
        f"{base}/robots.txt": _FakeResponse(f"{base}/robots.txt", 404, "not found"),
    }


# ---- JSON-LD richness score --------------------------------------------------

def test_richness_full_product_scores_100():
    html = '''<script type="application/ld+json">
    {"@type":"Product","name":"A","sku":"S1","mpn":"M1",
     "offers":{"price":"10"},"image":"a.jpg","brand":{"name":"X"}}
    </script>'''
    assert _jsonld_richness_score(html) == 100


def test_richness_name_only_scores_low():
    html = '<script type="application/ld+json">{"@type":"Product","name":"A"}</script>'
    score = _jsonld_richness_score(html)
    assert 0 < score < 30


def test_richness_no_product_nodes_scores_zero():
    assert _jsonld_richness_score("<html>nothing here</html>") == 0


def test_richness_averages_across_multiple_nodes():
    html = '''<script type="application/ld+json">
    [{"@type":"Product","name":"A","sku":"S1","mpn":"M1","offers":{"p":1},"image":"a","brand":"B"},
     {"@type":"Product","name":"B"}]
    </script>'''
    score = _jsonld_richness_score(html)
    assert 0 < score < 100  # full node + name-only node averaged


# ---- framework detection ------------------------------------------------------

def test_detects_nextjs():
    base = "https://ex.com"
    routes = _base_routes(base, '<script>window.__NEXT_DATA__={}</script>')
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.framework == "Next.js"


def test_detects_nuxt():
    base = "https://ex2.com"
    routes = _base_routes(base, '<script>window.__NUXT__=(function(){})()</script>')
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.framework == "Nuxt"


def test_no_framework_detected_on_plain_html():
    base = "https://ex3.com"
    routes = _base_routes(base, "<html><body>plain page</body></html>")
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.framework is None


# ---- platform hints ------------------------------------------------------------

def test_detects_graphql_hint():
    base = "https://ex4.com"
    routes = _base_routes(base, '<script src="/api/graphql.js"></script>')
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.graphql_hint is True


def test_detects_magento_hint():
    base = "https://ex5.com"
    routes = _base_routes(base, '<script src="/static/version1234/requirejs-config.js"></script>')
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.magento_hint is True
    assert result.platform_guess() == "magento/adobe_commerce"


def test_detects_salesforce_commerce_hint():
    base = "https://ex6.com"
    routes = _base_routes(base, '<html>powered by demandware</html>')
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.salesforce_commerce_hint is True
    assert result.platform_guess() == "salesforce_commerce"


def test_platform_guess_shows_js_hydrated_when_framework_but_no_jsonld():
    base = "https://ex7.com"
    routes = _base_routes(base, '<script>window.__NEXT_DATA__={}</script>')
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.platform_guess() == "js_hydrated (Next.js)"


# ---- derived recommendation / effort fields -----------------------------------

def test_recommendation_shopify():
    base = "https://ex8.com"
    routes = _base_routes(base, "<html>store</html>")
    routes[f"{base}/products.json"] = _FakeResponse(
        f"{base}/products.json", 200, '{"products":[{"id":1}]}')
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.collector_recommendation() == "shopify"
    assert result.estimated_implementation_effort() == "Low"


def test_recommendation_sitemap_jsonld_when_rich_enough():
    base = "https://ex9.com"
    html = '''<script type="application/ld+json">
    {"@type":"Product","name":"A","sku":"S1","offers":{"price":"10"},"image":"a.jpg"}
    </script>'''
    routes = _base_routes(base, html)
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.collector_recommendation() == "sitemap_jsonld"
    assert result.estimated_implementation_effort() == "Low"


def test_recommendation_blocked_bot():
    base = "https://ex10.com"
    routes = _base_routes(base, "checking your browser before accessing")
    routes[base] = _FakeResponse(base, 403, "checking your browser before accessing")
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.collector_recommendation().startswith("BLOCKED_BOT")
    assert "Blocked" in result.estimated_implementation_effort()


def test_recommendation_needs_owner_probe_when_framework_but_no_data():
    base = "https://ex11.com"
    routes = _base_routes(base, '<script>window.__NEXT_DATA__={}</script>')
    result = probe_storefront(base, session=_FakeSession(routes))
    rec = result.collector_recommendation()
    assert rec.startswith("NEEDS_OWNER_PROBE")
    assert "Next.js" in rec
    assert result.estimated_implementation_effort().startswith("High")


def test_public_api_count_aggregates_signals():
    base = "https://ex12.com"
    html = '<script src="graphql-client.js"></script>'
    routes = _base_routes(base, html)
    routes[f"{base}/products.json"] = _FakeResponse(
        f"{base}/products.json", 200, '{"products":[{"id":1}]}')
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.public_api_count() == 2  # shopify + graphql hint


def test_sitemap_compressed_flag():
    base = "https://ex13.com"
    routes = _base_routes(base, "<html></html>")
    routes[f"{base}/robots.txt"] = _FakeResponse(
        f"{base}/robots.txt", 200, "Sitemap: https://ex13.com/sitemap.xml.gz")
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.sitemap_compressed is True


def test_to_dict_includes_derived_fields():
    base = "https://ex14.com"
    routes = _base_routes(base, "<html></html>")
    result = probe_storefront(base, session=_FakeSession(routes))
    d = result.to_dict()
    assert "public_api_count" in d
    assert "estimated_implementation_effort" in d
    assert "collector_recommendation" in d
