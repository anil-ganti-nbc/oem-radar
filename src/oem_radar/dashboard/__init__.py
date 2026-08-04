"""Local read-only dashboard (M12). Stdlib-only HTTP server over the SQLite
DB; opens the DB read-only per request so it is safe to run while a crawl
writes (WAL). Clickable store links go straight to each product's source_url.
"""

from __future__ import annotations

import logging
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import json

from ..providers.sqlite import SqliteStore, connect_readonly
from .data import collect
from .render import render

log = logging.getLogger("oem_radar.dashboard")


class _Handler(BaseHTTPRequestHandler):
    db_path: str = ""

    def log_message(self, *a):  # keep the console clean
        pass

    def _query(self):
        conn = connect_readonly(self.db_path)
        try:
            return collect(conn)
        finally:
            conn.close()

    def do_POST(self):
        """The dashboard's ONE write action (owner request): curate the
        known-hardware DB. Opens read-write only for this operation."""
        if self.path != "/api/mark-seen":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or "{}")
            from pathlib import Path
            raw_dir = str(Path(self.db_path).parent / "raw")
            store = SqliteStore(self.db_path, raw_dir)  # read-write; migrate() idempotent
            try:
                names = None if payload.get("all") else payload.get("names")
                changed = store.mark_component_seen(names)
            finally:
                store.close()
            body = json.dumps({"ok": True, "changed": changed}).encode("utf-8")
        except Exception as exc:
            log.exception("mark-seen failed")
            self.send_error(500, str(exc))
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path.startswith("/api/data"):
                body = json.dumps(self._query()).encode("utf-8")
                ctype = "application/json"
            elif self.path in ("/", "/index.html"):
                body = render(self._query()).encode("utf-8")
                ctype = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
        except Exception as exc:  # never crash the server on a bad read
            log.exception("dashboard query failed")
            self.send_error(500, str(exc))
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(db_path: str, host: str = "127.0.0.1", port: int = 8787,
          open_browser: bool = True) -> None:
    handler = partial(_Handler)
    _Handler.db_path = db_path
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    print(f"OEM Radar dashboard: {url}  (Ctrl+C to stop)")
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
