# OEM Radar — Strategic Roadmap toward 2027

**Stage 11 update (2026-08-08):** The single most consequential change
since this roadmap was written: OEM Radar now has a second real subsystem
alongside the `SourceEngine`/`NormalizedProduct` pipeline —
`EvidenceSource` (`docs/EVIDENCE_ARCHITECTURE.md`), built after Lenovo
(PSREF) and HP independently confirmed real, enumerable, official
product-taxonomy APIs outside their blocked/JS-hydrated storefronts
(`docs/ALTERNATE_SOURCE_MATRIX.md`). This is not a sixth engine and does
not change the 5-engine/21-source counts anywhere else in this document —
it is a parallel concept for facts that aren't full product entities
(identity + status, no price, no confirmed specs). One real
implementation exists (`evidence_sources/lenovo_psref/`), proven against
live data (1,544 real items, real dedup behavior on repeat). The
project's next highest-leverage lever is now split three ways, all
already identified with exact next actions: a human DevTools session on
`psref.lenovo.com` and ASUS (`docs/OWNER_PROBE_BACKLOG.md`), and a second
real `EvidenceSource` for HP. None of these are collector-count questions.

**Stage 9 update (2026-08-07):** The Stage 8 addendum below predicted a
"Stage 9-scope exercise" would properly rewrite this document with a full
six-month lens. That didn't happen, and saying why is more useful than
silently deferring again: Stage 9's actual scope turned out to be the
*decision layer* (reconnaissance intelligence, discovery quality scoring,
economics), not new OEM strategy — see `docs/STAGE9.md`. The
near-term planning question this roadmap exists to answer is now better
served by two Stage 9 documents that are current rather than a rewrite of
this one that would immediately start decaying: `docs/OEM_ATLAS.md`
(every OEM, one table, current as of Stage 9) and
`docs/STAGE10_PROPOSAL.md` (the argued "what's actually worth doing next"
case, superseding this document's own "highest-leverage engines still
missing" section below — that section is now historical; #1, Samsung, is
done, and #2's Lenovo/ASUS/enterprise-API question is the subject of
`docs/STAGE10_PROPOSAL.md`'s Recommendation 1, argued with fresh Stage 9
evidence rather than repeated here). This document's "what should never
be built" section remains current and load-bearing — nothing in Stage 9
weakened any of those constraints.

**Stage 8 update (2026-08-07):** This roadmap's own closing line said "the
roadmap should get rewritten when [the current highest-leverage answer]
changes, not extended." It changed — Samsung is now enabled, via a real
`category_jsonld` engine, exactly the path §"Highest-leverage engines still
missing" #1 predicted. This is a dated addendum, not the promised rewrite
(that's a Stage 9-scope exercise, done properly with the full six-month
lens this document argues for) — but the facts below need correcting now,
not left stale for the next reader:

- Samsung: **done**, not pending. See `docs/STAGE8.md` and
  `docs/OEM_ECOSYSTEM_MAP.md`.
- Lenovo turned out to be *also* real-data-compatible with the same engine
  — and deliberately not enabled, on a new principle this roadmap didn't
  yet name explicitly: **this project will not spoof a browser identity to
  defeat UA-based bot detection**, even where no rendering/Playwright is
  involved. That belongs in "what should never be built" below,
  permanently, alongside the existing Playwright-as-default-fallback ban.
