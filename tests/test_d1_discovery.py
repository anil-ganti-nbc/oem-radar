"""Offline qualification of the separate D1 proposal inbox."""
import json
import os
from pathlib import Path

import pytest

from oem_radar import discovery as d

# The accepted producer and captured publisher evidence are external prerequisites,
# never vendored into OEM Radar. An explicit bad binding must fail, not skip.
_EXTERNAL_ROOT = os.environ.get('OEM_RADAR_D1_ROOT')
ROOT = Path(_EXTERNAL_ROOT) if _EXTERNAL_ROOT else Path(__file__).parent / '__external_d1_not_configured__'
if _EXTERNAL_ROOT:
    required = [ROOT / 'app/d1.py', ROOT / 'app/profiles.json', ROOT / 'inbox/leads.jsonl']
    if not ROOT.is_absolute() or not all(path.is_file() for path in required):
        raise RuntimeError('OEM_RADAR_D1_ROOT must name an absolute retained D1 app/inbox fixture root')
pytestmark = pytest.mark.skipif(
    not _EXTERNAL_ROOT,
    reason='External accepted D1 app/capture fixture not configured: set OEM_RADAR_D1_ROOT; real-evidence qualification NOT RUN',
)


def settings(tmp_path):
    return d.Settings(producer_id='accepted-d1', producer=ROOT / 'app/d1.py',
                      profiles=ROOT / 'app/profiles.json', evidence_root=ROOT / 'inbox',
                      data_dir=tmp_path / 'consumer', enabled=True)


def test_real_contract_routing_and_atomic_late_failure(tmp_path):
    cfg = settings(tmp_path)
    result = d.import_export(cfg, ROOT / 'inbox/leads.jsonl')
    original = [json.loads(x) for x in (ROOT / 'inbox/leads.jsonl').read_text(encoding='utf8').splitlines()]
    computing = [x for x in original if x['category_profile'] == 'computing']
    assert result['parsed'] == len(original)
    assert result['accepted'] == len(computing) == 5
    assert result['excluded'] == {'watches: unsupported profile': 14}
    rows = d.read_inbox(cfg)
    assert {x['payload']['lead_id'] for x in rows} == {x['lead_id'] for x in computing}
    assert all(x['payload'] in computing and x['evidence_status'] == 'verified' for x in rows)
    assert all(x['payload']['brand'] is None and x['payload']['model'] is None for x in rows)
    before = cfg.database.read_bytes()
    bad = tmp_path / 'bad.jsonl'
    bad.write_text(json.dumps(computing[0]) + '\n{"schema_version":"bad"}\n', encoding='utf8')
    with pytest.raises(ValueError):
        d.import_export(cfg, bad)
    assert cfg.database.read_bytes() == before
    assert d.import_export(cfg, ROOT / 'inbox/leads.jsonl')['unchanged'] == 5


def one_export(tmp_path):
    p = next(json.loads(x) for x in (ROOT / 'inbox/leads.jsonl').read_text(encoding='utf8').splitlines() if json.loads(x)['category_profile'] == 'computing')
    path = tmp_path / 'one.jsonl'
    path.write_text(json.dumps(p) + '\n', encoding='utf8')
    return path, p


def test_review_history_namespace_and_omissions(tmp_path):
    from dataclasses import replace
    cfg = settings(tmp_path)
    path, p = one_export(tmp_path)
    d.import_export(cfg, path)
    d.review(cfg, p['lead_id'], 'editorial_keep')
    d.import_export(cfg, path)
    assert d.read_inbox(cfg)[0]['consumer_review'] == 'editorial_keep'
    p['uncertainties'].append('Unfamiliar maker remains unresolved')
    path.write_text(json.dumps(p), encoding='utf8')
    assert d.import_export(cfg, path)['changed'] == 1
    rows = d.read_inbox(cfg)
    assert len(rows[0]['history']) == 2
    assert rows[0]['consumer_review'] == 'editorial_keep'
    assert rows[0]['payload']['review_state'] == 'unreviewed'
    assert d.import_export(replace(cfg, producer_id='other-producer'), path)['inserted'] == 1
    path.write_text('', encoding='utf8')
    d.import_export(cfg, path)
    assert len(d.read_inbox(cfg)) == 2
    assert len(d.read_inbox(replace(cfg))[0]['history']) == 2
    before = cfg.database.read_bytes()
    with pytest.raises(ValueError, match='disabled'):
        d.import_export(replace(cfg, enabled=False), path)
    assert cfg.database.read_bytes() == before


