import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('stan_review', ROOT / 'files/.opencode/stan-review.py')
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class StanReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='stan-review-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.git('init', '-q', '-b', 'release/main')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('commit', '--allow-empty', '-qm', 'Base')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('switch', '-qc', 'work/change')
        self.git('commit', '--allow-empty', '-qm', 'Head')
        self.head = self.git('rev-parse', 'HEAD')
        self.git('remote', 'add', 'origin', 'git@github.com:Example-Team/private-tool.git')
        self.repo = {
            'id': 81, 'full_name': 'Example-Team/private-tool', 'default_branch': 'release/main',
            'private': True, 'permissions': {'admin': True},
        }
        self.pr = {
            'number': 2, 'state': 'open',
            'base': {'repo': self.repo, 'sha': self.base, 'ref': 'release/main'},
            'head': {'repo': self.repo, 'sha': self.head, 'ref': 'work/change'},
        }
        self.refs = {'commit': {'sha': self.base}}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def check(self):
        answers = {
            'repos/example-team/private-tool/pulls/2': self.pr,
            'repos/example-team/private-tool': self.repo,
            'repos/example-team/private-tool/branches/release%2Fmain': self.refs,
        }
        with patch.object(POLICY.Path, 'cwd', return_value=self.root), \
             patch.object(POLICY, 'git', side_effect=self.git), \
             patch.object(POLICY, 'github', side_effect=answers.__getitem__):
            return POLICY.authorization(2, self.head)

    def test_same_repo_admin_receives_portable_approval(self):
        status, description = self.check()
        self.assertEqual(status, 'STANDING_APPROVAL')
        self.assertIn(f'head {self.head}', description)
        self.assertIn('github.com/example-team/private-tool', description)

    def test_same_repo_without_admin_and_cross_repo_pr_require_explicit_approval(self):
        self.repo['permissions']['admin'] = False
        with self.assertRaisesRegex(ValueError, 'does not administer'):
            self.check()
        self.repo['permissions']['admin'] = True
        self.pr['head']['repo'] = {**self.repo, 'id': 82, 'full_name': 'elsewhere/private-tool'}
        with self.assertRaisesRegex(ValueError, 'PR identity'):
            self.check()

    def test_pr_base_head_and_origin_must_agree(self):
        self.refs['commit']['sha'] = self.head
        with self.assertRaisesRegex(ValueError, 'live default branch'):
            self.check()
        self.refs['commit']['sha'] = self.base
        self.pr['head']['sha'] = self.base
        with self.assertRaisesRegex(ValueError, 'PR identity'):
            self.check()
        self.pr['head']['sha'] = self.head
        self.git('remote', 'set-url', '--push', 'origin', 'https://github.com/elsewhere/private-tool')
        with self.assertRaisesRegex(ValueError, 'push repositories differ'):
            self.check()

    def test_local_and_staged_markers_opt_out_even_without_network(self):
        marker = self.root / POLICY.OPT_OUT
        marker.touch()
        self.assertEqual(self.check()[0], 'LOCAL_ONLY')
        self.git('add', POLICY.OPT_OUT)
        marker.unlink()
        self.assertEqual(self.check()[0], 'LOCAL_ONLY')

    def test_candidate_cannot_lift_existing_opt_out(self):
        self.git('switch', '-q', 'release/main')
        (self.root / POLICY.OPT_OUT).touch()
        self.git('add', POLICY.OPT_OUT)
        self.git('commit', '-qm', 'Opt out on default')
        self.base = self.git('rev-parse', 'HEAD')
        self.refs['commit']['sha'] = self.base
        self.pr['base']['sha'] = self.base
        self.git('switch', '-qc', 'work/remove-opt-out')
        self.git('rm', '-q', POLICY.OPT_OUT)
        self.git('commit', '-qm', 'Remove opt-out in candidate')
        self.head = self.git('rev-parse', 'HEAD')
        self.pr['head'].update(sha=self.head, ref='work/remove-opt-out')
        self.assertEqual(self.check()[0], 'LOCAL_ONLY')

    def test_candidate_can_opt_out_even_if_default_allows(self):
        (self.root / POLICY.OPT_OUT).touch()
        self.git('add', POLICY.OPT_OUT)
        self.git('commit', '-qm', 'Opt out on feature')
        self.head = self.git('rev-parse', 'HEAD')
        self.pr['head']['sha'] = self.head
        self.git('rm', '-q', POLICY.OPT_OUT)
        self.assertEqual(self.check()[0], 'LOCAL_ONLY')


if __name__ == '__main__':
    unittest.main()
