#!/usr/bin/env python3.12
"""Optional native Arbiter handoff. Preview/doctor never start inference."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROLES = ('SCV', 'probe', 'Overlord')
ARBITER_MODEL = 'openai/gpt-6.1-sol'
HELPERS = ('compaction', 'title', 'summary')


def routing(root):
    profile_path = root / '.opencode/local.json'
    if profile_path.exists():
        profile = json.loads(profile_path.read_text())
    else:
        native = json.loads((root / '.opencode/opencode.json').read_text())
        profile = {
            'local_provider_ids': ['lmstudio'],
            'models': {role: native['agents'][role]['model'] for role in ROLES},
        }
    providers = profile['local_provider_ids']
    models = profile['models']
    if not isinstance(providers, list) or not providers or not all(isinstance(p, str) and p for p in providers):
        raise ValueError('local_provider_ids must list reviewed local provider IDs')
    for role in ROLES:
        model = models.get(role)
        if not isinstance(model, str) or '/' not in model or 'REPLACE' in model or any(c.isspace() for c in model):
            raise ValueError(f'Set a registered local model for {role}')
        if model.split('/', 1)[0] not in providers:
            raise ValueError(f'{role} model is outside local_provider_ids')
    if not profile_path.exists():
        # With no explicit launcher profile, preserve native worker/helper routes,
        # including project-authorized helper models and enabled providers.
        return {'model': ARBITER_MODEL, 'default_agent': 'Arbiter',
                'agents': {'Arbiter': {'model': ARBITER_MODEL},
                           'Sentry': {'model': ARBITER_MODEL}}}
    return {
        'model': ARBITER_MODEL,
        'enabled_providers': list(dict.fromkeys(['openai', *providers])),
        'default_agent': 'Arbiter',
        'agents': {**{name: {'model': models[name] if name in ROLES else models['Overlord']}
                   for name in (*ROLES, *HELPERS)},
                   'title': {'model': models['probe']},
                   'Arbiter': {'model': ARBITER_MODEL},
                   'Sentry': {'model': ARBITER_MODEL}},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', nargs='?', default='Arbiter', choices=['Arbiter'])
    parser.add_argument('--task', required=True, type=Path, help='Repo-local handoff file')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--doctor', action='store_true', help='Native agent discovery only; no inference')
    modes.add_argument('--execute', action='store_true', help='Start native Sol orchestration; authorized tasks may invoke local workers')
    parser.add_argument('--routing-reviewed', action='store_true', help='Reviewed Sol coordinator and local worker/helper routes, providers and plugins')
    parser.add_argument('--session', help='Resume a known healthy Arbiter session from this checkout')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        task = args.task.resolve()
        task.relative_to(root)
        if not task.is_file():
            raise ValueError('Task must be an existing repo-local file')
        config = routing(root)
        if os.environ.get('OPENCODE_CONFIG_CONTENT'):
            raise ValueError('Existing OPENCODE_CONFIG_CONTENT: reconcile it explicitly before dispatch')
        env = {**os.environ, 'OPENCODE_CONFIG_CONTENT': json.dumps(config)}
        command = ['opencode', 'debug', 'agents', '--standalone'] if args.doctor else [
            'opencode', 'run', '--standalone', '--agent', args.role,
            '--model', config['agents'][args.role]['model'], '--format', 'json',
            '--file', str(task),
            'Own the attached task through native local delegation, recovery, fresh Overlord QA and Sentry code review. Codex intervention is optional. Preserve project acceptance and authorization boundaries; return evidence.',
        ]
        if args.session:
            command += ['--session', args.session]
        if not args.doctor and not args.execute:
            print(json.dumps({'cwd': str(root), 'argv': command, 'runtime_config': config,
                              'note': 'Preview only. Arbiter/Sentry use cloud Sol; inspect effective worker/helper routes. Provider IDs do not verify endpoints.'}, indent=2))
            return 0
        if args.execute:
            contract = (root / '.opencode/PROJECT.md').read_text()
            if 'Status: READY' not in contract or 'Status: UNCONFIGURED' in contract:
                raise ValueError('Complete .opencode/PROJECT.md and mark Status: READY before execution')
            if not args.routing_reviewed:
                raise ValueError('Inspect native doctor output, provider endpoints and merged plugins first; then pass --routing-reviewed')
        evidence = root / '.opencode/evidence'
        # Refuse escaped evidence/lock paths rather than writing through symlinks.
        evidence.mkdir(exist_ok=True)
        if evidence.resolve() != evidence:
            raise ValueError('Evidence directory must not be a symlink')
        lock = root / '.opencode/.worker.lock'
        with lock.open('x') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'role': args.role, 'task': str(task)}) + '\n')
        try:
            run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
            log = evidence / f'{run_id}-{args.role}-{"doctor" if args.doctor else "run"}.log'
            print(f'{"Discovery" if args.doctor else "OpenCode Arbiter"}: {log}', flush=True)
            with log.open('x') as stream:
                result = subprocess.run(command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT)
            print(f'PROCESS_EXIT={result.returncode}; log={log}')
            return result.returncode
        finally:
            lock.unlink()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'run-local: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
