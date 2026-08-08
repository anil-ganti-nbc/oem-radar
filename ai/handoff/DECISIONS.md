# Decisions — OEM Radar cloud migration (Tier C)

1. **Adapted the stale `unified/oem-radar` snapshot as a recipe, not a copy.** That
   snapshot was never Docker-verified (its host had no Docker installed at all — see
   its own `STAGE1_3_BLOCKER.md`). This phase rebuilt the same pattern against the
   live repository and verified it for real, for the first time.

2. **`release_channel` defaults to `"experimental"`, never `"production"`.** The stale
   template had the identical hard-coded `RELEASE_CHANNEL = "production"` bug found
   and fixed in Free Game Tracker's template. OEM Radar's current maturity
   classification is "Needs More Features" (Tier C) — an unpromoted, freshly-verified
   image must not self-report as production regardless of what an older example
   inventory claimed.

3. **No production Compose file for this clank in this phase.** Only
   `docker-compose.yml` exists, and it's explicitly labeled/positioned as
   portability + investigation only. Tier C does not get a production deployment
   path at all in this migration phase.

4. **Left the main crawl path's path-resolution untouched.** `OEM_RADAR_DATA_DIR` is
   wired only into the new `paths.py`/health command. The existing crawl code already
   resolves `data/radar.db` correctly relative to the container's `WORKDIR /app` when
   the volume is mounted at `/app/data` — no remapping was needed for the primary
   pipeline, so none was added, keeping the diff minimal.

5. **Wrote new backup/restore scripts rather than adapting an existing mechanism**,
   because none existed for this clank before (unlike Semiconductor Intelligence,
   which already has a `backup` command). Modeled directly on Free Game Tracker's
   now-verified pattern for consistency across the fleet.

6. **Shopify investigation kept as a separate commit from the mechanical portability
   work**, per the brief's explicit instruction to not mix transport experiments with
   packaging changes — even though the investigation produced no code change at all.

7. **Did not expand the investigation to all 17 Shopify-backed OEMs.** Two
   specifically-named affected OEMs (Aoostar, Beelink) were sufficient to get a clear,
   consistent signal without needlessly hitting 15 additional live third-party sites.
