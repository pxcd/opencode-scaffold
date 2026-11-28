"""Opt-in native Stan handoff test with a scripted loopback provider."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from test_scaffold_qa_native import tool_delta


ROOT = Path(__file__).resolve().parent
PACKET = 'Stan review packet v1\nbase fixture, head fixture\nApproved fixture source'
AMBIENT = 'SYNTHETIC_AMBIENT_INSTRUCTIONS'
PARENT_CHAT = 'SYNTHETIC_PARENT_CHAT'


def scripted_response(request, child):
    ready = {'role': 'assistant', 'content': 'PASS: synthetic fixture.'}
    if child:
        return ready
    calls = [call['function'] for message in request['messages']
             for call in message.get('tool_calls', [])]
    actions = [json.loads(call['arguments'])['action'] for call in calls
               if call['name'] == 'continuation_checkpoint']
    if 'start' not in actions:
        return tool_delta('continuation_checkpoint', {
            'action': 'start', 'goal': 'Review scoped fixture',
            'milestones': [{'id': 'review', 'title': 'Independent review'}],
            'next_action': 'Dispatch Stan',
        }, 'fixture_plan')
    if not any(call['name'] == 'subagent' for call in calls):
        return tool_delta('subagent', {
            'agent': 'Stan', 'description': 'Review fixture packet', 'prompt': PACKET,
        }, 'fixture_stan')
    if any('<background-result' in str(message['content']) for message in request['messages']
           if message.get('role') == 'user') and 'progress' not in actions:
        return tool_delta('continuation_checkpoint', {
            'action': 'progress', 'completed': ['review'], 'evidence': 'Fixture child finished',
            'next_action': 'Complete',
        }, 'fixture_progress')
    if 'progress' in actions and 'complete' not in actions:
        return tool_delta('continuation_checkpoint', {
            'action': 'complete', 'evidence': 'Synthetic fixture finished',
        }, 'fixture_complete')
    return ready


@unittest.skipUnless(os.environ.get('NEWOC_NATIVE_TESTS') == '1', 'explicit native fixture opt-in')
class StanBoundaryNativeTests(unittest.TestCase):
    def test_native_provider_receives_only_the_review_packet(self):
        parent_requests, child_requests = [], []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_body(self, body, mime):
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                body = {'models': [{'type': 'llm', 'key': 'fixture-stub', 'display_name': 'Fixture',
                    'loaded_instances': [], 'max_context_length': 128000,
                    'capabilities': {'vision': False, 'trained_for_tool_use': True}}]}
                self.send_body(json.dumps(body).encode(), 'application/json')

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                child = self.headers.get('x-opencode-parent-session-id') is not None
                (child_requests if child else parent_requests).append(request)
                delta = scripted_response(request, child)
                reason = 'tool_calls' if 'tool_calls' in delta else 'stop'

                def event(content, finish):
                    chunk = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1,
                             'model': 'stub', 'choices': [
                                 {'index': 0, 'delta': content, 'finish_reason': finish}]}
                    return 'data: ' + json.dumps(chunk) + '\n\n'

                stream = event(delta, None) + event({}, reason) + 'data: [DONE]\n\n'
                self.send_body(stream.encode(), 'text/event-stream')

        with tempfile.TemporaryDirectory(prefix='newoc-stan-native-') as scratch, \
                http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            base = Path(scratch).resolve()
            subprocess.run([sys.executable, str(ROOT / 'newoc.py'), 'fixture', '--root', str(base)],
                           check=True, capture_output=True)
            project = base / 'fixture'
            (project / 'AGENTS.md').write_text(AMBIENT + '\n')
            model = 'lmstudio/fixture-stub'
            config = {'model': model, 'enabled_providers': ['lmstudio'],
                'agents': {name: {'model': model}
                           for name in ['Cartman', 'Stan', 'title', 'summary', 'compaction']},
                'providers': {'lmstudio': {'package': '@opencode/ai/providers/openai-compatible',
                    'settings': {'baseURL': f'http://127.0.0.1:{server.server_port}/v1'},
                    'models': {'fixture-stub': {'name': 'Scripted fixture',
                        'limit': {'context': 128000, 'output': 4096},
                        'capabilities': {'tools': True, 'input': ['text'], 'output': ['text']}}}}}}
            (project / '.opencode/opencode.json').write_text(json.dumps(config))
            home = base / 'home'
            home.mkdir()
            env = {'HOME': str(home), 'PATH': os.environ['PATH'], 'PWD': str(project), 'SHELL': '/bin/sh'}
            env.update({f'XDG_{name}_HOME': str(base / name.lower())
                        for name in ['CONFIG', 'DATA', 'CACHE', 'STATE']})
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = subprocess.run(['opencode', 'run', '--standalone', '--archived',
                    '--agent', 'Cartman', '--model', model, '--title', 'Stan fixture',
                    '--format', 'json', PARENT_CHAT], cwd=project, env=env,
                    capture_output=True, text=True, timeout=60)
            finally:
                server.shutdown()
                thread.join(timeout=5)

        self.assertEqual(result.returncode, 0, (result.stderr + result.stdout)[-4000:])
        self.assertTrue(any(AMBIENT in str(request['messages']) for request in parent_requests))
        self.assertTrue(any(PARENT_CHAT in str(request['messages']) for request in parent_requests))
        self.assertEqual(len(child_requests), 1, result.stdout[-4000:])
        child = child_requests[0]
        self.assertFalse(child.get('tools'))
        self.assertEqual([message['role'] for message in child['messages']], ['system', 'user'])
        self.assertEqual(child['messages'][1]['content'], PACKET)
        self.assertNotIn(AMBIENT, str(child))
        self.assertNotIn(PARENT_CHAT, str(child))


if __name__ == '__main__':
    unittest.main()
