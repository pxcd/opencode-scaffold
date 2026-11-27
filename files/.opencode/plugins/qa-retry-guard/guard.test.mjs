import assert from 'node:assert/strict';
import test from 'node:test';
import plugin from './index.js';

let context;
await plugin.setup({ location: { directory: '/fixture' }, tool: { hook() {} }, session: { hook(name, callback) {
  if (name === 'context') context = callback;
} } });

const command = 'python3.12 .opencode/verify-scaffold.py';
function check(id, changes = {}, result = { type: 'text', value: 'PASS' }) {
  return [
    { role: 'assistant', content: [
      { type: 'text', text: 'Checking the staged snapshot' },
      { type: 'tool-call', name: 'shell', id, input: { command, description: id, ...changes } },
    ] },
    { role: 'tool', content: [{ type: 'tool-result', name: 'shell', id, result }] },
  ];
}

function prepare(messages, agent = 'Kyle') {
  const tools = { shell: {}, read: {} };
  const request = { agent, tools, messages, system: [{ type: 'text', text: 'Project instructions' }] };
  context(request);
  assert.equal(request.system[0].text, 'Project instructions');
  return request;
}

for (const result of [{ type: 'text', value: 'PASS' },
    { type: 'text', value: 'Exit code: 1' },
    { type: 'error', value: { error: { message: 'Invalid working directory' }, content: [] } }]) {
  test('identical completed calls yield a checkpoint for ' + JSON.stringify(result), () => {
    const messages = [...check('first', {}, result), ...check('second', {}, result)];
    const history = structuredClone(messages);
    const request = prepare(messages);
    assert.deepEqual(request.tools, {});
    assert.match(request.system.at(-1).text, /checkpoint to Cartman/);
    assert.deepEqual(request.messages, history);
  });
}

for (const [label, second] of [
  ['changed command', check('2', { command: 'pytest' })],
  ['changed checkout', check('2', { workdir: 'fixture' })],
  ['changed timeout', check('2', { timeout: 60 })],
  ['changed output', check('2', {}, { type: 'text', value: 'FAIL' })],
  ['different status', check('2', {}, { type: 'error', value: 'PASS' })],
]) {
  test(label + ' allows further diagnosis', () => {
    assert.ok(prepare([...check('1'), ...second]).tools.shell);
  });
}

test('single checks, intervening tools, parallel calls and new handoffs stay eligible', () => {
  const user = { role: 'user', content: [{ type: 'text', text: 'Run the next diagnostic.' }] };
  const read = check('read');
  read[0].content.at(-1).name = read[1].content[0].name = 'read';
  const parallel = check('parallel');
  parallel[0].content.push(...read[0].content);
  const background = { background: true };
  for (const messages of [
    check('once'), [...check('1'), ...read, ...check('2')], [...check('1'), ...parallel],
    [...check('1'), ...check('2'), user], [...check('1'), user, ...check('2')],
    [...check('1', background), ...check('2', background)],
  ]) assert.ok(prepare(messages).tools.shell);
});

test('other agents keep their tools and a malformed call-result pair cannot trigger', () => {
  const messages = [...check('1'), ...check('2')];
  for (const agent of ['Cartman', 'build', 'Butters', 'Stan', 'Chef'])
    assert.ok(prepare(messages, agent).tools.shell);
  messages.at(-1).content[0].id = 'unrelated';
  assert.ok(prepare(messages).tools.shell);
});

// The QA trace narrowed the same numbered staged diff from 20 to 15 to 10
// lines. All three windows still contained the entire nine-line result.
const numberedDiff = `git diff --cached -- src/guard.js | grep -E '^[+-]' | grep -vE '^(\\+\\+\\+|---)' | awk '{print NR": "$0}'`;
const nineLines = Array.from({ length: 9 }, (_, i) => `${i + 1}: +example${i}\n`).join('');
function windowCall(id, end, options = {}) {
  const { producer = numberedDiff, result = { type: 'text', value: nineLines }, ...input } = options;
  return check(id, { command: `${producer} | sed -n '1,${end}p'`, ...input }, result);
}

test('repeated views of the same completed staged diff checkpoint while a second look is allowed', () => {
  const start = [...windowCall('a', 20), ...windowCall('b', 15)];
  assert.ok(prepare(start).tools.shell);
  const messages = [...start, ...windowCall('c', 10)];
  assert.deepEqual(prepare(messages).tools, {});
  assert.match(prepare(messages).system.at(-1).text, /same diff/);
  assert.ok(prepare(messages, 'Butters').tools.shell);
});

test('another range, changed inputs, newly visible output or a new task can continue', () => {
  const start = [...windowCall('a', 20), ...windowCall('b', 15)];
  for (const end of [
    windowCall('c', 10, { command: `${numberedDiff} | sed -n '21,30p'` }),
    windowCall('c', 10, { producer: numberedDiff.replace('src/guard.js', 'src/other.js') }),
    windowCall('c', 10, { workdir: '/other/checkout' }),
    windowCall('c', 10, { result: { type: 'text', value: nineLines + '10: +new line\n' } }),
    [{ role: 'user', content: [{ type: 'text', text: 'Verify this new revision.' }] }, ...windowCall('c', 10)],
  ]) assert.ok(prepare([...start, ...end]).tools.shell);
});

test('reading a truncated result, an error or a different check remains eligible', () => {
  for (const options of [
    { result: { type: 'text', value: 'partial\n\n[showing the last 1 line; full output saved to example]' } },
    { result: { type: 'content', value: [{ type: 'text', text: 'failed' }, { type: 'text', text: 'Exit code: 1' }] } },
    { result: { type: 'error', value: 'Unable to read the diff' } },
    { producer: 'node ./run-tests.js' },
  ]) {
    const messages = [20, 15, 10].flatMap(end => windowCall(String(end), end, options));
    assert.ok(prepare(messages).tools.shell);
  }
});


test('two empty trailing pages stop Kyle while nonempty pages and other diffs may continue', () => {
  const first = 'git diff --cached -- .opencode/plugins/continuation-guard/guard.test.mjs';
  const result = { type: 'text', value: '(no output)' };
  const pages = (source, range, output = result) => check(range, { command: source + " | sed -n '" + range + "p'" }, output);
  const empty = pages(first, '120,160');
  assert.ok(prepare(empty).tools.shell);
  for (const second of [
    pages(first, '160,200', { type: 'text', value: '+new evidence' }),
    pages('git diff --cached -- other', '160,200'),
  ]) assert.ok(prepare([...empty, ...second]).tools.shell);
  const stopped = prepare([...empty, ...pages(first, '160,200')]);
  assert.deepEqual(stopped.tools, {});
  assert.match(stopped.system.at(-1).text, /Stop paging past the end/);
});