def test_refresh_failed_partial_and_complete_are_atomic(tmp_path, monkeypatch):
    import subprocess
    cfg = settings(tmp_path)
    path, p = one_export(tmp_path)
    d.import_export(cfg, path)
    pointer = (cfg.data_dir / 'CURRENT').read_bytes()
    def fake(argv, **kwargs):
        assert argv[:4] == [d.sys.executable, '-I', '-B', str(cfg.producer)]
        assert argv[4:7] == ['run', '--config', argv[6]]
        assert '--category' not in argv
        projection = json.loads(Path(argv[6]).read_text(encoding='utf8'))
        original = json.loads(cfg.profiles.read_text(encoding='utf8'))
        assert projection['profiles'] == [original['profiles'][0]]
        stage = Path(argv[8])
        ev = stage / 'evidence'
        ev.mkdir(parents=True)
        rewritten = json.loads(json.dumps(p))
        for kind in ('text', 'capture'):
            source = Path(p['evidence'][kind + '_file'])
            target = ev / source.name
            target.write_bytes(source.read_bytes())
            rewritten['evidence'][kind + '_file'] = str(target)
        (stage / 'leads.jsonl').write_text(json.dumps(rewritten), encoding='utf8')
        return subprocess.CompletedProcess(argv, fake.code, json.dumps({'status': fake.status}), '')
    monkeypatch.setattr(d.subprocess, 'run', fake)
    for code, status in [(2, 'FAILED'), (0, 'PARTIAL'), (1, 'COMPLETE')]:
        fake.code, fake.status = code, status
        with pytest.raises(ValueError):
            d.refresh(cfg)
        assert (cfg.data_dir / 'CURRENT').read_bytes() == pointer
    fake.code, fake.status = 0, 'COMPLETE'
    assert d.refresh(cfg)['status'] == 'IMPORTED'
    assert len(d.read_inbox(cfg)) == 1


