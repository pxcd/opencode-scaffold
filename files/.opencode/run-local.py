#!/usr/bin/env python3.12
"""Optional native Cartman handoff. Preview/doctor never start inference."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from preflight import validate_overrides

ROLES = ('Butters', 'Kyle')
ARBITER_MODEL = 'openai/gpt-6.2-sol#medium'
HELPERS = ('compaction', 'title', 'summary')


def verified_session(root, env, session_id=None):
    """Bind and verify the native session location before submitting any task."""
    command = ['opencode', 'api', '--standalone']
    if session_id:
        command += ['session.get', '--param', 'sessionID=' + session_id]
    else:
        command += ['session.create', '--data', json.dumps({
            'location': {'directory': str(root)}, 'agent': 'Cartman',
            'model': {'providerID': 'openai', 'id': 'gpt-6.2-sol', 'variant': 'medium'}})]
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Native session discovery failed; no task submitted')
    session = json.loads(result.stdout)['data']
    directory = session.get('location', {}).get('directory')
    if not directory or not Path(directory).is_absolute() or Path(directory).resolve() != root:
        raise ValueError(f'Session {session.get("id")} has an unsuitable repository root; no task submitted')
    if session.get('agent') != 'Cartman':
        raise ValueError('Resume requires a Cartman session; no task submitted')
    return session['id']


def routing(root):
    native = json.loads((root / 'opencode.json').read_text())
    overrides = validate_overrides(root, native)
    native['agents'] = {**native['agents'], **{
        role: {**native['agents'].get(role, {}), **settings}
        for role, settings in overrides.get('agents', {}).items()}}
    profile_path = root / '.opencode/local.json'
    if profile_path.exists():
        profile = json.loads(profile_path.read_text())
    else:
        profile = {
            'local_provider_ids': ['lmstudio'],
            'models': {role: native['agents'][role]['model'] for role in ROLES},
        }
    providers = profile['local_provider_ids']
    models = dict(profile['models'])
    for old, new in [('SCV', 'Butters'), ('Overlord', 'Kyle')]:
        if old in models:
            if new in models and models[new] != models[old]:
                raise ValueError(f'Conflicting {old}/{new} launcher model overrides')
            models.setdefault(new, models[old])
    if not isinstance(providers, list) or not providers or not all(isinstance(p, str) and p for p in providers):
        raise ValueError('local_provider_ids must list reviewed local provider IDs')
    if profile_path.exists():
        models['title'] = models.get('title', models.get('probe', native['agents']['title']['model']))
    for role in (*ROLES, 'title') if profile_path.exists() else ROLES:
        model = models.get(role)
        if not isinstance(model, str) or '/' not in model or 'REPLACE' in model or any(c.isspace() for c in model):
            raise ValueError(f'Set a registered local model for {role}')
        if model.split('/', 1)[0] not in providers:
            raise ValueError(f'{role} model is outside local_provider_ids')
    cloud_agents = {'Cartman': {'model': ARBITER_MODEL},
                    'Stan': {'model': ARBITER_MODEL},
                    'Chef': {'model': native['agents']['Chef']['model']}}
    if not profile_path.exists():
        # With no explicit launcher profile, preserve native worker/helper routes,
        # including project-authorized helper models and enabled providers.
        return {'model': ARBITER_MODEL, 'default_agent': 'Cartman',
                'agents': cloud_agents}
    return {
        'model': ARBITER_MODEL,
        'enabled_providers': list(dict.fromkeys(['openai', *providers])),
        'default_agent': 'Cartman',
        'agents': {**{name: {'model': models[name] if name in ROLES else models['Kyle']}
                   for name in (*ROLES, *HELPERS)},
                   'title': {'model': models['title']},
                   **cloud_agents},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', nargs='?', default='Cartman', choices=['Cartman', 'Arbiter'])
    parser.add_argument('--task', required=True, type=Path, help='Repo-local handoff file')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--doctor', action='store_true', help='Native agent discovery only; no inference')
    modes.add_argument('--execute', action='store_true', help='Start native Sol orchestration; authorized tasks may invoke local workers')
    parser.add_argument('--routing-reviewed', action='store_true', help='Reviewed Sol coordinator and local worker/helper routes, providers and plugins')
    parser.add_argument('--session', help='Resume a known healthy Cartman session from this checkout')
    args = parser.parse_args()
    if args.role == 'Arbiter':
        args.role = 'Cartman'
    root = Path(__file__).resolve().parent.parent
    try:
        task = args.task.resolve()
        task.relative_to(root)
        if not task.is_file():
            raise ValueError('Task must be an existing repo-local file')
        config = routing(root)
        if os.environ.get('OPENCODE_CONFIG_CONTENT'):
            raise ValueError('Existing OPENCODE_CONFIG_CONTENT: reconcile it explicitly before dispatch')
        # OpenCode uses logical PWD when creating sessions, not just process cwd.
        env = {**os.environ, 'PWD': str(root), 'OPENCODE_CONFIG_CONTENT': json.dumps(config)}
        command = ['opencode', 'debug', 'agents', '--standalone'] if args.doctor else [
            'opencode', 'run', '--standalone', '--agent', args.role,
            '--model', config['agents'][args.role]['model'], '--format', 'json',
            '--file', str(task),
            'Own the attached task through native local delegation, recovery, fresh Kyle QA and Stan code review. Codex intervention is optional. Preserve project acceptance and authorization boundaries; return evidence.',
        ]
        if not args.doctor and not args.execute:
            if args.session:
                command += ['--session', args.session]
            print(json.dumps({'cwd': str(root), 'argv': command, 'runtime_config': config,
                              'note': 'Preview only. Cartman/Stan use cloud Sol and Chef uses cloud Astra; inspect effective worker/helper routes. Provider IDs do not verify endpoints.'}, indent=2))
            return 0
        if args.execute:
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
            run_evidence = evidence / run_id
            run_evidence.mkdir()
            log = run_evidence / f'{args.role}-{"doctor" if args.doctor else "run"}.log'
            if args.execute:
                session_id = verified_session(root, env, args.session)
                command += ['--session', session_id]
                (run_evidence / 'handoff.json').write_text(json.dumps({
                    'sessionID': session_id, 'directory': str(root), 'task': str(task)}, indent=2) + '\n')
            print(f'{"Discovery" if args.doctor else "OpenCode Cartman"}: {log}', flush=True)
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
