"""Windows -> WSL transport for the isolated Linux runner, never a shell."""
import json,os,subprocess,threading,time
from pathlib import Path
from mc_sandbox import Refus

def _linux_path(path):
    path=Path(path).resolve()
    if not path.drive or len(path.drive)!=2 or path.drive[1]!=':':raise Refus('Chemin WSL local requis')
    return '/mnt/'+path.drive[0].lower()+path.as_posix()[2:]

def executer(argv,cwd,delai=30,memoire_mo=1024,max_processus=8,cancel_event=None,*,_operation=None,_message=None):
    from mc_sandbox import valider_workspace_windows
    source=Path(cwd).absolute();valider_workspace_windows(source)
    translated=[]
    for value in argv:
        if isinstance(value,str) and Path(value).is_absolute():value=_linux_path(value)
        translated.append(value)
    payload=json.dumps({'argv':translated,'cwd':_linux_path(source),'delai':delai,
                        'memoire_mo':memoire_mo,'max_processus':max_processus,'operation':_operation,'message':_message},ensure_ascii=True).encode()+b'\n'
    exe=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/wsl.exe'
    broker=Path(__file__).resolve().with_name('mc_sandbox_linux.py')
    env={k:os.environ[k] for k in ('SystemRoot','WINDIR') if k in os.environ}
    distro=os.environ.get('MC_WSL_DISTRO','Ubuntu')
    user=os.environ.get('MC_WSL_USER','')
    identity=['--user',user] if user else []
    process=subprocess.Popen([str(exe),'--distribution',distro,*identity,'--exec','/usr/bin/python3','-I','-S',_linux_path(broker)],
                             stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    output=[];errors=[]
    def drain(stream,target):
        # Never let a malformed broker output allocate unbounded host memory.
        while True:
            block=stream.read(4096)
            if not block:break
            if sum(map(len,target))<65536:target.append(block)
    threads=[threading.Thread(target=drain,args=(process.stdout,output),daemon=True),threading.Thread(target=drain,args=(process.stderr,errors),daemon=True)]
    for thread in threads:thread.start()
    try:
        process.stdin.write(payload);process.stdin.flush()
        deadline=time.monotonic()+delai+45
        while process.poll() is None:
            if time.monotonic()>deadline or (cancel_event is not None and cancel_event.is_set()):
                process.stdin.close()  # EOF revokes broker lease and kills its namespace.
                break
            time.sleep(.025)
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:raise Refus('Le broker WSL ne confirme pas sa terminaison')
    finally:
        if not process.stdin.closed:process.stdin.close()
        if process.poll() is None:
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
        for thread in threads:thread.join(timeout=5)
        process.stdout.close();process.stderr.close()
    try:result=json.loads(b''.join(output))
    except ValueError:
        raw=b''.join(output)
        if b'\x00' in raw and 'WSL_E_DISTRO_NOT_FOUND' in raw.decode('utf-16-le','replace'):
            raise Refus('Distribution WSL indisponible : '+distro+' ; aucun repli non isolé') from None
        raise Refus('Broker WSL indisponible ou réponse invalide : aucune exécution non isolée') from None
    if 'sandbox_error' in result:raise Refus(result['sandbox_error'])
    result.setdefault('isolement',{})['transport']='wsl2'
    return result

def commit_git(cwd,message):
    return executer(['git'],cwd,delai=180,_operation='git_commit',_message=message)
