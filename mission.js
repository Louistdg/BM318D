(()=>{
'use strict';
const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data={agents:[],missions:[],assignments:[],handoffs:[],notes:[],links:[],jobs:[],audit:[]},chosen=null,mode='agents',pan={x:45,y:35},zoom=1,drag=null,modalCallback=null,tic=0,modelesOllama=[];
const getProject=()=>Number(document.getElementById('project').value);
const acteurId=()=>{const s=document.getElementById('mcActeur');return s&&s.value?Number(s.value):null};
let jetonAdmin=(typeof window.mcJetonAdmin==='string')?window.mcJetonAdmin:'';
function memoriserJeton(valeur){jetonAdmin=String(valeur||'');window.mcJetonAdmin=jetonAdmin;}
const TOKEN=(document.querySelector('meta[name="mc-token"]')||{}).content||'';
const entetes=extra=>Object.assign({'X-MC-Token':TOKEN},extra||{});
function demanderJeton(){return new Promise(resolve=>{const retour=document.activeElement;let boite=document.getElementById('mcAuth');if(!boite){boite=document.createElement('dialog');boite.id='mcAuth';boite.innerHTML='<form><h2>Action non réalisée</h2><p>Le serveur a refusé cette action. Saisis le jeton administrateur pour réessayer. Il reste seulement en mémoire pour cette page.</p><label>Jeton administrateur <input name="jeton" type="password" autocomplete="current-password"></label><div class="mc-auth-actions"><button type="submit">Réessayer</button><button type="button" id="mcAuthAnnuler">Annuler</button></div></form>';document.body.append(boite);}const form=boite.querySelector('form');const fin=v=>{if(boite.open)boite.close();if(retour&&retour.focus)retour.focus();resolve(v);};form.onsubmit=e=>{e.preventDefault();memoriserJeton(form.elements.jeton.value);form.elements.jeton.value='';fin(!!jetonAdmin);};boite.querySelector('#mcAuthAnnuler').onclick=()=>{form.elements.jeton.value='';fin(false);};boite.showModal();form.elements.jeton.focus();});}
const post=async(path,obj,retente)=>{const r=await fetch('/api/mc/'+path,{method:'POST',headers:entetes({'Content-Type':'application/json',...(jetonAdmin?{'X-MC-Admin':jetonAdmin}:{})}),body:JSON.stringify({project:getProject(),...obj})});let d={};try{d=await r.json()}catch(_){d={}}if(r.status===403&&!retente){const ok=await demanderJeton();if(!ok)throw Error('Action non réalisée : autorisation requise.');return post(path,obj,true);}if(!r.ok)throw Error(d.error||('Action non réalisée ('+r.status+')'));return d};
fetch('/api/mc/models',{headers:entetes()}).then(r=>r.json()).then(d=>{modelesOllama=d.models||[]}).catch(()=>{});
function toast(s){if(typeof notify==='function')notify(s);else alert(s)}
function libellePreuve(etat){
 const noms={none:'Non vérifié',declared:'Déclaré',human:'Revu par une personne',test:'Test exécuté',validated:'Validé',approved:'Validé',refused:'Refusé'};
 return Object.prototype.hasOwnProperty.call(noms,etat)?noms[etat]:('État serveur : '+etat);
}
function choisirTest(id){
 modal('Lancer un test autorisé','<p class="subtle">Seules les commandes autorisées par le serveur. Aucun texte libre.</p><label>Commande</label><select id="mcTestCmd"><option value="unittest">unittest</option><option value="py_compile">py_compile</option><option value="node_check">node_check</option></select>',async()=>{
  const command=$('mcTestCmd').value;
  const r=await post('job/test',{id,agent_id:acteurId(),command});
  const code=(r.evidence||{}).exit_code;
  toast('Test exécuté : '+command+' · code '+code);
 },'Lancer le test');
}
async function refresh(){const p=getProject();if(!p)return;try{const r=await fetch('/api/mc/state?project='+p,{headers:entetes()});if(!r.ok)throw Error('Serveur indisponible');data=await r.json();render();majNotifications()}catch(e){toast(e.message)}}
let focusRetour=null;
function fermerModal(){window.mcModal=false;$('modalback').classList.remove('open');$('submit').disabled=false;$('submit').textContent='Enregistrer';const retour=focusRetour;focusRetour=null;if(retour&&retour.focus)retour.focus();}
function modal(title,html,fn,libelle){focusRetour=document.activeElement;$('modalTitle').textContent=title;$('modalFields').innerHTML=html;$('submit').textContent=libelle||'Enregistrer';$('submit').disabled=false;$('modalback').classList.add('open');modalCallback=fn;window.mcModal=true;const premier=$('modalFields').querySelector('input,select,textarea,button');if(premier)premier.focus();}
const submit=$('submit');submit.addEventListener('click',async e=>{if(!window.mcModal)return;e.stopImmediatePropagation();try{await modalCallback();fermerModal();await refresh()}catch(err){toast(err.message);$('submit').disabled=false;if(/refl|fléch/.test($('submit').textContent))$('submit').textContent='Réessayer';}},true);
$('cancel').addEventListener('click',()=>{if(window.mcModal)fermerModal();});
const roles=[['manager','Chef de projet'],['architect','Architecte'],['frontend','Développeur frontend'],['backend','Développeur backend'],['database','Spécialiste données'],['tester','Tests'],['auditor','Audit'],['security','Sécurité'],['documentation','Documentation'],['specialist','Spécialiste']];
const roleName=r=>{const t=(data.roles||[]).find(x=>x.key===r);return t?t.label:(roles.find(x=>x[0]===r)?.[1]||r)};
const roleListe=()=>((data.roles&&data.roles.length)?data.roles.map(r=>[r.key,r.label]):roles);
function opts(list,value){return list.map(([id,name])=>'<option value="'+esc(id)+'" '+(String(id)===String(value)?'selected':'')+'>'+esc(name)+'</option>').join('')}
function agentOptions(includeNone=true){return (includeNone?'<option value="">Aucun responsable</option>':'')+opts(data.agents.map(a=>[a.id,a.name]))}
function createAgent(){
 modal('Ajouter un assistant','<label>Nom</label><input id="mcName" placeholder="Architecte backend"><label>Rôle</label><select id="mcRole">'+opts(roleListe())+'</select><label>Équipe / branche</label><input id="mcTeam" value="Général"><label>Responsable</label><select id="mcManager">'+agentOptions()+'</select><label>Compétences (séparées par des virgules)</label><input id="mcSkills" placeholder="python, sqlite"><label>Consignes</label><textarea id="mcInstructions" placeholder="Périmètre et responsabilités"></textarea>',()=>post('agent',{name:$('mcName').value,role:$('mcRole').value,team:$('mcTeam').value,manager_id:$('mcManager').value||null,skills:$('mcSkills').value,instructions:$('mcInstructions').value,x:140+(data.agents.length%4)*290,y:120+Math.floor(data.agents.length/4)*200}));
}
function createMission(){modal('Nouvelle mission','<label>Titre</label><input id="mcTitle" placeholder="Développer une API"><label>Objectif</label><textarea id="mcObjective" placeholder="Résultat attendu, contraintes, critères de réussite"></textarea>',()=>post('mission',{title:$('mcTitle').value,objective:$('mcObjective').value}))}
function createAssignment(){
 if(!data.missions.length||!data.agents.length){toast('Crée une mission et un agent avant une attribution');return}
 modal('Attribuer une mission','<label>Mission</label><select id="mcMission">'+opts(data.missions.map(m=>[m.id,m.title]))+'</select><label>Agent</label><select id="mcAssignee">'+agentOptions(false)+'</select><label>Travail à effectuer</label><textarea id="mcTask" placeholder="Tâche précise, résultat et preuve attendue"></textarea>',()=>post('assignment',{mission_id:Number($('mcMission').value),agent_id:Number($('mcAssignee').value),task:$('mcTask').value}))}
function createNote(){modal('Note de contexte','<label>Portée</label><select id="mcScope"><option value="project">Projet entier</option><option value="team">Équipe</option><option value="agent">Agent</option></select><label>Équipe (portée équipe)</label><input id="mcNoteTeam" placeholder="Backend"><label>Agent concerné (optionnel)</label><select id="mcNoteAgent">'+agentOptions()+'</select><label>Décision / contexte</label><textarea id="mcNoteText" placeholder="Décision, fichiers concernés, contraintes, blocages..."></textarea><label>Remplace la note n° (optionnel)</label><input id="mcNoteRemplace" placeholder="ex. 12">',()=>post('note',{scope:$('mcScope').value,team:$('mcNoteTeam').value||null,agent_id:$('mcNoteAgent').value||null,supersedes:$('mcNoteRemplace').value||null,content:$('mcNoteText').value}))}
function createJob(){
 if(!data.agents.length){toast('Crée un agent avant un job');return}
 const missions=data.missions.map(m=>[m.id,m.title]);
 modal('Nouveau job d\'exécution','<p class="subtle">Le modèle travaille dans un dossier isolé. Rien n\'est écrit avant ton approbation.</p><label>Agent</label><select id="mcJobAgent">'+agentOptions(false)+'</select><label>Mission (optionnel)</label><select id="mcJobMission"><option value="">Aucune</option>'+opts(missions)+'</select><label>Titre</label><input id="mcJobTitle" placeholder="Corriger le calcul"><label>Branche (optionnel)</label><select id="mcJobBranch"><option value="">Aucune</option>'+opts((data.branches||[]).map(b=>[b.id,b.name]))+'</select><label>Travail demandé</label><textarea id="mcJobTask" placeholder="Ce que l\'agent doit produire, précisément"></textarea>',()=>post('job',{agent_id:Number($('mcJobAgent').value),mission_id:$('mcJobMission').value||null,branch_id:$('mcJobBranch').value||null,title:$('mcJobTitle').value,task:$('mcJobTask').value}));
}
function remplirActeurs(){
 const s=document.getElementById('mcActeur');if(!s)return;
 const ancien=s.value;s.innerHTML=(data.agents||[]).filter(a=>a.status!=='archived').map(a=>'<option value="'+a.id+'">'+esc(a.name)+'</option>').join('');
 if(ancien)s.value=ancien;
}
async function agirSurJob(id,action){
 try{
  if(action==='review_tests'){if(!confirm('Confirme que tu as examiné les résultats des tests et qu’ils vérifient bien le changement ?'))return;await post('review',{job_id:id,kind:'tests',verdict:'ok',findings:['Résultats examinés et jugés pertinents par l’opérateur']});toast('Revue humaine des tests enregistrée')}
  else if(action==='review_secu'){const r=await post('review',{job_id:id,agent_id:acteurId(),kind:'securite'});toast(r.verdict==='ok'?'Audit sécurité : rien à signaler':('Audit sécurité : '+r.findings.length+' constat(s)'))}
  else{await post('job/'+action,{id,agent_id:acteurId()});toast('Job : '+action)}
  await refresh()
 }catch(e){toast(e.message)}
}
async function voirDiff(id){
 try{
  const r=await fetch('/api/mc/job?project='+getProject()+'&id='+id,{headers:entetes()});
  if(!r.ok)throw Error('Diff indisponible');
  const j=await r.json();
  modal('Proposition · '+j.title,'<p class="subtle">Statut : '+esc(j.status)+'. Approuver écrit les fichiers dans le dossier isolé. Ce n\'est pas un commit git : le commit est une action séparée, après les tests et les revues.</p><pre style="max-height:50vh;overflow:auto;white-space:pre-wrap">'+esc(j.diff||'Aucun diff')+'</pre>',async()=>{});
 }catch(e){toast(e.message)}
}
async function revueCode(id){
 modal('Revue de code','<label>Verdict</label><select id="mcRevVerdict"><option value="ok">Conforme</option><option value="probleme">Problème relevé</option></select><label>Constats</label><textarea id="mcRevFindings" placeholder="Un constat par ligne"></textarea>',async()=>{
  const constats=($('mcRevFindings').value||'').split('\n').map(x=>x.trim()).filter(Boolean);
  await post('review',{job_id:id,agent_id:acteurId(),kind:'code',verdict:$('mcRevVerdict').value,findings:constats});
  toast('Revue enregistrée');
 });
}
async function validerJob(id){
 try{await post('job/validate',{id,agent_id:acteurId()});await refresh();toast('Travail validé (tests verts + revues)')}catch(e){toast(e.message)}
}
async function committerJob(id){
 if(!confirm('Écrire un commit git dans le workspace de ce job ? Cette écriture n\'est pas annulée depuis cette fenêtre.'))return;
 try{const r=await post('job/commit',{id,agent_id:acteurId()});await refresh();toast(r.commit?('Commit '+String(r.commit).slice(0,8)):'Rien à committer')}catch(e){toast(e.message)}
}
async function voirRapport(id){
 try{
  const r=await fetch('/api/mc/report?project='+getProject()+'&job='+id,{headers:entetes()});
  if(!r.ok)throw Error('Rapport indisponible');
  const p=await r.json();
  const revues=(p.reviews||[]).map(x=>'<div class="mc-record"><b>'+esc(x.kind)+'</b> · '+esc(x.verdict)+'<p>'+esc(x.findings||'')+'</p></div>').join('');
  modal('Rapport · '+p.job.title,'<p class="subtle">'+esc(p.job.status)+' · modèle '+esc(p.job.model)+' · test : '+(p.evidence.exit_code===0?'réussi (code 0)':'non exécuté')+(p.evidence.commit?' · commit '+esc(String(p.evidence.commit).slice(0,10)):'')+'</p><h4>Diff</h4><pre style="max-height:30vh;overflow:auto;white-space:pre-wrap">'+esc(p.diff||'—')+'</pre><h4>Revues</h4>'+(revues||'<p class="subtle">Aucune revue.</p>')+'<h4>Journal</h4><pre style="max-height:20vh;overflow:auto;white-space:pre-wrap">'+esc(p.log||'—')+'</pre>',async()=>{});
 }catch(e){toast(e.message)}
}

function createLink(){
 if(data.agents.length<2){toast('Il faut au moins deux agents');return}
 modal('Relier deux agents','<label>Source</label><select id="mcSource">'+agentOptions(false)+'</select><label>Destination</label><select id="mcTarget">'+agentOptions(false)+'</select><label>Type de connexion</label><select id="mcKind"><option value="communication">Communication</option><option value="dependency">Dépendance</option></select>',()=>post('link',{source_id:Number($('mcSource').value),target_id:Number($('mcTarget').value),kind:$('mcKind').value}))}
const nav=document.querySelector('.rail');
const button=document.createElement('button');button.type='button';button.textContent='◎';button.title='Mission Control';button.setAttribute('aria-label','Mission Control');button.dataset.page='mission';button.onclick=()=>open();
const logo=nav.querySelector('.logo');nav.insertBefore(button,logo?logo.nextSibling:nav.firstChild);
const section=document.createElement('section');section.id='mission';section.className='view';
section.innerHTML='<div class="mc-toolbar"><strong>Mission Control</strong><label title="Indique quel agent est cité dans l\'action. Ce n\'est pas une connexion.">Attribuer l\'action à</label><select id="mcActeur" aria-label="Attribuer l\'action à"></select><div class="mc-modes" role="tablist"><button type="button" class="active" data-groupe="equipe" aria-pressed="true">Équipe</button><button type="button" data-groupe="travail" aria-pressed="false">Travail</button><button type="button" data-groupe="decisions" aria-pressed="false">Décisions</button><button type="button" data-groupe="compte" aria-pressed="false">Compte</button></div><div class="mc-groupe" data-groupe="equipe"><button id="mcAdd" type="button">＋ Agent</button><button id="mcRol" type="button">＋ Rôle</button><button id="mcRecrute" type="button">Recruter</button><button id="mcLink" type="button">↗ Connexion</button><button id="mcAligner" type="button">Aligner</button></div><div class="mc-groupe" data-groupe="travail" hidden><button id="mcMission" type="button">＋ Mission</button><button id="mcAssign" type="button">＋ Attribution</button><button id="mcJob" type="button">＋ Job</button><button id="mcBranche" type="button">＋ Branche</button><button id="mcPlan" type="button" title="Demander un découpage en tâches. Rien n\'est créé avant accord.">Proposer un plan</button><button id="mcOrchestrer" type="button">Orchestrer</button><button id="mcNote" type="button">＋ Contexte</button></div><div class="mc-groupe" data-groupe="decisions" hidden><button id="mcDecision" type="button">＋ Décision</button><button id="mcDecisionsVue" type="button">Propositions</button><button id="mcCharge" type="button">Charge</button><button id="mcPerm" type="button">Permissions</button></div><div class="mc-groupe" data-groupe="compte" hidden><button id="mcReglages" type="button">Réglages</button><button id="mcSauvegardes" type="button">Sauvegardes</button><button id="mcConnecteurs" type="button">Connecteurs</button><input id="mcRecherche" aria-label="Rechercher" placeholder="Rechercher (2 lettres min.)"><button id="mcNotif" type="button" title="Notifications" aria-label="Notifications">●</button></div><div style="flex:1"></div><button id="mcSwitch" type="button">Missions & preuves</button><button id="mcRefresh" type="button" aria-label="Actualiser">↻</button></div><div class="mc-stage" id="mcStage"><div class="mc-world" id="mcWorld"><div class="mc-zones" id="mcZones"></div><svg class="mc-links" id="mcLinks"></svg><div id="mcNodes"></div></div><div class="mc-minimap"><canvas id="mcMinimapCanvas" width="200" height="120"></canvas></div><div class="mc-legend">Déplacer : glisser · Maj+clic : sélection · Déposer sur une zone : changer d\'équipe · Violet : hiérarchie · Vert : communication · Orange : dépendance</div><aside class="mc-side" id="mcDetails" style="display:none"></aside></div><div id="mcRecords" class="dash" style="display:none;overflow:auto"></div>';
document.querySelector('.main').appendChild(section);
function createDecision(){
 modal('Décision technique','<label>Titre</label><input id="mcDecTitle" placeholder="Choix du stockage"><label>Décision</label><textarea id="mcDecBody" placeholder="Ce qui a été décidé"></textarea><label>Justification (obligatoire)</label><textarea id="mcDecWhy" placeholder="Pourquoi, avec les faits mesurés"></textarea><label>Alternatives écartées</label><textarea id="mcDecAlt" placeholder="Ce qui a été envisagé et pourquoi ce n\'est pas retenu"></textarea><label>Agent (optionnel)</label><select id="mcDecAgent">'+agentOptions()+'</select>',()=>post('decision',{agent_id:$('mcDecAgent').value||null,title:$('mcDecTitle').value,decision:$('mcDecBody').value,rationale:$('mcDecWhy').value,alternatives:$('mcDecAlt').value}));
}
function createRole(){
 modal('Nouveau rôle','<label>Clé (minuscules, sans espace)</label><input id="mcRoleKey" placeholder="devops"><label>Nom affiché</label><input id="mcRoleLabel" placeholder="Ingénieur DevOps"><label>Description</label><textarea id="mcRoleDesc"></textarea>',()=>post('role',{key:$('mcRoleKey').value.trim().toLowerCase(),label:$('mcRoleLabel').value,description:$('mcRoleDesc').value}));
}
function createRecruit(){
 modal('Demande de recrutement','<p class="subtle">La demande reste en attente : elle doit être acceptée pour créer l\'agent.</p><label>Nom</label><input id="mcRecName" placeholder="Testeur temporaire"><label>Rôle</label><select id="mcRecRole">'+opts(roleListe())+'</select><label>Équipe</label><input id="mcRecTeam" value="Général"><label>Justification (obligatoire)</label><textarea id="mcRecWhy" placeholder="Pourquoi cet agent, pour quelle charge"></textarea>',()=>post('recruit',{name:$('mcRecName').value,role:$('mcRecRole').value,team:$('mcRecTeam').value,justification:$('mcRecWhy').value}));
}
async function rechercherGlobal(terme){
 try{
  const r=await fetch('/api/mc/search?project='+getProject()+'&q='+encodeURIComponent(terme),{headers:entetes()});
  if(!r.ok)throw Error('Recherche indisponible');
  const s=await r.json();
  const bloc=(titre,liste,rendu)=>liste&&liste.length?('<h4>'+titre+' ('+liste.length+')</h4>'+liste.map(rendu).join('')):'';
  const html=bloc('Agents',s.agents,a=>'<div class="mc-record">'+esc(a.name)+' · '+esc(roleName(a.role))+' · '+esc(a.team)+'</div>')
   +bloc('Missions',s.missions,m=>'<div class="mc-record">'+esc(m.title)+'</div>')
   +bloc('Jobs',s.jobs,j=>'<div class="mc-record">'+esc(j.title)+' · '+esc(j.status)+'</div>')
   +bloc('Notes',s.notes,n=>'<div class="mc-record">'+esc(n.content)+'</div>')
   +bloc('Décisions',s.decisions,d=>'<div class="mc-record">'+esc(d.title)+' · '+esc(d.decision)+'</div>')
   +bloc('Messages',s.messages,m=>'<div class="mc-record">'+esc(m.body)+'</div>');
  modal('Recherche · '+s.terme,html||'<p class="subtle">Aucun résultat.</p>',async()=>{});
 }catch(e){toast(e.message)}
}
async function ouvrirPermissions(){
 try{
  const equipes=(data.permissions&&data.permissions.length)?data.permissions:[...new Set(data.agents.map(a=>a.team))].map(equipe=>({team:equipe,can_create_agents:false,can_approve_jobs:false,can_run_tests:false}));
  const html=equipes.map(e=>'<div class="mc-record"><b>'+esc(e.team)+'</b><br><label style="display:inline-block;margin-right:10px"><input type="checkbox" data-perm-team="'+esc(e.team)+'" data-perm="can_create_agents" '+(e.can_create_agents?'checked':'')+'> Recruter</label><label style="display:inline-block;margin-right:10px"><input type="checkbox" data-perm-team="'+esc(e.team)+'" data-perm="can_approve_jobs" '+(e.can_approve_jobs?'checked':'')+'> Approuver un job</label><label style="display:inline-block"><input type="checkbox" data-perm-team="'+esc(e.team)+'" data-perm="can_run_tests" '+(e.can_run_tests?'checked':'')+'> Lancer les tests</label></div>').join('')||'<p class="subtle">Aucune équipe.</p>';
  modal('Permissions par équipe', html, async()=>{
   for(const e of equipes){
    const lire=a=>{const b=document.querySelector('[data-perm-team="'+e.team+'"][data-perm="'+a+'"]');return b?b.checked:true};
    await post('permissions',{team:e.team,can_create_agents:lire('can_create_agents'),can_approve_jobs:lire('can_approve_jobs'),can_run_tests:lire('can_run_tests')});
   }
   toast('Permissions enregistrées');
  });
 }catch(e){toast(e.message)}
}
async function ouvrirReglages(){
 try{
  const r=await fetch('/api/mc/settings?project='+getProject(),{headers:entetes()});
  if(!r.ok)throw Error('Réglages indisponibles');
  const s=await r.json();
  modal('Réglages','<p class="subtle">Le jeton administrateur reste dans logs\\admin-token.txt sur cette machine. Le serveur ne le renvoie pas. Saisi ici, il reste seulement en mémoire pour cette page.</p><label>Jeton administrateur</label><input id="mcSetAdmin" type="password" autocomplete="current-password" placeholder="'+(jetonAdmin?'déjà en mémoire pour cette page':'coller le jeton local')+'"><p class="subtle">Ces réglages s’appliquent au projet sélectionné. Chaque projet peut utiliser son propre dossier local ; ses travaux y sont rangés dans des sous-dossiers.</p>'
   +'<label>Adresse Ollama</label><input id="mcSetUrl" value="'+esc(s.ollama_url)+'">'
   +'<label>Modèle par défaut</label><input id="mcSetModel" value="'+esc(s.ollama_model)+'">'
   +'<label>Jobs simultanés (vide = selon la mémoire)</label><input id="mcSetJobs" value="'+esc(s.max_jobs)+'">'
   +'<label>Sauvegarde automatique (minutes, 0 = arrêtée)</label><input id="mcSetBackup" value="'+esc(s.auto_backup_minutes)+'">'
   +'<label>Dossier local du projet (disque C: ou D:)</label><input id="mcSetWorkspace" value="'+esc(s.workspace_dir)+'" maxlength="1024" autocomplete="off"><p class="subtle">BM318d créera ici les dossiers du projet et de ses travaux. Les imports seront copiés dans cet espace ; l’original restera à son emplacement.</p><p class="subtle"><strong>À savoir :</strong> les sauvegardes BM318d couvrent la base SQLite, pas les fichiers importés. Inclue aussi ce dossier dans tes sauvegardes personnelles.</p>',async()=>{
    const saisi=$('mcSetAdmin').value.trim();if(saisi)memoriserJeton(saisi);
    await post('settings',{key:'workspace_dir',value:$('mcSetWorkspace').value});
    await post('settings',{key:'ollama_url',value:$('mcSetUrl').value});
    await post('settings',{key:'ollama_model',value:$('mcSetModel').value});
    await post('settings',{key:'max_jobs',value:$('mcSetJobs').value});
    await post('settings',{key:'auto_backup_minutes',value:$('mcSetBackup').value});
    toast('Réglages enregistrés');
   });
 }catch(e){toast(e.message)}
}
async function ouvrirSauvegardes(){
 try{
  const r=await fetch('/api/mc/backups',{headers:entetes()});
  if(!r.ok)throw Error('Sauvegardes indisponibles');
  const s=await r.json();
  const lignes=(s.backups||[]).map(b=>'<div class="mc-record">'+esc(b.nom)+' · '+Math.round(b.octets/1024)+' Ko · '+esc(b.quand)+' <button data-restore="'+esc(b.nom)+'">Restaurer</button></div>').join('');
  modal('Sauvegardes',(lignes||'<p class="subtle">Aucune sauvegarde.</p>')+'<p><button id="mcBackupNow">Sauvegarder maintenant</button></p>',async()=>{});
  setTimeout(()=>{const b=$('mcBackupNow');if(b)b.onclick=async()=>{try{const r=await post('backup',{});if(!r||!r.file)throw Error('Le serveur n\'a pas confirmé la sauvegarde.');await refresh();toast('Sauvegarde écrite : '+r.file)}catch(e){toast('Sauvegarde non confirmée : '+e.message)}};},50);
  setTimeout(()=>{document.querySelectorAll('[data-restore]').forEach(b=>b.onclick=async()=>{if(!confirm('Restaurer '+b.dataset.restore+' ? La base actuelle sera sauvegardée avant.'))return;try{await post('restore',{file:b.dataset.restore});await refresh();toast('Base restaurée')}catch(e){toast(e.message)}});},50);
 }catch(e){toast(e.message)}
}
async function voirNotifications(){
 try{
  const r=await fetch('/api/mc/notifications?project='+getProject(),{headers:entetes()});
  if(!r.ok)throw Error('Notifications indisponibles');
  const n=await r.json();
  modal('Notifications','<div class="mc-record">Messages non lus : <b>'+n.messages_non_lus+'</b></div>'
   +'<div class="mc-record">Recrutements en attente : <b>'+n.recrutements_en_attente+'</b></div>'
   +'<div class="mc-record">Jobs en échec : <b>'+n.jobs_en_echec+'</b></div>'
   +'<div class="mc-record">Jobs en cours : <b>'+n.jobs_en_cours+'</b></div>'
   +'<div class="mc-record">Passations à acquitter : <b>'+n.passations_a_acquitter+'</b></div>',async()=>{});
 }catch(e){toast(e.message)}
}
async function majNotifications(){
 try{
  const r=await fetch('/api/mc/notifications?project='+getProject(),{headers:entetes()});
  if(!r.ok)return;
  const n=await r.json();
  const total=(n.messages_non_lus||0)+(n.recrutements_en_attente||0)+(n.jobs_en_echec||0)+(n.passations_a_acquitter||0);
  const b=$('mcNotif');if(b){b.textContent=total?('● '+total):'○';b.title='Messages '+n.messages_non_lus+' · recrutements '+n.recrutements_en_attente+' · échecs '+n.jobs_en_echec+' · passations '+n.passations_a_acquitter;}
 }catch(_){}
}
async function voirCharge(){
 try{
  const r=await post('charge',{});
  const lignes=r.agents.map(a=>'<tr><td>'+esc(a.name)+'</td><td>'+esc(a.role)+'</td><td>'+esc(a.team)+'</td><td>'+a.en_cours+'</td><td>'+a.echecs+'</td><td>'+a.messages_non_lus+'</td><td>'+(a.disponible?'oui':'non')+'</td></tr>').join('');
  const suggestions=r.suggestions.map(s=>'<div class="mc-record">'+esc(s.titre)+' : '+esc(s.agent_actuel)+' → '+esc(s.vers)+'</div>').join('');
  modal('Charge de l\'équipe','<p class="subtle">'+r.total.actifs+' actifs · '+r.total.archives+' archivés · '+r.total.en_cours+' en cours · '+r.total.echecs+' échec(s) · mémoire libre '+(r.memoire_libre_mo||'?')+' Mo · CPU '+(r.cpu_pct==null?'?':r.cpu_pct+' %')+' · GPU '+(r.gpu?Math.round(r.gpu.utilisation_pct)+' %':'absent')+' · limite '+r.limite+'</p><table style="width:100%;font-size:13px;border-collapse:collapse"><tr><th align="left">Agent</th><th align="left">Rôle</th><th align="left">Équipe</th><th>En cours</th><th>Échecs</th><th>Non lus</th><th>Dispo</th></tr>'+lignes+'</table><h4>Réaffectations proposées</h4>'+(suggestions||'<p class="subtle">Aucune.</p>'),async()=>{});
 }catch(e){toast(e.message)}
}
$('mcAdd').onclick=createAgent;$('mcMission').onclick=createMission;$('mcAssign').onclick=createAssignment;$('mcNote').onclick=createNote;$('mcDecision').onclick=createDecision;$('mcRol').onclick=createRole;$('mcRecrute').onclick=createRecruit;$('mcCharge').onclick=voirCharge;$('mcPerm').onclick=ouvrirPermissions;$('mcReglages').onclick=ouvrirReglages;$('mcSauvegardes').onclick=ouvrirSauvegardes;$('mcNotif').onclick=voirNotifications;$('mcRecherche').addEventListener('keydown',e=>{if(e.key==='Enter')rechercherGlobal($('mcRecherche').value)});$('mcLink').onclick=createLink;$('mcJob').onclick=createJob;$('mcBranche').onclick=createBranche;$('mcPlan').onclick=createPlan;$('mcOrchestrer').onclick=orchestrer;$('mcAligner').onclick=aligner;$('mcRefresh').onclick=refresh;
$('mcSwitch').onclick=()=>{mode=mode==='agents'?'missions':'agents';$('mcSwitch').textContent=mode==='agents'?'Missions & preuves':'Canvas des agents';render()};
document.querySelectorAll('.mc-modes button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.mc-modes button').forEach(x=>{const on=x===b;x.classList.toggle('active',on);x.setAttribute('aria-pressed',on?'true':'false');});document.querySelectorAll('.mc-groupe').forEach(g=>{g.hidden=g.dataset.groupe!==b.dataset.groupe;});});
$('mcConnecteurs').onclick=()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent==='Connecteurs IA / MCP');if(b)b.click();};
$('mcDecisionsVue').onclick=()=>{mode='missions';$('mcSwitch').textContent='Canvas des agents';render();};
function open(){window.mcPage='mission';document.body.classList.remove('legacy-page');const rail=document.querySelector('.rail');if(rail)rail.classList.remove('legacy-open');document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id==='mission'));document.querySelectorAll('.rail button[data-page]').forEach(x=>x.classList.toggle('active',x.dataset.page==='mission'));$('pageTitle').textContent='Mission Control';if($('linkTask'))$('linkTask').style.display='none';refresh()}
const originalShow=window.showPage;
document.querySelectorAll('.rail button[data-page]:not([data-page="mission"])').forEach(b=>b.addEventListener('click',()=>{window.mcModal=false},true));
$('project').addEventListener('change',()=>{chosen=null;if(typeof window.rechargerConversations==='function')window.rechargerConversations();if(window.mcPage==='mission')refresh()});
function pos(a){return{x:a.x,y:a.y}}
function edgeMarkup(){const m=new Map(data.agents.map(a=>[a.id,a]));let lines=[];
for(const a of data.agents){if(a.manager_id&&m.has(a.manager_id))lines.push([m.get(a.manager_id),a,'#a98df0',false])}
for(const l of data.links){if(m.has(l.source_id)&&m.has(l.target_id))lines.push([m.get(l.source_id),m.get(l.target_id),l.kind==='communication'?'#6ac6a2':'#e8b570',true])}
$('mcLinks').innerHTML='<defs><marker id="mcArrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6" fill="none" stroke="#e2d1fc"/></marker></defs>'+lines.map(([a,b,color,dashed])=>'<path d="M'+(a.x+118)+' '+(a.y+132)+' C'+(a.x+118)+' '+(a.y+185)+','+(b.x+118)+' '+(b.y-50)+','+(b.x+118)+' '+b.y+'" fill="none" stroke="'+color+'" stroke-width="2" '+(dashed?'stroke-dasharray="7 5"':'')+' marker-end="url(#mcArrow)"/>').join('')}
function transform(){$('mcWorld').style.transform='translate('+pan.x+'px,'+pan.y+'px) scale('+zoom+')'}
let selection=new Set();
function zonesMarkup(){
 const groupes={};data.agents.forEach(a=>{(groupes[a.team]=groupes[a.team]||[]).push(a)});
 return Object.keys(groupes).sort().map(t=>{
  const xs=groupes[t].map(a=>a.x),ys=groupes[t].map(a=>a.y);
  const x=Math.min.apply(null,xs)-46,y=Math.min.apply(null,ys)-64;
  const l=Math.max.apply(null,xs)+235+46-x,h=Math.max.apply(null,ys)+170+46-y;
  return '<div class="mc-zone" data-team="'+esc(t)+'" style="left:'+x+'px;top:'+y+'px;width:'+l+'px;height:'+h+'px"><span>'+esc(t)+' · '+groupes[t].length+'</span></div>';
 }).join('');
}
function marquerSelection(){
 document.querySelectorAll('.mc-node').forEach(el=>el.classList.toggle('selectionne',selection.has(Number(el.dataset.id))));
}
function dessinerMinimap(){
 const cv=$('mcMinimapCanvas');if(!cv)return;const ctx=cv.getContext('2d');
 ctx.clearRect(0,0,cv.width,cv.height);ctx.fillStyle='#191524';ctx.fillRect(0,0,cv.width,cv.height);
 if(!data.agents.length)return;
 const largeurMax=Math.max.apply(null,data.agents.map(a=>a.x))+235,hauteurMax=Math.max.apply(null,data.agents.map(a=>a.y))+170;
 const s=Math.min((cv.width-12)/(largeurMax+40),(cv.height-12)/(hauteurMax+40));
 data.agents.forEach(a=>{ctx.fillStyle=selection.has(a.id)?'#6ac6a2':'#b9a6e8';ctx.fillRect(6+a.x*s,6+a.y*s,Math.max(3,235*s*0.28),Math.max(3,120*s*0.28))});
 const r=$('mcStage').getBoundingClientRect();
 ctx.strokeStyle='#8a7bb0';ctx.strokeRect(6+(-pan.x/zoom)*s,6+(-pan.y/zoom)*s,(r.width/zoom)*s,(r.height/zoom)*s);
}
function equipeSous(clientX,clientY){
 const r=$('mcStage').getBoundingClientRect();
 const wx=(clientX-r.left-pan.x)/zoom,wy=(clientY-r.top-pan.y)/zoom;
 const zone=[...document.querySelectorAll('.mc-zone')].find(z=>{
  const l=parseFloat(z.style.left),t=parseFloat(z.style.top),w=parseFloat(z.style.width),h=parseFloat(z.style.height);
  return wx>=l&&wx<=l+w&&wy>=t&&wy<=t+h;
 });
 return zone?zone.dataset.team:null;
}
function renderCanvas(){
 $('mcNodes').innerHTML=data.agents.map(a=>'<div class="mc-node'+(selection.has(a.id)?' selectionne':'')+'" data-id="'+a.id+'" data-status="'+esc(a.status)+'" style="left:'+a.x+'px;top:'+a.y+'px"><div class="mc-head"><b>◈ &nbsp;'+esc(a.name)+'</b><div class="mc-role">'+esc(roleName(a.role))+' · '+esc(a.team)+'</div><div class="mc-role">Responsable : '+esc(data.agents.find(m=>m.id===a.manager_id)?.name||'Aucun')+'</div></div><div class="mc-foot"><span class="mc-dot"></span>'+esc(a.status)+' · '+esc(a.model)+'</div></div>').join('')||'<div class="mc-empty">Ton équipe est vide. Clique sur « ＋ Agent » pour créer ton premier assistant. Ensuite, dans Travail, crée la première mission.</div>';
 $('mcZones').innerHTML=zonesMarkup();
 edgeMarkup();transform();dessinerMinimap();marquerSelection();
 $('mcNodes').querySelectorAll('.mc-node').forEach(el=>el.addEventListener('pointerdown',e=>{
  if(e.button!==0)return;e.stopPropagation();
  const id=Number(el.dataset.id);
  if(e.shiftKey){
   if(selection.has(id))selection.delete(id);else selection.add(id);
   marquerSelection();dessinerMinimap();return;
  }
  if(!selection.has(id)){selection.clear();selection.add(id)}
  const positions=data.agents.filter(a=>selection.has(a.id)).map(a=>({id:a.id,x:a.x,y:a.y}));
  drag={type:'node',id,sx:e.clientX,sy:e.clientY,positions,moved:false};
  marquerSelection();el.setPointerCapture(e.pointerId);
 }));
}
$('mcStage').addEventListener('pointerdown',e=>{
 if(e.target.closest('.mc-node,.mc-side,.mc-minimap')||e.button!==0)return;
 selection.clear();marquerSelection();
 drag={type:'pan',sx:e.clientX,sy:e.clientY,x:pan.x,y:pan.y};$('mcStage').setPointerCapture(e.pointerId);
});
document.addEventListener('pointermove',e=>{
 if(!drag||window.mcPage!=='mission')return;
 const dx=e.clientX-drag.sx,dy=e.clientY-drag.sy;
 if(drag.type==='pan'){pan.x=drag.x+dx;pan.y=drag.y+dy;transform();dessinerMinimap();return}
 drag.moved=drag.moved||Math.abs(dx)+Math.abs(dy)>4;
 for(const p of drag.positions){
  const a=data.agents.find(x=>x.id===p.id);if(!a)continue;
  a.x=Math.round(p.x+dx/zoom);a.y=Math.round(p.y+dy/zoom);
  const el=$('mcNodes').querySelector('[data-id="'+p.id+'"]');
  if(el){el.style.left=a.x+'px';el.style.top=a.y+'px'}
 }
 edgeMarkup();dessinerMinimap();
});
document.addEventListener('pointerup',async e=>{
 if(!drag||window.mcPage!=='mission')return;
 const d=drag;drag=null;
 if(d.type!=='node')return;
 if(!d.moved){detail(d.id);return}
 const equipe=equipeSous(e.clientX,e.clientY);
 const bougees=data.agents.filter(a=>selection.has(a.id));
 for(const a of bougees){
  const envoi={id:a.id,x:a.x,y:a.y};
  if(equipe&&equipe!==a.team)envoi.team=equipe;
  try{await post('agent/update',envoi)}catch(err){toast(err.message);break}
 }
 await refresh();
});
$('mcStage').addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.4,Math.min(2,zoom*(e.deltaY<0?1.08:.92)));transform();dessinerMinimap()},{passive:false});
async function aligner(){
 const groupes={};data.agents.forEach(a=>{(groupes[a.team]=groupes[a.team]||[]).push(a)});
 let rang=0,casses=0;
 for(const t of Object.keys(groupes).sort()){
  const liste=groupes[t].sort((a,b)=>a.id-b.id);
  for(let k=0;k<liste.length;k++){
   const x=80+(k%3)*290,y=90+rang*230+Math.floor(k/3)*190;
   try{await post('agent/update',{id:liste[k].id,x,y})}catch(_){casses++}
  }
  rang++;
 }
 await refresh();
 toast(casses?'Alignement partiel ('+casses+' refus)':'Agents alignes par equipe');
}
function createBranche(){
 modal('Nouvelle branche','<p class="subtle">Une branche est gérée par un architecte.</p><label>Nom</label><input id="mcBrName" placeholder="api"><label>Architecte</label><select id="mcBrArchitect">'+agentOptions()+'</select><label>Description</label><textarea id="mcBrDesc"></textarea>',()=>post('branch',{name:$('mcBrName').value,architect_id:$('mcBrArchitect').value||null,description:$('mcBrDesc').value}));
}
function createPlan(){
 const missions=data.missions.map(m=>[m.id,m.title]);
 const modeles=[...new Set(modelesOllama)].map(m=>[m,m]);
 const alerte=modeles.length?'':'<p role="alert">Aucun modèle disponible. Ollama ne répond pas : rien n\'a été lancé.</p><p><button type="button" id="mcPlanRetry">Réessayer le modèle</button></p>';
 modal('Nouveau plan',alerte+'<p class="subtle">Le modele decoupe l\'objectif en taches. Rien n\'est cree avant ton accord.</p><label>Objectif</label><textarea id="mcPlanObjective" placeholder="Ce que l\'equipe doit livrer"></textarea><label>Mission (optionnel)</label><select id="mcPlanMission"><option value="">Aucune</option>'+opts(missions)+'</select><label>Modele</label><select id="mcPlanModel">'+(modeles.length?opts(modeles):'<option value="">Modèle indisponible</option>')+'</select>',async()=>{
  if(!modelesOllama.length)throw Error('Aucun modèle disponible. Rien n\'a été lancé. Réessaie.');
  const bouton=$('submit');
  if(bouton){bouton.disabled=true;bouton.textContent='Le modele reflechit…'}
  const r=await post('plan',{objective:$('mcPlanObjective').value,mission_id:$('mcPlanMission').value||null,model:$('mcPlanModel').value});
  setTimeout(()=>afficherPlan(r),150);
 });
 const retry=$('mcPlanRetry');
 if(retry)retry.onclick=async()=>{retry.disabled=true;try{const r=await fetch('/api/mc/models',{headers:entetes()});const d=await r.json();modelesOllama=d.models||[];}catch(_){modelesOllama=[];}retry.disabled=false;if(modelesOllama.length){fermerModal();createPlan();}else toast('Toujours aucun modèle. Rien n\'a été lancé.');};
}
function afficherPlan(r){
 const taches=r.plan.tasks.map((t,i)=>'<div class="mc-record"><b>'+(i+1)+'. '+esc(t.title)+'</b> · '+esc(t.role)+' · '+(t.depends_on.length?'apres '+t.depends_on.map(x=>x+1).join(', '):'sans prerequis')+'<p>'+esc(t.task)+'</p><small>'+esc((r.assignations[String(t.index)]||{}).agent||'aucun agent')+'</small></div>').join('');
 const alerte=r.roles_sans_agent.length?'<p class="warn">Roles sans agent : '+esc(r.roles_sans_agent.join(', '))+' — cree-les avant d\'appliquer.</p>':'';
 modal('Plan propose',taches+alerte,async()=>{await post('plan/apply',{id:r.id});toast('Plan applique : jobs crees')});
}
async function orchestrer(){
 if(!confirm("Orchestrer lance maintenant les jobs prêts, dans la limite de charge. Aucune proposition n\'est approuvée automatiquement."))return;
 try{const r=await post('orchestrator/run',{});
  toast(r.lances.length?('Lances : '+r.lances.join(', ')):'Rien a lancer ('+r.limite+' place(s), '+r.en_cours+' en cours)');
  await refresh();
 }catch(e){toast(e.message)}
}
function detail(id){
 chosen=id;const a=data.agents.find(x=>x.id===id);if(!a)return;
 const handoffs=data.handoffs.filter(h=>h.agent_id===id);
 const assignments=data.assignments.filter(x=>x.agent_id===id);
 const panel=$('mcDetails');panel.style.display='block';
 const nonLus=(data.messages||[]).filter(m=>!m.read_at&&(m.to_agent===id||(m.to_team&&m.to_team===a.team)));
 const aAcquitter=data.handoffs.filter(h=>h.new_manager_id===id&&!h.ack_at);
 panel.innerHTML='<button id="mcClose" style="float:right">✕</button><h3>'+esc(a.name)+'</h3><small>'+esc(roleName(a.role))+' · '+esc(a.status)+'</small><label>Nom</label><input id="mcEditName" value="'+esc(a.name)+'"><label>Équipe / branche</label><input id="mcEditTeam" value="'+esc(a.team)+'"><label>Responsable (transfert avec passation)</label><select id="mcEditManager">'+opts([['','Aucun responsable'],...data.agents.filter(x=>x.id!==id).map(x=>[x.id,x.name])],a.manager_id||'')+'</select><label>Statut</label><select id="mcEditStatus">'+opts([['idle','En attente'],['working','En cours'],['blocked','Bloqué'],['done','Terminé (déclaré)'],['paused','En pause']],a.status)+'</select><label>Compétences</label><input id="mcEditSkills" value="'+esc(a.skills||'')+'"><label>Modèle Ollama</label><select id="mcEditModel">'+opts([...new Set([a.model,...modelesOllama])].filter(Boolean).map(m=>[m,m]),a.model)+'</select><label>Instructions</label><textarea id="mcEditInstructions">'+esc(a.instructions)+'</textarea><button id="mcSave" class="primary" title="Enregistre le nom, l\'équipe et le responsable. Un nouveau responsable crée une passation.">Enregistrer l\'agent</button><button id="mcClone">Dupliquer</button><button id="mcArchive">Archiver</button><button id="mcContext">Voir le dossier de passation</button><h4>Messages non lus ('+nonLus.length+')</h4>'+nonLus.map(m=>'<div class="mc-record">'+esc(m.body)+'<br><button data-msg="'+m.id+'">Marquer lu</button></div>').join('')+'<h4>Passations à acquitter ('+aAcquitter.length+')</h4>'+aAcquitter.map(h=>'<div class="mc-record">'+esc(h.summary)+'<br><button data-handoff="'+h.id+'">Acquitter</button></div>').join('')+'<h4>Tâches attribuées ('+assignments.length+')</h4>'+assignments.slice(0,6).map(x=>'<div class="mc-record">'+esc(x.task)+'<br><small>'+esc(x.status)+'</small></div>').join('')+'<h4>Passations ('+handoffs.length+')</h4>'+handoffs.slice(0,5).map(x=>'<div class="mc-record">'+esc(x.summary)+'</div>').join('');
 $('mcContext').onclick=async()=>{try{const r=await fetch('/api/mc/context?project='+getProject()+'&agent='+id,{headers:entetes()});if(!r.ok)throw Error('Contexte indisponible');const pack=await r.json();modal('Dossier de passation · '+a.name,'<p class="subtle">Données préparées, non envoyées automatiquement à une IA.</p><textarea id="mcPacket" style="min-height:330px"></textarea>',async()=>{await navigator.clipboard.writeText($('mcPacket').value);toast('Contexte copié')});$('mcPacket').value=JSON.stringify(pack,null,2)}catch(e){toast(e.message)}};
 $('mcClose').onclick=()=>panel.style.display='none';
 $('mcClone').onclick=async()=>{try{await post('agent/clone',{id});await refresh();toast('Agent dupliqué')}catch(e){toast(e.message)}};
 $('mcArchive').onclick=async()=>{if(!confirm('Archiver '+a.name+" ? Il quitte le canvas. Les missions et l\'historique restent."))return;try{await post('agent/archive',{id});await refresh();panel.style.display='none';toast('Agent archivé')}catch(e){toast(e.message)}};
 panel.querySelectorAll('[data-msg]').forEach(b=>b.onclick=async()=>{try{await post('message/read',{id:Number(b.dataset.msg),agent_id:id});await refresh();toast('Message lu')}catch(e){toast(e.message)}});
 panel.querySelectorAll('[data-handoff]').forEach(b=>b.onclick=async()=>{try{await post('handoff/ack',{id:Number(b.dataset.handoff),agent_id:id});await refresh();toast('Passation acquittée')}catch(e){toast(e.message)}});
 $('mcSave').onclick=async()=>{try{await post('agent/update',{id,name:$('mcEditName').value,team:$('mcEditTeam').value,manager_id:$('mcEditManager').value||null,status:$('mcEditStatus').value,model:$('mcEditModel').value,skills:$('mcEditSkills').value,instructions:$('mcEditInstructions').value});await refresh();toast('Agent actualisé et passation enregistrée')}catch(e){toast(e.message)}};
}
function renderRecords(){
 const box=$('mcRecords');
 const jobs=(data.jobs||[]).map(j=>{
  const nom=(data.agents.find(a=>a.id===j.agent_id)||{}).name||'agent inconnu';
  const actions=[];
  if(['queued','failed','cancelled','blocked'].indexOf(j.status)>=0)actions.push(['run','Démarrer']);
  if(j.status==='running')actions.push(['pause','Pause'],['cancel','Arrêter']);
  if(j.status==='paused')actions.push(['resume','Reprendre'],['reject','Refuser']);
  if(j.status==='proposed')actions.push(['approve','Approuver'],['pause','Pause'],['reject','Refuser'],['diff','Voir le diff']);
  if(j.status==='approved')actions.push(['test','Lancer les tests'],['diff','Voir le diff']);
  if(j.status==='approved'||j.status==='completed')actions.push(['review_secu','Audit sécu'],['review_code','Revue code'],['review_tests','Revue tests (humaine)'],['validate','Valider'],['commit','Commit'],['report','Rapport']);
  return '<div class="mc-record"><b>'+esc(j.title)+'</b> · '+esc(nom)+'<p>'+esc(j.task)+'</p><small>'+esc(j.status)+(j.error?' — '+esc(j.error):'')+' · modèle '+esc(j.model)+' · '+esc(libellePreuve((data.assignments.find(x=>x.id===j.assignment_id)||{}).verification||'none'))+'</small><p class="subtle">Approuver écrit la proposition dans le dossier isolé. Valider exige un test réussi et des revues. Commit écrit un commit git, à part.</p><p>'+actions.map(x=>'<button data-job="'+j.id+'" data-action="'+x[0]+'">'+esc(x[1])+'</button>').join(' ')+'</p><details><summary>Journal</summary><pre style="white-space:pre-wrap">'+esc(j.log||'—')+'</pre></details></div>';
 }).join('');
 const plans=(data.plans||[]).map(p=>'<div class="mc-record"><b>'+esc(p.objective)+'</b><small>'+esc(p.status)+' · '+esc(p.created_at)+'</small>'+(p.status==='proposed'?'<p><button data-plan="'+p.id+'">Appliquer</button></p>':'')+'</div>').join('');
 const decisions=(data.decisions||[]).map(d=>'<div class="mc-record"><b>'+esc(d.title)+'</b><p>'+esc(d.decision)+'</p><small>Justification : '+esc(d.rationale)+(d.alternatives?' · Alternatives : '+esc(d.alternatives):'')+' · '+esc(d.created_at)+'</small></div>').join('');
 const recrues=(data.recruits||[]).filter(r=>r.status==='pending').map(r=>'<div class="mc-record"><b>'+esc(r.name)+'</b> · '+esc(roleName(r.role))+' · '+esc(r.team)+'<p>'+esc(r.justification)+'</p><p><button data-recruit="'+r.id+'" data-decision="1">Accepter</button> <button data-recruit="'+r.id+'" data-decision="0">Refuser</button></p></div>').join('');
 box.innerHTML='<h2>Missions, responsabilités et preuves</h2><p class="subtle">Affecte une mission, lance le travail, puis distingue approbation, test et commit. Un état validé vient du serveur.</p><div class="mc-summary"><span>'+data.agents.length+' agents</span><span>'+data.missions.length+' missions</span><span>'+data.assignments.length+' attributions</span><span>'+data.handoffs.length+' passations</span><span>'+(data.jobs||[]).length+' jobs</span><span>'+(data.plans||[]).length+' plans</span></div><h3>Missions</h3>'+(data.missions.length?data.missions.map(m=>'<div class="mc-record"><b>'+esc(m.title)+'</b><p>'+esc(m.objective)+'</p><small>'+esc(m.status)+'</small></div>').join(''):'<p class="mc-empty">Aucune mission. Crée un assistant dans Équipe, puis une mission et une attribution. Le lancement, l\'approbation, le test et le commit sont des actions séparées.</p>')+'<h3>Attributions et vérifications</h3>'+data.assignments.map(a=>'<div class="mc-record"><b>'+esc(data.agents.find(x=>x.id===a.agent_id)?.name||'Agent inconnu')+'</b> · '+esc(a.task)+'<p>'+esc(a.result||'Aucun résultat transmis')+'</p><small>'+esc(a.status)+' · '+esc(libellePreuve(a.verification||'none'))+'</small>'+(a.verification==='test'?'<small>'+esc(a.evidence||'')+'</small>':'')+'<p><button data-assignment="'+a.id+'">Mettre à jour / vérifier</button></p></div>').join('')+'<h3>Branches</h3>'+((data.branches||[]).map(b=>'<div class="mc-record"><b>'+esc(b.name)+'</b> · architecte : '+esc((data.agents.find(a=>a.id===b.architect_id)||{}).name||'aucun')+'<p>'+esc(b.description||'')+'</p></div>').join('')||'<p class="subtle">Aucune branche.</p>')+'<h3>Plans</h3>'+(plans||'<p class="subtle">Aucun plan. « Proposer un plan » dans Travail pour en proposer un.</p>')+'<h3>Décisions</h3>'+(decisions||'<p class="subtle">Aucune décision enregistrée.</p>')+'<h3>Recrutements en attente</h3>'+(recrues||'<p class="subtle">Aucune demande en attente.</p>')+'<h3>Jobs d\'exécution</h3>'+(jobs||'<p class="subtle">Aucun job. « ＋ Job » sur le canvas pour en créer un.</p>')+'<h3>Mémoire de projet</h3>'+data.notes.map(n=>'<div class="mc-record">'+esc(n.content)+'<br><small>'+esc(n.scope)+' · '+esc(n.created_at)+'</small></div>').join('')+'<h3>Passations</h3>'+data.handoffs.map(h=>'<div class="mc-record">'+esc(h.summary)+'</div>').join('')+'<h3>Journal de coordination</h3>'+data.audit.slice(0,25).map(a=>'<div class="mc-record"><small>'+esc(a.created_at)+' · '+esc(a.action)+'</small></div>').join('');
 box.querySelectorAll('[data-plan]').forEach(b=>b.onclick=async()=>{try{await post('plan/apply',{id:Number(b.dataset.plan)});await refresh();toast('Plan appliqué : jobs créés')}catch(e){toast(e.message)}});
 box.querySelectorAll('[data-recruit]').forEach(b=>b.onclick=async()=>{try{await post('recruit/decide',{id:Number(b.dataset.recruit),approve:b.dataset.decision==='1'});await refresh();toast(b.dataset.decision==='1'?'Recrutement accepté':'Recrutement refusé')}catch(e){toast(e.message)}});
 box.querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>{const id=Number(b.dataset.job),action=b.dataset.action;
  if(action==='diff')return voirDiff(id);
  if(action==='review_secu')return agirSurJob(id,'review_secu');
  if(action==='review_code')return revueCode(id);
  if(action==='validate')return validerJob(id);
  if(action==='commit')return committerJob(id);
  if(action==='report')return voirRapport(id);
  if(action==='test')return choisirTest(id);
  return agirSurJob(id,action)});
 box.querySelectorAll('[data-assignment]').forEach(b=>b.onclick=()=>{const a=data.assignments.find(a=>a.id===Number(b.dataset.assignment));
  const etabli=['test','validated','approved','refused'].indexOf(a.verification)>=0;
  const champ=etabli?'<p>Preuve : <strong>'+esc(libellePreuve(a.verification))+"</strong>. Le serveur l\'a établie. Ce formulaire ne la remplace pas.</p>":'<label>Déclaration</label><select id="mcAsVerif">'+opts([['none','Non vérifié'],['declared','Déclaré'],['human','Revu par une personne']],a.verification||'none')+'</select>';
  modal('Mettre à jour le suivi','<p class="subtle">Une revue humaine est une lecture. Un test exécuté ou une validation ne se déclarent pas ici.</p><label>Statut</label><select id="mcAsStatus">'+opts([['queued','À faire'],['working','En cours'],['blocked','Bloqué'],['done','Terminé'],['reviewed','Revu']],a.status)+'</select><label>Résultat</label><textarea id="mcAsResult">'+esc(a.result)+'</textarea>'+champ,async()=>{const corps={id:a.id,status:$('mcAsStatus').value,result:$('mcAsResult').value};if(!etabli)corps.verification=$('mcAsVerif').value;await post('assignment/update',corps)},'Enregistrer le suivi')});
}
function render(){remplirActeurs();$('mcStage').style.display=mode==='agents'?'block':'none';$('mcRecords').style.display=mode==='missions'?'block':'none';if(mode==='agents'){renderCanvas();if(chosen&&data.agents.some(a=>a.id===chosen))detail(chosen)}else renderRecords()}
setInterval(()=>{tic++;if(window.mcPage!=='mission'||drag||window.mcModal||$('mcDetails').style.display!=='none')return;
 // Rafraîchissement rapproché tant qu'un job travaille, lent sinon.
 const actif=(data.jobs||[]).some(j=>['running','queued','paused'].indexOf(j.status)>=0);
 if(actif||tic%6===0)refresh();},2500);
