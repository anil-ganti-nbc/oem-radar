# Manual D1 Discovery inbox

Discovery is a separate **research-proposal inbox**, not product admission,
manufacturer resolution, official-source qualification or notification input.
It creates no catalogue entities, snapshots, product events, outbox entries or
product-alert/quality counts, and does not fuzzy-link products. Computing is
supported; watches and other profiles are explicitly counted as excluded.

## External producer prerequisite

The shared producer is not bundled or forked into OEM Radar. Obtain the accepted
D1 application and profiles through their separately authorised distribution.
Paths are configurable; this adapter consumes its actual `d1.lead.v2` JSONL.

| Pin | Required value |
| --- | --- |
| Accepted D1 content candidate (not a Git commit) | `5e138fabb1918e2fec8a570348c4a69070a4b00bdc2d488dea86d07ac45ad118` |
| `d1.py` SHA256 | `eaac15eb9ad414b2bbdd63870b70bbc1a8b2d93d9f21f1308c43db3217c69bf1` |
| `profiles.json` SHA256 | `a2ba255264a5599ac717b2c3a464e34c7f1a32564e55ca6949937afa5aa1375e` |

The adapter authenticates these pins before using the unchanged producer's
structural prefix and full available-evidence validator. It never silently
accepts another producer revision. A pin change needs explicit compatibility
verification. Missing evidence is unavailable/quarantined, never verified.

## Configure and import

Install this repository using its documented environment (Python 3.10+). Use the
project venv's Python below, or the equivalent installed `oem-radar` command.
Run from the checkout and replace all example absolute paths for your machine;
Windows accepts `C:/path/to/d1/app/d1.py`. No workstation path is built into the
application. `config/d1-discovery.example.json` shows the six settings fields with
intentionally non-runnable placeholders; prefer the validated `configure` command.

```bash
python -m oem_radar.cli discovery --settings config/d1-discovery.json configure \
  --producer-id discovery-core-d1 \
  --producer /absolute/path/to/d1/app/d1.py \
  --profiles /absolute/path/to/d1/app/profiles.json \
  --evidence-root /absolute/path/to/d1/inbox \
  --data-dir /absolute/path/to/oem-sidecar/discovery
python -m oem_radar.cli discovery --settings config/d1-discovery.json enable
python -m oem_radar.cli discovery --settings config/d1-discovery.json import /absolute/path/to/d1/inbox/leads.jsonl
python -m oem_radar.cli discovery --settings config/d1-discovery.json list
```

`configure` validates pins, creates **disabled** settings and refuses identity
overwrite. Paths must be absolute; consumer data must be outside the producer
evidence root. Choose the producer ID once: keys are `(producer_id, original
lead_id)`, not globally assumed unique IDs. Never publish live local settings.

Consumer-only editorial triage uses:

```bash
python -m oem_radar.cli discovery --settings config/d1-discovery.json review ORIGINAL_LEAD_ID --label editorial_research
```

Other labels: `unreviewed`, `editorial_keep`, `editorial_dismiss`. Producer review
state remains distinct, with no implicit write-back. Triage is neither product
admission nor source qualification. Ordinary success returns JSON/exit0; failure
returns JSON/exit2. Null brand/model and all uncertainties remain unresolved.

## Read-only view and explicit refresh

```bash
python -m oem_radar.cli discovery --settings config/d1-discovery.json dashboard \
  --catalog /absolute/path/to/existing/radar.db --port 8787 --no-browser
```

Open `http://127.0.0.1:8787/` → **Discovery**, or `/discovery`. This uses the
existing dashboard shell and an existing catalogue read-only (`mode=ro`),
bypassing legacy startup registry synchronization. It supplies no crawl
controller or web mutation authority; POST is405. Opening/reloading the view does
not collect, import, review or deliver. Do not combine this manual mode with
crawl/review-write authority. Source publication does not rebuild the packaged
executable or alter ordinary collector startup.

All retained cards and visible counts are available, without a hidden display
cap, alongside `/api/discovery`. Each card exposes source-faithful headline,
passage, publisher/link/date, observation/import clocks, uncertainties, both
review states, observation history and copied evidence. Third-party content does
not acquire `OFFICIAL_*` provenance. Text and attributes are escaped; safe HTTPS
links are not publisher verification. Copied evidence is served only by retained
referenced SHA256 identifier as `text/plain` with `nosniff` and sandbox CSP.

```bash
python -m oem_radar.cli discovery --settings config/d1-discovery.json refresh
```

