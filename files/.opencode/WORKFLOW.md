# OpenCode Arbiter owns orchestration; Codex intervention is optional

Read root AGENTS.md and `.opencode/PROJECT.md` for the actual project contract,
commands, invariants, access policy, delivery and acceptance. User instructions
remain authoritative. Keep handoffs and evidence scoped to the current task.

## Two levels, one active execution coordinator

GPT-6.1 Sol runs as the native OpenCode Arbiter. It owns planning, routing,
checkpoints, recovery, integration and independent verification. SCV implements
behavior; probe implements presentation; fresh Overlord independently verifies.
Workers use local inference and cannot delegate further. Arbiter can launch only
these three native subagents. Keep local inference sequential by default.

Codex sits above Arbiter for optional task definition, architecture advice,
concrete escalation and final evidence review. Arbiter must be able to execute
an authorized task end-to-end without Codex polling, routine checkpoint approval
or repeated intervention. Do not run two competing coordinator loops or have
Codex dispatch duplicate workers alongside Arbiter. Direct OpenCode use is fully
supported; the launcher is only an optional handoff/diagnostic entry point.

By default only Arbiter is routed to cloud GPT-6.1 Sol. Workers must remain local;
maintenance helpers remain local unless the project contract explicitly authorizes
other helper routes. Check model/provider registrations, effective configuration
and project plugins before inference; a provider ID alone does not prove a local
endpoint. Do not install software, reconfigure providers or start competing GPU
workloads without authorization. Configuration discovery does not run inference.

## Native task loop

1. Confirm absolute checkout, dirty state, issue ownership and any active session.
   Preserve existing work and never duplicate a possibly completed operation.
   Record original scope, acceptance, allowed paths and invariants in
   `.opencode/evidence/<task>/task.md`; avoid copying the whole chat/history.
2. Inspect relevant source/tests and give a bounded milestone with known facts,
   references, constraints, evidence directory and one meaningful first check.
   Route state ownership, async work, persistence, networking and security to SCV;
   route presentation to probe. A view filename does not imply presentation-only.
   For mixed work, establish the interface with SCV before presentation changes.
3. One implementation writer per checkout. Concurrent writes require isolated
   worktrees and explicit integration ownership; worktrees do not isolate models.
   Verify native session directories rather than trusting prompts to change cwd.
4. At a worker checkpoint, inspect the actual diff and executed check output.
   Resume a healthy native child session only for related bounded work. Repeated
   no-progress attempts require a changed hypothesis or assignment, not blind
   renewal. Provider/transport failures require infrastructure diagnosis, not
   speculative application edits. Keep useful progress and recover autonomously
   while productive; do not return routine recovery decisions to Codex.
5. Freeze implementation and dispatch NEW Overlord with original acceptance,
   invariants, paths/diff and required checks, without builder verdicts. QA reads
   enough source/fixtures to assess correctness and executes its own gates.
   Record before/after identities including relevant untracked files. QA never
   repairs. Supported FAIL returns to the responsible builder, followed by NEW
   independent QA of the repaired source. Never waive acceptance to obtain PASS.
6. Distinguish independent QA, hosted CI, human GUI acceptance and publication.
   Stop at the project's agreed boundary. App launches, installs, destructive Git,
   commits/pushes, deployments and external messages need task authorization.
   Escalate genuine permissions, unresolved concrete blockers or user decisions.
   Codex can assist when requested; its availability is not an execution gate.

## Boundaries and evidence

Native step limits are checkpoint backstops, not lifetime quotas. When Arbiter's
own cap fires, preserve session IDs, completed milestones, source/check state and
next action; incomplete execution is not automatically BLOCKED or PASS. Do not
claim a model will stop merely because a prompt says STOP.

Builders return VERIFIED_MILESTONE, CHECKPOINT or BLOCKED. QA returns PASS, FAIL
or BLOCKED with commands, underlying exits, test counts/skips, raw log paths,
source identity and concrete findings. Successful agent process exit or prose
alone is not acceptance. Compilation does not establish runtime or visual QA.
Avoid repeated successful checks on unchanged source without a specific concern.
Keep raw logs outside the model context and inspect bounded relevant excerpts.

For POSIX checks retain the underlying status, for example:

```sh
if <check> > <evidence-log> 2>&1; then check_rc=0; else check_rc=$?; fi
printf 'CHECK_EXIT=%s\n' "$check_rc"
exit "$check_rc"
```

Permissions are not OS containment. Unrestricted shell can read/write files even
when dedicated tools are denied; inspect commands and preserve source identities.
No hard runtime timeout or machine-validated verdict receipt is claimed by the
optional launcher. Project CI remains a deterministic check entry point.
