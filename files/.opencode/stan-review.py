#!/usr/bin/env python3.12
"""Check portable standing authorization for an exact GitHub PR review."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote


OPT_OUT = '.stan-review-local-only'
ORIGIN = re.compile(
    r'(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)'
    r'([A-Za-z0-9-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?'
)


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=20).strip()


def git(*args):
    return command('git', '--no-replace-objects', '--no-optional-locks', *args)


def github(path):
    return json.loads(command('gh', 'api', '--hostname', 'github.com', path))


def repository(remote):
    match = ORIGIN.fullmatch(remote)
    if not match:
        raise ValueError('origin must identify one credential-free github.com repository')
    return match[1].lower()


def authorization(number, head, trusted_base):
    root = Path.cwd().resolve()
    if Path(git('rev-parse', '--show-toplevel')).resolve() != root:
        raise ValueError('run from the confirmed repository root')
    if os.path.lexists(root / OPT_OUT) or git('ls-files', '--stage', '--', OPT_OUT):
        return 'LOCAL_ONLY', 'the checkout or index opts out'
    if git('ls-tree', head, '--', OPT_OUT):
        return 'LOCAL_ONLY', 'the PR head opts out'
    if git('rev-parse', 'HEAD') != head:
        raise ValueError('local HEAD differs from the requested review head')
    origin = repository(git('remote', 'get-url', '--all', 'origin'))
    if repository(git('remote', 'get-url', '--push', '--all', 'origin')) != origin:
        raise ValueError('origin fetch and push repositories differ')

    pr = github(f'repos/{origin}/pulls/{number}')
    base, final = pr['base'], pr['head']
    base_repo, head_repo = base['repo'], final['repo']
    repo = github(f'repos/{origin}')
    if (pr['number'] != number or pr['state'] != 'open' or
            any(side['id'] != repo['id'] or side['full_name'].lower() != origin
                for side in (repo, base_repo, head_repo)) or
            base['ref'] != repo['default_branch'] or final['sha'] != head or
            final['ref'] == base['ref']):
        raise ValueError('PR identity, default base or exact review head cannot be verified')

    live_base = github(f"repos/{origin}/branches/{quote(base['ref'], safe='')}")['commit']['sha']
    if not re.fullmatch('[a-f0-9]{40}', live_base) or live_base != base['sha'] or live_base != trusted_base:
        raise ValueError('the trusted helper revision does not match the live PR base')
    if git('ls-tree', live_base, '--', OPT_OUT):
        return 'LOCAL_ONLY', 'the default branch opts out'
    if repo['permissions']['admin'] is not True:
        raise ValueError('the authenticated GitHub account does not administer the repository')
    return 'STANDING_APPROVAL', f'github.com/{origin} PR #{number}, base {live_base}, head {head}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pr', required=True, type=int)
    parser.add_argument('--head', required=True)
    parser.add_argument('--trusted-base', required=True)
    args = parser.parse_args()
    if args.pr < 1 or any(not re.fullmatch('[a-f0-9]{40}', sha) for sha in (args.head, args.trusted_base)):
        parser.error('a positive PR number and full lowercase head and trusted base SHAs are required')
    try:
        status, reason = authorization(args.pr, args.head, args.trusted_base)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as error:
        status = 'ASK'
        reason = str(error) if type(error) is ValueError else 'required repository or GitHub metadata could not be verified'
    print(f'{status}: {reason}')
    return {'STANDING_APPROVAL': 0, 'ASK': 1, 'LOCAL_ONLY': 2}[status]


if __name__ == '__main__':
    raise SystemExit(main())
