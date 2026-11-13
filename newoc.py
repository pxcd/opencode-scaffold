#!/usr/bin/env python3.12
"""Copy reviewed, local OpenCode project policy without overwriting existing files."""
import argparse
import hashlib
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

TEMPLATE = Path(__file__).resolve().parent / 'files'
VERSION = (TEMPLATE.parent / 'TEMPLATE_VERSION').read_text().strip()
MANIFEST = Path('.opencode/scaffold.json')
LAYOUT = 'native-layers-v1'
OVERRIDES = Path('.opencode/opencode.json')


def managed(relative):
    return relative == Path('opencode.json') or (
        str(relative).startswith('.opencode/') and relative not in
        (Path('.opencode/PROJECT.md'), OVERRIDES))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def template_files():
    # Finder metadata is binary and is not part of the scaffold, even when ignored by Git.
    return sorted(p for p in TEMPLATE.rglob('*') if p.is_file() and p.name != '.DS_Store')


def manifest(contents, project_owned=()):
    result = {'version': VERSION, 'layout': LAYOUT,
              'files': {str(p): digest(data) for p, data in contents.items() if managed(p)}}
    if project_owned:
        result['project_owned'] = sorted(project_owned)
    return result


def validate_overrides(target, defaults):
    """Check scaffold invariants without rewriting project-owned configuration."""
    if (target / '.opencode/opencode.jsonc').exists() or (target / 'opencode.jsonc').exists():
        raise ValueError('JSONC config requires a reviewed migration to the scaffold JSON override layout')
    path = target / OVERRIDES
    if path.is_symlink():
        raise ValueError('Refusing symlink project overrides')
    overrides = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(overrides, dict):
        raise ValueError('Project overrides must be a JSON object')
    if overrides.get('default_agent', 'Arbiter') != 'Arbiter':
        raise ValueError('Project override conflicts with scaffold default_agent Arbiter')
    agents = overrides.get('agents', {})
    if not isinstance(agents, dict):
        raise ValueError('Project agents override must be an object')
    global_rules = overrides.get('permissions', [])
    if not isinstance(global_rules, list) or any(
            not isinstance(r, dict) or not all(isinstance(r.get(k), str) for k in ('action', 'resource', 'effect'))
            or r['effect'] not in ('deny', 'allow', 'ask') for r in global_rules):
        raise ValueError('Project permissions must be a list of action/resource/effect rules')
    for role, shared in defaults['agents'].items():
        custom = agents.get(role, {})
        if not isinstance(custom, dict):
            raise ValueError(f'Invalid project override for {role}')
        if role in ('Arbiter', 'Sentry') and custom.get('model', shared['model']) != shared['model']:
            raise ValueError(f'Project override conflicts with pinned {role} model')
        if role in ('Arbiter', 'SCV', 'probe', 'Overlord', 'Sentry'):
            mode = 'primary' if role == 'Arbiter' else 'subagent'
            if custom.get('disable') or custom.get('mode', mode) != mode:
                raise ValueError(f'Project override disables or changes required role {role}')
        rules = custom.get('permissions', [])
        if not isinstance(rules, list):
            raise ValueError(f'Project {role} permissions must be a list')
        for rule in rules:
            if not isinstance(rule, dict) or not all(isinstance(rule.get(k), str) for k in ('action', 'resource', 'effect')):
                raise ValueError(f'Invalid permission override for {role}')
            if rule['effect'] not in ('allow', 'ask', 'deny'):
                raise ValueError(f'Invalid permission effect for {role}')
            if role == 'Sentry' and rule['effect'] != 'deny' and any(
                    fnmatchcase(action, rule['action']) for action in
                    ('edit', 'shell', 'execute', 'subagent', 'external_directory')):
                raise ValueError('Project override weakens Sentry read-only permissions')
            if role in ('SCV', 'probe', 'Overlord') and rule['effect'] != 'deny' and fnmatchcase('subagent', rule['action']):
                raise ValueError(f'Project override enables delegation for {role}')
        # Native role rules follow global rules. Refuse a shadowed project denial
        # rather than claiming that leaving the override file intact preserves it.
        for rule in global_rules:
            if rule['effect'] != 'deny':
                continue
            for base in shared.get('permissions', []):
                if (base['effect'] != 'deny' and
                        (fnmatchcase(rule['action'], base['action']) or fnmatchcase(base['action'], rule['action'])) and
                        (fnmatchcase(rule['resource'], base['resource']) or fnmatchcase(base['resource'], rule['resource']))):
                    matches = [r for r in rules if fnmatchcase(rule['action'], r['action']) and fnmatchcase(rule['resource'], r['resource'])]
                    if not matches or matches[-1]['effect'] != 'deny':
                        raise ValueError(f'Project global denial can be shadowed by {role}; repeat it in agents.{role}.permissions')
        def decision(action, resource):
            effect = None
            for rule in [*shared.get('permissions', []), *rules]:
                if fnmatchcase(action, rule['action']) and fnmatchcase(resource, rule['resource']):
                    effect = rule['effect']
            return effect
        if role == 'Arbiter':
            children = {r['resource'] for r in shared['permissions']
                        if r['action'] == 'subagent' and r['effect'] == 'allow'}
            for child in sorted(children):
                if decision('subagent', child) != 'allow':
                    raise ValueError(f'Project override blocks Arbiter delegation to {child}; reconcile it explicitly')
        elif role == 'Sentry':
            for action in ('edit', 'shell', 'execute', 'subagent', 'external_directory'):
                if decision(action, '*') != 'deny':
                    raise ValueError(f'Project override weakens Sentry {action} denial')
    return overrides


