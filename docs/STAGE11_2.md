# Stage 11.2 — Triggering a crawl from the dashboard

**Written 2026-08-08.** Feature request, not a regression fix: *"the
ability to trigger a collector run from the GUI. Reload doesn't really do
anything, and every time I login to the radar, I see stale runs."*

Tests: 444 → **479**. Schema: **unchanged at v7** (this touches no
tables). Collectors: **unchanged at 21**.

---

## The problem, stated precisely

The dashboard was read-only by design and said so in its own docstring:
*"it never crawls, never calls a discovery/parsing engine, and never
touches the network."* That was a defensible property while a scheduled
task was the only writer. It had two consequences the request names:

1. **"Reload doesn't really do anything."** Correct, and for two separate
   reasons. The server re-queried a database nothing was updating, so the
   same rows came back — and the reload also dropped you back onto the
   Stories tab, because the active tab was never in the URL. Both halves
   made reload feel inert.
2. **"Every time I login to the radar, I see stale runs."** The last
   successful crawl on the real DB was **2026-08-07 ~18:00** — the
   scheduled hourly task had not fired for a day. The dashboard had no
   way to say so and no way to fix it.

The dashboard is the only thing a journalist opens. If opening it cannot
produce current data, the schedule is a single point of failure with no
manual override.

---

## What was built

### One crawl, two callers — `core/crawl_service.py`

`run_all` had exactly one caller (`cli.cmd_run`), so the assembly around
it lived inline there: resolve the webhook, build the fetcher, build the
store and notifier, take the single-instance lock, seed components, count
what is left pending. Adding a second caller was the exact shape of
mistake Stage 11.1 spent a whole stage undoing, so the assembly moved into
one module first:

```
cli.cmd_run ─┐
             ├─> crawl_service.execute_crawl ─> runner.run_all
CrawlController ─┘         (lock, store, notifier, fetcher, seeding)
```

`cmd_run` is now a printer around `execute_crawl` — it contains no
`run_all` call at all, and a test asserts that (`test_execute_crawl_is_
what_cmd_run_calls`). `cli._build_fetcher` and `cli._resolve_webhook`
survive as aliases pointing at the crawl_service functions, and another
test asserts they are literally the same objects, so re-inlining a copy
fails the suite rather than passing review.

**A real bug this surfaced:** `launch_dashboard.py` (the `.exe`) never
imports `cli.py`, and `cli.py` was where the engine and provider modules
got imported for their registration side effect. A crawl triggered from
the browser would have hit an empty engine registry and failed on its
first source. `execute_crawl` now calls `_ensure_registries()` itself
rather than depending on who imported what first.

### Progress that can be observed — `run_all(on_progress=…)`

An optional callback, emitting `planned` / `source_start` / `source_done`
/ `source_skipped` / `stories` / `finished`. Additive; every existing
caller is unaffected. Two deliberate details:

- **Skips are reported, not silent.** A crawl where everything is inside
  its `min_interval` does nothing and finishes fast. Without an event the
  UI cannot distinguish *up to date* from *hung*.
- **A raising observer cannot abort a crawl.** Wrapped and logged. A
  progress bar is not worth losing an hour of crawling to.

### `CrawlController` — single-flight, background, observable

One instance per dashboard process. `trigger()` returns immediately;
`status()` is a cheap snapshot safe to poll from handler threads. States:
`idle` / `running` / `ok` / `failed` / `blocked`.

`blocked` is deliberately not `failed`. The scheduled task and the
dashboard share one `RunLock`; if the hourly crawl is mid-flight, the
right thing to tell a user is *"a crawl is already running"*, not *"your
crawl failed."*

It is **not a queue**. A second trigger while one is in flight is refused
(409), not deferred — the running crawl will pick up everything due
anyway, so queueing would only buy a redundant second pass over the same
catalogs.

### HTTP

| | |
|---|---|
| `GET /api/crawl/status` | current state; polled every 2s while running |
| `POST /api/crawl` | `{force, source}`; 202 accepted / 409 running / 403 CSRF or manual-disabled / 503 read-only |

CSRF-gated with the same per-process token as review writes. Starting a
crawl fetches from OEM sites and can send Discord notifications — strictly
more side-effecting than saving a review, so it gets no weaker a check.

### UI — the crawl bar

Above the stats, always present, four states:

- **idle / stale** — "last successful crawl 3h ago", amber past
  `dashboard.stale_after_hours`, with **Run collectors now** and **Force
  re-crawl all**.
- **running** — live source name, `n of 21 source(s) checked`, progress
  bar, buttons disabled. Says *"started automatically when you opened the
  dashboard"* when the trigger was the auto one, so an unexpected crawl is
  never unexplained.
- **finished** — sources / snapshots / changes / duration.
- **blocked / failed** — the lock holder, or the exception.

Two behaviours worth naming:

- **Auto-reload is conditional.** The page reloads itself only when the
  crawl actually wrote something (`events > 0 or snapshots > 0`). A quiet
  crawl should not throw away your scroll position to show you the same
  rows.
