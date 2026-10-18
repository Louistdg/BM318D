// Test du chat de l'agent Ollama dans un vrai Chrome (CDP).
// Serveur isole, base temporaire, aucune reponse reseau reelle : window.api est remplace.
import {spawn, spawnSync} from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const RACINE = path.dirname(fileURLToPath(import.meta.url));
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
  else { echecs++; console.log('  ECHEC ' + nom + (detail !== undefined ? '  -> ' + JSON.stringify(detail).slice(0, 240) : '')); }
};

const portLibre = () => new Promise((res, rej) => {
  const s = net.createServer();
  s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); });
  s.on('error', rej);
});

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

const dossier = fs.mkdtempSync(path.join(os.tmpdir(), 'bm318d-chat-'));
const base = path.join(dossier, 'chat.sqlite3');
const prep = spawnSync('python', ['-c', `
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.executescript("""
CREATE TABLE projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE tasks(id INTEGER PRIMARY KEY, project_id INTEGER, title TEXT, priority TEXT, agent TEXT, status TEXT, created TEXT);
CREATE TABLE events(id INTEGER PRIMARY KEY, project_id INTEGER, created TEXT, agent TEXT, status TEXT, message TEXT);
INSERT INTO projects(id,name) VALUES(1,'Projet chat');
""")
c.commit(); c.close()
`, base], {encoding: 'utf8'});
if (prep.status !== 0) { console.error(prep.stderr); process.exit(1); }

const port = await portLibre();
const portCDP = await portLibre();
const serveur = spawn('python', ['MissionControl.py'], {
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
  const base_url = 'http://127.0.0.1:' + port + '/';
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
      const page = JSON.parse(reponse.body).find(x => x.type === 'page' && x.webSocketDebuggerUrl);
      if (page) wsUrl = page.webSocketDebuggerUrl;
    } catch {}
    if (!wsUrl) await sleep(250);
  }
  if (!wsUrl) throw new Error('Chrome CDP injoignable');
  c = await CDP.connect(wsUrl);
  await c.send('Page.enable'); await c.send('Runtime.enable'); await c.send('Log.enable');
  await c.send('Emulation.setDeviceMetricsOverride', {width: 1440, height: 900, deviceScaleFactor: 1, mobile: false});

  console.log('\n=== structure du chat ===');
  await c.naviguer(base_url);
  await c.evaluate(`document.querySelector('.rail button[data-page="agents"]').click()`);
  await sleep(700);
  t('aucune erreur JavaScript au chargement', c.erreurs().length === 0, c.erreurs());
  t('une zone de conversation existe', await c.evaluate(`!!document.getElementById('chatlog')`));
  t('un message d’accueil est present', await c.evaluate(`document.querySelectorAll('#chatlog .msg').length`) === 1);
  t('le champ est unique et en bas', await c.evaluate(`(() => {
    const z = document.getElementById('prompt').getBoundingClientRect();
    const m = document.querySelector('#chatlog .msg').getBoundingClientRect();
    return z.top > m.bottom && document.querySelectorAll('#prompt').length === 1;
  })()`));
  t('le bouton Envoyer est visible et dans la fenetre', await c.evaluate(`(() => {
    const b = document.getElementById('sendAI').getBoundingClientRect();
    return b.width > 40 && b.right < innerWidth && b.bottom <= innerHeight;
  })()`));
  t('l’ancien panneau deux colonnes a disparu', await c.evaluate(`!document.querySelector('.agentlayout')`));
  t('le texte d’aide mentionne Entree', await c.evaluate(`/Entr/.test(document.getElementById('prompt').placeholder)`));

  console.log('\n=== envoi d’un message (reponse simulee) ===');
  await c.evaluate(`(() => {
    window.__vraiFetch = window.__vraiFetch || window.fetch;
    window.fetch = (url, opts) => String(url).includes('/api/ollama')
      ? Promise.resolve(new Response(JSON.stringify({ok: true, answer: 'Reponse de test'}),
          {status: 200, headers: {'Content-Type': 'application/json'}}))
      : window.__vraiFetch(url, opts);
  })()`);
  const avant = await c.evaluate(`document.querySelectorAll('#chatlog .msg').length`);
  await c.evaluate(`(() => { const z = document.getElementById('prompt'); z.value = 'Bonjour'; document.getElementById('chatbar').requestSubmit(); })()`);
  await sleep(900);
  const apres = await c.evaluate(`document.querySelectorAll('#chatlog .msg').length`);
  t('le message et la reponse sont ajoutes', apres === avant + 2, {avant, apres});
  t('le message de l’utilisateur est a droite', await c.evaluate(`(() => {
    const msgs = [...document.querySelectorAll('#chatlog .msg')];
    const u = msgs[msgs.length - 2], r = msgs[msgs.length - 1];
    return u.classList.contains('user') && r.classList.contains('bot')
      && u.getBoundingClientRect().right > r.getBoundingClientRect().right;
  })()`));
  const dernierTexte = await c.evaluate(`[...document.querySelectorAll('#chatlog .msg')].pop().textContent`);
  const etatFetch = await c.evaluate(`String(window.fetch).slice(0, 40)`);
  t('la reponse affichee est celle du serveur', String(dernierTexte).includes('Reponse de test'), {dernierTexte, etatFetch});
  t('le champ est vide apres envoi', await c.evaluate(`document.getElementById('prompt').value`) === '');

  console.log('\n=== clavier ===');
  const avantEntree = await c.evaluate(`document.querySelectorAll('#chatlog .msg').length`);
  await c.evaluate(`(() => {
    const z = document.getElementById('prompt');
    z.value = 'Envoye par Entree';
    z.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));
  })()`);
  await sleep(900);
  t('Entree envoie le message', await c.evaluate(`document.querySelectorAll('#chatlog .msg').length`) === avantEntree + 2);
  const avantMaj = await c.evaluate(`document.querySelectorAll('#chatlog .msg').length`);
  await c.evaluate(`(() => {
    const z = document.getElementById('prompt');
    z.value = 'Ligne 1';
    z.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', shiftKey: true, bubbles: true, cancelable: true}));
  })()`);
  await sleep(600);
  t('Maj+Entree n’envoie pas', await c.evaluate(`document.querySelectorAll('#chatlog .msg').length`) === avantMaj);
  t('Maj+Entree laisse le texte dans le champ', await c.evaluate(`document.getElementById('prompt').value.includes('Ligne 1')`));

  console.log('\n=== panne d’Ollama ===');
  await c.evaluate(`(() => {
    window.fetch = (url, opts) => String(url).includes('/api/ollama')
      ? Promise.reject(new Error('<urlopen error [WinError 10061] Aucune connexion n’a pu etre etablie>'))
      : window.__vraiFetch(url, opts);
  })()`);
  await c.evaluate(`(() => { const z = document.getElementById('prompt'); z.value = 'Test panne'; document.getElementById('chatbar').requestSubmit(); })()`);
  await sleep(900);
  t('la panne affiche un message lisible', await c.evaluate(`[...document.querySelectorAll('#chatlog .msg')].pop().textContent.includes('Ollama ne repond pas')`));
  t('aucune erreur JavaScript non geree', c.erreurs().length === 0, c.erreurs());
} finally {
  if (c) { try { await c.send('Browser.close'); } catch {} }
  chrome.kill();
  serveur.kill();
  await sleep(500);
  try { fs.rmSync(dossier, {recursive: true, force: true}); } catch {}
}

console.log('\n' + passes + ' ok, ' + echecs + ' echec(s)');
process.exit(echecs ? 1 : 0);
