"""Verify scaffold manifest hashes and native role wiring in the Git index."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from tempfile import TemporaryDirectory


MANIFEST = '.opencode/scaffold.json'
OVERRIDES = '.opencode/opencode.json'
PREFLIGHT = '.opencode/preflight.py'
ROLE_MODES = {'Cartman': 'primary', 'Butters': 'subagent', 'Kyle': 'subagent',
              'Stan': 'subagent', 'Chef': 'subagent'}
ROLE_FILES = {role: f'.opencode/agents/{role}.md' for role in ROLE_MODES}
PLUGIN_DIR = '.opencode/plugins/'
REQUIRED_PLUGIN_SUITES = {
    PLUGIN_DIR + 'continuation-guard/guard.test.mjs',
    PLUGIN_DIR + 'qa-retry-guard/guard.test.mjs',
    PLUGIN_DIR + 'qa-retry-guard/staged-qa.test.mjs',
    PLUGIN_DIR + 'step-limit-compat/normalize.test.mjs',
}
VERIFIER = '.opencode/verify-scaffold.py'


def git(*args):
    result = subprocess.run(['git', '--no-optional-locks', *args], capture_output=True)
    if result.returncode:
        raise ValueError(f'git {args[0]}: {result.stderr.decode(errors="replace").strip()}')
    return result.stdout


def scaffold_index():
    if git('rev-parse', '--show-prefix').strip():
        raise ValueError('Run this command from the project checkout root')
    entries = {}
    for line in git('ls-files', '--stage', '-z', '--', 'opencode.json', 'opencode.jsonc', '.opencode').split(b'\0'):
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


def run_staged_suites(managed):
    plugins = {path: data for path, data in managed.items() if path.startswith(PLUGIN_DIR)}
    suites = sorted(path for path in plugins if path.endswith('.test.mjs'))
    missing = REQUIRED_PLUGIN_SUITES.difference(suites)
    if missing:
        raise ValueError('Missing required staged scaffold plugin suites: ' + ', '.join(sorted(missing)))
    evidence = Path('.opencode/evidence')
    if evidence.parent.is_symlink() or evidence.is_symlink():
        raise ValueError('Refusing symlink scaffold QA evidence directory')
    if subprocess.run(['git', 'check-ignore', '--quiet', '--', str(evidence) + '/']).returncode:
        raise ValueError('Scaffold QA scratch space .opencode/evidence/ must be Git-ignored')
    evidence.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='scaffold-qa-', dir=evidence) as directory:
        snapshot = Path(directory)
        # Avoid inheriting the consuming project's Node module type.
        (snapshot / 'package.json').write_text('{"type":"module"}\n')
        for path, data in plugins.items():
            target = snapshot / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        print(f'Running {len(suites)} staged plugin suites: ' + ', '.join(suites), flush=True)
        result = subprocess.run(['node', '--test', '--test-reporter=tap', *suites], cwd=snapshot,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
    if result.returncode:
        sys.stderr.write(result.stdout)
        sys.exit(result.returncode if result.returncode > 0 else 128 - result.returncode)
    # Keep the independent receipt compact; retain complete diagnostics on failure.
    totals = {name: int(count) for name, count in re.findall(
        r'^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$', result.stdout, re.MULTILINE)}
    for name, count in totals.items():
        print(f'# {name} {count}')
    if (not totals.get('tests') or not totals.get('pass')
            or totals.get('fail') != 0 or totals.get('cancelled') != 0):
        raise ValueError('Node exited successfully without TAP totals confirming executed passing tests')


def check_coordinator_policy(validate, defaults):
    # Synthetic project layers exercise the actual staged validator even in a
    # checkout with no overrides. They never alter this project's settings.
    try:
        validate(defaults, {'agents': {'Cartman': {'steps': 80}, 'build': {'steps': 60}}})
    except ValueError as error:
        raise ValueError(f'Valid asymmetric project step limits (80/60) were rejected: {error}') from error
    for role, override in [('build', {'steps': 0}), ('Cartman', {'steps': True}),
                           ('build', {'disabled': True})]:
        try:
            validate(defaults, {'agents': {role: override}})
        except ValueError:
            continue
        raise ValueError(f'Invalid synthetic {role} override was accepted: {override}')
    print('Staged coordinator policy checks: accepted 80/60 project limits; '
          'rejected zero and boolean limits and a disabled build coordinator.')


def verify(qa=False):
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
    required = {'opencode.json', PREFLIGHT, *ROLE_FILES.values()}
    if qa:
        required.add(VERIFIER)
    if not isinstance(hashes, dict) or not required <= hashes.keys():
        raise ValueError('Manifest must list the shared config, preflight and all native role files')
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

    if 'opencode.jsonc' in index or '.opencode/opencode.jsonc' in index:
        raise ValueError('Staged JSONC requires a reviewed migration to the scaffold JSON override layout')
    entry_point = Path(VERIFIER)
    # The native gate feeds the staged entry point through standard input.
    # Direct invocations must still match the staged script on disk.
    if qa and __file__ != '<stdin>' and (entry_point.parent.is_symlink() or entry_point.is_symlink() or not entry_point.is_file()
               or Path(__file__).resolve() != entry_point.resolve()
               or entry_point.read_bytes() != managed.get(VERIFIER)):
        raise ValueError('Working verify-scaffold.py must be a regular file matching the staged QA entry point')
    helper = Path(PREFLIGHT)
    if (helper.is_symlink() or helper.parent.is_symlink() or not helper.is_file()
            or helper.read_bytes() != managed[PREFLIGHT]):
        raise ValueError('Working preflight.py must match the staged scaffold verifier helper')
    overrides = json_object(read(OVERRIDES), OVERRIDES) if OVERRIDES in index else {}
    # Execute the same verified bytes even if the working helper is replaced after the check.
    module = {'__file__': str(helper.resolve()), '__name__': 'scaffold_preflight'}
    exec(compile(managed[PREFLIGHT], PREFLIGHT, 'exec'), module)
    validate = module['validate_coordinator_overrides']
    project_agents = validate(config, overrides)
    module['validate_required_subagents'](config, project_agents)

    prefix = 'Verified' if qa else 'PASS:'
    print(f'{prefix} {len(managed)} staged manifest SHA-256 digests and shared native role wiring')
    cartman_steps = project_agents.get('Cartman', {}).get('steps', cartman['steps'])
    build_steps = project_agents.get('build', {}).get('steps', build['steps'])
    print(f'Valid project step limits: Cartman={cartman_steps}, build={build_steps}. '
          'Positive project limits may differ between coordinator entries.')
    if qa:
        check_coordinator_policy(validate, config)
        run_staged_suites(managed)
        if scaffold_index() != index:
            raise ValueError('Scaffold index changed during QA; verify the new snapshot')
        override_oid = index[OVERRIDES][1] if OVERRIDES in index else 'absent'
        print(f'PASS: staged scaffold QA (manifest {index[MANIFEST][1]}, '
              f'project overrides {override_oid}, verifier {index[VERIFIER][1]}, plugin suite exit 0)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qa', action='store_true',
                        help='also run the staged, scaffold-managed Node plugin test suites')
    try:
        verify(parser.parse_args().qa)
    except (ValueError, OSError) as error:
        sys.exit(f'verify-scaffold: {error}')
