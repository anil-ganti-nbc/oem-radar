"""Manual D1 proposal intake. No catalogue, crawler or notification dependencies.

CURRENT is the atomic publication point for a sidecar/export generation. Readers
never create files. Producer code is executed only after fixed hash authentication.
"""
from __future__ import annotations

import ast
from contextlib import closing
import copy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import types
import uuid

IDENTITY = '5e138fabb1918e2fec8a570348c4a69070a4b00bdc2d488dea86d07ac45ad118'
CODE_SHA = 'eaac15eb9ad414b2bbdd63870b70bbc1a8b2d93d9f21f1308c43db3217c69bf1'
PROFILES_SHA = 'a2ba255264a5599ac717b2c3a464e34c7f1a32564e55ca6949937afa5aa1375e'
MAX_EXPORT = 32 * 1024 * 1024
MAX_FILE = 5 * 1024 * 1024
LABELS = ('unreviewed', 'editorial_keep', 'editorial_dismiss', 'editorial_research')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def dumps(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False)


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('Duplicate JSON key: ' + key)
            out[key] = value
        return out
    def constant(value):
        raise ValueError('Nonfinite JSON number: ' + value)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    # Overflow such as 1e999 is not passed to parse_constant.
    dumps(value)
    return value


@dataclass(frozen=True)
class Settings:
    producer_id: str
    producer: Path
    profiles: Path
    evidence_root: Path
    data_dir: Path
    enabled: bool = False

    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', self.producer_id):
            raise ValueError('Explicit stable producer_id required')
        for field in ('producer', 'profiles', 'evidence_root', 'data_dir'):
            value = Path(getattr(self, field))
            if not value.is_absolute():
                raise ValueError('Settings paths must be absolute: ' + field)
            object.__setattr__(self, field, value)
        if self.data_dir.resolve().is_relative_to(self.evidence_root.resolve()):
            raise ValueError('Consumer data must be outside producer evidence root')

    @property
    def generation(self):
        pointer = self.data_dir / 'CURRENT'
        if not pointer.exists():
            return None
        name = pointer.read_text(encoding='ascii').strip()
        if not re.fullmatch(r'[a-f0-9]{32}', name):
            raise ValueError('Invalid sidecar generation')
        return self.data_dir / 'versions' / name

    @property
    def database(self):
        generation = self.generation
        return (generation if generation else self.data_dir / 'uninitialized') / 'proposals.sqlite3'


def authenticate(cfg):
    raw = cfg.producer.read_bytes()
    profiles = cfg.profiles.read_bytes()
    if digest(raw) != CODE_SHA or digest(profiles) != PROFILES_SHA:
        raise ValueError('Accepted D1 code/profile pin mismatch')
    module = types.ModuleType('_oem_pinned_d1')
    module.__file__ = str(cfg.producer)
    exec(compile(raw, str(cfg.producer), 'exec'), module.__dict__)
    # Reuse the exact delivered structural checks before its file I/O. This
    # allows explicit unavailable observations without weakening verified ones.
    tree = ast.parse(raw)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'validate')
    prefix = []
    for node in fn.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'raw' for t in node.targets):
            break
        prefix.append(node)
    fn.name = 'validate_structure'
    fn.body = prefix
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<pinned D1 structural validator>', 'exec'), module.__dict__)
    return module, strict_json(profiles)


def checked_path(root, supplied):
    """Reject lexical escapes/reparse points BEFORE opening a supplied file."""
    root = Path(root)
    path = Path(supplied)
    if not path.is_absolute() or '..' in path.parts or any(':' in p for p in path.parts[1:]):
        raise ValueError('Unsafe evidence path')
    if not path.is_relative_to(root):
        raise ValueError('Evidence root escape')
    for component in reversed([path, *path.parents]):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Evidence links/junctions prohibited')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Resolved evidence escape')
    try:
        info = path.stat()
    except FileNotFoundError:
        return path
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
        raise ValueError('Unsuitable evidence file')
    return path


def read_bounded(path, limit):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Input byte limit exceeded')
    return raw


