"""Generic sitemap + schema.org JSON-LD engine (Stage 6).

For OEMs that publish a plain XML sitemap (optionally a sitemap *index* of
nested sitemaps) whose product pages embed schema.org `Product` JSON-LD.
No platform-specific code: everything vendor-specific — which sitemap to
start from, which URLs are actually products, currency — lives in the
per-source YAML descriptor via `SitemapJsonLdSourceConfig`.

Confirmed live 2026-08 against real, structurally different platforms
(WordPress/Yoast @graph, a Wix Stores site with schema-casing quirks, LG's
own CMS) — see docs/STAGE6_RECON.md. Two discovery-time truths this design
leans on:

- Bulk discovery (a sitemap) is cheap; the actual product data only exists
  on the *individual* product page — unlike Shopify's `/products.json`,
  this engine needs one fetch per product. The core pipeline already
  supports this: `discover()` returns bare `ProductRef`s with no
  `inline_payload`, so `run_source` fetches each URL itself before calling
  `parse()`.
- Real-world JSON-LD is inconsistent even within "the spec": `@type` can be
  a bare string or a list; `offers` can be a single object or a list;
  and at least one real site in this stage (Khadas, a Wix Store) emits
  `Offers`/`Availability` with capital letters instead of the documented
  `offers`/`availability`. Every field lookup here is deliberately
  case-tolerant for exactly this reason.
"""

from __future__ import annotations

import html as _html_mod
import re
from typing import Iterable
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ...core.config import SourceConfig
from ...core.interfaces import Fetcher
from ...core.jsonld import extract_jsonld_nodes
from ...core.models import (
    FetchedDocument,
    NormalizedProduct,
    Price,
    ProductRef,
    RawProduct,
    ValidationIssue,
)
from ...core.registry import engines
from ...core.textutil import contains_any, parse_schema_availability, strip_html

_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)

# Titles/URLs that aren't monitorable PC products — accessories, warranties,
# gift cards, cables. Same spirit as the Shopify engine's denylist; kept as
# a separate local list rather than a shared import so the two engines stay
# fully decoupled (a change to one can never silently affect the other).
_DEFAULT_NON_PRODUCT = [
    "gift card", "gift-card", "warranty", "extended-warranty", "power supply",
    "power-supply", "cable", "adapter", "replacement", "spare part",
    "return label", "shipping-protection", "protection plan",
]


