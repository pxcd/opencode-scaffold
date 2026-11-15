"""One-time native role-ID migration; project prose and history are not rewritten."""
from copy import deepcopy
from fnmatch import fnmatchcase
from pathlib import Path

RENAMES = {'Arbiter': 'Cartman', 'SCV': 'Butters', 'Overlord': 'Kyle', 'Sentry': 'Stan'}
RETIRED = 'probe'


def rename_overrides(value, target=None):
    result = deepcopy(value)
    if not isinstance(result, dict):
        raise ValueError('Project configuration must be an object')
    agents = result.get('agents', {})
    if not isinstance(agents, dict):
        raise ValueError('Project agents must be an object')
    for old, new in RENAMES.items():
        if old in agents:
            if new in agents and agents[new] and agents[old] and agents[new] != agents[old]:
                raise ValueError(f'Conflicting {old}/{new} overrides; no files changed')
            previous = agents.pop(old)
            agents[new] = agents.get(new) or previous
    if RETIRED in agents:
        retired = agents[RETIRED]
        if not isinstance(retired, dict) or set(retired) - {'model', 'steps', 'mode', 'description', 'disabled'}:
            raise ValueError('Custom probe policy needs reconciliation with Butters before retiring the UI role; no files changed')
        del agents[RETIRED]
    if result.get('default_agent') in RENAMES:
        result['default_agent'] = RENAMES[result['default_agent']]
    for settings in [result, *agents.values()]:
        if not isinstance(settings, dict):
            raise ValueError('Project agent settings must be objects')
        if 'system' in settings and isinstance(settings['system'], str):
            for old, new in {**RENAMES, RETIRED: 'Butters'}.items():
                paths = [(f'.opencode/agents/{old}.md', f'.opencode/agents/{new}.md'),
                         (f'./.opencode/agents/{old}.md', f'./.opencode/agents/{new}.md')]
                if target is not None:
                    paths.append(tuple(str(Path(target).resolve() / path) for path in paths[0]))
                for old_path, new_path in paths:
                    token = '{file:' + old_path + '}'
                    if token in settings['system']:
                        if old == RETIRED:
                            raise ValueError('Custom system references the retired probe policy; no files changed')
                        settings['system'] = settings['system'].replace(token, '{file:' + new_path + '}')
        rules = settings.get('permissions', [])
        if not isinstance(rules, list):
            raise ValueError('Project permissions must be a list')
        for rule in rules:
            if not isinstance(rule, dict) or not isinstance(rule.get('resource'), str) or not isinstance(rule.get('action'), str):
                continue  # The compatibility checker reports malformed rules.
            resource = rule['resource']
            if fnmatchcase('subagent', rule['action']):
                if rule['action'] == 'subagent' and resource in {**RENAMES, RETIRED: 'Butters'}:
                    rule['resource'] = {**RENAMES, RETIRED: 'Butters'}[resource]
                elif resource in RENAMES.values():
                    pass
                elif any(fnmatchcase(old, resource) and not fnmatchcase(new, resource)
                         for old, new in {**RENAMES, RETIRED: 'Butters'}.items()):
                    raise ValueError(f'Ambiguous legacy subagent permission pattern: {resource}; no files changed')
            if any(fnmatchcase(action, rule['action']) for action in ('read', 'edit')):
                for old, new in {**RENAMES, RETIRED: 'Butters'}.items():
                    paths = [(f'.opencode/agents/{old}.md', f'.opencode/agents/{new}.md')]
                    if target is not None:
                        paths.append(tuple(str(Path(target).resolve() / path) for path in paths[0]))
                    for old_path, new_path in paths:
                        if resource == old_path:
                            if old == RETIRED and rule.get('effect') != 'deny':
                                raise ValueError('Probe-specific file access policy needs review before merging UI into Butters')
                            rule['resource'] = new_path
                        elif resource == new_path:
                            pass
                        elif fnmatchcase(old_path, resource) and not fnmatchcase(new_path, resource):
                            raise ValueError(f'Ambiguous role-file permission pattern: {resource}; no files changed')
    return result
