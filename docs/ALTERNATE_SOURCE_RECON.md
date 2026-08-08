# Alternate Official Source Reconnaissance

**Written Stage 10 (2026-08-07).** Investigates whether official
public surfaces other than a blocked/inaccessible storefront (support
portals, spec databases, driver/BIOS indexes, documentation) expose
enough real, enumerable, identity-rich signal to justify building an
`EvidenceSource` subsystem. Every finding below is a real live fetch made
with this project's honest, declared crawler UA
(`OEMRadar/0.1 (product-intelligence; respectful crawler; contact@x8.design)`)
— no browser spoofing, no JS execution. Where a JavaScript bundle's
*text* was read to find an API path, that is static analysis of a text
file (the same class of action as reading any other fetched document) —
not executing it.

## The evidence-system trigger (defined before evaluating results)

Per `docs/STAGE10_PROPOSAL.md`'s spirit and this stage's own instruction:
implementation is justified only if, across the OEMs investigated below,
either:

- **2 OEMs** have useful, enumerable alternate-source data, **or**
- **1 OEM + 3 materially distinct evidence types** (e.g. support record,
  BIOS, manual) with stable enough identifiers to correlate safely.

If neither bar is met: stop at reconnaissance and documentation. That is
a valid, successful Stage 10 result — see the verdict at the bottom.

## Lenovo

**Priority target — the storefront question here is permanently closed
by policy** (`docs/OEM_ATLAS.md` §2), so any independent signal is purely
upside.

