# Native Sol Arbiter + local OpenCode scaffold 3.0.2

The existing `newoc` command creates projects with **GPT-6.1 Sol as the native
OpenCode Arbiter**, local SCV/probe/Overlord subagents, and optional Codex oversight.
Arbiter owns the complete delegation, checkpoint, recovery and independent-QA loop.
It does not depend on a Codex chat polling or approving routine checkpoints.

```sh
newoc my-project
# Python workflow remains compatible:
newpy my-python-project
newoc --here
```

`newpy` remains independent. New projects default to ~/Development; use
--root PATH for another parent. `--here` preserves an existing README, Git state,
Python files/venv and ignore entries, but rejects other collisions before writing.
New scaffolds create a main Git branch without commits/remotes. No packages,
models, applications, inference or project publication are started by setup.

## Ownership and routing

| Layer | Files | Responsibility |
| --- | --- | --- |
| Shared orchestration | `.opencode/WORKFLOW.md`, `agents/`, `opencode.json`, `run-local.py`, compatibility hook | Native Sol Arbiter and bounded local workers |
| Project contract | `AGENTS.md`, `.opencode/PROJECT.md`, README, issue/PR templates, `.gitignore` | Actual stack, commands, invariants, access and acceptance; project-owned |
| Machine configuration | OpenCode provider registration/endpoints/auth; optional ignored `.opencode/local.json` | Machine-local; never commit credentials |

Arbiter is primary, pinned to `openai/gpt-6.1-sol`, and can dispatch only SCV,
probe and Overlord. Workers are native subagents with delegation denied. Default
worker model IDs match the current registered LM Studio choices: Swift1.5 Qwen3.8
Splash for SCV/Overlord and Qwen3.6 35B A3B for probe. Summary/compaction use the
local QA model; titles use the local presentation model. Only Arbiter is cloud.
Model IDs are editable repo defaults, not credentials or installed models.

On another machine, register the providers/models and deliberately adjust native
opencode.json IDs before use. An optional local.json, copied from local.example.json,
overrides worker/helper IDs only through the launcher. Without that profile, the
launcher preserves native worker/helper routes; bare OpenCode uses native
repo defaults. Direct OpenCode therefore needs no ignored profile, launcher or
Codex connection. Machine-specific model tuning is not bundled; verify it against
the selected model/runtime rather than importing another project's hooks blindly.

Complete PROJECT.md before substantive work. Arbiter must honor its privacy,
network, ownership, build/test and delivery rules. Codex can prepare a handoff,
give requested advice or review final evidence. Native Sol handles routine worker
failures itself. Genuine permissions, unresolved concrete blockers and the agreed
human acceptance/publication gates still go to the user. One execution coordinator
owns a task; do not run a competing Codex worker loop alongside Arbiter.

## Optional launcher and evidence

Use `python3.12 .opencode/run-local.py Arbiter --task <repo-local-handoff>` to
preview a launch; --doctor inspects native agent discovery without inference.
Execution additionally requires --execute --routing-reviewed. Confirm the actual
provider endpoints and merged config/plugins first: a provider ID does not prove
a local endpoint. Do not start inference during a conflicting GPU workload.

The launcher dispatches Arbiter only, supports resuming a known healthy Arbiter
session in the same checkout, retains process exits/raw logs and holds a checkout
lock. Inspect a stale lock's PID/native session before removing it. Fresh Overlord
sessions remain Arbiter's responsibility. There is no --auto, resident Codex
supervisor, hard runtime timeout or machine-validated verdict receipt. Exit0 is
not QA acceptance; source identity, executed gates and test counts/skips matter.
Permissions are not OS containment, especially with shell access.

## Maintenance and deployment

This Git repository at `~/Development/opencode-scaffold` is the editable source
of truth. The local `newoc` shell entry loads `newoc.zsh` directly from this repo;
the helper resolves its templates beside its defining file. `NEWOC_TEMPLATE_DIR`
remains an explicit override. Shared templates live in `files/`; generated
project contracts remain project-owned. No existing project is updated by moving
or editing this repository. Validate changes before generating or updating projects:

```sh
python3.12 -m unittest -v test_newoc.py
node --test files/.opencode/plugins/step-limit-compat/normalize.test.mjs
python3.12 deploy.py                 # preview installed-starter replacement
python3.12 deploy.py --apply         # explicit deployment; retain previous backup
```

`~/.zshrc` sources `~/Development/opencode-scaffold/newoc.zsh`. Open a new shell,
or source that helper in an existing shell, to pick up the new location.
On another workstation, clone this repo and source its `newoc.zsh` from your shell
startup file. It works from other checkout paths without editing the helper.
New projects receive the checkout's templates; pin/review a Git revision before
use. The previous `~/.config/project-templates/opencode` deployment is retained
but is no longer the default for this shell entry. `deploy.py` remains available
for users who prefer a separate installed copy. Its deployment commands above
are optional and were not run during this move.
Existing projects keep their copies and manifests until explicitly updated:

```sh
newoc --update                       # preview compatible same-major update
newoc --update --apply               # apply after ownership checks
```

Updates refuse managed-file edits, symlinks, active locks, implicit downgrades,
file removal without migration and cross-major changes. Project-owned contracts,
README/AGENTS and ignored local routing are never automatically replaced. A reviewed
migration may list customized template paths in manifest `project_owned`; these
are excluded from automatic updates and must not also appear in managed `files`.
Keep their rules/models/hooks under project review. Finder `.DS_Store` metadata
is excluded from generation and updates; legacy metadata ownership is retired
without deleting the existing file.

### Migrating from2.x

Version2 used Codex-direct primary workers; version3 uses native Sol Arbiter and
local subagents. A managed-files-only update would leave conflicting project-owned
AGENTS.md/README.md instructions. Cross-major --update therefore stops before any
writes. Generate a disposable v3 project and review/merge its role/config/workflow,
launcher and instruction changes with the actual target's project contract, native
model choices and hooks. Preserve all dirty work. Verify native discovery, project
checks and source identity before recording the new baseline. Do not blindly copy
a generic manifest over a customized project or run --here to force adoption.
Version1 projects without a manifest also need a reviewed migration.

Rollback the installed starter by deploying a reviewed previous source/backup;
existing projects remain unchanged. Roll back project changes through their own
reviewed history. There is no automatic fleet sync or bulk migration.

## Compatibility and limits

Native discovery is validated with installed OpenCode v2.2.6. Recheck its V2
agents/permissions, Markdown roles and CLI syntax on upgrades. Reference docs:
https://opencode.ai/v2/docs/agents and https://opencode.ai/v2/docs/config.
Tests use isolated repositories/fake workers and the actual newpy function
without sourcing unrelated startup. Native discovery is configuration evidence,
not sustained live Sol-to-local orchestration acceptance. Run a deliberate small
smoke task when inference is authorized and GPU capacity is available.

## Publication permission policy (3.0.1)

Shared configuration denies Git pushes for workers and helpers. Only Arbiter can request native approval for an ordinary push, after explicit task authorization. Force/mirror pushes and remote-ref deletion remain denied. This does not authorize publication or waive the project's PR, CI and human-acceptance gates. Shell permission patterns are best-effort checks, not OS containment. Existing projects require an explicit reviewed update.
