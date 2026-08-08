# Test results — OEM Radar cloud migration (Tier C)

## Native, before changes
`pytest -q` → **502 passed** in 128.6s.

## Native, after changes
`pytest -q` → **502 passed** (re-run after adding runtime_bridge/paths/CLI commands and
the backup/restore scripts — no regressions).

## In-container verification (not pytest — CLI invocation, matching Free Game Tracker's approach)
- `id` → `uid=10001(clank)`
- `version` / `identity` → valid JSON, `release_channel: "experimental"`
- `validate` → `OK: 28 OEM(s), 28 source(s), engines: [...]`
- `health` (empty volume) → `"degraded"`, exit 0, honest reason
- `run --source dell-us-laptops` (isolated volume) → live 403 from Dell (unrelated
  pre-existing issue), recorded as `failed` status row, exit 0
- `status` after container recreation (same volume) → identical data
- `python scripts/backup.py` → DB snapshot + raw evidence tarball
- `python scripts/restore.py` (isolated volume, including a read-only-mounted
  source) → `PRAGMA integrity_check` ok, 20 tables
- `run --source aoostar-shopify` / `run --source beelink-shopify` (real fetcher,
  real app, isolated volume) → both **200**, 0 errors — see `SHOPIFY_INVESTIGATION.md`

## Not run
- Full 28-OEM crawl — out of scope for portability verification; would needlessly
  hit 26 additional live third-party sites for no additional migration evidence.
