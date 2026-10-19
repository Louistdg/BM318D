"""Linux namespace sandbox. Only trusted OS runtime and /workspace are exposed.

Sockets and new processes are denied with seccomp; threads remain available.
The namespace contains no host /home, /mnt, /run, /etc or Windows interop.
"""
import ctypes,errno,json,os,platform,resource,shutil,signal,stat,struct,subprocess,sys,tempfile,threading,time
from pathlib import Path

class Refus(ValueError):pass
BWRAP='/usr/bin/bwrap'

def valider_arbre(root):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():raise Refus('Workspace invalide ou lien symbolique')
    count=0;size=0
    for parent,dirs,files in os.walk(root,followlinks=False):
        for name in dirs+files:
            path=Path(parent)/name;info=path.lstat();count+=1
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise Refus('Liens et fichiers spéciaux refusés')
            if stat.S_ISREG(info.st_mode):
                if info.st_nlink!=1:raise Refus('Liens physiques refusés')
                size+=info.st_size
            if count>10000 or size>64*1024*1024:raise Refus('Workspace trop volumineux')

def copie_sure(source,destination):
    """Open each directory/file without following links, including copy races."""
    count=0;total=0
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    root_fd=os.open('/',flags)
    try:
        for part in Path(source).absolute().parts[1:]:
            next_fd=os.open(part,flags,dir_fd=root_fd);os.close(root_fd);root_fd=next_fd
        def walk(fd,dest):
            nonlocal count,total
            dest.mkdir()
            with os.scandir(fd) as entries:
                for entry in entries:
                    if entry.name in ('.git','__pycache__') or entry.name.endswith('.pyc'):continue
                    count+=1
                    if count>10000:raise Refus('Workspace trop volumineux')
                    info=entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        child=os.open(entry.name,flags,dir_fd=fd)
                        try:walk(child,dest/entry.name)
                        finally:os.close(child)
                    elif stat.S_ISREG(info.st_mode):
                        child=os.open(entry.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                        try:
                            current=os.fstat(child)
                            if not stat.S_ISREG(current.st_mode) or current.st_nlink!=1:raise Refus('Fichier non régulier ou lié')
                            with os.fdopen(os.dup(child),'rb') as src,(dest/entry.name).open('xb') as dst:
                                while block:=src.read(65536):
                                    total+=len(block)
                                    if total>64*1024*1024:raise Refus('Workspace trop volumineux')
                                    dst.write(block)
                        finally:os.close(child)
                    else:raise Refus('Liens et fichiers spéciaux refusés')
        walk(root_fd,Path(destination))
    finally:os.close(root_fd)

def filtre_seccomp():
    if platform.machine()!='x86_64':raise Refus('Architecture seccomp non prise en charge')
    # struct sock_filter: code, jump_true, jump_false, constant.
    instructions=[]
    def bpf(code,jt,jf,k):instructions.append(struct.pack('HBBI',code,jt,jf,k))
    bpf(0x20,0,0,4)                   # audit architecture
    bpf(0x15,1,0,0xC000003E)
    bpf(0x06,0,0,0x80000000)         # kill process for another ABI
    bpf(0x20,0,0,0)                 # syscall number
    bpf(0x45,0,1,0x40000000)          # reject x32 ABI syscall-number bypass
    bpf(0x06,0,0,0x80000000)
    for nr in (41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,288,299,307,
               57,58,101,155,161,165,166,248,249,250,272,298,303,304,308,310,311,321,323,425,426,427,438):
        bpf(0x15,0,1,nr);bpf(0x06,0,0,0x50000|errno.EPERM)
    bpf(0x15,0,1,435);bpf(0x06,0,0,0x50000|errno.ENOSYS)  # clone3 -> libc fallback
    bpf(0x15,0,4,56)                 # clone: threads only
    bpf(0x20,0,0,16)                 # args[0] low word
    bpf(0x45,1,0,0x10000)            # CLONE_THREAD
    bpf(0x06,0,0,0x50000|errno.EPERM)
    bpf(0x06,0,0,0x7fff0000)
    bpf(0x06,0,0,0x7fff0000)
    return b''.join(instructions)

def _limits(memory,delay):
    resource.setrlimit(resource.RLIMIT_AS,(memory*1024*1024,)*2)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024*1024,)*2)
    resource.setrlimit(resource.RLIMIT_CPU,(max(1,int(delay)+1),)*2)
    resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))

