"""Generic WooCommerce Store API engine (Stage 7).

`GET {base}/wp-json/wc/store/v1/products` — when a WooCommerce site exposes
it (many don't; several real sites checked across Stage 5-7 return 404/500
even with clear WooCommerce hints elsewhere on the page), it returns a
paginated, full-fidelity product catalog: real prices, stock status,
categories, and stable numeric IDs. Confirmed live against three
independent OEMs (GEEKOM, NovaCustom, Pine64) before this engine was built
— see docs/STAGE7.md.

Like the `shopify` engine (and unlike `sitemap_jsonld`), this is a
bulk-inline discovery pattern: one paginated endpoint returns full product
records, so `discover()` embeds each record as `ProductRef.inline_payload`
and the pipeline never has to fetch a per-product page.

One real-world quirk this engine exists to handle correctly: the Store API
returns `prices.price` as a **string of the amount in minor units** (e.g.
"104000" for a laptop), scaled by `prices.currency_minor_unit` (usually 2,
sometimes 0) — dividing wrong by a fixed 100 would silently misprice every
site that uses a different minor-unit count (GEEKOM's is 0).
"""

from __future__ import annotations

import json
from typing import Iterable

from pydantic import BaseModel, Field

from ...core.config import SourceConfig
from ...core.interfaces import Fetcher
from ...core.models import (
    Availability,
    NormalizedProduct,
    Price,
    ProductRef,
    RawProduct,
    ValidationIssue,
)
from ...core.registry import engines
from ...core.textutil import contains_any, strip_html

# Same spirit as the Shopify/sitemap_jsonld denylists, kept local and
# decoupled — accessories/spare-parts/warranty terms common across
# WooCommerce storefronts observed in Stage 5-7 (GEEKOM, NovaCustom, Pine64).
# Deliberately excludes generic input-device words like "keyboard"/"mouse":
# a real Pine64 laptop is literally named "PINEBOOK Pro LINUX LAPTOP (UK
# Keyboard)" — those words describe a real product's regional variant, not
# an accessory. Per-source `non_product_terms` can add them back when a
# specific catalog's *standalone* keyboard/mouse listings need filtering
# (e.g. NovaCustom's "DVORAK keyboard (USB)").
_DEFAULT_NON_PRODUCT = [
    "gift card", "warranty", "power supply", "power adapter", "cable",
    "adapter", "replacement", "spare part", "dock", "case", "bag",
    "sleeve", "screw", "bracket", "sticker", "shipping",
]


class WooCommerceSourceConfig(BaseModel):
    model_config = {"extra": "ignore"}
    per_page: int = 100
    max_pages: int = 30
    non_product_terms: list[str] = Field(default_factory=list)
    # Category name/slug substrings (case-insensitive). If category_include
    # is set, a product is kept only when at least one of its categories
    # matches; category_exclude always drops a match regardless of include.
    # This is how e.g. NovaCustom's ~275-item mixed catalog (laptops mixed
    # with spare parts, refurb listings, keyboards) gets scoped to just the
    # real new-laptop/mini-PC categories without any vendor code.
    category_include: list[str] = Field(default_factory=list)
    category_exclude: list[str] = Field(default_factory=list)


