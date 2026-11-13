# Native Sol Arbiter + local OpenCode scaffold 4.0.3

The existing `newoc` command creates projects with **GPT-6.1 Sol as the native
OpenCode Arbiter**, local SCV/probe/Overlord subagents, a separate Sol **Sentry**
reviewer, and optional Codex oversight.
Arbiter owns the complete delegation, checkpoint, recovery and independent-QA loop.
It does not depend on a Codex chat polling or approving routine checkpoints.

```sh
newoc my-project
# Python workflow remains compatible:
newpy my-python-project
newoc --here
```

`newpy` remains independent. New projects default to ~/Development; use
--root PATH for another parent. `--here` preserves existing AGENTS.md, README, project overrides, Git state,
Python files/venv and ignore entries, but rejects other collisions before writing.
New scaffolds create a main Git branch without commits/remotes. No packages,
models, applications, inference or project publication are started by setup.

## Ownership and routing

| Layer | Files | Responsibility |
| --- | --- | --- |
| Shared orchestration | root `opencode.json`, `.opencode/WORKFLOW.md`, `.opencode/agents/`, launcher and compatibility hook | Updated together; do not edit managed defaults |
| Project instructions | root `AGENTS.md`, optional `.opencode/PROJECT.md`, README, issue/PR templates, `.gitignore` | Project-owned; existing files are never replaced |
| Project configuration | `.opencode/opencode.json` | Native overrides for models, additional plugins/instructions and stricter per-agent permissions; never replaced |
| Machine configuration | OpenCode provider registration/endpoints/auth; optional ignored `.opencode/local.json` | Machine-local; never commit credentials |

Arbiter is primary, pinned to `openai/gpt-6.1-sol`, and can dispatch only SCV,
probe, Overlord and Sentry. All subagents have delegation denied. Default local
worker model IDs match the current registered LM Studio choices: Swift1.5 Qwen3.8
Splash for SCV/Overlord and Qwen3.6 35B A3B for probe. Summary/compaction use the
local QA model; titles use the local presentation model. Arbiter and Sentry use cloud Sol.
Model IDs are editable repo defaults, not credentials or installed models.

On another machine, register providers/models and set project overrides in
`.opencode/opencode.json`; keep root `opencode.json` as the managed defaults. An optional local.json, copied from local.example.json,
overrides worker/helper IDs only through the launcher. Without that profile, the
launcher preserves native worker/helper routes; bare OpenCode uses native
repo defaults. Direct OpenCode therefore needs no ignored profile, launcher or
Codex connection. Machine-specific model tuning is not bundled; verify it against
the selected model/runtime rather than importing another project's hooks blindly.

A fresh project receives usable minimum instructions in AGENTS.md. Project-specific
rules are optional additions; no blank questionnaire, setup session or READY marker
blocks investigation, implementation or configured worker delegation. The coordinator
discovers relevant commands from source/scripts/CI and asks only when a specific
consequential action needs a decision or access the task/repository cannot establish.
Existing project-owned instructions and substantive restrictions are preserved.
Credentials, private runtime data and unrelated archives are excluded by default.
Publication and other consequential operations still require task authorization.
One active execution coordinator owns a task; do not run competing worker loops.

Desktop's normal `build` primary entry loads the Arbiter policy through a native
file reference to `.opencode/agents/Arbiter.md`; model, steps and bounded delegation
defaults match the explicit Arbiter agent. No @mention, extra command or primary-agent
picker is required. Legacy scaffold status markers are not authorization or runtime
gates. Verify effective routing when there is a concrete mismatch rather than
repeating broad startup inventories. The optional launcher checks repository config
compatibility; it does not prove machine-global/session settings or endpoint locality.

## Optional launcher and evidence

