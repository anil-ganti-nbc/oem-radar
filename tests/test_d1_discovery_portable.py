"""Portable store/parser/authority controls; no producer or publisher captures needed.

These are generic mechanics, not substitutes for the separately selected real-D1
contract/routing qualification in test_d1_discovery.py.
"""
from dataclasses import replace
from pathlib import Path

import pytest

from oem_radar import discovery as d
from oem_radar.discovery_cli import load, save


def local_settings(tmp_path):
    return d.Settings(
        producer_id='external-d1',
        producer=tmp_path / 'producer.py',
        profiles=tmp_path / 'profiles.json',
        evidence_root=tmp_path / 'input-evidence',
        data_dir=tmp_path / 'consumer',
        enabled=False,
    )


def test_portable_settings_roundtrip_is_explicitly_disabled(tmp_path):
    cfg = local_settings(tmp_path)
    path = tmp_path / 'settings.json'
    save(path, cfg)
    restored = load(path)
    assert restored == cfg
    assert restored.enabled is False
    assert not cfg.data_dir.exists()
    values = d.strict_json(path.read_bytes())
    values['enabled'] = 'true'
    path.write_text(d.dumps(values), encoding='utf8')
    with pytest.raises(ValueError, match='Invalid Discovery settings'):
        load(path)


def test_strict_json_closure_keeps_useful_finite_input():
    assert d.strict_json('{"count":1,"name":"ordinary proposal"}') == {
        'count': 1, 'name': 'ordinary proposal',
    }
    for malformed in ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}']:
        with pytest.raises(ValueError):
            d.strict_json(malformed)


def test_unpinned_producer_is_refused_before_execution(tmp_path):
    cfg = local_settings(tmp_path)
    cfg.producer.write_text("raise AssertionError('UNPINNED_CODE_EXECUTED')\n", encoding='utf8')
    cfg.profiles.write_text('{}', encoding='utf8')
    with pytest.raises(ValueError, match='pin mismatch'):
        d.authenticate(cfg)
    assert not cfg.data_dir.exists()


def test_evidence_paths_confine_a_useful_file_and_reject_escape(tmp_path):
    root = tmp_path / 'evidence'
    root.mkdir()
    useful = root / 'article.txt'
    useful.write_bytes(b'ordinary immutable evidence')
    assert d.checked_path(root, str(useful)) == useful
    assert d.read_bounded(useful, 100) == b'ordinary immutable evidence'
    outside = tmp_path / 'outside.txt'
    outside.write_bytes(b'not admitted evidence')
    with pytest.raises(ValueError, match='escape'):
        d.checked_path(root, str(outside))
    with pytest.raises(ValueError, match='Unsafe'):
        d.checked_path(root, str(root / '..' / 'outside.txt'))


def test_atomic_publication_preserves_previous_empty_generation(tmp_path, monkeypatch):
    cfg = local_settings(tmp_path)
    generation, conn = d.new_generation(cfg)
    d.publish(cfg, generation, conn)
    pointer = (cfg.data_dir / 'CURRENT').read_bytes()
    assert d.read_inbox(cfg) == []
    assert (generation / 'consumer.jsonl').read_bytes() == b''
    second, conn = d.new_generation(cfg)
    real_replace = d.os.replace

    def interrupt(source, target):
        if Path(target).name == 'CURRENT':
            raise OSError('test-only publication interruption')
        return real_replace(source, target)

    monkeypatch.setattr(d.os, 'replace', interrupt)
    with pytest.raises(OSError, match='interruption'):
        d.publish(cfg, second, conn)
    assert (cfg.data_dir / 'CURRENT').read_bytes() == pointer
    assert d.read_inbox(cfg) == []


def test_disable_refuses_intake_without_erasing_retained_store(tmp_path):
    cfg = local_settings(tmp_path)
    generation, conn = d.new_generation(cfg)
    d.publish(cfg, generation, conn)
    pointer = (cfg.data_dir / 'CURRENT').read_bytes()
    with pytest.raises(ValueError, match='disabled'):
        d.import_export(cfg, tmp_path / 'not-opened.jsonl')
    with pytest.raises(ValueError, match='disabled'):
        d.review(cfg, 'not-admitted', 'editorial_keep')
    assert (cfg.data_dir / 'CURRENT').read_bytes() == pointer
    assert d.read_inbox(cfg) == []
    assert replace(cfg, enabled=True).enabled is True


def test_empty_discovery_view_never_initializes_state(tmp_path):
    from oem_radar.discovery_dashboard import render_discovery
    cfg = local_settings(tmp_path)
    page = render_discovery(cfg)
    assert '0 retained proposals' in page
    assert 'no cap' in page
    assert 'Discovery' in page
    assert not cfg.data_dir.exists()
