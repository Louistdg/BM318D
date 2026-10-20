"""Additive V2.2 connector registry. Untrusted tools are fail-closed."""
import asyncio
import uuid
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import http.client
import ipaddress
import socket
import sqlite3
import threading
import os
import secrets
from pathlib import Path
import mc_credentials

KINDS = ('ollama', 'openai', 'anthropic', 'gemini', 'mcp')
SECURITY = 'V2.1 : isolation réseau et secrets non démontrée ; exécution MCP et stdio bloquées'
LOCK = threading.RLock()

SCHEMA = '''
CREATE TABLE IF NOT EXISTS mc_connectors(
 id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id),
 credential_ref TEXT NOT NULL UNIQUE, name TEXT NOT NULL, kind TEXT NOT NULL, version TEXT NOT NULL DEFAULT '1',
 config TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'untested',
 calls_limit INTEGER NOT NULL DEFAULT 100, token_limit INTEGER NOT NULL DEFAULT 100000,
 calls_used INTEGER NOT NULL DEFAULT 0, tokens_reserved INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS mc_connector_agents(
 project_id INTEGER NOT NULL, agent_id INTEGER NOT NULL REFERENCES mc_agents(id),
 connector_id INTEGER NOT NULL REFERENCES mc_connectors(id), model TEXT NOT NULL DEFAULT '',
 tools TEXT NOT NULL DEFAULT '[]', priority INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(agent_id,connector_id));
CREATE TABLE IF NOT EXISTS mc_connector_calls(
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, connector_id INTEGER NOT NULL,
 agent_id INTEGER, operation TEXT NOT NULL, status TEXT NOT NULL,
 reserved_tokens INTEGER NOT NULL DEFAULT 0, duration_ms INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
'''

def migrate(c):
    c.executescript(SCHEMA)
    colonnes={r[1] for r in c.execute('PRAGMA table_info(mc_connector_calls)')}
    if 'error' not in colonnes:
        c.execute("ALTER TABLE mc_connector_calls ADD COLUMN error TEXT NOT NULL DEFAULT ''")
    # Reprise apres crash : un appel reste « running » alors que le processus a disparu.
    c.execute("UPDATE mc_connector_calls SET status='interrupted',error='interrompu par un redémarrage du serveur' WHERE status='running'")

def row(c, p, i):
    r = c.execute('SELECT * FROM mc_connectors WHERE project_id=? AND id=?', (p, int(i))).fetchone()
    if not r: raise ValueError('Connecteur introuvable')
    return dict(r)

