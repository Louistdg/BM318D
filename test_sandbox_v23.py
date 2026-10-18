"""Real OS confinement tests, synthetic files only; works on Windows+WSL/Linux."""
import errno,json,os,socket,subprocess,sys,tempfile,threading,time,unittest,uuid
from pathlib import Path
import mc_sandbox

def linux_path(path):
    p=Path(path).resolve()
    if os.name=='nt':return '/mnt/'+p.drive[0].lower()+p.as_posix()[2:]
    return str(p)

class SandboxV23(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='bm318d-v23-')
        self.root=Path(self.tmp.name);self.workspace=self.root/'workspace';self.workspace.mkdir()
        self.outside=self.root/'outside-secret.txt';self.outside.write_text('synthetic-secret-only')
    def tearDown(self):self.tmp.cleanup()
    def run_code(self,code,**kw):
        result=mc_sandbox.executer([sys.executable,'-c',code],str(self.workspace),**kw)
        self.assertEqual(result['exit_code'],0,result)
        self.assertEqual(result['isolement']['backend'],'linux-bwrap-seccomp')
        return json.loads(result['stdout'])
    def test_01_outside_read_and_windows_mounts_denied(self):
        self.assertTrue(self.outside.is_file())
        code=f'''import json,pathlib
paths=[{linux_path(self.outside)!r},'/mnt/c','/mnt/d',{str(pathlib.Path.home())!r},'/run','/etc/passwd','/proc/1/root/mnt/c','/proc/self/root/mnt/d']
results=[]
for path in paths:
 try:
  value=pathlib.Path(path).read_bytes();results.append([path,False,0])
 except OSError as e:results.append([path,True,e.errno])
print(json.dumps(results))'''
        result=self.run_code(code)
        self.assertTrue(all(x[1] for x in result),result)
        self.assertEqual(self.outside.read_text(),'synthetic-secret-only')
    def test_02_actual_child_environment(self):
        os.environ['BM318D_V23_CANARY']='must-not-be-inherited'
        try:r=self.run_code('import os,json;print(json.dumps(dict(os.environ)))')
        finally:os.environ.pop('BM318D_V23_CANARY',None)
        self.assertEqual(r['HOME'],'/workspace');self.assertEqual(r['TEMP'],r['HOME'])
        self.assertEqual(r['PATH'],'/usr/bin:/bin')
        self.assertFalse(set(r)&{'BM318D_V23_CANARY','WSL_INTEROP','WSLENV','SSH_AUTH_SOCK','MC_TOKEN','MC_ADMIN_TOKEN'})
    def test_03_socket_families_blocked_at_os_level(self):
        code='''import socket,json
results=[]
for family in (socket.AF_INET,socket.AF_INET6,socket.AF_UNIX):
 try:socket.socket(family,socket.SOCK_STREAM);results.append(0)
 except OSError as error:results.append(error.errno)
print(json.dumps(results))'''
        self.assertEqual(self.run_code(code),[errno.EPERM]*3)
    def test_04_external_and_loopback_connect_syscalls_denied(self):
        code='''import ctypes,json
libc=ctypes.CDLL(None,use_errno=True)
# Invalid FD would ordinarily yield EBADF; the filter denies before routing.
results=[]
for address in ('127.0.0.1','198.51.100.1'):
 libc.syscall(42,-1,0,0);results.append(ctypes.get_errno())
print(json.dumps(results))'''
        self.assertEqual(self.run_code(code),[errno.EPERM]*2)
    def test_05_subprocesses_and_namespace_escape_blocked(self):
        code='''import os,subprocess,ctypes,json
results=[]
try:subprocess.run(['/usr/bin/python3','-c','print(1)']);results.append(0)
except OSError as e:results.append(e.errno)
libc=ctypes.CDLL(None,use_errno=True)
for nr in (57,58,272,308,165,310,438,425):
 libc.syscall(nr,0,0,0,0,0,0);results.append(ctypes.get_errno())
print(json.dumps(results))'''
        self.assertEqual(self.run_code(code),[errno.EPERM]*9)
    def test_06_threads_allowed(self):
        code='''import threading,json
x=[];t=threading.Thread(target=lambda:x.append(42));t.start();t.join();print(json.dumps(x))'''
        self.assertEqual(self.run_code(code),[42])
    def test_07_disposable_write_and_readonly_runtime(self):
        code='''import pathlib,json
pathlib.Path('/workspace/created.txt').write_text('temporary')
r=[]
for p in ('/outside.txt','/usr/created.txt'):
 try:pathlib.Path(p).write_text('escape');r.append(False)
 except OSError:r.append(True)
print(json.dumps(r))'''
        self.assertEqual(self.run_code(code),[True,True]);self.assertFalse((self.workspace/'created.txt').exists())
    def test_08_hardlinks_rejected(self):
        os.link(self.outside,self.workspace/'linked.txt')
        with self.assertRaises(ValueError):mc_sandbox.executer([sys.executable,'-c','print(1)'],str(self.workspace))
    def test_09_symlinks_or_junctions_rejected(self):
        target=self.root/'secret-dir';target.mkdir();(target/'secret').write_text('dummy')
        link=self.workspace/'escape'
        if os.name=='nt':
            r=subprocess.run(['cmd.exe','/c','mklink','/J',str(link),str(target)],capture_output=True)
            self.assertEqual(r.returncode,0,'Impossible de créer la jonction de test')
        else:os.symlink(target,link,target_is_directory=True)
        with self.assertRaises(ValueError):mc_sandbox.executer([sys.executable,'-c','print(1)'],str(self.workspace))
    def test_10_timeout_cleanup(self):
        start=time.monotonic()
        r=mc_sandbox.executer([sys.executable,'-c','import time;time.sleep(60)'],str(self.workspace),delai=.3)
        self.assertEqual(r['exit_code'],-1);self.assertEqual(r['timeout'],.3)
        self.assertLess(time.monotonic()-start,20)
    def test_11_cancellation(self):
        event=threading.Event();timer=threading.Timer(.3,event.set);timer.start()
        try:r=mc_sandbox.executer([sys.executable,'-c','import time;time.sleep(60)'],str(self.workspace),cancel_event=event)
        finally:timer.cancel()
        self.assertTrue(r['cancelled']);self.assertEqual(r['exit_code'],-1)
    def test_12_memory_limit(self):
        code='''import json
try:x=bytearray(800*1024*1024);r=False
except MemoryError:r=True
print(json.dumps(r))'''
        self.assertTrue(self.run_code(code,memoire_mo=128))
    def test_13_x32_syscall_bypass_kills_process(self):
        r=mc_sandbox.executer([sys.executable,'-c','import ctypes;ctypes.CDLL(None).syscall(0x40000029,2,1,0)'],str(self.workspace))
        self.assertEqual(r['exit_code'],128+31,r)  # bubblewrap propagates fatal signals as 128+signal
    def test_14_quotes_unicode_roundtrip(self):
        expected='test "quote" \\ path é\nnext'
        self.assertEqual(self.run_code('import json;print(json.dumps('+repr(expected)+'))'),expected)
    def test_15_parent_file_handle_not_inherited(self):
        with self.outside.open('rb') as stream:
            os.set_inheritable(stream.fileno(),True)
            result=self.run_code('''import pathlib,json
paths=[]
for p in pathlib.Path('/proc/self/fd').iterdir():
 try:paths.append(str(p.readlink()))
 except OSError:pass
print(json.dumps(paths))''')
        self.assertFalse(any('outside-secret' in p for p in result),result)
    def test_16_windows_interop_and_vault_unavailable(self):
        # No actual secret is read; only an ephemeral synthetic credential is created.
        ref=uuid.uuid4().hex
        if os.name=='nt':
            import mc_credentials
            mc_credentials.put(ref,'BM318d-v23-synthetic-canary')
        try:
            code='''import os,pathlib,ctypes,json
r={'windows_loader':hasattr(ctypes,'WinDLL'),'interop':pathlib.Path('/init').exists(),'windows_mount':pathlib.Path('/mnt/c').exists(),'credentials':pathlib.Path.home().joinpath('.ssh').exists()}
print(json.dumps(r))'''
            self.assertEqual(self.run_code(code),dict.fromkeys(('windows_loader','interop','windows_mount','credentials'),False))
            if os.name=='nt':self.assertEqual(mc_credentials.get(ref),'BM318d-v23-synthetic-canary')
        finally:
            if os.name=='nt':mc_credentials.delete(ref)

    def test_17_aggregate_workspace_quota(self):
        code='''import pathlib,json,errno
count=0
try:
 for i in range(80):
  pathlib.Path('/workspace/quota-'+str(i)).write_bytes(b'x'*1048576);count+=1
 result={'denied':False,'count':count}
except OSError as e:result={'denied':e.errno==errno.ENOSPC,'count':count}
print(json.dumps(result))'''
        result=self.run_code(code)
        self.assertTrue(result['denied'],result);self.assertLess(result['count'],80)
        self.assertEqual(list(self.workspace.iterdir()),[])
    def test_18_workspace_inode_quota(self):
        code='''import pathlib,json,errno
count=0
try:
 for i in range(10000):pathlib.Path('/workspace/inode-'+str(i)).touch();count+=1
 result={'denied':False,'count':count}
except OSError as e:result={'denied':e.errno==errno.ENOSPC,'count':count}
print(json.dumps(result))'''
        result=self.run_code(code);self.assertTrue(result['denied'],result);self.assertLess(result['count'],10000)
    def test_19_no_capabilities_inside_namespace(self):
        code='''import pathlib,json
status=pathlib.Path('/proc/self/status').read_text()
r={k:int(next(line.split(':')[1].strip() for line in status.splitlines() if line.startswith(k+':')),16) for k in ('CapEff','CapPrm','CapAmb')}
print(json.dumps(r))'''
        self.assertEqual(self.run_code(code),dict.fromkeys(('CapEff','CapPrm','CapAmb'),0))
    def test_20_output_flood_is_terminated(self):
        result=mc_sandbox.executer([sys.executable,'-c','import os;[os.write(1,b"x"*4096) for _ in range(100000)]'],str(self.workspace),delai=10)
        self.assertNotEqual(result['exit_code'],0);self.assertLessEqual(len(result['stdout']),4000)
    def test_21_crash_stays_in_namespace(self):
        result=mc_sandbox.executer([sys.executable,'-c','import os;os.abort()'],str(self.workspace))
        self.assertEqual(result['exit_code'],128+6)
        self.assertEqual(list(self.workspace.iterdir()),[])

    def test_22_node_runtime_and_subprocess_denial(self):
        code="""const cp=require('child_process');let denied=false;try{cp.execFileSync('/usr/bin/true')}catch(e){denied=e.code==='EPERM'};console.log(JSON.stringify({denied,home:process.env.HOME,canary:process.env.MC_ADMIN_TOKEN||null}))"""
        result=mc_sandbox.executer(['node','-e',code],str(self.workspace))
        self.assertEqual(result['exit_code'],0,result)
        self.assertEqual(json.loads(result['stdout']),{'denied':True,'home':'/workspace','canary':None})

    def test_23_unknown_backend_fails_closed(self):
        previous=os.environ.get('MC_SANDBOX_BACKEND')
        os.environ['MC_SANDBOX_BACKEND']='unvalidated'
        try:
            with self.assertRaises(mc_sandbox.Refus):mc_sandbox.executer([sys.executable,'-c','print(1)'],str(self.workspace))
        finally:
            if previous is None:os.environ.pop('MC_SANDBOX_BACKEND',None)
            else:os.environ['MC_SANDBOX_BACKEND']=previous

    def test_24_git_persistent_history_and_disabled_hooks(self):
        if os.name=='nt':from mc_sandbox_wsl import commit_git
        else:from mc_sandbox_linux import commit_git
        (self.workspace/'file.txt').write_text('first')
        first=commit_git(str(self.workspace),'first')
        self.assertRegex(first['commit'],r'^[0-9a-f]{40,64}$')
        self.assertIsNone(commit_git(str(self.workspace),'unchanged')['commit'])
        hooks=self.workspace/'.git'/'hooks';hooks.mkdir(exist_ok=True)
        hook=hooks/'pre-commit';hook.write_text('#!/bin/sh\necho executed > /workspace/hook-executed\nexit 1\n');hook.chmod(0o755)
        (self.workspace/'file.txt').write_text('second')
        second=commit_git(str(self.workspace),'second')
        self.assertNotEqual(first['commit'],second['commit'])
        self.assertFalse((self.workspace/'hook-executed').exists())
        log=(self.workspace/'.git'/'logs'/'HEAD').read_text()
        self.assertIn(first['commit']+' '+second['commit'],log)
        self.assertEqual(self.outside.read_text(),'synthetic-secret-only')

    def test_25_git_external_filter_cannot_execute(self):
        if os.name=='nt':from mc_sandbox_wsl import commit_git
        else:from mc_sandbox_linux import commit_git
        (self.workspace/'file.txt').write_text('first');commit_git(str(self.workspace),'initial')
        config=self.workspace/'.git'/'config'
        with config.open('a') as f:f.write('\n[filter "hostile"]\n clean = /usr/bin/touch /workspace/filter-executed\n required = true\n')
        (self.workspace/'.gitattributes').write_text('*.txt filter=hostile\n')
        (self.workspace/'file.txt').write_text('changed')
        with self.assertRaises((mc_sandbox.Refus,ValueError)) as failure:commit_git(str(self.workspace),'blocked filter')
        self.assertRegex(str(failure.exception),r'(?i)fork|operation not permitted|permission denied')
        self.assertFalse((self.workspace/'filter-executed').exists())

    def test_26_abrupt_parent_death_removes_untrusted_process(self):
        # The host observer only returns PIDs whose -c argument exactly matches
        # this synthetic command. It never terminates unrelated Linux processes.
        code='import time;time.sleep(120) # bm318d-orphan-'+uuid.uuid4().hex
        observer="""import os,pathlib,sys,json
wanted=sys.argv[1].encode();found=[]
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit() or int(p.name)==os.getpid():continue
 try:
  args=(p/'cmdline').read_bytes().split(b'\\0')
  executable=os.path.realpath(p/'exe')
  if wanted in args and executable==os.path.realpath('/usr/bin/python3') and args[1:5]==[b'-I',b'-S',b'-B',b'-c']:found.append(int(p.name))
 except OSError:pass
print(json.dumps(found))"""
        def children():
            command=['/usr/bin/python3','-I','-S','-c',observer,code]
            if os.name=='nt':
                user=os.environ.get('MC_WSL_USER','')
                command=['wsl.exe','--distribution',os.environ.get('MC_WSL_DISTRO','Ubuntu'),*(['--user',user] if user else []),'--exec',*command]
            result=subprocess.run(command,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            return json.loads(result.stdout)
        wrapper='import mc_sandbox;mc_sandbox.executer('+repr([sys.executable,'-c',code])+','+repr(str(self.workspace))+',delai=120)'
        process=subprocess.Popen([sys.executable,'-c',wrapper],cwd=str(Path(__file__).parent),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+15;running=[]
            while time.monotonic()<deadline and process.poll() is None:
                running=children()
                if running:break
                time.sleep(.1)
            self.assertTrue(running,'Untrusted process must be observed alive before killing its parent')
            process.kill();process.wait(timeout=5)
            deadline=time.monotonic()+10
            while time.monotonic()<deadline and children():time.sleep(.1)
            self.assertEqual(children(),[],'Untrusted process survived abrupt parent death')
        finally:
            if process.poll() is None:process.kill()
            process.communicate(timeout=5)

if __name__=='__main__':unittest.main(verbosity=2)
