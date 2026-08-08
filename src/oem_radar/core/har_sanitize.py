"""Stage 10 Track 2: sanitize an owner-captured HAR export before anything
in it is stored as a fixture, pasted into a doc, or handed back to a
developer. An owner running the DevTools capture procedure
(`docs/OWNER_DEVTOOLS_GUIDE.md`) may export a full HAR without knowing
which fields are sensitive — this strips the credential-shaped ones and
keeps only what's useful for reconnaissance (endpoint, method, query
shape, a representative response body).

Deliberately narrow: this is a redaction pass over a well-known JSON
format, not a HAR analysis subsystem. It does not infer platform type,
does not classify the API, does not talk to the network.
"""

from __future__ import annotations

import json
from typing import Any

_SENSITIVE_HEADER_NAMES = frozenset({
    "cookie", "set-cookie", "authorization", "proxy-authorization",
    "x-csrf-token", "x-xsrf-token", "x-api-key", "x-auth-token",
})
_SENSITIVE_QUERY_PARAM_NAMES = frozenset({
    "token", "access_token", "auth", "session", "sessionid", "session_id",
    "api_key", "apikey", "csrf", "csrftoken", "bearer",
})
_SENSITIVE_COOKIE_LIKE = frozenset({"csrf", "xsrf"})
_REDACTED = "[REDACTED]"


def _is_sensitive_header(name: str) -> bool:
    low = name.lower()
    return low in _SENSITIVE_HEADER_NAMES or "token" in low or "secret" in low


def _is_sensitive_query_param(name: str) -> bool:
    return name.lower() in _SENSITIVE_QUERY_PARAM_NAMES


def _sanitize_headers(headers: Any) -> list[dict[str, Any]]:
    if not isinstance(headers, list):
        return []
    out = []
    for h in headers:
        if not isinstance(h, dict):
            continue
        name = h.get("name", "")
        if _is_sensitive_header(name):
            out.append({**h, "value": _REDACTED})
        else:
            out.append(h)
    return out


def _sanitize_query_string(qs: Any) -> list[dict[str, Any]]:
    if not isinstance(qs, list):
        return []
    out = []
    for q in qs:
        if not isinstance(q, dict):
            continue
        if _is_sensitive_query_param(q.get("name", "")):
            out.append({**q, "value": _REDACTED})
        else:
            out.append(q)
    return out


def _sanitize_post_data(post_data: Any) -> Any:
    if not isinstance(post_data, dict):
        return post_data
    out = dict(post_data)
    text = out.get("text")
    if isinstance(text, str):
        try:
            body = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            out["text"] = text  # not JSON — left as-is, no credential-shaped field to target
        else:
            out["text"] = json.dumps(_sanitize_json_value(body))
    params = out.get("params")
    if isinstance(params, list):
        out["params"] = [
            {**p, "value": _REDACTED} if isinstance(p, dict) and _is_sensitive_query_param(p.get("name", "")) else p
            for p in params
        ]
    return out


def _sanitize_json_value(value: Any) -> Any:
    """Recursively redact dict keys that look like credentials, anywhere
    in a JSON request/response body — not just at the top level."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and (_is_sensitive_header(k) or _is_sensitive_query_param(k)
                                        or any(s in k.lower() for s in _SENSITIVE_COOKIE_LIKE)):
                out[k] = _REDACTED
            else:
                out[k] = _sanitize_json_value(v)
        return out
    if isinstance(value, list):
        return [_sanitize_json_value(v) for v in value]
    return value


def sanitize_har(har: dict[str, Any]) -> dict[str, Any]:
    """Returns a new HAR dict with cookies, auth/CSRF headers, bearer
    tokens, and known tracking/session query params redacted from every
    entry. Structure and non-sensitive fields (URL, method, status,
    content-type, response bodies with credential fields redacted) are
    preserved — this is redaction, not summarization."""
    log = har.get("log")
    if not isinstance(log, dict) or "entries" not in log:
        raise ValueError("not a HAR file: missing log.entries")
    entries = log.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("not a HAR file: missing log.entries")

    sanitized_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        e = dict(entry)
        req = dict(e.get("request", {}))
        resp = dict(e.get("response", {}))

        req["headers"] = _sanitize_headers(req.get("headers"))
        req["cookies"] = []  # cookies carry session identity by definition — never retained
        req["queryString"] = _sanitize_query_string(req.get("queryString"))
        if "postData" in req:
            req["postData"] = _sanitize_post_data(req["postData"])

        resp["headers"] = _sanitize_headers(resp.get("headers"))
        resp["cookies"] = []
        content = resp.get("content")
        if isinstance(content, dict) and isinstance(content.get("text"), str):
            new_content = dict(content)
            try:
                body = json.loads(content["text"])
            except (json.JSONDecodeError, ValueError):
                pass  # non-JSON body (HTML/binary) — left as-is
            else:
                new_content["text"] = json.dumps(_sanitize_json_value(body))
            resp["content"] = new_content

        e["request"] = req
        e["response"] = resp
        sanitized_entries.append(e)

    return {"log": {**har.get("log", {}), "entries": sanitized_entries}}