def _adresses(hote):
    try:
        infos = socket.getaddrinfo(hote, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError('Hôte introuvable : ' + hote) from None
    return {ipaddress.ip_address(i[4][0]) for i in infos}

def _publique(adresse):
    return not (adresse.is_private or adresse.is_loopback or adresse.is_link_local
                or adresse.is_multicast or adresse.is_reserved or adresse.is_unspecified)

def endpoint(url, resoudre=True):
    """Valide une URL de base : schéma, forme, et cible réseau autorisée.

    Refuse les adresses privées, loopback (sauf boucle locale assumée), lien-local
    (169.254.0.0/16, métadonnées cloud), multicast et réservées. La résolution est
    refaite juste avant chaque appel pour limiter le rebinding DNS.
    """
    u = urllib.parse.urlsplit(url)
    if u.username or u.password or u.query or u.fragment or not u.hostname:
        raise ValueError('URL sans identifiants, paramètres ou fragment requise')
    local = u.hostname == 'localhost'
    try: local = local or ipaddress.ip_address(u.hostname).is_loopback
    except ValueError: pass
    if u.scheme != 'https' and not (u.scheme == 'http' and local):
        raise ValueError('HTTPS requis sauf boucle locale')
    if resoudre:
        adresses = _adresses(u.hostname)
        if not adresses:
            raise ValueError('Hôte sans adresse réseau')
        for adresse in adresses:
            if local:
                if not adresse.is_loopback:
                    raise ValueError('Adresse locale non loopback refusée : ' + str(adresse))
            elif not _publique(adresse):
                raise ValueError('Adresse réseau non publique refusée : ' + str(adresse))
    return url.rstrip('/')

def verifier_cible(url):
    """Validate once and return the exact IP set used by the HTTP connection."""
    base = endpoint(url, resoudre=False)
    parsed = urllib.parse.urlsplit(base)
    host = parsed.hostname
    if not host:
        raise ValueError('Hôte requis')
    local = host == 'localhost'
    try:
        local = local or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    addresses = _adresses(host)
    if not addresses:
        raise ValueError('Hôte sans adresse réseau')
    for address in addresses:
        if local:
            if not address.is_loopback:
                raise ValueError('Adresse locale non loopback refusée : ' + str(address))
        elif not _publique(address):
            raise ValueError('Adresse réseau non publique refusée : ' + str(address))
    return base, tuple(sorted(str(address) for address in addresses))


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, address, **kwargs):
        super().__init__(host, **kwargs)
        self._pinned_address = address

    def connect(self):
        self.sock = socket.create_connection((self._pinned_address, self.port), self.timeout,
                                             self.source_address)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, **kwargs):
        super().__init__(host, **kwargs)
        self._pinned_address = address

    def connect(self):
        sock = socket.create_connection((self._pinned_address, self.port), self.timeout,
                                        self.source_address)
        # Keep the original URL hostname for SNI and certificate hostname checks.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, address):
        super().__init__()
        self.address = address

    def http_open(self, request):
        return self.do_open(lambda host, **kwargs: _PinnedHTTPConnection(host, self.address, **kwargs), request)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, address):
        super().__init__()
        self.address = address

    def https_open(self, request):
        return self.do_open(lambda host, **kwargs: _PinnedHTTPSConnection(
            host, self.address, context=self._context, check_hostname=self._check_hostname, **kwargs), request)


def _opener_cible(url):
    base, addresses = verifier_cible(url)
    parsed = urllib.parse.urlsplit(base)
    address = addresses[0]
    handlers = [NoRedirect(), urllib.request.ProxyHandler({})]
    if parsed.scheme == 'https':
        handlers.append(_PinnedHTTPSHandler(address))
    else:
        handlers.append(_PinnedHTTPHandler(address))
    return base, urllib.request.build_opener(*handlers)

def validate(d):
    kind = d.get('kind')
    if kind not in KINDS: raise ValueError('Type de connecteur invalide')
    name = str(d.get('name', '')).strip()
    if not name or len(name) > 100: raise ValueError('Nom requis (100 caractères maximum)')
    cfg = d.get('config', {})
    allowed = {'url','model','timeout','max_tokens','network_allowed','transport','models_allowed'}
    if not isinstance(cfg, dict) or set(cfg) - allowed:
        raise ValueError('Configuration invalide : aucune clé ni en-tête libre accepté')
    cfg = dict(cfg)
    cfg['url'] = endpoint(str(cfg.get('url','')))
    cfg['timeout'] = max(1, min(300, int(cfg.get('timeout',30))))
    cfg['max_tokens'] = max(1, min(8192, int(cfg.get('max_tokens',600))))
    cfg['model'] = str(cfg.get('model',''))[:150]
    brut = cfg.get('models_allowed') or []
    if not isinstance(brut, list) or len(brut) > 50:
        raise ValueError('Liste de modeles invalide (50 maximum)')
    cfg['models_allowed'] = [str(m)[:150] for m in brut if str(m).strip()][:50]
    cfg['network_allowed'] = cfg.get('network_allowed') is True
    cfg['transport'] = str(cfg.get('transport','http'))
    if cfg['transport'] not in ('http','stdio'): raise ValueError('Transport invalide')
    return kind, name, cfg

