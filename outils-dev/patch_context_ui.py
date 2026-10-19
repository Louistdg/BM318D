from pathlib import Path
p=Path('mission.js');s=p.read_text(encoding='utf-8')
old="""'<button id="mcSave" class="primary">Enregistrer / Transférer</button><h4>Tâches attribuées ('"""
new="""'<button id="mcSave" class="primary">Enregistrer / Transférer</button><button id="mcContext">Voir le dossier de passation</button><h4>Tâches attribuées ('"""
assert old in s
s=s.replace(old,new)
needle=" $('mcClose').onclick=()=>panel.style.display='none';"
insert=""" $('mcContext').onclick=async()=>{try{const r=await fetch('/api/mc/context?project='+getProject()+'&agent='+id);if(!r.ok)throw Error('Contexte indisponible');const pack=await r.json();modal('Dossier de passation · '+a.name,'<p class="subtle">Données préparées, non envoyées automatiquement à une IA.</p><textarea id="mcPacket" style="min-height:330px"></textarea>',async()=>{await navigator.clipboard.writeText($('mcPacket').value);toast('Contexte copié')});$('mcPacket').value=JSON.stringify(pack,null,2)}catch(e){toast(e.message)}};
"""
assert needle in s
s=s.replace(needle,insert+needle)
p.write_text(s,encoding='utf-8')
print('CONTEXT_UI_ADDED')
