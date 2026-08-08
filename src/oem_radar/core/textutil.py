"""Shared engine text/data utilities (Stage 7 Phase 5).

Extracted after `shopify`, `sitemap_jsonld`, and `woocommerce_store_api`
each carried an identical `_strip_html`/`_TAG_RE`/`_WS_RE` trio, and `dell`/
`sitemap_jsonld` each hand-rolled the same schema.org availability-string
mapping. Pure boilerplate, not policy — the actual non-product denylist
*term lists* stay local to each engine deliberately (see
`engines/sitemap_jsonld/__init__.py`'s module docstring): different
vendors need different terms, and sharing the list itself would couple
engines that should stay independent. Sharing the mechanics that apply
those lists is safe; sharing the lists would not be.
"""

from __future__ import annotations

import html as _html_mod
import re
from typing import Iterable

from .models import Availability

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(s: str | None) -> str:
    """Tags stripped, entities unescaped, whitespace collapsed. Used to turn
    a vendor's `body_html`/`description`/`short_description` field into
    plain text for storage."""
    return _WS_RE.sub(" ", _html_mod.unescape(_TAG_RE.sub(" ", s or ""))).strip()


def contains_any(haystack: str, terms: Iterable[str]) -> bool:
    """Case-insensitive substring match against any term — the mechanism
    behind every engine's non-product denylist. `haystack` should already
    combine whatever fields the denylist checks (name, URL, category, ...)."""
    low = haystack.lower()
    return any(term.lower() in low for term in terms)


def first_offer(offers) -> dict:
    """Schema.org `offers` may legally be a single `Offer` object or a list
    of them; most real single-price listings only ever populate one, so
    "take the first" is the right default for engines that track one price
    per listing (see `docs/ARCHITECTURE.md` on configurations vs. summary
    price). Extracted Stage 8 after `dell` and `category_jsonld` both
    carried the identical two-line list-or-dict normalization — genuine
    duplication, not shared preemptively. `sitemap_jsonld` deliberately does
    NOT use this: it keeps the full offer list to check every offer's
    availability, a different (and case-insensitive-keyed) need."""
    if isinstance(offers, list):
        return offers[0] if offers else {}
    return offers or {}


def parse_schema_availability(raw: str | None) -> Availability:
    """Map a schema.org-style availability value (e.g. "InStock",
    "https://schema.org/OutOfStock", "PreOrder") to the shared Availability
    enum. Case-insensitive substring match, since real sites emit both the
    bare enum name and the full schema.org URL."""
    low = str(raw or "").lower()
    if "outofstock" in low:
        return Availability.SOLD_OUT
    if "preorder" in low:
        return Availability.PREORDER
    if "instock" in low:
        return Availability.IN_STOCK
    return Availability.UNKNOWN
