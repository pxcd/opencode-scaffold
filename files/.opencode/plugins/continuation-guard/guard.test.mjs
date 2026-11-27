import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { install } from './index.js';

const root = fileURLToPath(new URL('.', import.meta.url)).replace(/\/$/, '');
async function fixture(t, existing = new Map(), directory = root) {
  const hooks = new Map(), tools = new Map(), notices = [];
  let heldWrite;
  let clock = 1000, session = { agent: 'Cartman', location: { directory } };
  const queue = []; let wake, ended = false;
  const context = {
    location: { directory },
    storage: { get: async k => existing.has(k) ? structuredClone(existing.get(k)) : undefined,
      set: async (k, v) => {
        if (heldWrite) { const held = heldWrite; heldWrite = undefined; held.enter(); await held.wait; }
        existing.set(k, structuredClone(v));
      } },
    session: { get: async () => session,
      synthetic: async n => { notices.push(n); },
      hook: async (name, callback) => { hooks.set(name, callback); return { dispose: async () => hooks.delete(name) }; } },
    tool: { transform: async fn => { fn({ add: tool => tools.set(tool.name, tool) }); return { dispose: async () => {} }; },
      hook: async (name, callback) => { hooks.set(name, callback); return { dispose: async () => {} }; } },
    event: { subscribe: async function* ({ signal }) {
      signal.addEventListener('abort', () => { ended = true; wake?.(); }, { once: true });
      while (!ended) {
        if (!queue.length) await new Promise(resolve => { wake = resolve; });
        while (queue.length) yield queue.shift();
      }
    } },
  };
  const dispose = await install(context, () => clock);
  t.after(dispose);
  const call = (input, agent = 'Cartman') => tools.get('continuation_checkpoint').execute(input, { sessionID: 's1', agent });
  return { call, notices, existing, context,
    state: () => existing.get('continuation:s1'),
    holdNextWrite: () => {
      let enter, release; const entered = new Promise(r => { enter = r; });
      const wait = new Promise(r => { release = r; }); heldWrite = { enter, wait };
      return { entered, release };
    },
    start: () => call({ action: 'start', goal: 'Finish authorized change',
      milestones: [{ id: 'repair', title: 'Repair' }, { id: 'qa', title: 'Fresh QA' }], next_action: 'Repair, then execute fresh QA' }),
    idle: background => hooks.get('experimental.idle')({ sessionID: 's1', background: background ?? [] }),
    prompt: () => hooks.get('prompt')({ sessionID: 's1' }),
    delegate: () => hooks.get('execute.before')({ sessionID: 's1', agent: 'Cartman', tool: 'subagent' }),
    setSession: s => { session = s; }, setClock: n => { clock = n; },
    event: async type => { queue.push({ type, data: { sessionID: 's1' } }); wake?.(); await new Promise(r => setImmediate(r)); },
  };
}

