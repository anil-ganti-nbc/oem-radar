"""Shared JSON-LD extraction. Used by `core.probe` (reconnaissance) and the
`sitemap_jsonld` engine (collection) so the "walk plain object / array /
@graph, tolerate malformed blocks" logic lives in exactly one place.
"""

from __future__ import annotations

import json
import re
from typing import Any

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def extract_jsonld_nodes(html: str, type_filter: str | None = None) -> list[dict[str, Any]]:
    """Every JSON-LD node embedded in `html`, flattened across plain-object,
    array, and `@graph` shapes. Malformed blocks are skipped, never fatal.

    `type_filter`: if given, keep only nodes whose `@type` (a string or a
    list of strings — schema.org allows both, and so does the casing some
    real sites use, e.g. lowercase `"product"`) case-insensitively matches.
    """
    nodes: list[dict[str, Any]] = []
    for raw in _JSONLD_RE.findall(html):
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            graph = data.get("@graph")
            candidates = graph if isinstance(graph, list) else [data]
        else:
            continue
        for node in candidates:
            if not isinstance(node, dict):
                continue
            if type_filter is not None:
                t = node.get("@type")
                types = t if isinstance(t, list) else [t]
                if not any(isinstance(x, str) and x.lower() == type_filter.lower() for x in types):
                    continue
            nodes.append(node)
    return nodes


def extract_page_products(html: str) -> list[dict[str, Any]]:
    """Every real `Product` node on a category/listing page, across the two
    real shapes seen so far (Stage 8): products nested inside an `ItemList`'s
    `itemListElement[].item` (Samsung — the `ItemList` itself carries full
    offer/price data per item), and standalone top-level `Product` nodes
    sitting as sibling `<script>` blocks alongside a purely-navigational
    `ItemList` that has no offer data of its own (Lenovo — its `ItemList`
    only carries `name`/`url`/`image` per `ListItem`, with the actual
    price/sku/availability living in separate per-product `Product` blocks
    on the same page). Both are "the category page IS the bulk catalog"
    shapes; which one a given platform uses is a fact about that platform,
    not something to assume, so both are checked rather than picking one.

    A nested `ListItem.item` is kept only when it looks like a real product
    (typed `Product`, or carries `sku`/`offers`) — this is what keeps a
    purely-navigational `ItemList` (Lenovo's, or a breadcrumb-style one)
    from being misread as a product catalog.
    """
    products: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for node in extract_jsonld_nodes(html, type_filter="ItemList"):
        elements = node.get("itemListElement")
        if not isinstance(elements, list):
            continue
        for el in elements:
            if not isinstance(el, dict):
                continue
            item = el.get("item", el)
            if not isinstance(item, dict):
                continue
            t = item.get("@type")
            types = t if isinstance(t, list) else [t]
            if (any(isinstance(x, str) and x.lower() == "product" for x in types)
                    or "sku" in item or "offers" in item):
                products.append(item)
                if isinstance(item.get("url"), str):
                    seen_urls.add(item["url"])

    for node in extract_jsonld_nodes(html, type_filter="Product"):
        url = node.get("url")
        if isinstance(url, str) and url in seen_urls:
            continue  # already captured via the nested-ItemList path
        products.append(node)

    return products
