"""Verified identities for HTTP and trusted broker calls; default is anonymous.

Agent identities are issued by an administrator, scoped to one project/agent,
action-limited, expire, and are revocable. Payload IDs never authenticate.
This is a broker boundary, not an isolation mechanism for code in this process.
"""
import contextlib,contextvars,dataclasses,hashlib,secrets,threading,time,weakref
from urllib.parse import urlsplit,parse_qs

class Refus(PermissionError):pass
_SEAL=object()
_CURRENT=contextvars.ContextVar('dioptre_principal',default=None)
_TOKENS={};_LOCK=threading.RLock()
_ISSUED=weakref.WeakValueDictionary()
_CONFIGURATION=None

def configure(session,admin):
    global _CONFIGURATION
    with _LOCK:
        if _CONFIGURATION is not None and _CONFIGURATION!=(session,admin):raise Refus('Autorité déjà configurée')
        _CONFIGURATION=(session,admin)

def _issued(principal):
    with _LOCK:_ISSUED[id(principal)]=principal
    return principal
AGENT_ACTIONS=frozenset(('read_context','job_create','job_run','job_control','approve','test','validate','commit','review','note','message'))
@dataclasses.dataclass(frozen=True)
class Principal:
    kind:str
    project:int|None=None
    agent:int|None=None
    actions:frozenset=frozenset()
    expires:float=float('inf')
    grant_id:str=''
    seal:object=dataclasses.field(default=None,repr=False,compare=False)

def operator(session,expected,admin='',expected_admin=''):
    if _CONFIGURATION is None:raise Refus('Autorité non configurée')
    expected,expected_admin=_CONFIGURATION
    if not isinstance(session,str) or not secrets.compare_digest(session,expected):raise Refus('Session non authentifiée')
    kind='operator'
    if admin:
        if not secrets.compare_digest(admin,expected_admin):raise Refus('Jeton administrateur invalide')
        kind='admin'
    return _issued(Principal(kind,seal=_SEAL))

def current():
    principal=_CURRENT.get()
    if not isinstance(principal,Principal) or principal.seal is not _SEAL or _ISSUED.get(id(principal)) is not principal:raise Refus('Identité vérifiée requise')
    if principal.expires<=time.monotonic():raise Refus('Identité expirée')
    if principal.kind=='agent':
        with _LOCK:
            if not any(p is principal for p in _TOKENS.values()):raise Refus('Identité révoquée')
    return principal

@contextlib.contextmanager
def use(principal):
    context=_CURRENT.set(principal)
    try:current();yield principal
    finally:_CURRENT.reset(context)

def issue(project,agent,actions,ttl=900):
    if current().kind!='admin':raise Refus('Jeton administrateur requis')
    if not isinstance(actions,list) or not actions or set(actions)-AGENT_ACTIONS:raise Refus('Autorisations agent invalides')
    if not 1<=ttl<=3600:raise Refus('Expiration entre 1 et 3600 secondes requise')
    token=secrets.token_urlsafe(32)
    principal=_issued(Principal('agent',int(project),int(agent),frozenset(actions),time.monotonic()+ttl,secrets.token_hex(12),_SEAL))
    with _LOCK:_TOKENS[hashlib.sha256(token.encode()).digest()]=principal
    return {'token':token,'grant_id':principal.grant_id,'expires_in':ttl}

def authenticate_agent(token):
    with _LOCK:principal=_TOKENS.get(hashlib.sha256(token.encode()).digest())
    with use(principal):return current()

def revoke(grant_id):
    if current().kind!='admin':raise Refus('Jeton administrateur requis')
    with _LOCK:
        for key,principal in list(_TOKENS.items()):
            if principal.grant_id==grant_id:del _TOKENS[key]

