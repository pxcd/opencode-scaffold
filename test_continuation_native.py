"""Opt-in native idle-hook smoke test; loopback fake model, no real inference."""
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parent


@unittest.skipUnless(os.environ.get('NEWOC_NATIVE_TESTS') == '1', 'explicit native fixture opt-in')
class ContinuationNativeTests(unittest.TestCase):
    def test_premature_final_is_resumed_by_native_idle_hook(self):
        self.run_fixture(False)

    def test_missing_plan_is_a_recoverable_tool_error_not_a_session_stop(self):
        self.run_fixture(True)

    def run_fixture(self, missing_plan):
        calls = []
        failure = []
        steps = [
            {'action': 'start', 'goal': 'Complete fixture repair and QA',
             'milestones': [{'id': 'repair', 'title': 'Repair'}, {'id': 'qa', 'title': 'QA'}],
             'next_action': 'Run fixture QA'},
            None,
            {'action': 'progress', 'completed': ['repair', 'qa'], 'evidence': 'Fixture checks passed', 'next_action': 'Record completion'},
            {'action': 'complete', 'evidence': 'All registered fixture milestones verified'},
            None,
        ]

        if missing_plan:
            steps.insert(0, {'delegate_without_plan': True})

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                index = len(calls)
                calls.append(request)
                if index >= len(steps):
                    failure.append('Unexpected repeated generation')
                    self.send_error(500)
                    return
                tool = steps[index]
                if tool is None:
                    delta = {'role': 'assistant', 'content': 'Ready for QA.' if index == 1 else 'Fixture complete.'}
                    finish = 'stop'
                else:
                    names = [t.get('function', {}).get('name') for t in request.get('tools', [])]
                    if 'continuation_checkpoint' not in names:
                        failure.append('Native checkpoint tool was not registered: ' + str(names))
                        self.send_error(500)
                        return
                    name = 'continuation_checkpoint'
                    if tool.get('delegate_without_plan'):
                        name = 'subagent'
                        tool = {'agent': 'worker', 'description': 'Unregistered fixture work', 'prompt': 'Do not execute; expected guard rejection'}
                    delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'call_fixture_' + str(index),
                        'type': 'function', 'function': {'name': name, 'arguments': json.dumps(tool)}}]}
                    finish = 'tool_calls'
                def chunk(content, stop=None):
                    return {'id': 'fixture-' + str(index), 'object': 'chat.completion.chunk',
                            'created': 1, 'model': 'stub', 'choices': [{'index': 0, 'delta': content, 'finish_reason': stop}]}
                body = ('data: ' + json.dumps(chunk(delta)) + '\n\n' +
                        'data: ' + json.dumps(chunk({}, finish)) + '\n\ndata: [DONE]\n\n').encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix='newoc-idle-fixture-', dir='/private/tmp') as directory:
                base = Path(directory)
                project = base / 'project'
                plugin = project / '.opencode/plugins/continuation-guard'
                shutil.copytree(ROOT / 'files/.opencode/plugins/continuation-guard', plugin)
                config = {'$schema': 'https://opencode.ai/config.json', 'default_agent': 'Cartman',
                    'model': 'fixture/stub', 'enabled_providers': ['fixture'],
                    'agents': {'Cartman': {'mode': 'primary', 'model': 'fixture/stub', 'steps': 20},
                               'worker': {'mode': 'subagent', 'model': 'fixture/stub'}},
                    'plugins': ['./.opencode/plugins/continuation-guard'],
                    'permissions': [{'action': 'continuation_checkpoint', 'resource': '*', 'effect': 'allow'},
                                    {'action': 'subagent', 'resource': 'worker', 'effect': 'allow'}],
                    'providers': {'fixture': {'package': 'aisdk:@ai-sdk/openai-compatible',
                        'settings': {'baseURL': f'http://127.0.0.1:{server.server_port}/v1'},
                        'models': {'stub': {'name': 'Local fake model', 'limit': {'context': 128000, 'output': 4096},
                                            'capabilities': {'tools': True, 'input': ['text'], 'output': ['text']}}}}}}
                (project / 'opencode.json').write_text(json.dumps(config))
                env = dict(os.environ)
                for key in ['OPENCODE_CONFIG', 'OPENCODE_CONFIG_DIR', 'OPENCODE_CONFIG_CONTENT']:
                    env.pop(key, None)
                for key in ['CONFIG', 'DATA', 'CACHE', 'STATE']:
                    env['XDG_' + key + '_HOME'] = str(base / key.lower())
                env['PWD'] = str(project)
                result = subprocess.run(['opencode', 'run', '--standalone', '--archived', '--agent', 'Cartman',
                    '--model', 'fixture/stub', '--title', 'Scaffold idle-hook fixture', '--format', 'json',
                    'Execute the authorized fixture lifecycle only.'], cwd=project, env=env,
                    capture_output=True, text=True, timeout=90)
                Path('/private/tmp/scaffold-idle-native-fixture.log').write_text(result.stdout + result.stderr)
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-5000:])
                self.assertFalse(failure, failure)
                self.assertEqual(len(calls), len(steps), (result.stdout + result.stderr)[-5000:])
                # Request three exists only because the fake premature final was intercepted.
                continued = json.dumps(calls[3 if missing_plan else 2].get('messages', []))
                self.assertIn('The authorized task is still active', continued)
                self.assertIn('qa: QA', continued)
                if missing_plan:
                    rejected = json.dumps(calls[1].get('messages', []))
                    self.assertIn('register/resume', rejected)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
