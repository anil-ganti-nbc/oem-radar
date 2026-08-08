# Discovery Architecture

**Status: design doc, written Stage 8 (2026-08-07).** Stage 8 Phase 6 asked
whether discovery should become a first-class plugin system, separate from
engines, the way `SourceEngine` implementations are separate from `Notifier`
implementations. This document answers that with evidence from every
discovery mechanism the platform has actually built or evaluated through
Stage 8, and the answer is **not yet** — with the specific, falsifiable
condition that would change that answer.

## What "discovery" has actually meant, in practice

Every engine's `discover()` picks from a small, closed set of real-world
shapes. Across `shopify`, `dell`, `sitemap_jsonld`, `woocommerce_store_api`,
and the new `category_jsonld` (Stage 8), discovery has only ever been one
of:

| Mechanism | Used by | What varies per-OEM |
|---|---|---|
| Bulk JSON endpoint (`/products.json`) | `shopify` | Just the base URL |
| Sitemap + per-page fetch | `sitemap_jsonld` | Sitemap URL, `url_include_pattern`/`url_exclude_pattern` |
| Paginated REST API | `woocommerce_store_api` | Base URL, `category_include`/`category_exclude` |
| Static category/listing HTML page | `dell`, `category_jsonld` | Which category URL(s) to fetch |

Every one of these is **config, not code**, once the engine exists. Adding
OEM #29 has never required writing a new discovery mechanism — it has
required picking which of the four rows above applies, then supplying URLs
and scoping regex. This is the load-bearing fact behind this document's
conclusion.

## The candidate list from Stage 8 Phase 6

The prompt for this stage listed eight discovery *ideas* to evaluate:
sitemap, robots, category crawl, JSON feed, Store API, GraphQL, support
index, search API, RSS. Going through them against real Stage 8 evidence:

- **Sitemap** — already `sitemap_jsonld`'s mechanism. Solved.
- **Robots.txt** — already consulted opportunistically inside probing (Stage
  7/8 checked it for Samsung, System76, TUXEDO) to locate a sitemap
  reference; it has never itself been the *source* of product URLs, only a
  pointer to one. Not a distinct discovery strategy — a lookup step inside
  the sitemap strategy.
- **Category crawl** — this is exactly what `category_jsonld` is (Stage 8).
  Already built, already generalized across two real shapes (Samsung's
  ItemList-with-offers, Lenovo's ItemList-navigation-plus-sibling-Products).
  Solved.
- **JSON feed / RSS** — investigated opportunistically this stage (OnLogic's
  Next.js sitemap, Winmate's sitemap) and found real but did not turn up a
  platform where the *feed itself* carried product data (every real feed
  found was a plain URL list, i.e. a sitemap in a different XML dialect).
  No confirmed real candidate yet. Not built.
- **Store API** — already `woocommerce_store_api`'s mechanism. Solved.
- **GraphQL** — actively investigated this stage (Lenovo, ASUS, Samsung,
  Kontron, OnLogic). Zero platforms confirmed to expose a public,
  unauthenticated GraphQL catalog endpoint their own frontend calls without
  also requiring JS execution to discover the query shape. Still an open
  question, not a confirmed strategy — see `docs/OEM_ECOSYSTEM_MAP.md` and
  the roadmap's "highest-leverage engines still missing" section.
- **Support index / search API** — investigated for Lenovo (found only
  back-office APIs: loyalty points, delivery estimates, price-preview — not
  a catalog surface) and OnLogic/Kontron (Next.js/Nuxt apps expose no public
  search API visible without executing their JS bundles). No confirmed real
  candidate.

Net result: of eight candidate discovery ideas, four map onto mechanisms
already built (sitemap, category crawl, Store API, and robots.txt-as-a-
lookup-step), and four remain unconfirmed after a real attempt to find
them (JSON feed, GraphQL, support index, search API) — not because they
were untried, but because no real platform evidenced them this stage.

## Why not a first-class discovery plugin system

The proposal under consideration was: extract `discover()` into a separate,
independently-registered plugin interface (`discovery.register("sitemap")`,
etc.) that any engine could compose, decoupling "how to find product URLs"
from "how to parse a product page." `docs/PLUGIN_GUIDE.md` already gestures
at this ("Discovery strategies are separate registered classes") for the
`shopify` engine's `products_json`/`sitemap` pair — but that's the only
place it's actually happened, and even there it's two strategies *within
one engine*, not a shared cross-engine plugin.

The case *for* generalizing further would be: the same discovery mechanism
recurring across engines that otherwise parse differently. That hasn't
happened. Every discovery mechanism above is entangled with exactly one
engine's parsing contract:

- A sitemap's URLs feed `sitemap_jsonld`'s per-page JSON-LD parser — no
  other engine consumes a sitemap.
- A category page's `ItemList` feeds `category_jsonld`'s bulk-inline
  parser — `dell`'s conceptually-similar category-page parsing is
  deliberately *not* sharing code with it (see
  `docs/ENTERPRISE_OEM_ARCHITECTURE.md` §9 and this stage's Phase 9 review).
- The Store API's pagination feeds `woocommerce_store_api`'s specific
  minor-unit price parsing — no other engine calls that endpoint shape.

Extracting a plugin interface now would produce four plugins, each with
exactly one consumer — pure ceremony, the opposite of what a plugin system
is for. `docs/OEM_ROADMAP_2027.md` already names this failure mode
directly: *"A configuration DSL, plugin marketplace, or engine-selection
AI... Keep the judgment human; keep the mechanism simple."* A discovery
plugin registry with one implementation per slot is that DSL in miniature.

## The condition that would change this answer

If a **fifth** engine is ever justified (the roadmap's tracked candidates:
a confirmed public GraphQL catalog API, or Magento/Adobe Commerce
product-page verification) and that engine's natural discovery mechanism
turns out to be sitemap-based or category-crawl-based — i.e., the *same*
discovery mechanism as an existing engine, wrapping a *different* parse —
that is the trigger to extract that one mechanism into a shared,
engine-agnostic discovery step (e.g. a `sitemap_urls(fetcher, cfg) ->
list[str]` helper both engines' `discover()` call, analogous to how
`core/jsonld.py` and `core/textutil.py` already share pure parsing
mechanism without sharing policy). That would be extracting a second real
consumer of one mechanism — not inventing a speculative interface for a
population of one.

Until then: discovery stays exactly where it is, as a method on each
engine, config-driven per source. This is not a gap — it is the direct
consequence of every discovery investigation this stage actually running
into either "this maps onto a mechanism we already have" or "this doesn't
exist yet on any real platform we checked."

## Stage 9 re-check (2026-08-07)

Stage 9 asked the same question again, deliberately, before building
anything: "investigate whether discovery should become an independent
subsystem." The trigger condition above — a fifth engine whose discovery
mechanism duplicates an existing one wrapping a different parser — still
has not fired. No new engine was built this stage. Stage 9's actual
discovery work (`oem-radar probe`'s upgrade into an evidence-backed
reconnaissance report, the Discovery Quality Score, and the benchmark
suite — see `docs/STAGE9.md`) all operate *on top of* the existing
per-engine discovery methods; none of it required extracting discovery
into a separate registered plugin type. That is itself evidence for this
document's original conclusion: the leverage this stage found was in
making discovery *decisions* smarter (scoring, benchmarking, triage), not
in re-architecting how discovery *code* is organized. Those are different
problems, and only the first one turned out to be real work. The
extraction trigger stated above is unchanged and remains the thing to
watch for.
