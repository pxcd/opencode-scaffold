"""Integration tests against the pinned Gitleaks binary and a private local remote."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCAFFOLD = Path(__file__).resolve().parent
NEWOC = [sys.executable, str(SCAFFOLD / "newoc.py")]
TOKEN = "ghp_" + "AsD1xY2pQrZvNhCk43uJkBdQ7oG2wPox4ZnB"


class CredentialGateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = self.root / "project"
        self.remote = self.root / "remote.git"
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        self.cmd(*NEWOC, "project", "--root", str(self.root), cwd=self.root)
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("init", "--bare", str(self.remote))
        self.git("remote", "add", "origin", str(self.remote))
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.cmd(*NEWOC, "--enable-secret-scan")
        self.git("push", "-q", "origin", "HEAD:refs/heads/base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def cmd(self, *args, cwd=None, ok=True, env=None, input=None):
        result = subprocess.run(args, cwd=cwd or self.repo, env=env or self.env,
                                input=input, capture_output=True, text=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def git(self, *args, **kw):
        return self.cmd("git", *args, **kw)

    def commit(self, path, content):
        (self.repo / path).write_text(content)
        self.git("add", "--", path)
        self.git("commit", "-qm", "fixture change")
        return self.git("rev-parse", "HEAD").stdout.strip()

    def test_clean_scope_ignores_unrelated_dirty_and_untracked_data(self):
        (self.repo / "private.txt").write_text(TOKEN)
        (self.repo / "README.md").write_text(TOKEN)
        self.commit("feature.txt", "clean\n")
        before = self.git("status", "--porcelain=v1").stdout
        self.git("push", "origin", "HEAD:refs/heads/base")
        self.assertEqual(self.git("status", "--porcelain=v1").stdout, before)
        self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", "base").stdout,
                         self.git("rev-parse", "HEAD").stdout)

    def test_secrets_removed_later_block_existing_and_new_refs_with_redaction(self):
        self.commit("settings.py", f'API_TOKEN="{TOKEN}"\n')
        self.commit("settings.py", "# clean\n")
        for ref in ("base", "new"):
            result = self.git("push", "origin", f"HEAD:refs/heads/{ref}", ok=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('"settings.py":1 (github-pat)', result.stderr)
            self.assertNotIn(TOKEN, result.stderr + result.stdout)
        self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", "base").stdout.strip(), self.base)

    def test_multiple_refs_are_checked_and_deletion_only_needs_no_scan(self):
        good = self.commit("feature.txt", "clean\n")
        self.commit("settings.py", f'API_TOKEN="{TOKEN}"\n')
        result = self.git("push", "origin", f"{good}:refs/heads/good", "HEAD:refs/heads/bad", ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("github-pat", result.stderr)
        self.assertEqual(self.git("--git-dir", str(self.remote), "for-each-ref", "--format=%(refname)").stdout.strip(),
                         "refs/heads/base")
        self.git("push", "origin", ":refs/heads/base")

    def test_merge_only_findings_are_detected(self):
        self.git("switch", "-qc", "side")
        self.commit("side.txt", "side\n")
        self.git("switch", "--detach", self.base)
        self.commit("main.txt", "other\n")
        self.git("merge", "--no-ff", "--no-commit", "side")
        self.commit("settings.py", f'API_TOKEN="{TOKEN}"\n')
        result = self.git("push", "origin", "HEAD:refs/heads/base", ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("github-pat", result.stderr)

    def test_hook_activation_is_idempotent_and_preserves_custom_hooks(self):
        self.cmd(*NEWOC, "--enable-secret-scan")
        hook = self.repo / ".git/hooks/pre-push"
        hook.write_text("#!/bin/sh\nexit 17\n")
        self.assertNotEqual(self.cmd(*NEWOC, "--enable-secret-scan", ok=False).returncode, 0)
        self.assertIn("exit 17", hook.read_text())
        self.git("config", "core.hooksPath", "existing-hooks")
        self.assertNotEqual(self.cmd(*NEWOC, "--enable-secret-scan", ok=False).returncode, 0)
        self.assertFalse((self.repo / "existing-hooks").exists())

    def test_missing_or_wrong_version_and_incomplete_refs_block(self):
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "git").symlink_to(shutil.which("git"))
        env = {**self.env, "PATH": str(bin_dir)}
        scan = [sys.executable, "-I", str(self.repo / ".opencode/scan-gitleaks.py")]
        args = ["ship", self.base, self.base, self.git("rev-parse", "HEAD^{tree}").stdout.strip()]
        self.assertIn("Install Gitleaks 8.30.1", self.cmd(*scan, *args, env=env, ok=False).stderr)
        wrong = bin_dir / "gitleaks"
        wrong.write_text("#!/bin/sh\necho 8.0.0\n")
        wrong.chmod(0o755)
        self.assertIn("Install Gitleaks 8.30.1", self.cmd(*scan, *args, env=env, ok=False).stderr)
        bad = self.cmd(*scan, "pre-push", input="refs/heads/test malformed\n", ok=False)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("Malformed", bad.stderr)


if __name__ == "__main__":
    unittest.main()
