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
        for role in ['Arbiter','SCV','Overlord','probe']:
            self.assertEqual((p/f'.opencode/agents/{role}.md').read_bytes(),(HERE/f'files/.opencode/agents/{role}.md').read_bytes())
        self.assertIn('# example engineering contract',(p/'AGENTS.md').read_text())
        self.assertFalse((p/'Sources').exists())
        self.assertTrue((p/'.opencode/agents/Arbiter.md').exists())
        config=json.loads((p/'.opencode/opencode.json').read_text())
        self.assertEqual(config['default_agent'],'Arbiter')
        self.assertEqual(config['agents']['Arbiter']['model'],'openai/gpt-6.1-sol')
        self.assertIn('mode: primary',(p/'.opencode/agents/Arbiter.md').read_text())
        for role in ['SCV','probe','Overlord']:
            self.assertIn('mode: subagent',(p/f'.opencode/agents/{role}.md').read_text())
            self.assertTrue(config['agents'][role]['model'].startswith('lmstudio/'))
        self.assertTrue((p/'.opencode/scaffold.json').is_file())
    def test_publication_requires_coordinator_approval(self):
        config=json.loads((HERE/'files/.opencode/opencode.json').read_text())
        self.assertIn({'action':'shell','resource':'git push*','effect':'deny'},config['permissions'])
        def permissions(role):
            header=(HERE/f'files/.opencode/agents/{role}.md').read_text().removeprefix('---\n').split('\n---\n',1)[0]
            parsed=subprocess.check_output(['ruby','-ryaml','-rjson','-e','puts JSON.generate(YAML.safe_load(STDIN.read))'],input=header,text=True)
            return json.loads(parsed)['permissions']
        shell=[p for p in permissions('Arbiter') if p['action']=='shell']
        self.assertEqual([p for p in shell if p['effect']=='ask'],[{'action':'shell','resource':'git push*','effect':'ask'}])
        for resource in ['git push*--force*','git push -f*','git push* -f*','git push* +*','git push*--mirror*','git push*--delete*','git push* :*']:
            self.assertIn({'action':'shell','resource':resource,'effect':'deny'},shell)
        for role in ['SCV','probe','Overlord']:
            self.assertFalse(any(p['action']=='shell' for p in permissions(role)))

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
        p=self.root/'collision';p.mkdir();(p/'AGENTS.md').write_text('do not replace')
        r=self.run_tool('--here',cwd=p);self.assertNotEqual(r.returncode,0)
        self.assertEqual([x.name for x in p.iterdir()],['AGENTS.md'])
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
        data['version']='3.0.0';data['files']['.opencode/WORKFLOW.md']=hashlib.sha256(workflow.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(data))
        before=manifest.read_bytes()
        r=self.run_tool('--update',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(manifest.read_bytes(),before);self.assertEqual(workflow.read_text(),'old reviewed workflow\n')
        r=self.run_tool('--update','--apply',cwd=p);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(workflow.read_bytes(),(HERE/'files/.opencode/WORKFLOW.md').read_bytes())
        self.assertEqual(contract.read_text(),'project-owned custom commands\n')

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
        profile={'local_provider_ids':['lmstudio'],'models':{r:'lmstudio/test-local' for r in ['SCV','probe','Overlord']}}
        (p/'.opencode/local.json').write_text(json.dumps(profile))
        r=subprocess.run(args,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
        preview=json.loads(r.stdout)
        self.assertEqual(set(preview['runtime_config']['agents']),{'Arbiter','SCV','probe','Overlord','title','summary','compaction'})
        self.assertEqual(preview['runtime_config']['agents']['Arbiter']['model'],'openai/gpt-6.1-sol')
        self.assertTrue(all(a['model']=='lmstudio/test-local' for n,a in preview['runtime_config']['agents'].items() if n!='Arbiter'))
        self.assertIn('Codex intervention is optional',preview['argv'][-1])
        self.assertNotIn('--auto',preview['argv'])
        self.assertFalse((p/'.opencode/evidence').exists())
        r=subprocess.run(args+['--execute'],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0);self.assertIn('PROJECT.md',r.stderr)
        args[2]='Overlord'
        r=subprocess.run(args+['--session','old-session'],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0);self.assertIn('invalid choice',r.stderr)

    def test_worker_process_exit_and_lock_are_preserved_with_fake_cli(self):
        self.assertEqual(self.run_tool('dispatch','--root',str(self.root)).returncode,0)
        p=self.root/'dispatch';task=p/'task.md';task.write_text('Controlled fake dispatch')
        (p/'.opencode/PROJECT.md').write_text('Status: READY\nControlled fixture')
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

if __name__=='__main__': unittest.main()