Use `python3.12 .opencode/run-local.py Arbiter --task <repo-local-handoff>` to
preview a launch; --doctor inspects native agent discovery without inference.
Execution additionally requires --execute --routing-reviewed. Confirm the actual
provider endpoints and merged config/plugins first: a provider ID does not prove
a local endpoint. Do not start inference during a conflicting GPU workload.

The launcher dispatches Arbiter only, supports resuming a known healthy Arbiter
session in the same checkout, retains process exits/raw logs and holds a checkout
lock. Inspect a stale lock's PID/native session before removing it. Fresh Overlord and Sentry
sessions remain Arbiter's responsibility. There is no --auto, resident Codex
supervisor, hard runtime timeout or machine-validated verdict receipt. Exit0 is
not QA acceptance; source identity, executed gates and test counts/skips matter.
Permissions are not OS containment, especially with shell access.

## Maintenance and deployment

For this scaffold repository, use one focused branch, a coherent commit and a PR
to main. Run the generator/update tests, native config discovery and hook tests;
obtain fresh independent review of the final commit and satisfy the hosted gates.
After explicit merge authorization, squash-merge remotely, fast-forward local main,
smoke-test disposable project generation/update, then delete only the completed
branch and publish the accepted version tag. No project migration is implied.
The shared SCM policy is in `files/.opencode/WORKFLOW.md`; project-specific
exceptions remain in each project's AGENTS.md. Keep the live template checkout
on main between tasks: `newoc` reads its working files, including uncommitted edits.

This Git repository at `~/Development/opencode-scaffold` is the editable source
of truth. The local `newoc` shell entry loads `newoc.zsh` directly from this repo;
the helper resolves its templates beside its defining file. `NEWOC_TEMPLATE_DIR`
remains an explicit override. Shared templates live in `files/`; generated
project contracts remain project-owned. No existing project is updated by moving
or editing this repository. Validate changes before generating or updating projects:

