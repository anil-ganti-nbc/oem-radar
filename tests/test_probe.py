"""core.probe: deterministic storefront reconnaissance. Pure parsing logic
tested offline (no network) via monkeypatched requests.Session; live probing
is exercised manually / during Stage 5 recon, not in the offline test suite."""

from __future__ import annotations

import json

import pytest

from oem_radar.core.probe import _extract_jsonld_product_count, _looks_bot_blocked, probe_storefront


# ---- JSON-LD Product extraction --------------------------------------------

def test_jsonld_single_product_object():
    html = '''<script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Product","name":"Widget"}
    </script>'''
    assert _extract_jsonld_product_count(html) == 1


def test_jsonld_array_of_objects():
    html = '''<script type="application/ld+json">
    [{"@type":"Product","name":"A"},{"@type":"BreadcrumbList"},{"@type":"Product","name":"B"}]
    </script>'''
    assert _extract_jsonld_product_count(html) == 2


def test_jsonld_graph_with_multiple_product_nodes():
    html = '''<script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"Product","name":"A"},
      {"@type":"Organization","name":"Acme"},
      {"@type":"Product","name":"B"}
    ]}
    </script>'''
    assert _extract_jsonld_product_count(html) == 2


def test_jsonld_type_as_list():
    html = '''<script type="application/ld+json">
    {"@type":["Product","Thing"],"name":"A"}
    </script>'''
    assert _extract_jsonld_product_count(html) == 1


def test_jsonld_malformed_json_is_skipped_not_fatal():
    html = '''<script type="application/ld+json">{not valid json</script>
    <script type="application/ld+json">{"@type":"Product","name":"OK"}</script>'''
    assert _extract_jsonld_product_count(html) == 1


def test_jsonld_no_blocks_returns_zero():
    assert _extract_jsonld_product_count("<html><body>no ld+json here</body></html>") == 0


def test_jsonld_non_product_types_ignored():
    html = '''<script type="application/ld+json">
    {"@type":"BreadcrumbList","itemListElement":[]}
    </script>'''
    assert _extract_jsonld_product_count(html) == 0


# ---- bot/challenge detection -------------------------------------------------

def test_bot_marker_strong_signal_regardless_of_status():
    assert _looks_bot_blocked(200, "Please wait... Checking your browser before...") is True


def test_bot_weak_marker_requires_403_or_503():
    assert _looks_bot_blocked(200, "protected by cloudflare, captcha widget included") is False
    assert _looks_bot_blocked(403, "Access Denied - protected by cloudflare") is True


def test_captcha_word_alone_on_200_is_not_a_false_positive():
    """Real-world regression: Shopify's own anti-spam captcha-bootstrap script
    embeds the literal word 'captcha' on completely ordinary storefronts."""
    body = '<script id="captcha-bootstrap">!function(){"use strict"}()</script>'
    assert _looks_bot_blocked(200, body) is False


def test_clean_page_not_flagged():
    assert _looks_bot_blocked(200, "<html><body>Welcome to our store</body></html>") is False


# ---- probe_storefront orchestration (network mocked) ------------------------

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
        # Longest-prefix match so e.g. "/products.json" doesn't get
        # shadowed by the bare base-URL route.
        match = max((p for p in self.routes if url.startswith(p)), key=len, default=None)
        if match is None:
            raise AssertionError(f"unexpected URL in fake session: {url}")
        return self.routes[match]


def test_probe_detects_shopify_end_to_end():
    base = "https://shop.example.com"
    routes = {
        base: _FakeResponse(base, 200, "<html>storefront</html>", headers={"Server": "cloudflare"}),
        f"{base}/products.json": _FakeResponse(
            f"{base}/products.json", 200,
            json.dumps({"products": [{"id": 1}, {"id": 2}]}),
        ),
        f"{base}/wp-json/wc/store/v1/products": _FakeResponse(
            f"{base}/wp-json/wc/store/v1/products", 404, "not found"),
        f"{base}/sitemap.xml": _FakeResponse(f"{base}/sitemap.xml", 404, "not found"),
        f"{base}/robots.txt": _FakeResponse(f"{base}/robots.txt", 404, "not found"),
    }
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.shopify_products_json is True
    assert result.shopify_product_count_sample == 2
    assert result.platform_guess() == "shopify"
    assert result.error is None


def test_probe_detects_woocommerce_store_api():
    base = "https://shop2.example.com"
    routes = {
        base: _FakeResponse(base, 200, "<html>Powered by WooCommerce</html>"),
        f"{base}/products.json": _FakeResponse(f"{base}/products.json", 404, "not found"),
        f"{base}/wp-json/wc/store/v1/products": _FakeResponse(
            f"{base}/wp-json/wc/store/v1/products", 200,
            json.dumps([{"id": 1}, {"id": 2}, {"id": 3}]),
        ),
        f"{base}/sitemap.xml": _FakeResponse(f"{base}/sitemap.xml", 404, "not found"),
        f"{base}/robots.txt": _FakeResponse(f"{base}/robots.txt", 404, "not found"),
    }
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.woocommerce_store_api is True
    assert result.woocommerce_store_api_count_sample == 3
    assert result.platform_guess() == "woocommerce_store_api"


def test_probe_detects_sitemap_index():
    base = "https://shop3.example.com"
    routes = {
        base: _FakeResponse(base, 200, "<html>static catalog</html>"),
        f"{base}/products.json": _FakeResponse(f"{base}/products.json", 404, "not found"),
        f"{base}/wp-json/wc/store/v1/products": _FakeResponse(
            f"{base}/wp-json/wc/store/v1/products", 404, "not found"),
        f"{base}/sitemap.xml": _FakeResponse(
            f"{base}/sitemap.xml", 200,
            "<sitemapindex><sitemap><loc>https://shop3.example.com/sitemap-products.xml</loc></sitemap></sitemapindex>",
        ),
    }
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.sitemap_found is True
    assert result.sitemap_is_index is True
    assert result.product_sitemap_found is True


def test_probe_network_error_is_non_fatal_reported():
    class _BrokenSession:
        def get(self, *a, **kw):
            import requests
            raise requests.ConnectionError("refused")

    result = probe_storefront("https://down.example.com", session=_BrokenSession())
    assert result.error is not None
    assert result.status is None


def test_probe_redirect_chain_recorded():
    base = "https://old.example.com"
    final = "https://new.example.com"
    routes = {
        base: _FakeResponse(final, 200, "<html>moved</html>",
                            history=[_FakeResponse(base, 301, "")]),
        f"{final}/products.json": _FakeResponse(f"{final}/products.json", 404, "not found"),
        f"{final}/wp-json/wc/store/v1/products": _FakeResponse(
            f"{final}/wp-json/wc/store/v1/products", 404, "not found"),
        f"{final}/sitemap.xml": _FakeResponse(f"{final}/sitemap.xml", 404, "not found"),
        f"{final}/robots.txt": _FakeResponse(f"{final}/robots.txt", 404, "not found"),
    }
    result = probe_storefront(base, session=_FakeSession(routes))
    assert result.redirected is True
    assert result.final_url == final
