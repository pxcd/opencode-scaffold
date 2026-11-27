# Native continuation guard

Before delegating authorized work, use `continuation_checkpoint` to register the
full task and its milestones (including required QA/review and later batch groups).
Give the next executable action. Ordinary conversation needs no checkpoint.
The tool does not grant permission to run a task or create a goal by itself.

After actual milestones finish, record their evidence and the next action. Reopen
milestones when source changes invalidate their results. Keep unfinished plans
when new input arrives and reconcile their pending scope. A worker's checkpoint is not
a batch completion; dispatch the next permitted step instead of merely saying it
is ready. Complete only when every registered milestone has current evidence.
Evidence strings are coordinator claims, not machine verification of QA quality.

The native `experimental.idle` hook queues unfinished work with `resume: false`
for the CURRENT execution, rather than starting another execution. Cancellation
and new-input epochs fence pending admissions before the session lock.
It feeds unfinished work back to the SAME primary
coordinator. It does not poll, add a cloud arbiter, execute shell commands, broaden
permissions, or repeat a consequential action on its own. Parent-owned background
jobs wake the parent normally; abandoned descendant work is reported as blocked.
The guard persists bounded state in native plugin storage, scoped to session/root.
After a separately authorized native checkout move, use `rebind` to retain the
existing plan and budgets in the new root; if storage is location-scoped, register
the still-pending scope there. If the plan is paused, it stays paused after
rebinding. Rebinding grants no directory access or move authority.

A real blocker must name its cause and next action. New user input suspends
continuation until the coordinator explicitly reconciles it: resume only if work
remains authorized, pause when asked, and never reinterpret stop as permission to
continue. A status question does not cancel the task: answer it and resume the
preserved plan when the existing authorization still applies. Native
interruption/failure suspends the checkpoint. There is no restart
from failure, permission prompts, server restart, or an explicit user stop.

Automatic recovery is bounded to twelve nudges per activation, three consecutive
nudges without milestone progress, and a 24-hour window. Exhaustion reports an
incomplete checkpoint, not success; rearming needs fresh user input. These are
backstops, not instructions to keep trying an unchanged failure or ignore stricter
user budgets. Native hooks cannot guarantee acceptance or prevent a coordinator
from falsely reporting evidence. This is continuation enforcement, not a QA judge.

Implementation uses the experimental native idle hook validated against the
OpenCode plugin SDK. A missing hook fails plugin setup visibly; do not silently
fall back to unbounded polling. Deploy only through an explicitly approved source
release/update. Do not patch already deployed scaffold copies to enable it.