test('ordinary conversation is unarmed; delegation requires the full task plan', async t => {
  const f = await fixture(t); await f.idle(); assert.equal(f.notices.length, 0);
  await assert.rejects(f.delegate(), /register/); await f.start(); await f.delegate();
});
test('repair ready for QA cannot quietly finish: injects continuation in same session', async t => {
  const f = await fixture(t); await f.start();
  await f.call({ action: 'progress', completed: ['repair'], evidence: 'Focused test exit0', next_action: 'Dispatch fresh QA' });
  await assert.rejects(f.call({ action: 'complete', evidence: 'Ready for QA' }), /Pending/);
  await f.idle(); assert.equal(f.notices.length, 1); assert.equal(f.notices[0].sessionID, 's1');
  assert.equal(f.notices[0].resume, false); assert.match(f.notices[0].text, /qa: Fresh QA/);
});
test('native background worker wakes parent; do not dispatch or spend recovery budget', async t => {
  const f = await fixture(t); await f.start();
  await f.idle([{ kind: 'subagent', sessionID: 's1', childSessionID: 'child' }]);
  assert.equal(f.notices.length, 0); assert.equal(f.state().resumes, 0);
  await f.idle(); assert.equal(f.notices.length, 1);
});
test('orphaned descendant work is an explicit blocker, not a silent idle', async t => {
  const f = await fixture(t); await f.start();
  await f.idle([{ kind: 'shell', sessionID: 'child', shellID: 'sh' }]);
  assert.equal(f.state().phase, 'blocked'); assert.match(f.notices[0].text, /descendant/);
  await f.idle(); assert.equal(f.notices.length, 1);
});
test('complete needs every milestone and evidence; then no wake', async t => {
  const f = await fixture(t); await f.start();
  await assert.rejects(f.call({ action: 'progress', completed: ['qa'], next_action: 'finish' }), /evidence/);
  await f.call({ action: 'progress', completed: ['repair', 'qa'], evidence: 'Actual final gates exit0', next_action: 'Report delivery' });
  await f.call({ action: 'complete', evidence: 'All authorized work verified' });
  await f.idle(); assert.equal(f.notices.length, 0);
});
test('reopened verification invalidates completion', async t => {
  const f = await fixture(t); await f.start();
  await f.call({ action: 'progress', completed: ['repair', 'qa'], evidence: 'exit0', next_action: 'Review' });
  await f.call({ action: 'progress', reopen: ['qa'], next_action: 'Recheck changed source' });
  await assert.rejects(f.call({ action: 'complete', evidence: 'old pass' }), /Pending/);
});
test('concrete blockers do not auto-retry or silently grant permission', async t => {
  const f = await fixture(t); await f.start();
  await assert.rejects(f.call({ action: 'block', reason: 'Ready for QA', next_action: 'Run it' }), /category/);
  await f.call({ action: 'block', blocker: 'permission', reason: 'Required access denied', next_action: 'Ask for exact access' });
  await f.idle(); assert.equal(f.notices.length, 0);
  await assert.rejects(f.delegate(), /register/);
  await assert.rejects(f.call({ action: 'resume', next_action: 'bypass' }), /fresh user/);
});
test('new user input suspends auto-continuation until explicit reconciliation', async t => {
  const f = await fixture(t); await f.start(); await f.prompt();
  await f.idle(); assert.equal(f.notices.length, 0); assert.equal(f.state().phase, 'paused');
  await f.call({ action: 'pause', reason: 'User requested stop' }); await f.idle(); assert.equal(f.notices.length, 0);
  await assert.rejects(f.call({ action: 'resume', next_action: 'Restart without another user instruction' }), /fresh user/);
});
test('a new user continuation can resume the preserved plan', async t => {
  const f = await fixture(t); await f.start(); await f.prompt();
  await f.call({ action: 'resume', next_action: 'Continue approved QA' }); await f.idle();
  assert.equal(f.notices.length, 1); assert.equal(f.state().milestones.length, 2);
});
for (const type of ['session.execution.interrupted', 'session.execution.failed'])
  test(type + ' never restarts on a later idle notice', async t => {
    const f = await fixture(t); await f.start(); await f.event(type); await f.idle();
    assert.equal(f.state().phase, 'paused'); assert.equal(f.notices.length, 0);
    await assert.rejects(f.call({ action: 'resume', next_action: 'retry' }), /fresh user/);
  });
