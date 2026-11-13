# {{PROJECT_NAME}}

Created with the native Sol Arbiter + local OpenCode scaffold, version 4.1.1.

Open the repo in OpenCode and use GPT-6.1 Sol normally. Desktop's `build` primary
entry is configured as the Arbiter coordinator, with the same shared policy and
bounded delegation as the explicit `Arbiter` CLI/API agent. No @mention or agent
picker is required. The named default remains Arbiter for explicit entry points.
It owns delegation, checkpoints, recovery and fresh independent QA through local
SCV/probe/Overlord subagents, followed by fresh Sentry code review on Sol. Codex is an optional upper-level advisor, not a
resident supervisor. Direct OpenCode use needs no Codex chat or launcher.

Managed `.opencode/BASELINE.md` supplies usable engineering defaults immediately;
AGENTS.md is for optional project rules. Add project-specific
commands, architecture, invariants or references later when helpful. Existing
instructions are preserved; no setup session or READY marker is required.
The coordinator discovers relevant scripts/tests/CI as part of the requested task
and asks only for genuinely missing permissions or consequential decisions.

Set optional project config overrides in `.opencode/opencode.json`; root
`opencode.json` contains managed defaults. Register machine providers/models before
inference; endpoints/authentication stay machine-local. SCV/probe/Overlord and
maintenance helpers are local by default; Arbiter and Sentry use cloud Sol.
Optional local.json worker overrides apply only through the launcher.

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

Customized AGENTS.md, project config overrides and optional PROJECT.md are preserved.
Updates may refresh an untouched generated AGENTS.md starter with a backup, or
restore a missing starter; shared BASELINE.md updates independently. Keep shared role policy in the
managed workflow/agents. Native config loads scaffold defaults before project
overrides; no launcher is required. Stricter role permissions belong in
`agents.<role>.permissions`, because native role rules follow global rules.

Coordinator permission overrides must be identical under both `agents.build` and
`agents.Arbiter`. Updates/dispatch refuse asymmetric rules instead of dropping a
stricter rule when changing entry point. Existing project override files are never
rewritten automatically. Native discovery verifies the actual loaded policy.
