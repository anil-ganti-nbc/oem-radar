"""Deterministic storefront reconnaissance for `oem-radar probe`.

Pure HTTP/HTML/JSON inspection — no JS execution, no browser. Every check is
independent and non-fatal: a failed request just leaves that field False/None
rather than aborting the whole probe. Used both by the CLI and by Stage 5
OEM reconnaissance.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import requests

from .jsonld import extract_jsonld_nodes

DEFAULT_UA = "OEMRadar/0.1 (product-intelligence; respectful probe; contact@x8.design)"

# Strong markers: specific enough to trust regardless of HTTP status. Plain
# "captcha" is deliberately excluded — ordinary Shopify checkout/contact-form
# anti-spam widgets embed that word on completely normal storefronts.
_STRONG_BOT_MARKERS = (
    "checking your browser", "cf-chl", "just a moment", "attention required",
    "are you a human", "verify you are human", "solve the captcha",
)
# Weak markers: only meaningful paired with a 403/503 status, since they're
# common words that also appear on ordinary pages.
_WEAK_BOT_MARKERS = ("access denied", "unusual traffic", "cloudflare", "captcha")

# Framework/platform fingerprints — all string-substring checks on the raw
# HTML, deliberately simple (a false positive here just means "worth a
# closer manual look," not a wrong collector decision on its own).
_FRAMEWORK_MARKERS = (
    ("Next.js", ("__NEXT_DATA__", "/_next/static/")),
    ("Nuxt", ("__NUXT__", "/_nuxt/")),
    ("React (generic)", ("__REACT_DEVTOOLS_GLOBAL_HOOK__", "data-reactroot")),
)
_MAGENTO_MARKERS = ("magento_", "mage-cache-storage", "requirejs-config.js", "/static/version")
_ADOBE_COMMERCE_MARKERS = ("adobe commerce", "magento_cloud", "commerce-cloud")
_SFCC_MARKERS = ("demandware", "dwsid", "/on/demandware.store/", "salesforce commerce")
_GRAPHQL_MARKERS = ("graphql",)


def _jsonld_richness_score(html: str) -> int:
    """0-100: how complete the Product JSON-LD on this page is, averaged
    across every Product node found. Purely a measure of *data
    completeness* (name/identity/price/image/brand present or not) — not a
    judgment about the OEM's newsworthiness, which no static probe can
    determine. See collector_recommendation for how this feeds a technical
    (not editorial) suggestion."""
    nodes = extract_jsonld_nodes(html, type_filter="product")
    if not nodes:
        return 0
    fields = ("name", "sku", "mpn", "offers", "image", "brand")
    total = 0
    for node in nodes:
        present = sum(1 for f in fields if node.get(f) not in (None, "", [], {}))
        total += present / len(fields)
    return round(100 * total / len(nodes))


@dataclass
class ProbeResult:
    input_url: str
    final_url: str | None = None
    status: int | None = None
    redirected: bool = False
    redirect_chain: list[str] = field(default_factory=list)
    error: str | None = None

    shopify_products_json: bool = False
    shopify_product_count_sample: int | None = None
    shopify_theme_hint: bool = False

    woocommerce_hint: bool = False
    woocommerce_store_api: bool = False
    woocommerce_store_api_count_sample: int | None = None

    sitemap_found: bool = False
    sitemap_is_index: bool = False
    sitemap_url: str | None = None
    product_sitemap_found: bool = False

    jsonld_product_count: int = 0
    jsonld_richness_score: int = 0  # 0-100, data completeness only — see _jsonld_richness_score

    bot_challenge_hint: bool = False
    server_header: str | None = None

    # -- Stage 7 Phase 4: richer reconnaissance -------------------------------
    framework: str | None = None            # "Next.js" | "Nuxt" | "React (generic)" | None
    graphql_hint: bool = False
    magento_hint: bool = False
    adobe_commerce_hint: bool = False
    salesforce_commerce_hint: bool = False
    sitemap_compressed: bool = False        # sitemap URL ends .gz — needs decompression support

    def platform_guess(self) -> str:
        if self.bot_challenge_hint:
            return "BLOCKED_BOT"
        if self.shopify_products_json or self.shopify_theme_hint:
            return "shopify"
        if self.woocommerce_store_api:
            return "woocommerce_store_api"
        if self.woocommerce_hint:
            return "woocommerce"
        if self.magento_hint or self.adobe_commerce_hint:
            return "magento/adobe_commerce"
        if self.salesforce_commerce_hint:
            return "salesforce_commerce"
        if self.jsonld_product_count or self.product_sitemap_found:
            return "static_jsonld"
        if self.framework:
            return f"js_hydrated ({self.framework})"
        return "unknown"

    def public_api_count(self) -> int:
        """Count of distinct, confirmed-or-hinted public data APIs found —
        a rough proxy for "how many static integration points exist,"
        independent of which one turns out best."""
        return sum([
            self.shopify_products_json,
            self.woocommerce_store_api,
            self.graphql_hint,
            bool(self.jsonld_product_count),
        ])

    def estimated_implementation_effort(self) -> str:
        """A technical estimate from observable signals only (existing
        engine fit, data completeness) — not a guess at how hard a bespoke
        parser would be to write for a platform this tool hasn't seen yet."""
        if self.bot_challenge_hint:
            return "Blocked (not a Low/Medium/High estimate — static access denied)"
        if self.shopify_products_json or self.woocommerce_store_api:
            return "Low"  # existing generic engine, config-only
        if self.jsonld_product_count and self.jsonld_richness_score >= 60:
            return "Low"  # existing sitemap_jsonld engine likely fits as-is
        if self.jsonld_product_count and self.jsonld_richness_score >= 25:
            return "Medium"  # sitemap_jsonld fits but data is partial (e.g. no price)
        if self.framework:
            return "High (requires a public API check before any code — see docs)"
        return "Unknown (needs a product-page fetch, not just this root probe)"

    def collector_recommendation(self) -> str:
        """A technical suggestion only — never a claim about editorial
        value, which no static probe can determine."""
        if self.bot_challenge_hint:
            return "BLOCKED_BOT — do not pursue without a written browser-automation justification"
        if self.shopify_products_json:
            return "shopify"
        if self.woocommerce_store_api:
            return "woocommerce_store_api"
        if self.jsonld_product_count and self.jsonld_richness_score >= 25:
            return "sitemap_jsonld"
        if self.magento_hint or self.adobe_commerce_hint:
            return "NEEDS_OWNER_PROBE (Magento/Adobe Commerce — no engine yet, check for a public GraphQL/REST catalog API before assuming JS rendering is required)"
        if self.salesforce_commerce_hint:
            return "NEEDS_OWNER_PROBE (Salesforce Commerce Cloud — no engine yet)"
        if self.framework:
            return f"NEEDS_OWNER_PROBE ({self.framework} detected, no Product JSON-LD found — check for a public API the frontend itself calls before assuming JS rendering is required)"
        return "NEEDS_OWNER_PROBE"

    # -- Stage 9: reconnaissance-analyst report ------------------------------
    # Every method below derives strictly from fields already populated by
    # `probe_storefront()` above — no new network calls, no guessing. Editorial
    # value is deliberately never estimated here (see collector_recommendation's
    # docstring): a static probe can measure data completeness, not
    # newsworthiness, and Stage 9's mandate is "evidence-backed, never guessed."

    def confidence(self) -> int:
        """0-100: how sure the platform_guess/collector_recommendation are,
        given the evidence actually collected. Not a confidence in editorial
        value, which this probe never estimates."""
        if self.error:
            return 0
        if self.bot_challenge_hint:
            return 90  # confident it's blocked, not confident about anything past that
        if self.shopify_products_json:
            return 98
        if self.woocommerce_store_api:
            return 96
        if self.jsonld_product_count and self.jsonld_richness_score >= 60:
            return 85
        if self.jsonld_product_count and self.jsonld_richness_score >= 25:
            return 60
        if self.jsonld_product_count:
            return 40
        if self.framework:
            return 55  # confident about the framework, not about data availability
        if self.magento_hint or self.adobe_commerce_hint or self.salesforce_commerce_hint:
            return 50
        return 15  # nothing found on the root page; too little evidence for a real conclusion

    def evidence(self) -> list[str]:
        """Plain-language evidence lines backing platform_guess/confidence —
        every line traces to a field this probe actually observed."""
        items: list[str] = []
        if self.status is not None:
            items.append(
                f"HTTP {self.status}"
                + (f" after {len(self.redirect_chain) - 1} redirect(s)" if self.redirected else "")
            )
        if self.shopify_products_json:
            items.append(f"/products.json returned {self.shopify_product_count_sample} product(s)")
        elif self.shopify_theme_hint:
            items.append("cdn.shopify.com referenced in page body (theme asset only — products.json not confirmed)")
        if self.woocommerce_store_api:
            items.append(f"/wp-json/wc/store/v1/products returned {self.woocommerce_store_api_count_sample} product(s)")
        elif self.woocommerce_hint:
            items.append("WooCommerce/wp-content markers present, but Store API did not return product data")
        if self.sitemap_found:
            items.append(
                f"sitemap at {self.sitemap_url} (index={self.sitemap_is_index}, "
                f"product-shaped URLs={self.product_sitemap_found}"
                + (", compressed" if self.sitemap_compressed else "") + ")"
            )
        else:
            items.append("no sitemap found (root sitemap.xml or robots.txt Sitemap: directive)")
        if self.jsonld_product_count:
            items.append(f"{self.jsonld_product_count} Product JSON-LD node(s) on this page, richness={self.jsonld_richness_score}/100")
        if self.framework:
            items.append(f"{self.framework} framework markers detected")
        if self.graphql_hint:
            items.append("the word 'graphql' appears in page body (unconfirmed — not a verified endpoint)")
        if self.magento_hint:
            items.append("Magento markers detected")
        if self.adobe_commerce_hint:
            items.append("Adobe Commerce markers detected")
        if self.salesforce_commerce_hint:
            items.append("Salesforce Commerce Cloud markers detected")
        if self.bot_challenge_hint:
            items.append("bot/challenge page markers detected in response body")
        return items

    def known_risks(self) -> list[str]:
        risks: list[str] = []
        if self.bot_challenge_hint:
            risks.append("Root page itself is bot-gated — a deeper probe would likely also be blocked")
        if self.framework and not self.jsonld_product_count:
            risks.append(f"{self.framework} app with no server-rendered product data — likely requires JS execution, which this project does not do")
        if self.jsonld_product_count and self.jsonld_richness_score < 60:
            risks.append("JSON-LD present but incomplete (some fields missing) — expect validate() warnings, not silent failure")
        if self.shopify_products_json or self.woocommerce_store_api or self.jsonld_product_count:
            risks.append("Accessory/non-product filtering will be required (every enabled source needs a denylist)")
        if self.graphql_hint and not (self.shopify_products_json or self.woocommerce_store_api):
            risks.append("GraphQL mentioned in page body but no confirmed public catalog endpoint — do not assume one exists without a captured request")
        if not self.sitemap_found and not (self.shopify_products_json or self.woocommerce_store_api):
            risks.append("No sitemap found — category-page discovery would need a human to supply category URLs")
        if not risks:
            risks.append("None observed from this root-page probe — a full product-page fetch may still surface more")
        return risks

    def recommended_next_step(self) -> str:
        if self.bot_challenge_hint:
            return "Stop. Do not pursue without a written justification — this project does not spoof identity or bypass bot detection."
        if self.shopify_products_json or self.woocommerce_store_api:
            return "Capture fixtures and write a source descriptor (config-only, existing engine)."
        if self.jsonld_product_count and self.jsonld_richness_score >= 25:
            return "Fetch 2-3 more product pages to confirm richness holds across the catalog, then capture fixtures."
        if self.jsonld_product_count:
            return "Investigate why richness is low before committing — may be a partial/legacy JSON-LD template."
        if self.framework:
            return "Manually check browser devtools' network tab for a public fetch()/GraphQL call the frontend itself makes — not automatable by this probe."
        return "Fetch an actual product or category page (this probe only checked the root) before concluding anything."

    def discovery_quality(self) -> tuple[int, list[tuple[str, int, str]]]:
        """Stage 9 Phase 3: 0-100 discovery quality score, plus every
        deduction applied with its reason. Only deducts for confirmed
        evidence (never a guess); baseline 100 assumes maximal discovery
        fitness for what this single root-page probe could observe."""
        deductions: list[tuple[str, int, str]] = []
        has_bulk_api = self.shopify_products_json or self.woocommerce_store_api

        if self.bot_challenge_hint:
            deductions.append(("anti_bot", 50, "Root page is bot/challenge-gated — discovery cannot proceed at all"))

        if not self.sitemap_found and not has_bulk_api:
            deductions.append(("sitemap", 15, "No sitemap found and no bulk catalog API — discovery has no automatic entry point"))
        elif self.sitemap_compressed:
            deductions.append(("sitemap", 5, "Sitemap is gzip-compressed — unsupported by the current fetcher"))
        elif self.sitemap_found and not self.product_sitemap_found and not has_bulk_api and not self.jsonld_product_count:
            deductions.append(("sitemap", 8, "Sitemap found but no product-shaped URLs detected in it"))

        if not has_bulk_api and not self.jsonld_product_count and not self.graphql_hint:
            deductions.append(("data_availability", 25, "No public data source of any kind found (bulk API, JSON-LD, GraphQL hint)"))
        elif self.jsonld_product_count and not has_bulk_api:
            richness_gap = 100 - self.jsonld_richness_score
            pts = round(richness_gap * 0.15)
            if pts:
                deductions.append(("jsonld_richness", pts, f"JSON-LD richness is {self.jsonld_richness_score}/100 — missing fields reduce identity/price confidence"))

        if self.framework and not self.jsonld_product_count and not has_bulk_api:
            deductions.append(("js_hydration", 20, f"{self.framework} detected with no server-rendered product data — likely needs JS execution to discover anything"))

        total = sum(d[1] for d in deductions)
        return max(0, 100 - total), deductions

    def missing_information(self) -> list[str]:
        missing: list[str] = []
        if not self.sitemap_found:
            missing.append("Confirmed sitemap URL")
        if self.jsonld_product_count == 0 and not (self.shopify_products_json or self.woocommerce_store_api):
            missing.append("A real product/category page fetch (this probe only checked the root)")
        if self.framework and not self.jsonld_product_count:
            missing.append("Whether the frontend calls a public API (requires manual devtools inspection, not automatable)")
        if self.jsonld_product_count and self.jsonld_richness_score < 60:
            missing.append("Whether richness holds across the catalog, or this page was a lucky/unlucky sample")
        if not missing:
            missing.append("None — probe evidence is sufficient to decide the next step")
        return missing

    def recommended_fixture_count(self) -> str:
        if self.bot_challenge_hint:
            return "N/A — blocked"
        if self.shopify_products_json or self.woocommerce_store_api:
            return "1 bulk listing response + 1-2 product detail pages (existing engine minimum)"
        if self.jsonld_product_count and self.jsonld_richness_score >= 25:
            return "3+ category/product pages, per the reusable-engine bar (docs/PLUGIN_GUIDE.md)"
        return "Not yet determinable — need a confirmed data source first"

    def recommended_engineer_time(self) -> str:
        effort = self.estimated_implementation_effort()
        if effort == "Low":
            return "1-2 hours (config + fixture capture, existing engine)"
        if effort == "Medium":
            return "4-8 hours (existing engine, but scoping/denylist work needed for partial data)"
        if effort.startswith("High"):
            return "Not estimable until a public API is confirmed or ruled out by manual inspection"
        if effort.startswith("Blocked"):
            return "0 — do not pursue"
        return "Not estimable — needs a real product-page fetch first"

    def should_pursue(self) -> tuple[bool, str]:
        if self.bot_challenge_hint:
            return False, "Blocked by bot detection; pursuing would require identity-spoofing this project does not do"
        if self.shopify_products_json or self.woocommerce_store_api:
            return True, "Confirmed bulk data API — cheapest possible next OEM"
        if self.jsonld_product_count and self.jsonld_richness_score >= 25:
            return True, "Confirmed real structured data at a usable richness level"
        if self.jsonld_product_count:
            return False, "Structured data is real but too sparse to trust without a wider sample first (see Axiomtek precedent, docs/OEM_ECOSYSTEM_MAP.md)"
        if self.framework:
            return False, "No structured data found; needs a manual API check before any engineering time is spent"
        return False, "Insufficient evidence — this probe only checked the root page"

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["public_api_count"] = self.public_api_count()
        d["estimated_implementation_effort"] = self.estimated_implementation_effort()
        d["collector_recommendation"] = self.collector_recommendation()
        d["confidence"] = self.confidence()
        d["evidence"] = self.evidence()
        d["known_risks"] = self.known_risks()
        d["recommended_next_step"] = self.recommended_next_step()
        score, deductions = self.discovery_quality()
        d["discovery_quality_score"] = score
        d["discovery_quality_deductions"] = [
            {"category": c, "points": p, "reason": r} for c, p, r in deductions
        ]
        d["missing_information"] = self.missing_information()
        d["recommended_fixture_count"] = self.recommended_fixture_count()
        d["recommended_engineer_time"] = self.recommended_engineer_time()
        pursue, pursue_reason = self.should_pursue()
        d["should_pursue"] = pursue
        d["should_pursue_reason"] = pursue_reason
        return d