def test_discovery_dashboard_real_get_is_readonly(tmp_path, monkeypatch):
    import http.client
    import threading
    from oem_radar.dashboard import _Handler
    from oem_radar.providers.sqlite import SqliteStore
    from http.server import ThreadingHTTPServer
    cfg = settings(tmp_path)
    path, p = one_export(tmp_path)
    d.import_export(cfg, path)
    catalog = tmp_path / 'catalog.db'
    store = SqliteStore(str(catalog), str(tmp_path / 'raw'))
    man = store.ensure_manufacturer('Unfamiliar OEM', None, [])
    store.ensure_source('isolated', man, 'shopify', 'https://example.com', {})
    from oem_radar.core.models import ChangeEvent, ChangeType, Severity
    event = store.record_event(ChangeEvent(product_key='isolated:one', change_type=ChangeType.NEW_PRODUCT, severity=Severity.NOTABLE))
    store.upsert_review(event, outcome='HIT', reason_codes=['VALID_CONFIRMATION_SIGNAL'])
    store.close()
    import sqlite3
    def logical():
        with sqlite3.connect(catalog) as conn:
            return '\n'.join(conn.iterdump())
    before = logical()
    import oem_radar.dashboard as dashboard
    def denied(*a, **k):
        pytest.fail('Forbidden viewing side effect')
    monkeypatch.setattr(dashboard, 'SqliteStore', denied)
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'request', denied)
    from oem_radar.core import runner
    monkeypatch.setattr(runner, 'run_all', denied)
    handler = d.dashboard_handler(cfg, str(catalog))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for route in ['/', '/api/data', '/discovery', '/api/discovery', '/feedback', '/api/feedback/suggestions']:
            client = http.client.HTTPConnection('127.0.0.1', server.server_port)
            client.request('GET', route)
            response = client.getresponse()
            body = response.read()
            assert response.status == 200, (route, body)
            if route == '/':
                assert b'href="/discovery"' in body
            if route == '/discovery':
                assert p['source_title'].encode('utf8') in body
                assert b'1 retained proposals' in body
                assert b'Consumer editorial review' in body
            client.close()
        blob = d.read_inbox(cfg)[0]['copied']['text']
        client = http.client.HTTPConnection('127.0.0.1', server.server_port)
        client.request('GET', '/discovery/evidence/' + blob)
        response = client.getresponse()
        assert response.status == 200
        assert response.getheader('Content-Type') == 'text/plain; charset=utf-8'
        assert response.getheader('X-Content-Type-Options') == 'nosniff'
        assert response.read() == Path(p['evidence']['text_file']).read_bytes()
        client.close()
        for route in ['/discovery/evidence/../../catalog.db', '/discovery/evidence/' + '0' * 64]:
            client = http.client.HTTPConnection('127.0.0.1', server.server_port)
            client.request('GET', route)
            response = client.getresponse()
            assert response.status == 404
            response.read()
            client.close()
        client = http.client.HTTPConnection('127.0.0.1', server.server_port)
        client.request('POST', '/api/discovery/review', body='{}')
        response = client.getresponse()
        assert response.status == 405
        response.read()
        client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert logical() == before


@pytest.mark.parametrize('bad', ['[]', 'null', '{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}', '{"schema_version":"v1"}', '{"unfinished":'])
def test_malformed_input_preserves_previous_generation(tmp_path, bad):
    cfg = settings(tmp_path)
    path, p = one_export(tmp_path)
    d.import_export(cfg, path)
    pointer = (cfg.data_dir / 'CURRENT').read_bytes()
    path.write_text(json.dumps(p) + '\n' + bad, encoding='utf8')
    with pytest.raises((ValueError, TypeError)):
        d.import_export(cfg, path)
    assert (cfg.data_dir / 'CURRENT').read_bytes() == pointer


def test_evidence_root_missing_bounds_and_restart(tmp_path, monkeypatch):
    from dataclasses import replace
    cfg = settings(tmp_path)
    path, p = one_export(tmp_path)
    local = tmp_path / 'producer-evidence'
    local.mkdir()
    for kind in ('text', 'capture'):
        original = Path(p['evidence'][kind + '_file'])
        target = local / original.name
        target.write_bytes(original.read_bytes())
        p['evidence'][kind + '_file'] = str(target)
    cfg = replace(cfg, evidence_root=local)
    path.write_text(json.dumps(p), encoding='utf8')
    d.import_export(cfg, path)
    text = Path(p['evidence']['text_file'])
    text.unlink()
    d.import_export(cfg, path)
    assert d.read_inbox(cfg)[0]['evidence_status'] == 'unavailable/quarantined'
    assert len(d.read_inbox(cfg)[0]['history']) == 2
    # Copied evidence from the earlier observation is independent of originals.
    earlier = json.loads(d.read_inbox(cfg)[0]['history'][0]['copied'])['text']
    monkeypatch.chdir(tmp_path)
    assert d.evidence_bytes(cfg, earlier)
    p['evidence']['text_file'] = str(tmp_path / 'host-secret.txt')
    path.write_text(json.dumps(p), encoding='utf8')
    with pytest.raises(ValueError, match='escape'):
        d.import_export(cfg, path)
    p['evidence']['text_file'] = str(local / '..' / 'host-secret.txt')
    path.write_text(json.dumps(p), encoding='utf8')
    with pytest.raises(ValueError, match='Unsafe'):
        d.import_export(cfg, path)
    p['evidence']['text_file'] = str(local / 'missing.txt')
    p['evidence']['length'] += 1
    path.write_text(json.dumps(p), encoding='utf8')
    with pytest.raises(ValueError, match='bounds'):
        d.import_export(cfg, path)


