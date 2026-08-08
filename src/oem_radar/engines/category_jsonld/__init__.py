"""Category-page ItemList JSON-LD engine (Stage 8).

A second structural shape beyond `sitemap_jsonld`'s "sitemap + one `Product`
node per detail page": some platforms instead embed a full `ItemList` of
`Product` nodes — complete with price, availability, name, and image — right
on the category/listing page itself. `dell` was the first confirmed
instance of this shape (2026-07-22) and was deliberately left as a bespoke,
isolated engine because one OEM does not justify a general case (see
`docs/ENTERPRISE_OEM_ARCHITECTURE.md` §9).

Samsung (Stage 8, 2026-08-07) is the second confirmed instance:
`https://www.samsung.com/us/computers/galaxy-book/` embeds a real 12-item
`ItemList` with real price/availability/name/image, no sitemap needed at
all — the category page *is* the bulk catalog endpoint. Per the Dell
exception note's own stated trigger ("if a second OEM is ever confirmed
with the same shape, that is the trigger to extract a third reusable
engine — not before"), this engine generalizes that shape. `dell` itself is
NOT migrated onto this engine — it has its own text-fallback path and
Dell-specific silicon-extraction regexes tuned over two stages, and
touching working code to satisfy an abstraction would be refactoring for
aesthetics, not fixing genuine duplication (see docs/STAGE8.md §9).

Bulk-inline discovery, same contract as `shopify`/`woocommerce_store_api`:
`discover()` embeds each `Product` node as `ProductRef.inline_payload`, so
the pipeline never fetches a per-product detail page. Cheapest possible
crawl (one request per configured category URL) — but only works where the
category page's ItemList is itself complete, which is a per-platform fact
to verify with a real fetch, not assume from "has ItemList" alone (an
ItemList could just as easily be a navigational breadcrumb list with 3
items, which Samsung's own pages also emit — that shape doesn't come
through this parser because `extract_page_products` requires each
nested item to look like a real product, not merely be typed `ListItem`.
Lenovo (confirmed Stage 8) turned out to use a third real variant of this
shape: a purely-navigational `ItemList` (name/url/image only, no offers)
alongside separate standalone top-level `Product` blocks on the same page
— `extract_page_products` checks both shapes since which one a platform
uses is a fact to verify per-platform, not something to assume.
"""

from __future__ import annotations

import json
import re
from typing import Iterable

from pydantic import BaseModel, Field

from ...core.config import SourceConfig
from ...core.interfaces import Fetcher
from ...core.jsonld import extract_page_products
from ...core.models import (
    Component,
    NormalizedProduct,
    Price,
    ProductRef,
    RawProduct,
    ValidationIssue,
)
from ...core.registry import engines
from ...core.textutil import contains_any, first_offer, parse_schema_availability, strip_html

# Fallback identity: when a `Product` node has no `sku`/`mpn` (Samsung's
# category-page ItemList doesn't), some real platforms still embed a stable
# vendor code as a URL suffix (Samsung: "...-sku-np960ujh-xg7us"). Kept as a
# per-source-configurable regex rather than hardcoded, since the next
# platform to use this engine may not use the literal string "sku" as its
# separator.
_DEFAULT_SKU_URL_PATTERN = r"-sku-([a-z0-9\-]+)$"

_CPU_PATTERNS = [
    re.compile(r"snapdragon[- ]x2?[- ]?(?:elite|plus)?", re.I),
    re.compile(r"intel[- ]core[- ]ultra[- ](?:[57]355|[57]\b|9\b|x7\b)", re.I),
    re.compile(r"intel[- ]core[- ]ultra", re.I),
    re.compile(r"amd[- ]ryzen[- ]ai[- ]\d+\w*", re.I),
]
_STORAGE_RE = re.compile(r"(\d+)(tb|gb)(?!.*(?:\d+)(?:tb|gb))", re.I)
_MEMORY_RE = re.compile(r"(\d+)\s*gb\b", re.I)
_DISPLAY_RE = re.compile(r'(\d{2}(?:\.\d)?)["”]|(\d{2}(?:\.\d)?)-inch', re.I)


class CategoryJsonLdSourceConfig(BaseModel):
    model_config = {"extra": "ignore"}
    category_urls: list[str] = Field(default_factory=list)
    non_product_terms: list[str] = Field(default_factory=list)
    currency_default: str = "USD"
    region: str = "US"
    category: str = "laptop"
    sku_url_pattern: str = _DEFAULT_SKU_URL_PATTERN


