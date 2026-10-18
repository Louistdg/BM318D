// Contrats d'interface extraits du source réellement servi.
// Échoue si le parcours, les libellés de preuve ou l'isolation des conversations
// ne sont pas ceux du serveur. N'exécute pas de navigateur.
import fs from 'node:fs';
import assert from 'node:assert/strict';

const mission = fs.readFileSync(new URL('./mission.js', import.meta.url), 'utf8');
const html = fs.readFileSync(new URL('./BM318d-Railway.html', import.meta.url), 'utf8');
const securite = fs.readFileSync(new URL('./security-ui.js', import.meta.url), 'utf8');
const connecteurs = fs.readFileSync(new URL('./connectors.js', import.meta.url), 'utf8');

function extraire(source, nom) {
  const marque = 'function ' + nom;
  const i = source.indexOf(marque);
  if (i < 0) throw new Error('fonction absente: ' + nom);
  const start = source.indexOf('{', i);
  let n = 0;
  for (let j = start; j < source.length; j++) {
    if (source[j] === '{') n++;
    else if (source[j] === '}') {
      n--;
      if (n === 0) return source.slice(i, j + 1);
    }
  }
  throw new Error('accolade non fermée: ' + nom);
}

const libellePreuve = new Function(extraire(mission, 'libellePreuve') + '\nreturn libellePreuve;')();
assert.equal(libellePreuve('none'), 'Non vérifié');
assert.equal(libellePreuve('declared'), 'Déclaré');
assert.equal(libellePreuve('human'), 'Revu par une personne');
assert.equal(libellePreuve('test'), 'Test exécuté');
assert.equal(libellePreuve('validated'), 'Validé');
assert.equal(libellePreuve('approved'), 'Validé');
assert.equal(libellePreuve('refused'), 'Refusé');
assert.equal(libellePreuve('autre-chose'), 'État serveur : autre-chose');
assert.ok(!libellePreuve('validated').includes('Non vérifié'));

const choisir = extraire(mission, 'choisirTest');
for (const commande of ['unittest', 'py_compile', 'node_check']) assert.ok(choisir.includes(commande), commande);
assert.equal((choisir.match(/<option /g) || []).length, 3);
assert.ok(!choisir.includes('<input'));
assert.ok(!mission.includes('mcAsEvidence'));
assert.ok(!mission.includes('sessionStorage'));
assert.ok(mission.includes("window.mcPage='mission'"));
assert.ok(mission.includes('data-groupe="equipe"'));
assert.ok(mission.includes('data-groupe="travail"'));
assert.ok(mission.includes('data-groupe="decisions"'));
assert.ok(mission.includes('data-groupe="compte"'));
assert.ok(mission.includes('Attribuer l\'action à') || mission.includes('Attribuer l\\\'action à'));

const cleConversations = new Function('project', extraire(html, 'cleConversations') + '\nreturn cleConversations();');
assert.equal(cleConversations(null), 'mc_conversations_aucun');
assert.equal(cleConversations(7), 'mc_conversations_7');
assert.notEqual(cleConversations(7), cleConversations(8));
assert.ok(html.includes('Seul le message en cours est envoyé'));
assert.ok(html.includes('pièce jointe'));
assert.ok(!html.includes("const CLE_CONVERSATIONS='mc_conversations_'+project"));
assert.ok(html.includes('legacy-nav'));
assert.ok(html.includes('id="serviceDot"'));

assert.ok(!securite.includes('sessionStorage'));
assert.ok(securite.includes('mcJetonAdmin'));
assert.ok(connecteurs.includes('name="name"'));
assert.ok(connecteurs.includes('name="kind"'));
assert.ok(connecteurs.includes('name="model"'));
assert.ok(connecteurs.includes('fieldset'));
assert.ok(connecteurs.includes('readonly'));
assert.ok(!connecteurs.includes('sessionStorage'));

console.log('ok contrat interface');
