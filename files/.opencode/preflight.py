"""Shared scaffold compatibility checks; no inference or project writes."""
from fnmatch import fnmatchcase
import json
from pathlib import Path

OVERRIDES = Path('.opencode/opencode.json')


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
    coordinators = ('Arbiter', 'build')
    # Both entry points are the same coordinator. Do not silently lose a stricter
    # project rule when Desktop chooses build instead of the explicit Arbiter role.
    coordinator_permissions = []
    for role in coordinators:
        custom = agents.get(role, {})
        if not isinstance(custom, dict):
            raise ValueError(f'Invalid project override for {role}')
        coordinator_permissions.append(custom.get('permissions', []))
    if coordinator_permissions[0] != coordinator_permissions[1]:
        raise ValueError('Mirror coordinator permission overrides in agents.Arbiter.permissions and agents.build.permissions before updating or dispatching')
    global_rules = overrides.get('permissions', [])
    if not isinstance(global_rules, list) or any(
            not isinstance(r, dict) or not all(isinstance(r.get(k), str) for k in ('action', 'resource', 'effect'))
            or r['effect'] not in ('deny', 'allow', 'ask') for r in global_rules):
        raise ValueError('Project permissions must be a list of action/resource/effect rules')
    for role, shared in defaults['agents'].items():
        custom = agents.get(role, {})
        if not isinstance(custom, dict):
            raise ValueError(f'Invalid project override for {role}')
        if role in (*coordinators, 'Sentry') and custom.get('model', shared['model']) != shared['model']:
            raise ValueError(f'Project override conflicts with pinned {role} model')
        if role in (*coordinators, 'SCV', 'probe', 'Overlord', 'Sentry'):
            mode = 'primary' if role in coordinators else 'subagent'
            if custom.get('disabled') or custom.get('mode', mode) != mode:
                raise ValueError(f'Project override disables or changes required role {role}')
        if role == 'build' and 'system' in custom and custom['system'] != shared['system']:
            raise ValueError('Project build system override conflicts with the shared coordinator policy')
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
        if role in coordinators:
            children = {r['resource'] for r in shared['permissions']
                        if r['action'] == 'subagent' and r['effect'] == 'allow'}
            for child in sorted(children):
                if decision('subagent', child) != 'allow':
                    raise ValueError(f'Project override blocks {role} delegation to {child}; reconcile it explicitly')
        elif role == 'Sentry':
            for action in ('edit', 'shell', 'execute', 'subagent', 'external_directory'):
                if decision(action, '*') != 'deny':
                    raise ValueError(f'Project override weakens Sentry {action} denial')
    return overrides
