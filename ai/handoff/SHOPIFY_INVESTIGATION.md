```yaml
project: oem-radar
investigation: shopify-collector-transport-defect
date: 2026-08-08
environment: Docker Desktop (Windows host), linux/amd64, base image python:3.12-slim-bookworm
image_digest: sha256:68dc23f210ccd1fcc45821f35126d3aff9fce52e3623e8f7b61b476d0a1b2bc0
python: 3.12.13
requests: 2.34.2
urllib3: 2.7.0
curl: 7.88.1 (OpenSSL/3.0.20)
result: NOT REPRODUCED in this environment on this date
conclusion: unresolved — do not generalize either direction
```

## What this is and isn't

This is a reproduction *attempt* against the previously documented defect
(`PORTABILITY_FINDINGS.MD` / `KNOWN_ISSUES.MD`: Docker `curl` gets 200, Python
`requests` gets `429 local_rate_limited` with `Retry-After: 60`). It is **not** a
fix, and it does not authorize broadly re-declaring Shopify collectors healthy.

## Protocol followed

1. Did not generalize the prior finding to other clanks or assume it still holds here.
2. Established an unmodified baseline first (plain `curl`, then plain Python `requests`,
   both from a fresh `python:3.12-slim-bookworm` container — the same base image family
   as the actual `oem-radar` image), before touching the real application at all.
3. Tested inside the actual target image afterward (`oem-radar:test-local`, built from
   this repo's own `Dockerfile`), using the real `run` command against two of the three
   specifically-named affected OEMs (Aoostar, Beelink) — not a synthetic probe.
4. Two different live domains were tested (`aoostar.com`, `www.bee-link.com`), not
   repeated hammering of one endpoint. No `429` was hit at any point, so no `Retry-After`
   wait was ever required.
5. Captured status, headers, and body prefix for every request (see below).

## Results

| Test | Target | Result |
|---|---|---|
| `curl` (baseline, unmodified) | `aoostar.com/products.json?limit=250&page=1` | **200**, HTTP/2, real product JSON, served via Cloudflare |
| Python `requests` (bare, same base image) | same URL | **200**, HTTP/1.1, identical product JSON, `Content-Encoding: gzip` |
| `oem-radar run --source aoostar-shopify` (real app, real fetcher, in the actual built image) | `aoostar.com` | **200** — 27 products discovered, 27 new snapshots, **0 errors** |
| `oem-radar run --source beelink-shopify` (real app, real fetcher) | `www.bee-link.com` | **200** — 41 products discovered, 40 new snapshots, **0 errors** |

Full response headers were captured for the first two requests (available in this
session's transcript on request); both show a normal Cloudflare-fronted Shopify
response (`server: cloudflare`, `powered-by: Shopify`, `x-dc: gcp-asia-southeast1`,
Shopify session cookies set correctly) with no rate-limit indicators anywhere.

## What this evidence does and doesn't show

**Weakens** (does not disprove) the standing hypothesis that this is a general
"Linux Python HTTP-stack/TLS-fingerprint" problem: if that were the root cause, a
plain `requests` call from a fresh Linux container should have failed here the same
way it did before. It didn't — 4 for 4 successes across two independent domains,
including through the real application code path.

**Does not prove** the issue is fixed or was never real. Cloudflare-fronted rate
limiting is commonly keyed to source IP reputation, ASN, and recent traffic volume —
factors tied to the *specific host* making the request, not the client library. The
original evidence was gathered on a different host than this one. It is entirely
possible that host's outbound IP was rate-limited or flagged for reasons unrelated to
Python vs. curl, and that a *different* future host (in particular, whatever cloud
host is eventually provisioned for real deployment) could reproduce the same 429
regardless of what this test showed today.

## Classification

**Unknown**, leaning toward **infrastructure/network-path-specific** rather than a
portability defect in the strict sense (code behaving differently due to OS/packaging
differences). Not reclassified as a product defect — there is still no evidence the
collector code itself is wrong. Per the brief's own framework: "Do not relabel an
unknown as a portability defect merely because it appeared during Docker testing" —
symmetrically, I'm not relabeling it "resolved" merely because it didn't reproduce once
on a different host.

## Recommendation

- **Do not** merge any transport change (no `httpx`, `curl_cffi`, or `urllib.request`
  substitution) — there is nothing to fix based on this evidence, and the brief
  prohibits speculative transport rewrites regardless.
- **Do not** mark OEM Radar's Shopify collectors "healthy" or promote release status
  based on this result alone — this was one test session against two domains.
- **Do** re-run this same reproduction protocol from the actual cloud host once one is
  provisioned, before relying on Shopify collectors in that environment. If it
  reproduces there, the "specific host/IP reputation" theory gains support and the
  fix path becomes an infrastructure one (different egress IP, different provider) —
  not a code change. If it doesn't reproduce there either, that's further (still not
  conclusive) evidence the original issue was tied to the original sandbox host
  specifically.
- Continue treating this as an open, tracked unknown — not a blocker for the
  portability work (Docker/runtime-bridge/backup-restore) already completed and
  verified in this session, which does not depend on Shopify collector health.
