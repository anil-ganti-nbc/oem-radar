# Gzip Sitemap Support — Stage 10 Decision

**Written Stage 10 (2026-08-07).** `docs/ENTERPRISE_OEM_ARCHITECTURE.md`
§15 has flagged since Stage 5 that `HttpFetcher`/`FetchedDocument` model
response bodies as text, with no explicit gzip-compressed-sitemap
(`sitemap.xml.gz`) decompression support. Stage 10 was asked to determine
whether any currently valuable/reachable candidate would actually become
collectable if this were implemented, before building it speculatively.

## Search

Grepped every `docs/*.md` for prior mentions of gzip/`.gz` sitemaps. The
only real OEM ever cited against this gap is **Dynabook** (Stage 5),
and `docs/OEM_ATLAS.md` §9 records Dynabook's actual disposition: "sitemap
resolves but content is Windows-8.1-era, abandoned" — a *content*
problem, not a compression problem. Dynabook would not become
collectable even with gzip support; its catalog is stale regardless of
how the sitemap is served.

No other OEM in `docs/OEM_ATLAS.md` (enabled, confirmed-real,
confirmed-blocked, inconclusive, or undetermined) is recorded as blocked
specifically by sitemap compression.

## Decision

**Do not implement gzip sitemap support this stage.** The capability has
no real current consumer — the one OEM ever cited against it doesn't
actually need it (a different, unrelated problem blocks it), and no
newly-probed OEM this stage (Stage 9 or 10) surfaced a `.gz` sitemap as
an active blocker. This is exactly the "capability must be justified by
a real consumer" bar this project applies everywhere else (Stage 6-9);
building it now would be exactly the kind of speculative capability this
project's own architecture principles argue against.

Remains deferred, tracked in `docs/ENTERPRISE_OEM_ARCHITECTURE.md` §15,
until a real OEM is found where this is the actual, sole blocker.