def test_manual_cli_enable_disable_restart_and_no_startup_writes(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    env = dict(os.environ, PYTHONPATH=str(Path(d.__file__).parents[1]), PYTHONDONTWRITEBYTECODE='1')
    config = tmp_path / 'discovery.json'
    data = tmp_path / 'owned'
    def cli(*args):
        result = subprocess.run([sys.executable, '-B', '-m', 'oem_radar.cli', 'discovery', '--settings', str(config), *map(str, args)], cwd=tmp_path, env=env, capture_output=True, text=True)
        return result.returncode, json.loads(result.stdout)
    code, result = cli('configure', '--producer-id', 'accepted-d1', '--producer', ROOT / 'app/d1.py', '--profiles', ROOT / 'app/profiles.json', '--evidence-root', ROOT / 'inbox', '--data-dir', data)
    assert code == 0 and result['enabled'] is False
    assert cli('import', ROOT / 'inbox/leads.jsonl')[0] == 2
    assert not data.exists()
    assert cli('enable')[0] == 0
    code, result = cli('import', ROOT / 'inbox/leads.jsonl')
    assert code == 0 and result['accepted'] == 5
    code, result = cli('list')
    assert code == 0 and len(result['proposals']) == 5
    lead = result['proposals'][0]['lead_id']
    assert cli('review', lead, '--label', 'editorial_research')[0] == 0
    assert cli('list')[1]['proposals'][0]['consumer_review'] == 'editorial_research'
    before = (data / 'CURRENT').read_bytes()
    assert cli('disable')[0] == 0
    assert cli('import', ROOT / 'inbox/leads.jsonl')[0] == 2
    assert (data / 'CURRENT').read_bytes() == before
    # Manual launch delegates to existing serve but never legacy cmd_dashboard.
    from oem_radar.cli import main
    import oem_radar.dashboard as dashboard
    from oem_radar import cli as module
    monkeypatch.setattr(module, 'sync_registry_before_serve', lambda *a, **k: pytest.fail('registry sync'))
    called = []
    monkeypatch.setattr(dashboard, 'serve', lambda *a, **kw: called.append((a, kw)))
    assert cli('enable')[0] == 0
    import sqlite3
    catalog = tmp_path / 'read-only-catalog.db'
    with sqlite3.connect(catalog) as conn:
        conn.execute('CREATE TABLE sentinel(value)')
    assert main(['discovery', '--settings', str(config), 'dashboard', '--catalog', str(catalog), '--no-browser']) == 0
    assert called[0][1]['discovery_settings'].enabled
    assert not called[0][1].get('crawl')


from test_dashboard import populated_db  # reuse representative isolated product fixture


def test_full_catalogue_logical_isolation(populated_db, tmp_path, monkeypatch):
    import sqlite3
    import http.client
    import threading
    from http.server import ThreadingHTTPServer
    import oem_radar.dashboard as dashboard
    from oem_radar.dashboard.data import collect
    from oem_radar.providers.sqlite import connect_readonly
    def snapshot():
        conn = sqlite3.connect(populated_db)
        try:
            return '\n'.join(conn.iterdump())
        finally:
            conn.close()
    conn = connect_readonly(populated_db)
    metrics_before = collect(conn)
    conn.close()
    before = snapshot()
    cfg = settings(tmp_path)
    d.import_export(cfg, ROOT / 'inbox/leads.jsonl')
    def denied(*a, **kw):
        pytest.fail('Catalogue migration, collection or delivery attempted')
    monkeypatch.setattr(dashboard, 'SqliteStore', denied)
    from oem_radar.core import runner
    from oem_radar.providers.discord import DiscordNotifier
    monkeypatch.setattr(runner, 'run_all', denied)
    monkeypatch.setattr(DiscordNotifier, 'drain', denied)
    monkeypatch.setattr(DiscordNotifier, 'enqueue', denied)
    server = ThreadingHTTPServer(('127.0.0.1', 0), d.dashboard_handler(cfg, populated_db))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for route in ['/', '/discovery', '/api/discovery', '/api/data', '/feedback', '/api/feedback/metrics', '/api/feedback/suggestions']:
            client = http.client.HTTPConnection('127.0.0.1', server.server_port)
            client.request('GET', route)
            response = client.getresponse()
            assert response.status == 200, response.read()
            response.read()
            client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert snapshot() == before
    conn = connect_readonly(populated_db)
    after = collect(conn)
    conn.close()
    assert after['summary'] == metrics_before['summary']
    assert after['feedback_summary'] == metrics_before['feedback_summary']
    assert after['summary']['products'] >= 3


def test_links_reparse_and_atomic_interruption(tmp_path, monkeypatch):
    import os
    import subprocess
    cfg = settings(tmp_path)
    path, p = one_export(tmp_path)
    d.import_export(cfg, path)
    pointer = (cfg.data_dir / 'CURRENT').read_bytes()
    p['uncertainties'].append('New uncertainty')
    path.write_text(json.dumps(p), encoding='utf8')
    original_replace = d.os.replace
    def interrupt(source, target):
        if Path(target).name == 'CURRENT':
            raise KeyboardInterrupt('simulated interruption before publication')
        return original_replace(source, target)
    monkeypatch.setattr(d.os, 'replace', interrupt)
    with pytest.raises(KeyboardInterrupt):
        d.import_export(cfg, path)
    assert (cfg.data_dir / 'CURRENT').read_bytes() == pointer
    monkeypatch.setattr(d.os, 'replace', original_replace)
    outside = tmp_path / 'outside'
    outside.mkdir()
    root = tmp_path / 'allowed'
    root.mkdir()
    junction = root / 'junction'
    if os.name == 'nt':
        result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(junction), str(outside)], capture_output=True)
        assert result.returncode == 0, result.stderr
    else:
        junction.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='links/junctions'):
        d.checked_path(root, str(junction / 'secret.txt'))
    secret = outside / 'secret.txt'
    secret.write_text('not evidence', encoding='utf8')
    hardlink = root / 'hardlink.txt'
    os.link(secret, hardlink)
    with pytest.raises(ValueError, match='Unsuitable'):
        d.checked_path(root, str(hardlink))


