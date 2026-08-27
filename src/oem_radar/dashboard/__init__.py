"""Local read-only dashboard (M12) + alert review workflow (feedback v4).

Stdlib-only HTTP server over the SQLite DB. Opens the DB read-only for reads;
opens read-write only for mark-seen and review POST. Bound to localhost by
default. CSRF token is per-process and required for browser review writes.
"""

from __future__ import annotations

import json
import ipaddress
import logging
import re
import secrets
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from ..core.qc_archive import AlreadyQCed, QCArchive
from ..providers.sqlite import SqliteStore, connect_readonly
from .data import (
    collect,
    collect_alert_detail,
    collect_baseline_events,
    collect_evidence_detail,
)
from .render import render, render_evidence_page, render_qc_page, render_review_page

log = logging.getLogger("oem_radar.dashboard")

_CSRF_TOKEN = secrets.token_urlsafe(32)

_ALERT_PATH_RE = re.compile(r"^/alerts/(\d+)/?$")
_API_REVIEW_RE = re.compile(r"^/api/alerts/(\d+)/review/?$")
_EVIDENCE_PATH_RE = re.compile(r"^/evidence/(\d+)/?$")
_API_EVIDENCE_RE = re.compile(r"^/api/evidence/(\d+)/?$")


def _json_error(handler: BaseHTTPRequestHandler, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler, max_bytes: int) -> dict | None:
    ctype = (handler.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype not in ("application/json", "text/json"):
        _json_error(handler, 400, "invalid_content_type",
                    "Content-Type must be application/json")
        return None
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        _json_error(handler, 400, "invalid_content_length", "Invalid Content-Length")
        return None
    if length < 0:
        _json_error(handler, 400, "invalid_content_length", "Invalid Content-Length")
        return None
    if length > max_bytes:
        _json_error(handler, 413, "body_too_large",
                    f"Request body exceeds {max_bytes} bytes")
        return None
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        _json_error(handler, 400, "empty_body", "Request body is empty")
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _json_error(handler, 400, "malformed_json", f"Malformed JSON: {exc}")
        return None
    if not isinstance(data, dict):
        _json_error(handler, 400, "invalid_body", "JSON body must be an object")
        return None
    return data


class _Handler(BaseHTTPRequestHandler):
    db_path: str = ""
    raw_dir: str = ""
    max_body: int = 16384
    csrf_token: str = ""
    #: Two independent, orthogonal opt-ins -- each defaults off, each is
    #: decided by the entry point (CLI flag / config), never guessed here.
    #: Both still require `mutation_authorizer` to pass first, and both
    #: still require their own per-request CSRF header on top of that.
    review_writes_enabled: bool = False
    crawl_mutations_enabled: bool = False
    #: A `core.crawl_service.CrawlController`, or None. None means this
    #: launch did not authorize manual crawl triggering (dashboard.
    #: allow_manual_crawl is false, or `--no-crawl` / `--allow-manual-crawl`
    #: was not passed) -- crawl endpoints answer 503 and the UI says so.
    #: The controller is built by the entry point (CLI or the .exe
    #: launcher), never here: serving a database and deciding to crawl the
    #: internet are different authorities, and only the entry point has the
    #: config to decide. Auto-crawl-on-launch is never wired through this
    #: attribute at all -- see `serve()`'s hard rejection of auto_crawl.
    crawl = None
    mutation_authorizer = None
    stale_after_hours: float = 6.0

    def log_message(self, *a):
        pass

    def _readonly(self):
        return connect_readonly(self.db_path)

    def _qc_archive(self) -> QCArchive:
        """Separate, on-disk archive DB for alert-review QC decisions --
        sibling file to the live DB, never the live DB's own schema. See
        core.qc_archive for why (fleet-wide QC-archive contract)."""
        return QCArchive(Path(self.db_path).parent / "oem_radar_qc.db")

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            if path.startswith("/api/data"):
                conn = self._readonly()
                try:
                    body = json.dumps(
                        collect(conn, archived_alert_ids=self._qc_archive().archived_alert_ids())
                    ).encode("utf-8")
                finally:
                    conn.close()
                self._send(200, body, "application/json")
                return

            if path == "/api/feedback/metrics":
                from urllib.parse import parse_qs
                qs = parse_qs(urlparse(self.path).query)
                def q1(k):
                    v = qs.get(k, [None])[0]
                    return v
                try:
                    limit = int(q1("limit") or 50)
                except ValueError:
                    _json_error(self, 400, "invalid_limit", "limit must be an integer")
                    return
                group_by = q1("group_by")
                conn = self._readonly()
                try:
                    from ..core.feedback_analytics import build_metrics_payload
                    from ..core.feedback import FeedbackError
                    from ..core.config import load_radar_config
                    try:
                        min_sample = 5
                        payload = build_metrics_payload(
                            conn, start=q1("start"), end=q1("end"),
                            group_by=group_by, limit=limit, min_sample=min_sample,
                        )
                    except FeedbackError as fe:
                        _json_error(self, 400, "invalid_query", str(fe))
                        return
                finally:
                    conn.close()
                self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
                return

            if path == "/api/feedback/suggestions":
                raw_dir = self.raw_dir or str(Path(self.db_path).parent / "raw")
                store = SqliteStore(self.db_path, raw_dir)
                try:
                    rows = store.list_rule_suggestions(limit=100)
                finally:
                    store.close()
                self._send(200, json.dumps({"suggestions": rows}).encode("utf-8"), "application/json")
                return

            if path == "/feedback" or path.startswith("/feedback/"):
                # Minimal analytics page: JSON summary embedded
                conn = self._readonly()
                try:
                    from ..core.feedback_analytics import build_metrics_payload
                    metrics = build_metrics_payload(conn)
                except Exception as exc:
                    metrics = {"error": str(exc)}
                finally:
                    conn.close()
                raw_dir = self.raw_dir or str(Path(self.db_path).parent / "raw")
                store = SqliteStore(self.db_path, raw_dir)
                try:
                    suggestions = store.list_rule_suggestions(limit=50)
                finally:
                    store.close()
                from .render import render_feedback_page
                html = render_feedback_page(metrics, suggestions, csrf_token=self.csrf_token)
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return

            if path == "/api/baseline-events":
                conn = self._readonly()
                try:
                    body = json.dumps(
                        {"baseline_events": collect_baseline_events(conn)}
                    ).encode("utf-8")
                finally:
                    conn.close()
                self._send(200, body, "application/json")
                return

            if path == "/api/crawl/status":
                self._send(200, json.dumps(self._crawl_status()).encode("utf-8"),
                           "application/json")
                return

            if path == "/api/feedback/reasons":
                from ..core.feedback import reason_taxonomy, OUTCOMES
                payload = {
                    "outcomes": list(OUTCOMES),
                    "reasons": reason_taxonomy(),
                }
                self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
                return

            m = _API_REVIEW_RE.match(path)
            if m:
                alert_id = int(m.group(1))
                conn = self._readonly()
                try:
                    detail = collect_alert_detail(conn, alert_id)
                finally:
                    conn.close()
                if detail is None:
                    _json_error(self, 404, "not_found", f"No alert with id={alert_id}")
                    return
                from ..core.feedback import reason_taxonomy, OUTCOMES
                payload = {
                    "alert": detail,
                    "review": detail.get("review"),
                    "history": detail.get("history") or [],
                    "outcomes": list(OUTCOMES),
                    "reasons": reason_taxonomy(),
                    "csrf_token": self.csrf_token,
                }
                self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
                return

            m = _API_EVIDENCE_RE.match(path)
            if m:
                conn = self._readonly()
                try:
                    detail = collect_evidence_detail(conn, int(m.group(1)))
                finally:
                    conn.close()
                if detail is None:
                    _json_error(self, 404, "not_found",
                                f"No evidence item with id={m.group(1)}")
                    return
                self._send(200, json.dumps(detail).encode("utf-8"), "application/json")
                return

            m = _EVIDENCE_PATH_RE.match(path)
            if m:
                evidence_id = int(m.group(1))
                conn = self._readonly()
                try:
                    detail = collect_evidence_detail(conn, evidence_id)
                finally:
                    conn.close()
                if detail is None:
                    self.send_error(404, f"Evidence item {evidence_id} not found")
                    return
                html = render_evidence_page(detail)
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return

            m = _ALERT_PATH_RE.match(path)
            if m:
                alert_id = int(m.group(1))
                conn = self._readonly()
                try:
                    detail = collect_alert_detail(conn, alert_id)
                finally:
                    conn.close()
                if detail is None:
                    self.send_error(404, f"Alert {alert_id} not found")
                    return
                html = render_review_page(detail, csrf_token=self.csrf_token)
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return

            if path in ("/", "/index.html"):
                archived = self._qc_archive().archived_alert_ids()
                conn = self._readonly()
                try:
                    data = collect(conn, archived_alert_ids=archived)
                finally:
                    conn.close()
                body = render(data, csrf_token=self.csrf_token).encode("utf-8")
                self._send(200, body, "text/html; charset=utf-8")
                return

            if path == "/qc" or path.startswith("/qc/"):
                recent = [dict(r) for r in self._qc_archive().recent(limit=100)]
                html = render_qc_page(recent, csrf_token=self.csrf_token)
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return

            if path == "/api/qc/recent":
                from urllib.parse import parse_qs
                qs = parse_qs(urlparse(self.path).query)
                try:
                    limit = int((qs.get("limit", [None])[0]) or 50)
                except ValueError:
                    limit = 50
                limit = max(1, min(limit, 500))
                recent = [dict(r) for r in self._qc_archive().recent(limit=limit)]
                self._send(200, json.dumps({"recent": recent}).encode("utf-8"),
                          "application/json")
                return

            self.send_error(404)
        except Exception as exc:
            log.exception("dashboard GET failed")
            self.send_error(500, str(exc)[:200])

    def do_POST(self):
        authorizer = type(self).mutation_authorizer
        if authorizer is None or not authorizer(self.headers):
            _json_error(
                self, 403, "authenticated_profile_required",
                "This dashboard was launched with no mutation authorization "
                "(dashboard.allow_manual_crawl / --allow-review-writes); "
                "CSRF alone is not authentication.",
            )
            return
        path = urlparse(self.path).path
        try:
            # mark-seen is a local-only DB write (no network call, no
            # notification) -- gated on the same "some mutation capability
            # is authorized" check as everything else, not on crawl
            # specifically, so a --allow-review-writes-only launch can still
            # use it.
            if path == "/api/mark-seen":
                self._handle_mark_seen()
                return
            if path == "/api/crawl":
                # `self.crawl is None` (crawl_mutations_enabled False) is
                # handled inside _handle_crawl_post, which answers 503 --
                # that is the "disabled" signal the UI already reads.
                self._handle_crawl_post()
                return

            m = _API_REVIEW_RE.match(path)
            if m:
                if not type(self).review_writes_enabled:
                    _json_error(self, 403, "review_writes_disabled_launch",
                                "This dashboard was launched without "
                                "--allow-review-writes.")
                    return
                self._handle_review_post(int(m.group(1)))
                return
            self.send_error(404)
        except Exception as exc:
            log.exception("dashboard POST failed")
            _json_error(self, 500, "internal_error", "Internal server error")

    def do_PUT(self):
        self.send_error(405, "Method Not Allowed")

    def do_DELETE(self):
        self.send_error(405, "Method Not Allowed")

    # ---- crawl trigger -----------------------------------------------------

    def _crawl_status(self) -> dict:
        """The one shape both the poller and the POST response return, so
        the page never has to reconcile two descriptions of the same run."""
        if self.crawl is None:
            return {
                "enabled": False, "allow_manual": False, "running": False,
                "status": "disabled", "stale_after_hours": self.stale_after_hours,
                "catalog": [],
                "message": "This dashboard was opened read-only; crawls are not "
                           "triggered from here.",
            }
        state = self.crawl.status()
        state["enabled"] = True
        state["stale_after_hours"] = self.stale_after_hours
        # Static per-collector list for the "run this one" buttons. Cheap
        # (local YAML, no network) and only read on page load / while idle.
        state["catalog"] = self.crawl.catalog()
        return state

    def _handle_crawl_post(self):
        if self.crawl is None:
            _json_error(self, 503, "crawl_disabled",
                        "This dashboard was opened read-only; crawls are not "
                        "triggered from here.")
            return

        data = _read_json_body(self, self.max_body)
        if data is None:
            return

        # Same CSRF gate as review writes. Starting a crawl reaches out to
        # OEM sites and can send Discord notifications — strictly more
        # side-effecting than saving a review, so it gets no weaker a check.
        token = self.headers.get("X-OEM-Radar-CSRF") or data.get("csrf_token")
        if not token or not secrets.compare_digest(str(token), self.csrf_token):
            _json_error(self, 403, "csrf_invalid",
                        "Missing or invalid CSRF token (X-OEM-Radar-CSRF header "
                        "or csrf_token field)")
            return

        unknown = set(data.keys()) - {"force", "source", "csrf_token"}
        if unknown:
            _json_error(self, 400, "unknown_fields",
                        f"Unknown fields: {', '.join(sorted(unknown))}")
            return

        force = data.get("force", False)
        if not isinstance(force, bool):
            _json_error(self, 400, "invalid_force", "force must be a boolean")
            return
        source = data.get("source")
        if source is not None and not isinstance(source, str):
            _json_error(self, 400, "invalid_source", "source must be a string or null")
            return

        # A full sweep (no source named) is "Run all collectors": fleet
        # policy excludes any collector whose normal runtime exceeds 5
        # minutes from it (see SourceConfig.heavy). Naming a source
        # explicitly always runs it, heavy or not -- that is the
        # individually-runnable escape hatch the policy requires.
        accepted, reason, state = self.crawl.trigger(
            force=force, only_source=source, include_heavy=source is not None)
        state["enabled"] = True
        state["stale_after_hours"] = self.stale_after_hours
        state["catalog"] = self.crawl.catalog()
        if accepted:
            self._send(202, json.dumps({"ok": True, "state": state}).encode("utf-8"),
                       "application/json")
            return
        # Refusing is not an error the user caused — say which case it is.
        status = 409 if reason == "already_running" else 403
        body = json.dumps({
            "error": {"code": reason, "message": (
                "A crawl is already running." if reason == "already_running"
                else "Manual crawls are disabled in config (dashboard."
                     "allow_manual_crawl).")},
            "state": state,
        }).encode("utf-8")
        self._send(status, body, "application/json")

    def _handle_mark_seen(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self.send_error(400)
            return
        if length > self.max_body:
            _json_error(self, 413, "body_too_large", f"Body exceeds {self.max_body} bytes")
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            _json_error(self, 400, "malformed_json", "Malformed JSON")
            return
        raw_dir = self.raw_dir or str(Path(self.db_path).parent / "raw")
        store = SqliteStore(self.db_path, raw_dir)
        try:
            names = None if payload.get("all") else payload.get("names")
            changed = store.mark_component_seen(names)
        finally:
            store.close()
        body = json.dumps({"ok": True, "changed": changed}).encode("utf-8")
        self._send(200, body, "application/json")

    def _handle_review_post(self, alert_id: int):
        data = _read_json_body(self, self.max_body)
        if data is None:
            return

        token = (
            self.headers.get("X-OEM-Radar-CSRF")
            or data.get("csrf_token")
            or data.get("_csrf")
        )
        if not token or not secrets.compare_digest(str(token), self.csrf_token):
            _json_error(self, 403, "csrf_invalid",
                        "Missing or invalid CSRF token (X-OEM-Radar-CSRF header or csrf_token field)")
            return

        allowed = {"outcome", "reason_codes", "reviewer_note", "reviewer", "change_note",
                   "csrf_token", "_csrf"}
        unknown = set(data.keys()) - allowed
        if unknown:
            _json_error(self, 400, "unknown_fields",
                        f"Unknown fields: {', '.join(sorted(unknown))}")
            return

        outcome = data.get("outcome")
        if not outcome or not isinstance(outcome, str):
            _json_error(self, 400, "missing_outcome", "outcome is required")
            return

        reason_codes = data.get("reason_codes", [])
        if reason_codes is not None and not isinstance(reason_codes, list):
            _json_error(self, 400, "invalid_reason_codes",
                        "reason_codes must be an array of strings")
            return

        raw_dir = self.raw_dir or str(Path(self.db_path).parent / "raw")
        store = SqliteStore(self.db_path, raw_dir)
        try:
            from ..core.feedback import FeedbackError
            try:
                rev = store.upsert_review(
                    alert_id,
                    outcome=outcome,
                    reason_codes=reason_codes,
                    reviewer_note=data.get("reviewer_note"),
                    reviewer=data.get("reviewer"),
                    change_note=data.get("change_note"),
                )
                # Fleet-wide QC-archive contract: the alert's first terminal
                # decision is transactionally archived (full snapshot +
                # provenance) to a separate DB and leaves the active queue
                # immediately (see collect()'s archived_alert_ids filter).
                # A later change-of-mind still updates alert_reviews above
                # (that is what alert_review_history is for) but does not
                # re-archive -- the UNIQUE(alert_id) constraint makes that
                # a no-op, never a duplicate or a crash.
                event_row = store.db.execute(
                    "SELECT id, product_key, change_type, field, old_value_json, "
                    "new_value_json, severity, meta_json, detected_at "
                    "FROM change_events WHERE id=?", (alert_id,),
                ).fetchone()
                archived = False
                if event_row is not None:
                    try:
                        self._qc_archive().archive(
                            event_row, outcome, reason_codes=reason_codes,
                            note=data.get("reviewer_note"),
                            decided_by=data.get("reviewer"),
                        )
                        archived = True
                    except AlreadyQCed:
                        archived = False  # already archived by an earlier decision
            except FeedbackError as fe:
                msg = str(fe)
                code = "validation_error"
                if "no change_event" in msg:
                    _json_error(self, 404, "not_found", msg)
                    return
                if "invalid outcome" in msg:
                    code = "invalid_outcome"
                elif "invalid reason code" in msg:
                    code = "invalid_reason_code"
                elif "exceeds" in msg:
                    code = "field_too_long"
                _json_error(self, 400, code, msg)
                return
        finally:
            store.close()

        hist_store = SqliteStore(self.db_path, raw_dir)
        try:
            history = hist_store.list_review_history(alert_id)
        finally:
            hist_store.close()

        body = json.dumps(
            {"ok": True, "review": rev, "history": history, "qc_archived": archived}
        ).encode("utf-8")
        self._send(200, body, "application/json")

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def require_loopback_host(host: str) -> None:
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
    if not loopback:
        raise ValueError("OEM Radar has no authenticated remote dashboard profile; host must be loopback")


def serve(
    db_path: str,
    host: str = "127.0.0.1",
    port: int = 8787,
    open_browser: bool = True,
    *,
    max_body: int = 16384,
    raw_dir: str | None = None,
    crawl=None,
    auto_crawl: bool = False,
    auto_crawl_force: bool = False,
    stale_after_hours: float = 6.0,
    allow_review_writes: bool = False,
) -> None:
    require_loopback_host(host)
    # Fleet Law 5, hard requirement: the dashboard NEVER starts a crawl on
    # its own just because it was opened. This is enforced independently at
    # three layers -- config defaults to auto_crawl_on_start=False, no
    # entry point (cli.py's build_dashboard_crawl_kwargs, launch_dashboard.py)
    # ever wires that config value through to here, and this check rejects
    # auto_crawl outright even if some future caller tries. There is no
    # config value or flag that can make this True reach serve_forever().
    if auto_crawl:
        raise ValueError(
            "OEM Radar dashboard never auto-starts a crawl on launch "
            "(fleet policy); auto_crawl/auto_crawl_force are not accepted here"
        )
    handler = partial(_Handler)
    _Handler.db_path = db_path
    _Handler.raw_dir = raw_dir or str(Path(db_path).parent / "raw")
    _Handler.max_body = max_body
    _Handler.csrf_token = _CSRF_TOKEN
    # `crawl` being non-None means the entry point explicitly authorized
    # *manual* triggering (dashboard.allow_manual_crawl, minus --no-crawl).
    # It is a human clicking a button in their own browser, once, same as
    # them typing `oem-radar run` in a terminal -- not something opening
    # the dashboard causes by itself.
    _Handler.crawl = crawl
    _Handler.crawl_mutations_enabled = crawl is not None
    _Handler.review_writes_enabled = bool(allow_review_writes)
    # M4.5 QC activation + manual-crawl activation: each capability is its
    # own opt-in, each still requires its own per-request CSRF header
    # (checked inside _handle_review_post / _handle_crawl_post). This gate
    # only answers "is *any* mutation capability authorized for this
    # launch" -- which one is decided per-path in do_POST.
    if allow_review_writes or _Handler.crawl_mutations_enabled:
        def _authorizer(headers) -> bool:
            return True
        _Handler.mutation_authorizer = _authorizer
    else:
        _Handler.mutation_authorizer = None
    _Handler.stale_after_hours = stale_after_hours
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    print(f"OEM Radar dashboard: {url}  (Ctrl+C to stop)")
    print("  CSRF token active for authorized writes (localhost model)")

    # Opening the dashboard never starts anything by itself (see above). If
    # manual crawl triggering is authorized, the button becomes live; if
    # not, the crawl bar stays informational only.
    if _Handler.crawl_mutations_enabled:
        print("  crawl trigger available (Run all collectors excludes "
              "collectors whose normal runtime exceeds 5 minutes; those "
              "stay individually runnable)")
    else:
        print("  read-only: crawl mutations are disabled for this launch "
              "(dashboard.allow_manual_crawl / --no-crawl)")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\ndashboard stopped")
    finally:
        httpd.server_close()