```sh
python3.12 -m unittest -v test_newoc.py
NEWOC_NATIVE_TESTS=1 python3.12 -m unittest -v test_newoc.ScaffoldTests.test_native_layers_preserve_models_steps_permissions_and_plugins
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

### Plug-and-play ownership (4.0.0)

New repositories receive AGENTS.md with usable default engineering instructions.
Existing AGENTS.md files are preserved verbatim by both `--here` and updates. The
shared workflow is loaded through native config, so project contracts do not need
copied role descriptions. PROJECT.md is optional additional project context.

OpenCode 2.2.7 loads root `opencode.json` before `.opencode/opencode.json`. The root
file contains scaffold defaults, including role models, steps and permissions.
Markdown agents contain role descriptions/modes and prompts, without steps or
permissions that would shadow project JSON overrides. No launcher or environment
variable is required for these native config layers to work.

Example project-owned `.opencode/opencode.json`:

```json
{
  "agents": {
    "SCV": {"model": "lmstudio/project-worker", "steps": 24},
    "compaction": {"model": "openai/gpt-6.1-sol"},
    "Arbiter": {
      "permissions": [{"action": "shell", "resource": "git push*", "effect": "deny"}]
    },
    "build": {
      "permissions": [{"action": "shell", "resource": "git push*", "effect": "deny"}]
    }
  },
  "instructions": ["docs/engineering-rules.md"],
  "plugins": ["./plugins/project-hook"]
}
```

Relative plugin paths in this override file are relative to `.opencode/`. Additional
instruction paths are repository-relative. Keep provider endpoints/auth machine-local.
Cloud helper routes need project authorization; configuration is not authorization.
Only configure a plugin that actually exists. These examples do not install plugins
or register models. Native discovery remains necessary after changing overrides.

The two coordinator entry points share one prompt file. Their native JSON default
permissions/models are kept aligned by regression checks. Mirror any project
coordinator permission overrides under both `agents.Arbiter` and `agents.build`;
updates/dispatch stop on asymmetric rules rather than silently changing access.
This may require a reviewed edit to an existing project's overrides before update;
the updater never rewrites those overrides. Other subagents retain their existing
local routes and delegation denials.

Role permissions are evaluated after global permissions: place stricter role rules
in `agents.<role>.permissions`. The updater refuses recognized shadowed global denies,
blocked required delegation, disabled core roles, weakened Sentry permissions and
conflicting pinned cloud routes before writing. This is a focused compatibility
check, not a complete OpenCode schema validator or proof of arbitrary glob-policy
containment. Use native discovery to verify the effective result. Supported overrides
are JSON; JSONC alongside these files is refused rather than silently misinterpreted.

On a compatible installed 4.x layout, updates add new role definitions, routing and
workflow together. They preserve AGENTS.md, project overrides, extra hooks and dirty
application work. A manifest layout marker prevents treating legacy ownership as
this layout. Cross-major changes, managed-file edits/collisions and incompatible
overrides stop before writes. Project-owned exclusions cannot hide shared config,
workflow or agent definitions; move intentional settings into project overrides.

Existing 1.x–3.x projects need a one-time reviewed migration: retain project rules,
merge intentional config/role customizations into overrides, establish managed
shared files, then record the new baseline. `--here` is not an adoption/force option.
No existing project is migrated merely by changing this template repository.

`--update` always reads this local template checkout (or NEWOC_TEMPLATE_DIR). It
does not fetch remote policy, reload running OpenCode sessions, start inference,
commit or publish. Deliberately pull/check out a reviewed source release first.

Rollback the installed starter by deploying a reviewed previous source/backup;
existing projects remain unchanged. Roll back project changes through their own
reviewed history. There is no automatic fleet sync or bulk migration.

## Compatibility and limits

Native config layering/discovery is validated with installed OpenCode v2.2.7. Recheck its V2
agents/permissions, Markdown roles and CLI syntax on upgrades. Reference docs:
https://opencode.ai/v2/docs/agents and https://opencode.ai/v2/docs/config.
Tests use isolated repositories/fake workers and the actual newpy function
without sourcing unrelated startup. Native discovery is configuration evidence,
not sustained live Sol-to-local orchestration acceptance. Run a deliberate small
smoke task when inference is authorized and GPU capacity is available.

## Publication permission policy (3.0.1)

Shared configuration denies Git pushes for workers and helpers. Only the coordinator (Arbiter or its Desktop build entry) can request native approval for an ordinary push, after explicit task authorization. Force/mirror pushes and remote-ref deletion remain denied. This does not authorize publication or waive the project's PR, CI and human-acceptance gates. Shell permission patterns are best-effort checks, not OS containment. Existing projects require an explicit reviewed update.


## Sentry code review (3.1.0)

Overlord retains independent local source assessment and executed QA. Sentry is a
fresh, read-only `openai/gpt-6.1-sol` subagent for final code review, with shell,
edits, nested execution and delegation denied. Arbiter supplies a bounded diff,
relevant paths, original acceptance, revision identities and QA evidence. Sentry
returns concrete findings and PASS/FAIL/BLOCKED; it never repairs or publishes.
Arbiter routes repairs to SCV/probe and obtains fresh QA/review after changes.
Project cloud-source authorization applies to Sentry too. No extra coordinator or
continuous Codex supervision is introduced.

Example instruction to Arbiter:

> Commit the scoped changes, push the branch, create a PR, and have Sentry review
> its exact head commit. Address supported findings through the builders, obtain
> Overlord QA and fresh Sentry review after fixes, and record the review using the
> project's existing gate. Leave the PR open for my acceptance; do not merge.

Publication still requires task authorization/native approval and project gates.
A receipt is valid only for its reviewed PR head. A pre-commit review must match
the committed tree or be repeated. Sentry PASS is not human approval or permission
to merge. In the 4.x layout, compatible scaffold updates install role definitions and native
routing together; project-owned AGENTS.md/README.md do not need role-description
merges. Earlier layouts still require a reviewed ownership migration.
