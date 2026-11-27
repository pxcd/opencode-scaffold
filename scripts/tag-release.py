#!/usr/bin/env python3.12
"""Tag the scaffold revision already merged into the remote default branch."""

import argparse
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def git(*args, check=True):
    return subprocess.run(
        ['git', '-C', str(ROOT), *args], check=check, capture_output=True, text=True,
    ).stdout.strip()


def release(push):
    if git('symbolic-ref', '--quiet', '--short', 'HEAD', check=False) != 'main':
        raise ValueError('Switch to local main after the scaffold PR is merged.')
    commit = git('rev-parse', 'HEAD')
    version = git('show', f'{commit}:TEMPLATE_VERSION')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('The merged TEMPLATE_VERSION must be major.minor.patch.')
    tag = f'v{version}'
    ref = f'refs/tags/{tag}'

    if push and git('remote', 'get-url', '--push', '--all', 'origin') != git('remote', 'get-url', 'origin'):
        raise ValueError('Origin must have one matching fetch and push URL to publish a tag.')
    refs = git('ls-remote', '--symref', 'origin', 'HEAD', 'refs/heads/main', ref, f'{ref}^{{}}').splitlines()
    remote = {name: value for value, name in (line.split('\t', 1) for line in refs)}
    if 'ref: refs/heads/main\tHEAD' not in refs or remote.get('refs/heads/main') != commit:
        raise ValueError('Local main must match the merged commit on origin’s default main branch.')

    local_object = git('rev-parse', '--verify', '--quiet', ref, check=False)
    if local_object and git('rev-parse', '--verify', f'{ref}^{{commit}}', check=False) != commit:
        raise ValueError(f'Local {tag} already points elsewhere. No refs changed.')
    remote_target = remote.get(f'{ref}^{{}}', remote.get(ref))
    if remote_target:
        if remote_target != commit:
            raise ValueError(f'Origin {tag} already points elsewhere. No refs changed.')
        print(f'Origin {tag} already points to {commit}.')
        return

    if not local_object:
        git('tag', '-a', tag, commit, '-m', f'OpenCode scaffold {version}')
    if push:
        git('push', '--no-follow-tags', 'origin', f'{ref}:{ref}')
        print(f'Published {tag} at {commit}.')
    else:
        print(f'Local tag {tag} points to {commit}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--push', action='store_true', help='Publish only this tag to origin')
    args = parser.parse_args()
    try:
        release(args.push)
    except (ValueError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            parser.exit(1, f'tag-release: git {error.cmd[3]} failed (exit {error.returncode}).\n')
        parser.exit(1, f'tag-release: {error}\n')


if __name__ == '__main__':
    main()
