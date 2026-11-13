"""Conservative, offline adoption of recognized pre-manifest native scaffolds."""
from copy import deepcopy
from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path


def plan(target, contents, catalog, defaults, check_path):
    """Return writes/ownership/messages; never write or infer Markdown semantics."""
    config_path = target / '.opencode/opencode.json'
    if not config_path.is_file():
        raise ValueError('No scaffold manifest or supported legacy .opencode/opencode.json; use newoc --here for an unscaffolded repository')
    if (target / 'opencode.json').exists():
        raise ValueError('Missing scaffold manifest with an existing root opencode.json; ownership is ambiguous, no files changed')
    for path in ['opencode.jsonc', '.opencode/opencode.jsonc']:
        if (target / path).exists():
            raise ValueError('Legacy JSONC configuration needs a reviewed conversion; no files changed')
    check_path(target, config_path)
    old = json.loads(config_path.read_text())
    if not isinstance(old, dict):
        raise ValueError('Legacy configuration must be a JSON object')
    custom = deepcopy(old)
    # Remove only recognized shared defaults. Everything else remains an override.
    for key in list(custom):
        if key not in ('agents', 'plugins', 'permissions', 'instructions') and custom[key] == defaults.get(key):
            del custom[key]
    agents = custom.setdefault('agents', {})
    if not isinstance(agents, dict):
        raise ValueError('Legacy agents configuration must be an object')
    messages = []
    roles = ['Arbiter', 'SCV', 'probe', 'Overlord']
    if (target / '.opencode/agents/Sentry.md').exists():
        roles.append('Sentry')
    for role in roles:
        path = target / f'.opencode/agents/{role}.md'
        check_path(target, path)
        if not path.is_file():
            raise ValueError(f'Incomplete legacy scaffold: missing {path.relative_to(target)}; no files changed')
        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        record = catalog['roles'].get(role, {}).get(fingerprint)
        if record is None:
            raise ValueError(f'Unrecognized/customized legacy role: {path.relative_to(target)}; refusing to overwrite it, no files changed')
        override = agents.get(role, {})
        if not isinstance(override, dict):
            raise ValueError(f'Legacy {role} override must be an object')
        # Recognized frontmatter supplies old model/step settings; JSON overrides
        # retain precedence. Known shared permission lists are replaced as policy.
        settings = {**record['settings'], **override}
        agents[role] = {key: value for key, value in settings.items()
                        if value != defaults['agents'][role].get(key,
                            'primary' if key == 'mode' and role == 'Arbiter' else
                            'subagent' if key == 'mode' else None)}
        messages.append(f'{role}: recognized {record["snapshot"]}; retain model/step overrides')
    for role in list(agents):
        if not isinstance(agents[role], dict):
            raise ValueError(f'Legacy {role} override must be an object')
        agents[role] = {key: value for key, value in agents[role].items()
                        if value != defaults['agents'].get(role, {}).get(key)}
        if not agents[role]:
            del agents[role]

    for field in ('instructions', 'plugins', 'permissions'):
        if not isinstance(custom.get(field, []), list):
            raise ValueError(f'Legacy {field} must be a list')
    instructions = custom.get('instructions', [])
    if not all(isinstance(value, str) for value in instructions):
        raise ValueError('Legacy instructions must contain paths')
    custom['instructions'] = [value for value in instructions if value not in defaults['instructions']]
    plugins = custom.get('plugins', [])
    if not all(isinstance(value, str) for value in plugins):
        raise ValueError('Legacy plugins must contain package/path strings')
    # These two native config layers resolve relative plugin paths differently.
    shared_plugins = {(target / value).resolve() for value in defaults['plugins'] if value.startswith('.')}
    custom['plugins'] = [value for value in plugins
                         if not (value.startswith('.') and
                                 (target / '.opencode' / value).resolve() in shared_plugins)]
    rules = custom.get('permissions', [])
    if any(not isinstance(rule, dict) or not all(isinstance(rule.get(key), str)
           for key in ('action', 'resource', 'effect')) for rule in rules):
        raise ValueError('Invalid legacy permission rule')
    custom['permissions'] = [rule for rule in rules if rule not in defaults['permissions']]
    # A project denial must survive native role rules appended after global rules.
    original_build_rules = deepcopy(agents.get('build', {}).get('permissions', []))
    mirror_roles = set()
    for rule in custom['permissions']:
        if rule['effect'] != 'deny':
            continue
        for role, settings in defaults['agents'].items():
            if any(base['effect'] != 'deny' and
                   (fnmatchcase(rule['action'], base['action']) or fnmatchcase(base['action'], rule['action'])) and
                   (fnmatchcase(rule['resource'], base['resource']) or fnmatchcase(base['resource'], rule['resource']))
                   for base in settings.get('permissions', [])):
                if role not in ('Arbiter', 'build'):
                    raise ValueError(f'Legacy global permission conflicts with {role} policy; no files changed')
                mirror_roles.add(role)
    for role in mirror_roles:
        role_rules = agents.setdefault(role, {}).setdefault('permissions', [])
        if not isinstance(role_rules, list):
            raise ValueError(f'Legacy {role} permissions must be a list')
        # Preserve the complete ordered policy, including later allow exceptions.
        agents[role]['permissions'] = deepcopy(custom['permissions']) + role_rules
    # Desktop and explicit Arbiter are the same coordinator, including constraints.
    arbiter_rules = agents.get('Arbiter', {}).get('permissions', [])
    build_rules = agents.get('build', {}).get('permissions', [])
    if arbiter_rules != build_rules:
        if original_build_rules:
            raise ValueError('Legacy build/Arbiter permissions conflict; no files changed')
        agents.setdefault('build', {})['permissions'] = deepcopy(arbiter_rules)

    writes = {}
    workflow = target / '.opencode/WORKFLOW.md'
    check_path(target, workflow)
    if not workflow.is_file():
        raise ValueError('Incomplete legacy scaffold: missing .opencode/WORKFLOW.md')
    project = Path('.opencode/PROJECT.md')
    if (target / project).exists():
        project = Path('.opencode/LEGACY-PROJECT.md')
    check_path(target, target / project)
    original = workflow.read_bytes()
    if (target / project).exists() and (target / project).read_bytes() != original:
        raise ValueError(f'Legacy project-policy destination collision: {project}; no files changed')
    writes[project] = original
    if str(project) not in defaults['instructions'] and str(project) not in custom['instructions']:
        custom['instructions'].append(str(project))
    project_owned = []
    for relative, data in contents.items():
        path = target / relative
        check_path(target, path)
        if path.exists() and path.read_bytes() != data:
            if str(relative).startswith('.opencode/plugins/'):
                project_owned.append(str(relative))
                messages.append(f'{relative}: preserved project-owned plugin')
                continue
            if relative not in {Path('.opencode/WORKFLOW.md'),
                                *[Path(f'.opencode/agents/{role}.md') for role in roles]}:
                raise ValueError(f'Unowned legacy collision: {relative}; no files changed')
        if not path.exists() or path.read_bytes() != data:
            writes[relative] = data
    custom = {key: value for key, value in custom.items()
              if key not in ('agents', 'plugins', 'permissions', 'instructions') or value}
    writes[Path('.opencode/opencode.json')] = (json.dumps(custom, indent=2) + '\n').encode()
    messages.append(f'WORKFLOW.md: preserve original bytes in {project}')
    return writes, project_owned, custom, messages
