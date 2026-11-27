import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeStepLimit, STEP_LIMIT_PROMPT, unsupportedPrefill } from './normalize.mjs';
import plugin from './index.js';

test('only synthetic trailing assistant budget instruction changes role', () => {
  const first={role:'user',content:[{type:'text',text:'task'}]};
  const last={role:'assistant',content:[{type:'text',text:STEP_LIMIT_PROMPT}]};
  const messages=[first,last];
  assert.equal(normalizeStepLimit(messages),true);
  assert.equal(messages[1].role,'user');
  assert.equal(messages[1].content,last.content);
  assert.equal(last.role,'assistant');
  assert.equal(messages[0],first);
});
for (const [name,last] of [
  ['ordinary assistant',{role:'assistant',content:[{type:'text',text:'done'}]}],
  ['user instruction',{role:'user',content:[{type:'text',text:STEP_LIMIT_PROMPT}]}],
  ['tool result',{role:'tool',content:[{type:'text',text:STEP_LIMIT_PROMPT}]}],
  ['unknown revised control',{role:'assistant',content:[{type:'text',text:STEP_LIMIT_PROMPT+' changed'}]}],
  ['mixed content',{role:'assistant',content:[{type:'text',text:STEP_LIMIT_PROMPT},{type:'text',text:'other'}]}],
  ['string content',{role:'assistant',content:STEP_LIMIT_PROMPT}],
]) test('leaves '+name+' unchanged',()=>{ const xs=[last];assert.equal(normalizeStepLimit(xs),false);assert.equal(xs[0],last); });
test('empty/malformed input is ignored',()=>{ for(const x of [null,undefined,{},[]])assert.equal(normalizeStepLimit(x),false); });
test('only deterministic unsupported-prefill failure bypasses retry',()=>{
 assert.equal(unsupportedPrefill({message:'Splash does not support assistant response prefill/continuation.'}),true);
 assert.equal(unsupportedPrefill({message:'network timeout'}),false);
 assert.equal(unsupportedPrefill({message:'rate limited'}),false);
});

test('LM Studio context adds empty properties only to the affected browser tool', async () => {
  let handler;
  await plugin.setup({ session: { hook(name, callback, options) {
    if (name !== 'context') return;
    assert.deepEqual(options, { providerID: 'lmstudio' });
    handler = callback;
  } } });
  const input = Object.freeze({ type: 'object', propertyNames: { type: 'string' } });
  const tools = { browser_tabs_list: { input }, unrelated: { input } };
  handler({ messages: [], tools });
  assert.deepEqual(tools.browser_tabs_list.input, { ...input, properties: {} });
  assert.equal(tools.unrelated.input, input);
  const normalized = tools.browser_tabs_list.input;
  handler({ messages: [], tools });
  assert.equal(tools.browser_tabs_list.input, normalized);
  handler({ messages: [] });
});
