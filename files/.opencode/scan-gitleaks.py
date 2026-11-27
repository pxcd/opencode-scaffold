#!/usr/bin/env -S python3 -I
"""Offline Gitleaks gate for confirmed shipments and Git pre-push ref updates."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

VERSION = "8.30.1"
FINDINGS = 23
OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class Blocked(Exception):
    pass


def git(*args, env=None, cwd=None):
    proc = subprocess.run(["git", *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL, cwd=cwd, env=env)
    if proc.returncode:
        raise Blocked("Could not resolve the complete Git snapshot. Check repository state.")
    return os.fsdecode(proc.stdout).rstrip("\n")


def oid(value):
    if not OID.fullmatch(value):
        raise Blocked("Invalid object ID in the shipping scope.")
    return value


def tool():
    binary = shutil.which("gitleaks")
    if binary:
        result = subprocess.run([binary, "version"], capture_output=True, stdin=subprocess.DEVNULL)
        if result.returncode == 0 and result.stdout.strip() == VERSION.encode():
            return os.path.abspath(binary)
    raise Blocked(f"Install Gitleaks {VERSION} on the host PATH and retry.")


def ref_updates(lines):
    updates = []
    for line in lines:
        fields = line.split()
        if len(fields) != 4:
            raise Blocked("Malformed pre-push ref update.")
        new, old = oid(fields[1]), oid(fields[3])
        if new.strip("0"):
            updates.append((old if old.strip("0") else None, new))
    return updates


def scan(updates, tree=None):
    if not updates:
        return
    binary = tool()
    if git("rev-parse", "--is-shallow-repository") != "false":
        raise Blocked("Complete local history is required for the credential scan.")
    objects = git("rev-parse", "--path-format=absolute", "--git-path", "objects")
    fmt = git("rev-parse", "--show-object-format")
    if fmt not in ("sha1", "sha256"):
        raise Blocked("Unsupported Git object format.")
    # A private bare repository keeps the scanner independent of worktree edits,
    # branch-owned config, hooks and Git diff drivers. It references local objects.
    with tempfile.TemporaryDirectory(prefix="ship-gitleaks-") as temp:
        root = Path(temp)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "GITLEAKS_"))}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1",
                   GIT_AUTHOR_NAME="Scan", GIT_COMMITTER_NAME="Scan",
                   GIT_AUTHOR_EMAIL="scan@example.invalid", GIT_COMMITTER_EMAIL="scan@example.invalid")
        db = root / "objects.git"
        git("init", "-q", "--bare", "--template=", f"--object-format={fmt}", str(db), cwd=root, env=env)
        if "\n" in objects:
            raise Blocked("Unsupported object directory name.")
        (db / "objects/info/alternates").write_bytes(os.fsencode(objects) + b"\n")
        config, ignores, report = (root / name for name in ("policy.toml", "ignores", "report.json"))
        config.write_text("[extend]\nuseDefault = true\n")
        ignores.touch()

        for old, new in dict.fromkeys(updates):
            tip = git("rev-parse", "--verify", oid(new) + "^{commit}", cwd=db, env=env)
            if tree is not None:
                # Include staged blobs as an extra commit without touching refs or the live index.
                tip = git("commit-tree", oid(tree), "-p", tip, "-m", "Staged snapshot", cwd=db, env=env)
            revisions = tip
            if old:
                prev = subprocess.run(["git", "rev-parse", "--verify", oid(old) + "^{commit}"],
                                      cwd=db, env=env, capture_output=True)
                if prev.returncode == 0:
                    revisions = oid(prev.stdout.decode().strip()) + ".." + tip
                # Unknown remote tip (e.g. a force push) requires the full ancestry.
            report.unlink(missing_ok=True)
            result = subprocess.run(
                [binary, "git", "--log-opts", "--root --full-history --diff-merges=first-parent " + revisions,
                 "--config", str(config), "--gitleaks-ignore-path", str(ignores), "--ignore-gitleaks-allow",
                 "--redact=100", "--exit-code", str(FINDINGS), "--no-banner", "--no-color",
                 "--log-level", "error", "--report-format", "json", "--report-path", str(report), str(db)],
                cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            # Gitleaks can log a Git enumeration error separately from its findings exit code.
            if result.returncode not in (0, FINDINGS) or result.stderr.strip() or not report.is_file():
                raise Blocked("Gitleaks could not complete the scan. Check Git history and the pinned binary.")
            findings = json.loads(report.read_bytes())
            if not isinstance(findings, list) or bool(findings) != (result.returncode == FINDINGS):
                raise Blocked("Incomplete Gitleaks result.")
            if findings:
                details = []
                for item in findings[:8]:
                    details.append(f"{json.dumps(item['File'], ensure_ascii=True)}:{int(item['StartLine'])} ({item['RuleID']})")
                raise Blocked(f"{len(findings)} potential credential(s) found: " + ", ".join(details))


def main():
    if Path(__file__).name == "pre-push" or sys.argv[1:] == ["pre-push"]:
        scan(ref_updates(sys.stdin))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("mode", choices=["ship"])
        parser.add_argument("base")
        parser.add_argument("head")
        parser.add_argument("tree", nargs="?")
        args = parser.parse_args()
        scan([(oid(args.base), oid(args.head))], oid(args.tree) if args.tree else git("write-tree"))


if __name__ == "__main__":
    try:
        main()
    except Blocked as exc:
        sys.exit(f"Credential scan blocked: {exc}")
    except (OSError, ValueError, KeyError, TypeError):
        sys.exit("Credential scan blocked: unreadable scanner result or local dependency.")