- The new **current answer** to "where does the next unit of engineering
  effort produce the most newly-understood OEM ecosystem": the enterprise
  public-API question (§"highest-leverage engines still missing" #2) is now
  the most load-bearing open item — Stage 8 checked Lenovo, ASUS, Kontron,
  OnLogic and found real internal APIs (Lenovo) or JS-hydration (ASUS/
  Kontron/OnLogic) but zero public catalog APIs. Still unresolved, still
  the single highest-leverage question on the table.
- Axiomtek is a new, honestly-graded data point for "highest-leverage
  engines still missing" #3's Magento/Adobe-Commerce question: real
  Product JSON-LD confirmed to exist on that general class of platform, but
  at a coverage rate (1-of-8 sampled pages) too sparse to trust — a
  different failure mode than "doesn't exist," worth remembering the next
  time a similarly-templated industrial vendor gets probed.

The rest of this document is Stage 7 text, preserved as written.

---

**Written Stage 7 (2026-08-07).** Not a backlog. A backlog says what to add
next; this says where the platform's leverage actually is, what would
change how much it understands versus how many things it collects, and
what to deliberately refuse to build even if asked. Read
`docs/ENTERPRISE_OEM_ARCHITECTURE.md` first for the mechanics this roadmap
assumes; read `docs/OEM_PLATFORM_MATRIX.md` for the evidence it's built on.

## Where the platform actually is

20 enabled sources, 4 engines (3 reusable + 1 deliberately isolated),
242→316 tests across Stages 5-7 without a single fabricated fixture or
speculative `enabled: true`. The thing worth naming plainly: **every stage
so far has found more real signal than it enabled.** Samsung has real,
confirmed, price-bearing product data sitting unclaimed right now — not
because it's hard, but because claiming it responsibly (a real discovery
mechanism, not a rushed one) takes more than a probe run. That gap between
"confirmed reachable" and "actually collecting" is the platform's honest
current bottleneck, not engine count.

## If we had six more months, what would OEM Radar become?

Not "monitors every PC OEM." That's not achievable and isn't the right
goal — Lenovo and MSI are confirmed hard-blocked, and no amount of
engineering changes that without crossing a line the project has correctly
refused to cross (browser automation as a first resort). The achievable,
valuable six-month version looks like:

1. **Every OEM with a genuine static/API surface, collected.** That's a
   closed, findable set — Stage 5-7 already mapped most of it. Finishing
   the `NEEDS_OWNER_PROBE` backlog (roughly 15 candidates), building the
   Samsung discovery strategy, and deep-checking the Stage 7 WooCommerce
   spillover (Axiomtek, Qotom, BOXX, Velocity Micro) would plausibly reach
   30-40 enabled sources without a single new engine.
2. **A fifth engine, if — and only if — the enterprise tier's actual shape
   clarifies.** ASUS proved one enterprise platform requires JS execution.
   It did not prove all of them do. If, in the next probing round, three
   or more mainstream OEMs turn out to expose a real public GraphQL/REST
   catalog API their own frontend calls (the investigation Stage 7
   explicitly deferred, not skipped), that's a legitimate fifth engine —
   probably `graphql_catalog` or similar. If instead three or more turn
   out to genuinely require rendering, that's the evidence base a written
   Playwright justification would need — and even then, scoped to exactly
   those confirmed platforms, not adopted platform-wide.
3. **A metrics-informed prioritization loop, not a recon-then-forget
   cycle.** `oem-radar coverage` (Stage 7) is the seed of this — the
   six-month version tracks fixture coverage and signal quality *by
   engine*, so "which engine's OEMs produce the most HIT-rated alerts per
   crawl" becomes an answerable question, not a guess. That answer should
   directly inform which recon batch gets run next.
4. **NOT a bigger platform surface area.** No new store types (dashboard,
   scheduler, database) — those are solved problems for this project's
   actual scale, and solving them "better" would be effort spent away from
   the mission. See "what should never be built," below.

## Highest-leverage engines still missing

Ranked by evidence quality, not aspiration:

1. **A Samsung-specific discovery strategy** (not really a new *engine* —
   `sitemap_jsonld`'s parsing already works; it needs a category-page link
   crawler as an alternative discovery strategy when no sitemap exists).
   This is the single highest-confidence next investment in the entire
   platform: data access is proven, only bulk discovery is missing.
2. **A public-API investigation for the enterprise tier** (ASUS/HP/Acer/
   Samsung-adjacent, potentially Lenovo/MSI if their block turns out to be
   IP-reputation-based rather than universal). Not an engine yet — a
   probe-level investigation (check for `/api/`, `/graphql`, XHR-visible
   endpoints referenced in page JS) that could *become* the evidence base
   for a `graphql_catalog` engine if 3+ OEMs confirm.
