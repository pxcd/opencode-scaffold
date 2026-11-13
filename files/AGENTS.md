# {{PROJECT_NAME}} engineering instructions

Work on the user's task immediately within its authorized scope. These defaults
are usable as installed; project-specific instructions may be added later.
Follow `.opencode/WORKFLOW.md` for coordinator routing, delegation and independent
QA/review. This file is project-owned and scaffold updates never replace it.

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