def prepare(cfg, export):
    module, _ = authenticate(cfg)
    if not cfg.evidence_root.is_dir():
        raise ValueError('Configured evidence root must be an existing directory')
    checked_path(cfg.evidence_root, str(cfg.evidence_root / '__root_probe__'))
    raw = read_bounded(export, MAX_EXPORT)
    lines = raw.decode('utf-8').splitlines()
    if len(lines) > 10000:
        raise ValueError('Record limit exceeded')
    prepared, seen, excluded, total_bytes = [], set(), {}, 0
    for line in lines:
        if not line.strip():
            continue
        if len(line.encode('utf8')) > 1024 * 1024:
            raise ValueError('Line limit exceeded')
        payload = strict_json(line)
        if not isinstance(payload, dict):
            raise ValueError('Proposal must be object')
        module.validate_structure(payload)
        if payload['lead_id'] in seen:
            raise ValueError('Duplicate lead ID')
        seen.add(payload['lead_id'])
        e = payload['evidence']
        for key in ('text_sha256', 'capture_sha256'):
            if not isinstance(e[key], str) or not re.fullmatch('[a-f0-9]{64}', e[key]):
                raise ValueError('Invalid evidence SHA256')
        if e['offset'] + e['length'] > MAX_FILE or e['length'] != len(payload['supporting_passage'].encode('utf8')):
            raise ValueError('Invalid evidence bounds')
        if payload['subject_text'] != payload['source_title']:
            raise ValueError('Subject/headline mismatch')
        if not isinstance(payload['media_metadata'], list) or payload['content_source_field'] is not None and not isinstance(payload['content_source_field'], str):
            raise ValueError('Invalid source metadata')
        blobs, unavailable = {}, []
        # Both references are checked before either is read.
        paths = {kind: checked_path(cfg.evidence_root, e[kind + '_file']) for kind in ('text', 'capture')}
        for kind, path in paths.items():
            try:
                data = read_bounded(path, MAX_FILE)
            except FileNotFoundError:
                unavailable.append(kind + ': missing reference')
                continue
            total_bytes += len(data)
            if total_bytes > 128 * 1024 * 1024:
                raise ValueError('Export evidence byte budget exceeded')
            if digest(data) != e[kind + '_sha256']:
                raise ValueError('Evidence SHA256 mismatch')
            blobs[str(path)] = data
        if str(paths['text']) in blobs:
            text = blobs[str(paths['text'])]
            text.decode('utf8')
            if e['offset'] + e['length'] > len(text) or text[e['offset']:e['offset'] + e['length']].decode('utf8') != payload['supporting_passage']:
                raise ValueError('Supporting passage not literal evidence')
        if not unavailable:
            # The unchanged validator sees ONLY already bounded, root-checked
            # bytes, not a second opening of input-controlled host paths.
            class CapturedPath:
                def __init__(self, value):
                    self.value = str(Path(value))
                def is_absolute(self):
                    return Path(self.value).is_absolute()
                def read_bytes(self):
                    return blobs[self.value]
            module.Path = CapturedPath
            try:
                module.validate(payload)
            finally:
                module.Path = Path
        if payload['category_profile'] != 'computing':
            reason = payload['category_profile'] + ': unsupported profile'
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        owned = {}
        for kind, path in paths.items():
            if str(path) in blobs:
                data = blobs[str(path)]
                owned[kind] = (digest(data), data)
        prepared.append((payload, owned, unavailable))
    return prepared, {'parsed': len(seen), 'accepted': len(prepared), 'excluded': excluded}


SCHEMA = '''
CREATE TABLE IF NOT EXISTS proposals (
 producer_id TEXT, lead_id TEXT, review TEXT NOT NULL, current_observation INTEGER,
 PRIMARY KEY(producer_id,lead_id));
CREATE TABLE IF NOT EXISTS observations (
 id INTEGER PRIMARY KEY, producer_id TEXT, lead_id TEXT, fingerprint TEXT,
 payload TEXT, copied TEXT, evidence_status TEXT, limitations TEXT, imported_at TEXT);
CREATE TABLE IF NOT EXISTS review_history (
 id INTEGER PRIMARY KEY, producer_id TEXT, lead_id TEXT, label TEXT, reviewed_at TEXT);
'''


