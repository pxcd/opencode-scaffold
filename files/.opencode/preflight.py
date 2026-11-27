"""Shared scaffold compatibility checks; no inference or project writes."""
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path

OVERRIDES = Path('.opencode/opencode.json')
COORDINATORS = ('Cartman', 'build')
NON_ORCHESTRATION_DIRECTORIES = {'evidence', 'node_modules', '__pycache__', '.git'}


def validate_coordinator_overrides(defaults, overrides):
    """Validate the coordinator entries from supplied project config layers."""
    if not isinstance(overrides, dict):
        raise ValueError('Project overrides must be a JSON object')
    if overrides.get('default_agent', 'Cartman') != 'Cartman':
        raise ValueError('Project override conflicts with scaffold default_agent Cartman')
    agents = overrides.get('agents', {})
    if not isinstance(agents, dict):
        raise ValueError('Project agents override must be an object')
    # Both entry points are the same coordinator. Do not silently lose a stricter
    # project rule when Desktop chooses build instead of the explicit Cartman role.
    coordinator_permissions = []
    for role in COORDINATORS:
        custom = agents.get(role, {})
        if not isinstance(custom, dict):
            raise ValueError(f'Invalid project override for {role}')
        shared = defaults['agents'][role]
        if custom.get('disabled') or custom.get('mode', 'primary') != 'primary':
            raise ValueError(f'Project override disables or changes required role {role}')
        if custom.get('model', shared['model']) != shared['model']:
            raise ValueError(f'Project override conflicts with pinned {role} model')
        policy = defaults['agents']['build']['system']
        if custom.get('system', policy) != policy:
            raise ValueError(f'Project {role} system override conflicts with the shared coordinator policy; move project constraints to project-owned AGENTS.md, PROJECT.md or native instructions before updating')
        steps = custom.get('steps', shared['steps'])
        if type(steps) is not int or steps < 1:
            raise ValueError(f'Invalid project step limit for {role}')
        rules = custom.get('permissions', [])
        if not isinstance(rules, list) or any(
                not isinstance(rule, dict)
                or not all(isinstance(rule.get(k), str) for k in ('action', 'resource', 'effect'))
                or rule['effect'] not in ('allow', 'ask', 'deny') for rule in rules):
            raise ValueError(f'Invalid project permission override for {role}')
        coordinator_permissions.append(rules)
    if coordinator_permissions[0] != coordinator_permissions[1]:
        raise ValueError('Mirror coordinator permission overrides in agents.Cartman.permissions and agents.build.permissions before updating or dispatching')
    return agents


def validate_required_subagents(defaults, agents):
    """Keep managed worker and reviewer roles enabled in the project layer."""
    for role in ('Butters', 'Kyle', 'Stan', 'Chef'):
        if role not in defaults['agents']:
            continue
        custom = agents.get(role, {})
        if not isinstance(custom, dict):
            raise ValueError(f'Invalid project override for {role}')
        if custom.get('disabled') or custom.get('mode', 'subagent') != 'subagent':
            raise ValueError(f'Project override disables or changes required role {role}')


def validate_overrides(target, defaults, overrides=None):
    """Check scaffold invariants without rewriting project-owned configuration."""
    if (target / '.opencode/opencode.jsonc').exists() or (target / 'opencode.jsonc').exists():
        raise ValueError('JSONC config requires a reviewed migration to the scaffold JSON override layout')
    path = target / OVERRIDES
    if path.is_symlink():
        raise ValueError('Refusing symlink project overrides')
    if overrides is None:
        overrides = json.loads(path.read_text()) if path.exists() else {}
    protected = set()
    # Inspect names, not contents. Include shipped and existing custom orchestration;
    # never walk investigation logs or dependency/vendor trees for this check.
    for folder in (Path(__file__).resolve().parent, target / '.opencode'):
        for parent, directories, files in os.walk(folder, followlinks=False):
            directories[:] = [d for d in directories if d not in NON_ORCHESTRATION_DIRECTORIES]
            for name in files:
                relative = (Path(parent) / name).relative_to(folder)
                if relative != Path('PROJECT.md'):
                    protected.add(str(Path('.opencode') / relative))
    validate_project_policy(target, defaults, overrides, protected)
    return overrides


