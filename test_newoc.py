import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from deploy import deploy

HERE = Path(__file__).resolve().parent
SCRIPT = HERE/'newoc.py'

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
    def test_new_project(self):
        r=self.run_tool('example','--root',str(self.root));self.assertEqual(r.returncode,0,r.stderr)
        p=self.root/'example';self.assertEqual(r.stdout.strip(),str(p))
        self.assertEqual(self.git(p,'branch','--show-current'),'main')
        self.assertFalse(self.git(p,'remote'))
        self.assertNotEqual(subprocess.run(['git','-C',str(p),'rev-parse','HEAD'],capture_output=True).returncode,0)
        for role in ['Arbiter','SCV','Overlord','probe','Sentry']:
            self.assertEqual((p/f'.opencode/agents/{role}.md').read_bytes(),(HERE/f'files/.opencode/agents/{role}.md').read_bytes())
        self.assertIn('# example engineering contract',(p/'AGENTS.md').read_text())
        self.assertFalse((p/'Sources').exists())
        self.assertTrue((p/'.opencode/agents/Arbiter.md').exists())
        config=json.loads((p/'opencode.json').read_text())
        self.assertEqual(config['default_agent'],'Arbiter')
        self.assertEqual(config['agents']['Arbiter']['model'],'openai/gpt-6.1-sol')
        self.assertIn('mode: primary',(p/'.opencode/agents/Arbiter.md').read_text())
        for role in ['SCV','probe','Overlord']:
            self.assertIn('mode: subagent',(p/f'.opencode/agents/{role}.md').read_text())
            self.assertTrue(config['agents'][role]['model'].startswith('lmstudio/'))
        self.assertTrue((p/'.opencode/scaffold.json').is_file())
    def test_publication_requires_coordinator_approval(self):
        config=json.loads((HERE/'files/opencode.json').read_text())
        self.assertIn({'action':'shell','resource':'git push*','effect':'deny'},config['permissions'])
        def permissions(role):
            return config['agents'][role]['permissions']
        shell=[p for p in permissions('Arbiter') if p['action']=='shell']
        self.assertEqual([p for p in shell if p['effect']=='ask'],[{'action':'shell','resource':'git push*','effect':'ask'}])
        for resource in ['git push*--force*','git push -f*','git push* -f*','git push* +*','git push*--mirror*','git push*--delete*','git push* :*']:
            self.assertIn({'action':'shell','resource':resource,'effect':'deny'},shell)
        for role in ['SCV','probe','Overlord']:
            self.assertFalse(any(p['action']=='shell' for p in permissions(role)))

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
        self.assertNotEqual(r.returncode,0);self.assertIn('AGENTS.md',r.stderr)
        args[2]='Overlord'
        r=subprocess.run(args+['--session','old-session'],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0);self.assertIn('invalid choice',r.stderr)

    def test_worker_process_exit_and_lock_are_preserved_with_fake_cli(self):
        self.assertEqual(self.run_tool('dispatch','--root',str(self.root)).returncode,0)
        p=self.root/'dispatch';task=p/'task.md';task.write_text('Controlled fake dispatch')
        (p/'AGENTS.md').write_text('Status: READY\nControlled fixture')
        (p/'.opencode/local.json').write_text(json.dumps({'local_provider_ids':['lmstudio'],'models':{r:'lmstudio/test' for r in ['SCV','probe','Overlord']}}))
        bin_dir=self.root/'bin';bin_dir.mkdir();cli=bin_dir/'opencode'
        cli.write_text('#!/bin/sh\nprintf "fake-worker-result\\n"\nexit 17\n');cli.chmod(0o755)
        env={**os.environ,'PATH':str(bin_dir)+os.pathsep+os.environ['PATH']}
        args=['python3.12',str(p/'.opencode/run-local.py'),'Arbiter','--task',str(task),'--execute','--routing-reviewed']
        r=subprocess.run(args,env=env,text=True,capture_output=True)
        self.assertEqual(r.returncode,17,r.stderr)
        self.assertFalse((p/'.opencode/.worker.lock').exists())
        self.assertIn('fake-worker-result',next((p/'.opencode/evidence').glob('*.log')).read_text())
        (p/'.opencode/.worker.lock').write_text('existing-worker')
        r=subprocess.run(args,env=env,text=True,capture_output=True)
        self.assertNotEqual(r.returncode,0)
        self.assertEqual((p/'.opencode/.worker.lock').read_text(),'existing-worker')

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
        smoke=subprocess.run(['python3.12','-m','unittest','test_newoc.ScaffoldTests.test_new_project'],
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
        overrides=b'{"agents":{"SCV":{"model":"lmstudio/custom"},"Arbiter":{"permissions":[{"action":"shell","resource":"git push*","effect":"deny"}]}},"instructions":["POLICY.md"],"plugins":["./plugins/project-hook"]}\n'
        (p/'.opencode/opencode.json').write_bytes(overrides)
        (p/'AGENTS.md').write_text('Project-only instructions.\n')
        config=source/'files/opencode.json';defaults=json.loads(config.read_text())
        defaults['agents']['Auditor']={'model':'lmstudio/qa'}
        defaults['agents']['Arbiter']['permissions'].append({'action':'subagent','resource':'Auditor','effect':'allow'})
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
    def test_native_layers_preserve_models_steps_permissions_and_plugins(self):
        self.assertEqual(self.run_tool('native','--root',str(self.root)).returncode,0)
        p=self.root/'native'
        plugin=p/'.opencode/plugins/project-hook';plugin.mkdir()
        (plugin/'index.js').write_text("export default {id:'test.project-hook',async setup(){}};\n")
        overrides={'agents': {'SCV': {'model':'lmstudio/project-worker','steps':7},
                              'compaction': {'model':'openai/project-helper'},
                              'Arbiter': {'permissions':[{'action':'shell','resource':'git push*','effect':'deny'}]}},
                   'instructions':['POLICY.md'],'plugins':['./plugins/project-hook']}
        (p/'.opencode/opencode.json').write_text(json.dumps(overrides))
        env={**os.environ,**{f'XDG_{k}_HOME':str(self.root/k.lower()) for k in ['CONFIG','DATA','CACHE','STATE']}}
        for key in ['OPENCODE_CONFIG','OPENCODE_CONFIG_DIR','OPENCODE_CONFIG_CONTENT']:env.pop(key,None)
        r=subprocess.run(['opencode','debug','agents','--standalone'],cwd=p,env=env,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        agents={a['name']:a for a in json.loads(r.stdout)}
        self.assertEqual(agents['SCV']['model'],{'providerID':'lmstudio','id':'project-worker'})
        self.assertEqual(agents['SCV']['steps'],7)
        for role in ['SCV','probe']:
            for resource in ['opencode.json','*/opencode.json']:
                rules=[r for r in agents[role]['permissions'] if r['action']=='edit' and r['resource']==resource]
                self.assertEqual(rules[-1]['effect'],'deny')
        self.assertEqual(agents['Sentry']['model'],{'providerID':'openai','id':'gpt-6.1-sol'})
        push=[r for r in agents['Arbiter']['permissions'] if r['action']=='shell' and r['resource']=='git push*']
        self.assertEqual(push[-1]['effect'],'deny')
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
        serialized=json.dumps([defaults['plugins'],project['plugins']])
        self.assertIn('project-hook',serialized);self.assertIn('step-limit-compat',serialized)
        self.assertEqual(self.run_tool('--update','--apply',cwd=p).returncode,0)
        self.assertEqual(json.loads((p/'.opencode/opencode.json').read_text()),overrides)

if __name__=='__main__': unittest.main()
