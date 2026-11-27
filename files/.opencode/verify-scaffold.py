"""Verify scaffold manifest hashes and native role wiring in the Git index."""

import hashlib
import json
from pathlib import PurePosixPath
import re
import subprocess
import sys


MANIFEST = '.opencode/scaffold.json'
OVERRIDES = '.opencode/opencode.json'
ROLE_MODES = {'Cartman': 'primary', 'Butters': 'subagent', 'Kyle': 'subagent',
              'Stan': 'subagent', 'Chef': 'subagent'}
ROLE_FILES = {role: f'.opencode/agents/{role}.md' for role in ROLE_MODES}


def git(*args):
    result = subprocess.run(['git', '--no-optional-locks', *args], capture_output=True)
    if result.returncode:
        raise ValueError(f'git {args[0]}: {result.stderr.decode(errors="replace").strip()}')
    return result.stdout


def scaffold_index():
    if git('rev-parse', '--show-prefix').strip():
        raise ValueError('Run this command from the project checkout root')
    entries = {}
    for line in git('ls-files', '--stage', '-z', '--', 'opencode.json', '.opencode').split(b'\0'):
        if line:
            metadata, path = line.split(b'\t', 1)
            mode, oid, stage = metadata.decode().split()
            name = path.decode(errors='surrogateescape')
            if stage != '0':
                raise ValueError(f'Unmerged scaffold index path: {name!r}')
            entries[name] = (mode, oid)
    return entries


def json_object(data, path):
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError(f'{path} must contain a JSON object')
    return value


def verify():
    index = scaffold_index()

    def read(path):
        entry = index.get(path)
        if entry is None:
            raise ValueError(f'Missing from Git index: {path!r}')
        mode, oid = entry
        if mode not in ('100644', '100755'):
            raise ValueError(f'Expected a regular staged file: {path!r}')
        return git('cat-file', 'blob', oid)

    manifest = json_object(read(MANIFEST), MANIFEST)
    hashes = manifest.get('files')
    required = {'opencode.json', *ROLE_FILES.values()}
    if not isinstance(hashes, dict) or not required <= hashes.keys():
        raise ValueError('Manifest must list the shared config and all native role files')
    managed = {}
    for path, digest in hashes.items():
        relative = PurePosixPath(path)
        if (str(relative) != path or '..' in relative.parts
                or not (path == 'opencode.json' or path.startswith('.opencode/'))
                or path in (MANIFEST, OVERRIDES, '.opencode/PROJECT.md')):
            raise ValueError(f'Invalid managed manifest path: {path!r}')
        managed[path] = read(path)
        if hashlib.sha256(managed[path]).hexdigest() != digest:
            raise ValueError(f'Manifest SHA-256 mismatch in Git index: {path!r}')

    config = json_object(managed['opencode.json'], 'opencode.json')
    agents = config.get('agents', {})
    if config.get('default_agent') != 'Cartman' or not isinstance(agents, dict):
        raise ValueError('Expected Cartman as the scaffold default agent')
    for role, mode in ROLE_MODES.items():
        settings = agents.get(role)
        header = managed[ROLE_FILES[role]].decode().split('---', 2)
        if (not isinstance(settings, dict) or not settings.get('model')
                or settings.get('disabled') or settings.get('mode', mode) != mode
                or len(header) != 3 or header[0]
                or re.findall(r'^mode:\s*(\w+)[ \t]*$', header[1], re.MULTILINE) != [mode]):
            raise ValueError(f'Invalid staged native role: {role} (expected {mode})')

    cartman, build = agents['Cartman'], agents.get('build')
    policy = '{file:' + ROLE_FILES['Cartman'] + '}'
    if (not isinstance(build, dict) or build.get('disabled') or build.get('mode') != 'primary'
            or build.get('system') != policy or cartman.get('system', policy) != policy
            or any(key not in cartman or build.get(key) != cartman[key]
                   for key in ('model', 'steps', 'permissions'))):
        raise ValueError('Staged build and Cartman must share coordinator policy, model, steps and permissions')

    if OVERRIDES in index:
        overrides = json_object(read(OVERRIDES), OVERRIDES)
        custom_agents = overrides.get('agents', {})
        if not isinstance(custom_agents, dict):
            raise ValueError('Staged project agents override must be an object')
        custom_cartman, custom_build = (custom_agents.get(role, {}) for role in ('Cartman', 'build'))
        if (not isinstance(custom_cartman, dict) or not isinstance(custom_build, dict)
                or custom_cartman.get('permissions', []) != custom_build.get('permissions', [])):
            raise ValueError('Staged project permissions must match across Cartman and build')

    print(f'PASS: {len(managed)} staged manifest SHA-256 digests and shared native role wiring')


if __name__ == '__main__':
    try:
        verify()
    except (ValueError, OSError) as error:
        sys.exit(f'verify-scaffold: {error}')