def readonly(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def new_generation(cfg):
    directory = cfg.data_dir / 'versions' / uuid.uuid4().hex
    directory.mkdir(parents=True)
    database = directory / 'proposals.sqlite3'
    if cfg.database.exists():
        with closing(readonly(cfg.database)) as source, closing(sqlite3.connect(database)) as target:
            source.backup(target)
    conn = sqlite3.connect(database)
    conn.executescript(SCHEMA)
    return directory, conn


def publish(cfg, directory, conn):
    conn.commit()
    conn.close()
    # The consumer export is published WITH its matching sidecar by CURRENT.
    rows = read_database(directory / 'proposals.sqlite3')
    (directory / 'consumer.jsonl').write_text(''.join(dumps(row) + '\n' for row in rows), encoding='utf8')
    temp = cfg.data_dir / ('CURRENT.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(directory.name, encoding='ascii')
    os.replace(temp, cfg.data_dir / 'CURRENT')


def copy_blob(cfg, name, data):
    directory = cfg.data_dir / 'evidence'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if path.exists():
        if read_bounded(checked_path(directory, str(path)), MAX_FILE) != data:
            raise ValueError('Owned immutable evidence corruption')
    else:
        with path.open('xb') as stream:
            stream.write(data)
    return name


def import_export(cfg, export):
    if not cfg.enabled:
        raise ValueError('Discovery is disabled')
    prepared, result = prepare(cfg, export)  # NO consumer writes before full validation
    directory, conn = new_generation(cfg)
    result.update(inserted=0, changed=0, unchanged=0)
    try:
        with conn:
            for payload, blobs, unavailable in prepared:
                copied = {kind: copy_blob(cfg, name, data) for kind, (name, data) in blobs.items()}
                fingerprint = digest(dumps([payload, copied, unavailable]).encode())
                key = (cfg.producer_id, payload['lead_id'])
                previous = conn.execute('SELECT o.fingerprint FROM proposals p JOIN observations o ON o.id=p.current_observation WHERE p.producer_id=? AND p.lead_id=?', key).fetchone()
                if previous and previous[0] == fingerprint:
                    result['unchanged'] += 1
                    continue
                cursor = conn.execute('INSERT INTO observations(producer_id,lead_id,fingerprint,payload,copied,evidence_status,limitations,imported_at) VALUES(?,?,?,?,?,?,?,?)', (*key, fingerprint, dumps(payload), dumps(copied), 'unavailable/quarantined' if unavailable else 'verified', dumps(unavailable), datetime.now(timezone.utc).isoformat()))
                conn.execute('INSERT INTO proposals VALUES(?,?,?,?) ON CONFLICT(producer_id,lead_id) DO UPDATE SET current_observation=excluded.current_observation', (*key, 'unreviewed', cursor.lastrowid))
                result['changed' if previous else 'inserted'] += 1
        publish(cfg, directory, conn)
    except BaseException:
        conn.close()
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return dict(result, status='IMPORTED', producer_id=cfg.producer_id, export=str(directory / 'consumer.jsonl'))


def read_database(database):
    if not Path(database).exists():
        return []
    with closing(readonly(database)) as conn:
        conn.row_factory = sqlite3.Row
        rows = []
        for row in conn.execute('SELECT p.review AS consumer_review,o.* FROM proposals p JOIN observations o ON o.id=p.current_observation ORDER BY o.producer_id,o.lead_id'):
            item = dict(row)
            for key in ('payload', 'copied', 'limitations'):
                item[key] = json.loads(item[key])
            item['history'] = [dict(x) for x in conn.execute('SELECT * FROM observations WHERE producer_id=? AND lead_id=? ORDER BY id', (item['producer_id'], item['lead_id']))]
            item['review_history'] = [dict(x) for x in conn.execute('SELECT label,reviewed_at FROM review_history WHERE producer_id=? AND lead_id=? ORDER BY id', (item['producer_id'], item['lead_id']))]
            rows.append(item)
        return rows


def read_inbox(cfg):
    return read_database(cfg.database)


def review(cfg, lead_id, label):
    if not cfg.enabled:
        raise ValueError('Discovery is disabled')
    if label not in LABELS:
        raise ValueError('Explicit editorial label required')
    if not any(x['producer_id'] == cfg.producer_id and x['lead_id'] == lead_id for x in read_inbox(cfg)):
        raise ValueError('Unknown producer/lead key')
    directory, conn = new_generation(cfg)
    try:
        with conn:
            conn.execute('UPDATE proposals SET review=? WHERE producer_id=? AND lead_id=?', (label, cfg.producer_id, lead_id))
            conn.execute('INSERT INTO review_history(producer_id,lead_id,label,reviewed_at) VALUES(?,?,?,?)', (cfg.producer_id, lead_id, label, datetime.now(timezone.utc).isoformat()))
        publish(cfg, directory, conn)
    except BaseException:
        conn.close()
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return {'status': 'REVIEWED', 'producer_id': cfg.producer_id, 'lead_id': lead_id, 'consumer_review': label, 'product_admission': False}


def refresh(cfg):
    if not cfg.enabled:
        raise ValueError('Discovery is disabled')
    _, profiles = authenticate(cfg)
    computing = [p for p in profiles['profiles'] if p['id'] == 'computing']
    if len(computing) != 1:
        raise ValueError('Exactly one authenticated computing profile required')
    stage = cfg.data_dir / 'refresh-staging' / uuid.uuid4().hex
    stage.mkdir(parents=True)
    projection = stage / 'computing-profiles.json'
    projection.write_text(dumps(dict(profiles, profiles=computing)), encoding='utf8')
    state = stage / 'state'
    state.mkdir()
    # Never shell interpolation or unsupported category options. This is the
    # only live producer invocation, exercised with a fake process offline.
    result = subprocess.run([sys.executable, '-I', '-B', str(cfg.producer), 'run', '--config', str(projection), '--state', str(state)], capture_output=True, text=True, encoding='utf8', timeout=120, shell=False)
    try:
        report = strict_json(result.stdout)
    except (ValueError, TypeError) as exc:
        raise ValueError('Producer emitted invalid completion report') from exc
    if result.returncode != 0 or not isinstance(report, dict) or report.get('status') != 'COMPLETE':
        raise ValueError('Producer refresh failed or incomplete; previous generation retained')
    # Re-authenticate after the child as well; never import a mixed identity.
    authenticate(cfg)
    return import_export(replace(cfg, evidence_root=state), state / 'leads.jsonl')


def dashboard_handler(cfg, db_path):
    from .discovery_dashboard import dashboard_handler as factory
    return factory(cfg, db_path)


def evidence_bytes(cfg, name):
    from .discovery_dashboard import evidence_bytes as read
    return read(cfg, name)
