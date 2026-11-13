#!/usr/bin/env python3.12
"""Copy reviewed, local OpenCode project policy without overwriting existing files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

TEMPLATE = Path(__file__).resolve().parent / 'files'
VERSION = (TEMPLATE.parent / 'TEMPLATE_VERSION').read_text().strip()
MANIFEST = Path('.opencode/scaffold.json')
LAYOUT = 'native-layers-v1'
OVERRIDES = Path('.opencode/opencode.json')
INSTRUCTIONS = Path('AGENTS.md')
STARTER_HISTORY = TEMPLATE.parent / 'starter-history'

# The same checker is shipped into projects for dispatch-time validation.
sys.path.insert(0, str(TEMPLATE / '.opencode'))
from preflight import validate_overrides


def managed(relative):
    return relative == Path('opencode.json') or (
        str(relative).startswith('.opencode/') and relative not in
        (Path('.opencode/PROJECT.md'), OVERRIDES))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.newoc-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        os.chmod(temporary, mode if mode is not None else 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_files(target, changes, new_mode=None):
    """Atomic per-file replacement, with rollback if a later write fails."""
    previous = {}
    for path, _ in changes:
        safe_update_destination(target, path)
        previous[path] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else (None, None)
    completed = []
    try:
        for path, data in changes:
            completed.append(path)
            atomic_write(path, data, previous[path][1] if previous[path][1] is not None else new_mode)
    except BaseException as error:
        failures = []
        for path in reversed(completed):
            data, mode = previous[path]
            try:
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, data, mode)
            except OSError:
                failures.append(str(path.relative_to(target)))
        if failures:
            raise OSError('Update failed and rollback needs recovery for: ' + ', '.join(failures)) from error
        if isinstance(error, KeyboardInterrupt):
            raise
        raise OSError(f'Update failed; original project files restored: {error}') from error


def template_files():
    # Finder metadata and Python's import caches are not template source.
    return sorted(p for p in TEMPLATE.rglob('*') if p.is_file() and p.name != '.DS_Store'
                  and '__pycache__' not in p.relative_to(TEMPLATE).parts)


def manifest(contents, project_owned=(), starter=None):
    result = {'version': VERSION, 'layout': LAYOUT,
              'files': {str(p): digest(data) for p, data in contents.items() if managed(p)}}
    if project_owned:
        result['project_owned'] = sorted(project_owned)
    if starter is not None:
        result['starters'] = {str(INSTRUCTIONS): starter}
    return result


def safe_update_destination(target, destination):
    for part in [destination, *destination.parents]:
        if part == target:
            break
        if part.is_symlink():
            raise ValueError(f'Refusing symlink update destination: {part}')
        if part != destination and part.exists() and not part.is_dir():
            raise ValueError(f'Parent is not a directory: {part}')


def evidence_ignore_status(target):
    """Check nested rules against the proposed root ignore without project writes."""
    if not target.exists():
        return False
    nested = target / '.opencode/.gitignore'
    if nested.exists() or nested.is_symlink():
        safe_update_destination(target, nested)
        ignore = target / '.gitignore'
        safe_update_destination(target, ignore)
        current = ignore.read_bytes() if ignore.exists() else b''
        # Directory-only negations need a real directory to evaluate. Mirror only
        # ignore policy in a disposable repo, never create evidence in the project.
        with tempfile.TemporaryDirectory(prefix='newoc-ignore-') as temporary:
            probe = Path(temporary)
            subprocess.run(['git', 'init', '-q', str(probe)], check=True, capture_output=True)
            (probe / '.opencode/evidence').mkdir(parents=True)
            (probe / '.gitignore').write_bytes(current + b'\n/.opencode/evidence/\n')
            (probe / '.opencode/.gitignore').write_bytes(nested.read_bytes())
            result = subprocess.run(['git', '-C', str(probe), 'check-ignore', '--no-index',
                                     '-q', '--', '.opencode/evidence/'], capture_output=True)
            if result.returncode:
                raise ValueError('Nested ignore rule exposes .opencode/evidence; reconcile it explicitly before updating; no files changed')
    return subprocess.run(['git', '-C', str(target), 'check-ignore', '--no-index',
                           '-q', '--', '.opencode/evidence/__newoc_ignore_probe__'],
                          capture_output=True).returncode == 0


def instruction_update(target, old):
    """Recognize generated bytes, never rebaseline a user's edited instructions."""
    records = old.get('starters', {})
    if not isinstance(records, dict):
        raise ValueError('Invalid starter provenance')
    record = records.get(str(INSTRUCTIONS))
    if record is not None and (not isinstance(record, dict) or
            not isinstance(record.get('sha256'), str) or
            not re.fullmatch('[a-f0-9]{64}', record['sha256']) or
            not isinstance(record.get('project_name'), str)):
        raise ValueError('Invalid AGENTS.md starter provenance')
    path = target / INSTRUCTIONS
    if path.is_symlink():
        return None, record, None, 'preserved project-owned symlink'
    if path.exists() and not path.is_file():
        raise ValueError('AGENTS.md exists but is not a file')
    previous = path.read_bytes() if path.exists() else None
    name = record['project_name'] if record else target.name
    recognized = previous is None or (record is not None and digest(previous) == record['sha256'])
    template = (TEMPLATE / INSTRUCTIONS).read_text()
    if not recognized:
        try:
            text = previous.decode('utf-8')
        except UnicodeDecodeError:
            text = ''
        # Match complete known templates byte-for-byte. Only the originally
        # substituted project name varies, including after a directory rename.
        for candidate in [(TEMPLATE / INSTRUCTIONS), *sorted(STARTER_HISTORY.glob('AGENTS-*.md'))]:
            known = candidate.read_text()
            heading = known.split('\n', 1)[0]
            prefix, suffix = heading.split('{{PROJECT_NAME}}', 1)
            first = text.split('\n', 1)[0]
            if first.startswith(prefix) and first.endswith(suffix):
                end = len(first) - len(suffix) if suffix else len(first)
                candidate_name = first[len(prefix):end]
                if candidate_name and known.replace('{{PROJECT_NAME}}', candidate_name).encode() == previous:
                    name = candidate_name
                    recognized = True
                    break
    if not recognized:
        return None, record, None, 'preserved customized or unrecognized instructions'
    data = template.replace('{{PROJECT_NAME}}', name).encode()
    updated_record = {'sha256': digest(data), 'project_name': name}
    if data == previous:
        return None, updated_record, None, 'generated starter already current'
    safe_update_destination(target, path)
    backup = None
    if previous is not None:
        backup_path = target / '.opencode/evidence/scaffold-updates' / ('AGENTS-' + digest(previous) + '.md')
        safe_update_destination(target, backup_path)
        if backup_path.exists() and (not backup_path.is_file() or backup_path.read_bytes() != previous):
            raise ValueError('AGENTS.md migration backup collision; no files changed')
        backup = (backup_path, previous)
    return (path, data), updated_record, backup, ('created missing file' if previous is None else 'replaced untouched generated starter; original retained in evidence/scaffold-updates')


