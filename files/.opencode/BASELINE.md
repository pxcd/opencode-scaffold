# Shared engineering defaults

Start the authorized task immediately. These defaults are loaded by native
configuration even when project AGENTS.md is missing or customized. Project-specific
instructions are optional additions; honor their substantive restrictions without
requiring a separate setup session, questionnaire or readiness marker.

- Inspect the actual checkout, relevant source, package/build scripts and CI before
  changing behavior. Discover the project's commands and conventions from evidence;
  do not invent a stack or require a separate setup session to investigate/delegate.
- Preserve existing tracked and untracked work. Change and stage only task-related
  files. Do not reset, stash, clean, delete or overwrite unrelated work.
- Keep changes small and consistent with the repository. Preserve public interfaces
  and existing security/data boundaries unless the task explicitly changes them.
- Start with the narrowest meaningful check, then run the relevant project/CI gates.
  Use synthetic/local fixtures where possible. Record actual commands, exits and
  limitations; do not treat skipped/unexecuted checks as passing or self-approve.
- Use relevant repository source and synthetic fixtures for the authorized task.
  Do not read or expose credentials, private runtime data, personal datasets or
  unrelated archives. Ask before an action actually needs additional data access,
  live services/device control, dependency installation or machine configuration.
- Do not start application services, training or unrelated GPU workloads as routine
  checks. Configured worker delegation for the requested task is normal operation;
  keep local workers sequential and respect existing workload restrictions.
- Commits, pushes, PRs, merges, deployments and destructive cleanup require task
  authorization. Preserve required review, CI and human-acceptance gates; never
  waive them or fabricate evidence to finish a task.
- Missing project details restrict only the affected action. Inspect or delegate
  discovery, continue independent safe work, and ask a focused question only for
  a consequential decision the repository and user request cannot establish.

## Session repository boundary

Before working, confirm the session's recorded absolute directory and resolve the
repository root (for Git, `git rev-parse --show-toplevel`). Arbiter and every worker
must agree on that root before any source access or edits. A mismatch is a
CHECKPOINT: report it rather than changing the session directory. The selected
checkout is authoritative; inherited Codex cwd, project display names and historical
evidence paths are not substitutes. Never select `~/.codex/worktrees/` merely
because Codex initiated a handoff.

By default, read/write project source, checkpoints, diagnostics and QA evidence
only inside that repository. Keep useful raw findings, reproductions, logs and
recovery notes under `.opencode/evidence/<task>/` (Git-ignored); routine discussion
belongs in chat, not mandatory files. Resolve evidence paths before writing and
refuse symlinks that escape the root. Do not relocate existing evidence.
Source changes and intentional deliverable documentation belong in their normal
project paths. Scratch notes/findings/logs are not deliverables: never force-add
or include `.opencode/evidence/` in a commit or publication scope.

Access to another checkout, an external worktree, historical evidence outside the
root, or a change of session directory requires explicit user authorization for
the exact path and purpose. "Work autonomously" does not grant filesystem scope.
Do not copy, modify or relocate historical evidence automatically. Arbiter must
arrange required external-access approvals before an unattended batch. Workers
must checkpoint unexpected access needs to Arbiter; never bypass a denial using
shell, scripts, symlinks, alternate tools or path spellings. Authorization does not
override a native deny: use bounded authorized facts supplied by Arbiter or have
the user explicitly approve a reviewed permission change before dispatch.

Normal OpenCode loading of machine provider configuration, authentication and
tool-managed session/output data is infrastructure, not project evidence. Leave
those stores in place; do not copy credentials/configuration into evidence or
request broad filesystem access to inspect them. A necessary agent-initiated read
of an external store still needs scoped authorization. Configuration loading is
not authorization to investigate arbitrary files beside it. Tool permissions are
not OS-level filesystem isolation; shell, plugins and other tools may have host
access beyond what the permission scanner detects. Honor the boundary regardless.
Do not enable auto-approval to satisfy an external-access requirement.
