"""Five isolated Japanese mini-PC discovery probes.

This module is deliberately *not* an OEM Radar engine and is not imported by
the production runner.  It writes only to an experiment-owned SQLite file and
emits no notifications.  Its unit of discovery is a base model plus CPU/
platform, never a RAM, SSD, OS, price, availability, or BTO offer selection.

The probes are intentionally bounded to the five sources approved for the
Japan mini-PC experiment:

* NEC Mate NEW index, with an optional PC Search form enricher;
* Epson Direct catalogue checksum plus press-release model extraction;
* MousePro CR catalogue;
* THIRDWAVE HG catalogue; and
* GEEKOM Japan Shopify catalogue, compared only with the existing global
  GEEKOM WooCommerce catalogue identity.
"""
from __future__ import annotations

import hashlib
import html as html_mod
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin


NEC_NEW_URL = "https://jpn.nec.com/products/bizpc/index.html?mode=mvj"
NEC_PC_SEARCH_URL = "https://www.bizpc.nec.co.jp/pcseek/model_search"
EPSON_PRESS_URL = "https://shop.epson.jp/info/press/"
EPSON_CATALOGUE_URL = "https://shop.epson.jp/pdf/catalog_all.pdf"
MOUSEPRO_CR_URL = "https://www.mouse-jp.co.jp/store/r/ra3043012_ssp/"
THIRDWAVE_HG_URL = "https://www.dospara.co.jp/TC922"
GEEKOM_JP_PRODUCTS_URL = "https://geekom.jp/products.json?limit=250&page=1"
GEEKOM_GLOBAL_PRODUCTS_URL = (
    "https://www.geekompc.com/wp-json/wc/store/v1/products?per_page=100&page={page}"
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_CPU_RE = re.compile(
    r"(?:AMD\s+)?Ryzen(?:\s+AI)?(?:\s+MAX\+?)?\s*(?:\d\s*)?(?:PRO\s*)?"
    r"(?:HX\s*)?[A-Z]{0,2}\s*\d{3,4}[A-Z]*|"
    r"(?:Intel\s+)?Core\s*(?:Ultra\s*)?(?:[3579]\s*)?(?:i[3579][ -]?)?\d{3,5}[A-Z]*|"
    r"Intel\s+(?:Processor\s+)?N\d{2,3}|Celeron\s+[A-Z]?\d{3,5}",
    re.I,
)
_NEC_MATE_RE = re.compile(r"\bMate\s*(?:type\s*)?([A-Z]{1,3})\b", re.I)
_NEC_CODE_RE = re.compile(r"\b(?:PC-)?M(?=[A-Z0-9-]*\d)[A-Z0-9]{3,}(?:-[A-Z0-9]+)?\b", re.I)
_EPSON_RE = re.compile(r"\bEndeavor\s+((?:ST|JS)\d{2,3}[A-Z]?)\b|\b((?:ST|JS)\d{2,3}[A-Z]?)\b", re.I)
_MOUSE_RE = re.compile(r"\b(?:MousePro\s+)?(CR-[A-Z]\dU\d{2})\b", re.I)
_THIRDWAVE_RE = re.compile(r"\b(?:THIRDWAVE\s+)?(HG\d{4})\b", re.I)
_GEEKOM_MODEL_RE = re.compile(
    r"(?<![A-Z0-9])(MEGAMINI\s*G1|MINI\s*AIR\s*\d+|(?:IT|GT|AX|AE|XT|A)\d{1,2}"
    r"(?:\s+(?:MAX|MEGA|PRO))?)(?![A-Z0-9])",
    re.I,
)


def _text(value: str) -> str:
    return _WS_RE.sub(" ", html_mod.unescape(_TAG_RE.sub(" ", value))).strip()


def _token(value: str) -> str:
    return re.sub(r"[^A-Z0-9+]", "", value.upper())


def _cpu(value: str) -> str | None:
    match = _CPU_RE.search(_text(value))
    return _WS_RE.sub(" ", match.group(0)).strip() if match else None


def _identity(source: str, model: str, platform: str | None = None) -> str:
    # Explicitly omit commerce configuration details.  Platform is included
    # only when a vendor actually states a CPU/platform string.
    base = f"{source}:{_token(model)}"
    return base if not platform else f"{base}:{_token(platform)}"


@dataclass(frozen=True)
class JapanIdentity:
    source: str
    identity_key: str
    model: str
    platform: str | None
    url: str
    global_overlap: str = "not_applicable"
    evidence: str = "catalogue_base_model"


@dataclass
class JapanProbeStats:
    sources_polled: int = 0
    documents_fetched: int = 0
    baseline_identities: int = 0
    new_identities: int = 0
    candidates: int = 0
    global_duplicates: int = 0
    global_model_overlap: int = 0
    pc_search_enriched: int = 0
    failures: list[str] = field(default_factory=list)


def parse_nec_mate_new(html: str, url: str = NEC_NEW_URL) -> list[JapanIdentity]:
    text = _text(html)
    out: dict[str, JapanIdentity] = {}
    for match in _NEC_MATE_RE.finditer(text):
        family = f"Mate Type {match.group(1).upper()}"
        # A nearby PC code is only descriptive enrichment.  It does not split
        # an alert into RAM/SSD/OS sale configurations.
        window = text[match.start():match.start() + 350]
        code = _NEC_CODE_RE.search(window)
        platform = _cpu(window)
        model = family if code is None else f"{family} ({code.group(0).upper()})"
        key = _identity("nec_mate", family, platform)
        out[key] = JapanIdentity("nec_mate", key, model, platform, url,
                                 evidence="mate_new_index")
    return list(out.values())


def parse_nec_pc_search(html: str, source_url: str = NEC_PC_SEARCH_URL) -> dict[str, str]:
    """Extract only PC Search's exact product/model codes for enrichment.

    This is intentionally not a discovery parser: PC Search is a historical
    BTO search database and lacks a trustworthy added timestamp.  The caller
    may POST a model code into its public form and attach the returned exact
    code to an already-new Mate family.
    """
    return {code.upper(): source_url for code in _NEC_CODE_RE.findall(_text(html))}


def parse_epson_press(html: str, url: str = EPSON_PRESS_URL) -> list[JapanIdentity]:
    text = _text(html)
    out: dict[str, JapanIdentity] = {}
    for match in _EPSON_RE.finditer(text):
        model = (match.group(1) or match.group(2)).upper()
        # Require an Endeavor/PC context, avoiding unrelated document numbers.
        start = max(0, match.start() - 100)
        context = text[start:match.end() + 180]
        if "Endeavor" not in context and "エンデバー" not in context:
            continue
        platform = _cpu(context)
        key = _identity("epson_endeavor", model, platform)
        out[key] = JapanIdentity("epson_endeavor", key, f"Endeavor {model}",
                                 platform, url, evidence="epson_press")
    return list(out.values())


def parse_mousepro_cr(html: str, url: str = MOUSEPRO_CR_URL) -> list[JapanIdentity]:
    text = _text(html)
    out: dict[str, JapanIdentity] = {}
    for match in _MOUSE_RE.finditer(text):
        model = match.group(1).upper()
        context = text[max(0, match.start() - 80):match.end() + 250]
        platform = _cpu(context)
        key = _identity("mousepro_cr", model, platform)
        out[key] = JapanIdentity("mousepro_cr", key, f"MousePro {model}", platform,
                                 url, evidence="mousepro_cr_catalogue")
    return list(out.values())


def parse_thirdwave_hg(html: str, url: str = THIRDWAVE_HG_URL) -> list[JapanIdentity]:
    text = _text(html)
    out: dict[str, JapanIdentity] = {}
    for match in _THIRDWAVE_RE.finditer(text):
        model = match.group(1).upper()
        context = text[max(0, match.start() - 80):match.end() + 250]
        platform = _cpu(context)
        key = _identity("thirdwave_hg", model, platform)
        out[key] = JapanIdentity("thirdwave_hg", key, f"THIRDWAVE {model}", platform,
                                 url, evidence="thirdwave_hg_catalogue")
    return list(out.values())


def geekom_model_family(value: str) -> str | None:
    match = _GEEKOM_MODEL_RE.search(_text(value))
    if not match:
        return None
    return _WS_RE.sub(" ", match.group(1).upper()).strip()


def parse_geekom_jp_products(body: str) -> list[JapanIdentity]:
    data = json.loads(body)
    products = data.get("products") or []
    out: dict[str, JapanIdentity] = {}
    for product in products:
        title = _text(str(product.get("title") or ""))
        family = geekom_model_family(title)
        if not family:
            continue
        variants = product.get("variants") or []
        variant_text = " ".join(
            str(v.get(field) or "") for v in variants
            for field in ("option1", "option2", "option3", "title")
        )
        platform = _cpu(f"{title} {product.get('body_html') or ''} {variant_text}")
        key = _identity("geekom", family, platform)
        out[key] = JapanIdentity("geekom_jp", key, f"GEEKOM {family}", platform,
                                 f"https://geekom.jp/products/{product.get('handle', '')}",
                                 evidence="jp_shopify_product")
    return list(out.values())


def parse_geekom_global_products(body: str) -> set[str]:
    """Return base-model/platform identities from the configured global API.

    The global source's stable WooCommerce numeric IDs are intentionally not
    compared with Shopify numeric IDs; those are store-local.  Product family
    plus stated platform is the cross-store identity, with model-only overlap
    retained separately by the collector.
    """
    products = json.loads(body)
    out: set[str] = set()
    if not isinstance(products, list):
        return out
    for product in products:
        title = _text(str(product.get("name") or ""))
        family = geekom_model_family(title)
        if not family:
            continue
        text = f"{title} {product.get('short_description') or ''} {product.get('description') or ''}"
        out.add(_identity("geekom", family, _cpu(text)))
    return out


def geekom_model_key(identity_key: str) -> str:
    """Drop the optional platform suffix without losing a model-only key."""
    return ":".join(identity_key.split(":", 2)[:2])


def global_geekom_model_keys_from_db(path: str | Path) -> frozenset[str]:
    """Read the configured global GEEKOM source history without mutating it."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    try:
        rows = db.execute(
            "SELECT COALESCE(l.vendor_handle, ''), COALESCE(p.canonical_model, '') "
            "FROM listings l JOIN products p ON p.id=l.product_id "
            "JOIN sources s ON s.id=l.source_id WHERE s.source_key='geekom-wc'"
        ).fetchall()
    finally:
        db.close()
    keys = set()
    for row in rows:
        for value in row:
            family = geekom_model_family(str(value or ""))
            if family:
                keys.add(geekom_model_key(_identity("geekom", family)))
    return frozenset(keys)

class ExperimentalJapanMiniStore:
    """Private experimental state; deliberately unrelated to SnapshotStore."""

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS japan_mini_runs(
          id INTEGER PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL,
          status TEXT NOT NULL, identity_count INTEGER NOT NULL DEFAULT 0,
          document_count INTEGER NOT NULL DEFAULT 0, error TEXT);
        CREATE TABLE IF NOT EXISTS japan_mini_identities(
          source TEXT NOT NULL, identity_key TEXT NOT NULL, model TEXT NOT NULL,
          platform TEXT, url TEXT NOT NULL, global_overlap TEXT NOT NULL,
          evidence TEXT NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
          PRIMARY KEY(source, identity_key));
        CREATE TABLE IF NOT EXISTS japan_mini_candidates(
          id INTEGER PRIMARY KEY, source TEXT NOT NULL, identity_key TEXT NOT NULL,
          model TEXT NOT NULL, platform TEXT, url TEXT NOT NULL,
          global_overlap TEXT NOT NULL, reason TEXT NOT NULL, first_observed_at TEXT NOT NULL,
          UNIQUE(source, identity_key));
        CREATE TABLE IF NOT EXISTS japan_mini_artifacts(
          source TEXT NOT NULL, url TEXT NOT NULL, sha256 TEXT NOT NULL,
          first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
          PRIMARY KEY(source, url));
        """)
        self.db.commit()

    def previous_count(self, source: str) -> int | None:
        row = self.db.execute(
            "SELECT identity_count FROM japan_mini_runs WHERE source=? AND status='ok' "
            "ORDER BY id DESC LIMIT 1", (source,)).fetchone()
        return None if row is None else int(row[0])

    def known(self, source: str) -> set[str]:
        return {r[0] for r in self.db.execute(
            "SELECT identity_key FROM japan_mini_identities WHERE source=?", (source,))}

    def save_success(self, source: str, identities: list[JapanIdentity], candidates: list[JapanIdentity],
                     artifacts: list[tuple[str, str]], now: str, document_count: int) -> None:
        for item in identities:
            self.db.execute(
                "INSERT INTO japan_mini_identities(source,identity_key,model,platform,url,global_overlap,evidence,first_seen_at,last_seen_at) "
                "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(source,identity_key) DO UPDATE SET "
                "model=excluded.model,platform=excluded.platform,url=excluded.url,global_overlap=excluded.global_overlap, "
                "evidence=excluded.evidence,last_seen_at=excluded.last_seen_at",
                (source, item.identity_key, item.model, item.platform, item.url, item.global_overlap,
                 item.evidence, now, now))
        for item in candidates:
            self.db.execute(
                "INSERT OR IGNORE INTO japan_mini_candidates(source,identity_key,model,platform,url,global_overlap,reason,first_observed_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (source, item.identity_key, item.model, item.platform, item.url, item.global_overlap,
                 "base_model_platform_not_previously_seen", now))
        for url, body in artifacts:
            digest = hashlib.sha256(body.encode("utf-8", errors="ignore")).hexdigest()
            self.db.execute(
                "INSERT INTO japan_mini_artifacts(source,url,sha256,first_seen_at,last_seen_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(source,url) DO UPDATE SET sha256=excluded.sha256,last_seen_at=excluded.last_seen_at",
                (source, url, digest, now, now))
        self.db.execute(
            "INSERT INTO japan_mini_runs(source,started_at,status,identity_count,document_count) VALUES(?,?, 'ok',?,?)",
            (source, now, len(identities), document_count))
        self.db.commit()

    def save_failure(self, source: str, now: str, error: str) -> None:
        self.db.execute(
            "INSERT INTO japan_mini_runs(source,started_at,status,error) VALUES(?,?, 'failed',?)",
            (source, now, error))
        self.db.commit()

    def close(self) -> None:
        self.db.close()


