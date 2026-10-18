from pathlib import Path
p=Path('BM318d-Railway.html')
s=p.read_text(encoding='utf-8')
# Improve empty state and interaction hints
s=s.replace('Glisser pour déplacer · Molette pour zoomer · Cliquer pour les détails','Glisser une carte · Déplacer le fond · Molette : zoom · Cliquer : détails')
s=s.replace("function renderCanvas(){const list=tasks();","function renderCanvas(){const list=tasks();")
s=s.replace("document.querySelectorAll('.node').forEach(el=>el.addEventListener('pointerdown'", "document.querySelectorAll('.node').forEach(el=>el.addEventListener('pointerdown'")
# Keep the SVG arrows attached to cards while moving, without rerendering the nodes.
needle="const pos=new Map(tasks().map((t,i)=>[t[0],position(t,i)]));pos.set(drag.id,{x:drag.x+dx/scale,y:drag.y+dy/scale});$('links').innerHTML=$('links').innerHTML.replace(/<path d=\"M[\\s\\S]*$/,'');/* full refresh on release */"
replacement="const pos=new Map(tasks().map((t,i)=>[t[0],position(t,i)]));pos.set(drag.id,{x:drag.x+dx/scale,y:drag.y+dy/scale});drawEdges(pos);"
if needle not in s:
 needle="const pos=new Map(tasks().map((t,i)=>[t[0],position(t,i)]));pos.set(drag.id,{x:drag.x+dx/scale,y:drag.y+dy/scale});"
assert needle in s, 'drag code missing'
s=s.replace(needle,replacement)
# Centralize edge rendering, using same SVG path syntax as initial canvas.
marker="function transform(){$('world').style.transform="
insert="""function drawEdges(positions){$('links').innerHTML='<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#aa8de4"/></marker></defs>'+state.edges.filter(([a,b])=>positions.has(a)&&positions.has(b)).map(([a,b])=>{const p=positions.get(b),q=positions.get(a);const x=p.x+250,y=p.y+64,X=q.x,Y=q.y+64;return '<path d="M'+x+' '+y+' C'+(x+100)+' '+y+','+(X-100)+' '+Y+','+X+' '+Y+'" fill="none" stroke="#a78be1" stroke-width="2.5" marker-end="url(#arrow)"/>'}).join('')}
"""
assert marker in s
s=s.replace(marker,insert+marker)
# avoid silent failure when no task is present
s=s.replace("document.querySelectorAll('.node').forEach(el=>el.addEventListener('pointerdown'", "if(!list.length){$('nodes').innerHTML='<div style=\"position:absolute;left:140px;top:135px;background:#211d2b;border:1px dashed #665676;border-radius:18px;padding:28px;width:350px;color:#bdb1cc\"><b style=\"color:#eee;font-size:17px\">Ton canvas est prêt</b><p>Crée une tâche avec le bouton ＋ Tâche pour faire apparaître ta première carte.</p></div>'}document.querySelectorAll('.node').forEach(el=>el.addEventListener('pointerdown'")
# avoid refreshing while editing a modal or details panel
s=s.replace("if(!drag&&page!=='agents')load()","if(!drag&&page!=='agents'&&!$('modalback').classList.contains('open')&&!$('details').classList.contains('open'))load()")
p.write_text(s,encoding='utf-8')
print('PATCH_OK',len(s))
