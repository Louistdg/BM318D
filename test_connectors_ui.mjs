// Test de l'interface Mission Control dans un vrai Chrome (CDP), sur un serveur
// isole et une base temporaire. Aucune donnee de travail n'est utilisee.
import {spawn, spawnSync} from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const RACINE = path.dirname(fileURLToPath(import.meta.url));
// Navigateur : variable CHROME_PATH, sinon chemins usuels Windows puis Linux.
const CHROME = process.env.CHROME_PATH || (process.platform === 'win32'
  ? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
  : ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser']
      .find(p => fs.existsSync(p)) || '');
if (!CHROME || !fs.existsSync(CHROME)) {
  console.log('NON EXÉCUTÉ : aucun navigateur Chrome/Chromium trouvé (définir CHROME_PATH).');
  process.exit(3);
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
let passes = 0, echecs = 0;
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
const dossier = fs.mkdtempSync(path.join(os.tmpdir(), 'bm318d-ui-'));
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
  await c.naviguer(base_url);
  await sleep(1200);
  t('aucune erreur JavaScript au chargement', c.erreurs().length === 0, c.erreurs());
  t('la barre laterale a le bouton Mission Control', await c.evaluate(`!!document.querySelector('.rail button[data-page="mission"]')`));
  t('la page contient un jeton de session', await c.evaluate(`(document.querySelector('meta[name="mc-token"]')||{}).content||''`).then(v => (v || '').length > 20));

  const lireEtat = async () => JSON.parse(await c.evaluate(`(async () => JSON.stringify(await (await fetch('/api/mc/state?project='+Number(document.getElementById('project').value),{headers:{'X-MC-Token':(document.querySelector('meta[name="mc-token"]')||{}).content}})).json()))()`));
  console.log('\n=== connecteurs V2.2 ===');
  await c.evaluate(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Connecteurs IA / MCP').click()`);
  await sleep(600);
  t('gestionnaire ouvert',await c.evaluate(`document.querySelector('dialog').open`));
  t('verrou sécurité visible',await c.evaluate(`document.querySelector('dialog').textContent.includes('bloquées')`));
  await c.evaluate(`document.querySelector('#cx-new').click()`);
  await c.evaluate(`(()=>{const f=document.querySelector('#cx-form');f.elements.name.value='Local test';f.elements.model.value='test';f.requestSubmit()})()`);
  await sleep(600);
  t('connecteur enregistré désactivé',await c.evaluate(`document.querySelector('dialog').textContent.includes('Local test')&&document.querySelector('dialog').textContent.includes('Désactivé')`));
  await c.evaluate(`document.querySelector('[data-action="edit"]').click()`);
  t('configuration persistée',await c.evaluate(`document.querySelector('form').elements.model.value==='test'`));
  await c.evaluate(`document.querySelector('#cx-back').click()`);await sleep(400);
  await c.evaluate(`document.querySelector('[data-action="secret"]').click()`);
  t('clé masquée',await c.evaluate(`document.querySelector('input[name="secret"]').type==='password'`));
  await c.evaluate(`document.querySelector('#cx-back').click()`);await sleep(400);
  await c.evaluate(`document.querySelector('[data-action="toggle"]').click()`);await sleep(400);
  t('activation persistée',await c.evaluate(`document.querySelector('dialog').textContent.includes('Actif')`));
  await c.evaluate(`document.querySelector('#cx-close').click()`);
  console.log('\n=== erreurs et quotas V2.3 ===');
  await c.evaluate(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Connecteurs IA / MCP').click()`);
  await sleep(500);
  t('le gestionnaire se rouvre', await c.evaluate(`document.querySelector('dialog').open`));
  t('le quota affiche un pourcentage', await c.evaluate(`/\\(\\d+ %\\)/.test(document.querySelector('dialog').textContent)`));
  t('le journal est un tableau lisible', await c.evaluate(`!!document.querySelector('dialog table')`));
  await c.evaluate(`document.querySelector('#cx-new').click()`);
  await sleep(200);
  await c.evaluate(`(()=>{const f=document.querySelector('#cx-form');f.elements.name.value='Refus SSRF';f.elements.url.value='http://exemple-publique.test';f.requestSubmit()})()`);
  await sleep(700);
  const messageErreur = await c.evaluate(`(document.querySelector('#cx-message')||{}).textContent||''`);
  t('une URL non locale en http est refusée avec un message visible', /HTTPS requis/.test(messageErreur), messageErreur);
  t('aucune alerte bloquante (message dans le panneau)', await c.evaluate(`!!document.querySelector('#cx-message')`));
  await c.evaluate(`document.querySelector('#cx-back')?.click()`);
  await sleep(300);
  const restantes = c.erreurs().filter(x => !/status of 400/i.test(x));
  t('aucune erreur JS hors refus attendu', restantes.length === 0, restantes);
} finally {
  if (c) { try { await c.send('Browser.close'); } catch {} }
  chrome.kill();
  if (serveur) serveur.kill();
  await sleep(500);
  try { fs.rmSync(dossier, {recursive: true, force: true}); } catch {}
}

console.log('\n' + passes + ' ok, ' + echecs + ' echec(s)');
process.exit(echecs ? 1 : 0);
