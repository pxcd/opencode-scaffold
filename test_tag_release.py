from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parent / 'scripts/tag-release.py'


class TagReleaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='scaffold-release-')
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.repo = base / 'scaffold'
        self.origin = base / 'origin.git'
        self.repo.mkdir()
        self.git('init', '--quiet', '--initial-branch=main')
        self.git('init', '--quiet', '--bare', '--initial-branch=main', str(self.origin))
        self.git('config', 'user.name', 'Release Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('remote', 'add', 'origin', str(self.origin))
        self.script = self.repo / 'scripts/tag-release.py'
        self.script.parent.mkdir()
        shutil.copyfile(SCRIPT, self.script)
        (self.repo / 'TEMPLATE_VERSION').write_text('4.3.8\n')
        self.git('add', 'TEMPLATE_VERSION')
        self.git('commit', '-qm', 'Merged fixture')
        self.git('push', 'origin', 'main')
        self.merge_commit = self.git('rev-parse', 'HEAD')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True,
                                       stderr=subprocess.PIPE).strip()

    def tag(self, *args, version='4.3.8', commit=None):
        return subprocess.run(['python3.12', str(self.script), '--version', version,
                               '--merge-commit', commit or self.merge_commit, *args], cwd=self.repo,
                              capture_output=True, text=True)

    def test_local_tag_uses_the_committed_version_and_push_publishes_only_it(self):
        (self.repo / 'TEMPLATE_VERSION').write_text('9.9.9\n')
        self.git('tag', '-a', 'unrelated', '-m', 'Unrelated fixture')
        self.git('config', 'push.followTags', 'true')
        result = self.tag()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('cat-file', '-t', 'v4.3.8'), 'tag')
        self.assertEqual(self.git('rev-parse', 'v4.3.8^{commit}'), self.git('rev-parse', 'HEAD'))
        self.assertEqual(self.git('ls-remote', '--tags', 'origin'), '')
        result = self.tag('--push')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('ls-remote', '--tags', 'origin', 'refs/tags/v4.3.8^{}').split()[0],
                         self.git('rev-parse', 'HEAD'))
        self.assertNotIn('unrelated', self.git('ls-remote', '--tags', 'origin'))
        self.git('tag', '-d', 'v4.3.8')
        repeated = self.tag('--push')
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn('already points to', repeated.stdout)
        self.assertEqual(self.git('tag', '--list', 'v4.3.8'), '')

    def test_unmerged_local_head_is_refused(self):
        self.git('commit', '--allow-empty', '-qm', 'Local only')
        result = self.tag('--push', commit=self.git('rev-parse', 'HEAD'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must match', result.stderr)
        self.assertEqual(self.git('tag', '--list', 'v4.3.8'), '')

    def test_conflicting_local_and_remote_tags_are_preserved(self):
        self.git('tag', 'v4.3.8')
        original = self.git('rev-parse', 'v4.3.8')
        self.git('commit', '--allow-empty', '-qm', 'New remote main')
        self.git('push', 'origin', 'main')
        result = self.tag('--push', commit=self.git('rev-parse', 'HEAD'))
        self.assertIn('Local v4.3.8 already points elsewhere', result.stderr)
        self.assertEqual(self.git('rev-parse', 'v4.3.8'), original)
        self.git('push', 'origin', 'refs/tags/v4.3.8')
        self.git('tag', '-d', 'v4.3.8')
        result = self.tag('--push', commit=self.git('rev-parse', 'HEAD'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Origin v4.3.8 already points elsewhere', result.stderr)
        self.assertEqual(self.git('ls-remote', '--tags', 'origin', 'refs/tags/v4.3.8').split()[0], original)

    def test_local_and_remote_main_advance_after_the_authorized_merge(self):
        (self.repo / 'TEMPLATE_VERSION').write_text('4.3.9\n')
        self.git('commit', '-qam', 'Later release')
        self.git('push', 'origin', 'main')
        result = self.tag('--push')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('authorized merge commit', result.stderr)
        self.assertEqual(self.git('tag', '--list'), '')
        self.assertEqual(self.git('ls-remote', '--tags', 'origin'), '')

    def test_wrong_version_cannot_tag_the_authorized_merge(self):
        result = self.tag('--push', version='4.3.9')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('authorized version', result.stderr)
        self.assertEqual(self.git('tag', '--list'), '')

    def test_object_named_branch_cannot_redirect_the_release_tag(self):
        self.assertEqual(self.tag().returncode, 0)
        tag_object = self.git('rev-parse', 'refs/tags/v4.3.8')
        tree = self.git('rev-parse', 'HEAD^{tree}')
        other = self.git('commit-tree', tree, '-m', 'Alternate fixture object')
        self.git('branch', tag_object, other)
        result = self.tag('--push')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('ls-remote', '--tags', 'origin', 'refs/tags/v4.3.8').split()[0], tag_object)
        self.assertEqual(self.git('ls-remote', '--tags', 'origin', 'refs/tags/v4.3.8^{}').split()[0],
                         self.merge_commit)


if __name__ == '__main__':
    unittest.main()