def list_state(c,p):
    connectors=[]
    for r in c.execute('SELECT * FROM mc_connectors WHERE project_id=? ORDER BY id',(p,)):
        x=dict(r); x['config']=json.loads(x['config'])
        dernier=c.execute('SELECT status,duration_ms,error,created_at FROM mc_connector_calls WHERE connector_id=? ORDER BY id DESC LIMIT 1',(r['id'],)).fetchone()
        x['dernier']=dict(dernier) if dernier else None
        x['capabilities']=['tools_discovery','tools_locked'] if x['kind']=='mcp' else ['chat']
        x['alerte_quota']=bool(x['calls_limit']) and x['calls_used']*5 >= x['calls_limit']*4
        connectors.append(x)
    return {'connectors':connectors, 'assignments':[dict(r) for r in c.execute('SELECT * FROM mc_connector_agents WHERE project_id=?',(p,))],
            'calls':[dict(r) for r in c.execute('SELECT * FROM mc_connector_calls WHERE project_id=? ORDER BY id DESC LIMIT 100',(p,))],
            'security':SECURITY, 'agents':[dict(r) for r in c.execute('SELECT id,name FROM mc_agents WHERE project_id=?',(p,))]}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirection refusée')

class FournisseurErreur(ValueError):
    """Erreur fournisseur déjà expurgée : aucun corps de réponse, aucun secret."""

def request_json(url, body, headers, timeout):
    url, opener = _opener_cible(url)
    request=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json',**headers})
    try:
        with opener.open(request,timeout=timeout) as response:
            raw=response.read(2_000_001)
    except urllib.error.HTTPError as error:
        code=error.code
        error.close()
        raise FournisseurErreur('HTTP %d du fournisseur' % code) from None
    except socket.timeout:
        raise FournisseurErreur('Délai dépassé après %s s' % timeout) from None
    except urllib.error.URLError as error:
        if isinstance(getattr(error,'reason',None),socket.timeout):
            raise FournisseurErreur('Délai dépassé après %s s' % timeout) from None
        raise FournisseurErreur('Fournisseur injoignable') from None
    if len(raw)>2_000_000: raise FournisseurErreur('Réponse trop volumineuse')
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise FournisseurErreur('Réponse JSON invalide') from None

def _cle(r, obligatoire):
    """Le coffre n'est interrogé que si nécessaire : Ollama et un OpenAI local
    fonctionnent sans clé, et un coffre indisponible ne doit pas bloquer un
    fournisseur qui n'en a pas besoin."""
    try:
        return mc_credentials.get(r['credential_ref'])
    except ValueError as erreur:
        if obligatoire:
            raise FournisseurErreur(str(erreur)) from None
        return ''

def request_get(url, headers, timeout):
    """GET JSON vers un fournisseur, memes garde-fous que request_json."""
    url, opener = _opener_cible(url)
    requete=urllib.request.Request(url, headers=headers, method='GET')
    try:
        with opener.open(requete,timeout=timeout) as reponse:
            brut=reponse.read(2_000_001)
    except urllib.error.HTTPError as error:
        code=error.code
        error.close()
        raise FournisseurErreur('HTTP %d du fournisseur' % code) from None
    except socket.timeout:
        raise FournisseurErreur('Delai depasse apres %s s' % timeout) from None
    except urllib.error.URLError as error:
        if isinstance(getattr(error,'reason',None),socket.timeout):
            raise FournisseurErreur('Delai depasse apres %s s' % timeout) from None
        raise FournisseurErreur('Fournisseur injoignable') from None
    if len(brut)>2_000_000: raise FournisseurErreur('Reponse trop volumineuse')
    try:
        return json.loads(brut)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise FournisseurErreur('Reponse JSON invalide') from None


