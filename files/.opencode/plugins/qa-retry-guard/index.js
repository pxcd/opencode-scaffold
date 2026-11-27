import { installStagedQA } from './staged-qa.mjs';
import { isDeepStrictEqual } from 'node:util';

function shellObservation(assistant, tool) {
  if (assistant?.role !== 'assistant' || !Array.isArray(assistant.content)
      || tool?.role !== 'tool' || !Array.isArray(tool.content) || tool.content.length !== 1) return;
  const calls = assistant.content.filter(part => part.type === 'tool-call');
  const [call] = calls;
  const [reply] = tool.content;
  if (calls.length !== 1 || call.name !== 'shell' || call.providerExecuted
      || typeof call.input?.command !== 'string' || call.input.background
      || typeof call.id !== 'string' || reply?.type !== 'tool-result' || reply.name !== 'shell'
      || reply.id !== call.id || !reply.result) return;

  // A different display label or tool-call ID is not a different check.
  const { description, ...input } = call.input;
  return { input, result: reply.result };
}

// Compare only the final prefix filter. Keep the diff source, any intermediate
// pipeline, all other tool inputs and the complete displayed result verbatim.
function diffWindow(observation) {
  if (observation?.result.type !== 'text') return;
  const output = observation.result.value;
  if (typeof output !== 'string' || !output.trim() || output.includes('full output saved to ')) return;
  const { command, ...options } = observation.input;
  if (!command.startsWith('git diff ') || /[;&\r\n]/.test(command)) return;
  if (output === '(no output)') {
    const page = /\s+\|\s+sed -n '([1-9]\d*),([1-9]\d*)p'$/.exec(command);
    if (page) return { producer: command.slice(0, page.index), options, output };
  }
  const prefix = /\s+\|\s+(?:sed -n '1,[1-9]\d*p'|head -n [1-9]\d*)$/.exec(command);
  if (prefix) return { producer: command.slice(0, prefix.index), options, output };
}

export default {
  id: 'scaffold.qa-retry-guard',
  async setup(ctx) {
    await installStagedQA(ctx);
    await ctx.session.hook('context', request => {
      if (request.agent !== 'Kyle' || request.messages.length < 4) return;
      const messages = request.messages;
      const previous = shellObservation(messages.at(-4), messages.at(-3));
      const latest = shellObservation(messages.at(-2), messages.at(-1));
      if (!previous || !latest) return;
      let reason = 'Two consecutive shell calls used the same inputs and returned the same result.';
      if (!isDeepStrictEqual(previous, latest)) {
        const window = diffWindow(latest);
        if (!window || !isDeepStrictEqual(window, diffWindow(previous))) return;
        if (window.output === '(no output)') {
          reason = 'Two consecutive pages from the same diff were empty. Stop paging past the end.';
        } else {
          const first = shellObservation(messages.at(-6), messages.at(-5));
          if (!isDeepStrictEqual(window, diffWindow(first))) return;
          reason = 'Three consecutive prefix reads of the same diff returned identical output.';
        }
      }

      // This tool set is local to the current model request. A new handoff
      // naturally breaks the consecutive pairs; no session flags to clear.
      for (const name of Object.keys(request.tools)) delete request.tools[name];
      request.system.push({ type: 'text', text:
        'QA retry checkpoint. ' + reason + ' '
        + 'If your gates and inspection establish a verdict, give it now. Otherwise return a text checkpoint to Cartman. Cite the check and result, the outstanding requirement '
        + 'and the next diagnostic that would distinguish it. Keep unresolved QA pending. '
        + 'Matching output alone proves neither unchanged source nor a defect.' });
    });
  },
};
