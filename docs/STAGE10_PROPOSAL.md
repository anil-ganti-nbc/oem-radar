# Stage 10 Proposal

**Written Stage 9 (2026-08-07), as the closing deliverable Stage 9 asked
for.** This is a proposal, not a backlog: it argues for a specific,
narrow set of next moves, using evidence gathered this stage and prior
ones, and explicitly rules out several plausible-sounding alternatives.

## The thesis

Stage 9 was asked to make OEM Radar better at deciding what to build next
than a human eyeballing a list of OEMs. The honest result of doing that
work is a finding the project has not had to state this bluntly before:
**there are currently zero OEMs that are both (a) confirmed-real and
(b) blocked only on engineering effort.** Every remaining known-real
opportunity (Lenovo) is blocked by policy, not code. Every remaining
inconclusive enterprise OEM (ASUS, Acer, HP, MSI) is blocked on evidence
this project's automated tooling cannot generate from where it runs
today — not on a missing engine.

This is not a stall. It is what "the platform matured" actually looks
like, concretely, instead of as a slogan: Stage 5-8 exhausted the
category of problem that new engines and better discovery mechanisms can
solve. What's left sorts into three different categories, and Stage 10
should be organized around closing each on its own terms rather than
treating them as one undifferentiated "keep probing OEMs" backlog.

## Recommendation 1: a real devtools pass on ASUS

**Why ASUS specifically, not the other four Fortune-500 candidates:**
`docs/ENTERPRISE_OEM_ARCHITECTURE.md` §16 classified all five real-time
this stage. ASUS is the only one where the page is *not* blocked (HTTP
200, no bot markers) and *not* silently stalling (unlike Acer/HP) — it is
a fully reachable, JS-hydrated Nuxt application with zero server-rendered
product data. That is the single failure class in the whole atlas
(`docs/OEM_ATLAS.md` §5) where a human spending 30 minutes in browser
devtools, watching the Network tab while the laptops page loads, could
plausibly find a public `fetch()`/GraphQL call the frontend itself
issues — turning a "needs Playwright" dead end into a `category_jsonld`-
or GraphQL-shaped real discovery, with zero new engine code. This has
never actually been done in five stages of otherwise-thorough
reconnaissance. It is manual, it is cheap, and it is the highest expected
value per hour of any action available right now.

**What NOT to do**: do not build Playwright to render the page instead.
That is the shortcut this exact investigation exists to avoid — it would
solve ASUS specifically while leaving the actual open question (does a
public API exist) unanswered, and it violates a standing constraint this
project has held since Stage 5.

## Recommendation 2: resolve Axiomtek with a wider sample

**Why this and not a new industrial-computing engine:** Axiomtek is the
one candidate in `docs/OEM_ATLAS.md` §7 sitting in "confirmed real but
below the production bar" — real Product JSON-LD exists, verified on 1 of
8 sampled pages. That ratio is genuinely ambiguous: it could mean the
template only fires on ~12% of the real catalog (permanently below bar),
or it could mean an 8-page sample was simply unlucky. The fix costs
nothing architecturally — fetch 20-30 more real pages with the existing
probe tooling and recompute the ratio. This either promotes Axiomtek to
`category_jsonld`/`sitemap_jsonld`-eligible (config + fixtures only, per
`docs/PLUGIN_GUIDE.md`'s existing bar) or closes the question permanently
with real evidence instead of a stale "almost." No other industrial
candidate (Advantech, Neousys, Portwell, Kontron) is this close.

## Recommendation 3: give the three newest engines real production mileage

**Why this belongs in an engineering proposal at all:**
`docs/COLLECTOR_ECONOMICS.md` found something Stage 9's own economics
analysis wasn't originally looking for: `sitemap_jsonld`,
`woocommerce_store_api`, and `category_jsonld` have strong test/fixture
coverage (32, 27, and 25 dedicated tests respectively) but **zero rows**
in `data/radar.db`'s `crawler_runs` table — they have never actually
executed against a live network in this environment. `shopify` is the
only engine with enough real run history to say anything evidence-based
about signal density or failure modes in production. That is a real gap
in the project's own self-knowledge, not a cosmetic one: every future
Stage-9-style economics or benchmark analysis will keep being forced to
say "unmeasured" for 3 of 5 engines until this changes. The fix is
operational, not architectural — run `oem-radar run` against these
sources for real and let history accumulate. This is deliberately listed
as a recommendation rather than assumed to already be happening, because
the evidence (an empty table) says it currently is not.

## What this proposal explicitly does NOT recommend

- **A new engine.** No candidate has crossed the 3-confirmed bar since
  `category_jsonld` (Stage 8). Building one now would be exactly the
  "increase collector count for its own sake" failure mode Stage 8 and 9
  were both explicitly written to avoid.
- **A discovery plugin subsystem.** Re-checked this stage
  (`docs/DISCOVERY_ARCHITECTURE.md`'s Stage 9 addendum) — the extraction
  trigger still hasn't fired. Nothing found this stage changes that.
- **Playwright, for ASUS or anyone else.** See Recommendation 1 — the
  correct next step is cheaper and answers a more fundamental question
  first.
- **Any identity-spoofing workaround for Lenovo.** That door is closed by
  policy, not by missing engineering, and re-opening it was never on the
  table.
- **More automated re-probing of Acer/HP.** Three stages of identical
  silent-timeout symptoms (`docs/OEM_ATLAS.md` §5) is enough evidence
  that this project's current network path cannot resolve these two on
  its own; further automated attempts from the same environment would
  not produce new information.

## What success looks like after Stage 10

Not a higher collector count. Three closed questions: ASUS either has a
discoverable public API or doesn't (human-verified, not guessed);
Axiomtek is either enabled or permanently parked with a real wide-sample
ratio backing that call; and the next `docs/COLLECTOR_ECONOMICS.md`-style
analysis has real run history for all five engines instead of two. Every
one of these is cheaper, faster, and more honest than building anything
new.