def update(target, apply=False):
    target = target.absolute()
    if (target / '.opencode').is_symlink() or (target / MANIFEST).is_symlink():
        raise ValueError('Refusing symlink scaffold metadata')
    if (target / '.opencode/.worker.lock').exists():
        raise ValueError('A worker lock exists; reconcile the active run before updating')
    old = json.loads((target / MANIFEST).read_text())
    if tuple(map(int, old['version'].split('.'))) > tuple(map(int, VERSION.split('.'))):
        raise ValueError('Refusing an implicit downgrade; use a reviewed migration')
    if old['version'].split('.')[0] != VERSION.split('.')[0]:
        raise ValueError('Major scaffold change requires a reviewed migration of project-owned AGENTS.md/README.md; no files changed')
    if old.get('layout') != LAYOUT:
        raise ValueError('Scaffold layout requires a reviewed migration; no files changed')
    project_owned = old.get('project_owned', [])
    if (not isinstance(project_owned, list) or
            any(not isinstance(p, str) or not p.startswith('.opencode/') or
                '..' in Path(p).parts or str(Path(p)) != p for p in project_owned) or
            set(project_owned) & set(old['files'])):
        raise ValueError('Invalid or overlapping project-owned paths; review the migration manifest')
    contents = {p.relative_to(TEMPLATE): p.read_bytes() for p in template_files()
                if managed(p.relative_to(TEMPLATE)) and str(p.relative_to(TEMPLATE)) not in project_owned}
    if any(str(p) in project_owned for p in [Path('opencode.json'), Path('.opencode/WORKFLOW.md'), Path('.opencode/run-local.py'),
                                           *[p.relative_to(TEMPLATE) for p in (TEMPLATE/'.opencode/agents').glob('*.md')]]):
        raise ValueError('Shared orchestration cannot be project-owned in this layout; use project config overrides')
    validate_overrides(target, json.loads(contents[Path('opencode.json')]))
    # No implicit deletion or adoption of existing unmanaged files.
    old_files = {p: h for p, h in old['files'].items() if Path(p).name != '.DS_Store'}
    if set(old_files) - {str(p) for p in contents}:
        raise ValueError('Template removed managed files; a reviewed migration is required')
    changes = []
    for relative, data in contents.items():
        destination = target / relative
        for part in [destination, *destination.parents]:
            if part == target:
                break
            if part.is_symlink():
                raise ValueError(f'Refusing symlink update destination: {part}')
            if part != destination and part.exists() and not part.is_dir():
                raise ValueError(f'Parent is not a directory: {part}')
        previous = old_files.get(str(relative))
        if previous is not None:
            if not destination.is_file() or digest(destination.read_bytes()) != previous:
                raise ValueError(f'Locally changed managed file; merge manually: {relative}')
        elif destination.exists():
            raise ValueError(f'Refusing to adopt existing file: {relative}')
        if not destination.exists() or destination.read_bytes() != data:
            changes.append((destination, data))
    print(f'Scaffold {old["version"]} -> {VERSION}: {len(changes)} file changes; '+('applying' if apply else 'preview only'), file=sys.stderr)
    for destination, data in changes:
        print(f'  {destination.relative_to(target)}', file=sys.stderr)
    if apply:
        for destination, data in changes:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (target / MANIFEST).write_text(json.dumps(manifest(contents, project_owned), indent=2)+'\n')
    return target.resolve()


