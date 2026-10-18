/* BM318d V2.5 workspace: presentation and operator-only project documents. */
(() => {
 'use strict';
 const safe = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
 const rail = document.querySelector('.rail');
 const main = document.querySelector('.main');
 const token = (document.querySelector('meta[name="mc-token"]') || {}).content || '';
 const widthKey = 'bm318d.sidebar.width.v1', collapsedKey = 'bm318d.sidebar.collapsed.v1';
 const mobile = () => matchMedia('(max-width:760px)').matches;
 const clamp = value => Math.max(168, Math.min(330, Math.round(Number(value) || 216)));
 let width = clamp(localStorage.getItem(widthKey) || 216);
 let collapsed = localStorage.getItem(collapsedKey) === 'true';
 const labels = {canvas:'Canevas',overview:"Vue d’ensemble",tasks:'Tâches',agents:'Agent IA local',events:'Journal',documents:'Dossiers & fiches',mission:'Mission Control'};
 const symbols = {canvas:'◇',overview:'▦',tasks:'☷',agents:'◈',events:'▤',documents:'▣',mission:'◎'};
 function widthApply(value, remember = false) {
   width = clamp(value);
   rail.style.setProperty('--sidebar-width',width + 'px');
   const grip = document.getElementById('sidebarGrip');
   if (grip) grip.setAttribute('aria-valuenow',String(width));
   if (remember) localStorage.setItem(widthKey,String(width));
 }
 function collapsedApply(value) {
   collapsed = Boolean(value);
   document.body.classList.toggle('sidebar-collapsed', collapsed);
   const toggle = document.getElementById('sidebarToggle');
   if (toggle) {
     toggle.setAttribute('aria-expanded',String(!collapsed));
     toggle.setAttribute('aria-label',collapsed?'Déplier la navigation':'Replier la navigation');
     toggle.title = collapsed?'Déplier la navigation':'Replier la navigation';
   }
   localStorage.setItem(collapsedKey,String(collapsed));
 }
 const brand = document.createElement('span');
 brand.className='nav-brand';brand.textContent='BM318d';
 rail.querySelector('.logo').append(brand);
 const toggle=document.createElement('button');
 toggle.type='button';toggle.id='sidebarToggle';toggle.className='sidebar-toggle';
 toggle.textContent='☰';toggle.onclick=()=>{
   if (mobile()) {
     document.body.classList.toggle('sidebar-mobile-open');
     toggle.setAttribute('aria-expanded',String(document.body.classList.contains('sidebar-mobile-open')));
   } else collapsedApply(!collapsed);
 };
 rail.querySelector('.logo').after(toggle);
 const docButton=document.createElement('button');
 docButton.type='button';docButton.dataset.page='documents';docButton.title='Dossiers et fiches du projet';
 const missionButton=rail.querySelector('[data-page="mission"]');
 rail.querySelector('button[data-page="tasks"]').after(docButton);
 rail.insertBefore(missionButton,rail.querySelector('#reset'));
 for (const b of rail.querySelectorAll('button[data-page]')) {
   const p=b.dataset.page;
   b.innerHTML='<span class="nav-icon" aria-hidden="true">'+symbols[p]+'</span><span class="nav-label">'+safe(labels[p])+'</span>';
   b.setAttribute('aria-label',labels[p]);
   b.title=labels[p];
 }
 const reset=rail.querySelector('#reset');
 if (reset) {reset.setAttribute('aria-label','Recentrer le canevas');reset.innerHTML='<span class="nav-icon" aria-hidden="true">⌖</span><span class="nav-label">Recentrer</span>';}
 const grip=document.createElement('div');
 grip.id='sidebarGrip';grip.className='sidebar-grip';grip.tabIndex=0;grip.setAttribute('role','separator');
 grip.setAttribute('aria-label','Ajuster la largeur de la navigation');
 grip.setAttribute('aria-orientation','vertical');grip.setAttribute('aria-valuemin','168');grip.setAttribute('aria-valuemax','330');
 rail.append(grip);
 widthApply(width);collapsedApply(collapsed);
 if(mobile())toggle.setAttribute('aria-expanded','false');
 let resizing=false;
 grip.addEventListener('pointerdown',e=>{if(mobile()||collapsed||e.button!==0)return;resizing=true;grip.setPointerCapture(e.pointerId);e.preventDefault()});
 grip.addEventListener('pointermove',e=>{if(resizing)widthApply(e.clientX-rail.getBoundingClientRect().left)});
 grip.addEventListener('pointerup',()=>{if(resizing){resizing=false;widthApply(width,true)}});
 grip.addEventListener('pointercancel',()=>{resizing=false});
 grip.addEventListener('keydown',e=>{
   const delta=e.key==='ArrowRight'?16:e.key==='ArrowLeft'?-16:0;
   if (delta || e.key==='Home' || e.key==='End') {e.preventDefault();widthApply(e.key==='Home'?168:e.key==='End'?330:width+delta,true)}
 });
 rail.addEventListener('click',e=>{
   const b=e.target.closest('button[data-page]');if(!b)return;
   if (b.dataset.page!=='mission') {
     window.mcPage='legacy';rail.classList.add('legacy-open');document.body.classList.add('legacy-page');
     if (b.dataset.page==='overview') refreshOverview();
     if (b.dataset.page==='documents') {showDocuments();refreshDocuments();}
   }
   if (mobile())document.body.classList.remove('sidebar-mobile-open');
 });
 docButton.onclick=()=>showDocuments();
 const before= document.getElementById('ancienTableau');
 if(before)before.textContent='Canevas';

 /* Overview uses the existing project tasks and the authenticated real Mission Control snapshot. */
 let overviewData=null, overviewProject=null, overviewRequest=0;
 async function refreshOverview() {
   const p=Number(project), request=++overviewRequest;
   if(!p){if(overviewRequest<40)setTimeout(refreshOverview,250);return;}
   overviewProject=p;overviewData=null;
   try {
     const response=await fetch('/api/mc/state?project='+encodeURIComponent(p),{headers:{'X-MC-Token':token},cache:'no-store'});
     if(!response.ok)throw Error('État de Mission Control indisponible');
     const data=await response.json();
     if(request!==overviewRequest||Number(project)!==p)return;
     overviewData=data;
   } catch(err) {
     if(request!==overviewRequest)return;
     overviewData={error:err.message};
   }
   renderOverview();
 }
 const metrics=document.getElementById('metrics');
 const work=document.createElement('div');work.id='overviewWork';work.className='overview-work';
 metrics.after(work);
 document.getElementById('recent').previousElementSibling.textContent='Missions et actions à suivre';
 document.getElementById('agentCards').previousElementSibling.textContent='Agents enregistrés dans ce projet';
 renderOverview=function () {
   const ts=tasks();
   const enCours=ts.filter(t=>t[5]==='En cours');
   const terminees=ts.filter(t=>t[5]==='Validée'||t[5]==='Terminée (déclarée)');
   const bloquees=ts.filter(t=>t[5]==='Bloquée');
   const metr=[['Tâches',ts.length],['En cours',enCours.length],['Terminées',terminees.length],['Bloquées',bloquees.length]];
   metrics.innerHTML=metr.map(([name,count])=>'<div class="metric"><div class="caption">'+safe(name)+'</div><div class="num">'+count+'</div></div>').join('');
   const tasksBlock=(title,list)=>'<div class="panel"><h3>'+title+'</h3>'+(list.length?list.slice(0,5).map(t=>'<button class="overview-task" data-overview-task="'+t[0]+'">'+safe(t[2])+' <small>'+safe(t[5])+'</small></button>').join(''):'<p class="subtle">Aucune tâche.</p>')+'</div>';
   work.innerHTML=tasksBlock('En cours',enCours)+tasksBlock('Bloquées',bloquees)+tasksBlock('Terminées',terminees);
   work.querySelectorAll('[data-overview-task]').forEach(b=>b.onclick=()=>{showPage('canvas');detail(Number(b.dataset.overviewTask))});
   const area=document.getElementById('agentCards'),recent=document.getElementById('recent');
   if(overviewProject!==Number(project) || !overviewData) {
     area.innerHTML='<p class="subtle">Chargement des agents du projet…</p>';
     recent.innerHTML='<p class="subtle">Chargement des missions et de leur état…</p>';return;
   }
   if(overviewData.error) {area.innerHTML='<p role="alert">'+safe(overviewData.error)+'</p>';recent.innerHTML='<p class="subtle">Aucune donnée inventée.</p>';return;}
   const agents=overviewData.agents||[], missions=overviewData.missions||[], jobs=overviewData.jobs||[], assignments=overviewData.assignments||[];
   area.innerHTML=agents.length?agents.map(a=>'<div class="agent"><strong>'+safe(a.name)+'</strong><p>'+safe(a.role)+' · '+safe(a.team)+'</p><span class="pill">'+safe(a.status)+'</span></div>').join(''):'<p class="subtle">Aucun agent Mission Control enregistré dans ce projet.</p>';
   const attention=jobs.filter(j=>['failed','blocked','proposed','paused'].includes(j.status)).slice(0,5);
   const restes=assignments.filter(a=>['blocked','queued','working'].includes(a.status)).slice(0,4);
   const lines=attention.map(j=>'<div class="eventline"><span><strong>'+safe(j.title)+'</strong> · '+safe(j.status)+'</span><span class="subtle">Job #'+j.id+'</span></div>')
     .concat(restes.map(a=>'<div class="eventline"><span>'+safe(a.task)+' · '+safe(a.status)+'</span><span class="subtle">Attribution #'+a.id+'</span></div>'));
   recent.innerHTML='<p class="subtle">'+missions.length+' mission(s) · '+jobs.length+' job(s) récemment chargés · '+assignments.length+' attribution(s)</p>'+
     (lines.join('')||'<p class="subtle">Aucune action bloquée ou en attente dans les missions.</p>')+
     '<h3>Missions</h3>'+(missions.length?missions.slice(0,6).map(m=>'<div class="eventline"><strong>'+safe(m.title)+'</strong><span class="pill">'+safe(m.status)+'</span></div>').join(''):'<p class="subtle">Aucune mission créée.</p>');
 };
 const projectSelect=document.getElementById('project');
 projectSelect.addEventListener('change',()=>{overviewData=null;overviewProject=null;currentFolder=null;selectedDoc=null;refreshOverview();if(page==='documents')refreshDocuments()});
 refreshOverview();
 setInterval(()=>{if(page==='overview')refreshOverview()},18000);

 /* Task edits reuse the existing task details and the project-checked legacy API. */
 const editTask=document.createElement('button');editTask.type='button';editTask.id='editTask';editTask.textContent='Modifier la tâche';
 document.getElementById('saveStatus').after(editTask);
 editTask.onclick=()=>{
   const t=tasks().find(t=>t[0]===selected);if(!t)return;
   openModal('Modifier la tâche','<label>Titre</label><input id="taskEditTitle" maxlength="300" value="'+safe(t[2])+'"><label>Priorité</label><input id="taskEditPriority" maxlength="30" value="'+safe(t[3])+'"><label>Responsable déclaré</label><input id="taskEditAgent" maxlength="80" value="'+safe(t[4])+'">',
   ()=>api('/api/task/update',{id:t[0],project,title:document.getElementById('taskEditTitle').value,priority:document.getElementById('taskEditPriority').value,agent:document.getElementById('taskEditAgent').value}));
 };

 /* Documents: all records are project scoped server-side. Nothing reaches local agent tools or the filesystem. */
 const section=document.createElement('section');section.id='documents';section.className='view';
 section.innerHTML='<div class="documents-layout"><header class="documents-header"><div><h2>Dossiers & fiches</h2><p class="subtle">Organise tes notes, liens et informations de projet. Les modifications sont enregistrées dans SQLite.</p></div><div class="documents-actions"><button id="docNewFolder">＋ Dossier</button><button id="docNewFile">＋ Fiche</button></div></header><div class="documents-body"><aside class="documents-tree"><strong>Arborescence</strong><div id="docTree"></div></aside><div class="documents-board"><div class="documents-path" id="docPath"></div><div class="documents-scroll" id="docScroll"><div class="documents-world" id="docWorld"></div></div><p class="documents-hint">Déplace les fiches sur le canevas. Ouvre un dossier pour parcourir son contenu ; « Modifier » permet de changer de dossier.</p></div><aside id="docDetails" class="documents-details" hidden></aside></div></div>';
 main.append(section);
 let documents=[],currentFolder=null,selectedDoc=null,documentsProject=null,docLoading=false,docDirty=false,docDrag=null;
 const docEl=id=>document.getElementById(id);
 function showDocuments(){
   window.mcPage='legacy';
   showPage('documents');
   docEl('pageTitle').textContent='Dossiers & fiches';
 }
 function docItem(id){return documents.find(x=>x.id===id);}
 async function docApi(action,data={}) {
   const url='/api/mc/documents/'+action;
   const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-MC-Token':token},body:JSON.stringify({project:Number(project),...data})});
   let result={};try{result=await response.json()}catch(_){}
   if(!response.ok)throw Error(result.error||'Écriture refusée ('+response.status+')');
   return result;
 }
 async function refreshDocuments(){
   if(!project)return;
   const p=Number(project);documentsProject=p;docLoading=true;
   docEl('docWorld').innerHTML='<p class="subtle">Chargement…</p>';
   try{
     const r=await fetch('/api/mc/documents?project='+encodeURIComponent(p),{headers:{'X-MC-Token':token},cache:'no-store'});
     const d=await r.json();if(!r.ok)throw Error(d.error||'Lecture refusée');
     if(Number(project)!==p)return;
     documents=Array.isArray(d.items)?d.items:[];
     if(currentFolder&&!documents.some(x=>x.id===currentFolder&&x.kind==='folder'))currentFolder=null;
     if(selectedDoc&&!docItem(selectedDoc))selectedDoc=null;
     renderDocuments();
   }catch(e){if(Number(project)===p){docEl('docWorld').innerHTML='<p role="alert">'+safe(e.message)+'</p>';notify(e.message)}}
   finally{docLoading=false;}
 }
 function folderChoices(item){
   return '<option value="">Racine du projet</option>'+documents.filter(x=>x.kind==='folder'&&(!item||x.id!==item.id)).map(x=>'<option value="'+x.id+'">'+safe(x.title)+'</option>').join('');
 }
 function docEditor(item,kind='file'){
   const editing=Boolean(item),folder=kind==='folder';
   docDirty=false;
   openModal(editing?'Modifier '+(folder?'le dossier':'la fiche'):folder?'Créer un dossier':'Créer une fiche',
     '<label>Titre</label><input id="docTitle" maxlength="160" required value="'+safe(item?.title||'')+'">'+
     '<label>Dossier parent</label><select id="docParent">'+folderChoices(item)+'</select>'+
     (folder?'':'<label>Type de contenu</label><select id="docContentType"><option value="note">Notes</option><option value="link">Liens</option><option value="info">Informations du projet</option></select><label>Contenu</label><textarea id="docContent" maxlength="8000" placeholder="Notes, liens ou informations…">'+safe(item?.content||'')+'</textarea>')+
     (editing?'<p><button type="button" id="docDelete" class="doc-danger">Supprimer cette fiche</button></p>':''),
     async()=>{
       const payload={kind,title:docEl('docTitle').value,parent_id:docEl('docParent').value?Number(docEl('docParent').value):null};
       if(!folder){payload.content_type=docEl('docContentType').value;payload.content=docEl('docContent').value}
       if(item){payload.id=item.id;payload.revision=item.revision}
       else {payload.x=120+(documents.length%4)*225;payload.y=110+Math.floor(documents.length/4)*175}
       await docApi('save',payload);docDirty=false;await refreshDocuments();
     });
   docEl('docParent').value=item?.parent_id ?? currentFolder ?? '';
   if(!folder)docEl('docContentType').value=item?.content_type||'note';
   const fields=docEl('modalFields');
   fields.querySelectorAll('input,select,textarea').forEach(el=>el.addEventListener('input',()=>{docDirty=true}));
   if(editing)docEl('docDelete').onclick=async()=>{
     if(!confirm('Supprimer « '+item.title+' » ? Cette action n’efface pas les autres fiches.'))return;
     try{await docApi('delete',{id:item.id,revision:item.revision});docDirty=false;closeModal();await refreshDocuments()}
     catch(e){notify(e.message);await refreshDocuments()}
   };
 }
 function selectDoc(item){
   selectedDoc=item.id;
   const panel=docEl('docDetails');panel.hidden=false;
   panel.innerHTML='<button type="button" id="docClose">× Fermer</button><p class="subtle">'+(item.kind==='folder'?'DOSSIER':safe(item.content_type).toUpperCase())+'</p><h3>'+safe(item.title)+'</h3><div class="doc-preview" id="docPreview"></div><button id="docModify">Modifier</button>'+(item.kind==='folder'?'<button id="docOpenFolder">Ouvrir ce dossier</button>':'');
   const preview=docEl('docPreview');preview.textContent=item.kind==='folder'?'Dossier du projet':item.content||'Aucun contenu';
   if(item.content_type==='link'&&item.kind==='file'){
     const lines=item.content.split(/\s+/).filter(Boolean), links=lines.filter(x=>{try{return ['http:','https:'].includes(new URL(x).protocol)}catch(_){return false}});
     for(const address of links.slice(0,8)){const anchor=document.createElement('a');anchor.href=address;anchor.target='_blank';anchor.rel='noopener noreferrer';anchor.textContent='Ouvrir le lien';preview.append(document.createElement('br'),anchor)}
   }
   docEl('docClose').onclick=()=>{selectedDoc=null;panel.hidden=true};
   docEl('docModify').onclick=()=>docEditor(item,item.kind);
   if(item.kind==='folder')docEl('docOpenFolder').onclick=()=>{currentFolder=item.id;selectedDoc=null;renderDocuments()};
 }
 function renderDocuments(){
   const p=docEl('docPath');
   const hierarchy=[];let parent=currentFolder;const visited=new Set();
   while(parent && !visited.has(parent)){visited.add(parent);const it=docItem(parent);if(!it)break;hierarchy.unshift(it);parent=it.parent_id}
   p.innerHTML='<button data-doc-root>Projet</button>'+hierarchy.map(x=>' <span>›</span> <button data-doc-path="'+x.id+'">'+safe(x.title)+'</button>').join('');
   p.querySelector('[data-doc-root]').onclick=()=>{currentFolder=null;selectedDoc=null;renderDocuments()};
   p.querySelectorAll('[data-doc-path]').forEach(b=>b.onclick=()=>{currentFolder=Number(b.dataset.docPath);selectedDoc=null;renderDocuments()});
   const children=parentId=>documents.filter(x=>x.parent_id===parentId&&x.kind==='folder');
   const tree=(parentId,depth=0,seen=new Set())=>children(parentId).filter(x=>!seen.has(x.id)).map(x=>'<button type="button" class="'+(currentFolder===x.id?'active':'')+'" style="padding-left:'+(12+depth*14)+'px" data-doc-folder="'+x.id+'">▣ '+safe(x.title)+'</button>'+tree(x.id,depth+1,new Set([...seen,x.id]))).join('');
   docEl('docTree').innerHTML='<button class="'+(currentFolder===null?'active':'')+'" data-doc-folder="">⌂ Racine du projet</button>'+tree(null);
   docEl('docTree').querySelectorAll('[data-doc-folder]').forEach(b=>b.onclick=()=>{currentFolder=b.dataset.docFolder?Number(b.dataset.docFolder):null;selectedDoc=null;renderDocuments()});
   const list=documents.filter(x=>x.parent_id===currentFolder);
   const maxX=Math.max(1100,...list.map(x=>x.x+290)),maxY=Math.max(700,...list.map(x=>x.y+210));
   const world=docEl('docWorld');world.style.width=Math.min(11000,maxX)+'px';world.style.height=Math.min(11000,maxY)+'px';
   world.innerHTML=list.length?list.map(x=>'<article class="doc-card" tabindex="0" data-doc-id="'+x.id+'" style="left:'+x.x+'px;top:'+x.y+'px"><strong>'+(x.kind==='folder'?'▣ ':'▤ ')+safe(x.title)+'</strong><small>'+(x.kind==='folder'?'Dossier':safe(({note:'Notes',link:'Liens',info:'Informations'})[x.content_type]||'Fiche'))+'</small><p>'+safe(x.kind==='folder'?'Ouvrir pour consulter':x.content.slice(0,115))+'</p><div class="doc-card-actions"><button type="button" data-doc-edit="'+x.id+'">Modifier</button>'+(x.kind==='folder'?'<button type="button" data-doc-open="'+x.id+'">Ouvrir</button>':'')+'</div></article>').join(''):'<p class="doc-empty">Cet espace est vide. Crée un dossier ou une fiche.</p>';
   for(const card of world.querySelectorAll('.doc-card')) {
     const ident=Number(card.dataset.docId);
     card.onclick=e=>{if(card.dataset.dragged==='true'||e.target.closest('button'))return;selectDoc(docItem(ident))};
     card.onkeydown=e=>{if(e.target===card&&(e.key==='Enter'||e.key===' ')){e.preventDefault();selectDoc(docItem(ident))}};
     card.addEventListener('pointerdown',e=>{
       if(e.button!==0||e.target.closest('button'))return;
       const it=docItem(ident);
       docDrag={card,it,startX:e.clientX,startY:e.clientY,x:it.x,y:it.y,moved:false};
       card.setPointerCapture(e.pointerId);
     });
     card.addEventListener('pointermove',e=>{
       if(!docDrag||docDrag.card!==card)return;
       const dx=e.clientX-docDrag.startX,dy=e.clientY-docDrag.startY;
       if(Math.abs(dx)+Math.abs(dy)>5)docDrag.moved=true;
       if(docDrag.moved){card.style.left=Math.max(0,Math.min(10000,docDrag.x+dx))+'px';card.style.top=Math.max(0,Math.min(10000,docDrag.y+dy))+'px'}
     });
     card.addEventListener('pointerup',async e=>{
       if(!docDrag||docDrag.card!==card)return;
       const drag=docDrag;docDrag=null;
       if(!drag.moved)return;
       card.dataset.dragged='true';
       const x=Math.max(0,Math.min(10000,Math.round(drag.x+e.clientX-drag.startX)));
       const y=Math.max(0,Math.min(10000,Math.round(drag.y+e.clientY-drag.startY)));
       try{await docApi('save',{id:ident,revision:drag.it.revision,x,y});await refreshDocuments()}
       catch(err){notify(err.message);await refreshDocuments()}
     });
     card.addEventListener('pointercancel',()=>{docDrag=null;renderDocuments()});
   }
   world.querySelectorAll('[data-doc-edit]').forEach(b=>b.onclick=e=>{e.stopPropagation();const x=docItem(Number(b.dataset.docEdit));docEditor(x,x.kind)});
   world.querySelectorAll('[data-doc-open]').forEach(b=>b.onclick=e=>{e.stopPropagation();currentFolder=Number(b.dataset.docOpen);selectedDoc=null;renderDocuments()});
   const panel=docEl('docDetails');
   if(selectedDoc&&docItem(selectedDoc))selectDoc(docItem(selectedDoc));else panel.hidden=true;
 }
 docEl('docNewFolder').onclick=()=>docEditor(null,'folder');
 docEl('docNewFile').onclick=()=>docEditor(null,'file');
 /* The legacy modal can otherwise close without reporting an unsaved draft. */
 for(const b of [document.getElementById('cancel'),document.getElementById('modalback')]){
   b.addEventListener('click',e=>{
     if(!docDirty||!docEl('docTitle'))return;
     if(b.id==='modalback' && e.target!==b)return;
     if(!confirm('Abandonner les modifications non enregistrées ?')){e.stopImmediatePropagation();e.preventDefault();return}
     docDirty=false;
   },true);
 }
 window.addEventListener('beforeunload',e=>{if(docDirty){e.preventDefault();e.returnValue=''}});
 /* Chat stays read-only; merely position the existing selector in the composer. */
 const chatbar=document.getElementById('chatbar'),selector=document.getElementById('chatModel');
 if(chatbar&&selector){selector.setAttribute('aria-label','Modèle local de cette conversation');chatbar.insertBefore(selector,document.getElementById('sendAI'));}
 document.querySelector('#agents .dash h2 span').textContent='Discussion avec l’agent IA local';
})();