def update(target, apply=False):
    target = target.absolute()
    if (target / '.opencode').is_symlink() or (target / MANIFEST).is_symlink():
        raise ValueError('Refusing symlink scaffold metadata')
    if (target / '.opencode/.worker.lock').exists():
        raise ValueError('A worker lock exists; reconcile the active run before updating')
    if not (target / MANIFEST).exists():
        return legacy_update(target, apply)
    old = json.loads((target / MANIFEST).read_text())
    if (not isinstance(old, dict) or not isinstance(old.get('version'), str) or
            not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', old['version']) or
            not isinstance(old.get('files'), dict) or any(
                not isinstance(path, str) or Path(path).is_absolute() or '..' in Path(path).parts or
                not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value)
                for path, value in old.get('files', {}).items())):
        raise ValueError('Invalid scaffold manifest version/files; restore valid ownership metadata, no files changed')
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
    if any(str(p) in project_owned for p in [Path('opencode.json'), Path('.opencode/BASELINE.md'), Path('.opencode/WORKFLOW.md'), Path('.opencode/run-local.py'), Path('.opencode/preflight.py'),
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
        safe_update_destination(target, destination)
        previous = old_files.get(str(relative))
        if previous is not None:
            if not destination.is_file() or digest(destination.read_bytes()) != previous:
                raise ValueError(f'Locally changed managed file; merge manually: {relative}')
        elif destination.exists():
            raise ValueError(f'Refusing to adopt existing file: {relative}')
        if not destination.exists() or destination.read_bytes() != data:
            changes.append((destination, data))
    instruction_change, starter, backup, instruction_status = instruction_update(target, old)
    if instruction_change is not None:
        changes.append(instruction_change)
    ignore_path = target / '.gitignore'
    safe_update_destination(target, ignore_path)
    ignore = ignore_path.read_bytes() if ignore_path.exists() else b''
    ignored = evidence_ignore_status(target)
    if not ignored or not {b'.opencode/evidence/', b'/.opencode/evidence/'} & set(ignore.splitlines()):
        separator = b'\n' if ignore and not ignore.endswith(b'\n') else b''
        changes.append((ignore_path, ignore + separator + b'/.opencode/evidence/\n'))
    print(f'Scaffold {old["version"]} -> {VERSION}: {len(changes)} file changes; '+('applying' if apply else 'preview only'), file=sys.stderr)
    for destination, data in changes:
        print(f'  {destination.relative_to(target)}', file=sys.stderr)
    print(f'  AGENTS.md: {instruction_status}', file=sys.stderr)
    if apply:
        if backup is not None:
            backup_path, previous = backup
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            if not backup_path.exists():
                with backup_path.open('xb') as stream:
                    stream.write(previous)
        changes.append((target / MANIFEST, (json.dumps(manifest(contents, project_owned, starter), indent=2)+'\n').encode()))
        apply_files(target, changes)
    return target.resolve()


def legacy_update(target, apply=False):
    from legacy import plan
    defaults = json.loads((TEMPLATE / 'opencode.json').read_text())
    contents = {path.relative_to(TEMPLATE): path.read_bytes() for path in template_files()
                if managed(path.relative_to(TEMPLATE))}
    catalog = json.loads((TEMPLATE.parent / 'legacy-history/native-v3.json').read_text())
    writes, project_owned, overrides, messages = plan(target, contents, catalog, defaults, safe_update_destination)
    validate_overrides(target, defaults, overrides)
    starter = None
    instruction_path = target / INSTRUCTIONS
    safe_update_destination(target, instruction_path)
    if not instruction_path.exists():
        writes[INSTRUCTIONS] = (TEMPLATE / INSTRUCTIONS).read_text().replace('{{PROJECT_NAME}}', target.name).encode()
        starter = {'sha256': digest(writes[INSTRUCTIONS]), 'project_name': target.name}
    ignore_path = target / '.gitignore'
    safe_update_destination(target, ignore_path)
    ignore = ignore_path.read_bytes() if ignore_path.exists() else b''
    ignored = evidence_ignore_status(target)
    if not ignored or not {b'.opencode/evidence/', b'/.opencode/evidence/'} & set(ignore.splitlines()):
        writes[Path('.gitignore')] = ignore + (b'\n' if ignore and not ignore.endswith(b'\n') else b'') + b'/.opencode/evidence/\n'
    contents = {path: data for path, data in contents.items() if str(path) not in project_owned}
    writes[MANIFEST] = (json.dumps(manifest(contents, project_owned, starter), indent=2)+'\n').encode()
    originals = {}
    for relative, data in writes.items():
        path = target / relative
        safe_update_destination(target, path)
        if path.exists() and path.read_bytes() != data:
            originals[str(relative)] = path.read_bytes()
    identity = digest(json.dumps({name: digest(data) for name, data in sorted(originals.items())}).encode())
    backup_root = target / '.opencode/scaffold-backups' / ('legacy-' + identity)
    backups = []
    backup_ignore = backup_root / '.gitignore'
    safe_update_destination(target, backup_ignore)
    if backup_ignore.exists() and backup_ignore.read_bytes() != b'*\n':
        raise ValueError('Legacy migration backup ignore collision; no files changed')
    # Recovery copies remain ignored even if the project's root-ignore write
    # fails and rollback restores a root file without an evidence rule.
    backups.append((backup_ignore, b'*\n'))
    for name, data in originals.items():
        path = backup_root / 'files' / name
        safe_update_destination(target, path)
        if path.exists() and path.read_bytes() != data:
            raise ValueError('Legacy migration backup collision; no files changed')
        backups.append((path, data))
    print(f'Legacy native scaffold -> {VERSION}: '+('applying' if apply else 'preview only'), file=sys.stderr)
    for message in messages:
        print('  ' + message, file=sys.stderr)
    for relative in sorted(writes):
        print('  ' + str(relative), file=sys.stderr)
    print('  Preserve AGENTS.md, README, source, Git history and unrelated files; originals backed up locally on apply', file=sys.stderr)
    if apply:
        apply_files(target, backups, new_mode=0o600)
        apply_files(target, [(target / path, data) for path, data in writes.items()])
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
    evidence_ignored = evidence_ignore_status(target)
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
                if not evidence_ignored and '.opencode/evidence/' not in ignore_additions:
                    ignore_additions.append('/.opencode/evidence/')
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
    starter = {'sha256': digest(contents[INSTRUCTIONS]), 'project_name': name} if any(
        destination == target / INSTRUCTIONS for destination, _ in writes) else None
    (target / MANIFEST).write_text(json.dumps(manifest(contents, starter=starter), indent=2)+'\n')
    # Preserve existing repositories, branch names, remotes and commits.
    found = subprocess.run(['git', '-C', str(target), 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if found.returncode or Path(found.stdout.strip()).resolve() != target.resolve():
        subprocess.run(['git', '-C', str(target), 'init', '-b', 'main'], check=True, stdout=subprocess.DEVNULL)
    print('Scaffold installed: shared BASELINE.md provides working defaults; AGENTS.md is for optional project rules. Review registered model/provider routes before inference. Codex intervention is optional.', file=sys.stderr)
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
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            print(f'newoc: {error}', file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print('newoc: Update interrupted; completed project writes rolled back', file=sys.stderr)
            return 130
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
