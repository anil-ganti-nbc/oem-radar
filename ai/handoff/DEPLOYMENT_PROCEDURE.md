# Deployment / build procedure — OEM Radar (Tier C, Hetzner staging)

## Building an image with provenance

Every image built for Hetzner (or any deployment target) must pass the full
Git SHA as `GIT_REVISION`, so the running container can prove what it was
built from without trusting a checkout, a tag name, or an operator's memory:

```bash
git rev-parse HEAD   # capture the full SHA of the commit you're building
GIT_REVISION="$(git rev-parse HEAD)" \
IMAGE_TAG="$(git rev-parse --short HEAD)" \
docker compose build
```

`GIT_REVISION` (full SHA) is baked into the image as:

- the `org.opencontainers.image.revision` OCI label (`docker inspect
  oem-radar:<tag> --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'`)
- the `OEM_RADAR_SOURCE_REVISION` environment variable, surfaced by
  `oem-radar identity` and `oem-radar version` as `source_revision` (full)
  and `source_revision_short` (first 12 chars, for humans)

`IMAGE_TAG` (commonly the short SHA) only controls the local Docker image
tag/filename — it is a convenience label, not the authoritative provenance
record. Never assume `IMAGE_TAG` alone proves what code is running; always
cross-check `org.opencontainers.image.revision` or `oem-radar identity`
against the GitHub commit you intended to deploy.

## Never trust a checkout or tag alone

If `GIT_REVISION` is omitted, the image builds successfully but reports
`source_revision: "unknown"` everywhere — a deliberate, honest default,
never a fabricated guess. A build that reports `"unknown"` should not be
treated as identified provenance for a real deployment; treat it as a
local/dev build only.

## Verifying a deployment matches the intended GitHub revision

After building and deploying, confirm all three agree before trusting the
deployment:

```bash
git rev-parse HEAD                                                       # GitHub truth
docker inspect oem-radar:<tag> --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'  # image label
docker run --rm oem-radar:<tag> oem-radar identity                       # running-code claim
```

All three full SHAs must match. If they don't, do not assume the deployment
is correct — investigate before proceeding, the same way a stale-deployment
check should (see the 2026-08-09 OEM Radar Hetzner revision verification for
a worked example of why the image itself, not just the checkout, is the
authoritative source of truth for what's actually running).
