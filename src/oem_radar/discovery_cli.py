"""Explicit manual Discovery CLI; separate settings, disabled by default."""
from dataclasses import asdict
from pathlib import Path
import os
import uuid

from . import discovery as d


def load(path):
    values = d.strict_json(d.read_bounded(path, 65536))
    if not isinstance(values, dict) or set(values) != {'producer_id', 'producer', 'profiles', 'evidence_root', 'data_dir', 'enabled'} or type(values['enabled']) is not bool:
        raise ValueError('Invalid Discovery settings')
    return d.Settings(**values)


def save(path, cfg):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(d.dumps({k: str(v) if isinstance(v, Path) else v for k, v in asdict(cfg).items()}) + '\n', encoding='utf8')
    os.replace(temp, path)


def execute(args):
    try:
        if args.discovery_action == 'configure':
            if Path(args.settings).exists():
                raise ValueError('Settings already exist; refusing identity overwrite')
            cfg = d.Settings(producer_id=args.producer_id, producer=Path(args.producer), profiles=Path(args.profiles), evidence_root=Path(args.evidence_root), data_dir=Path(args.data_dir), enabled=False)
            d.authenticate(cfg)
            d.checked_path(cfg.evidence_root, str(cfg.evidence_root / '__probe__'))
            save(args.settings, cfg)
            result = {'status': 'CONFIGURED', 'enabled': False, 'producer_identity': d.IDENTITY}
        else:
            cfg = load(args.settings)
            action = args.discovery_action
            if action in ('enable', 'disable'):
                from dataclasses import replace
                cfg = replace(cfg, enabled=action == 'enable')
                save(args.settings, cfg)
                result = {'status': action.upper() + 'D', 'enabled': cfg.enabled, 'retained_data': True}
            elif not cfg.enabled:
                raise ValueError('Discovery is disabled')
            elif action == 'import':
                result = d.import_export(cfg, args.export)
            elif action == 'refresh':
                result = d.refresh(cfg)
            elif action == 'review':
                result = d.review(cfg, args.lead_id, args.label)
            elif action == 'list':
                rows = d.read_inbox(cfg)
                result = {'status': 'OK', 'total': len(rows), 'proposals': rows}
            elif action == 'dashboard':
                from .dashboard import serve
                catalog = Path(args.catalog)
                if not catalog.is_absolute() or not catalog.is_file():
                    raise ValueError('Existing absolute catalogue path required (read-only)')
                conn = d.readonly(catalog)
                conn.close()
                # Deliberately NOT cmd_dashboard or launch_dashboard.py: those
                # paths synchronize the registry before serving.
                serve(str(catalog), host=args.host, port=args.port, open_browser=not args.no_browser, discovery_settings=cfg)
                return 0
        print(d.dumps(result))
        return 0
    except Exception as exc:
        print(d.dumps({'status': 'FAILED', 'error': type(exc).__name__ + ': ' + str(exc)}))
        return 2


def register(sub):
    parser = sub.add_parser('discovery', help='manual separate D1 proposal inbox (default disabled)')
    parser.add_argument('--settings', required=True, help='explicit separate Discovery JSON settings path')
    actions = parser.add_subparsers(dest='discovery_action', required=True)
    configure = actions.add_parser('configure', help='create disabled settings; never activate automatically')
    for name in ('producer-id', 'producer', 'profiles', 'evidence-root', 'data-dir'):
        configure.add_argument('--' + name, required=True)
    for action in ('enable', 'disable', 'list', 'refresh'):
        actions.add_parser(action)
    intake = actions.add_parser('import', help='bounded, all-or-nothing offline JSONL intake')
    intake.add_argument('export')
    review = actions.add_parser('review', help='consumer editorial triage only; NOT product admission')
    review.add_argument('lead_id')
    review.add_argument('--label', choices=d.LABELS, required=True)
    dashboard = actions.add_parser('dashboard', help='manual GET-only dashboard; no registry writes')
    dashboard.add_argument('--catalog', required=True)
    dashboard.add_argument('--host', default='127.0.0.1')
    dashboard.add_argument('--port', default=8787, type=int)
    dashboard.add_argument('--no-browser', action='store_true')
    parser.set_defaults(func=execute)