def validate_project_policy(target, defaults, overrides, protected_paths):
    """Check supplied settings without loading project configuration from disk."""
    agents = validate_coordinator_overrides(defaults, overrides)
    validate_required_subagents(defaults, agents)
    global_rules = overrides.get('permissions', [])
    if not isinstance(global_rules, list) or any(
            not isinstance(r, dict) or not all(isinstance(r.get(k), str) for k in ('action', 'resource', 'effect'))
            or r['effect'] not in ('deny', 'allow', 'ask') for r in global_rules):
        raise ValueError('Project permissions must be a list of action/resource/effect rules')
    protected = {'opencode.json', 'opencode.jsonc', '.opencode/opencode.json', '.opencode/opencode.jsonc'}
    for path in protected_paths:
        if (path.startswith('.opencode/') and path != '.opencode/PROJECT.md'
                and NON_ORCHESTRATION_DIRECTORIES.isdisjoint(Path(path).parts[1:-1])):
            protected.add(path)
    root = target.resolve()
    for role, shared in defaults['agents'].items():
        custom = agents.get(role, {})
        if not isinstance(custom, dict):
            raise ValueError(f'Invalid project override for {role}')
        if role in ('Stan', 'Chef') and custom.get('model', shared['model']) != shared['model']:
            raise ValueError(f'Project override conflicts with pinned {role} model')
        if role == 'Chef' and ('system' in custom or 'request' in custom):
            raise ValueError('Project override conflicts with Chef planning policy or request settings')
        rules = custom.get('permissions', [])
        if not isinstance(rules, list):
            raise ValueError(f'Project {role} permissions must be a list')
        for rule in rules:
            if not isinstance(rule, dict) or not all(isinstance(rule.get(k), str) for k in ('action', 'resource', 'effect')):
                raise ValueError(f'Invalid permission override for {role}')
            if rule['effect'] not in ('allow', 'ask', 'deny'):
                raise ValueError(f'Invalid permission effect for {role}')
            if role == 'Chef' and rule['effect'] != 'deny':
                raise ValueError('Project override weakens Chef read-only permissions')
            if role == 'Stan' and rule['effect'] != 'deny' and any(
                    fnmatchcase(action, rule['action']) for action in
                    ('edit', 'shell', 'execute', 'subagent', 'external_directory')):
                raise ValueError('Project override weakens Stan read-only permissions')
            if role in ('Butters', 'Kyle') and rule['effect'] != 'deny' and fnmatchcase('subagent', rule['action']):
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
        if role in (*COORDINATORS, 'Butters', 'Kyle', 'Stan', 'title', 'summary', 'compaction'):
            if decision('external_directory', '*') == 'allow':
                raise ValueError(f'Project override grants unrestricted external access to {role}; use explicitly authorized scoped paths')
        if role in ('Butters', 'Kyle'):
            for path in sorted(protected):
                for resource in (path, str(root / path)):
                    if decision('edit', resource) == 'allow':
                        raise ValueError(f'Project override permits {role} to edit orchestration: {path}')
        if role in COORDINATORS:
            children = {r['resource'] for r in shared['permissions']
                        if r['action'] == 'subagent' and r['effect'] == 'allow'}
            # A project can opt out of the advisory cloud route.
            for child in sorted(children - {'Chef'}):
                if decision('subagent', child) != 'allow':
                    raise ValueError(f'Project override blocks {role} delegation to {child}; reconcile it explicitly')
        elif role == 'Stan':
            for action in ('edit', 'shell', 'execute', 'subagent', 'external_directory'):
                if decision(action, '*') != 'deny':
                    raise ValueError(f'Project override weakens Stan {action} denial')
    return agents
