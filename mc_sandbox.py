"""Explicit sandbox selection. WSL is a transport, bubblewrap+seccomp isolate.
No backend is allowed to fall back to unrestricted execution.
"""
import os
from pathlib import Path
RACINE=Path(__file__).resolve().parent
SANDBOX=Path(os.environ.get('MC_SANDBOX') or RACINE/'sandbox')
class Refus(ValueError):pass

def executer(argv,cwd,delai=30,memoire_mo=1024,max_processus=8,cancel_event=None):
    backend=os.environ.get('MC_SANDBOX_BACKEND') or ('wsl' if os.name=='nt' else 'linux')
    if backend=='windows' and os.name=='nt':
        raise Refus('Backend Windows natif expérimental non validé ; utiliser le backend WSL isolé')
    if backend=='linux' and os.name=='posix':
        import mc_sandbox_linux as linux
        return linux.executer(argv,cwd,delai,memoire_mo,max_processus,cancel_event)
    if backend=='wsl' and os.name=='nt':
        import mc_sandbox_wsl as wsl
        return wsl.executer(argv,cwd,delai,memoire_mo,max_processus,cancel_event)
    raise Refus('Backend de sandbox absent ou incompatible : exécution refusée')

def environnement(travail):
    # Kept as a public Windows helper; the actual child environment is tested.
    runtime=str(travail)
    result={'HOME':runtime,'TEMP':runtime,'TMP':runtime,'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'}
    if os.name=='nt':result.update(SystemRoot=os.environ.get('SystemRoot',r'C:\Windows'))
    return result

def commit_git(cwd,message):
    import mc_security
    identity=mc_security.current()
    if identity.kind not in ('admin','agent'):raise mc_security.Refus('Autorisation de commit requise')
    if identity.kind=='agent':
        import MissionControl as mc
        with mc.connect() as c:
            job=c.execute('SELECT id,project_id FROM mc_jobs WHERE workspace=?',(str(cwd),)).fetchone()
            if not job:raise mc_security.Refus('Workspace de job inconnu')
            mc_security.require(c,job['project_id'],'commit',job=job['id'])
    if os.name=='nt':
        import mc_sandbox_wsl
        return mc_sandbox_wsl.commit_git(cwd,message)
    import mc_sandbox_linux
    return mc_sandbox_linux.commit_git(cwd,message)

def valider_workspace_windows(root):
    import stat
    if os.name!='nt':raise Refus('Validation Windows appelée hors Windows')
    root=Path(root)
    def inspect(path):
        info=path.lstat()
        if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT or path.is_symlink():raise Refus('Lien/reparse point refusé dans le workspace')
        if stat.S_ISREG(info.st_mode) and info.st_nlink!=1:raise Refus('Lien physique refusé dans le workspace')
    inspect(root)
    for parent,dirs,files in os.walk(root,followlinks=False):
        for name in dirs+files:inspect(Path(parent)/name)