def executer(argv,cwd,delai=30,memoire_mo=1024,max_processus=8,cancel_event=None,*,_git=False):
    if os.getuid()==0 or os.geteuid()==0:raise Refus('Courtier Linux root refusé : configurer un utilisateur Linux ordinaire')
    if not isinstance(argv,(tuple,list)) or not argv or any(not isinstance(a,str) or '\0' in a for a in argv):raise Refus('Arguments invalides')
    if not 0<delai<=300 or not 64<=memoire_mo<=4096 or not 1<=max_processus<=16:raise Refus('Limites invalides')
    if not Path(BWRAP).is_file():raise Refus('Bubblewrap absent : aucune exécution autorisée')
    source=Path(cwd).absolute();valider_arbre(source)
    name=Path(argv[0]).name.lower()
    if _git and name=='git':
        command=['/usr/bin/git'];runtime='git'
    elif name in ('python','python3','python3.14','python.exe','python315.exe') or name.startswith('python3.'):
        command=['/usr/bin/python3','-I','-S','-B'];runtime='python'
    elif name in ('node','node.exe'):
        command=['/usr/bin/node'];runtime='node'
    else:raise Refus('Runtime non approuvé')
    if not Path(command[0]).is_file():raise Refus('Runtime Linux absent')
    args=[]
    for a in argv[1:]:
        if Path(a).is_absolute():
            try:a='/workspace/'+str(Path(a).relative_to(source))
            except ValueError:pass
        args.append(a)
    start=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='dioptre-v23-') as directory:
        directory=Path(directory);copy=directory/'workspace'
        if not _git:
            copie_sure(source,copy)
            valider_arbre(copy)
        # No sockets, user configuration or writable host runtime is mounted.
        seccomp=directory/'seccomp.bpf';seccomp.write_bytes(filtre_seccomp())
        memory_workspace=directory/'memory-workspace';memory_workspace.mkdir()
        memory_tmp=directory/'memory-tmp';memory_tmp.mkdir()
        with seccomp.open('rb') as filter_file, (directory/'stdout').open('w+b') as out, (directory/'stderr').open('w+b') as err:
            cmd=[BWRAP,'--unshare-all','--die-with-parent','--new-session','--cap-drop','ALL','--clearenv',
                 '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
                 '--symlink','usr/bin','/bin','--proc','/proc','--dev','/dev','--bind',str(memory_tmp),'/tmp','--hostname','dioptre-sandbox',
                 '--bind',str(memory_workspace),'/workspace','--chdir','/workspace','--seccomp',str(filter_file.fileno())]
            env={'HOME':'/workspace','USERPROFILE':'/workspace','TEMP':'/workspace','TMP':'/workspace',
                 'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'}
            if _git:env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_SYSTEM='/dev/null',GIT_ATTR_NOSYSTEM='1',GIT_TERMINAL_PROMPT='0')
            for k,v in env.items():cmd.extend(['--setenv',k,v])
            cmd.extend(['--remount-ro','/dev','--remount-ro','/proc','--remount-ro','/','--',*command,*args])
            # preexec_fn is intentionally avoided: the WSL broker is threaded.
            # prlimit sets inherited hard limits before bubblewrap executes.
            request_file=directory/'prepare.json'
            request_file.write_text(json.dumps({'source':str(source if _git else copy),'workspace':str(memory_workspace),'tmp':str(memory_tmp),'command':cmd,'persistent_git':_git}),encoding='utf-8')
            setup=['/usr/bin/unshare','--user','--map-root-user','--mount','--propagation','private',
                   '/usr/bin/python3','-I','-S','-B',str(Path(__file__).resolve()),'--prepare',str(request_file)]
            cmd=['/usr/bin/prlimit','--as='+str(memoire_mo*1024*1024),'--core=0',
                 '--fsize='+str(8*1024*1024),'--cpu='+str(max(1,int(delai)+1)),'--nofile=128','--',*setup]
            process=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                                     env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},pass_fds=(filter_file.fileno(),),start_new_session=True)
            expired=False;cancelled=False;overflow=False
            try:
                deadline=time.monotonic()+delai
                while process.poll() is None:
                    expired=time.monotonic()>=deadline
                    cancelled=cancel_event is not None and cancel_event.is_set()
                    overflow=os.fstat(out.fileno()).st_size+os.fstat(err.fileno()).st_size>131072
                    if expired or cancelled or overflow:break
                    time.sleep(.025)
            finally:
                if process.poll() is None:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                process.wait(timeout=5)
            def tail(stream):stream.seek(max(0,os.fstat(stream.fileno()).st_size-4000));return stream.read(4000).decode('utf-8','replace')
            result={'exit_code':-1 if expired or cancelled or overflow else process.returncode,'timeout':delai if expired else None,
                    'cancelled':cancelled,'output_limit':overflow,'stdout':tail(out),'stderr':tail(err),
                    'duration_ms':int((time.monotonic()-start)*1000),'isolement':{'backend':'linux-bwrap-seccomp','namespace_mount':True,
                    'namespace_network':True,'namespace_pid':True,'seccomp':True,'sous_processus':'refusés, threads autorisés',
                    'environ_nettoye':True,'copie_jetable':None if _git else '/workspace','workspace_git_persistant':_git,'runtime':runtime,'memoire_max_mo':memoire_mo,'workspace_max_octets':None if _git else 64*1024*1024,'workspace_max_inodes':None if _git else 8192}}
            if process.returncode and ('bwrap:' in result['stderr'] or 'prlimit:' in result['stderr']):
                raise Refus('Configuration du confinement refusée : '+result['stderr'][-400:])
            return result

