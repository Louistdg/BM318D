from pathlib import Path
p=Path('MissionControl.py')
s=p.read_text(encoding='utf-8')
needle='def dispatch(c,path,d):'
context="""def context_packet(c,p,i):
 a=agent(c,p,i)
 manager=agent(c,p,a['manager_id']) if a['manager_id'] else None
 notes=rows(c,"SELECT scope,content,created_at FROM mc_notes WHERE project_id=? AND (scope='project' OR (scope='team' AND (agent_id IS NULL OR agent_id IN (SELECT id FROM mc_agents WHERE project_id=? AND team=?))) OR (scope='agent' AND agent_id=?)) ORDER BY id DESC LIMIT 40",(p,p,a['team'],i))
 assignments=rows(c,"SELECT m.title AS mission,a.task,a.status,a.result,a.verified FROM mc_assignments a JOIN mc_missions m ON m.id=a.mission_id WHERE m.project_id=? AND a.agent_id=? ORDER BY a.id DESC LIMIT 30",(p,i))
 handoffs=rows(c,"SELECT summary,created_at FROM mc_handoffs WHERE project_id=? AND agent_id=? ORDER BY id DESC LIMIT 10",(p,i))
 colleagues=rows(c,"SELECT id,name,role,team FROM mc_agents WHERE project_id=? AND team=? AND id<>? ORDER BY id",(p,a['team'],i))
 return {'agent':{'id':i,'name':a['name'],'role':a['role'],'team':a['team'],'instructions':a['instructions'],'manager':manager['name'] if manager else None},'notes':notes,'assignments':assignments,'handoffs':handoffs,'colleagues':colleagues,'warning':'Dossier de contexte préparé automatiquement. Aucun message transmis à un modèle ou agent externe.'}
"""
assert needle in s
s=s.replace(needle,context+needle)
needle2="  if self.path.startswith('/api/mc/state?'):"
new="""  if self.path.startswith('/api/mc/context?'):
   from urllib.parse import parse_qs,urlsplit
   try:
    q=parse_qs(urlsplit(self.path).query);p=int(q['project'][0]);i=int(q['agent'][0])
    with connect() as c:project(c,p);result=context_packet(c,p,i)
    self.reply(result)
   except (ValueError,KeyError) as e:self.reply({'error':str(e)},400)
   return
"""
assert needle2 in s
s=s.replace(needle2,new+needle2)
p.write_text(s,encoding='utf-8')
print('CONTEXT_PACKET_ADDED')
