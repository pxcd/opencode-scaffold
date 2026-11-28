import assert from 'node:assert/strict';
import { test } from 'node:test';
import boundary from './index.js';

const packet = 'Stan review packet v1\nbase abc, head def\nApproved source diff';
const fixture = (agent, content) => ({
  agent,
  system: [{ type: 'text', text: 'Ambient repository instructions' }],
  messages: [
    { role: 'user', content: 'Private conversation' },
    { role: 'assistant', content: 'Earlier response' },
    { role: 'user', content, metadata: { private: 'Context metadata' } },
  ],
  tools: { read: {}, grep: {}, subagent: {} },
});

test('native Stan context gets the explicit packet and no ambient content or tools', async () => {
  let contextHook;
  await boundary.setup({ session: { hook(name, hook) {
    assert.equal(name, 'context');
    contextHook = hook;
  } } });
  const request = fixture('Stan', [{
    type: 'text', text: 'You are a subagent spawned by another session.\n' + packet,
  }]);
  contextHook(request);
  assert.deepEqual(request.messages, [
    { role: 'user', content: [{ type: 'text', text: packet }] },
  ]);
  assert.equal(request.system.length, 1);
  assert.match(request.system[0].text, /Review only the supplied/);
  assert.deepEqual(request.tools, {});
});

test('malformed or mixed prompts are dropped without echoing them', async () => {
  for (const content of [
    'Unscoped material', 'Stan review packet v1\n  ', 'Unscoped preamble\n' + packet,
    [{ type: 'text', text: packet }, { type: 'text', text: 'Extra context' }],
    [{ type: 'text', text: 42 }],
  ]) {
    const request = fixture('Stan', content);
    boundaryContext(request);
    assert.deepEqual(request.messages, [{
      role: 'user', content: [{ type: 'text', text: 'No valid review packet was supplied. Return BLOCKED.' }],
    }]);
  }
});

test('other agents keep their context and tools', () => {
  for (const role of ['Cartman', 'Butters', 'Kyle', 'Chef']) {
    const request = fixture(role, packet);
    boundaryContext(request);
    assert.deepEqual(request, fixture(role, packet));
  }
});

let boundaryContext;
await boundary.setup({ session: { hook(_name, hook) { boundaryContext = hook; } } });