def commit_git(cwd,message,cancel_event=None):
    # Every Git process, including configuration handling, stays in the same
    # mount/network/seccomp boundary. Only its approved workspace persists.
    directory=Path(cwd).absolute();valider_arbre(directory)
    if (directory/'.git').exists() and not (directory/'.git').is_dir():raise Refus('Git externe/worktree lié refusé')
    flags=['-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false','-c','commit.gpgsign=false',
           '-c','gc.auto=0','-c','maintenance.auto=false','-c','init.templateDir=',
           '-c','user.email=dioptre@local','-c','user.name=DIOPTRE',
           '--git-dir=/workspace/.git','--work-tree=/workspace']
    def run(*arguments):
        result=executer(['git',*flags,*arguments],str(directory),cancel_event=cancel_event,_git=True)
        if result['exit_code']!=0:raise Refus('Commande Git isolée refusée ou en échec : '+result['stderr'][-300:])
        return result
    if not (directory/'.git').exists():run('init')
    run('add','-A')
    if not run('status','--porcelain')['stdout'].strip():return {'commit':None,'message':'Aucun changement à committer'}
    run('commit','-m',message[:200])
    commit=run('rev-parse','HEAD')['stdout'].strip()
    if len(commit) not in (40,64) or any(c not in '0123456789abcdef' for c in commit):raise Refus('Identifiant Git invalide')
    return {'commit':commit,'message':message[:200],'isolement':{'backend':'linux-bwrap-seccomp','workspace_git_persistant':True}}

def prepare_namespaces(request):
    # Runs as namespace-root mapped to the normal host user, before executing
    # any untrusted code. Mounts are private; all capabilities are then dropped.
    libc=ctypes.CDLL(None,use_errno=True)
    libc.mount.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_char_p,ctypes.c_ulong,ctypes.c_char_p]
    libc.mount.restype=ctypes.c_int
    mounts=[(request['tmp'],8388608,1024)]
    if not request.get('persistent_git'):mounts.append((request['workspace'],67108864,8192))
    for path,size,inodes in mounts:
        options=f'size={size},nr_inodes={inodes},mode=0700'.encode()
        if libc.mount(b'tmpfs',os.fsencode(path),b'tmpfs',2|4,options):
            raise OSError(ctypes.get_errno(),'Montage privé quota refusé')
    # copie_sure expects to create its destination; copy into a child directory
    # on the quota mount and bind that directory as /workspace.
    if request.get('persistent_git'):target=Path(request['source'])
    else:
        target=Path(request['workspace'])/'data'
        copie_sure(request['source'],target)
    command=request['command']
    index=command.index(request['workspace']);command[index]=str(target)
    os.execv(command[0],command)

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--prepare':
        prepare_namespaces(json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')))
        raise SystemExit(2)
    # Trusted WSL broker: one bounded JSON request, then EOF cancels execution.
    cancel=threading.Event()
    request=sys.stdin.buffer.readline(1_000_001)
    if len(request)>1_000_000 or not request.endswith(b'\n'):raise SystemExit(2)
    data=json.loads(request)
    def lease():
        sys.stdin.buffer.read(1);cancel.set()
    threading.Thread(target=lease,daemon=True).start()
    try:
        if data.get('operation')=='git_commit':result=commit_git(data['cwd'],data['message'],cancel)
        else:result=executer(data['argv'],data['cwd'],data['delai'],data['memoire_mo'],data['max_processus'],cancel)
        print(json.dumps(result,ensure_ascii=True),flush=True)
    except Exception as error:
        print(json.dumps({'sandbox_error':str(error)[:500]},ensure_ascii=True),flush=True)
        raise SystemExit(1)
