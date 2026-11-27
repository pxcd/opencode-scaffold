"""Exercise the deployed merge command with a disposable Git repo and a local gh double."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
PR = 'https://github.com/example/fixture/pull/7'
GH_FIXTURE = '''#!/usr/bin/env python3
import os, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
if len(args) != 6 or args[:5] != ['pr', 'merge', 'https://github.com/example/fixture/pull/7', '--squash', '--match-head-commit']:
    sys.exit(2)
if len(args[-1]) != 40:
    sys.exit(1)
with Path('requests').open('a') as f:
    print(args[-1], file=f)
# Atomically verify the head and record the accepted result like a host mutation.
command = f"verify refs/heads/feature {args[-1]}\\ncreate refs/test/merged {args[-1]}\\n"
sys.exit(subprocess.run(['git','update-ref','--stdin'], input=command, text=True).returncode)
'''


class ReviewedMergeTests(unittest.TestCase):
    def test_only_stans_reviewed_head_can_merge(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / 'fixture'
            subprocess.run([sys.executable, str(ROOT/'newoc.py'), 'fixture', '--root', temp],
                           check=True, capture_output=True)
            env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=repo, env=env, text=True).strip()
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'test@example.invalid')
            git('switch', '-c', 'feature')
            git('commit', '--allow-empty', '-qm', 'reviewed change')
            reviewed = git('rev-parse', 'HEAD')
            git('commit', '--allow-empty', '-qm', 'intervening change')
            current = git('rev-parse', 'HEAD')
            binary = Path(temp)/'gh'
            binary.write_text(GH_FIXTURE)
            binary.chmod(0o755)
            env['PATH'] = temp + os.pathsep + env['PATH']
            flow = (repo/'.opencode/WORKFLOW.md').read_text()
            commands = [line.strip() for line in flow.splitlines() if line.lstrip().startswith('gh pr merge ')]
            self.assertEqual(commands, ['gh pr merge "$pr_url" --squash --match-head-commit "${stan_reviewed_head:?missing reviewed PR head}"'])
            def merge(sha):
                return subprocess.run(['sh', '-eu', '-c', commands[0]], cwd=repo,
                                      env={**env, 'pr_url': PR, 'stan_reviewed_head': sha}, capture_output=True)
            self.assertNotEqual(merge('').returncode, 0)
            self.assertNotEqual(merge(reviewed[:8]).returncode, 0)
            self.assertFalse((repo/'requests').exists())
            self.assertNotEqual(merge(reviewed).returncode, 0)
            self.assertEqual((repo/'requests').read_text().splitlines(), [reviewed])
            self.assertEqual(git('for-each-ref', 'refs/test/merged'), '')
            result = merge(current)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(git('rev-parse', 'refs/test/merged'), current)
            self.assertEqual((repo/'requests').read_text().splitlines(), [reviewed, current])
