// Test de l'interface Mission Control dans un vrai Chrome (CDP), sur un serveur
// isole et une base temporaire. Aucune donnee de travail n'est utilisee.
import {spawn, spawnSync} from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';

import {fileURLToPath} from 'node:url';

const RACINE = process.env.MC_RACINE || path.dirname(fileURLToPath(import.meta.url));
const CHROME = process.env.CHROME_PATH || (process.platform === 'win32'
  ? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
  : ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser']
      .find(p => fs.existsSync(p)) || '');
const sleep = ms => new Promise(r => setTimeout(r, ms));
let passes = 0, echecs = 0;
let refus400Attendus = 0;
const aucuneErreurInattendue = c => c.erreurs().every(e => /status of 400/i.test(e)) &&
  c.events.filter(e => e.method === 'Log.entryAdded' && e.params.entry.level === 'error' && /status of 400/i.test(e.params.entry.text)).length === refus400Attendus;
const t = (nom, ok, detail) => {
  if (ok) { passes++; console.log('  ok    ' + nom); }
  else { echecs++; console.log('  ECHEC ' + nom + (detail !== undefined ? '  -> ' + JSON.stringify(detail).slice(0, 300) : '')); }
};

const portLibre = () => new Promise((res, rej) => {
  const s = net.createServer();
  s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); });
  s.on('error', rej);
});

// Petite requete HTTP : fetch garde des connexions ouvertes que le serveur
// Python ferme, ce qui fait tomber undici.
const httpGet = url => new Promise((res, rej) => {
  const r = http.get(url, {headers: {'Connection': 'close'}}, rep => {
    let corps = '';
    rep.on('data', c => corps += c);
    rep.on('end', () => res({status: rep.statusCode, body: corps}));
  });
  r.on('error', rej);
});

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.enAttente = new Map(); this.events = []; }
  static async connect(url) {
    const ws = new WebSocket(url);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const c = new CDP(ws);
    ws.onmessage = m => {
      const msg = JSON.parse(m.data);
      if (msg.id && c.enAttente.has(msg.id)) {
        const {res, rej} = c.enAttente.get(msg.id); c.enAttente.delete(msg.id);
        msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
      } else if (msg.method) c.events.push(msg);
    };
    return c;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => {
      this.enAttente.set(id, {res, rej});
      this.ws.send(JSON.stringify({id, method, params}));
    });
  }
  async evaluate(expression) {
    const r = await this.send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true, userGesture: true});
    if (r.exceptionDetails) return {__erreur: r.exceptionDetails.exception?.description || r.exceptionDetails.text};
    return r.result.value;
  }
  async naviguer(url) { this.events.length = 0; await this.send('Page.navigate', {url}); await sleep(2200); }
  erreurs() {
    const sortie = [];
    for (const e of this.events) {
      if (e.method === 'Runtime.exceptionThrown') sortie.push((e.params.exceptionDetails.exception?.description || e.params.exceptionDetails.text || '').split('\n')[0]);
      if (e.method === 'Log.entryAdded' && e.params.entry.level === 'error') sortie.push(e.params.entry.text);
    }
    return [...new Set(sortie)].filter(x => !/favicon|status of 404/i.test(x));
  }
}

// MC_UI_URL=http://127.0.0.1:31880/ : verification en lecture seule du serveur
// reel (aucune creation, aucun deplacement).
const URL_IMPOSEE = process.env.MC_UI_URL || '';
const LECTURE_SEULE = Boolean(URL_IMPOSEE);
const dossier = fs.mkdtempSync(path.join(os.tmpdir(), 'dioptre-ui-'));
const base = path.join(dossier, 'ui.sqlite3');
// Schema minimal + deux projets, comme une base de travail neuve.
if (!LECTURE_SEULE) {
  const prep = spawnSync('python', ['-c', `
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.executescript("""
CREATE TABLE projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE tasks(id INTEGER PRIMARY KEY, project_id INTEGER, title TEXT, priority TEXT, agent TEXT, status TEXT, created TEXT);
CREATE TABLE events(id INTEGER PRIMARY KEY, project_id INTEGER, created TEXT, agent TEXT, status TEXT, message TEXT);
INSERT INTO projects(id,name) VALUES(1,'Projet UI'),(2,'Second projet');
""")
c.commit(); c.close()
`, base], {encoding: 'utf8'});
  if (prep.status !== 0) { console.error(prep.stderr); process.exit(1); }
}
const port = await portLibre();
const portCDP = await portLibre();

const serveur = LECTURE_SEULE ? null : spawn('python', ['MissionControl.py'], {
  cwd: RACINE,
  env: {...process.env, MC_DB: base, MC_PORT: String(port), MC_RATE_LIMIT: '1000'},
  stdio: 'ignore'
});

const profil = path.join(dossier, 'chrome');
fs.mkdirSync(profil, {recursive: true});
const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  ...(process.platform === 'win32' ? [] : ['--no-sandbox', '--disable-dev-shm-usage']),
  '--remote-debugging-port=' + portCDP, '--user-data-dir=' + profil,
  '--window-size=1440,900', 'about:blank'
], {stdio: 'ignore'});

