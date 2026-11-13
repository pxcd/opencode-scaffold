# {{PROJECT_NAME}} engineering contract

GPT-6.1 Sol is OpenCode Arbiter and owns native planning, delegation, recovery
and independent QA. SCV implements behavior, probe presentation, and a NEW
Overlord verifies final unchanged source. Local subagents cannot delegate.
Codex may provide an upper-level handoff, advice or final review; its polling,
checkpoint approvals and intervention are not required for task execution.

Read `.opencode/WORKFLOW.md` for shared orchestration and `.opencode/PROJECT.md`
for this project's commands, invariants, access policy and acceptance. Establish
that contract from the actual repository/user requirements before implementation;
do not copy another project's commands, privacy authorization or architecture.

Native role definitions are in `.opencode/agents/`; model-ID defaults are in
`.opencode/opencode.json`. Provider registration, endpoints and credentials stay
machine-local. An optional launcher can apply ignored `local.json` overrides;
opening OpenCode directly does not require Codex or the launcher.