def _ci_get(d: dict, *keys: str):
    """Case-insensitive dict lookup — real sites emit both `offers` and
    `Offers`, `availability` and `Availability` (see module docstring)."""
    for k in keys:
        if k in d:
            return d[k]
    lower = {k.lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in lower:
            return lower[k.lower()]
    return None


class SitemapJsonLdSourceConfig(BaseModel):
    model_config = {"extra": "ignore"}
    # Defaults to {base_url}/sitemap.xml when unset.
    sitemap_url: str | None = None
    # Regex applied to every discovered URL. include keeps only matches;
    # exclude drops matches. Both optional; this is how e.g. Medion's
    # mixed-catalog sitemap gets scoped to notebook/desktop paths without
    # any vendor-specific code in the engine.
    url_include_pattern: str | None = None
    url_exclude_pattern: str | None = None
    # Safety valves — mirrors ShopifySourceConfig.max_pages.
    max_sitemaps: int = 50
    max_products: int = 3000
    currency_default: str = "USD"
    non_product_terms: list[str] = Field(default_factory=list)


@engines.register("sitemap_jsonld")
class SitemapJsonLdEngine:
    config_schema = SitemapJsonLdSourceConfig

    def __init__(self, source: SourceConfig, manufacturer: str) -> None:
        self.source = source
        self.manufacturer = manufacturer
        self.cfg = SitemapJsonLdSourceConfig.model_validate(source.model_dump())
        self.base = source.base_url.rstrip("/")

    # -- discovery: sitemap index/leaf walk, no product data yet -------------

    def discover(self, fetcher: Fetcher) -> Iterable[ProductRef]:
        root = self.cfg.sitemap_url or f"{self.base}/sitemap.xml"
        visited: set[str] = set()
        queue: list[str] = [root]
        product_urls: list[str] = []
        seen_products: set[str] = set()

        while queue and len(visited) < self.cfg.max_sitemaps:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                doc = fetcher.get(url)
            except Exception:
                continue  # one broken sitemap in an index must not sink the rest
            body = doc.body or ""
            locs = _LOC_RE.findall(body)
            is_index = "<sitemapindex" in body.lower()
            for loc in locs:
                loc = _html_mod.unescape(loc.strip())
                if not loc:
                    continue
                if is_index or loc.lower().endswith((".xml", ".xml.gz")):
                    if loc not in visited and len(visited) + len(queue) < self.cfg.max_sitemaps:
                        queue.append(loc)
                else:
                    if loc not in seen_products:
                        seen_products.add(loc)
                        product_urls.append(loc)

        include = re.compile(self.cfg.url_include_pattern) if self.cfg.url_include_pattern else None
        exclude = re.compile(self.cfg.url_exclude_pattern) if self.cfg.url_exclude_pattern else None

        refs: list[ProductRef] = []
        for u in product_urls:
            if include and not include.search(u):
                continue
            if exclude and exclude.search(u):
                continue
            refs.append(ProductRef(url=u, handle=self._slug(u)))
            if len(refs) >= self.cfg.max_products:
                break
        return refs

    @staticmethod
    def _slug(url: str) -> str:
        path = urlparse(url).path.rstrip("/")
        return path.rsplit("/", 1)[-1] or url

    # -- parse / normalize / validate ----------------------------------------

    def parse(self, doc: FetchedDocument) -> RawProduct:
        nodes = extract_jsonld_nodes(doc.body, type_filter="product")
        node = self._pick_node(nodes, doc.url)
        return RawProduct(source_id=self.source.id, url=doc.url, payload=node or {})

    @staticmethod
    def _pick_node(nodes: list[dict], page_url: str) -> dict | None:
        """A page can legitimately embed more than one Product node (e.g. a
        'you may also like' rail using the same schema). Prefer the one that
        identifies itself as *this* page; otherwise take the first."""
        if not nodes:
            return None
        for n in nodes:
            ident = n.get("@id") or n.get("url")
            if isinstance(ident, str) and ident.rstrip("/") == page_url.rstrip("/"):
                return n
        return nodes[0]

    def normalize(self, raw: RawProduct) -> NormalizedProduct:
        p = raw.payload
        name = (p.get("name") or "").strip()
        desc = strip_html(p.get("description") or "")[:2000]

        sku = p.get("sku") or None
        mpn = p.get("mpn") or None
        vendor_sku = sku or mpn

        brand = p.get("brand")
        brand_name = (brand.get("name") if isinstance(brand, dict)
                      else brand if isinstance(brand, str) else None)

        prices = self._extract_prices(p)

        images = self._extract_images(p.get("image"))

        non_product = self._is_non_product(name, raw.url)
        confidence = 0.0 if non_product else 1.0
        if not non_product:
            if not vendor_sku:
                confidence = min(confidence, 0.6)
            if not prices:
                confidence = min(confidence, 0.6)

        return NormalizedProduct(
            manufacturer=self.manufacturer,
            model=name,  # "" when JSON-LD had no usable Product node — validate() catches it
            prices=prices,
            vendor_sku=vendor_sku,
            images=images[:10],
            description=desc or None,
            source_url=p.get("url") or raw.url,
            confidence=max(confidence, 0.0),
            aliases=[a for a in (sku, mpn) if a],
            raw_data={
                "brand": brand_name,
                "mpn": mpn,
                "jsonld_type": p.get("@type"),
                "non_product": non_product,
            },
        )

    def _extract_prices(self, p: dict) -> list[Price]:
        offers_raw = _ci_get(p, "offers", "Offers", "offer", "Offer")
        offer_list = offers_raw if isinstance(offers_raw, list) else ([offers_raw] if offers_raw else [])
        prices: list[Price] = []
        for o in offer_list:
            if not isinstance(o, dict):
                continue
            price_val = _ci_get(o, "price", "Price")
            currency = _ci_get(o, "priceCurrency", "PriceCurrency") or self.cfg.currency_default
            availability = parse_schema_availability(_ci_get(o, "availability", "Availability"))
            try:
                amt = float(price_val) if price_val not in (None, "") else None
            except (TypeError, ValueError):
                amt = None
            # A real, honest zero/blank price (several confirmed vendors use
            # "0" as a "request a quote" placeholder) is not usable pricing
            # signal — dropped here rather than stored as a fake $0 product.
            if amt is not None and amt > 0:
                prices.append(Price(amount=amt, currency=str(currency), availability=availability))
        return prices

    @staticmethod
    def _extract_images(image_field) -> list[str]:
        if image_field is None:
            return []
        if isinstance(image_field, str):
            return [image_field]
        images: list[str] = []
        if isinstance(image_field, list):
            for im in image_field:
                if isinstance(im, str):
                    images.append(im)
                elif isinstance(im, dict):
                    url = im.get("contentUrl") or im.get("url")
                    if url:
                        images.append(url)
        elif isinstance(image_field, dict):
            url = image_field.get("contentUrl") or image_field.get("url")
            if url:
                images.append(url)
        return images

    def _is_non_product(self, name: str, url: str) -> bool:
        hay = f"{name} {url}"
        return contains_any(hay, _DEFAULT_NON_PRODUCT + self.cfg.non_product_terms)

    def validate(self, product: NormalizedProduct) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if product.raw_data.get("non_product"):
            issues.append(ValidationIssue(
                field="model", message="not a monitorable PC product (denylist match)",
                fatal=True))
            return issues
        if not product.model:
            issues.append(ValidationIssue(field="model", message="no Product name in JSON-LD",
                                          fatal=True))
            return issues
        if not product.vendor_sku:
            issues.append(ValidationIssue(field="vendor_sku",
                          message="no sku/mpn in JSON-LD"))
        if not product.prices:
            issues.append(ValidationIssue(field="prices",
                          message="no usable offer price in JSON-LD"))
        brand = product.raw_data.get("brand")
        if brand and self.manufacturer.lower() not in brand.lower() \
                and brand.lower() not in self.manufacturer.lower():
            issues.append(ValidationIssue(
                field="brand",
                message=f"JSON-LD brand {brand!r} doesn't match configured "
                        f"manufacturer {self.manufacturer!r} — possible misconfigured source"))
        return issues