@engines.register("woocommerce_store_api")
class WooCommerceStoreApiEngine:
    config_schema = WooCommerceSourceConfig

    def __init__(self, source: SourceConfig, manufacturer: str) -> None:
        self.source = source
        self.manufacturer = manufacturer
        self.cfg = WooCommerceSourceConfig.model_validate(source.model_dump())
        self.base = source.base_url.rstrip("/")

    # -- discovery: bulk-inline, paginated ------------------------------------

    def discover(self, fetcher: Fetcher) -> Iterable[ProductRef]:
        refs: list[ProductRef] = []
        for page in range(1, self.cfg.max_pages + 1):
            url = f"{self.base}/wp-json/wc/store/v1/products?per_page={self.cfg.per_page}&page={page}"
            try:
                doc = fetcher.get(url)
            except Exception:
                break  # one bad page must not lose already-discovered pages
            try:
                products = json.loads(doc.body)
            except (json.JSONDecodeError, TypeError, ValueError):
                break
            if not isinstance(products, list) or not products:
                break
            for p in products:
                if not isinstance(p, dict):
                    continue
                pid = p.get("id")
                slug = p.get("slug") or (str(pid) if pid is not None else None)
                url_ = p.get("permalink") or f"{self.base}/?p={pid}"
                refs.append(ProductRef(url=url_, handle=slug, inline_payload=p))
            if len(products) < self.cfg.per_page:
                break  # short page = last page
        return refs

    # -- parse / normalize / validate ----------------------------------------

    def parse(self, doc) -> RawProduct:
        return RawProduct(source_id=self.source.id, url=doc.url,
                          payload=json.loads(doc.body))

    def normalize(self, raw: RawProduct) -> NormalizedProduct:
        p = raw.payload
        name = strip_html(p.get("name") or "")
        sku = p.get("sku") or None
        categories = [c.get("name", "") for c in (p.get("categories") or [])
                      if isinstance(c, dict)]

        non_product = self._is_non_product(name, categories)
        prices = self._extract_prices(p)

        images = [im.get("src") for im in (p.get("images") or [])
                  if isinstance(im, dict) and im.get("src")]

        desc = strip_html(p.get("short_description") or p.get("description") or "")[:2000]

        confidence = 0.0 if non_product else 1.0
        if not non_product:
            if not sku:
                confidence = min(confidence, 0.6)
            if not prices:
                confidence = min(confidence, 0.6)

        wc_id = p.get("id")
        return NormalizedProduct(
            manufacturer=self.manufacturer,
            model=name,
            prices=prices,
            vendor_sku=sku,
            images=images[:10],
            description=desc or None,
            source_url=p.get("permalink") or raw.url,
            confidence=max(confidence, 0.0),
            aliases=[a for a in (sku, str(wc_id) if wc_id is not None else None) if a],
            raw_data={
                "wc_id": wc_id,
                "wc_type": p.get("type"),
                "categories": categories,
                "non_product": non_product,
            },
        )

    @staticmethod
    def _extract_prices(p: dict) -> list[Price]:
        prices_obj = p.get("prices")
        if not isinstance(prices_obj, dict):
            return []
        raw_price = prices_obj.get("price")
        minor = prices_obj.get("currency_minor_unit")
        try:
            minor = int(minor) if minor is not None else 2
        except (TypeError, ValueError):
            minor = 2
        currency = prices_obj.get("currency_code") or "USD"
        try:
            amt = float(raw_price) / (10 ** minor) if raw_price not in (None, "") else None
        except (TypeError, ValueError):
            amt = None
        if amt is None or amt <= 0:
            return []
        availability = (Availability.IN_STOCK if p.get("is_in_stock")
                       else Availability.SOLD_OUT if p.get("is_in_stock") is False
                       else Availability.UNKNOWN)
        return [Price(amount=amt, currency=str(currency), availability=availability)]

    def _is_non_product(self, name: str, categories: list[str]) -> bool:
        hay = f"{name} {' '.join(categories)}"
        if contains_any(hay, _DEFAULT_NON_PRODUCT + self.cfg.non_product_terms):
            return True
        cats_lower = [c.lower() for c in categories]
        if self.cfg.category_exclude and any(
            any(ex.lower() in c for c in cats_lower) for ex in self.cfg.category_exclude
        ):
            return True
        if self.cfg.category_include and not any(
            any(inc.lower() in c for c in cats_lower) for inc in self.cfg.category_include
        ):
            return True
        return False

    def validate(self, product: NormalizedProduct) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if product.raw_data.get("non_product"):
            issues.append(ValidationIssue(
                field="model", message="not a monitorable PC product (denylist/category scoping)",
                fatal=True))
            return issues
        if not product.model:
            issues.append(ValidationIssue(field="model", message="no product name",
                                          fatal=True))
            return issues
        if not product.vendor_sku:
            issues.append(ValidationIssue(field="vendor_sku", message="no SKU in Store API response"))
        if not product.prices:
            issues.append(ValidationIssue(field="prices", message="no usable price in Store API response"))
        return issues
