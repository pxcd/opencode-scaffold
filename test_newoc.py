import hashlib
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from deploy import deploy

HERE = Path(__file__).resolve().parent
SCRIPT = HERE/'newoc.py'

FAKE_SESSION_API = """#!/usr/bin/env python3.12
import json, os, sys
from pathlib import Path
if 'api' in sys.argv:
    print(json.dumps({'data': {'id': 'ses_scope_fixture', 'agent': 'Arbiter',
        'location': {'directory': os.environ.get('FAKE_SESSION_DIRECTORY', os.environ['PWD'])}}}))
    raise SystemExit(0)
"""


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='newoc-test-', dir='/private/tmp')
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def run_tool(self, *args, cwd=None):
        return subprocess.run(['python3.12',str(SCRIPT),*args],cwd=cwd,text=True,capture_output=True)
    def git(self, path, *args):
        return subprocess.check_output(['git','-C',str(path),*args],text=True).strip()
    def legacy_fixture(self, name='legacy'):
        import shutil
        p=self.root/name;p.mkdir()
        shutil.copytree(HERE/'legacy-history/native-v3',p/'.opencode')
        (p/'.opencode/WORKFLOW.md').write_text('# Project constraints\nUse offline fixtures. Require independent QA and GUI acceptance.\n')
        (p/'AGENTS.md').write_text('# Custom project instructions\nPreserve security invariants.\n')
        (p/'README.md').write_text('Existing project documentation\n')
        (p/'source.txt').write_text('Existing source\n')
        (p/'.gitignore').write_text('.local/\n')
        config=p/'.opencode/opencode.json';data=json.loads(config.read_text())
        data['agents']['summary']['model']='openai/project-helper'
        data['agents']['compaction']['model']='openai/project-helper'
        data['instructions'].append('POLICY.md')
        data['plugins'].append('./plugins/project-hook')
        plugin=p/'.opencode/plugins/project-hook';plugin.mkdir(parents=True)
        (plugin/'index.js').write_text("export default {id:'fixture.project-hook',async setup(){}};\n")
        config.write_text(json.dumps(data,indent=2)+'\n')
        self.git(p,'init','-b','work/existing')
        self.git(p,'add','source.txt','README.md')
        self.git(p,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','Existing work')
        return p

    def snapshot(self, path):
        return {str(f.relative_to(path)):f.read_bytes() for f in path.rglob('*')
                if f.is_file() and '.git' not in f.parts and 'evidence' not in f.parts and 'scaffold-backups' not in f.parts}

    def test_legacy_update_preview_apply_and_repeat_preserve_project(self):
        p=self.legacy_fixture();(p/'source.txt').write_text('Existing source\nUncommitted work\n')
        before=self.snapshot(p);head=self.git(p,'rev-parse','HEAD')
        result=self.run_tool('--update',cwd=p);self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Legacy native scaffold',result.stderr)
        self.assertEqual(self.snapshot(p),before)
        self.assertFalse((p/'.opencode/evidence').exists())
        result=self.run_tool('--update','--apply',cwd=p);self.assertEqual(result.returncode,0,result.stderr)
        for path in ['AGENTS.md','README.md','source.txt','.opencode/plugins/project-hook/index.js']:
            self.assertEqual((p/path).read_bytes(),before[path])
        self.assertEqual((p/'.opencode/PROJECT.md').read_bytes(),before['.opencode/WORKFLOW.md'])
        overrides=json.loads((p/'.opencode/opencode.json').read_text())
        self.assertEqual(overrides['agents']['summary']['model'],'openai/project-helper')
        self.assertIn('POLICY.md',overrides['instructions'])
        self.assertIn('./plugins/project-hook',overrides['plugins'])
        self.assertEqual(self.git(p,'rev-parse','HEAD'),head)
        self.assertEqual(self.git(p,'branch','--show-current'),'work/existing')
        backups=list((p/'.opencode/scaffold-backups').glob('legacy-*'))
        self.assertEqual(len(backups),1)
        self.assertEqual((backups[0]/'files/.opencode/opencode.json').read_bytes(),before['.opencode/opencode.json'])
        self.assertEqual((backups[0]/'files/.opencode/opencode.json').stat().st_mode & 0o777,0o600)
        self.assertEqual((backups[0]/'files/.opencode/WORKFLOW.md').read_bytes(),before['.opencode/WORKFLOW.md'])
        self.git(p,'check-ignore','--no-index',str(backups[0]/'files/.opencode/WORKFLOW.md'))
        result=self.run_tool('--update',cwd=p);self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('0 file changes',result.stderr)

    def test_legacy_project_file_and_custom_shared_plugin_are_preserved(self):
        p=self.legacy_fixture()
        project=p/'.opencode/PROJECT.md';project.write_text('Existing optional project policy\n')
        plugin=p/'.opencode/plugins/step-limit-compat/index.js';plugin.parent.mkdir()
        plugin.write_text("export default {id:'fixture.custom-compat',async setup(){}};\n")
        before=self.snapshot(p)
        result=self.run_tool('--update','--apply',cwd=p);self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(project.read_bytes(),before['.opencode/PROJECT.md'])
        self.assertEqual((p/'.opencode/LEGACY-PROJECT.md').read_bytes(),before['.opencode/WORKFLOW.md'])
        self.assertEqual(plugin.read_bytes(),before['.opencode/plugins/step-limit-compat/index.js'])

        self.assertIn('.opencode/LEGACY-PROJECT.md',json.loads((p/'.opencode/opencode.json').read_text())['instructions'])
        metadata=json.loads((p/'.opencode/scaffold.json').read_text())
        self.assertIn('.opencode/plugins/step-limit-compat/index.js',metadata['project_owned'])
        self.assertNotIn('.opencode/plugins/step-limit-compat/index.js',metadata['files'])
        result=self.run_tool('--update','--apply',cwd=p);self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(plugin.read_bytes(),before['.opencode/plugins/step-limit-compat/index.js'])

    def test_legacy_ordered_global_permission_exceptions_survive(self):
        p=self.legacy_fixture();config=p/'.opencode/opencode.json'
        custom=[{'action':'shell','resource':'*','effect':'deny'},
                {'action':'shell','resource':'git status*','effect':'allow'}]
        data=json.loads(config.read_text());data['permissions'].extend(custom)
        config.write_text(json.dumps(data))
        result=self.run_tool('--update','--apply',cwd=p);self.assertEqual(result.returncode,0,result.stderr)
        effective=json.loads((p/'opencode.json').read_text());overrides=json.loads(config.read_text())
        for role in ['Arbiter','build']:
            rules=[*effective['permissions'],*overrides['permissions'],
                   *effective['agents'][role]['permissions'],*overrides['agents'][role]['permissions']]
            for command,wanted in [('git status --short','allow'),('touch unrelated','deny')]:
                matches=[r['effect'] for r in rules if fnmatchcase('shell',r['action']) and fnmatchcase(command,r['resource'])]
                self.assertEqual(matches[-1],wanted)

    def test_legacy_role_permission_exceptions_follow_global_policy(self):
        p=self.legacy_fixture();config=p/'.opencode/opencode.json'
        data=json.loads(config.read_text())
        data['permissions'].append({'action':'shell','resource':'*','effect':'deny'})
        for role in ['Arbiter','build']:
            data['agents'][role]={'permissions':[{'action':'shell','resource':'git status*','effect':'allow'}]}
        config.write_text(json.dumps(data))
        result=self.run_tool('--update','--apply',cwd=p);self.assertEqual(result.returncode,0,result.stderr)
        overrides=json.loads(config.read_text())
        for role in ['Arbiter','build']:
            matches=[r['effect'] for r in overrides['agents'][role]['permissions']
                     if r['action']=='shell' and fnmatchcase('git status --short',r['resource'])]
            self.assertEqual(matches[-1],'allow')

    def test_legacy_conflicts_and_malformed_inputs_have_no_partial_writes(self):
        cases=[('.opencode/agents/SCV.md','custom role body\n'),
               ('.opencode/opencode.json','{ malformed JSON'),
               ('.opencode/opencode.json','[]'),
               ('opencode.json','{}'),
               ('.opencode/.gitignore','!evidence/\n')]
        for number,(path,data) in enumerate(cases):
            p=self.legacy_fixture('invalid-'+str(number));(p/path).write_text(data)
            before=self.snapshot(p)
            for flags in [[],['--apply']]:
                result=self.run_tool('--update',*flags,cwd=p)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertNotIn('Traceback',result.stderr)
                self.assertEqual(self.snapshot(p),before)
                self.assertFalse((p/'.opencode/scaffold.json').exists())
                self.assertFalse((p/'.opencode/evidence').exists())
        p=self.root/'empty';p.mkdir()
        result=self.run_tool('--update',cwd=p)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('newoc --here',result.stderr)
        self.assertNotIn('Errno 2',result.stderr)

    def test_invalid_manifest_reports_an_actionable_error(self):
        self.assertEqual(self.run_tool('bad-manifest','--root',str(self.root)).returncode,0)
        p=self.root/'bad-manifest';path=p/'.opencode/scaffold.json'
        for value in [[],{}, {'version':'nonsense','files':{}},{'version':'4.0.0','files':[]}]:
            path.write_text(json.dumps(value));before=self.snapshot(p)
            result=self.run_tool('--update','--apply',cwd=p)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Invalid scaffold manifest',result.stderr)
            self.assertEqual(self.snapshot(p),before)

    def test_legacy_write_failure_rolls_back_and_retains_original_backups(self):
        from unittest.mock import patch
        import newoc
        p=self.legacy_fixture();before=self.snapshot(p);real_write=newoc.atomic_write
        failed=False
        def fail_manifest_once(path,data,mode=None):
            nonlocal failed
            if path == p/'.opencode/scaffold.json' and not failed:
                failed=True
                raise PermissionError('synthetic manifest write failure')
            return real_write(path,data,mode)
        with patch.object(newoc,'atomic_write',side_effect=fail_manifest_once):
            with self.assertRaisesRegex(OSError,'original project files restored'):
                newoc.update(p,True)
        self.assertTrue(failed)
        self.assertEqual(self.snapshot(p),before)
        self.assertFalse((p/'.opencode/scaffold.json').exists())
        backups=list((p/'.opencode/scaffold-backups').glob('legacy-*'))
        self.assertEqual((backups[0]/'files/.opencode/opencode.json').read_bytes(),before['.opencode/opencode.json'])
        self.git(p,'check-ignore','--no-index',str(backups[0]/'files/.opencode/opencode.json'))

    def test_interrupt_after_atomic_replace_restores_current_file(self):
        from unittest.mock import patch
        import newoc
        p=self.root/'interrupt';p.mkdir()
        first=p/'first';second=p/'second'
        first.write_bytes(b'original first');second.write_bytes(b'original second')
        real_write=newoc.atomic_write;interrupted=False
        def interrupt_after_replace(path,data,mode=None):
            nonlocal interrupted
            real_write(path,data,mode)
            if path==second and not interrupted:
                interrupted=True
                raise KeyboardInterrupt()
        with patch.object(newoc,'atomic_write',side_effect=interrupt_after_replace):
            with self.assertRaises(KeyboardInterrupt):
                newoc.apply_files(p,[(first,b'new first'),(second,b'new second')])
        self.assertEqual(first.read_bytes(),b'original first')
        self.assertEqual(second.read_bytes(),b'original second')
    def test_new_project(self):
        r=self.run_tool('example','--root',str(self.root));self.assertEqual(r.returncode,0,r.stderr)
        p=self.root/'example';self.assertEqual(r.stdout.strip(),str(p))
        self.assertEqual(self.git(p,'branch','--show-current'),'main')
        self.assertFalse(self.git(p,'remote'))
        self.assertNotEqual(subprocess.run(['git','-C',str(p),'rev-parse','HEAD'],capture_output=True).returncode,0)
        for role in ['Arbiter','SCV','Overlord','probe','Sentry']:
            self.assertEqual((p/f'.opencode/agents/{role}.md').read_bytes(),(HERE/f'files/.opencode/agents/{role}.md').read_bytes())
        self.assertIn('# example project instructions',(p/'AGENTS.md').read_text())
        manifest=json.loads((p/'.opencode/scaffold.json').read_text())
        self.assertNotIn('AGENTS.md',manifest['files'])
        self.assertEqual(manifest['starters']['AGENTS.md']['sha256'],
                         hashlib.sha256((p/'AGENTS.md').read_bytes()).hexdigest())
        self.assertIn('.opencode/BASELINE.md',manifest['files'])
        self.assertFalse((p/'Sources').exists())
        self.assertTrue((p/'.opencode/agents/Arbiter.md').exists())
        config=json.loads((p/'opencode.json').read_text())
        self.assertEqual(config['default_agent'],'Arbiter')
        self.assertIn('.opencode/BASELINE.md',config['instructions'])
        self.assertEqual(config['agents']['Arbiter']['model'],'openai/gpt-6.1-sol')
        self.assertIn('mode: primary',(p/'.opencode/agents/Arbiter.md').read_text())
        for role in ['SCV','probe','Overlord']:
            self.assertIn('mode: subagent',(p/f'.opencode/agents/{role}.md').read_text())
            self.assertTrue(config['agents'][role]['model'].startswith('lmstudio/'))
        self.assertTrue((p/'.opencode/scaffold.json').is_file())
        self.assertFalse(list(p.rglob('__pycache__')))
    def test_coordinator_push_permissions_are_scoped_to_single_feature_branch(self):
        config=json.loads((HERE/'files/opencode.json').read_text())
        def decision(role, command):
            result=None
            for rule in [*config['permissions'], *config['agents'][role].get('permissions',[])]:
                if fnmatchcase('shell',rule['action']) and fnmatchcase(command,rule['resource']):
                    result=rule['effect']
            return result
        allowed=['git push origin codex/task','git push -u origin codex/task',
                 'git push --set-upstream origin codex/task', 'git push origin codex/nested/task']
        guarded=['git push','git push origin main','git push origin master',
                 'git push -u origin main','git push upstream codex/task',
                 'git push origin HEAD','git push origin codex/task main',
                 'git push origin codex/task codex/other','git push origin codex/task --all',
                 'git push origin codex/task\tmain','git push origin codex/task\nmain',
                 'git push origin codex/task\rmain',
                 'git push origin codex/task:main','git push origin codex/task:refs/heads/main',
                 'git push --all origin','git push --tags origin']
        denied=['git push --force origin codex/task','git push origin codex/task --force-with-lease',
                'git push -uf origin codex/task','git push -f origin codex/task',
                'git push origin +codex/task','git push --mirror origin',
                'git push --delete origin codex/task','git push -d origin codex/task',
                'git push origin :codex/task']
        for role in ['Arbiter','build']:
            for effect,commands in [('allow',allowed),('ask',guarded),('deny',denied)]:
                for command in commands:
                    with self.subTest(role=role,command=command):
                        self.assertEqual(decision(role,command),effect)
        for role in ['SCV','probe','Overlord','Sentry','title','summary','compaction']:
            for command in allowed:
                with self.subTest(role=role,command=command):
                    self.assertEqual(decision(role,command),'deny')

    def test_desktop_entry_uses_bounded_coordinator_defaults(self):
        config=json.loads((HERE/'files/opencode.json').read_text())
        desktop=config['agents']['build'];explicit=config['agents']['Arbiter']
        self.assertEqual(desktop['system'],'{file:.opencode/agents/Arbiter.md}')
        self.assertEqual(desktop['mode'],'primary')
        for field in ['model','steps','permissions']:
            self.assertEqual(desktop[field],explicit[field])
        self.assertIn({'action':'subagent','resource':'*','effect':'deny'},config['permissions'])
        for role in ['SCV','probe','Overlord','Sentry']:
            self.assertIn({'action':'subagent','resource':'*','effect':'deny'},
                          config['agents'][role]['permissions'])

    def test_sentry_is_cloud_read_only_and_dispatchable(self):
        self.assertEqual(self.run_tool('review', '--root', str(self.root)).returncode, 0)
        p = self.root/'review'
        config = json.loads((p/'opencode.json').read_text())
        self.assertEqual(config['agents']['Sentry']['model'], 'openai/gpt-6.1-sol')
        def header(role):
            text = (p/f'.opencode/agents/{role}.md').read_text().removeprefix('---\n').split('\n---\n', 1)[0]
            return json.loads(subprocess.check_output(
                ['ruby', '-ryaml', '-rjson', '-e', 'puts JSON.generate(YAML.safe_load(STDIN.read))'],
                input=text, text=True))
        sentry = header('Sentry')
        self.assertEqual(sentry['mode'], 'subagent')
        for action in ['edit', 'shell', 'execute', 'subagent', 'external_directory']:
            self.assertEqual([rule for rule in config['agents']['Sentry']['permissions'] if rule['action'] == action],
                             [{'action': action, 'resource': '*', 'effect': 'deny'}])
        self.assertIn({'action': 'subagent', 'resource': 'Sentry', 'effect': 'allow'},
                      config['agents']['Arbiter']['permissions'])
        self.assertIn('.opencode/agents/Sentry.md',
                      json.loads((p/'.opencode/scaffold.json').read_text())['files'])
        # An old local profile must not require or redirect the cloud reviewer.
        (p/'.opencode/local.json').write_text(json.dumps({
            'local_provider_ids': ['lmstudio'],
            'models': {role: 'lmstudio/test' for role in ['SCV', 'probe', 'Overlord', 'Sentry']}}))
        (p/'task.md').write_text('Review fixture')
        preview = json.loads(subprocess.check_output([
            'python3.12', str(p/'.opencode/run-local.py'), '--task', str(p/'task.md')], text=True))
        self.assertEqual(preview['runtime_config']['agents']['Sentry']['model'], 'openai/gpt-6.1-sol')

    def test_builders_cannot_edit_managed_root_config(self):
        config=json.loads((HERE/'files/opencode.json').read_text())
        for role in ['SCV','probe']:
            for resource in ['opencode.json','*/opencode.json']:
                self.assertIn({'action':'edit','resource':resource,'effect':'deny'},
                              config['agents'][role]['permissions'])

    def test_existing_project_refused(self):
        p=self.root/'exists';p.mkdir();(p/'important').write_text('keep')
        r=self.run_tool('exists','--root',str(self.root));self.assertNotEqual(r.returncode,0)
        self.assertEqual([x.name for x in p.iterdir()],['important'])
    def test_invalid_name(self):
        r=self.run_tool('../escape','--root',str(self.root));self.assertNotEqual(r.returncode,0)
        self.assertFalse(list(self.root.iterdir()))
    def test_here_preserves_readme_git_branch_and_ignores(self):
        p=self.root/'python-app';p.mkdir();(p/'README.md').write_text('existing docs\n');(p/'.gitignore').write_text('.venv/\n.env')
        subprocess.run(['git','-C',str(p),'init','-b','custom'],check=True,capture_output=True)
        r=self.run_tool('--here',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual((p/'README.md').read_text(),'existing docs\n')
        self.assertTrue((p/'.gitignore').read_text().startswith('.venv/\n.env\n'))
        self.assertEqual((p/'.gitignore').read_text().splitlines().count('.env'),1)
        self.assertEqual(self.git(p,'branch','--show-current'),'custom')
    def test_collision_has_no_partial_writes(self):
        p=self.root/'collision';p.mkdir();(p/'opencode.json').write_text('do not replace')
        r=self.run_tool('--here',cwd=p);self.assertNotEqual(r.returncode,0)
        self.assertEqual([x.name for x in p.iterdir()],['opencode.json'])
    def test_symlink_destination_rejected(self):
        p=self.root/'linked';p.mkdir();outside=self.root/'outside';outside.mkdir();(p/'.opencode').symlink_to(outside,target_is_directory=True)
        r=self.run_tool('--here',cwd=p);self.assertNotEqual(r.returncode,0)
        self.assertFalse(list(outside.iterdir()));self.assertFalse((p/'AGENTS.md').exists())
    def test_zsh_wrapper_enters_project_and_help_does_not_cd(self):
        env={**os.environ,'NEWOC_TEMPLATE_DIR':str(HERE)}
        # Paths are supplied as positional parameters, never interpolated shell code.
        r=subprocess.run(['zsh','-f','-c','source "$1"; newoc wrapped --root "$2" || exit; [[ "$PWD" == "$2/wrapped" ]] || exit 2; newoc --help >/dev/null; [[ "$PWD" == "$2/wrapped" ]]', 'test',str(HERE/'newoc.zsh'),str(self.root)],env=env,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)

    def test_zsh_wrapper_uses_its_checkout_without_override(self):
        env = dict(os.environ)
        env.pop('NEWOC_TEMPLATE_DIR', None)
        r = subprocess.run(['zsh', '-f', '-c',
            'source "$1"; newoc relocated --root "$2" || exit; [[ "$PWD" == "$2/relocated" ]]',
            'test', str(HERE/'newoc.zsh'), str(self.root)], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.root/'relocated/.opencode/WORKFLOW.md').read_bytes(),
                         (HERE/'files/.opencode/WORKFLOW.md').read_bytes())

    def test_zsh_relative_source_survives_changing_directory(self):
        env = dict(os.environ)
        env.pop('NEWOC_TEMPLATE_DIR', None)
        r = subprocess.run(['zsh', '-f', '-c',
            'cd -- "$1"; source ./newoc.zsh; cd -- "$2"; newoc relative --root "$2" || exit; [[ "$PWD" == "$2/relative" ]]',
            'test', str(HERE), str(self.root)], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.root/'relative/.opencode/WORKFLOW.md').read_bytes(),
                         (HERE/'files/.opencode/WORKFLOW.md').read_bytes())

    def test_update_preview_and_apply_preserve_project_contract(self):
        self.assertEqual(self.run_tool('upgrade','--root',str(self.root)).returncode,0)
        p=self.root/'upgrade'
        contract=p/'.opencode/PROJECT.md';contract.write_text('project-owned custom commands\n')
        # Simulate an older deployed revision of a managed file.
        workflow=p/'.opencode/WORKFLOW.md';workflow.write_text('old reviewed workflow\n')
        manifest=p/'.opencode/scaffold.json';data=json.loads(manifest.read_text())
        data['version']='4.0.0';data['files']['.opencode/WORKFLOW.md']=hashlib.sha256(workflow.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(data))
        before=manifest.read_bytes()
        r=self.run_tool('--update',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(manifest.read_bytes(),before);self.assertEqual(workflow.read_text(),'old reviewed workflow\n')
        r=self.run_tool('--update','--apply',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(workflow.read_bytes(),(HERE/'files/.opencode/WORKFLOW.md').read_bytes())
        self.assertEqual(contract.read_text(),'project-owned custom commands\n')

    def test_finder_metadata_is_ignored_for_creation_and_update(self):
        # Use a disposable template, never contaminate the real source in a test.
        import shutil
        source=self.root/'starter'
        shutil.copytree(HERE/'files',source/'files')
        for name in ['newoc.py','TEMPLATE_VERSION']:
            shutil.copy2(HERE/name,source/name)
        metadata=b'\x00\xffFinder metadata'
        for relative in ['.DS_Store','.opencode/.DS_Store']:
            (source/'files'/relative).write_bytes(metadata)
        script=source/'newoc.py'
        p=self.root/'clean'
        r=subprocess.run(['python3.12',str(script),'clean','--root',str(self.root)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse(list(p.rglob('.DS_Store')))
        # Older generators may have recorded metadata; retire ownership without deleting it.
        m=p/'.opencode/scaffold.json';data=json.loads(m.read_text())
        finder=p/'.opencode/.DS_Store';finder.write_bytes(metadata)
        data['files']['.opencode/.DS_Store']=hashlib.sha256(metadata).hexdigest()
        m.write_text(json.dumps(data))
        r=subprocess.run(['python3.12',str(script),'--update','--apply'],cwd=p,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(finder.read_bytes(),metadata)
        self.assertNotIn('.opencode/.DS_Store',json.loads(m.read_text())['files'])

    def test_update_preserves_explicit_project_owned_config(self):
        self.assertEqual(self.run_tool('custom','--root',str(self.root)).returncode,0)
        p=self.root/'custom';config=p/'.opencode/opencode.json'
        custom=b'{"agents": {"compaction": {"model": "openai/project-helper"}}}\n';config.write_bytes(custom)
        m=p/'.opencode/scaffold.json';data=json.loads(m.read_text())
        data['project_owned']=['.opencode/opencode.json']
        m.write_text(json.dumps(data))
        r=self.run_tool('--update','--apply',cwd=p)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(config.read_bytes(),custom)
        self.assertEqual(json.loads(m.read_text())['project_owned'],data['project_owned'])
        self.assertEqual(self.run_tool('--update',cwd=p).returncode,0)
        data['files']['.opencode/opencode.json']='overlapping ownership'
        m.write_text(json.dumps(data));before=m.read_bytes()
        r=self.run_tool('--update','--apply',cwd=p)
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(m.read_bytes(),before);self.assertEqual(config.read_bytes(),custom)

    def test_update_refuses_local_edits_and_symlinks_without_partial_writes(self):
        self.assertEqual(self.run_tool('edited','--root',str(self.root)).returncode,0)
        p=self.root/'edited';workflow=p/'.opencode/WORKFLOW.md';workflow.write_text('custom local policy')
        before={str(f.relative_to(p)):f.read_bytes() for f in (p/'.opencode').rglob('*') if f.is_file()}
        r=self.run_tool('--update','--apply',cwd=p);self.assertNotEqual(r.returncode,0)
        self.assertIn('merge manually',r.stderr)
        self.assertEqual(before,{str(f.relative_to(p)):f.read_bytes() for f in (p/'.opencode').rglob('*') if f.is_file()})
        workflow.unlink();outside=self.root/'outside-policy';outside.write_text('untouched')
        workflow.symlink_to(outside)
        r=self.run_tool('--update','--apply',cwd=p);self.assertNotEqual(r.returncode,0)
        self.assertEqual(outside.read_text(),'untouched')

    def test_newpy_then_newoc_here(self):
        # Extract the actual existing function only; do not source unrelated shell startup.
        zshrc=(Path.home()/'.zshrc').read_text()
        function=zshrc[zshrc.index('newpy () {'):zshrc.index('\n}\n',zshrc.index('newpy () {'))+3]
        fake_home=self.root/'home';fake_home.mkdir()
        r=subprocess.run(['zsh','-f','-c',function+'\nnewpy python-app', 'test'],
                         env={**os.environ,'HOME':str(fake_home)},text=True,capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr)
        p=fake_home/'Development/python-app'
        preserved={f:(p/f).read_bytes() for f in ['main.py','requirements.txt','README.md']}
        r=self.run_tool('--here',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue((p/'.venv/pyvenv.cfg').is_file())
        self.assertEqual(preserved,{f:(p/f).read_bytes() for f in preserved})
        self.assertIn('.venv/',(p/'.gitignore').read_text())

    def test_local_launcher_guards_and_explicit_routes_without_inference(self):
        self.assertEqual(self.run_tool('routing','--root',str(self.root)).returncode,0)
        p=self.root/'routing';task=p/'task.md';task.write_text('Controlled handoff')
        launcher=p/'.opencode/run-local.py'
        args=['python3.12',str(launcher),'Arbiter','--task',str(task)]
        self.assertEqual(subprocess.run(args,capture_output=True).returncode,0)
        native=json.loads((p/'opencode.json').read_text())
        native['agents']['compaction']['model']='openai/project-authorized-helper'
        (p/'.opencode/opencode.json').write_text(json.dumps({'agents': {'compaction': native['agents']['compaction']}}))
        preview=json.loads(subprocess.check_output(args,text=True))
        self.assertNotIn('compaction',preview['runtime_config']['agents'])
        self.assertEqual(preview['runtime_config']['agents']['Sentry']['model'],'openai/gpt-6.1-sol')
        self.assertNotIn('enabled_providers',preview['runtime_config'])
        profile={'local_provider_ids':['lmstudio'],'models':{r:'lmstudio/test-local' for r in ['SCV','probe','Overlord']}}
        (p/'.opencode/local.json').write_text(json.dumps(profile))
        r=subprocess.run(args,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
        preview=json.loads(r.stdout)
        self.assertEqual(set(preview['runtime_config']['agents']),{'Arbiter','SCV','probe','Overlord','Sentry','title','summary','compaction'})
        self.assertEqual(preview['runtime_config']['agents']['Arbiter']['model'],'openai/gpt-6.1-sol')
        self.assertEqual(preview['runtime_config']['agents']['Sentry']['model'],'openai/gpt-6.1-sol')
        self.assertTrue(all(a['model']=='lmstudio/test-local' for n,a in preview['runtime_config']['agents'].items() if n not in ('Arbiter','Sentry')))
        self.assertIn('Codex intervention is optional',preview['argv'][-1])
        self.assertNotIn('--auto',preview['argv'])
        self.assertFalse((p/'.opencode/evidence').exists())
        r=subprocess.run(args+['--execute'],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0);self.assertIn('routing-reviewed',r.stderr)
        args[2]='Overlord'
        r=subprocess.run(args+['--session','old-session'],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0);self.assertIn('invalid choice',r.stderr)

    def test_worker_process_exit_and_lock_are_preserved_with_fake_cli(self):
        self.assertEqual(self.run_tool('dispatch','--root',str(self.root)).returncode,0)
        p=self.root/'dispatch';task=p/'task.md';task.write_text('Controlled fake dispatch')
        (p/'.opencode/local.json').write_text(json.dumps({'local_provider_ids':['lmstudio'],'models':{r:'lmstudio/test' for r in ['SCV','probe','Overlord']}}))
        bin_dir=self.root/'bin';bin_dir.mkdir();cli=bin_dir/'opencode'
        cli.write_text(FAKE_SESSION_API + 'print("fake-worker-result")\nprint("SESSION_PWD="+os.environ["PWD"])\nraise SystemExit(17)\n');cli.chmod(0o755)
        env={**os.environ,'PATH':str(bin_dir)+os.pathsep+os.environ['PATH']}
        args=['python3.12',str(p/'.opencode/run-local.py'),'Arbiter','--task',str(task),'--execute','--routing-reviewed']
        r=subprocess.run(args,env=env,text=True,capture_output=True)
        self.assertEqual(r.returncode,17,r.stderr)
        self.assertFalse((p/'.opencode/.worker.lock').exists())
        self.assertIn('fake-worker-result',next((p/'.opencode/evidence').glob('*/*.log')).read_text())
        self.assertIn('SESSION_PWD='+str(p),next((p/'.opencode/evidence').glob('*/*.log')).read_text())
        (p/'.opencode/.worker.lock').write_text('existing-worker')
        r=subprocess.run(args,env=env,text=True,capture_output=True)
        self.assertNotEqual(r.returncode,0)
        self.assertEqual((p/'.opencode/.worker.lock').read_text(),'existing-worker')

    def test_launcher_rejects_wrong_session_root_before_task_submission(self):
        self.assertEqual(self.run_tool('session-root','--root',str(self.root)).returncode,0)
        p=self.root/'session-root';task=p/'task.md';task.write_text('Controlled handoff')
        bin_dir=self.root/'bin';bin_dir.mkdir();cli=bin_dir/'opencode'
        marker=self.root/'submitted'
        cli.write_text(FAKE_SESSION_API + 'Path(os.environ["SUBMIT_MARKER"]).touch()\n');cli.chmod(0o755)
        env={**os.environ,'PATH':str(bin_dir)+os.pathsep+os.environ['PATH'],
             'FAKE_SESSION_DIRECTORY':str(self.root),'SUBMIT_MARKER':str(marker)}
        args=['python3.12',str(p/'.opencode/run-local.py'),'--task',str(task),
              '--execute','--routing-reviewed']
        for flags in [[], ['--session','ses_scope_fixture']]:
            result=subprocess.run(args+flags,cwd=p,env=env,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertIn('unsuitable repository root',result.stderr)
            self.assertFalse(marker.exists())
            self.assertFalse((p/'.opencode/.worker.lock').exists())

    def test_update_restores_ignored_evidence_and_preserves_project_work(self):
        p=self.root/'preserved';p.mkdir()
        subprocess.run(['git','-C',str(p),'init','-b','work/custom'],check=True,capture_output=True)
        rules=b'# Custom CPU-only project rules\n';source=b'project source\n';readme=b'Existing README\n'
        for name,data in [('AGENTS.md',rules),('source.txt',source),('README.md',readme)]:
            (p/name).write_bytes(data)
        self.git(p,'add','AGENTS.md','source.txt','README.md')
        self.git(p,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture')
        head=self.git(p,'rev-parse','HEAD')
        overrides=p/'.opencode/opencode.json';overrides.parent.mkdir()
        custom=b'{"agents":{"SCV":{"model":"lmstudio/project-specific"}}}\n';overrides.write_bytes(custom)
        self.assertEqual(self.run_tool('--here',cwd=p).returncode,0)
        (p/'source.txt').write_bytes(source+b'uncommitted work\n')
        ignore=p/'.gitignore';ignore.write_bytes(b'# Custom ignores\r\n.cache/\r\n!/.opencode/evidence/\r\n')
        original=ignore.read_bytes()
        result=self.run_tool('--update',cwd=p);self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(ignore.read_bytes(),original)
        result=self.run_tool('--update','--apply',cwd=p);self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(ignore.read_bytes().startswith(original))
        log=p/'.opencode/evidence/scope-test/raw.log';log.parent.mkdir(parents=True);log.write_text('synthetic finding\n')
        self.git(p,'check-ignore','--no-index',str(log))
        self.assertEqual(self.git(p,'rev-parse','HEAD'),head)
        self.assertEqual(self.git(p,'branch','--show-current'),'work/custom')
        self.assertEqual((p/'AGENTS.md').read_bytes(),rules)
        self.assertEqual((p/'README.md').read_bytes(),readme)
        self.assertEqual((p/'source.txt').read_bytes(),source+b'uncommitted work\n')
        self.assertEqual(overrides.read_bytes(),custom)
        result=self.run_tool('--update',cwd=p);self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('0 file changes',result.stderr)

    def test_update_refuses_worker_orchestration_permission_bypass(self):
        self.assertEqual(self.run_tool('guard','--root',str(self.root)).returncode,0)
        p=self.root/'guard';path=p/'.opencode/opencode.json'
        for role,action,resource in [('SCV','edit','*'),('probe','edit','opencode.jsonc'),
                                     ('Overlord','edit','.opencode/WORKFLOW.md'),
                                     ('SCV','edit','.opencode/preflight.py'),
                                     ('SCV','edit','.opencode/run-local.py'),
                                     ('SCV','edit','.opencode/agents/SCV.md'),
                                     ('probe','edit','.opencode/plugins/step-limit-compat/index.js'),
                                     ('SCV','external_directory','*')]:
            path.write_text(json.dumps({'agents':{role:{'permissions':[
                {'action':action,'resource':resource,'effect':'allow'}]}}}))
            before=path.read_bytes()
            result=self.run_tool('--update','--apply',cwd=p)
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertEqual(path.read_bytes(),before)

    def test_nested_ignore_conflict_is_refused_without_partial_writes(self):
        self.assertEqual(self.run_tool('nested-ignore','--root',str(self.root)).returncode,0)
        p=self.root/'nested-ignore'
        (p/'.opencode/.gitignore').write_text('!evidence/\n')
        before={str(f.relative_to(p)):f.read_bytes() for f in p.rglob('*')
                if f.is_file() and '.git' not in f.parts}
        for flags in [[],['--apply']]:
            result=self.run_tool('--update',*flags,cwd=p)
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertIn('Nested ignore rule exposes',result.stderr)
            self.assertEqual(before,{str(f.relative_to(p)):f.read_bytes() for f in p.rglob('*')
                                     if f.is_file() and '.git' not in f.parts})
        fresh=self.root/'existing-nested-ignore';fresh.mkdir()
        self.git(fresh,'init','-b','main');(fresh/'.opencode').mkdir()
        (fresh/'.opencode/.gitignore').write_text('!evidence/\n')
        result=self.run_tool('--here',cwd=fresh)
        self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertFalse((fresh/'AGENTS.md').exists())
        self.assertEqual((fresh/'.opencode/.gitignore').read_text(),'!evidence/\n')
        # Unrelated nested customizations remain usable, and evidence stays optional.
        (fresh/'.opencode/.gitignore').write_text('# Keep project policy\n!cache/\n')
        result=self.run_tool('--here',cwd=fresh)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((fresh/'.opencode/evidence').exists())
        result=self.run_tool('--update','--apply',cwd=fresh)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('0 file changes',result.stderr)
        self.assertFalse((fresh/'.opencode/evidence').exists())
        self.assertEqual((fresh/'.opencode/.gitignore').read_text(),'# Keep project policy\n!cache/\n')

    def test_here_restores_ignore_after_existing_root_negation(self):
        p=self.root/'root-negation';p.mkdir()
        self.git(p,'init','-b','main')
        ignore=p/'.gitignore';original=b'.opencode/evidence/\n!.opencode/evidence/\n'
        ignore.write_bytes(original)
        result=self.run_tool('--here',cwd=p)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(ignore.read_bytes().startswith(original))
        self.assertFalse((p/'.opencode/evidence').exists())
        log=p/'.opencode/evidence/check/raw.log';log.parent.mkdir(parents=True);log.write_text('synthetic\n')
        self.git(p,'check-ignore','--no-index',str(log))

    def test_dispatch_rechecks_overrides_with_and_without_local_profile(self):
        self.assertEqual(self.run_tool('preflight','--root',str(self.root)).returncode,0)
        p=self.root/'preflight'
        task=p/'task.md';task.write_text('Synthetic handoff')
        bin_dir=self.root/'bin';bin_dir.mkdir();marker=self.root/'spawned'
        cli=bin_dir/'opencode'
        cli.write_text(FAKE_SESSION_API + 'Path(os.environ["PREFLIGHT_TEST_MARKER"]).write_text("reached")\n');cli.chmod(0o755)
        env={**os.environ,'PATH':str(bin_dir)+os.pathsep+os.environ['PATH'],
             'PREFLIGHT_TEST_MARKER':str(marker)}
        launcher=['python3.12',str(p/'.opencode/run-local.py'),'--task',str(task)]
        overrides=p/'.opencode/opencode.json'
        cases=[{'agents':{'Sentry':{'disabled':True}}},
               {'agents':{'Sentry':{'model':'lmstudio/wrong'}}},
               {'agents':{'Sentry':{'permissions':[{'action':'shell','resource':'*','effect':'allow'}]}}},
               {'agents':{'Arbiter':{'permissions':[{'action':'subagent','resource':'Sentry','effect':'deny'}]}}}]
        for local in [False,True]:
            if local:
                (p/'.opencode/local.json').write_text(json.dumps({'local_provider_ids':['lmstudio'],
                    'models':{r:'lmstudio/test' for r in ['SCV','probe','Overlord']}}))
            for custom in cases:
                overrides.write_text(json.dumps(custom));before=overrides.read_bytes()
                for flags in [[],['--doctor'],['--execute','--routing-reviewed']]:
                    with self.subTest(local=local,custom=custom,flags=flags):
                        r=subprocess.run(launcher+flags,cwd=p,env=env,capture_output=True,text=True)
                        self.assertNotEqual(r.returncode,0,r.stdout+r.stderr)
                        self.assertFalse(marker.exists());self.assertFalse((p/'.opencode/evidence').exists())
                        self.assertEqual(overrides.read_bytes(),before)
        overrides.write_text('{}\n')
        r=subprocess.run(launcher+['--execute','--routing-reviewed'],cwd=p,env=env,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(marker.exists())

    def test_fresh_and_legacy_instructions_do_not_gate_dispatch(self):
        self.assertEqual(self.run_tool('usable','--root',str(self.root)).returncode,0)
        p=self.root/'usable';task=p/'task.md';task.write_text('Synthetic handoff')
        instructions=p/'AGENTS.md';fresh=instructions.read_text()
        self.assertNotIn('Status:',fresh)
        self.assertNotIn('- Project purpose:',fresh)
        self.assertIn('Preserve existing tracked and untracked work',(p/'.opencode/BASELINE.md').read_text())
        bin_dir=self.root/'bin';bin_dir.mkdir();marker=self.root/'spawned'
        cli=bin_dir/'opencode'
        cli.write_text(FAKE_SESSION_API + 'Path(os.environ["USABLE_TEST_MARKER"]).write_text("reached")\n');cli.chmod(0o755)
        env={**os.environ,'PATH':str(bin_dir)+os.pathsep+os.environ['PATH'],
             'USABLE_TEST_MARKER':str(marker)}
        args=['python3.12',str(p/'.opencode/run-local.py'),'--task',str(task),'--execute','--routing-reviewed']
        for text in [fresh,'Status: UNCONFIGURED\n- Project purpose:\n',
                     '# Existing project rules\nUse CPU-only synthetic tests.\n']:
            with self.subTest(instructions=text[:40]):
                instructions.write_text(text);before=instructions.read_bytes()
                marker.unlink(missing_ok=True)
                r=subprocess.run(args,cwd=p,env=env,capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(marker.exists())
                self.assertEqual(instructions.read_bytes(),before)
                self.assertFalse((p/'.opencode/.worker.lock').exists())

    def test_major_migration_refused_without_touching_project_instructions(self):
        self.assertEqual(self.run_tool('v2-project','--root',str(self.root)).returncode,0)
        p=self.root/'v2-project'
        (p/'AGENTS.md').write_text('Old project-owned instructions: Codex dispatches workers directly.')
        manifest=p/'.opencode/scaffold.json';value=json.loads(manifest.read_text())
        value['version']='2.0.0';manifest.write_text(json.dumps(value))
        before={str(f.relative_to(p)):f.read_bytes() for f in p.rglob('*') if f.is_file() and '.git' not in f.parts}
        for extra in [[],['--apply']]:
            r=self.run_tool('--update',*extra,cwd=p)
            self.assertNotEqual(r.returncode,0)
            self.assertIn('Major scaffold change',r.stderr)
            self.assertEqual(before,{str(f.relative_to(p)):f.read_bytes() for f in p.rglob('*') if f.is_file() and '.git' not in f.parts})

    def test_update_refuses_downgrade_and_active_worker(self):
        self.assertEqual(self.run_tool('future','--root',str(self.root)).returncode,0)
        p=self.root/'future';manifest=p/'.opencode/scaffold.json';data=json.loads(manifest.read_text())
        data['version']='99.0.0';manifest.write_text(json.dumps(data))
        r=self.run_tool('--update','--apply',cwd=p)
        self.assertNotEqual(r.returncode,0);self.assertIn('downgrade',r.stderr)
        (p/'.opencode/.worker.lock').write_text('active')
        r=self.run_tool('--update','--apply',cwd=p)
        self.assertNotEqual(r.returncode,0);self.assertIn('worker lock',r.stderr)

    def test_nested_existing_root_rejected_but_new_project_gets_own_repo(self):
        subprocess.run(['git','-C',str(self.root),'init','-b','parent'],check=True,capture_output=True)
        nested=self.root/'nested';nested.mkdir()
        r=self.run_tool('--here',cwd=nested)
        self.assertNotEqual(r.returncode,0);self.assertFalse(list(nested.iterdir()))
        r=self.run_tool('own-repo','--root',str(self.root));self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.git(self.root/'own-repo','rev-parse','--show-toplevel'),str(self.root/'own-repo'))

    def test_deployment_preview_backup_and_symlink_refusal(self):
        destination=self.root/'installed';destination.mkdir();(destination/'custom').write_text('keep previous')
        deploy(HERE,destination)
        self.assertEqual([p.name for p in destination.iterdir()],['custom'])
        backup=deploy(HERE,destination,True)
        self.assertEqual((backup/'custom').read_text(),'keep previous')
        self.assertEqual((destination/'TEMPLATE_VERSION').read_text(),(HERE/'TEMPLATE_VERSION').read_text())
        smoke=subprocess.run(['python3.12','-m','unittest','test_newoc.ScaffoldTests.test_new_project',
                              'test_newoc.ScaffoldTests.test_update_recognizes_legacy_starter_and_keeps_backup',
                              'test_newoc.ScaffoldTests.test_legacy_update_preview_apply_and_repeat_preserve_project'],
                             cwd=destination,capture_output=True,text=True)
        self.assertEqual(smoke.returncode,0,smoke.stderr)
        link=self.root/'link';link.symlink_to(destination,target_is_directory=True)
        with self.assertRaises(ValueError): deploy(HERE,link,True)

    def test_here_and_updates_preserve_existing_project_contracts(self):
        p=self.root/'owned';p.mkdir()
        files={'AGENTS.md': b'# Existing rules\nNo network. Use custom tests.\n',
               'README.md': b'Existing documentation\n',
               '.opencode/PROJECT.md': b'Additional project rules\n',
               '.opencode/opencode.json': b'{"agents":{"SCV":{"model":"lmstudio/project-worker"}}}\n'}
        for f,data in files.items():
            out=p/f;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data)
        r=self.run_tool('--here',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        m=json.loads((p/'.opencode/scaffold.json').read_text())
        for f,data in files.items():
            self.assertEqual((p/f).read_bytes(),data);self.assertNotIn(f,m['files'])
        self.assertIn('opencode.json',m['files'])
        r=self.run_tool('--update','--apply',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        for f,data in files.items():self.assertEqual((p/f).read_bytes(),data)

    def test_incompatible_overrides_fail_before_writes(self):
        self.assertEqual(self.run_tool('conflict','--root',str(self.root)).returncode,0)
        p=self.root/'conflict';config=p/'.opencode/opencode.json'
        cases=[{'agents': {'Arbiter': {'permissions': [{'action':'subagent','resource':'Sentry','effect':'deny'}]}}},
               {'agents': {'Sentry': {'model':'lmstudio/wrong-route'}}},
               {'agents': {'Sentry': {'permissions':[{'action':'edit','resource':'Sources/*','effect':'allow'}]}}},
               {'agents': {'SCV': {'permissions':[{'action':'subagent','resource':'*','effect':'allow'}]}}},
               {'agents': {'Overlord': {'disabled':True}}},
               {'agents': {'Sentry': {'disabled':True}}}]
        cases.append({'permissions':[{'action':'shell','resource':'git push*','effect':'deny'}]})
        cases.extend([{'agents':{'build':{'disabled':True}}},
                      {'agents':{'build':{'model':'lmstudio/wrong'}}},
                      {'agents':{'build':{'system':'Implement everything yourself'}}},
                      {'agents':{'Arbiter':{'permissions':[{'action':'shell','resource':'git push*','effect':'deny'}]}}}])
        for overrides in cases:
            with self.subTest(overrides=overrides):
                config.write_text(json.dumps(overrides))
                before={str(f.relative_to(p)):f.read_bytes() for f in p.rglob('*') if f.is_file() and '.git' not in f.parts}
                r=self.run_tool('--update','--apply',cwd=p)
                self.assertNotEqual(r.returncode,0,r.stderr)
                self.assertEqual(before,{str(f.relative_to(p)):f.read_bytes() for f in p.rglob('*') if f.is_file() and '.git' not in f.parts})

    def test_future_agent_update_preserves_project_overrides(self):
        import shutil
        source=self.root/'starter';source.mkdir()
        shutil.copytree(HERE/'files',source/'files')
        for name in ['newoc.py','TEMPLATE_VERSION']:shutil.copy2(HERE/name,source/name)
        script=source/'newoc.py';p=self.root/'future-agent'
        r=subprocess.run(['python3.12',str(script),'future-agent','--root',str(self.root)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        overrides=b'{"agents":{"SCV":{"model":"lmstudio/custom"},"Arbiter":{"permissions":[{"action":"shell","resource":"git push*","effect":"deny"}]},"build":{"permissions":[{"action":"shell","resource":"git push*","effect":"deny"}]}},"instructions":["POLICY.md"],"plugins":["./plugins/project-hook"]}\n'
        (p/'.opencode/opencode.json').write_bytes(overrides)
        (p/'AGENTS.md').write_text('Project-only instructions.\n')
        config=source/'files/opencode.json';defaults=json.loads(config.read_text())
        defaults['agents']['Auditor']={'model':'lmstudio/qa'}
        for entry in ['Arbiter','build']:
            defaults['agents'][entry]['permissions'].append({'action':'subagent','resource':'Auditor','effect':'allow'})
        config.write_text(json.dumps(defaults,indent=2)+'\n')
        (source/'files/.opencode/agents/Auditor.md').write_text('---\ndescription: Future role\nmode: subagent\n---\nIndependent fixture.\n')
        before=(p/'opencode.json').read_bytes()
        r=subprocess.run(['python3.12',str(script),'--update'],cwd=p,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((p/'opencode.json').read_bytes(),before)
        self.assertFalse((p/'.opencode/agents/Auditor.md').exists())
        r=subprocess.run(['python3.12',str(script),'--update','--apply'],cwd=p,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue((p/'.opencode/agents/Auditor.md').exists())
        self.assertEqual(json.loads((p/'opencode.json').read_text())['agents']['Auditor']['model'],'lmstudio/qa')
        self.assertEqual((p/'.opencode/opencode.json').read_bytes(),overrides)
        self.assertEqual((p/'AGENTS.md').read_text(),'Project-only instructions.\n')
        r=subprocess.run(['python3.12',str(script),'--update'],cwd=p,capture_output=True,text=True)
        self.assertIn('0 file changes',r.stderr)

    @unittest.skipUnless(os.environ.get('NEWOC_NATIVE_TESTS') == '1', 'opt-in OpenCode native discovery; no inference')
    def test_native_launcher_verifies_session_before_handoff(self):
        self.assertEqual(self.run_tool('native-launch','--root',str(self.root)).returncode,0)
        p=self.root/'native-launch'
        env={k:v for k,v in os.environ.items() if not k.startswith('OPENCODE_')}
        env.update({f'XDG_{k}_HOME':str(self.root/k.lower()) for k in ['CONFIG','DATA','CACHE','STATE']})
        env['PWD']=str(p)
        program='''import json, os, runpy, sys
from pathlib import Path
root=Path(sys.argv[1])
sys.path.insert(0,str(root/'.opencode'))
verify=runpy.run_path(str(root/'.opencode/run-local.py'))['verified_session']
session=verify(root,dict(os.environ))
assert verify(root,dict(os.environ),session)==session
try:
    verify(root.parent,dict(os.environ),session)
except ValueError as e:
    assert 'unsuitable repository root' in str(e)
else:
    raise AssertionError('wrong repository was accepted')
print('Native create/get verified; wrong-root resume rejected; no prompt submitted')
'''
        result=subprocess.run(['python3.12','-c',program,str(p)],cwd=p,env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('no prompt submitted',result.stdout)

    @unittest.skipUnless(os.environ.get('NEWOC_NATIVE_TESTS') == '1', 'opt-in OpenCode native discovery; no inference')
    def test_native_repository_scope_permissions_without_inference(self):
        import base64
        import re
        import time
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        self.assertEqual(self.run_tool('native-scope','--root',str(self.root)).returncode,0)
        p=self.root/'native-scope'
        env={k:v for k,v in os.environ.items() if not k.startswith('OPENCODE_')}
        env.update({f'XDG_{k}_HOME':str(self.root/k.lower()) for k in ['CONFIG','DATA','CACHE','STATE']})
        env['PWD']=str(p)
        log=self.root/'isolated-server.log'
        with log.open('w') as stream:
            process=subprocess.Popen(['opencode','serve','--hostname','127.0.0.1','--port','0'],
                                     cwd=p,env=env,stdout=stream,stderr=stream)
            try:
                for _ in range(150):
                    output=log.read_text()
                    address=re.search(r'server listening on (http://127\.0\.0\.1:\d+)',output)
                    password=re.search(r'server password (\S+)',output)
                    if address and password:break
                    if process.poll() is not None:self.fail('Isolated server exited before discovery')
                    time.sleep(.1)
                else:self.fail('Isolated server did not become ready')
                def api(path,body=None):
                    headers={'Authorization':'Basic '+base64.b64encode(('opencode:'+password[1]).encode()).decode()}
                    if body is not None:headers['Content-Type']='application/json'
                    request=Request(address[1]+path,headers=headers,
                                    data=json.dumps(body).encode() if body is not None else None)
                    with urlopen(request,timeout=15) as response:
                        return json.load(response)
                query='?'+urlencode({'location[directory]':str(p)})
                for _ in range(100):
                    agents={a['id']:a for a in api('/api/agent'+query)['data']}
                    if 'Arbiter' in agents:break
                    time.sleep(.1)
                self.assertIn('Arbiter',agents,sorted(agents))
                for role in ['Arbiter','build','SCV','probe','Overlord','Sentry']:
                    session=api('/api/session',{'agent':role,'location':{'directory':str(p)}})['data']
                    self.assertEqual(Path(session['location']['directory']).resolve(),p)
                    def permission(action,resource):
                        return api('/api/session/'+session['id']+'/permission',{
                            'action':action,'resources':[resource],'agent':role})['data']['effect']
                    with self.subTest(role=role):
                        self.assertEqual(agents[role]['model']['providerID'],
                                         'openai' if role in ['Arbiter','build','Sentry'] else 'lmstudio')
                        expected='ask' if role in ['Arbiter','build'] else 'deny'
                        self.assertEqual(permission('external_directory',str(self.root/'other-checkout')+'/*'),expected)
                        # Check both tool-relative and absolute resources through the native engine.
                        if role in ['SCV','probe','Overlord']:
                            for path in ['opencode.json','opencode.jsonc','.opencode/opencode.json',
                                         '.opencode/WORKFLOW.md','.opencode/agents/Arbiter.md',
                                         '.opencode/agents/SCV.md','.opencode/preflight.py',
                                         '.opencode/plugins/step-limit-compat/index.js']:
                                for resource in [path,str(p/path)]:
                                    self.assertEqual(permission('edit',resource),'deny',resource)
                            evidence='.opencode/evidence/synthetic-scope/raw.log'
                            for resource in [evidence,str(p/evidence)]:
                                self.assertEqual(permission('edit',resource),'allow',resource)
                            target=p/evidence;target.parent.mkdir(parents=True,exist_ok=True)
                            target.write_text('Synthetic investigation evidence\n')
                            self.git(p,'check-ignore','--no-index',str(target))
                self.assertEqual(self.git(p,'status','--porcelain','--','.opencode/evidence'),'')
                legacy=self.legacy_fixture('native-legacy')
                config=legacy/'.opencode/opencode.json';custom=json.loads(config.read_text())
                custom['permissions'].extend([
                    {'action':'shell','resource':'*','effect':'deny'},
                    {'action':'shell','resource':'git status*','effect':'allow'}])
                config.write_text(json.dumps(custom))
                result=self.run_tool('--update','--apply',cwd=legacy)
                self.assertEqual(result.returncode,0,result.stderr)
                legacy_query='?'+urlencode({'location[directory]':str(legacy)})
                for _ in range(100):
                    migrated={a['id']:a for a in api('/api/agent'+legacy_query)['data']}
                    if 'Arbiter' in migrated:break
                    time.sleep(.1)
                self.assertEqual(migrated['summary']['model'],{'providerID':'openai','id':'project-helper'})
                for role in ['Arbiter','build']:
                    session=api('/api/session',{'agent':role,'location':{'directory':str(legacy)}})['data']
                    self.assertEqual(Path(session['location']['directory']).resolve(),legacy)
                    for command,wanted in [('git status --short','allow'),('touch unrelated','deny')]:
                        effect=api('/api/session/'+session['id']+'/permission',{
                            'action':'shell','resources':[command],'agent':role})['data']['effect']
                        self.assertEqual(effect,wanted)
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)

    @unittest.skipUnless(os.environ.get('NEWOC_NATIVE_TESTS') == '1', 'opt-in OpenCode native discovery; no inference')
    def test_native_layers_preserve_models_steps_permissions_and_plugins(self):
        self.assertEqual(self.run_tool('native','--root',str(self.root)).returncode,0)
        p=self.root/'native'
        plugin=p/'.opencode/plugins/project-hook';plugin.mkdir()
        (plugin/'index.js').write_text("export default {id:'test.project-hook',async setup(){}};\n")
        overrides={'agents': {'SCV': {'model':'lmstudio/project-worker','steps':7},
                              'compaction': {'model':'openai/project-helper'},
                              'Arbiter': {'permissions':[{'action':'shell','resource':'git push*','effect':'deny'}]}},
                   'instructions':['POLICY.md'],'plugins':['./plugins/project-hook']}
        overrides['agents']['build']={'permissions':overrides['agents']['Arbiter']['permissions']}
        (p/'.opencode/opencode.json').write_text(json.dumps(overrides))
        env={**os.environ,**{f'XDG_{k}_HOME':str(self.root/k.lower()) for k in ['CONFIG','DATA','CACHE','STATE']}}
        for key in ['OPENCODE_CONFIG','OPENCODE_CONFIG_DIR','OPENCODE_CONFIG_CONTENT']:env.pop(key,None)
        r=subprocess.run(['opencode','debug','agents','--standalone'],cwd=p,env=env,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        agents={a['id']:a for a in json.loads(r.stdout)}
        self.assertEqual(agents['SCV']['model'],{'providerID':'lmstudio','id':'project-worker'})
        self.assertEqual(agents['SCV']['steps'],7)
        for role in ['SCV','probe']:
            for resource in ['opencode.json','*/opencode.json']:
                rules=[r for r in agents[role]['permissions'] if r['action']=='edit' and r['resource']==resource]
                self.assertEqual(rules[-1]['effect'],'deny')
        self.assertEqual(agents['Sentry']['model'],{'providerID':'openai','id':'gpt-6.1-sol'})
        for coordinator in ['Arbiter','build']:
            push=[r for r in agents[coordinator]['permissions'] if r['action']=='shell' and r['resource']=='git push*']
            self.assertEqual(push[-1]['effect'],'deny')
        self.assertEqual(agents['build']['model'],agents['Arbiter']['model'])
        self.assertEqual(agents['build']['steps'],agents['Arbiter']['steps'])
        self.assertIn(agents['Arbiter']['system'].strip(),agents['build']['system'])
        for coordinator in ['Arbiter','build']:
            rules=[r for r in agents[coordinator]['permissions'] if r['action']=='subagent']
            self.assertEqual(rules[-5:],[{'action':'subagent','resource':'*','effect':'deny'},
                *[{'action':'subagent','resource':role,'effect':'allow'} for role in ['SCV','Overlord','probe','Sentry']]])
        for action in ['edit','shell','execute','subagent','external_directory']:
            rules=[r for r in agents['Sentry']['permissions'] if r['action']==action and r['resource']=='*']
            self.assertEqual(rules[-1]['effect'],'deny')
        r=subprocess.run(['opencode','debug','config','--standalone'],cwd=p,env=env,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        documents=[d for d in json.loads(r.stdout) if d['type']=='document']
        defaults=next(d['info'] for d in documents if d['path']==str(p/'opencode.json'))
        project=next(d['info'] for d in documents if d['path']==str(p/'.opencode/opencode.json'))
        self.assertLess(next(i for i,d in enumerate(documents) if d['info']==defaults),
                        next(i for i,d in enumerate(documents) if d['info']==project))
        self.assertEqual(project['agents']['compaction']['model'],{'providerID':'openai','model':'project-helper'})
        self.assertIn('POLICY.md',project['instructions'])
        self.assertIn('.opencode/WORKFLOW.md',defaults['instructions'])
        self.assertIn('.opencode/BASELINE.md',defaults['instructions'])
        serialized=json.dumps([defaults['plugins'],project['plugins']])
        self.assertIn('project-hook',serialized);self.assertIn('step-limit-compat',serialized)
        self.assertEqual(self.run_tool('--update','--apply',cwd=p).returncode,0)
        self.assertEqual(json.loads((p/'.opencode/opencode.json').read_text()),overrides)

    def test_update_recognizes_legacy_starter_and_keeps_backup(self):
        self.assertEqual(self.run_tool('renamed','--root',str(self.root)).returncode,0)
        p=self.root/'renamed';agents=p/'AGENTS.md';m=p/'.opencode/scaffold.json'
        old=(HERE/'starter-history/AGENTS-4.0.0.md').read_text().replace('{{PROJECT_NAME}}','original-name').encode()
        agents.write_bytes(old)
        data=json.loads(m.read_text());data.pop('starters');data['version']='4.0.2';m.write_text(json.dumps(data))
        before={str(f.relative_to(p)):f.read_bytes() for f in p.rglob('*') if f.is_file() and '.git' not in f.parts}
        r=self.run_tool('--update',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('replaced untouched generated starter',r.stderr)
        self.assertEqual(before,{str(f.relative_to(p)):f.read_bytes() for f in p.rglob('*') if f.is_file() and '.git' not in f.parts})
        r=self.run_tool('--update','--apply',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('# original-name project instructions',agents.read_text())
        backup=p/'.opencode/evidence/scaffold-updates'/('AGENTS-'+hashlib.sha256(old).hexdigest()+'.md')
        self.assertEqual(backup.read_bytes(),old)
        record=json.loads(m.read_text())['starters']['AGENTS.md']
        self.assertEqual(record,{'sha256':hashlib.sha256(agents.read_bytes()).hexdigest(),'project_name':'original-name'})
        r=self.run_tool('--update',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('0 file changes',r.stderr)

    def test_missing_instructions_are_restored_without_adopting_custom_rules(self):
        self.assertEqual(self.run_tool('missing','--root',str(self.root)).returncode,0)
        p=self.root/'missing';agents=p/'AGENTS.md';expected=agents.read_bytes()
        agents.unlink()
        r=self.run_tool('--update',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse(agents.exists());self.assertIn('created missing file',r.stderr)
        r=self.run_tool('--update','--apply',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(agents.read_bytes(),expected)
        custom=b'# Team instructions\nDo not access the production network.\n'
        agents.write_bytes(custom)
        for _ in range(2):
            r=self.run_tool('--update','--apply',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(agents.read_bytes(),custom)
            record=json.loads((p/'.opencode/scaffold.json').read_text())['starters']['AGENTS.md']
            self.assertEqual(record['sha256'],hashlib.sha256(expected).hexdigest())
            self.assertNotEqual(record['sha256'],hashlib.sha256(custom).hexdigest())

    def test_unknown_and_customized_legacy_instructions_are_preserved(self):
        self.assertEqual(self.run_tool('custom-rules','--root',str(self.root)).returncode,0)
        p=self.root/'custom-rules';agents=p/'AGENTS.md';m=p/'.opencode/scaffold.json'
        data=json.loads(m.read_text());data.pop('starters');m.write_text(json.dumps(data))
        legacy=(HERE/'starter-history/AGENTS-4.0.0.md').read_text().replace('{{PROJECT_NAME}}','custom-rules')
        for contents in [(legacy+'\nKeep this repo-specific rule.\n').encode(),b'# Human-authored rules\nUse custom checks.\n']:
            agents.write_bytes(contents)
            r=self.run_tool('--update','--apply',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(agents.read_bytes(),contents)
            self.assertIn('preserved customized or unrecognized',r.stderr)
            self.assertNotIn('starters',json.loads(m.read_text()))
            self.assertFalse((p/'.opencode/evidence/scaffold-updates').exists())

    def test_recorded_generated_starter_upgrades_without_history_match(self):
        self.assertEqual(self.run_tool('provenance','--root',str(self.root)).returncode,0)
        p=self.root/'provenance';agents=p/'AGENTS.md';m=p/'.opencode/scaffold.json'
        old=b'# Generated starter from an earlier compatible release\n'
        agents.write_bytes(old);data=json.loads(m.read_text())
        data['starters']['AGENTS.md']['sha256']=hashlib.sha256(old).hexdigest();m.write_text(json.dumps(data))
        r=self.run_tool('--update','--apply',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(agents.read_text(),(HERE/'files/AGENTS.md').read_text().replace('{{PROJECT_NAME}}','provenance'))

    def test_starter_backup_symlink_is_refused_before_any_writes(self):
        self.assertEqual(self.run_tool('backup-link','--root',str(self.root)).returncode,0)
        p=self.root/'backup-link';agents=p/'AGENTS.md'
        old=(HERE/'starter-history/AGENTS-4.0.0.md').read_text().replace('{{PROJECT_NAME}}','backup-link').encode()
        agents.write_bytes(old)
        outside=self.root/'outside';outside.mkdir();(p/'.opencode/evidence').symlink_to(outside,target_is_directory=True)
        manifest=(p/'.opencode/scaffold.json').read_bytes()
        r=self.run_tool('--update','--apply',cwd=p);self.assertNotEqual(r.returncode,0)
        self.assertEqual(agents.read_bytes(),old);self.assertEqual((p/'.opencode/scaffold.json').read_bytes(),manifest)
        self.assertFalse(list(outside.iterdir()))

    def test_project_owned_instruction_symlink_is_not_followed_or_replaced(self):
        self.assertEqual(self.run_tool('linked-rules','--root',str(self.root)).returncode,0)
        p=self.root/'linked-rules';agents=p/'AGENTS.md';agents.unlink()
        outside=self.root/'shared-rules';outside.write_bytes(b'# External project rules\n')
        agents.symlink_to(outside)
        r=self.run_tool('--update','--apply',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue(agents.is_symlink());self.assertEqual(outside.read_bytes(),b'# External project rules\n')
        self.assertIn('preserved project-owned symlink',r.stderr)

    def test_managed_baseline_updates_without_rewriting_project_instructions(self):
        self.assertEqual(self.run_tool('baseline','--root',str(self.root)).returncode,0)
        p=self.root/'baseline';agents=p/'AGENTS.md';agents.write_bytes(b'# Team policy\nKeep our rules.\n')
        baseline=p/'.opencode/BASELINE.md';baseline.write_text('previous generated defaults\n')
        m=p/'.opencode/scaffold.json';data=json.loads(m.read_text())
        data['files']['.opencode/BASELINE.md']=hashlib.sha256(baseline.read_bytes()).hexdigest();m.write_text(json.dumps(data))
        r=self.run_tool('--update','--apply',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(agents.read_bytes(),b'# Team policy\nKeep our rules.\n')
        self.assertEqual(baseline.read_bytes(),(HERE/'files/.opencode/BASELINE.md').read_bytes())

    def test_coordinator_system_overrides_cannot_drop_project_constraints(self):
        self.assertEqual(self.run_tool('system-policy','--root',str(self.root)).returncode,0)
        p=self.root/'system-policy';overrides=p/'.opencode/opencode.json'
        before={str(f.relative_to(p)):f.read_bytes() for f in p.rglob('*') if f.is_file() and '.git' not in f.parts}
        for role in ['Arbiter','build']:
            rules={'agents':{role:{'system':'Project constraint: never send internal source to cloud review.'}}}
            overrides.write_text(json.dumps(rules));original=overrides.read_bytes()
            r=self.run_tool('--update','--apply',cwd=p)
            self.assertNotEqual(r.returncode,0,r.stderr);self.assertIn('project-owned AGENTS.md',r.stderr)
            self.assertEqual(overrides.read_bytes(),original)
            for relative,contents in before.items():
                if relative!='.opencode/opencode.json':self.assertEqual((p/relative).read_bytes(),contents,relative)

if __name__=='__main__': unittest.main()
