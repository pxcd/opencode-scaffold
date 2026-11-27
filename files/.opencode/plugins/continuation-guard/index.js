import { realpath } from 'node:fs/promises';

const PRIMARY = new Set(['Cartman', 'build']);
const MAX_RESUMES = 12;
const MAX_STALLS = 3;
const MAX_AGE = 24 * 60 * 60 * 1000;
const key = id => `continuation:${id}`;
const text = (value, name, limit = 2000) => {
  if (typeof value !== 'string' || !value.trim() || value.length > limit)
    throw new Error(`${name} must be nonempty and at most ${limit} characters`);
  return value.trim();
};

export const checkpointSchema = {
  type: 'object', additionalProperties: false, required: ['action'],
  properties: {
    action: { enum: ['start', 'progress', 'complete', 'block', 'pause', 'resume', 'rebind', 'status'] },
    goal: { type: 'string', maxLength: 1000 },
    milestones: { type: 'array', minItems: 1, maxItems: 32, items: {
      type: 'object', additionalProperties: false, required: ['id', 'title'],
      properties: { id: { type: 'string', maxLength: 64 }, title: { type: 'string', maxLength: 256 } },
    } },
    completed: { type: 'array', maxItems: 32, items: { type: 'string' } },
    reopen: { type: 'array', maxItems: 32, items: { type: 'string' } },
    evidence: { type: 'string', maxLength: 2000 },
    next_action: { type: 'string', maxLength: 2000 },
    reason: { type: 'string', maxLength: 2000 },
    blocker: { enum: ['permission', 'external_dependency', 'verification', 'human_acceptance', 'scope_decision'] },
  },
};

