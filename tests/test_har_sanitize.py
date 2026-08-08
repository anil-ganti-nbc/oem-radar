"""Stage 10 Track 2: har_sanitize. A synthetic HAR fixture is used
deliberately here (not a real owner capture) — this tests the redaction
logic itself, the same convention tests/test_probe.py uses for
hand-written malformed inputs: never presented as a real vendor/owner
capture, only as a correctness check on the sanitizer's own behavior.
"""

from __future__ import annotations

import json

import pytest

from oem_radar.core.har_sanitize import sanitize_har


def _har(entries):
    return {"log": {"version": "1.2", "creator": {"name": "test"}, "entries": entries}}


def _entry(*, req_headers=None, req_cookies=None, query=None, post_data=None,
           resp_headers=None, resp_cookies=None, resp_content=None, status=200):
    return {
        "request": {
            "method": "GET", "url": "https://www.asus.com/api/products?category=laptops",
            "headers": req_headers or [], "cookies": req_cookies or [],
            "queryString": query or [],
            **({"postData": post_data} if post_data is not None else {}),
        },
        "response": {
            "status": status,
            "headers": resp_headers or [],
            "cookies": resp_cookies or [],
            "content": resp_content or {"mimeType": "application/json", "text": "{}"},
        },
    }


def test_strips_cookie_header():
    har = _har([_entry(req_headers=[{"name": "Cookie", "value": "sessionid=abc123"}])])
    out = sanitize_har(har)
    h = out["log"]["entries"][0]["request"]["headers"][0]
    assert h["value"] == "[REDACTED]"


def test_strips_authorization_header_case_insensitive():
    har = _har([_entry(resp_headers=[{"name": "authorization", "value": "Bearer xyz"}])])
    out = sanitize_har(har)
    assert out["log"]["entries"][0]["response"]["headers"][0]["value"] == "[REDACTED]"


def test_strips_all_cookies_regardless_of_name():
    har = _har([_entry(req_cookies=[{"name": "anything", "value": "whatever"}])])
    out = sanitize_har(har)
    assert out["log"]["entries"][0]["request"]["cookies"] == []


def test_strips_csrf_and_api_key_headers():
    har = _har([_entry(req_headers=[
        {"name": "X-CSRF-Token", "value": "t1"},
        {"name": "X-Api-Key", "value": "k1"},
        {"name": "Content-Type", "value": "application/json"},
    ])])
    out = sanitize_har(har)
    headers = {h["name"]: h["value"] for h in out["log"]["entries"][0]["request"]["headers"]}
    assert headers["X-CSRF-Token"] == "[REDACTED]"
    assert headers["X-Api-Key"] == "[REDACTED]"
    assert headers["Content-Type"] == "application/json"  # not sensitive — preserved


def test_strips_sensitive_query_params_keeps_others():
    har = _har([_entry(query=[
        {"name": "session_id", "value": "s1"},
        {"name": "category", "value": "laptops"},
    ])])
    out = sanitize_har(har)
    qs = {q["name"]: q["value"] for q in out["log"]["entries"][0]["request"]["queryString"]}
    assert qs["session_id"] == "[REDACTED]"
    assert qs["category"] == "laptops"  # real reconnaissance value — preserved


def test_strips_token_field_inside_json_response_body():
    body = json.dumps({"products": [{"sku": "X1", "price": 999}], "auth_token": "secret123"})
    har = _har([_entry(resp_content={"mimeType": "application/json", "text": body})])
    out = sanitize_har(har)
    result = json.loads(out["log"]["entries"][0]["response"]["content"]["text"])
    assert result["auth_token"] == "[REDACTED]"
    assert result["products"] == [{"sku": "X1", "price": 999}]  # real product data — preserved


def test_strips_token_field_inside_json_post_body():
    post_data = {"mimeType": "application/json", "text": json.dumps({"csrf": "abc", "filter": "laptop"})}
    har = _har([_entry(post_data=post_data)])
    out = sanitize_har(har)
    body = json.loads(out["log"]["entries"][0]["request"]["postData"]["text"])
    assert body["csrf"] == "[REDACTED]"
    assert body["filter"] == "laptop"


def test_non_json_body_left_alone_not_crashed():
    har = _har([_entry(resp_content={"mimeType": "text/html", "text": "<html>not json</html>"})])
    out = sanitize_har(har)
    assert out["log"]["entries"][0]["response"]["content"]["text"] == "<html>not json</html>"


def test_preserves_url_method_status_for_reconnaissance():
    har = _har([_entry(status=200)])
    out = sanitize_har(har)
    req = out["log"]["entries"][0]["request"]
    assert req["url"] == "https://www.asus.com/api/products?category=laptops"
    assert req["method"] == "GET"
    assert out["log"]["entries"][0]["response"]["status"] == 200


def test_malformed_har_raises_value_error():
    with pytest.raises(ValueError):
        sanitize_har({"not": "a har file"})


def test_multiple_entries_all_sanitized():
    har = _har([
        _entry(req_headers=[{"name": "Cookie", "value": "a"}]),
        _entry(req_headers=[{"name": "Cookie", "value": "b"}]),
    ])
    out = sanitize_har(har)
    for e in out["log"]["entries"]:
        assert e["request"]["headers"][0]["value"] == "[REDACTED]"


def test_nested_dict_credential_field_deep_in_response_redacted():
    body = json.dumps({"data": {"user": {"session_token": "deep-secret", "name": "ok"}}})
    har = _har([_entry(resp_content={"mimeType": "application/json", "text": body})])
    out = sanitize_har(har)
    result = json.loads(out["log"]["entries"][0]["response"]["content"]["text"])
    assert result["data"]["user"]["session_token"] == "[REDACTED]"
    assert result["data"]["user"]["name"] == "ok"