def _looks_bot_blocked(status: int, body: str) -> bool:
    low = body.lower()
    if any(m in low for m in _STRONG_BOT_MARKERS):
        return True
    if status in (403, 503):
        return any(m in low for m in _WEAK_BOT_MARKERS)
    return False


def _extract_jsonld_product_count(html: str) -> int:
    """Count Product nodes across all ld+json blocks — see core.jsonld for
    the shared plain-object/array/@graph walker (also used by the
    sitemap_jsonld engine)."""
    return len(extract_jsonld_nodes(html, type_filter="product"))


def probe_storefront(url: str, *, timeout: float = 15.0,
                     session: requests.Session | None = None) -> ProbeResult:
    """One deterministic recon pass over a storefront base URL. Every
    sub-check is independent and best-effort; network failures on optional
    endpoints (sitemap, wc store api) never abort the probe."""
    sess = session or requests.Session()
    headers = {"User-Agent": DEFAULT_UA}
    base = url.rstrip("/")
    result = ProbeResult(input_url=url)

    try:
        resp = sess.get(base, headers=headers, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        result.error = repr(exc)
        return result

    result.final_url = resp.url
    result.status = resp.status_code
    result.redirected = bool(resp.history)
    result.redirect_chain = [r.url for r in resp.history] + [resp.url]
    result.server_header = resp.headers.get("Server")
    body = resp.text or ""
    result.bot_challenge_hint = _looks_bot_blocked(resp.status_code, body)
    result.shopify_theme_hint = "cdn.shopify.com" in body.lower()
    low = body.lower()
    result.woocommerce_hint = "woocommerce" in low or "/wp-content/" in low
    result.jsonld_product_count = _extract_jsonld_product_count(body)
    result.jsonld_richness_score = _jsonld_richness_score(body)

    for fw_name, markers in _FRAMEWORK_MARKERS:
        if any(m in body for m in markers):  # case-sensitive: __NEXT_DATA__ etc. are exact tokens
            result.framework = fw_name
            break
    result.graphql_hint = any(m in low for m in _GRAPHQL_MARKERS)
    result.magento_hint = any(m in low for m in _MAGENTO_MARKERS)
    result.adobe_commerce_hint = any(m in low for m in _ADOBE_COMMERCE_MARKERS)
    result.salesforce_commerce_hint = any(m in low for m in _SFCC_MARKERS)

    effective_base = result.final_url.rstrip("/") if result.final_url else base

    # Shopify products.json
    try:
        r = sess.get(f"{effective_base}/products.json?limit=5", headers=headers,
                     timeout=timeout)
        if r.status_code == 200:
            data = json.loads(r.text)
            if isinstance(data, dict) and isinstance(data.get("products"), list):
                result.shopify_products_json = True
                result.shopify_product_count_sample = len(data["products"])
    except (requests.RequestException, json.JSONDecodeError, ValueError):
        pass

    # WooCommerce Store API
    try:
        r = sess.get(f"{effective_base}/wp-json/wc/store/v1/products?per_page=5",
                     headers=headers, timeout=timeout)
        if r.status_code == 200:
            data = json.loads(r.text)
            if isinstance(data, list):
                result.woocommerce_store_api = True
                result.woocommerce_store_api_count_sample = len(data)
    except (requests.RequestException, json.JSONDecodeError, ValueError):
        pass

    # sitemap.xml (fall back to robots.txt Sitemap: directive)
    try:
        r = sess.get(f"{effective_base}/sitemap.xml", headers=headers, timeout=timeout)
        if r.status_code == 200 and "<" in r.text[:200]:
            result.sitemap_found = True
            result.sitemap_url = f"{effective_base}/sitemap.xml"
            result.sitemap_is_index = "<sitemapindex" in r.text.lower()
            result.product_sitemap_found = bool(
                re.search(r"product", r.text, re.IGNORECASE)
            )
    except requests.RequestException:
        pass
    if not result.sitemap_found:
        try:
            r = sess.get(f"{effective_base}/robots.txt", headers=headers, timeout=timeout)
            if r.status_code == 200:
                m = re.search(r"Sitemap:\s*(\S+)", r.text, re.IGNORECASE)
                if m:
                    result.sitemap_found = True
                    result.sitemap_url = m.group(1)
        except requests.RequestException:
            pass
    if result.sitemap_url:
        result.sitemap_compressed = result.sitemap_url.lower().endswith(".gz")

    return result
