"""Read-only Discovery view within OEM Radar's existing dashboard shell."""
from contextlib import closing
from html import escape
import json
import re
from urllib.parse import urlparse

from . import discovery as d
from .dashboard import _Handler
from .dashboard.render import UI_CSS, _ADAPTER, render_feedback_page

CSS = UI_CSS + _ADAPTER


def evidence_bytes(cfg, name):
    if not re.fullmatch(r'[a-f0-9]{64}', name):
        raise ValueError('Invalid evidence identifier')
    # Only content referenced by retained observations is addressable.
    allowed = set()
    for row in d.read_inbox(cfg):
        for observation in row['history']:
            allowed.update(json.loads(observation['copied']).values())
    if name not in allowed:
        raise ValueError('Unreferenced evidence')
    path = d.checked_path(cfg.data_dir / 'evidence', str(cfg.data_dir / 'evidence' / name))
    raw = d.read_bounded(path, d.MAX_FILE)
    if d.digest(raw) != name:
        raise ValueError('Owned evidence corruption')
    return raw


def render_discovery(cfg):
    h = lambda value: escape(str(value), quote=True)
    rows = d.read_inbox(cfg)
    counts = {label: sum(r['consumer_review'] == label for r in rows) for label in d.LABELS}
    cards = []
    for row in rows:
        p = row['payload']
        url = p['source_url']
        try:
            # Same pinned syntactic HTTPS restrictions; never resolve/fetch.
            module, _ = d.authenticate(cfg)
            module.safe_url(url)
            title = '<a rel="noopener noreferrer" href="' + h(url) + '">' + h(p['source_title']) + '</a>'
        except (ValueError, TypeError):
            title = h(p['source_title']) + ' (unsafe link withheld)'
        clocks = ''.join('<dt>' + h(key) + '</dt><dd>' + h(p[key]) + '</dd>' for key in ('source_published_at', 'source_published_at_original', 'observed_at', 'collected_at', 'first_observed_at'))
        history = []
        for observation in row['history']:
            copied = json.loads(observation['copied'])
            links = ' · '.join('<a href="/discovery/evidence/' + h(name) + '">Copied ' + h(kind) + '</a>' for kind, name in copied.items())
            history.append('<details><summary>Observation ' + h(observation['id']) + ' · ' + h(observation['imported_at']) + ' · ' + h(observation['evidence_status']) + '</summary>' + links + '<pre>' + h(json.dumps(dict(observation), ensure_ascii=False, indent=2)) + '</pre></details>')
        cards.append('<article class="card"><h2>' + title + '</h2><p>Third-party proposal/report — not product truth, admission or official evidence.</p><blockquote>' + h(p['supporting_passage']) + '</blockquote><p>Publisher: ' + h(p['publisher']) + ' · ' + h(p['source_descriptor']) + '</p><dl>' + clocks + '<dt>Imported at</dt><dd>' + h(row['imported_at']) + '</dd><dt>Producer review</dt><dd>' + h(p['review_state']) + '</dd><dt>Consumer editorial review</dt><dd>' + h(row['consumer_review']) + '</dd><dt>Evidence</dt><dd>' + h(row['evidence_status']) + ' ' + h(row['limitations']) + '</dd><dt>Uncertainties</dt><dd>' + h('; '.join(p['uncertainties'])) + '</dd></dl><p>' + h(row['producer_id']) + ' / ' + h(p['lead_id']) + '</p><h3>Change history and copied evidence</h3>' + ''.join(history) + '<details><summary>Editorial review history</summary><pre>' + h(json.dumps(row['review_history'], indent=2)) + '</pre></details></article>')
    return '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>OEM Radar · Discovery</title><style>' + CSS + 'pre{white-space:pre-wrap;overflow-wrap:anywhere}article{padding:20px;margin:16px 0;border:1px solid #777}dd{overflow-wrap:anywhere}</style></head><body><nav class="crumbs"><a href="/">Overview</a> · <a href="/?tab=evidence">Evidence</a> · <a href="/discovery">Discovery</a></nav><main class="wrap"><h1>Discovery · proposals only</h1><p>' + str(len(rows)) + ' retained proposals · all retained leads shown (no cap)</p><p>' + h(d.dumps(counts)) + '</p><a href="/api/discovery">All retained proposals and history (JSON)</a>' + ''.join(cards) + '</main></body></html>'


def dashboard_handler(cfg, db_path):
    if not cfg.enabled:
        raise ValueError('Discovery is disabled')

    class DiscoveryHandler(_Handler):
        crawl = None
        mutation_authorizer = None

        def _readonly(self):
            # URI mode=ro, never SqliteStore or registry sync.
            return d.readonly(db_path)

        def _send(self, status, body, ctype):
            if ctype.startswith('text/html') and b'class="crumbs"' in body and b'href="/discovery"' not in body:
                body = body.replace(b'<nav class="crumbs">', b'<nav class="crumbs"><a href="/discovery">Discovery</a>', 1)
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            if ctype.startswith('text/plain'):
                self.send_header('Content-Security-Policy', "default-src 'none'; sandbox")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.send_error(405, 'Manual Discovery dashboard is GET-only')

        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path.startswith('/discovery/evidence/'):
                    try:
                        raw = evidence_bytes(cfg, path.removeprefix('/discovery/evidence/'))
                    except (ValueError, OSError):
                        self.send_error(404)
                        return
                    self._send(200, raw, 'text/plain; charset=utf-8')
                elif path == '/discovery':
                    self._send(200, render_discovery(cfg).encode('utf8'), 'text/html; charset=utf-8')
                elif path == '/api/discovery':
                    self._send(200, d.dumps(d.read_inbox(cfg)).encode('utf8'), 'application/json')
                elif path in ('/feedback', '/api/feedback/suggestions'):
                    # Legacy versions open SqliteStore on these GET routes.
                    # This manual launch instead uses a read-only catalogue.
                    with closing(self._readonly()) as conn:
                        suggestions = [dict(zip([c[0] for c in cursor.description], row)) for cursor in [conn.execute('SELECT * FROM rule_suggestions')] for row in cursor]
                    if path == '/api/feedback/suggestions':
                        self._send(200, d.dumps({'suggestions': suggestions}).encode('utf8'), 'application/json')
                    else:
                        from .core.feedback_analytics import build_metrics_payload
                        with closing(self._readonly()) as conn:
                            metrics = build_metrics_payload(conn)
                        self._send(200, render_feedback_page(metrics, suggestions, csrf_token='').encode('utf8'), 'text/html; charset=utf-8')
                elif path in ('/', '/index.html', '/api/data', '/api/baseline-events', '/api/crawl/status', '/api/manual-sources', '/api/feedback/metrics', '/api/feedback/reasons') or re.fullmatch(r'/(?:api/)?(?:alerts|evidence)/[0-9]+', path):
                    super().do_GET()
                else:
                    self.send_error(404)
            except Exception:
                self.send_error(500, 'Discovery read failed')

    DiscoveryHandler.db_path = db_path
    return DiscoveryHandler
