"""Vendored Reddit Atom transport v1. No state or editorial policy.

Canonical copy: oem-radar/src/clank_reddit. Consumers vendor identical bytes;
the owning Clank supplies HTTP transport, persistence, and interpretation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

VERSION = "1.0.1"
ATOM = "{http://www.w3.org/2005/Atom}"


class RedditUnavailable(ValueError):
    """Transport/parser failure; callers must not record a healthy empty run."""


@dataclass(frozen=True)
class Submission:
    external_id: str
    subreddit: str
    permalink: str
    title: str
    body: str
    author: str | None
    published_at: str | None
    links: tuple[str, ...]
    raw_xml: str

    @property
    def related_urls(self) -> tuple[str, ...]:
        # Relationship hints only. Never use these as observation identity.
        return tuple(dict.fromkeys(link_key(u) for u in self.links))

    def evidence(self) -> dict[str, Any]:
        return {
            "transport_version": VERSION,
            "submission_id": self.external_id,
            "subreddit": self.subreddit,
            "discovery_url": self.permalink,
            "source_published_at": self.published_at,
            "author": self.author,
            "outbound_links": list(self.links),
            "related_url_keys": list(self.related_urls),
            "original_source_url": None,
            "raw_xml": self.raw_xml,
            "raw_sha256": hashlib.sha256(self.raw_xml.encode()).hexdigest(),
        }


def feed_url(subreddit: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]{2,30}", subreddit):
        raise ValueError("Invalid subreddit name")
    return f"https://www.reddit.com/r/{subreddit}/new/.rss?limit=100"


def link_key(url: str) -> str:
    """Conservative relationship key: drop known tracking, preserve content query."""
    parts = urlsplit(url)
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), "")
    )


def _http_url(value: str) -> bool:
    try:
        p = urlsplit(value)
        return p.scheme in {"http", "https"} and bool(p.hostname) and not p.username
    except ValueError:
        return False


class _Content(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if _http_url(href) and href not in self.links:
                self.links.append(href)

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def parse_listing(body: str, subreddit: str) -> list[Submission]:
    feed_url(subreddit)  # validate before interpreting response data
    if (
        len(body.encode()) > 4_000_000
        or "<!DOCTYPE" in body.upper()
        or "<!ENTITY" in body.upper()
    ):
        raise RedditUnavailable("Unsupported or oversized Reddit feed")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise RedditUnavailable("Malformed Reddit Atom feed") from exc
    if root.tag != ATOM + "feed":
        raise RedditUnavailable("Response is not a Reddit Atom feed")
    entries = root.findall(ATOM + "entry")
    if not entries:
        raise RedditUnavailable("Suspicious empty Reddit listing")
    if len(entries) > 100:
        raise RedditUnavailable("Reddit listing exceeds bounded page size")
    result: list[Submission] = []
    seen: set[str] = set()
    for entry in entries:
        eid = (entry.findtext(ATOM + "id") or "").strip()
        permalink = next(
            (
                e.get("href", "")
                for e in entry.findall(ATOM + "link")
                if e.get("rel", "alternate") == "alternate"
            ),
            "",
        )
        p = urlsplit(permalink)
        match = re.fullmatch(r"/r/([^/]+)/comments/([a-z0-9]+)/[^/]*/?", p.path, re.I)
        if (
            p.hostname not in {"reddit.com", "www.reddit.com", "old.reddit.com"}
            or p.scheme != "https"
            or not match
            or match[1].lower() != subreddit.lower()
        ):
            raise RedditUnavailable("Missing or mismatched Reddit submission permalink")
        expected = "t3_" + match[2].lower()
        if eid and eid != expected:
            raise RedditUnavailable("Conflicting Reddit submission identity")
        eid = expected
        if eid in seen:
            continue
        seen.add(eid)
        title = (entry.findtext(ATOM + "title") or "").strip()
        # Individual deleted/removed or incomplete entries must not take down a
        # bounded listing that still contains usable evidence.  Structural feed
        # and identity/scope failures above remain fail-closed.
        if not title or title.casefold() in {"[deleted]", "[removed]"}:
            continue
        published = entry.findtext(ATOM + "published")
        if published:
            try:
                parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("missing timezone")
                published = parsed.astimezone(timezone.utc).isoformat()
            except ValueError as exc:
                raise RedditUnavailable("Invalid Reddit publication time") from exc
        content = _Content()
        content.feed(entry.findtext(ATOM + "content") or "")
        links = tuple(
            u
            for u in content.links
            if u != permalink and not urlsplit(u).path.startswith("/user/")
        )
        result.append(
            Submission(
                eid,
                subreddit,
                permalink,
                title,
                " ".join(content.text).strip(),
                entry.findtext(ATOM + "author/" + ATOM + "name"),
                published,
                links,
                ET.tostring(entry, encoding="unicode"),
            )
        )
    if not result:
        raise RedditUnavailable("Reddit listing contains no usable submissions")
    return result


def retrieve(subreddit: str, get: Callable[[str], tuple[int, str]]) -> list[Submission]:
    """Fetch one bounded newest-first page. Caller owns timeouts/backoff/auth.

    No cursor short-circuit: overlapping/reordered pages are reconciled against
    durable domain state, so a sticky or reordered entry cannot hide new posts.
    No outbound article fetches, redirects, scheduling, retries, or persistence.
    """
    status, body = get(feed_url(subreddit))
    if status != 200:
        raise RedditUnavailable(f"Reddit HTTP {status}; intake not completed")
    return parse_listing(body, subreddit)