3. **Magento/Adobe Commerce** — the probe now detects these platforms
   (Stage 7 Phase 4) but zero OEMs have been product-page-verified yet.
   Unknown leverage until that verification happens; flagged here because
   several boutique/workstation builders (BOXX, Velocity Micro showed
   `static_jsonld` guesses that could plausibly be Magento underneath) are
   worth a dedicated pass.
4. **NOT WooCommerce v2/expansion** — 3 real OEMs is enough to prove the
   engine, and the next WooCommerce candidates found (Protectli, Puget
   Systems) turned out to have the theme but not the API. This family's
   leverage is probably close to fully realized already; don't over-invest
   chasing a 4th/5th WooCommerce OEM at the expense of higher-leverage work
   above.

## OEM ecosystems that remain largely inaccessible

Named honestly, not softened:

- **The mainstream global brand tier as a whole** (Lenovo, MSI confirmed
  blocked; ASUS confirmed JS-required; Acer/HP genuinely unknown). Even
  in the optimistic six-month scenario, this tier stays partially
  inaccessible — Lenovo/MSI specifically, unless their blocking posture
  changes on its own or a legitimate API surface is found that this
  project hasn't looked for yet.
- **Configurator-driven boutique/gaming builders without JSON-LD**
  (Eurocom, Falcon Northwest, ASRock Industrial). Real, well-organized
  catalogs, zero structured data, custom pricing calculators. These would
  need bespoke per-vendor parsers — individually justifiable given high
  editorial fit (Eurocom/Falcon Northwest especially), but each one is a
  standalone investment, not part of a reusable-engine story. Worth
  revisiting as isolated, deliberately-scoped exceptions (like `dell`) if
  the editorial case is strong enough — not worth generalizing.
- **Industrial/embedded system vendors** (Advantech, Neousys, Winmate,
  Portwell) — mostly unresolved from network issues in this sandbox, but
  even where reachable, likely to be B2B-quote-driven catalogs with weak
  public pricing data (the pattern already seen at NovaCustom/SimplyNUC).
  Lower expected data richness even when access isn't the blocker.

## Architectural debt worth paying down

In priority order, with the reasoning for the order:

1. **`crawler_runs` has no wall-clock duration column.** Small, cheap,
   unblocks an honest "average runtime" metric that `oem-radar coverage`
   currently and correctly refuses to fabricate. Worth doing specifically
   *because* the alternative (leaving a metrics gap silently unfilled) is
   worse than a small schema addition (schema v6, one column,
   `ALTER TABLE crawler_runs ADD COLUMN duration_s REAL`).
2. **The per-domain serial fetcher**, flagged as far back as the original
   HANDOFF.md and never addressed. At 20 sources it's a non-issue; at 40+
   it will start to matter (one slow/hanging domain delaying every source
   queued behind it). Not urgent today — this is a "notice when it starts
   to hurt" item, not a "fix now" item. Fixing it before it hurts would be
   solving a problem the platform doesn't have yet.
3. **`docs/HANDOFF.md`'s continued existence as a live-looking document.**
   It's been superseded since Stage 5 and correctly banner-marked, but it
   still sits at the same path as `CURRENT_STATUS.md` and could mislead a
   future session that doesn't read the banner carefully. Low cost to
   archive (move to `docs/archive/` or similar) whenever someone's next
   pass through the docs tree happens to be there anyway — not worth a
   dedicated stage.
4. **NOT the `support_status:` comment convention.** `oem-radar coverage`
   correctly reports files without it as `UNDOCUMENTED` rather than
   guessing. Retrofitting all 10 undocumented original descriptors with
   the comment is a nice-to-have, not debt — the metrics command already
   degrades gracefully without it, which is the actual architectural
   requirement.

## What should never be built, and why

These aren't a maybes-later list. Building any of them would trade a
maintained, understandable platform for a fragile, impressive-sounding one
— the exact failure mode this project has been explicitly designed against
since `docs/ARCHITECTURE.md`'s original ADRs.

