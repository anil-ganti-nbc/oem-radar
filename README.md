# OEM Radar

Product-intelligence platform for boutique PC OEMs. It watches vendor storefronts, reasons about **products** (not webpages), detects semantic changes between immutable snapshots, and pushes high-signal alerts to Discord — with the explicit mission of spotting new hardware before mainstream tech media does.

## What it is not

Not a scraper. HTML is an implementation detail confined to source engines. Everything downstream of normalization — storage, diffing, severity scoring, AI summaries, notifications — operates only on the normalized product model.

## Quick orientation

| Question | Answer |
|---|---|
| Language | Python 3.10+, fully typed, `Protocol`-based interfaces |
| Runtime model | **Stateless one-shot runs** (`oem-radar run`) — catch-up semantics, no daemon required (see ADR-1 in ARCHITECTURE.md) |
| Extension unit | **Source**, not OEM. An OEM is identity + a list of sources; each source = platform engine + YAML descriptor (ADR-2) |
| Storage | SQLite, append-only snapshots, content-hash dedup (DATABASE.md) |
| Diffing | Semantic diff over normalized snapshots, rules-driven severity (DIFF_ENGINE.md) |
| Notifications | Discord webhooks via an outbox table — failed sends retry next run |
| AI | Anthropic (Claude) rewords machine-generated diff facts; it never sees HTML and never invents facts (ARCHITECTURE.md §AI) |

## Layout

```
oem_radar/
├── README.md
├── pyproject.toml
├── config/
│   ├── radar.yaml            # global: schedules, rate limits, severity thresholds, webhooks, AI
│   └── oems/                 # one descriptor per OEM (identity + sources)
│       └── gmktec.yaml
├── src/oem_radar/
│   ├── cli.py                # oem-radar run | status | backfill
│   ├── core/                 # vendor-agnostic engine
│   │   ├── models.py         # NormalizedProduct, Snapshot, ChangeEvent, Severity
│   │   ├── interfaces.py     # SourceEngine, Fetcher, SnapshotStore, Notifier, Summarizer
│   │   ├── pipeline.py       # discover → fetch → parse → normalize → resolve → diff → notify
│   │   ├── registry.py       # engine/provider registration
│   │   ├── config.py         # YAML loading + validation
│   │   ├── resolve.py        # product identity resolution (M5)
│   │   ├── diff.py           # semantic diff + severity rules
│   │   └── knownhw.py        # known-hardware flagging (M5)
│   ├── engines/              # platform engines: shopify/, woocommerce/, generic_html/
│   └── providers/            # discord/, sqlite/, anthropic/
├── tests/
└── docs/
    ├── ARCHITECTURE.md       # design + decision records (read this first)
    ├── PLUGIN_GUIDE.md       # adding an OEM or a new engine
    ├── DATABASE.md           # schema, immutability, dedup
    ├── DIFF_ENGINE.md        # change taxonomy, severity rules, entity resolution
    └── ROADMAP.md            # milestones M0–M12
```

## Running (M6 state — fully functional through Discord notifications)

```bash
pip install -e ".[dev]"
pytest                    # 46 tests: fetch, engine, store, diff, notifier, end-to-end
oem-radar validate        # validate config offline (incl. engine config schemas)

# set your webhook once (name configurable in radar.yaml):
set OEM_RADAR_DISCORD_WEBHOOK=https://discord.com/api/webhooks/...   # Windows
export OEM_RADAR_DISCORD_WEBHOOK=...                                  # *nix

oem-radar run             # crawl all due sources, diff, notify, drain outbox
oem-radar run --dry-run   # in-memory store + console output, nothing persisted
oem-radar run --force --source gmktec-shopify   # ignore min_interval, one source
oem-radar status          # recent run telemetry
oem-radar dashboard       # launch the local web UI (opens your browser)
oem-radar probe https://some-oem.com            # fingerprint storefront platform
```

**Dashboard** (`dashboard.cmd`, or `oem-radar dashboard`): a local, read-only
web page at http://127.0.0.1:8787 — a Signals feed (new products + unseen
silicon), a filterable log of every change, the growing unseen-hardware list,
per-OEM counts, and run history. Every card links straight to the store
listing. It reads the live database read-only, so it is safe to leave open
while crawls run; hit reload to refresh. Stdlib-only, fully offline.

## Automated hourly crawling (Windows, hands-off)

The crawler and the dashboard share one database (`data/radar.db`), so a
scheduled crawl's results appear in the dashboard automatically the next time
you open it — no wiring needed.

To run the crawler silently every hour:

1. Double-click **`install-hourly-task.cmd`** once. It registers a Windows
   Scheduled Task that runs the crawl with **no visible window** (via
   `crawl-silent.vbs` → `crawl-hourly.cmd`). If it reports a permissions
   error, right-click → Run as administrator.
2. That's it. The crawler now runs hourly in the background. It does NOT open
   the dashboard.

Check on it whenever you like:

- **See results:** `dashboard.cmd` (or `oem-radar dashboard`) — opens the GUI
  over the latest data.
- **Run log:** `data\crawl-runs.log` — one start/done line per hourly run.
- **Force a run now:** `schtasks /run /tn "OEM Radar Hourly Crawl"`
- **Stop automation:** double-click `uninstall-hourly-task.cmd`.

Notes: each source still respects its own `min_interval` (6h for most), so an
hourly *task* doesn't mean hourly *fetches* — it just means the system checks
each hour whether anything is due, which is the right cadence for catching
launches promptly without hammering the shops. Notifications use the webhook
in `config\discord_webhook.txt` (or the env var), so hourly runs alert you
even though the dashboard is closed.


`start-radar.cmd` wraps all of the above with the webhook env var pre-set.
In PowerShell, prefix it: `.\start-radar.cmd test-notify` (PowerShell doesn't
run commands from the current directory without `.\`).

First run on a fresh DB baselines every product (severity-5 "new product"
each — expected; there is no history yet). From the second run on, only real
changes notify. Configured OEMs: GMKtec + Minisforum live (both verified
Shopify), Trigkey stubbed (`enabled: false` until you probe it).

## Design docs

**Continuing this project in a new session or with a different assistant?
Point it at `docs/HANDOFF.md` first** — current state, agreed next steps,
and environment gotchas that aren't in the design docs.

Monitoring the big brands (Lenovo, ASUS, HP…)? Read `docs/BIG_BRANDS.md` —
Dell is built (static HTML); ASUS/Lenovo need a Playwright fetcher, documented
there with a probe-first workflow.

Read `docs/ARCHITECTURE.md` first — it contains the decision records (ADRs) explaining every deviation from the original brief, including why per-OEM code plugins were rejected in favor of platform engines, and how "immediate" notification is reconciled with an ad-hoc desktop runtime.