function surveillerService(){
 const dot=document.getElementById('serviceDot');
 if(!dot)return;
 fetch('/api/mc/version',{headers:entetes()}).then(r=>{
  dot.classList.toggle('hors-ligne',!r.ok);
  dot.setAttribute('aria-label',r.ok?'Service local en ligne':'Service local injoignable');
 }).catch(()=>{dot.classList.add('hors-ligne');dot.setAttribute('aria-label','Hors ligne : le service local ne répond pas');});
}
surveillerService();
setInterval(surveillerService,15000);
document.addEventListener('keydown',e=>{
 if(e.key==='Escape'&&window.mcModal){e.preventDefault();fermerModal();return;}
 if(e.key!=='Tab')return;
 const boite=window.mcModal?$('modalback'):(document.getElementById('mcAuth')&&document.getElementById('mcAuth').open?document.getElementById('mcAuth'):null);
 if(!boite||(boite.id==='modalback'&&!boite.classList.contains('open')))return;
 const focusables=[...boite.querySelectorAll('button,input,select,textarea')].filter(el=>!el.disabled&&el.offsetParent!==null);
 if(focusables.length<2)return;
 const premier=focusables[0],dernier=focusables[focusables.length-1];
 if(e.shiftKey&&document.activeElement===premier){e.preventDefault();dernier.focus();}
 else if(!e.shiftKey&&document.activeElement===dernier){e.preventDefault();premier.focus();}
});
let essaisProjet=0;
function demarrerMission(){
 essaisProjet++;
 if(!getProject()&&essaisProjet<40){setTimeout(demarrerMission,50);return;}
 window.mcPage='legacy';nav.classList.add('legacy-open');document.body.classList.add('legacy-page');showPage('canvas');
}
demarrerMission();
})();