def test_render_escapes_html_and_withholds_unsafe_links(tmp_path, monkeypatch):
    from oem_radar.discovery_dashboard import render_discovery
    cfg = settings(tmp_path)
    path, p = one_export(tmp_path)
    d.import_export(cfg, path)
    rows = d.read_inbox(cfg)
    rows[0]['payload']['source_title'] = '<img src=x onerror=alert(1)>'
    rows[0]['payload']['supporting_passage'] = '</blockquote><script>alert(1)</script>'
    rows[0]['payload']['source_url'] = 'javascript:alert(1)'
    monkeypatch.setattr(d, 'read_inbox', lambda cfg: rows)
    page = render_discovery(cfg)
    assert '<img src=x' not in page and '<script>alert(1)' not in page
    assert '&lt;img src=x' in page and '&lt;/blockquote&gt;' in page
    assert 'href="javascript:' not in page
    assert 'unsafe link withheld' in page


def test_changed_literal_evidence_and_unfamiliar_maker(tmp_path):
    from dataclasses import replace
    import sqlite3
    cfg = replace(settings(tmp_path), evidence_root=tmp_path / 'synthetic-producer')
    cfg.evidence_root.mkdir()
    module, profiles = d.authenticate(cfg)
    profile = profiles['profiles'][0]
    source = profile['sources'][0]
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE leads(id TEXT, first_observed TEXT, review_state TEXT)')
    path = tmp_path / 'synthetic.jsonl'
    for version, content in enumerate(['Unfamiliar Qzx maker introduces mini PC with 16GB RAM. 中文', 'Unfamiliar Qzx maker introduces mini PC with 32GB RAM. 中文']):
        raw = ('<rss><channel><item><title>Qzx launches a mini PC</title><link>https://example.com/qzx-device</link><pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate><description>' + content + '</description></item></channel></rss>').encode('utf8')
        capture_path = cfg.evidence_root / (d.digest(raw) + '.xml')
        capture_path.write_bytes(raw)
        doc = module.parse_feed(raw)[0]
        payload = module.proposal(conn, cfg.evidence_root, profile, source, doc, {'capture_file': str(capture_path), 'capture_sha256': d.digest(raw), 'response_url': source['url']}, '2026-10-26T11:00:00+00:00')
        path.write_text(json.dumps(payload), encoding='utf8')
        result = d.import_export(cfg, path)
        assert result['inserted' if version == 0 else 'changed'] == 1
    conn.close()
    row = d.read_inbox(cfg)[0]
    assert len(row['history']) == 2
    assert row['payload']['brand'] is None
    assert row['payload']['observed_at'] == '2026-10-26T11:00:00+00:00'
    assert d.evidence_bytes(cfg, row['copied']['text']).endswith('32GB RAM. 中文'.encode('utf8'))