| Surface | URL | Status | Finding |
|---|---|---|---|
| PSREF (Product Specifications Reference) | `psref.lenovo.com` | **200, reachable** | Real, but a client-rendered SPA (Vite/Vue bundle) — no static HTML product data |
| PSREF's own API (found via reading its published JS bundle text) | `psref.lenovo.com/api/ph/ProductCategoryTree` | **200, `application/json`, no auth required** | **Confirmed real, enumerable catalog**: 1,544 real products, `ProductID` + `ProductKey` + `ProductName` per entry, across 9 top-level classifications and 134 series (ThinkPad, IdeaPad, Legion, Yoga, etc.) |
| PSREF compare/search endpoints (same bundle) | `/api/product/Compare/ProductCompare`, `/api/search/.../Suggest` | 403/405 on unguessed request shapes | Endpoints exist (confirmed by the non-404 status) but require a request shape this recon didn't reverse-engineer from static analysis alone — a DevTools capture (`docs/OWNER_DEVTOOLS_GUIDE.md`) would resolve this quickly if pursued |
| Lenovo Support | `support.lenovo.com` | **403** | Same bot-gating signature as the main storefront |
| pcsupport.lenovo.com | — | **403** | Same signature |
| download.lenovo.com | — | **403** | Same signature |
| newsroom.lenovo.com | — | DNS failure | Wrong/stale hostname, not investigated further (needs the real current URL, same class of finding as Stage 8's Insurgo) |

**Assessment**: one strong, confirmed, real evidence type — a product/
spec database (`PRODUCT_DATABASE` in the taxonomy below) — reachable
without any policy violation. Three other candidate evidence types
(support docs, drivers, BIOS) are all blocked by the *same* UA-gating
this project already declined to spoof past for the storefront (Stage
8-9). This does not meet the "1 OEM + 3 types" bar — it's 1 OEM + 1
confirmed type, with 3 more blocked the same way as the storefront
itself, not confirmed-and-different.

## HP

| Surface | URL | Status | Finding |
|---|---|---|---|
| Support root | `support.hp.com/us-en/` | **200** | Reachable, but every path tried (`/drivers`, `/product/details`, `/search?q=laptop`) returned an **identical 7,066-byte page** — a generic client-side-routed shell, not per-page content. No `__NEXT_DATA__`/`__NUXT__` marker found, but the identical-shell behavior across distinct paths is the same practical blocker (real content loads after JS runs, this project cannot see it) |
| QuickSpecs (legacy subdomain) | `h20195.www2.hp.com` | TLS failure | `CERTIFICATE_VERIFY_FAILED` — broken infra on HP's end, the same class of finding as Stage 8's Portwell, not a bot block |

**Assessment**: no usable structured surface found. Both failure modes
are real and distinct from each other, but neither produces data.

## ASUS

Investigated alongside the Track 2 DevTools prep, since ASUS is already
the highest-priority mainstream OEM in the atlas.

| Surface | URL | Status | Finding |
|---|---|---|---|
| Support root | `asus.com/support/` | **200** | Real page, but its only JSON-LD is `BreadcrumbList`/`Organization` schema — no product/driver data |
| Download Center | `asus.com/support/Download-Center/` | **200** | Reachable; does not show the `__NUXT__` marker the storefront shows on this particular shell page — genuinely different from the storefront's rendering path, but not yet confirmed to expose real data without JS. This is exactly what Track 2's DevTools procedure is for, not more blind static probing |

**Assessment**: inconclusive, not negative. This is the one surface
worth a real DevTools look in the same session as the ASUS storefront
investigation (`docs/OWNER_DEVTOOLS_GUIDE.md`), since it already looks
structurally different from the blocked/JS-hydrated storefront.

## MSI

| Surface | URL | Status | Finding |
|---|---|---|---|
| Support root | `msi.com/support` | **403** | Same signature as the storefront |

## Acer

| Surface | URL | Status | Finding |
|---|---|---|---|
| Support root | `acer.com/us-en/support` | Read-timeout | Same silent-stall signature documented for the Acer storefront across three stages (`docs/OEM_ATLAS.md` §5) |

## Taxonomy used (kept deliberately narrow, per instructions)

Evidence kinds actually observed or plausible from what was found this
stage: `PRODUCT_DATABASE` (Lenovo PSREF), `SUPPORT_ENTRY`,
`FIRMWARE`/`DRIVER`/`MANUAL` (none confirmed reachable yet for any OEM).
No enum was created in code — this is prose taxonomy only, since nothing
was implemented (see verdict below).

## Verdict: evidence bar not met

- **2-OEMs bar**: not met. Only Lenovo produced a confirmed, enumerable,
  real data surface (PSREF). HP, ASUS, MSI, and Acer's alternate surfaces
  are each either blocked, JS-shell-gated, or (ASUS) merely inconclusive
  pending human DevTools work.
- **1-OEM-plus-3-types bar**: not met. Lenovo has exactly one confirmed
  type (`PRODUCT_DATABASE`). The other three plausible Lenovo evidence
  surfaces (support, drivers, BIOS) are blocked by the same UA-gating
  already declined as a spoofing target — they are not confirmed-and-
  distinct, they are the same closed door checked three more times.

**Decision, per the pre-committed trigger: do not build `EvidenceSource`
this stage.** This is a real, valid Stage 10 result, not a shortfall —
see `docs/STAGE10.md`.

## What IS worth carrying forward

Lenovo PSREF's `/api/ph/ProductCategoryTree` is a genuinely striking
finding: a real, unauthenticated, 1,544-product catalog with stable
identifiers, reachable without violating any policy, sitting completely
outside the blocked storefront. It does not meet this stage's bar alone
(one OEM, one evidence type), but it is the single most promising lead
in this document. Two concrete next steps, neither of which is
"build Evidence Fusion now":

1. A human DevTools session on `psref.lenovo.com` (using
   `docs/OWNER_DEVTOOLS_GUIDE.md`'s exact procedure) would likely reveal
   the correct request shape for the compare/search endpoints that
   returned 403/405 on this stage's guessed payloads — potentially
   turning "1,544 products, taxonomy only" into "1,544 products with
   full specs."
2. If a second OEM's support/spec surface is later found to be similarly
   open (this stage did not find one — HP/ASUS/MSI/Acer's surfaces were
   each blocked, shell-gated, or unconfirmed), that would independently
   satisfy the 2-OEM bar without Lenovo needing a second evidence type at
   all.