def provider(r, model, system, prompt):
    cfg=json.loads(r['config']); kind=r['kind']; base=cfg['url']; limit=cfg['max_tokens']
    if cfg.get('models_allowed') and model not in cfg['models_allowed']:
        raise FournisseurErreur('Modele desactive pour ce connecteur : '+str(model)[:80])
    secret=_cle(r, kind in ('anthropic','gemini')); headers={}
    messages=[{'role':'system','content':system},{'role':'user','content':prompt}]
    if kind=='ollama':
        body={'model':model,'messages':messages,'stream':False,'format':'json','think':False,'options':{'num_predict':limit}}
        url=base+'/api/chat'
    elif kind=='openai':
        if secret: headers['Authorization']='Bearer '+secret
        body={'model':model,'messages':messages,'max_tokens':limit,'stream':False}; url=base+'/chat/completions'
    elif kind=='anthropic':
        if not secret: raise ValueError('Clé absente')
        headers={'x-api-key':secret,'anthropic-version':'2023-06-01'}
        body={'model':model,'system':system,'messages':messages[1:],'max_tokens':limit}; url=base+'/messages'
    elif kind=='gemini':
        if not secret: raise ValueError('Clé absente')
        headers={'x-goog-api-key':secret}
        body={'systemInstruction':{'parts':[{'text':system}]},'contents':[{'role':'user','parts':[{'text':prompt}]}],
              'generationConfig':{'maxOutputTokens':limit,'responseMimeType':'application/json'}}
        url=base+'/models/'+urllib.parse.quote(model,safe='')+':generateContent'
    else: raise ValueError('Connecteur sans capacité chat')
    result=request_json(url,body,headers,cfg['timeout'])
    try:
        if kind=='ollama': text=result['message']['content']
        elif kind=='openai': text=result['choices'][0]['message']['content']
        elif kind=='anthropic': text=''.join(x.get('text','') for x in result['content'] if x.get('type')=='text')
        else: text=''.join(x.get('text','') for x in result['candidates'][0]['content']['parts'])
    except (KeyError,IndexError,TypeError):
        raise FournisseurErreur('Réponse fournisseur inattendue (champ manquant)') from None
    if not isinstance(text,str) or not text.strip():
        raise FournisseurErreur('Réponse fournisseur vide')
    return text.replace(secret,'[clé masquée]') if secret else text

MAX_OUTILS = 200
MAX_SCHEMA = 65536

def _outil(brut):
    nom = getattr(brut, 'name', None)
    if not isinstance(nom, str) or not nom or len(nom) > 200:
        raise ValueError('Outil MCP sans nom valide')
    description = getattr(brut, 'description', '') or ''
    if not isinstance(description, str) or len(description) > 4000:
        description = str(description)[:4000]
    schema = getattr(brut, 'input_schema', None)
    if not isinstance(schema, dict):
        raise ValueError('Schéma d’outil MCP invalide : ' + nom)
    texte = json.dumps(schema, ensure_ascii=False)
    if len(texte) > MAX_SCHEMA:
        raise ValueError('Schéma d’outil MCP trop volumineux : ' + nom)
    return {'name': nom, 'description': description, 'inputSchema': schema}

def _outils(resultats):
    liste = list(resultats)
    if len(liste) > MAX_OUTILS:
        raise ValueError('Trop d’outils MCP exposés (%d, maximum %d)' % (len(liste), MAX_OUTILS))
    return [_outil(x) for x in liste]

async def discover(r):
    # Official SDK; no subprocess transport, sampling callback or roots exposed.
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    import httpx2
    import httpcore2
    from httpcore2._backends.auto import AutoBackend
    cfg=json.loads(r['config'])
    if cfg['transport']!='http': raise ValueError(SECURITY)
    url, addresses = verifier_cible(cfg['url'])
    host_name=urllib.parse.urlsplit(url).hostname.casefold().rstrip('.')
    pinned_address=addresses[0]

    class PinnedNetworkBackend(AutoBackend):
        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            requested=host.decode('ascii') if isinstance(host,bytes) else str(host)
            if requested.casefold().rstrip('.')!=host_name:
                raise httpcore2.ConnectError('MCP attempted an unvalidated host')
            return await super().connect_tcp(pinned_address,port,timeout,local_address,socket_options)

        async def connect_unix_socket(self, *args, **kwargs):
            raise httpcore2.ConnectError('MCP Unix sockets are disabled')

    transport=httpx2.AsyncHTTPTransport(trust_env=False)
    pool=getattr(transport,'_pool',None)
    if pool is None or not hasattr(pool,'_network_backend'):
        raise ValueError('Transport HTTP ne permet pas le verrouillage DNS sécurisé')
    pool._network_backend=PinnedNetworkBackend()
    secret=mc_credentials.get(r['credential_ref'])
    headers={'Authorization':'Bearer '+secret} if secret else {}
    async with asyncio.timeout(cfg['timeout']):
        async with httpx2.AsyncClient(transport=transport,headers=headers,follow_redirects=False,trust_env=False,timeout=cfg['timeout']) as client:
            async with streamable_http_client(url,http_client=client) as (read,write):
                async with ClientSession(read,write,read_timeout_seconds=cfg['timeout']) as session:
                    await session.initialize()
                    result=await session.list_tools()
                    return _outils(result.tools)

