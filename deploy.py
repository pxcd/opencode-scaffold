#!/usr/bin/env python3.12
"""Deploy the reviewed newoc starter locally; preview by default, back up on apply."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import tempfile


def deploy(source, destination, apply=False):
    destination = destination.expanduser().absolute()
    for parent in [destination, *destination.parents]:
        if parent.is_symlink():
            raise ValueError(f'Refusing symlink deployment path: {parent}')
    if destination.exists() and not destination.is_dir():
        raise ValueError('Deployment destination must be a directory')
    if source.resolve() == destination.resolve():
        raise ValueError('Source and deployment must be different directories')
    print(f'{"Deploying" if apply else "Preview"}: {source} -> {destination}')
    if not apply:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.newoc-stage-', dir=destination.parent))
    backup = None
    try:
        for name in ['files', 'starter-history', 'legacy-history', 'legacy.py', 'newoc.py', 'newoc.zsh', 'deploy.py', 'test_newoc.py', 'TEMPLATE_VERSION', 'README.md']:
            src = source / name
            if src.is_dir():
                shutil.copytree(src, stage / name)
            else:
                shutil.copyfile(src, stage / name)
        if destination.exists():
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = destination.with_name(destination.name + '.backup-' + stamp)
            os.rename(destination, backup)
        try:
            os.rename(stage, destination)
        except OSError:
            if backup:
                os.rename(backup, destination)
            raise
        print(f'Deployed; previous starter retained at {backup}' if backup else 'Deployed')
        return backup
    finally:
        if stage.exists():
            shutil.rmtree(stage)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path.home()/'.config/project-templates/opencode')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        deploy(Path(__file__).resolve().parent, args.target, args.apply)
    except (OSError, ValueError) as error:
        parser.exit(1, f'deploy: {error}\n')
