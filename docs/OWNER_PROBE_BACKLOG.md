# Owner Probe Backlog

**Written Stage 10 (2026-08-07).** Stage 9 concluded several OEMs are
blocked on "wrong door" evidence (a stale subdomain, wrong path, broken
TLS, intermittent 500s) rather than a real technical or policy wall — see
`docs/OEM_ATLAS.md` §8. Automated re-probing of the same stale URL
produces the same result every time; each entry below needs one specific
human action, not another crawl attempt.

| OEM | URL needed | Page type wanted | What to check | Command to run after |
|---|---|---|---|---|
| TUXEDO | Current real storefront/shop path (not the informational site probed so far) | A category or product listing page | Confirm the page lists real laptop models with prices, not just marketing copy | `oem-radar probe <url>` |
| Slimbook | Confirm `sitemap.xml` is stable (it returned HTTP 500 on retest, 200 once) | N/A — same URL, different moment | Whether the 500 recurs consistently or was transient | `oem-radar probe https://slimbook.es` |
| Insurgo | Current real shop subdomain (`shop.insurgo.ca` fails DNS entirely — likely renamed/moved) | A category or product listing page | Confirm DNS resolves and the page has real product data | `oem-radar probe <url>` |
| Supermicro Edge | Current real product-listing path (`/en/products/system/edge` 404s) | A category or product listing page | Confirm the corrected path returns real listings | `oem-radar probe <url>` |
| Advantech | Any real category/product page (no sitemap found at root, `/en/`, or via robots.txt) | A category or product listing page | Whether a sitemap exists at all, or discovery would need a category-page approach instead | `oem-radar probe <url>` |
| Neousys | Same as Advantech — no sitemap found anywhere checked | A category or product listing page | Same as Advantech | `oem-radar probe <url>` |
| Portwell | N/A — TLS certificate chain fails verification, a server-side infrastructure problem, not a URL problem | N/A | Whether Portwell's cert issue has been fixed (retry the same URL) | `oem-radar probe https://www.portwell.com` |

## DevTools reconnaissance (Stage 11 additions — different from the URL-fix rows above)

These two don't need a corrected URL — they need a human running
`docs/OWNER_DEVTOOLS_GUIDE.md`'s procedure. Status:
**`PENDING_OWNER_ACTION`** for both; no automated re-probing was done
this stage since Stage 9/10/11 already established this class of gap
can't be closed by another script.

| Target | Why | What to capture | Command afterward |
|---|---|---|---|
| ASUS storefront (`asus.com/us/laptops/`) | Reachable, Nuxt-hydrated, zero server-rendered product data (`docs/OEM_ATLAS.md` §5) | A public `fetch()`/GraphQL request the frontend makes while browsing laptops | `oem-radar sanitize-har <file>`, then hand the sanitized output to a developer |
| Lenovo PSREF (`psref.lenovo.com/Product/...`) | Real catalog-level API confirmed (`docs/PSREF_RECON.md`), but the per-product spec/MTM endpoint could not be found via static analysis — 9 real guesses, all 404 | The request PSREF's own product-detail page makes when it loads CPU/RAM/MTM data | `oem-radar sanitize-har <file>`, then hand the sanitized output to a developer — this one specifically could resolve `docs/EVIDENCE_ARCHITECTURE.md`'s open "does PSREF ever expose full product entities" question |

## What NOT to do with this list

Do not re-run automated probes against the same known-stale URLs hoping
for a different result — every entry above already got that treatment in
Stage 8/9 and produced the same real, evidenced failure each time. The
next useful signal for any of these can only come from a human supplying
a corrected URL or confirming a transient failure has cleared.