def invoke(c,p,r,aid,operation,fn):
    # Reserve BEFORE I/O; crashes and ambiguous errors consume quota. Lifetime
    # counters cannot be reset by editing configuration or disabling a connector.
    cfg=json.loads(r['config']); reserved=cfg['max_tokens'] if operation=='chat' else 0
    with LOCK:
        if not r['enabled'] or not cfg['network_allowed']: raise ValueError('Connecteur désactivé ou réseau non autorisé')
        updated=c.execute('UPDATE mc_connectors SET calls_used=calls_used+1,tokens_reserved=tokens_reserved+? WHERE id=? AND calls_used<calls_limit AND tokens_reserved+?<=token_limit',(reserved,r['id'],reserved)).rowcount
        if not updated: raise ValueError('Quota épuisé')
        call=c.execute('INSERT INTO mc_connector_calls(project_id,connector_id,agent_id,operation,status,reserved_tokens) VALUES(?,?,?,?,?,?)',(p,r['id'],aid,operation,'running',reserved)).lastrowid
        try:
            ligne=c.execute('SELECT calls_used,calls_limit FROM mc_connectors WHERE id=?',(r['id'],)).fetchone()
            if ligne and ligne[1] and ligne[0]*5 >= ligne[1]*4:
                deja=c.execute("SELECT 1 FROM events WHERE project_id=? AND agent='Connecteurs' AND message LIKE ?",(p,'%quota%'+str(r['name'])[:60]+'%')).fetchone()
                if not deja:
                    c.execute('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(p,'Connecteurs','blocked','Quota a 80 % atteint pour '+str(r['name'])[:60]+' ('+str(ligne[0])+'/'+str(ligne[1])+' appels)'))
        except sqlite3.Error:
            pass  # le journal evenements n existe pas dans tous les schemas : l alerte ne doit pas bloquer l appel
        c.commit()
    start=time.monotonic()
    motif=''
    try:
        result=fn()
        status='ok'
    except Exception as error:
        status='failed'
        result=None
        motif=str(error)[:300] if isinstance(error,FournisseurErreur) else ('%s : %s' % (type(error).__name__, str(error)[:200]))
    with LOCK:
        c.execute('UPDATE mc_connector_calls SET status=?,duration_ms=?,error=? WHERE id=?',(status,int((time.monotonic()-start)*1000),motif,call))
        c.execute('UPDATE mc_connectors SET state=? WHERE id=?',('ready' if status=='ok' else 'error',r['id']))
        c.commit()
    if status!='ok':
        raise FournisseurErreur(motif or 'Appel fournisseur échoué (détails expurgés)')
    return result

def proposal(text):
    value=json.loads(text)
    if not isinstance(value,dict) or not isinstance(value.get('files'),list) or not value['files']:
        raise ValueError('Proposition fournisseur invalide')
    for entry in value['files']:
        if not isinstance(entry,dict) or not isinstance(entry.get('path'),str) or not isinstance(entry.get('content'),str):
            raise ValueError('Fichier fournisseur invalide')
    return value

def generate(c,p,aid,system,prompt):
    assigned=c.execute('SELECT a.*,r.kind FROM mc_connector_agents a JOIN mc_connectors r ON r.id=a.connector_id WHERE a.project_id=? AND a.agent_id=? AND r.kind!=? ORDER BY a.priority,a.connector_id',(p,aid,'mcp')).fetchall()
    if not assigned: return None
    motifs=[]
    for a in assigned:
        r=row(c,p,a['connector_id']); cfg=json.loads(r['config'])
        try:
            # Parse before success so invalid JSON can trigger an explicit fallback.
            return invoke(c,p,r,aid,'chat',lambda:proposal(provider(r,a['model'] or cfg['model'],system,prompt)))
        except ValueError as error:
            motifs.append('%s : %s' % (r['kind'], str(error)[:120]))
    raise ValueError('Aucun fournisseur attribué disponible — ' + '; '.join(motifs))

ACTIONS_ADMIN = {'save','secret','delete','toggle','assign','models','outils','export','import'}

def _jeton_admin():
    try:
        return (Path(__file__).resolve().parent/'logs'/'admin-token.txt').read_text(encoding='utf-8').strip()
    except OSError:
        return ''

def _admin_ok(d):
    """Contrôle administrateur, désactivé par défaut tant que MissionControl (Codex)
    ne le porte pas au niveau HTTP. Activer avec MC_CONNECTORS_REQUIRE_ADMIN=1."""
    if os.environ.get('MC_CONNECTORS_REQUIRE_ADMIN') != '1':
        return True
    attendu = _jeton_admin()
    return bool(attendu) and secrets.compare_digest(str(d.get('admin_token') or ''), attendu)

def dispatch(c,p,action,d):
    if action in ACTIONS_ADMIN and not _admin_ok(d):
        raise ValueError('Jeton administrateur requis pour modifier un connecteur')
    if action=='list': return list_state(c,p)
    if action=='export':
        liste=[]
        for r2 in c.execute('SELECT * FROM mc_connectors WHERE project_id=? ORDER BY id',(p,)):
            cfg=json.loads(r2['config'])
            liste.append({'name':r2['name'],'kind':r2['kind'],'config':cfg,
                          'enabled':bool(r2['enabled']),'calls_limit':r2['calls_limit'],
                          'token_limit':r2['token_limit']})
        return {'version':1,'connectors':liste}
    if action=='import':
        brut=d.get('connectors')
        if not isinstance(brut,list) or len(brut)>50: raise ValueError('Import invalide (50 connecteurs maximum)')
        importes=0
        for entree in brut:
            if not isinstance(entree,dict): raise ValueError('Entree d import invalide')
            kind,name,cfg=validate({'kind':entree.get('kind'),'name':entree.get('name'),'config':entree.get('config',{})})
            if c.execute('SELECT 1 FROM mc_connectors WHERE project_id=? AND name=?',(p,name)).fetchone(): continue
            c.execute('INSERT INTO mc_connectors(project_id,credential_ref,name,kind,config,enabled,calls_limit,token_limit) VALUES(?,?,?,?,?,?,?,?)',
                      (p,str(uuid.uuid4()),name,kind,json.dumps(cfg),int(entree.get('enabled') is True),
                       max(1,min(100000,int(entree.get('calls_limit',100)))),max(1,min(100000000,int(entree.get('token_limit',100000))))))
            importes+=1
        c.commit()
        return {'importes':importes}
    if action=='save':
        kind,name,cfg=validate(d); i=d.get('id')
        calls=int(d.get('calls_limit',100)); tokens=int(d.get('token_limit',100000))
        if not 1<=calls<=100000 or not 1<=tokens<=100000000: raise ValueError('Quotas invalides')
        if i:
            old=row(c,p,i)
            if kind!=old['kind']: raise ValueError('Le type est immuable')
            c.execute('UPDATE mc_connectors SET name=?,config=?,enabled=?,state=?,calls_limit=?,token_limit=? WHERE id=?',(name,json.dumps(cfg),int(d.get('enabled') is True),'untested',calls,tokens,i))
        else:
            i=c.execute('INSERT INTO mc_connectors(project_id,credential_ref,name,kind,config,enabled,calls_limit,token_limit) VALUES(?,?,?,?,?,?,?,?)',(p,uuid.uuid4().hex,name,kind,json.dumps(cfg),int(d.get('enabled') is True),calls,tokens)).lastrowid
        return {'id':int(i)}
    if action=='assign':
        aid=int(d['agent_id']); r=row(c,p,d['connector_id'])
        if not c.execute('SELECT 1 FROM mc_agents WHERE project_id=? AND id=?',(p,aid)).fetchone(): raise ValueError('Agent introuvable')
        tools=d.get('tools',[])
        if not isinstance(tools,list) or any(not isinstance(t,str) for t in tools): raise ValueError('Liste outils invalide')
        if d.get('remove'):
            c.execute('DELETE FROM mc_connector_agents WHERE agent_id=? AND connector_id=?',(aid,r['id']))
        else:
            c.execute('INSERT INTO mc_connector_agents(project_id,agent_id,connector_id,model,tools,priority) VALUES(?,?,?,?,?,?) ON CONFLICT(agent_id,connector_id) DO UPDATE SET model=excluded.model,tools=excluded.tools,priority=excluded.priority',(p,aid,r['id'],str(d.get('model',''))[:150],json.dumps(tools),int(d.get('priority',0))))
        return {}
    r=row(c,p,d['id'])
    if action=='secret':
        if d.get('clear'):
            mc_credentials.delete(r['credential_ref'])
        else:
            valeur=d.get('secret')
            if not isinstance(valeur,str) or not valeur.strip():
                raise ValueError('Clé vide refusée')
            mc_credentials.put(r['credential_ref'],valeur.strip())
        return {}
    if action=='delete':
        mc_credentials.delete(r['credential_ref'])
        c.execute('DELETE FROM mc_connector_agents WHERE connector_id=?',(r['id'],))
        c.execute('DELETE FROM mc_connectors WHERE id=?',(r['id'],))
        return {}
    if action=='toggle':
        c.execute('UPDATE mc_connectors SET enabled=? WHERE id=?',(int(d.get('enabled') is True),r['id'])); return {}
    if action=='call':
        # No tool annotations or user switch can override the V2.1 lock.
        c.execute('INSERT INTO mc_connector_calls(project_id,connector_id,agent_id,operation,status) VALUES(?,?,?,?,?)',(p,r['id'],None,'tool','denied'))
        c.commit()
        raise ValueError(SECURITY)
    if action=='models':
        cfg=json.loads(r['config'])
        if r['kind']=='ollama':
            url=cfg['url'].rstrip('/')+'/api/tags'
            donnees=request_get(url, {}, cfg['timeout'])
            liste=[m.get('name') for m in donnees.get('models',[]) if m.get('name')]
        elif r['kind']=='openai':
            url=cfg['url'].rstrip('/')+'/models'
            donnees=request_get(url, {'Authorization':'Bearer '+(_cle(r,False) or '')}, cfg['timeout'])
            liste=[m.get('id') for m in donnees.get('data',[]) if m.get('id')]
        else:
            raise ValueError('Ce fournisseur ne publie pas la liste de ses modeles : saisir le nom a la main')
        return {'models':sorted(set(liste))[:200]}
    if action=='outils':
        if r['kind']!='mcp': raise ValueError('La decouverte d outils concerne uniquement MCP')
        if d.get('approve_network') is not True: raise ValueError('Autorisation reseau explicite requise')
        return {'tools':invoke(c,p,r,None,'discover',lambda:asyncio.run(discover(r)))}
    if action=='test':
        if d.get('approve_network') is not True: raise ValueError('Autorisation réseau explicite requise')
        if r['kind']=='mcp': return {'tools':invoke(c,p,r,None,'discover',lambda:asyncio.run(discover(r)))}
        cfg=json.loads(r['config'])
        invoke(c,p,r,None,'chat',lambda:provider(r,cfg['model'],'Réponds en JSON.','Réponds {"ok":true}'))
        return {'tested':True}
    raise ValueError('Action connecteur inconnue')
