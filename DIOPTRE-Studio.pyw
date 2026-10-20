import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3, json, urllib.request, threading, http.server, os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
MODELE=os.environ.get('MC_OLLAMA_MODEL') or 'qwen2.5:3b'
PORT_API=int(os.environ.get('MC_PC_PORT') or 31878)
DB=ROOT/'dioptre.sqlite3'
C={'bg':'#100e17','sidebar':'#171320','panel':'#201b2b','panel2':'#282137','stroke':'#433750','text':'#f3edf9','muted':'#b4a8c3','accent':'#aa82f5','green':'#67d5a4','orange':'#f5b96e','red':'#f08392','blue':'#83b8f4'}
def sql(query,args=(),write=False):
    with sqlite3.connect(DB,timeout=20) as c:
        c.execute('PRAGMA busy_timeout=20000')
        r=c.execute(query,args)
        return r.lastrowid if write else r.fetchall()
sql('CREATE TABLE IF NOT EXISTS task_dependencies(task_id INTEGER NOT NULL, depends_on INTEGER NOT NULL, PRIMARY KEY(task_id,depends_on))',write=True)
class API(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path!='/event':self.send_error(404);return
        try:
            n=int(self.headers.get('Content-Length',0))
            if n<1 or n>16384:self.send_error(413);return
            obj=json.loads(self.rfile.read(n))
            pid=int(obj['project_id']);agent=str(obj['agent'])[:100].strip()
            status=str(obj['status'])[:40];msg=str(obj['message'])[:2000].strip()
            if not agent or not msg or status not in ('working','blocked','done','idle') or not sql('SELECT 1 FROM projects WHERE id=?',(pid,)):raise ValueError('Invalid event')
            eid=sql('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(pid,agent,status,msg),True)
            data=json.dumps({'ok':True,'event_id':eid}).encode()
            self.send_response(201);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        except (ValueError,KeyError,TypeError,json.JSONDecodeError):self.send_error(400,'Invalid event')
    def log_message(self,*args):pass
class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address=True
    daemon_threads=True
root=tk.Tk();root.title('TREDIO Control Center — Studio');root.geometry('1360x820');root.minsize(1060,660);root.configure(bg=C['bg'])
style=ttk.Style();style.theme_use('clam')
style.configure('Dark.TCombobox',fieldbackground=C['panel2'],background=C['panel2'],foreground=C['text'],arrowcolor=C['text'])
style.map('Dark.TCombobox',fieldbackground=[('readonly',C['panel2'])],foreground=[('readonly',C['text'])])
def frame(parent,bg=None):return tk.Frame(parent,bg=C.get(bg,bg) if bg else C['bg'])
def label(parent,text,size=11,color='text',bold=False,bg=None,**kw):
    return tk.Label(parent,text=text,font=('Segoe UI',size,'bold' if bold else 'normal'),fg=C.get(color,color),bg=C.get(bg,bg) if bg else C['bg'],**kw)
def button(parent,text,fn,primary=False):
    return tk.Button(parent,text=text,command=fn,bg=C['accent'] if primary else C['panel2'],fg='#160d23' if primary else C['text'],activebackground='#c4a8ff',activeforeground='#160d23',relief='flat',bd=0,font=('Segoe UI',10,'bold'),padx=13,pady=9,cursor='hand2')
def entry(parent,width=30):
    return tk.Entry(parent,width=width,bg=C['panel2'],fg=C['text'],insertbackground=C['text'],relief='flat',font=('Segoe UI',11),bd=8)
def combo(parent,values,width=20):
    x=ttk.Combobox(parent,values=values,width=width,state='readonly',style='Dark.TCombobox')
    if values:x.current(0)
    return x
sidebar=frame(root,'sidebar');sidebar.pack(side='left',fill='y')
sidebar.configure(width=210);sidebar.pack_propagate(False)
label(sidebar,'◆  TREDIO',19,'text',True,'sidebar').pack(anchor='w',padx=19,pady=(24,4))
label(sidebar,'CONTROL CENTER',9,'accent',True,'sidebar').pack(anchor='w',padx=21,pady=(0,34))
content=frame(root);content.pack(side='left',fill='both',expand=True)
header=frame(content);header.pack(fill='x',padx=24,pady=(22,10))
label(header,'Workspace',23,'text',True).pack(side='left')
project_box=combo(header,[],36);project_box.pack(side='right',padx=6)
label(header,'Projet actif',10,'muted').pack(side='right')
toolbar=frame(content);toolbar.pack(fill='x',padx=24,pady=(0,13))
area=frame(content);area.pack(fill='both',expand=True,padx=24,pady=(0,20))
views={}
current='Vue d’ensemble'
def nav_to(name):
    global current
    current=name
    for v in views.values():v.pack_forget()
    views[name].pack(fill='both',expand=True)
    for n,b in nav_buttons.items():b.configure(bg=C['panel2'] if n==name else C['sidebar'],fg=C['accent'] if n==name else C['text'])
    refresh()
nav_buttons={}
for name,icon in [('Vue d’ensemble','▦'),('Canvas','◇'),('Tâches','☷'),('Agents IA','◈'),('Journal & preuves','▤')]:
    b=tk.Button(sidebar,text=f'{icon}   {name}',anchor='w',font=('Segoe UI',11),bg=C['sidebar'],fg=C['text'],relief='flat',bd=0,padx=18,pady=13,command=lambda n=name:nav_to(n),cursor='hand2')
    b.pack(fill='x',padx=8,pady=2);nav_buttons[name]=b
label(sidebar,'LOCAL  •  SQLITE',9,'muted',bg='sidebar').pack(side='bottom',anchor='w',padx=20,pady=24)
for name in nav_buttons:views[name]=frame(area)
def pid():
    try:return int(project_box.get().split(' | ',1)[0])
    except Exception:return None
def projects(select=None):
    rows=sql('SELECT id,name FROM projects ORDER BY id DESC')
    project_box['values']=[f'{i} | {name}' for i,name in rows]
    chosen=select or pid() or (rows[0][0] if rows else None)
    for i,(k,n) in enumerate(rows):
        if k==chosen:project_box.current(i);break
    refresh()
def task_rows():
    return sql('SELECT id,title,priority,agent,status FROM tasks WHERE project_id=? ORDER BY id DESC',(pid(),)) if pid() else []
def event_rows():
    return sql('SELECT id,created,agent,status,message FROM events WHERE project_id=? ORDER BY id DESC LIMIT 300',(pid(),)) if pid() else []
def card(parent,title,value,color='text'):
    f=frame(parent,'panel');f.pack(side='left',fill='x',expand=True,padx=6)
    label(f,title,10,'muted',bg='panel').pack(anchor='w',padx=16,pady=(14,3))
    label(f,str(value),24,color,True,'panel').pack(anchor='w',padx=16,pady=(0,16))
def clear(f):
    for child in f.winfo_children():child.destroy()
def status_color(s):
    return 'red' if s in ('blocked','Bloquée') else 'green' if s in ('done','Validée','Terminée (déclarée)') else 'orange' if s in ('working','En cours') else 'muted'
def create_project():
    win=tk.Toplevel(root);win.title('Nouveau projet');win.configure(bg=C['bg']);win.geometry('420x160')
    label(win,'Nom du projet',13,'text',True).pack(pady=12)
    e=entry(win);e.pack()
    def save():
        n=e.get().strip()
        if n:
            i=sql('INSERT INTO projects(name) VALUES(?)',(n[:120],),True);win.destroy();projects(i)
    button(win,'Créer le projet',save,True).pack(pady=12)
def create_task():
    if not pid():return
    win=tk.Toplevel(root);win.title('Nouvelle tâche');win.configure(bg=C['bg']);win.geometry('490x300')
    label(win,'Créer une tâche',16,'text',True).pack(pady=13)
    title=entry(win,44);title.pack(pady=5)
    pr=combo(win,['Normale','Haute','Critique','Basse']);pr.pack(pady=7)
    ag=combo(win,['IA 1','IA 2','IA 3','IA 4','Humain']);ag.pack(pady=7)
    def save():
        name=title.get().strip()
        if name:
            sql('INSERT INTO tasks(project_id,title,priority,agent) VALUES(?,?,?,?)',(pid(),name[:300],pr.get(),ag.get()),True)
            win.destroy();refresh()
    button(win,'Ajouter la tâche',save,True).pack(pady=10)
def task_detail(tid):
    row=sql('SELECT id,title,priority,agent,status,created FROM tasks WHERE id=? AND project_id=?',(tid,pid()))
    if not row:return
    i,title,priority,agent,status,created=row[0]
    win=tk.Toplevel(root);win.title('Détail tâche #'+str(i));win.geometry('560x410');win.configure(bg=C['bg'])
    label(win,f'#{i}  {title}',17,'text',True,wraplength=500).pack(anchor='w',padx=20,pady=(22,8))
    for k,v in [('Priorité',priority),('Responsable',agent),('Statut',status),('Création',created)]:
        label(win,f'{k} : {v}',11,'muted').pack(anchor='w',padx=20,pady=4)
    label(win,'Changer le statut',11,'text',True).pack(anchor='w',padx=20,pady=(16,5))
    statusbox=combo(win,['À faire','En cours','Bloquée','Terminée (déclarée)','Validée'],27)
    statusbox.set(status);statusbox.pack(anchor='w',padx=20)
    def save():
        sql('UPDATE tasks SET status=? WHERE id=? AND project_id=?',(statusbox.get(),i,pid()),True)
        win.destroy();refresh()
    button(win,'Enregistrer',save,True).pack(anchor='w',padx=20,pady=18)
def agent_detail(agent):
    win=tk.Toplevel(root);win.title('Agent '+agent);win.geometry('570x390');win.configure(bg=C['bg'])
    label(win,agent,20,'text',True).pack(anchor='w',padx=20,pady=15)
    related=[r for r in event_rows() if r[2]==agent]
    if related:
        for _,dt,a,s,m in related[:5]:
            label(win,f'{dt}  [{s}]  {m[:100]}',10,status_color(s),wraplength=520,justify='left').pack(anchor='w',padx=20,pady=6)
    else:label(win,'Aucun événement enregistré pour cet agent.',11,'muted').pack(anchor='w',padx=20)
def draw_dashboard():
    view=views['Vue d’ensemble'];clear(view)
    tasks=task_rows();events=event_rows()
    metrics=frame(view);metrics.pack(fill='x',pady=(0,20))
    card(metrics,'Tâches',len(tasks),'accent')
    card(metrics,'En cours',sum(t[4]=='En cours' for t in tasks),'orange')
    card(metrics,'Blocages',sum(t[4]=='Bloquée' for t in tasks)+sum(e[3]=='blocked' for e in events),'red')
    card(metrics,'Événements',len(events),'green')
    label(view,'Agents et activité',17,'text',True).pack(anchor='w',pady=(0,10))
    agents=frame(view);agents.pack(fill='x')
    for idx,role in enumerate(('Architecture','Développement','Tests','Audit'),1):
        a='IA '+str(idx)
        last=next((e for e in events if e[2]==a),None)
        f=frame(agents,'panel');f.pack(side='left',fill='both',expand=True,padx=6)
        label(f,a,13,'text',True,'panel').pack(anchor='w',padx=14,pady=(12,2))
        label(f,role,10,'muted',bg='panel').pack(anchor='w',padx=14)
        label(f,'● '+(last[3] if last else 'En attente'),11,status_color(last[3]) if last else 'muted',True,'panel').pack(anchor='w',padx=14,pady=10)
        button(f,'Voir les détails',lambda a=a:agent_detail(a)).pack(anchor='w',padx=12,pady=(0,12))
    label(view,'Activité récente',17,'text',True).pack(anchor='w',pady=(25,10))
    for e in events[:7]:
        _,dt,ag,s,msg=e
        f=frame(view,'panel');f.pack(fill='x',pady=3)
        label(f,f'●  {ag}  •  {s}    {msg[:130]}',10,status_color(s),bg='panel',anchor='w').pack(fill='x',padx=14,pady=10)
def draw_tasks():
    view=views['Tâches'];clear(view)
    label(view,'Tâches du projet',18,'text',True).pack(anchor='w',pady=(0,12))
    for i,title,pr,ag,status in task_rows():
        f=frame(view,'panel');f.pack(fill='x',pady=4)
        label(f,f'#{i}  {title[:90]}',12,'text',True,'panel').pack(side='left',padx=14,pady=12)
        button(f,'Détails',lambda i=i:task_detail(i)).pack(side='right',padx=8,pady=5)
        label(f,f'{pr}  •  {ag}  •  {status}',10,status_color(status),bg='panel').pack(side='right',padx=12)
def draw_canvas():
    view=views['Canvas'];clear(view)
    top=frame(view);top.pack(fill='x',pady=(0,10))
    label(top,'Canvas des dépendances',18,'text',True).pack(side='left')
    tasklist=task_rows()
    vals=[f'{i} | {title[:35]}' for i,title,_,_,_ in tasklist]
    source=combo(top,vals,24);source.pack(side='left',padx=(20,5))
    label(top,'dépend de',10,'muted').pack(side='left')
    target=combo(top,vals,24);target.pack(side='left',padx=5)
    def getid(s):
        try:return int(s.split(' | ',1)[0])
        except Exception:return None
    def add_link():
        a,b=getid(source.get()),getid(target.get())
        valid={t[0] for t in tasklist}
        if a not in valid or b not in valid or a==b:messagebox.showwarning('Dépendances','Sélectionne deux tâches différentes.');return
        graph={}
        for x,y in sql('SELECT task_id,depends_on FROM task_dependencies'):graph.setdefault(x,[]).append(y)
        todo=[b];seen=set()
        while todo:
            n=todo.pop()
            if n==a:messagebox.showerror('Cycle','Dépendance circulaire refusée.');return
            if n in seen:continue
            seen.add(n);todo.extend(graph.get(n,[]))
        sql('INSERT OR IGNORE INTO task_dependencies(task_id,depends_on) VALUES(?,?)',(a,b),True);draw_canvas()
    button(top,'+ Lier',add_link,True).pack(side='left',padx=8)
    container=frame(view,'panel');container.pack(fill='both',expand=True)
    cvs=tk.Canvas(container,bg=C['panel'],highlightthickness=0)
    hbar=tk.Scrollbar(container,orient='horizontal',command=cvs.xview)
    vbar=tk.Scrollbar(container,orient='vertical',command=cvs.yview)
    cvs.configure(xscrollcommand=hbar.set,yscrollcommand=vbar.set)
    hbar.pack(side='bottom',fill='x');vbar.pack(side='right',fill='y');cvs.pack(fill='both',expand=True)
    coords={}
    for j,(tid,title,pr,ag,status) in enumerate(reversed(tasklist)):
        x=40+(j%3)*275;y=45+(j//3)*150
        coords[tid]=(x,y)
    for a,b in sql('SELECT task_id,depends_on FROM task_dependencies'):
        if a in coords and b in coords:
            x1,y1=coords[b];x2,y2=coords[a]
            cvs.create_line(x1+110,y1+100,x2+110,y2,fill=C['accent'],width=3,arrow=tk.LAST)
    for tid,title,pr,ag,status in tasklist:
        x,y=coords[tid]
        cvs.create_rectangle(x,y,x+230,y+100,fill=C['panel2'],outline=C[status_color(status)],width=2)
        cvs.create_text(x+12,y+21,text=f'#{tid}  {title[:27]}',anchor='w',fill=C['text'],font=('Segoe UI',11,'bold'))
        cvs.create_text(x+12,y+54,text=f'{ag}  •  {pr}',anchor='w',fill=C['muted'],font=('Segoe UI',10))
        cvs.create_text(x+12,y+78,text='● '+status[:26],anchor='w',fill=C[status_color(status)],font=('Segoe UI',10))
        cvs.tag_bind(cvs.create_rectangle(x,y,x+230,y+100,outline='',fill=''),'<Button-1>',lambda e,i=tid:task_detail(i))
    if not tasklist:cvs.create_text(35,40,text='Aucune tâche. Utilise « + Tâche » pour commencer.',anchor='nw',fill=C['muted'],font=('Segoe UI',14))
    cvs.configure(scrollregion=(0,0,850,max(550,180+len(tasklist)//3*150)))
def draw_events():
    view=views['Journal & preuves'];clear(view)
    label(view,'Journal et preuves',18,'text',True).pack(anchor='w',pady=(0,12))
    for _,dt,ag,s,msg in event_rows():
        f=frame(view,'panel');f.pack(fill='x',pady=4)
        label(f,f'{dt}  •  {ag}  •  {s}',10,status_color(s),True,'panel').pack(anchor='w',padx=14,pady=(10,2))
        label(f,msg[:1000],11,'text',bg='panel',wraplength=900,justify='left').pack(anchor='w',padx=14,pady=(0,10))
def draw_agent():
    view=views['Agents IA'];clear(view)
    label(view,'Agent Ollama local',18,'text',True).pack(anchor='w',pady=(0,6))
    label(view,'Modèle '+MODELE+' • Lecture seule • Réponses non vérifiées',10,'muted').pack(anchor='w',pady=(0,12))
    mission=tk.Text(view,height=6,bg=C['panel2'],fg=C['text'],insertbackground=C['text'],relief='flat',font=('Segoe UI',11),wrap='word',padx=14,pady=12)
    mission.pack(fill='x');mission.insert('1.0','Analyse ce projet et propose trois actions vérifiables.')
    label(view,'Réponse de l’agent',13,'text',True).pack(anchor='w',pady=(18,8))
    output=tk.Text(view,bg=C['panel'],fg=C['text'],insertbackground=C['text'],relief='flat',font=('Segoe UI',11),wrap='word',padx=14,pady=12)
    output.pack(fill='both',expand=True)
    state=tk.StringVar(value='Prêt')
    label(view,'Statut',10,'muted').pack(anchor='w',pady=(10,0))
    state_label=label(view,'Prêt',10,'green');state_label.pack(anchor='w')
    def run():
        p=pid();prompt=mission.get('1.0','end').strip()
        if not p or not prompt:return
        runbtn.configure(state='disabled');state_label.configure(text='Génération en cours...',fg=C['orange'])
        sql('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(p,'Ollama','working','Mission : '+prompt[:1900]),True)
        def worker():
            try:
                payload=json.dumps({'model':MODELE,'stream':False,'messages':[{'role':'system','content':'Tu es un assistant de développement en lecture seule. Ne prétends jamais avoir exécuté des tests ou modifié des fichiers.'},{'role':'user','content':prompt}],'options':{'num_predict':180}}).encode()
                req=urllib.request.Request('http://127.0.0.1:11434/api/chat',data=payload,headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=180) as r:result=json.load(r).get('message',{}).get('content','').strip()
                if not result:raise ValueError('Réponse vide')
                sql('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(p,'Ollama','done',('Réponse IA non vérifiée : '+result)[:2000]),True)
                def done():
                    if not output.winfo_exists():return
                    output.delete('1.0','end');output.insert('1.0',result)
                    state_label.configure(text='Réponse enregistrée',fg=C['green']);runbtn.configure(state='normal')
                root.after(0,done)
            except Exception as ex:
                error=str(ex)
                sql('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(p,'Ollama','blocked',error[:2000]),True)
                def failed():
                    if not output.winfo_exists():return
                    output.delete('1.0','end');output.insert('1.0',error)
                    state_label.configure(text='Agent bloqué',fg=C['red']);runbtn.configure(state='normal')
                root.after(0,failed)
        threading.Thread(target=worker,daemon=True).start()
    runbtn=button(view,'▶ Lancer Ollama',run,True);runbtn.pack(anchor='w',pady=10)
def show_blockers():
    nav_to('Tâches')
    blocked=[r for r in task_rows() if r[4]=='Bloquée']
    if blocked:task_detail(blocked[0][0])
    else:messagebox.showinfo('Blocages','Aucune tâche marquée bloquée dans ce projet.')
def refresh():
    if not pid():return
    {'Vue d’ensemble':draw_dashboard,'Canvas':draw_canvas,'Tâches':draw_tasks,'Agents IA':draw_agent,'Journal & preuves':draw_events}[current]()
def export_data():
    path=filedialog.asksaveasfilename(defaultextension='.json',initialfile='dioptre-export.json',filetypes=[('JSON','*.json')])
    if not path:return
    data={k:sql('SELECT * FROM '+k) for k in ('projects','tasks','events','task_dependencies')}
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    messagebox.showinfo('Export','Export terminé')
button(toolbar,'+ Projet',create_project).pack(side='left',padx=(0,8))
button(toolbar,'+ Tâche',create_task,True).pack(side='left',padx=8)
button(toolbar,'▶ Lancer une IA',lambda:nav_to('Agents IA')).pack(side='left',padx=8)
button(toolbar,'⚠ Blocages',show_blockers).pack(side='left',padx=8)
button(toolbar,'✓ Vérifier résultats',lambda:nav_to('Journal & preuves')).pack(side='left',padx=8)
button(toolbar,'Exporter',export_data).pack(side='right',padx=8)
project_box.bind('<<ComboboxSelected>>',lambda e:refresh())
try:
    server=Server(('127.0.0.1',PORT_API),API)
    threading.Thread(target=server.serve_forever,daemon=True).start()
except OSError:server=None
projects()
nav_to('Vue d’ensemble')
def shutdown():
    if server:
        try:server.shutdown()
        except Exception:pass
    root.destroy()
root.protocol('WM_DELETE_WINDOW',shutdown)
root.mainloop()