// The state is progress bookkeeping, not proof that QA or user authorization exists.
export async function install(ctx, now = Date.now) {
  const root = await realpath(ctx.location.directory);
  const locks = new Map();
  const registrations = [];
  const epochs = new Map();
  const suspended = new Set();
  const epoch = id => epochs.get(id) ?? 0;
  const suspend = id => { epochs.set(id, epoch(id) + 1); suspended.add(id); return epoch(id); };
  const clear = (id, version) => { if (epoch(id) === version) suspended.delete(id); };
  const abort = new AbortController();
  let monitoring = true;
  const serial = (id, work) => {
    const previous = locks.get(id) ?? Promise.resolve();
    const pending = previous.catch(() => {}).then(work);
    locks.set(id, pending);
    pending.finally(() => { if (locks.get(id) === pending) locks.delete(id); }).catch(() => {});
    return pending;
  };
  const get = async id => {
    const state = await ctx.storage.get(key(id));
    if (state !== undefined && (state.version !== 1 || !Array.isArray(state.milestones)
        || state.milestones.length > 32 || typeof state.phase !== 'string'))
      throw new Error('Invalid continuation checkpoint; no automatic continuation');
    return state === undefined ? undefined : structuredClone(state);
  };
  const put = (id, state) => ctx.storage.set(key(id), state);
  const primary = async id => {
    const session = await ctx.session.get({ sessionID: id });
    return !session.parentID && PRIMARY.has(session.agent)
      && await realpath(session.location.directory) === root;
  };
  const notice = (id, message, version) => {
    if (abort.signal.aborted || suspended.has(id) || epoch(id) !== version) return;
    // Idle-hook input is consumed by the CURRENT execution. Never independently
    // restart a session if interruption races the asynchronous admission call.
    return ctx.session.synthetic({ sessionID: id, text: message,
      description: 'Scaffold continuation guard', metadata: { source: 'scaffold.continuation-guard' }, resume: false });
  };

  async function checkpoint(input, context) {
    const id = context.sessionID;
    const version = epoch(id);
    if (!PRIMARY.has(context.agent) || !await primary(id))
      throw new Error('Continuation checkpoints belong to the primary coordinator in this checkout');
    return serial(id, async () => {
      const old = await get(id);
      if (epoch(id) !== version) throw new Error('New input or interruption superseded this checkpoint action');
      const state = old && structuredClone(old);
      if (input.action === 'status') return { content: JSON.stringify(state ?? { phase: 'unarmed' }) };
      if (input.action === 'start') {
        if (old?.phase === 'cancelled' && !old.freshInput)
          throw new Error('A cancelled plan needs a new user request before starting other work');
        if (old && !['complete', 'cancelled'].includes(old.phase))
          throw new Error('Preserve the existing plan; reconcile or rebind unfinished work before continuing');
        const goal = text(input.goal, 'goal', 1000);
        if (!Array.isArray(input.milestones) || !input.milestones.length || input.milestones.length > 32)
          throw new Error('Register 1–32 milestones covering the full authorized task');
        const milestones = input.milestones.map(m => ({ id: text(m.id, 'milestone id', 64),
          title: text(m.title, 'milestone title', 256), done: false, evidence: '' }));
        if (new Set(milestones.map(m => m.id)).size !== milestones.length) throw new Error('Duplicate milestone id');
        const nextAction = text(input.next_action, 'next_action');
        const fresh = { version: 1, root, goal, milestones, nextAction, phase: 'active',
          revision: 0, lastRevision: -1, resumes: 0, stalls: 0, started: now(), freshInput: false };
        if (old?.phase === 'cancelled') {
          await ctx.storage.set(key(id) + ':last-cancelled', old);
          if (epoch(id) !== version) throw new Error('New input or interruption superseded this checkpoint action');
        }
        await put(id, fresh); clear(id, version); return { content: JSON.stringify(fresh) };
      }
      if (!state) throw new Error('Register the task first');
      if (state.phase === 'cancelled') throw new Error('The cancelled plan cannot resume');
      if (state.root !== root && input.action !== 'rebind')
        throw new Error('Checkpoint belongs to another checkout; rebind only after an authorized native move');
      if (input.action === 'rebind') {
        if (!['active', 'paused'].includes(state.phase) || state.root === root)
          throw new Error('Rebind requires an active or paused task and an actual checkout change');
        state.reason = text(input.reason, 'authorized move reason');
        state.nextAction = text(input.next_action, 'next_action');
        state.root = root; // State transfer only: this tool never moves a session or grants access.
      } else if (input.action === 'resume') {
        if (!state.freshInput) throw new Error('A paused or blocked task needs fresh user input before resuming');
        state.phase = 'active'; state.freshInput = false;
        state.nextAction = text(input.next_action, 'next_action');
        state.started = now(); state.resumes = 0; state.stalls = 0;
      } else if (input.action === 'pause') {
        if (!state.freshInput) throw new Error('Only a new user instruction may pause the task');
        state.phase = 'paused'; state.freshInput = false; state.reason = text(input.reason, 'reason');
      } else {
        if (state.phase !== 'active') throw new Error('Task is not active');
        if (input.action === 'progress') {
          const completed = input.completed ?? [], reopen = input.reopen ?? [];
          if (!Array.isArray(completed) || !Array.isArray(reopen)) throw new Error('Invalid milestone updates');
          const ids = [...completed, ...reopen];
          if (new Set(ids).size !== ids.length || ids.some(x => !state.milestones.some(m => m.id === x)))
            throw new Error('Unknown or conflicting milestone id');
          const evidence = completed.length ? text(input.evidence, 'evidence') : '';
          for (const m of state.milestones) {
            if (completed.includes(m.id) && !m.done) { m.done = true; m.evidence = evidence; state.revision++; }
            if (reopen.includes(m.id) && m.done) { m.done = false; m.evidence = ''; state.revision++; }
          }
          state.nextAction = text(input.next_action, 'next_action');
        } else if (input.action === 'complete') {
          if (state.milestones.some(m => !m.done || !m.evidence))
            throw new Error('Pending/unverified milestones remain; ready for QA is not completion');
          state.phase = 'complete'; state.reason = text(input.evidence, 'evidence');
        } else if (input.action === 'block') {
          if (!checkpointSchema.properties.blocker.enum.includes(input.blocker)) throw new Error('A concrete blocker category is required');
          state.phase = 'blocked'; state.blocker = input.blocker; state.reason = text(input.reason, 'reason');
          state.nextAction = text(input.next_action, 'next_action');
        } else throw new Error('Unknown checkpoint action');
      }
      await put(id, state);
      if (input.action === 'resume' || (input.action === 'rebind' && state.phase === 'active')) clear(id, version);
      return { content: JSON.stringify(state) };
    });
  }

  registrations.push(await ctx.tool.transform(editor => editor.add({
    name: 'continuation_checkpoint', input: checkpointSchema, options: { codemode: false },
    description: 'Register and maintain the full authorized task before delegation. Record milestone evidence; complete only when all milestones are verified. Block only on a concrete unresolved dependency/permission/acceptance need. No permissions are granted by this tool.',
    execute: checkpoint,
  })));
  registrations.push(await ctx.tool.hook('execute.before', async event => {
    if (event.tool !== 'subagent' || !PRIMARY.has(event.agent)) return;
    const version = epoch(event.sessionID);
    if (!await primary(event.sessionID)) return;
    await serial(event.sessionID, async () => {
      const state = await get(event.sessionID);
      if (suspended.has(event.sessionID) || epoch(event.sessionID) !== version
          || !state || state.phase !== 'active' || state.root !== root)
        throw new Error('Use continuation_checkpoint to register/resume the authorized plan before delegation');
    });
  }));
  registrations.push(await ctx.session.hook('prompt', async event => {
    const version = suspend(event.sessionID); // Fence BEFORE awaiting the session lock.
    if (!await primary(event.sessionID)) { clear(event.sessionID, version); return; }
    await serial(event.sessionID, async () => {
      const state = await get(event.sessionID);
      if (epoch(event.sessionID) !== version) return;
      if (!state || state.phase === 'complete') { clear(event.sessionID, version); return; }
      // Recognize only the explicit user prompt. Native interruptions, status
      // questions and worker output do not authorize replacing a plan.
      if (/^cancel this task\.?$/i.test(event.prompt?.text?.trim() ?? '')) {
        state.phase = 'cancelled'; state.freshInput = false;
        state.reason = 'User explicitly cancelled the task';
        await put(event.sessionID, state);
        return;
      }
      if (state.phase === 'cancelled') {
        state.freshInput = true;
        await put(event.sessionID, state);
        return;
      }
      state.phase = 'paused'; state.freshInput = true;
      state.reason = 'New user input: reconcile the latest instruction before resuming';
      await put(event.sessionID, state);
    });
  }));
  registrations.push(await ctx.session.hook('experimental.idle', async event => {
    const version = epoch(event.sessionID);
    if (!await primary(event.sessionID)) return;
    await serial(event.sessionID, async () => {
      const state = await get(event.sessionID);
      if (!state || state.phase !== 'active' || state.root !== root) return;
      // Parent-owned background jobs will wake this session themselves.
      if (event.background.some(job => job.sessionID === event.sessionID)) return;
      let reason;
      if (!monitoring) reason = 'Interruption monitoring is unavailable';
      else if (event.background.length) reason = 'A descendant left background work running; reconcile its ownership';
      else if (now() - state.started >= MAX_AGE) reason = 'Continuation authorization window expired (24 hours)';
      else if (state.resumes >= MAX_RESUMES) reason = 'Automatic continuation limit reached (12); task remains incomplete';
      else {
        state.stalls = state.lastRevision === state.revision ? state.stalls + 1 : 0;
        if (state.stalls >= MAX_STALLS) reason = 'No milestone progress after three continuation attempts';
      }
      if (reason) {
        state.phase = 'blocked'; state.reason = reason; state.freshInput = false;
        await put(event.sessionID, state);
        await notice(event.sessionID, `Continuation guard stopped automatic recovery: ${reason}. Preserve the checkpoint and report the concrete limitation. Do not restart, broaden permissions, or claim completion. Fresh user input is required.`, version);
        return;
      }
      state.resumes++; state.lastRevision = state.revision;
      await put(event.sessionID, state); // Persist before enqueueing; duplicates consume the bounded budget.
      const remaining = state.milestones.filter(m => !m.done).map(m => `${m.id}: ${m.title}`).join('; ');
      await notice(event.sessionID, `The authorized task is still active. Pending milestones: ${remaining || 'record final evidence and complete the checkpoint'}. Next action: ${state.nextAction}. Execute the next permitted action now; describing readiness does not finish it. Respect current scope, permissions, budgets, and user stop instructions. If genuinely blocked, record a concrete blocker using continuation_checkpoint. This notice grants no new authority.`, version);
    });
  }));

  const events = (async () => {
    try {
      for await (const event of ctx.event.subscribe({ types: ['session.execution.interrupted', 'session.execution.failed'], signal: abort.signal })) {
        const id = event.data?.sessionID;
        if (!id) continue;
        const version = suspend(id); // Do not queue cancellation behind the idle hook.
        await serial(id, async () => {
          const state = await get(id);
          if (!state || state.phase === 'complete') { clear(id, version); return; }
          if (state.phase !== 'active' && !state.freshInput) return;
          // Revoke a prompt that already persisted while this event waited for the lock.
          state.freshInput = false;
          if (!['blocked', 'cancelled'].includes(state.phase)) {
            state.phase = 'paused';
            state.reason = 'Native execution interrupted or failed; no automatic restart';
          }
          await put(id, state);
        });
      }
      if (!abort.signal.aborted) monitoring = false;
    } catch { if (!abort.signal.aborted) monitoring = false; }
  })();
  return async () => {
    abort.abort();
    await Promise.all(registrations.map(r => r.dispose()));
    await events;
  };
}

export default { id: 'scaffold.continuation-guard', setup: install };