- **`activateTab` now writes `?tab=` via `history.replaceState`.** Reload
  — including the automatic one — returns you to the tab you were
  reading. This is the other half of "reload doesn't do anything".

State is polled from the server, never inferred from what the page
happens to be showing — the same discipline Stage 11.1 imposed on the OEM
registry, for the same reason.

### Auto-trigger on launch

Opening the dashboard is treated as *"show me current data"*. Both entry
points (`oem-radar dashboard` and the `.exe`) start a crawl in the
background before `serve_forever`, so the browser opens immediately rather
than after a crawl that can exceed an hour.

**It does not force.** Every source's own `min_interval` still applies, so
opening the dashboard five times in an hour crawls nothing the first run
already covered. A test pins this (`test_serve_auto_crawl_does_not_force_
by_default`) because it is the single assumption that makes auto-crawl
safe to leave on.

### Config — `dashboard:` in `radar.yaml`

```yaml
dashboard:
  auto_crawl_on_start: true
  allow_manual_crawl: true
  auto_crawl_force: false
  stale_after_hours: 6
```

Plus `oem-radar dashboard --no-crawl`, which overrides config and restores
the pre-Stage-11.2 read-only behaviour exactly. `serve(crawl=None)` is
still fully supported: the endpoints answer 503 and the bar explains
itself. The controller is built by the entry point, never inside
`serve()` — serving a database and deciding to reach out to the internet
are different authorities, and only the entry point holds the config.

### A path bug fixed on the way

The `.exe` now `os.chdir(ROOT)` before serving. Every path in
`radar.yaml` (`db_path`, `raw_dir`, `run_lock_path`, the HTTP cache) is
relative to the project root, because that is where `start-radar.cmd` runs
`oem-radar run` from — but a double-clicked `.exe` inherits whatever
directory Explorer felt like. Without the anchor, a dashboard-triggered
crawl would have written its lock file and its cache somewhere other than
the scheduled crawl does, defeating the shared lock.

---

## What this changes about the project's shape

The dashboard is no longer read-only, and that is a real change, not a
detail. Recorded honestly:

| | Before | After |
|---|---|---|
| Network access | never | on launch and on click |
| Discord notifications | never from here | yes — same outbox, same policy |
| DB writes | reviews and mark-seen only | plus everything a crawl writes |
| Concurrency | n/a | one `RunLock`, shared with the scheduler |

The mitigation is not a weaker crawl — it is the *same* crawl, under the
same lock, honouring the same `min_interval`, reachable through one code
path, with a config switch and a CLI flag to turn it off.

---

## Verified against the real system

The rebuilt `OEM Radar Dashboard.exe` was launched against the real
`data/radar.db`:

```
GET /api/crawl/status  ->  status=running  trigger=auto  sources_total=21
                           current_source=acemagic-shopify
     ~30s later         ->  sources_done=1
                           acemagic-shopify: ok, 9 snapshots, 6 events
POST /api/crawl (no CSRF header)  ->  403
GET /                  ->  200, 448,372 bytes, crawl bar present
```

The auto-crawl fired on launch, planned all 21 sources, reported real
per-source progress, and produced real events on the first source —
against live storefronts, not fixtures.

---

## Regression tests added — `tests/test_crawl_trigger.py` (35)

Progress: order of events · skips reported · a broken observer cannot
abort a crawl · `planned` total respects `--source` and `enabled: false`.

Controller: starts idle · reports outcome and per-source rows ·
single-flight under a real race · lock held reads `blocked` not `failed` ·
survives a crawl that raises and stays reusable · `allow_manual: false`
blocks the button but not the auto-trigger.

One code path: `cli._build_fetcher is crawl_service.build_fetcher` ·
`cmd_run` calls `execute_crawl` and never `run_all` · engines register
without the CLI.

HTTP: 503 read-only · CSRF required · wrong token rejected · 202 starts ·
force passed through · 409 while running · unknown fields and bad types
rejected · GET/PUT rejected.

Wiring: `serve` auto-crawls when told to · never forces · does nothing
when `auto_crawl=False` · works with no controller at all · `--no-crawl`
overrides config.

Page: crawl bar and both buttons present · CSRF token substituted and the
placeholder never leaks · reload keeps your tab · state is polled, not
guessed.

---

## Stage 12 recommendation — unchanged

This did not displace it. `docs/STAGE11_1.md`'s recommendation still
stands: wire evidence sources into `oem-radar run`, then define what
promotes an evidence observation into a product signal, then delivery.
This stage makes the first of those cheaper to observe — an evidence
source wired into `run_all` will now show up in the crawl bar like any
other collector.

One operational note surfaced here and left alone deliberately: **the
hourly scheduled task had not fired since 2026-08-07 ~18:00.** The manual
trigger is a workaround for that, not a fix. Worth checking
`install-hourly-task.cmd`'s registration separately.