@engines.register("category_jsonld")
class CategoryJsonLdEngine:
    config_schema = CategoryJsonLdSourceConfig

    def __init__(self, source: SourceConfig, manufacturer: str) -> None:
        self.source = source
        self.manufacturer = manufacturer
        self.cfg = CategoryJsonLdSourceConfig.model_validate(source.model_dump())
        self._sku_re = re.compile(self.cfg.sku_url_pattern, re.IGNORECASE)

    # -- discovery: bulk-inline, one fetch per configured category page ------

    def discover(self, fetcher: Fetcher) -> Iterable[ProductRef]:
        refs: list[ProductRef] = []
        seen: set[str] = set()
        for url in self.cfg.category_urls:
            try:
                doc = fetcher.get(url)
            except Exception:
                continue  # one bad category page must not lose the others
            for item in extract_page_products(doc.body):
                item_url = item.get("url")
                sku = item.get("sku") or item.get("mpn")
                if not sku and item_url:
                    m = self._sku_re.search(item_url)
                    sku = m.group(1).upper() if m else None
                handle = sku or item_url
                if not handle or handle in seen:
                    continue
                seen.add(handle)
                if sku:
                    item.setdefault("sku", sku)
                refs.append(ProductRef(url=item_url or url, handle=handle,
                                       inline_payload=item))
        return refs

    # -- parse / normalize / validate ----------------------------------------

    def parse(self, doc) -> RawProduct:
        return RawProduct(source_id=self.source.id, url=doc.url,
                          payload=json.loads(doc.body))

    def normalize(self, raw: RawProduct) -> NormalizedProduct:
        p = raw.payload
        name = strip_html(p.get("name") or "")
        sku = p.get("sku")
        url = p.get("url") or raw.url

        non_product = bool(name) and contains_any(name, self.cfg.non_product_terms)

        offers = first_offer(p.get("offers"))
        prices: list[Price] = []
        try:
            amt = float(offers.get("price")) if offers.get("price") not in (None, "") else None
        except (TypeError, ValueError):
            amt = None
        if amt is not None and amt > 0:
            prices.append(Price(
                amount=amt,
                currency=offers.get("priceCurrency") or self.cfg.currency_default,
                region=self.cfg.region.upper(),
                availability=parse_schema_availability(offers.get("availability")),
            ))

        images = []
        if p.get("image"):
            images = [p["image"]] if isinstance(p["image"], str) else list(p["image"])[:3]

        haystack = f"{name} {url}"
        cpu = self._first(_CPU_PATTERNS, haystack)
        storage = self._storage(haystack)
        memory = self._memory(name)
        display = self._display(name)

        confidence = 0.0 if non_product else 1.0
        if not non_product:
            if not sku:
                confidence = min(confidence, 0.6)
            if not prices:
                confidence = min(confidence, 0.6)

        return NormalizedProduct(
            manufacturer=self.manufacturer,
            model=name,
            category=self.cfg.category,
            cpu=Component(raw=cpu) if cpu else None,
            memory=memory,
            storage=storage,
            display=display,
            prices=prices,
            region=self.cfg.region.upper(),
            vendor_sku=sku,
            images=[i.split("?")[0] for i in images],
            source_url=url,
            confidence=max(confidence, 0.0),
            aliases=[sku] if sku else [],
            raw_data={"non_product": non_product},
        )

    @staticmethod
    def _first(patterns, text: str) -> str | None:
        for pat in patterns:
            m = pat.search(text or "")
            if m:
                return re.sub(r"[- ]+", " ", m.group(0)).strip().title()
        return None

    @staticmethod
    def _storage(text: str) -> str | None:
        m = _STORAGE_RE.search(text or "")
        return f"{m.group(1)}{m.group(2).upper()}" if m else None

    @staticmethod
    def _memory(text: str) -> str | None:
        m = _MEMORY_RE.search(text or "")
        return f"{m.group(1)} GB" if m else None

    @staticmethod
    def _display(text: str) -> str | None:
        m = _DISPLAY_RE.search(text or "")
        if not m:
            return None
        val = m.group(1) or m.group(2)
        return f'{val}"'

    def validate(self, product: NormalizedProduct) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if product.raw_data.get("non_product"):
            issues.append(ValidationIssue(
                field="model", message="matched non-product denylist term", fatal=True))
            return issues
        if not product.model:
            issues.append(ValidationIssue(field="model", message="no product name", fatal=True))
            return issues
        if not product.vendor_sku:
            issues.append(ValidationIssue(field="vendor_sku",
                          message="no SKU found in item or URL suffix"))
        if not product.prices:
            issues.append(ValidationIssue(field="prices", message="no usable price in listing"))
        return issues
