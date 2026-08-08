"""core.textutil: shared helpers extracted from shopify/sitemap_jsonld/
woocommerce_store_api/dell during the Stage 7 engine-maturity review."""

from __future__ import annotations

from oem_radar.core.models import Availability
from oem_radar.core.textutil import contains_any, parse_schema_availability, strip_html


def test_strip_html_removes_tags_and_unescapes_entities():
    assert strip_html("<p>Hello &amp; welcome</p>") == "Hello & welcome"


def test_strip_html_collapses_whitespace():
    assert strip_html("a\n\n  b\t\tc") == "a b c"


def test_strip_html_none_input_returns_empty_string():
    assert strip_html(None) == ""


def test_contains_any_case_insensitive():
    assert contains_any("Extended WARRANTY Plan", ["warranty"]) is True
    assert contains_any("A perfectly normal laptop", ["warranty"]) is False


def test_contains_any_empty_terms_never_matches():
    assert contains_any("anything", []) is False


def test_parse_schema_availability_in_stock():
    assert parse_schema_availability("https://schema.org/InStock") == Availability.IN_STOCK
    assert parse_schema_availability("InStock") == Availability.IN_STOCK


def test_parse_schema_availability_out_of_stock():
    assert parse_schema_availability("https://schema.org/OutOfStock") == Availability.SOLD_OUT


def test_parse_schema_availability_preorder():
    assert parse_schema_availability("PreOrder") == Availability.PREORDER


def test_parse_schema_availability_unknown_or_missing():
    assert parse_schema_availability(None) == Availability.UNKNOWN
    assert parse_schema_availability("") == Availability.UNKNOWN
    assert parse_schema_availability("SomethingElse") == Availability.UNKNOWN