class JapanMiniProbeCollector:
    """Bounded, baseline-then-delta collector for the five approved probes."""

    def __init__(self, store: ExperimentalJapanMiniStore, minimum_fraction: float = .35, global_geekom_history_db: str | Path | None = None):
        self.store = store
        self.minimum_fraction = minimum_fraction
        self._global_geekom_history = frozenset()
        self.global_history_error = None
        if global_geekom_history_db:
            try:
                self._global_geekom_history = global_geekom_model_keys_from_db(global_geekom_history_db)
            except (OSError, sqlite3.Error) as exc:

                self.global_history_error = str(exc)
    def _save(self, source: str, identities: list[JapanIdentity], artifacts: list[tuple[str, str]],
              stats: JapanProbeStats, now: str, documents: int, candidate_filter=None) -> None:
        previous = self.store.previous_count(source)
        if not identities:
            raise ValueError("unsafe zero base-model/platform identities")
        if previous and len(identities) / previous < self.minimum_fraction:
            raise ValueError(f"unsafe identity count {len(identities)} (previous={previous})")
        if previous is None:
            stats.baseline_identities += len(identities)
            self.store.save_success(source, identities, [], artifacts, now, documents)
            return
        known = self.store.known(source)
        new_all = [x for x in identities if x.identity_key not in known]
        new = [x for x in new_all if candidate_filter is None or candidate_filter(x)]
        stats.new_identities += len(new_all)
        stats.candidates += len(new)
        self.store.save_success(source, identities, new, artifacts, now, documents)

    @staticmethod
    def _get(fetcher, url: str) -> str:
        return fetcher.get(url).body

    def _run_source(self, source: str, parser, url: str, fetcher, stats: JapanProbeStats,
                    now: str, artifacts: list[tuple[str, str]] | None = None) -> list[JapanIdentity]:
        stats.sources_polled += 1
        try:
            body = self._get(fetcher, url)
            stats.documents_fetched += 1
            identities = parser(body, url)
            self._save(source, identities, (artifacts or []) + [(url, body)], stats, now, 1 + len(artifacts or []))
            return identities
        except Exception as exc:  # experiments fail per source, never partially overwrite a baseline
            stats.failures.append(f"{source}: {exc!r}")
            self.store.save_failure(source, now, str(exc))
            return []

    def _run_geekom(self, fetcher, stats: JapanProbeStats, now: str) -> None:
        source = "geekom_jp"
        stats.sources_polled += 1
        try:
            jp_body = self._get(fetcher, GEEKOM_JP_PRODUCTS_URL)
            stats.documents_fetched += 1
            global_keys: set[str] = set()
            global_pages = 0
            for page in range(1, 4):  # global source currently fits in one page; hard bounded
                body = self._get(fetcher, GEEKOM_GLOBAL_PRODUCTS_URL.format(page=page))
                stats.documents_fetched += 1
                global_pages += 1
                parsed = json.loads(body)
                global_keys.update(parse_geekom_global_products(body))
                if not isinstance(parsed, list) or len(parsed) < 100:
                    break
            global_models = {geekom_model_key(key) for key in global_keys}
            identities = []
            global_models.update(self._global_geekom_history)
            for item in parse_geekom_jp_products(jp_body):
                overlap = "duplicate_global" if item.identity_key in global_keys else (
                    "global_model_overlap" if geekom_model_key(item.identity_key) in global_models else "unique_jp"
                )
                if overlap == "duplicate_global":
                    stats.global_duplicates += 1
                elif overlap == "global_model_overlap":
                    stats.global_model_overlap += 1
                identities.append(JapanIdentity(item.source, item.identity_key, item.model, item.platform,
                                                item.url, overlap, item.evidence))
            self._save(source, identities, [(GEEKOM_JP_PRODUCTS_URL, jp_body)], stats, now, 1 + global_pages, lambda x: x.global_overlap == "unique_jp")
        except Exception as exc:
            stats.failures.append(f"{source}: {exc!r}")
            self.store.save_failure(source, now, str(exc))

    def run(self, fetcher, now: datetime | None = None, include_catalogue: bool = False) -> JapanProbeStats:
        now = now or datetime.now(timezone.utc)
        stamp = now.isoformat()
        stats = JapanProbeStats()
        self._run_source("nec_mate", parse_nec_mate_new, NEC_NEW_URL, fetcher, stats, stamp)

        # PC Search is explicitly an enrichment source, not a discovery source.
        # A client with post_form can opt into its public CSRF form.  Ordinary
        # HttpFetcher users still get the safer NEC NEW-only collector.
        if hasattr(fetcher, "post_form"):
            try:
                for row in self.store.db.execute("SELECT model FROM japan_mini_identities WHERE source='nec_mate'"):
                    code = next(iter(_NEC_CODE_RE.findall(row[0])), None)
                    if code:
                        parsed = parse_nec_pc_search(fetcher.post_form(NEC_PC_SEARCH_URL, {"KATA": code}).body)
                        stats.documents_fetched += 1
                        stats.pc_search_enriched += int(code.upper() in parsed)
            except Exception as exc:
                stats.failures.append(f"nec_pc_search: {exc!r}")

        # Epson's catalogue is currently ~100 MB.  It is a checksum-only
        # corroboration artifact, so keep it opt-in rather than making the
        # cheap daily discovery pass download a BTO catalogue.
        catalogue = ""
        if include_catalogue:
            try:
                catalogue = self._get(fetcher, EPSON_CATALOGUE_URL)
                stats.documents_fetched += 1
            except Exception as exc:
                stats.failures.append(f"epson_catalogue: {exc!r}")
        self._run_source("epson_endeavor", parse_epson_press, EPSON_PRESS_URL, fetcher, stats,
                         stamp, [(EPSON_CATALOGUE_URL, catalogue)] if catalogue else [])
        self._run_source("mousepro_cr", parse_mousepro_cr, MOUSEPRO_CR_URL, fetcher, stats, stamp)
        self._run_source("thirdwave_hg", parse_thirdwave_hg, THIRDWAVE_HG_URL, fetcher, stats, stamp)
        self._run_geekom(fetcher, stats, stamp)
        return stats