- **A general-purpose headless-browser rendering layer.** Not "don't add
  Playwright yet" — don't add it as a *default fallback* ever, even after
  ASUS's confirmed JS requirement. The moment "just render it" becomes an
  available escape hatch, every future engine decision degrades: instead
  of proving a platform has real static/API access (the discipline that
  found SimplyNUC, Khadas, GEEKOM, NovaCustom, Pine64, and Samsung), the
  path of least resistance becomes "couldn't find it statically, render
  it." That would quietly turn OEM Radar's core competency (deterministic,
  fixture-testable, offline-replayable collection) into an operationally
  fragile scraping farm — the exact starting point this project has spent
  three stages proving it isn't. If a specific, narrow, written
  justification for rendering exactly one confirmed-JS-required platform
  is ever approved, it must stay scoped to that platform, not become
  infrastructure other engines can casually reach for.
- **A vendor-specific engine per mainstream brand "just to get the data."**
  The `dell` engine is the one sanctioned exception, and its existence is
  justified by a structural difference (`ItemList`-in-page vs.
  per-URL-detail-page), not by "Dell was hard to generalize." Adding a
  `lenovo_engine`, `hp_engine`, etc. as one-off scrapers the moment a
  platform resists the existing engines would rebuild exactly the
  "collection of scrapers" problem Stage 6-7 exist to move past. If a new
  platform genuinely needs bespoke code, it needs the same bar `dell`
  cleared: a real structural reason, documented, and ideally with an eye
  toward whether a second OEM might share that structure later.
- **Automatic rule/suppression application from feedback analytics.**
  Already an explicit standing rule (`docs/FEEDBACK_SYSTEM.md`, "rule
  suggestions never auto-activate") — restated here because it's exactly
  the kind of feature that *sounds* like natural platform maturity
  ("the system learns and adapts!") while actually removing the human
  editorial judgment that makes the alerts trustworthy in the first place.
  Suggestions inform; humans decide. That boundary should outlive every
  engine this platform will ever add.
- **A second persistence layer, cache tier, or message queue "for scale."**
  SQLite has handled every stage so far including 534 real change events
  and 28 real crawler runs without strain, and the architecture doc's own
  scale check (§Scale check in `ENTERPRISE_OEM_ARCHITECTURE.md`) puts the
  first genuine infrastructure pressure point at 40+ sources, and even
  then it's a fetcher concurrency question, not a storage one. Adding
  Postgres/Redis/a queue now would be solving next year's hypothetical
  problem with this year's real complexity budget.
- **Identity-spoofing to defeat bot/UA detection** (Stage 8, added after a
  real case: Lenovo's `/buy/` landing pages serve real, engine-compatible
  catalog data to a browser-shaped User-Agent and HTTP 403 to OEM Radar's
  own honest, declared crawler UA). No rendering is involved — this isn't
  the Playwright question — but the principle is the same one degree
  removed: the moment "just pretend to be a browser" becomes an available
  escape hatch for a blocked source, every future blocked-source decision
  degrades the same way the Playwright ban protects against. A source that
  only serves real data to a spoofed identity stays disabled, permanently,
  same as one that's fully bot-walled — not a special case, a documented
  dead end (see `config/oems/lenovo.yaml`).
- **A configuration DSL, plugin marketplace, or engine-selection AI.**
  Every engine this project has built came from a human reading real
  probe evidence and making a judgment call about a 3-OEM bar. That
  judgment is cheap to exercise (a probe run and a docs read) and
  expensive to encode into a rules engine that would inevitably be wrong
  about the next genuinely weird platform (Khadas's `Offers`/`Availability`
  capitalization, GEEKOM's zero-minor-unit pricing, Pine64's
  "keyboard"-in-a-real-laptop-name — none of these were predictable in
  advance). Keep the judgment human; keep the mechanism simple.

## The measure of success

Not collector count. Not engine count. The question worth asking at the
start of every future stage is the one this roadmap tries to model
answering: **given everything already probed, where does the next unit of
engineering effort produce the most newly-understood OEM ecosystem, and
where would it just add more scrapers to the pile?** Samsung is the
current answer. Six months from now, something else will be — the roadmap
should get rewritten when that's true, not extended.