def require(c,p,action,data=None,job=None):
    principal=current();data=data or {}
    if principal.kind=='admin':return principal
    if principal.kind=='operator':
        if action in ('admin','approve','test','validate','commit'):raise Refus('Jeton administrateur requis pour cette action sensible')
        return principal
    if principal.kind!='agent' or principal.project!=int(p) or action not in principal.actions:raise Refus('Action ou projet non autorisé')
    agent=c.execute('SELECT project_id,team,status FROM mc_agents WHERE id=?',(principal.agent,)).fetchone()
    if not agent or agent['project_id']!=int(p) or agent['status']=='archived':raise Refus('Agent non actif dans ce projet')
    # Sender/actor fields cannot change an authenticated identity.
    for key in ('agent_id','from_agent','actor_id'):
        if data.get(key) not in (None,'') and int(data[key])!=principal.agent:raise Refus('Usurpation d’identité agent refusée')
    if job is not None:
        row=c.execute('SELECT project_id,agent_id FROM mc_jobs WHERE id=?',(int(job),)).fetchone()
        if not row or row['project_id']!=int(p) or row['agent_id']!=principal.agent:raise Refus('Job hors du périmètre de cet agent')
    permission={'approve':'can_approve_jobs','validate':'can_approve_jobs','commit':'can_approve_jobs','test':'can_run_tests'}.get(action)
    if permission:
        row=c.execute('SELECT '+permission+' FROM mc_team_permissions WHERE project_id=? AND team=?',(p,agent['team'])).fetchone()
        if not row or not row[0]:raise Refus('Permission équipe refusée')
    return principal

ROUTES={
 'agent':'manage','agent/update':'manage','agent/clone':'manage','agent/archive':'manage','link':'manage',
 'mission':'manage','assignment':'manage','assignment/update':'manage','decision':'manage','handoff/ack':'manage',
 'note':'note','message':'message','message/read':'manage','job':'job_create','job/run':'job_run',
 'job/pause':'job_control','job/resume':'job_control','job/cancel':'job_control','job/reject':'approve',
 'job/approve':'approve','job/test':'test','job/validate':'validate','job/commit':'commit','review':'review',
 'role':'admin','branch':'manage','branch/update':'manage','recruit':'manage','recruit/decide':'admin',
 'permissions':'admin','settings':'admin','backup':'admin','restore':'admin','shutdown':'admin',
 'plan':'manage','plan/apply':'manage','orchestrator/run':'manage','charge':'manage',
 'security/token':'admin','security/revoke':'admin',
 'documents/save':'manage','documents/delete':'manage','documents/import':'manage',
 'corbeille/purge':'admin',
}

def authorize_route(c,path,d):
    suffix=path.removeprefix('/api/mc/')
    action=ROUTES.get(suffix)
    if suffix.startswith('connectors/'):
        action='read_context' if suffix=='connectors/list' else 'admin'
    if not action:raise Refus('Route non autorisée')
    p=int(d.get('project',0));principal=current()
    job=d.get('id') if suffix.startswith('job/') else d.get('job_id') if suffix=='review' else None
    require(c,p,action,d,job)
    if principal.kind=='agent':
        if suffix.startswith('connectors/'):raise Refus('Gestion des connecteurs réservée à l’opérateur')
        if suffix in ('note','message','job','review') and int(d.get('agent_id') or d.get('from_agent') or 0)!=principal.agent:
            raise Refus('Identité de l’agent authentifié requise')
        if suffix=='note' and d.get('scope')!='agent':raise Refus('Portée de note non autorisée')
    return action

def authorize_read(c,path):
    principal=current()
    if principal.kind in ('operator','admin'):return
    u=urlsplit(path);q=parse_qs(u.query)
    if u.path not in ('/api/mc/context','/api/mc/job','/api/mc/report'):raise Refus('Lecture agent non autorisée')
    p=int(q.get('project',['0'])[0]);job=None
    if u.path=='/api/mc/context':
        if int(q.get('agent',['0'])[0])!=principal.agent:raise Refus('Contexte d’un autre agent refusé')
    else:job=int(q.get('id' if u.path.endswith('/job') else 'job',['0'])[0])
    require(c,p,'read_context',job=job)