for (const type of ['session.execution.interrupted', 'session.execution.failed']) {
  test(type + ' supersedes a prompt still resolving session scope', async t => {
    const f = await fixture(t); await f.start();
    const getSession = f.context.session.get;
    let release;
    const held = new Promise(resolve => { release = resolve; });
    f.context.session.get = async () => { await held; return getSession(); };
    const pending = f.prompt();
    await f.event(type);
    release(); await pending;
    assert.equal(f.state().freshInput, false);
    await assert.rejects(f.call({ action: 'resume', next_action: 'Stale retry' }), /fresh user/);
    await f.prompt();
    await f.call({ action: 'resume', next_action: 'New user request' });
    await f.delegate();
  });
  test(type + ' clears fresh input even if the prompt write is already in flight', async t => {
    const f = await fixture(t); await f.start(); const held = f.holdNextWrite();
    const pending = f.prompt(); await held.entered;
    await f.event(type); held.release(); await pending;
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.state().phase, 'paused');
    assert.equal(f.state().freshInput, false);
    await assert.rejects(f.delegate(), /register\/resume/);
    await assert.rejects(f.call({ action: 'resume', next_action: 'Stale retry' }), /fresh user/);
  });
}
test('stall guard reports incomplete once and cannot be self-rearmed', async t => {
  const f = await fixture(t); await f.start();
  for (let i = 0; i < 5; i++) await f.idle();
  assert.equal(f.state().phase, 'blocked'); assert.equal(f.notices.length, 4);
  assert.match(f.notices.at(-1).text, /No milestone progress/);
  await assert.rejects(f.start(), /fresh user/);
});
test('changing next-action prose does not count as milestone progress', async t => {
  const f = await fixture(t); await f.start();
  for (let i = 0; i < 5; i++) {
    if (f.state().phase !== 'active') break;
    await f.call({ action: 'progress', next_action: 'Same work, wording ' + i }); await f.idle();
  }
  assert.equal(f.state().phase, 'blocked');
});
test('total automatic recovery budget is not reset by genuine progress', async t => {
  const f = await fixture(t); await f.start();
  for (let i = 0; i < 13; i++) {
    if (i) await f.call({ action: 'progress', ...(i % 2 ? { completed: ['repair'], evidence: 'Current receipt' } : { reopen: ['repair'] }), next_action: 'Continue actual work' });
    await f.idle();
  }
  assert.equal(f.state().resumes, 12); assert.equal(f.state().phase, 'blocked');
  assert.match(f.notices.at(-1).text, /limit reached/);
});
test('expired task window does not keep spending tokens', async t => {
  const f = await fixture(t); await f.start(); f.setClock(1000 + 24 * 3600 * 1000); await f.idle();
  assert.equal(f.state().phase, 'blocked'); assert.match(f.notices[0].text, /expired/);
});
test('state persists across plugin reload without an external supervisor', async t => {
  const state = new Map(); const first = await fixture(t, state); await first.start();
  const second = await fixture(t, state); await second.idle(); assert.equal(second.notices.length, 1);
});
test('children and other checkouts cannot mutate a parent plan', async t => {
  const f = await fixture(t); await f.start();
  await assert.rejects(f.call({ action: 'complete', evidence: 'claim' }, 'Butters'), /primary/);
  f.setSession({ agent: 'Cartman', parentID: 'parent', location: { directory: root } }); await f.idle();
  await assert.rejects(f.call({ action: 'status' }), /primary/);
  f.setSession({ agent: 'Cartman', location: { directory: root + '/..' } }); await f.idle();
  assert.equal(f.notices.length, 0);
});
test('malformed plans cannot arm a loop or erase pending scope', async t => {
  const f = await fixture(t);
  await assert.rejects(f.call({ action: 'start', goal: 'x', milestones: [], next_action: 'x' }), /1–32/);
  await f.start(); await assert.rejects(f.start(), /Preserve/);
  await assert.rejects(f.call({ action: 'progress', completed: ['unknown'], evidence: 'x', next_action: 'x' }), /Unknown/);
});

test('authorized native checkout move can retain the full plan without resetting budgets', async t => {
  const shared = new Map(); const first = await fixture(t, shared); await first.start(); await first.idle();
  const second = await fixture(t, shared, root + '/..');
  await assert.rejects(second.delegate(), /register/);
  await second.call({ action: 'status' });
  await second.call({ action: 'rebind', reason: 'User-authorized native move already performed', next_action: 'Continue remaining QA' });
  assert.equal(second.state().milestones.length, 2); assert.equal(second.state().resumes, 1);
  await second.delegate(); await second.idle(); assert.equal(second.notices.length, 1);
  await first.idle(); assert.equal(first.notices.length, 1); // Old-root hook cannot resume it.
});

for (const type of ['session.execution.interrupted', 'session.execution.failed'])
  test(type + ' during idle storage write cannot enqueue stale continuation', async t => {
    const f = await fixture(t); await f.start(); const held = f.holdNextWrite();
    const pending = f.idle(); await held.entered;
    await f.event(type); held.release(); await pending;
    await new Promise(r => setImmediate(r));
    assert.equal(f.notices.length, 0); assert.equal(f.state().phase, 'paused');
  });
test('new user input during idle storage write fences the stale task', async t => {
  const f = await fixture(t); await f.start(); const held = f.holdNextWrite();
  const pending = f.idle(); await held.entered;
  const input = f.prompt(); await new Promise(r => setImmediate(r));
  held.release(); await pending; await input;
  assert.equal(f.notices.length, 0); assert.equal(f.state().phase, 'paused');
});

test('interruption during asynchronous admission cannot request a new execution', async t => {
  const f = await fixture(t); await f.start();
  f.context.session.synthetic = async notice => {
    await f.event('session.execution.interrupted'); f.notices.push(notice);
  };
  await f.idle(); await new Promise(r => setImmediate(r));
  assert.equal(f.notices.length, 1);
  assert.equal(f.notices[0].resume, false); // The server may queue it, never restart after stop.
  assert.equal(f.state().phase, 'paused');
});