def scaffold(target: Path, name: str, *, existing: bool) -> Path:
    if target.is_symlink():
        raise ValueError(f'Refusing a symlink project directory: {target}')
    if existing:
        if not target.is_dir():
            raise ValueError('The current directory must exist')
    elif target.exists():
        raise ValueError(f'Project already exists: {target}; use --here to add agent files safely')
    target = target.absolute()
    validate_overrides(target, json.loads((TEMPLATE/'opencode.json').read_text()))
    files = template_files()
    if not files:
        raise ValueError(f'Template files are missing: {TEMPLATE}')
    writes = []
    contents = {}
    ignore_additions = []
    for source in files:
        relative = source.relative_to(TEMPLATE)
        destination = target / relative
        for parent in [destination, *destination.parents]:
            if parent == target.parent:
                break
            if parent.is_symlink():
                raise ValueError(f'Refusing a symlink template destination: {parent}')
            if parent != destination and parent.exists() and not parent.is_dir():
                raise ValueError(f'Parent is not a directory: {parent}')
        content = source.read_text().replace('{{PROJECT_NAME}}', name)
        contents[relative] = content.encode()
        if destination.exists():
            if relative in (Path('README.md'), Path('AGENTS.md'), Path('.opencode/PROJECT.md'), OVERRIDES) and destination.is_file():
                continue  # Project contracts and overrides are never adopted or rewritten.
            if relative == Path('.gitignore') and destination.is_file():
                current_lines = destination.read_text().splitlines()
                ignore_additions = [line for line in content.splitlines() if line and line not in current_lines]
                continue
            raise ValueError(f'Refusing to overwrite: {destination}')
        writes.append((destination, content))
    if (target / MANIFEST).exists() or (target / MANIFEST).is_symlink():
        raise ValueError(f'Refusing to overwrite: {target / MANIFEST}')
    if not shutil.which('git'):
        raise ValueError('Git is required; nothing was created')
    found = subprocess.run(['git', '-C', str(target), 'rev-parse', '--show-toplevel'], capture_output=True, text=True) if target.exists() else None
    if existing and found and not found.returncode and Path(found.stdout.strip()).resolve() != target.resolve():
        raise ValueError('Run --here at the repository root, not a nested directory')
    if not existing:
        target.mkdir(parents=True, exist_ok=False)
    for destination, content in writes:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('x') as stream:
            stream.write(content)
    if ignore_additions:
        ignore = target / '.gitignore'
        current = ignore.read_text()
        with ignore.open('a') as stream:
            stream.write(('' if not current or current.endswith('\n') else '\n') + '\n'.join(ignore_additions) + '\n')
    (target / MANIFEST).write_text(json.dumps(manifest(contents), indent=2)+'\n')
    # Preserve existing repositories, branch names, remotes and commits.
    found = subprocess.run(['git', '-C', str(target), 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if found.returncode or Path(found.stdout.strip()).resolve() != target.resolve():
        subprocess.run(['git', '-C', str(target), 'init', '-b', 'main'], check=True, stdout=subprocess.DEVNULL)
    print('Scaffold ready: GPT-6.1 Sol is OpenCode Arbiter; complete AGENTS.md and review project config overrides/local model registration. Codex intervention is optional.', file=sys.stderr)
    return target.resolve()


def main():
    parser = argparse.ArgumentParser(description='Create an OpenCode-ready project in ~/Development, or add the scaffold to the current project.')
    parser.add_argument('name', nargs='?', help='New project directory name (letters, numbers, dots, underscores or hyphens)')
    parser.add_argument('--here', action='store_true', help='Add roles/workflow to the current directory; preserve existing README and append missing ignore rules')
    parser.add_argument('--update', action='store_true', help='Preview an update to managed files in the current project')
    parser.add_argument('--apply', action='store_true', help='Apply --update after all ownership checks pass')
    parser.add_argument('--root', type=Path, default=Path.home()/'Development', help='Parent for a new project (default: ~/Development)')
    args = parser.parse_args()
    if args.apply and not args.update:
        parser.error('--apply requires --update')
    if args.update:
        if args.here or args.name:
            parser.error('--update takes no name or --here')
        try:
            print(update(Path.cwd(), args.apply))
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f'newoc: {error}', file=sys.stderr)
            return 1
        return 0
    if args.here:
        if args.name:
            parser.error('--here does not take a project name')
        target = Path.cwd()
        name = target.name
    else:
        if not args.name or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', args.name):
            parser.error('Supply a simple project name, or --here')
        target = args.root.expanduser().absolute() / args.name
        name = args.name
    try:
        print(scaffold(target, name, existing=args.here))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'newoc: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
