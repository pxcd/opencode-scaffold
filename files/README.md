# {{PROJECT_NAME}}

Created with the native Sol Arbiter + local OpenCode scaffold, version 4.0.0.

Open the repo in OpenCode and use **Arbiter**, the default GPT-6.1 Sol coordinator.
It owns delegation, checkpoints, recovery and fresh independent QA through local
SCV/probe/Overlord subagents, followed by fresh Sentry code review on Sol. Codex is an optional upper-level advisor, not a
resident supervisor. Direct OpenCode use needs no Codex chat or launcher.

Complete root `AGENTS.md` with this project's stack, commands, invariants,
access policy and acceptance, then mark Status: READY. Set project overrides in
`.opencode/opencode.json`; root `opencode.json` contains managed defaults. Review
registered machine providers before inference. Endpoints/authentication stay in
machine OpenCode configuration; never commit credentials. SCV/probe/Overlord and
maintenance helpers are local; Arbiter and Sentry use cloud Sol. Optional local.json
worker overrides apply through the launcher and are ignored by Git.

Preview a prepared repo-local handoff:
`python3.12 .opencode/run-local.py Arbiter --task PATH_TO_HANDOFF`
Inspect effective native routes without inference by adding `--doctor`.
Actual execution requires `--execute --routing-reviewed`; verify provider URLs,
model registration, merged plugins, task authorization and GPU availability.
The launcher does not use --auto or continuously supervise the task.

Shared workflow/roles/config are tracked in `.opencode/scaffold.json`; project
rules stay separate. `newoc --update` previews same-major updates and `--apply`
opts in only if managed files remain unchanged. Major-version migrations require
reviewing project-owned instructions as well. Existing projects never auto-sync.

AGENTS.md, project config overrides and optional PROJECT.md are never overwritten
by setup over an existing file or scaffold updates. Keep shared role policy in the
managed workflow/agents. Native config loads scaffold defaults before project
overrides; no launcher is required. Stricter role permissions belong in
`agents.<role>.permissions`, because native role rules follow global rules.