def test_refresh_real_offline_child_and_timeout(tmp_path, monkeypatch):
    import subprocess
    import sys
    cfg = settings(tmp_path)
    path, p = one_export(tmp_path)
    d.import_export(cfg, path)
    pointer = (cfg.data_dir / 'CURRENT').read_bytes()
    script = tmp_path / 'fake_producer.py'
    script.write_text('import sys,json,pathlib,shutil\np=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf8"))\nstate=pathlib.Path(sys.argv[2]); ev=state/"evidence"; ev.mkdir()\nfor kind in ("text","capture"):\n source=pathlib.Path(p["evidence"][kind+"_file"]); target=ev/source.name; shutil.copyfile(source,target); p["evidence"][kind+"_file"]=str(target)\n(state/"leads.jsonl").write_text(json.dumps(p),encoding="utf8")\nprint(json.dumps({"status":sys.argv[3]}))\nsys.exit(int(sys.argv[4]))\n', encoding='utf8')
    real_run = subprocess.run
    mode = ['FAILED', '2']
    def execute(argv, **kwargs):
        return real_run([sys.executable, '-I', '-B', str(script), str(path), argv[8], *mode], **kwargs)
    monkeypatch.setattr(d.subprocess, 'run', execute)
    for status, code in [('FAILED','2'), ('PARTIAL','0')]:
        mode[:] = [status, code]
        with pytest.raises(ValueError):
            d.refresh(cfg)
        assert (cfg.data_dir / 'CURRENT').read_bytes() == pointer
    mode[:] = ['COMPLETE', '0']
    assert d.refresh(cfg)['status'] == 'IMPORTED'
    pointer = (cfg.data_dir / 'CURRENT').read_bytes()
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('fake-producer', 120)
    monkeypatch.setattr(d.subprocess, 'run', timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        d.refresh(cfg)
    assert (cfg.data_dir / 'CURRENT').read_bytes() == pointer


def test_empty_discovery_get_does_not_initialize(tmp_path):
    from oem_radar.discovery_dashboard import render_discovery
    cfg = settings(tmp_path)
    assert '0 retained proposals' in render_discovery(cfg)
    assert not cfg.data_dir.exists()