Refresh is a deliberate collection operation, never part of normal crawling,
schedules or dashboard GET. Use it only within existing source-access authority.
It projects the **exact existing computing profile** from authenticated profiles
into owned staged state and invokes the unchanged producer with supported options:

```text
<current Python> -I -B <pinned d1.py> run --config <computing projection> --state <owned stage>
```

No category flag, watch source or expanded source is invented. Exit0 **and** a
COMPLETE report are required, with re-authentication after the child. Failed,
partial, timed-out or pre-publication-interrupted refresh leaves the last usable
inbox/export selected. Source publication performs no refresh.

## Store and evidence semantics

- A dedicated SQLite sidecar stores proposals, observations and consumer review
  history. Identical exports dedupe without resetting review; changed evidence
  appends history; omissions do not delete leads.
- Entire input is bounded and validated before consumer writes. Limits: 32MiB
  export, 10000 lines, 1MiB per line, 5MiB per evidence file, 128MiB aggregate
  referenced bytes. Duplicate keys/IDs, nonfinite numbers, non-objects, unknown
  schema and incomplete JSON are refused.
- Evidence paths are confined to an explicit root **before reads**. Traversal,
  escapes, links/junctions/reparse points, hard links, unsuitable files, bad
  hashes and nonliteral passage offsets reject the input.
- Only required immutable evidence is copied. Original payload/paths remain in
  `payload`; owned evidence hashes remain in `copied`. Copied evidence survives
  process restart, foreign cwd and disappearance of original evidence files.
- `data_dir/CURRENT` atomically selects matching
  `versions/<id>/proposals.sqlite3` and `consumer.jsonl`. That export is a consumer
  projection, not a replacement for the producer contract.
- Failed/unpublished generations and unreferenced blobs may remain; no automatic
  garbage collection. Use one manual writer. This is not a multi-writer service
  or hostile-local-process sandbox.
- Refresh uses fresh staged producer state; first-observed clocks are scoped to
  that stage, with earlier observations retained in history. They do not establish
  a launch, global novelty or something new to the operator.

## Disable / rollback

Stop only the manual dashboard with Ctrl+C, then:

```bash
python -m oem_radar.cli discovery --settings config/d1-discovery.json disable
```

This refuses future intake, refresh, review and manual-dashboard launches without
deleting leads, histories, evidence or settings. Stop an already-running server
explicitly because it retains launch-time settings. Re-enable with the same
command ending in `enable`. No catalogue migration, executable replacement,
ordinary collector restart or notification-policy rollback is needed.

## Offline verification and public CI

`tests/test_d1_discovery_portable.py` exercises generic parser/store/configuration,
pin refusal, path confinement, empty-view and disable controls without an external
producer or private publisher captures. These controls run on a normal checkout;
they are not replacements for real-evidence qualification.

The original19 nodes in `tests/test_d1_discovery.py` require this external layout:

```text
<fixture-root>/app/d1.py
<fixture-root>/app/profiles.json
<fixture-root>/inbox/leads.jsonl
<fixture-root>/inbox/<referenced immutable evidence>
```

Use the accepted hash-matching app and retained19-proposal fixture
(5computing/14watches), with absolute evidence references valid under its inbox.
A documented path-only relocation of authentic evidence is permitted. Do not
upload these private inputs, fabricate publisher data or collect again for tests.

```bash
export OEM_RADAR_D1_ROOT=/absolute/path/to/retained-d1-fixture
python -B -m pytest -p no:cacheprovider -q
```

Without that variable, the19 real-evidence nodes are explicitly skipped as
**NOT RUN**. Public CI green is not real-D1 qualification. An explicitly selected
missing/malformed fixture fails, not skips.

## Publication lineage

Accepted local integration: completed **COPS-000204**, content candidate
`6d5279c3ba16b30fe08a2e8849bf0001868c63de4a154ddd8f416e30897dfcd9`
(not a Git commit). Publication: **COPS-000205**, dispatch
`OEM-D1-PUBLISH-20261028`. All five application runtime files are transferred
without logic changes. Git normalizes CRLF to LF in the two existing call-site
files; normalized text and executable ASTs match the accepted source, and the
three added runtime files retain their raw bytes. Publication changes only
external test-root binding, portable documentation/example and additional generic
tests. Original test function bodies/assertions remain unchanged. Current remote
main's dependency
and container updates are preserved. No scheduling, Discord, NAS, automatic
product admission or wider discovery-engine production claim is implied.