let c = null;
try {
  const base_url = LECTURE_SEULE ? URL_IMPOSEE : 'http://127.0.0.1:' + port + '/';
  let pret = false;
  for (let i = 0; i < 60; i++) {
    try { const r = await httpGet(base_url); if (r.status === 200) { pret = true; break; } } catch {}
    await sleep(250);
  }
  t('le serveur isole repond', pret, base_url);

  let wsUrl = null;
  for (let i = 0; i < 80 && !wsUrl; i++) {
    try {
      const reponse = await httpGet('http://127.0.0.1:' + portCDP + '/json/list');
      const liste = JSON.parse(reponse.body);
      const page = liste.find(x => x.type === 'page' && x.webSocketDebuggerUrl);
      if (page) wsUrl = page.webSocketDebuggerUrl;
    } catch {}
    if (!wsUrl) await sleep(250);
  }
  if (!wsUrl) throw new Error('Chrome CDP injoignable');
  c = await CDP.connect(wsUrl);
  await c.send('Page.enable'); await c.send('Runtime.enable'); await c.send('Log.enable');
  await c.send('Emulation.setDeviceMetricsOverride', {width: 1440, height: 900, deviceScaleFactor: 1, mobile: false});

  console.log('\n=== chargement ===');
  const fixtureAdmin=fs.readFileSync(path.join(path.dirname(base),'logs','admin-token.txt'),'utf8').trim();
  await c.send('Page.addScriptToEvaluateOnNewDocument',{source:`window.mcJetonAdmin=${JSON.stringify(fixtureAdmin)}`});
  await c.naviguer(base_url);
  await sleep(1200);
  t('aucune erreur JavaScript au chargement', c.erreurs().length === 0, c.erreurs());
  t('le canevas démarre avec un zoom plus rapproché', await c.evaluate(`document.getElementById('world').style.transform.includes('scale(1.15)')`));
  t('la palette bleu ardoise et accent ciel est appliquée', await c.evaluate(`getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()==='#0c1420' && getComputedStyle(document.documentElement).getPropertyValue('--violet').trim()==='#82cfff'`));
  await c.evaluate(`document.querySelector('.legacy-nav[data-page=\"overview\"]').click()`); await sleep(300);
  t('la vue d’ensemble ne fabrique pas d’agents', await c.evaluate(`!/IA 1|Architecture|Développement|Audit/.test(document.getElementById('agentCards').textContent)`));
  await c.evaluate(`document.querySelector('.legacy-nav[data-page=\"canvas\"]').click()`);
  t('la barre laterale a le bouton Mission Control', await c.evaluate(`!!document.querySelector('.rail button[data-page="mission"]')`));
  t('le logo DIOPTRE affiche son monogramme vectoriel accessible', await c.evaluate(`document.querySelector('.rail .logo[aria-label="Logo DIOPTRE"] .brand-mark path')!==null`));
  t('les icônes de navigation sont des pictogrammes cohérents en SVG', await c.evaluate(`document.querySelectorAll('.rail button[data-page] .icon-svg').length>=6 && document.querySelectorAll('.workspace-link .icon-svg').length===8`));
  t('la nouvelle navigation affiche le panneau projet et le rail compact', await c.evaluate(`!!document.querySelector('.workspace-sidebar') && !!document.querySelector('.workspace-grip') && document.querySelector('.rail').getBoundingClientRect().width < 80`));
  t('le canevas historique est l’accueil sans bouton Ancien tableau', await c.evaluate(`document.getElementById('canvas').classList.contains('active') && !document.getElementById('ancienTableau')`));
  t('le canevas vide propose un accueil utile dans le style de la maquette', await c.evaluate(`!!document.querySelector('.canvas-welcome') && document.querySelectorAll('.canvas-welcome-features>div').length===3`));
  await c.evaluate(`document.getElementById('emptyOverview').click()`); await sleep(100);
  t('le raccourci de l’accueil ouvre la vraie vue d’ensemble', await c.evaluate(`document.getElementById('overview').classList.contains('active')`));
  await c.evaluate(`document.querySelector('.workspace-link[data-workspace-page="canvas"]').click()`); await sleep(100);
  await c.evaluate(`document.getElementById('emptyNewTask').click()`); await sleep(80);
  t('le raccourci de l’accueil ouvre le vrai formulaire de tâche', await c.evaluate(`document.getElementById('modalback').classList.contains('open')`));
  await c.evaluate(`document.getElementById('cancel').click()`);
  await c.evaluate(`document.querySelector('.workspace-link[data-workspace-page="tasks"]').click()`); await sleep(100);
  t('la navigation ouvre les tâches et expose le choix actif aux lecteurs d’écran', await c.evaluate(`document.getElementById('tasks').classList.contains('active') && document.querySelector('.workspace-link[data-workspace-page="tasks"]').getAttribute('aria-current')==='page'`));
  await c.evaluate(`document.querySelector('.workspace-link[data-workspace-page="canvas"]').click()`); await sleep(100);
  const largeurAvant=await c.evaluate(`Number(document.getElementById('workspaceGrip').getAttribute('aria-valuenow'))`);
  await c.evaluate(`document.getElementById('workspaceGrip').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}))`);
  t('la largeur du panneau projet est ajustable au clavier', await c.evaluate(`Number(document.getElementById('workspaceGrip').getAttribute('aria-valuenow'))===${largeurAvant+16}`));
  await c.evaluate(`document.getElementById('sidebarToggle').click()`);
  t('le panneau projet peut être réduit', await c.evaluate(`document.body.classList.contains('sidebar-collapsed')`));
  await c.evaluate(`document.getElementById('sidebarToggle').click()`);
  t('le panneau projet peut être rouvert', await c.evaluate(`!document.body.classList.contains('sidebar-collapsed')`));
  t('la page contient un jeton de session', await c.evaluate(`(document.querySelector('meta[name="mc-token"]')||{}).content||''`).then(v => (v || '').length > 20));

  const lireEtat = async () => JSON.parse(await c.evaluate(`(async () => JSON.stringify(await (await fetch('/api/mc/state?project='+Number(document.getElementById('project').value),{headers:{'X-MC-Token':(document.querySelector('meta[name="mc-token"]')||{}).content}})).json()))()`));
  console.log('\n=== ouverture de Mission Control ===');
  await c.evaluate(`document.querySelector('.rail button[data-page="mission"]').click()`);
  await sleep(1500);
  t('la section Mission Control est active', await c.evaluate(`document.getElementById('mission').classList.contains('active')`));
  t('l\'etat vide invite a creer un agent', await c.evaluate(`(document.getElementById('mcNodes').innerText||'').includes('équipe est vide')`));

  if (LECTURE_SEULE) {
    console.log('\n  (mode lecture seule : creation, deplacement et transfert non testes)');
  } else {
  console.log('\n=== creation d\'un agent par le formulaire ===');
  await c.evaluate(`document.getElementById('mcAdd').click()`);
  await sleep(500);
  t('la modale s\'ouvre', await c.evaluate(`document.getElementById('modalback').classList.contains('open')`));
  const cree = await c.evaluate(`(() => {
    document.getElementById('mcName').value = 'Chef test';
    document.getElementById('mcRole').value = 'manager';
    document.getElementById('mcTeam').value = 'Direction';
    document.getElementById('submit').click();
    return true;
  })()`);
  await sleep(1800);
  const noeuds = await c.evaluate(`document.querySelectorAll('.mc-node').length`);
  t('le noeud de l\'agent apparait sur le canvas', noeuds === 1, noeuds);

  console.log('\n=== deplacement d\'une carte ===');
  const avant = await c.evaluate(`(() => { const n=document.querySelector('.mc-node'); const r=n.getBoundingClientRect(); return {x:Math.round(r.x),y:Math.round(r.y),left:parseInt(n.style.left),top:parseInt(n.style.top)}; })()`);
  const cx = avant.x + 60, cy = avant.y + 40;
  await c.send('Input.dispatchMouseEvent', {type: 'mousePressed', x: cx, y: cy, button: 'left', clickCount: 1});
  await sleep(120);
  for (let i = 1; i <= 6; i++) {
    await c.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: cx + i * 20, y: cy + i * 12, button: 'left', buttons: 1});
    await sleep(60);
  }
  await c.send('Input.dispatchMouseEvent', {type: 'mouseReleased', x: cx + 120, y: cy + 72, button: 'left', clickCount: 1});
  await sleep(1200);
  const apres = await c.evaluate(`(() => { const n=document.querySelector('.mc-node'); return {left:parseInt(n.style.left),top:parseInt(n.style.top)}; })()`);
  t('le glisser a deplace la carte', apres.left !== avant.left || apres.top !== avant.top, {avant, apres});

  await c.naviguer(base_url);
  await c.evaluate(`document.querySelector('.rail button[data-page="mission"]').click()`);
  await sleep(1600);
  const apresRechargement = await c.evaluate(`(() => { const n=document.querySelector('.mc-node'); return n ? {left:parseInt(n.style.left),top:parseInt(n.style.top)} : null; })()`);
  t('la position survit au rechargement', apresRechargement && apresRechargement.left === apres.left && apresRechargement.top === apres.top, {apres, apresRechargement});

  console.log('\n=== zoom et pan ===');
  const echelle0 = await c.evaluate(`document.getElementById('mcWorld').style.transform`);
  const zone = await c.evaluate(`(() => { const r=document.getElementById('mcStage').getBoundingClientRect(); return {x:r.x+200,y:r.y+200}; })()`);
  await c.send('Input.dispatchMouseEvent', {type: 'mouseWheel', x: zone.x, y: zone.y, deltaX: 0, deltaY: -240});
  await sleep(500);
  const echelle1 = await c.evaluate(`document.getElementById('mcWorld').style.transform`);
  t('la molette change le zoom', echelle1 !== echelle0, {echelle0, echelle1});
  t('le zoom reste dans les bornes', await c.evaluate(`(() => { const m=document.getElementById('mcWorld').style.transform.match(/scale\\(([\\d.]+)\\)/); return m ? Number(m[1]) <= 2 && Number(m[1]) >= 0.4 : false; })()`));

  console.log('\n=== panneau de details ===');
  await c.evaluate(`document.querySelector('.mc-node').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,clientX:0,clientY:0,pointerId:1}))`);
  await c.evaluate(`document.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,button:0}))`);
  await sleep(800);
  const panneau = await c.evaluate(`(() => { const p=document.getElementById('mcDetails'); return {visible:p.style.display!=='none', texte:(p.innerText||'').slice(0,120)}; })()`);
  t('le panneau de details s\'ouvre', panneau.visible, panneau);

  console.log('\n=== second agent et transfert ===');
  await c.evaluate(`document.getElementById('mcAdd').click()`);
  await sleep(400);
  await c.evaluate(`(() => {
    document.getElementById('mcName').value = 'Dev test';
    document.getElementById('mcRole').value = 'backend';
    document.getElementById('mcTeam').value = 'Backend';
    document.getElementById('submit').click();
  })()`);
  await sleep(1600);
  t('deux agents sont affiches', await c.evaluate(`document.querySelectorAll('.mc-node').length`) === 2);
  const transfert = await c.evaluate(`(async () => {
    const r = await fetch('/api/mc/state?project='+Number(document.getElementById('project').value)+'', {headers:{'X-MC-Token':(document.querySelector('meta[name="mc-token"]')||{}).content}});
    return r.ok;
  })()`);
  t('l\'etat est lisible avec le jeton de la page', transfert === true);

  }

  if (!LECTURE_SEULE) {
  console.log('\n=== job d\'execution par le formulaire ===');
  await c.evaluate(`document.getElementById('mcJob').click()`);
  await sleep(500);
  await c.evaluate(`(() => {
    document.getElementById('mcJobTitle').value = 'Job UI';
    document.getElementById('mcJobTask').value = 'Ecrire un fichier';
    document.getElementById('submit').click();
  })()`);
  await sleep(1500);
  await c.evaluate(`document.getElementById('mcSwitch').click()`);
  await sleep(800);
  const vue = await c.evaluate(`(() => { const t=document.getElementById('mcRecords').innerText||''; return {titre:t.includes("Jobs d'exécution"), boutons:[...document.querySelectorAll('[data-job]')].map(b=>b.textContent), journaux:document.querySelectorAll('#mcRecords details').length}; })()`);
  t('la liste des jobs s\'affiche', vue.titre === true, vue);
  t('un job cree propose « Démarrer »', vue.boutons.includes('Démarrer'), vue.boutons);
  t('le journal du job est consultable', vue.journaux >= 1, vue.journaux);

  console.log('\n=== zones d\'equipe ===');
  // Revenir au canvas : la vue « missions » masque le plateau.
  await c.evaluate(`document.getElementById('mcSwitch').click()`);
  await sleep(900);
  const zones = await c.evaluate(`(() => [...document.querySelectorAll('.mc-zone')].map(z => ({team:z.dataset.team, w:Math.round(z.getBoundingClientRect().width)})))()`);
  t('chaque equipe a sa zone sur le canvas', zones.length >= 2, zones);
  t('la zone porte le nom de l\'equipe', zones.every(z => typeof z.team === 'string' && z.team.length > 0), zones);
  t('la minimap est affichee', await c.evaluate(`!!document.getElementById('mcMinimapCanvas')`));

  console.log('\n=== deplacer un agent dans une autre equipe ===');
  const cible = await c.evaluate(`(() => {
    const zones=[...document.querySelectorAll('.mc-zone')];
    const node=[...document.querySelectorAll('.mc-node')].find(x=>x.textContent.includes('Chef test'));
    const nr=node.getBoundingClientRect();
    const autre=zones.find(z=>z.dataset.team!=='Direction');
    const r=autre.getBoundingClientRect();
    return {depart:{x:Math.round(nr.x+30),y:Math.round(nr.y+30)}, arrivee:{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}, equipe:autre.dataset.team, id:Number(node.dataset.id)};
  })()`);
  await c.send('Input.dispatchMouseEvent', {type:'mousePressed', x:cible.depart.x, y:cible.depart.y, button:'left', clickCount:1});
  await sleep(120);
  for (let i=1;i<=5;i++){
    await c.send('Input.dispatchMouseEvent', {type:'mouseMoved', x:cible.depart.x+(cible.arrivee.x-cible.depart.x)*i/5, y:cible.depart.y+(cible.arrivee.y-cible.depart.y)*i/5, button:'left', buttons:1});
    await sleep(60);
  }
  await c.send('Input.dispatchMouseEvent', {type:'mouseReleased', x:cible.arrivee.x, y:cible.arrivee.y, button:'left', clickCount:1});
  await sleep(1600);
  const equipeApres = await c.evaluate(`(async () => (await (await fetch('/api/mc/state?project='+Number(document.getElementById('project').value)+'',{headers:{'X-MC-Token':(document.querySelector('meta[name="mc-token"]')||{}).content}})).json()).agents.find(a=>a.id===${cible.id}).team)()`);
  const diagnostic = await c.evaluate(`(() => {
    const X=${cible.arrivee.x}, Y=${cible.arrivee.y};
    const zones=[...document.querySelectorAll('.mc-zone')].map(z=>{const r=z.getBoundingClientRect();return {t:z.dataset.team,x:r.x,y:r.y,w:r.width,h:r.height}});
    const dedans=zones.filter(z=>X>=z.x&&X<=z.x+z.w&&Y>=z.y&&Y<=z.y+z.h).map(z=>z.t);
    return {dedans, zones};
  })()`);
  t('deposer la carte dans une zone change l\'equipe', equipeApres === cible.equipe, {attendu:cible.equipe, obtenu:equipeApres, diagnostic});

  console.log('\n=== selection multiple ===');
  // Un clic dans le vide remet la sélection à zéro.
  await c.evaluate(`document.getElementById('mcStage').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,pointerId:1}))`);
  await sleep(200);
  const selection = await c.evaluate(`(() => {
    const noeuds=[...document.querySelectorAll('.mc-node')].slice(0,2);
    const etapes=[];
    for(const n of noeuds){
      n.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,shiftKey:true,pointerId:1}));
      etapes.push(document.querySelectorAll('.mc-node.selectionne').length);
    }
    return {selection:document.querySelectorAll('.mc-node.selectionne').length, noeuds:noeuds.length, ids:noeuds.map(n=>n.dataset.id), etapes};
  })()`);
  t('deux cartes peuvent etre selectionnees', selection.selection === 2, selection);

  console.log('\n=== deplacement groupe ===');
  const avantGroupe = await c.evaluate(`(async () => (await (await fetch('/api/mc/state?project='+Number(document.getElementById('project').value)+'',{headers:{'X-MC-Token':(document.querySelector('meta[name="mc-token"]')||{}).content}})).json()).agents.map(a=>a.x+','+a.y).join('|'))()`);
  const depart = await c.evaluate(`(() => { const r=document.querySelectorAll('.mc-node')[0].getBoundingClientRect(); return {x:Math.round(r.x+30),y:Math.round(r.y+30)}; })()`);
  await c.send('Input.dispatchMouseEvent', {type:'mousePressed', x:depart.x, y:depart.y, button:'left', clickCount:1});
  await sleep(120);
  for (let i=1;i<=4;i++){ await c.send('Input.dispatchMouseEvent', {type:'mouseMoved', x:depart.x+i*12, y:depart.y+i*9, button:'left', buttons:1}); await sleep(60); }
  await c.send('Input.dispatchMouseEvent', {type:'mouseReleased', x:depart.x+48, y:depart.y+36, button:'left', clickCount:1});
  await sleep(1500);
  const apresGroupe = await c.evaluate(`(async () => (await (await fetch('/api/mc/state?project='+Number(document.getElementById('project').value)+'',{headers:{'X-MC-Token':(document.querySelector('meta[name="mc-token"]')||{}).content}})).json()).agents.map(a=>a.x+','+a.y).join('|'))()`);
  t('les deux cartes selectionnees bougent ensemble', avantGroupe !== apresGroupe, {avantGroupe, apresGroupe});

  console.log('\n=== alignement ===');
  const avantAlign = await c.evaluate(`(await (await fetch('/api/mc/state?project='+Number(document.getElementById('project').value)+'',{headers:{'X-MC-Token':(document.querySelector('meta[name="mc-token"]')||{}).content}})).json()).agents.map(a=>a.x+','+a.y).join('|')`);
  await c.evaluate(`document.getElementById('mcAligner').click()`);
  await sleep(1800);
  const apresAlign = await c.evaluate(`(await (await fetch('/api/mc/state?project='+Number(document.getElementById('project').value)+'',{headers:{'X-MC-Token':(document.querySelector('meta[name="mc-token"]')||{}).content}})).json()).agents.map(a=>a.x+','+a.y).join('|')`);
  t('le bouton Aligner deplace les cartes', avantAlign !== apresAlign, {avantAlign, apresAlign});

  console.log('\n=== plan (formulaire) ===');
  await c.evaluate(`document.getElementById('mcPlan').click()`);
  await sleep(600);
  t('le formulaire de plan s\'ouvre', await c.evaluate(`document.getElementById('modalback').classList.contains('open') && !!document.getElementById('mcPlanObjective')`));
  const modelesDisponibles = await c.evaluate(`(async () => { const t=(document.querySelector('meta[name="mc-token"]')||{}).content; const r=await fetch('/api/mc/models',{headers:{'X-MC-Token':t}}); return ((await r.json()).models||[]).length; })()`);
  if (modelesDisponibles > 0) t('le formulaire propose les modeles installes', (await c.evaluate(`[...document.querySelectorAll('#mcPlanModel option')].length`)) >= 1);
  else console.log('  (aucun modele Ollama disponible : controle des modeles non execute)');
  await c.evaluate(`document.getElementById('cancel').click()`);
  await sleep(300);

  console.log('\n=== decision et message ===');
  await c.evaluate(`document.getElementById('mcDecision').click()`);
  await sleep(500);
  await c.evaluate(`(() => {
    document.getElementById('mcDecTitle').value = 'Choix du stockage';
    document.getElementById('mcDecBody').value = 'SQLite pour la base locale';
    document.getElementById('mcDecWhy').value = 'Pas de serveur a maintenir';
    document.getElementById('mcDecAlt').value = 'PostgreSQL, JSON';
    document.getElementById('submit').click();
  })()`);
  await sleep(1400);
  await c.evaluate(`document.getElementById('mcRefresh').click()`);
  await sleep(1200);
  await c.evaluate(`document.getElementById('mcSwitch').click()`);
  await sleep(900);
  t('la decision apparait dans les preuves',
    (await c.evaluate(`(document.getElementById('mcRecords').innerText||'').includes('Choix du stockage')`)) === true);

  const envoi = await c.evaluate(`(async () => {
    const t=(document.querySelector('meta[name="mc-token"]')||{}).content;
    const p=Number(document.getElementById('project').value);
    const r=await fetch('/api/mc/message',{method:'POST',headers:{'Content-Type':'application/json','X-MC-Token':t},body:JSON.stringify({project:p,from_agent:null,to_agent:1,body:'Message de test UI'})});
    return r.status;
  })()`);
  t('un message cible peut etre envoye', envoi === 201, envoi);
  await c.evaluate(`document.getElementById('mcRefresh').click()`);
  await sleep(1300);
  await c.evaluate(`document.getElementById('mcSwitch').click()`);
  await sleep(1100);
  await c.evaluate(`document.querySelector('.mc-node[data-id="1"]').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,pointerId:1}))`);
  await c.evaluate(`document.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,button:0,pointerId:1}))`);
  await sleep(900);
  const panneauMessages = await c.evaluate(`(() => { const p=document.getElementById('mcDetails'); return {texte:(p.innerText||''), boutons:p.querySelectorAll('[data-msg]').length}; })()`);
  t('le panneau affiche les messages non lus', /Messages non lus \(1\)/.test(panneauMessages.texte) && panneauMessages.boutons >= 1, panneauMessages.texte.slice(0, 160));
  await c.evaluate(`(() => { const b=document.querySelector('#mcDetails [data-msg]'); if(b) b.click(); })()`);
  await sleep(1600);
  await c.evaluate(`document.getElementById('mcRefresh').click()`);
  await sleep(1400);
  const titresPanneau = await c.evaluate(`(() => [...document.querySelectorAll('#mcDetails h4')].map(h => h.textContent))()`);
  const apresLecture = Array.isArray(titresPanneau) && titresPanneau.some(x => /Messages non lus \(0\)/.test(x));
  const diagLecture = await c.evaluate(`(async () => {
    const t=(document.querySelector('meta[name="mc-token"]')||{}).content;
    const p=Number(document.getElementById('project').value);
    const s=await (await fetch('/api/mc/state?project='+p,{headers:{'X-MC-Token':t}})).json();
    return {lus:(s.messages||[]).map(m=>m.read_at?1:0)};
  })()`);
  t('marquer lu retire le message des non-lus', apresLecture === true, {titresPanneau, diagLecture});

  console.log('\n=== revue, validation, commit (job approuve simule) ===');
  const graine = path.join(dossier, 'seed_job.py');
  fs.writeFileSync(graine, [
    'import sqlite3, sys',
    'c = sqlite3.connect(sys.argv[1])',
    'c.execute("UPDATE mc_jobs SET status=\'approved\', diff=?, evidence=? WHERE id=(SELECT max(id) FROM mc_jobs)",',
    '          ("+++ b/x.py\\n+print(1)\\n", \'{"command": "python -m unittest -v", "exit_code": 0}\'))',
    'c.commit(); c.close(); print("ok")'
  ].join('\n'), 'utf8');
  const graineRun = spawnSync('python', [graine, base], {encoding: 'utf8'});
  t('un job approuve peut etre simule', (graineRun.stdout || '').includes('ok'), graineRun.stderr);
  await c.evaluate(`document.getElementById('mcRefresh').click()`);
  await sleep(1300);
  for (let essai = 0; essai < 3; essai++) {
    if (await c.evaluate(`document.getElementById('mcRecords').style.display !== 'none'`)) break;
    await c.evaluate(`document.getElementById('mcSwitch').click()`);
    await sleep(800);
  }
  await sleep(500);
  const boutonsJob = await c.evaluate(`(() => [...document.querySelectorAll('[data-job]')].map(b => b.textContent))()`);
  t('les boutons de revue apparaissent', ['Audit sécu','Revue code','Revue tests (humaine)','Valider','Commit','Rapport'].every(x => boutonsJob.includes(x)), boutonsJob);

  await c.evaluate(`(() => { const s=document.getElementById('mcActeur'); if(s && s.options.length) s.value=s.options[0].value; })()`);
  await c.evaluate(`(() => { const b=[...document.querySelectorAll('[data-job]')].find(x=>x.textContent==='Audit sécu'); if(b) b.click(); })()`);
  await sleep(2200);
  const revues = await c.evaluate(`(async () => {
    const t=(document.querySelector('meta[name="mc-token"]')||{}).content;
    const p=Number(document.getElementById('project').value);
    const s=await (await fetch('/api/mc/state?project='+p,{headers:{'X-MC-Token':t}})).json();
    return (s.reviews||[]).length;
  })()`);
  t('l\'audit de securite enregistre une revue', revues >= 1, revues);

  await c.evaluate(`(() => { window.confirm=()=>true; const b=[...document.querySelectorAll('[data-job]')].find(x=>x.textContent==='Revue tests (humaine)'); if(b) b.click(); })()`);
  await sleep(900);
  await c.evaluate(`(() => { const b=[...document.querySelectorAll('[data-job]')].find(x=>x.textContent==='Valider'); if(b) b.click(); })()`);
  await sleep(2600);
  const statutJob = await c.evaluate(`(async () => {
    const t=(document.querySelector('meta[name="mc-token"]')||{}).content;
    const p=Number(document.getElementById('project').value);
    const s=await (await fetch('/api/mc/state?project='+p,{headers:{'X-MC-Token':t}})).json();
    return (s.jobs||[])[0].status;
  })()`);
  t('le bouton Valider refuse un job simulé sans source livrée', statutJob === 'approved', statutJob);
  refus400Attendus = c.events.filter(e => e.method === 'Log.entryAdded' && e.params.entry.level === 'error' && /status of 400/i.test(e.params.entry.text)).length;
  t('le refus de validation est visible comme HTTP 400', refus400Attendus === 1, refus400Attendus);

  console.log('\n=== roles, duplication, recrutement ===');
  await c.evaluate(`document.getElementById('mcRol').click()`);
  await sleep(500);
  await c.evaluate(`(() => {
    document.getElementById('mcRoleKey').value = 'devops';
    document.getElementById('mcRoleLabel').value = 'Ingenieur DevOps';
    document.getElementById('mcRoleDesc').value = 'CI et deploiement';
    document.getElementById('submit').click();
  })()`);
  await sleep(1300);
  const etatRoles = await lireEtat();
  t('un role personnalise est cree', (etatRoles.roles || []).some(r => r.key === 'devops'), (etatRoles.roles || []).map(r => r.key));

  await c.evaluate(`document.getElementById('mcSwitch').click()`);
  await sleep(900);
  await c.evaluate(`document.querySelector('.mc-node[data-id="1"]').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,pointerId:1}))`);
  await c.evaluate(`document.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,button:0,pointerId:1}))`);
  await sleep(800);
  const avantClone = (await lireEtat()).agents.length;
  await c.evaluate(`document.getElementById('mcClone').click()`);
  await sleep(1500);
  const apresClone = (await lireEtat()).agents.length;
  t('dupliquer cree un agent de plus', apresClone === avantClone + 1, {avantClone, apresClone});

  await c.evaluate(`document.getElementById('mcRecrute').click()`);
  await sleep(600);
  await c.evaluate(`(() => {
    document.getElementById('mcRecName').value = 'Testeur recrute';
    document.getElementById('mcRecRole').value = 'tester';
    document.getElementById('mcRecTeam').value = 'Qualite';
    document.getElementById('mcRecWhy').value = 'Renforcer les tests';
    document.getElementById('submit').click();
  })()`);
  await sleep(1300);
  const avecRecrue = await lireEtat();
  t('une demande de recrutement attend une validation', (avecRecrue.recruits || []).some(r => r.status === 'pending'));
  const avantRecrutement = avecRecrue.agents.length;
  for (let essai = 0; essai < 3; essai++) {
    if (await c.evaluate(`document.getElementById('mcRecords').style.display !== 'none'`)) break;
    await c.evaluate(`document.getElementById('mcSwitch').click()`);
    await sleep(800);
  }
  await c.evaluate(`document.getElementById('mcRefresh').click()`);
  await sleep(1200);
  const boutonAccepter = await c.evaluate(`!!document.querySelector('[data-recruit][data-decision="1"]')`);
  t('la demande apparait avec Accepter/Refuser', boutonAccepter === true);
  await c.evaluate(`(() => { const b=document.querySelector('[data-recruit][data-decision="1"]'); if(b) b.click(); })()`);
  await sleep(1600);
  const apresRecrutement = await lireEtat();
  t('accepter cree l\'agent recrute', apresRecrutement.agents.length === avantRecrutement + 1, {avantRecrutement, apres: apresRecrutement.agents.length});

  console.log('\n=== tableau de charge ===');
  await c.evaluate(`document.getElementById('mcCharge').click()`);
  await sleep(1200);
  const chargeVue = await c.evaluate(`(() => { return {tableau:/Dispo/.test(document.getElementById('modalFields').innerText||''), ouvert:document.getElementById('modalback').classList.contains('open'), titre:(document.getElementById('titre-fenetre')||{}).textContent, texte:(document.getElementById('modalFields').innerText||'').slice(0,160), annonce:(document.getElementById('annonce')||{}).textContent}; })()`);
  t('le tableau de charge s\'affiche', chargeVue.tableau === true, JSON.stringify(chargeVue));
  await c.evaluate(`document.getElementById('cancel').click()`);
  await sleep(300);

  console.log('\n=== recherche, reglages, sauvegardes ===');
  await c.evaluate(`(() => { const i=document.getElementById('mcRecherche'); i.value='Chef'; i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true})); })()`);
  await sleep(1300);
  const recherche = await c.evaluate(`(() => { const t=(document.getElementById('modalFields').innerText||''); const titre=(document.getElementById('modalTitle')||{}).textContent||''; return {ouverte:/Recherche/.test(titre), agents:/Agents/.test(t), titre, texte:t.slice(0,140)}; })()`);
  t('la recherche globale affiche des resultats', recherche.ouverte && recherche.agents, JSON.stringify(recherche));
  await c.evaluate(`document.getElementById('cancel').click()`);
  await sleep(300);

  await c.evaluate(`document.getElementById('mcReglages').click()`);
  await sleep(1100);
  t('la fenetre de reglages s\'ouvre', await c.evaluate(`!!document.getElementById('mcSetUrl')`));
  await c.evaluate(`document.getElementById('cancel').click()`);
  await sleep(300);

  await c.evaluate(`document.getElementById('mcSauvegardes').click()`);
  await sleep(1100);
  const sauvegardes = await c.evaluate(`(() => { const t=(document.getElementById('modalFields').innerText||''); return {liste:t.includes('.sqlite3')||t.includes('Aucune sauvegarde'), bouton:!!document.getElementById('mcBackupNow')}; })()`);
  t('la fenetre des sauvegardes s\'ouvre', sauvegardes.bouton === true, JSON.stringify(sauvegardes));
  await c.evaluate(`document.getElementById('cancel').click()`);
  await sleep(300);

  const badge = await c.evaluate(`(document.getElementById('mcNotif')||{}).textContent`);
  t('le bouton de notifications affiche un compteur', typeof badge === 'string' && badge.length > 0, badge);

  console.log('\n=== permissions par equipe ===');
  await c.evaluate(`document.getElementById('mcPerm').click()`);
  await sleep(1000);
  t('la fenetre des permissions s\'ouvre', (await c.evaluate(`document.querySelectorAll('[data-perm]').length`)) >= 3);
  await c.evaluate(`(() => { const b=document.querySelector('[data-perm="can_run_tests"]'); if(b) b.checked=false; })()`);
  await c.evaluate(`document.getElementById('submit').click()`);
  await sleep(1700);
  const perms = (await lireEtat()).permissions || [];
  t('les permissions sont enregistrees', perms.some(p => p.can_run_tests === false), perms);

  console.log('\n=== branches et competences ===');
  await c.evaluate(`document.getElementById('mcBranche').click()`);
  await sleep(600);
  await c.evaluate(`(() => {
    document.getElementById('mcBrName').value = 'api';
    document.getElementById('mcBrDesc').value = 'API et base';
    document.getElementById('submit').click();
  })()`);
  await sleep(1300);
  const branches = (await lireEtat()).branches || [];
  t('une branche est creee depuis l\'ecran', branches.some(b => b.name === 'api'), branches.map(b => b.name));
  await c.evaluate(`document.getElementById('mcJob').click()`);
  await sleep(600);
  t('le formulaire de job propose les branches', await c.evaluate(`!!document.getElementById('mcJobBranch')`));
  await c.evaluate(`document.getElementById('cancel').click()`);
  await sleep(300);
  await c.evaluate(`document.querySelector('.mc-node[data-id="1"]').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,pointerId:1}))`);
  await c.evaluate(`document.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,button:0,pointerId:1}))`);
  await sleep(800);
  t('le panneau propose les competences', await c.evaluate(`!!document.getElementById('mcEditSkills')`));
  }

  console.log('\n=== missions et preuves ===');
  let vueMissions = false;
  for (let essai = 0; essai < 3 && !vueMissions; essai++) {
    await c.evaluate(`document.getElementById('mcSwitch').click()`);
    await sleep(900);
    vueMissions = await c.evaluate(`document.getElementById('mcRecords').style.display !== 'none'`);
  }
  t('la vue missions s\'affiche', vueMissions === true);
  t('la vue missions liste les preuves', await c.evaluate(`/preuve/i.test(document.getElementById('mcRecords').innerText||'')`));

  console.log('\n=== changement de projet ===');
  const projets = await c.evaluate(`[...document.querySelectorAll('#project option')].map(o=>o.value)`);
  if (projets.length > 1) {
    await c.evaluate(`(() => { const s=document.getElementById('project'); s.value='${projets[projets.length - 1]}'; s.dispatchEvent(new Event('change')); })()`);
    await sleep(1200);
    t('le changement de projet ne casse pas la page', aucuneErreurInattendue(c), c.erreurs());
  } else {
    console.log('  (un seul projet dans la base isolee : changement non testable)');
  }

  console.log('\n=== navigation mobile ===');
  await c.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await c.evaluate(`document.getElementById('sidebarToggle').click()`); await sleep(220);
  t('le panneau projet s’ouvre depuis le bouton de navigation mobile', await c.evaluate(`document.body.classList.contains('sidebar-mobile-open')`));
  await c.evaluate(`document.querySelector('.workspace-link[data-workspace-page="overview"]').click()`); await sleep(120);
  t('la navigation mobile ouvre la vue demandée et replie le panneau', await c.evaluate(`document.getElementById('overview').classList.contains('active') && !document.body.classList.contains('sidebar-mobile-open')`));

  console.log('\n=== fin ===');
  t('aucune erreur JavaScript inattendue a la fin', aucuneErreurInattendue(c), c.erreurs());
} finally {
  if (c) { try { await Promise.race([c.send('Browser.close'), sleep(2000)]); } catch {} }
  chrome.kill();
  if (serveur) serveur.kill();
  await sleep(500);
  try { fs.rmSync(dossier, {recursive: true, force: true}); } catch {}
}

console.log('\n' + passes + ' ok, ' + echecs + ' echec(s)');
process.exit(echecs ? 1 : 0);
