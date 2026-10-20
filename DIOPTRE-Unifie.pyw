import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3, json, datetime, threading, http.server, os, urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DB=ROOT/'dioptre.sqlite3'
PORT_API=int(os.environ.get('MC_PC_PORT') or 31878)

con=sqlite3.connect(DB,check_same_thread=False,timeout=15)
con.execute('PRAGMA busy_timeout=5000')
lock=threading.RLock()
with lock:
    con.executescript("""CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL,title TEXT NOT NULL,priority TEXT NOT NULL DEFAULT 'Normale',status TEXT NOT NULL DEFAULT 'À faire',agent TEXT DEFAULT '',created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL,agent TEXT NOT NULL,status TEXT NOT NULL,message TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_events_project ON events(project_id,id);
CREATE INDEX IF NOT EXISTS ix_tasks_project ON tasks(project_id,id);""")
    if not con.execute('SELECT 1 FROM projects LIMIT 1').fetchone():
        con.execute('INSERT INTO projects(name) VALUES(?)',('Projet de démonstration',))
    con.execute('CREATE TABLE IF NOT EXISTS task_dependencies(task_id INTEGER NOT NULL, depends_on INTEGER NOT NULL, PRIMARY KEY(task_id,depends_on))')
    con.commit()

def query(sql,args=()):
    with lock: return con.execute(sql,args).fetchall()
def execute(sql,args=()):
    with lock:
        cur=con.execute(sql,args);con.commit();return cur.lastrowid

class API(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path!='/event': self.send_error(404);return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<1 or length>16384: self.send_error(413);return
            data=json.loads(self.rfile.read(length))
            project=int(data['project_id'])
            agent=str(data['agent'])[:100].strip()
            status=str(data['status'])[:40].strip()
            message=str(data['message'])[:2000].strip()
            if not agent or not message or status not in ('working','blocked','done','idle'): raise ValueError('invalid fields')
            if not query('SELECT 1 FROM projects WHERE id=?',(project,)): raise ValueError('unknown project')
            event_id=execute('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(project,agent,status,message))
            result=json.dumps({'ok':True,'event_id':event_id}).encode()
            self.send_response(201);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(result)));self.end_headers();self.wfile.write(result)
        except (ValueError,KeyError,TypeError,json.JSONDecodeError):
            self.send_error(400,'Invalid event')
    def log_message(self,*args): pass

class Server(http.server.ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True

app=tk.Tk();app.title('TREDIO Control Center — Local');app.geometry('1180x760');app.minsize(880,580);app.configure(bg='#111019')
style=ttk.Style();style.theme_use('clam')
style.configure('TFrame',background='#111019')
style.configure('TLabel',background='#111019',foreground='#e9e5f1',font=('Segoe UI',10))
style.configure('TButton',background='#342844',foreground='#f2eafd',padding=9,font=('Segoe UI',10))
style.map('TButton',background=[('active','#4e3964')])
style.configure('TCombobox',fieldbackground='#241f30',background='#241f30',foreground='#eee')
style.configure('Treeview',background='#1b1724',fieldbackground='#1b1724',foreground='#f2edf8',rowheight=29,borderwidth=0)
style.configure('Treeview.Heading',background='#30273e',foreground='#e8dcfa',font=('Segoe UI',10,'bold'))
style.map('Treeview',background=[('selected','#624582')])
main=ttk.Frame(app,padding=20);main.pack(fill='both',expand=True)
ttk.Label(main,text='◆ TREDIO  /  CONTROL CENTER',font=('Segoe UI',19,'bold')).pack(anchor='w')
ttk.Label(main,text='Supervision locale • Projets, tâches, agents et événements vérifiables').pack(anchor='w',pady=(0,12))
top=ttk.Frame(main);top.pack(fill='x')
ttk.Label(top,text='Projet :').pack(side='left')
projects=ttk.Combobox(top,state='readonly',width=37);projects.pack(side='left',padx=8)
name=tk.StringVar()
ttk.Entry(top,textvariable=name,width=28).pack(side='left',padx=6)
statusbar=tk.StringVar(value='Initialisation')
def project_id():
    try: return int(projects.get().split(' | ',1)[0])
    except Exception: return None
def load_projects(select=None):
    rows=query('SELECT id,name FROM projects ORDER BY id DESC')
    projects['values']=[f'{i} | {n}' for i,n in rows]
    target=select or project_id() or rows[0][0]
    for index,(i,n) in enumerate(rows):
        if i==target: projects.current(index);break
    refresh()
def add_project():
    n=name.get().strip()
    if not n:return
    i=execute('INSERT INTO projects(name) VALUES(?)',(n[:120],));name.set('');load_projects(i)
ttk.Button(top,text='+ Projet',command=add_project).pack(side='left')
notebook=ttk.Notebook(main);notebook.pack(fill='both',expand=True,pady=(14,0))
tabs={}
for tab in ('Tableau de bord','Tâches','Journal','Connexion IA'):
    frame=ttk.Frame(notebook,padding=12);notebook.add(frame,text=tab);tabs[tab]=frame
summary=tk.StringVar()
ttk.Label(tabs['Tableau de bord'],textvariable=summary,font=('Segoe UI',13,'bold')).pack(anchor='w',pady=10)
agents_frame=ttk.Frame(tabs['Tableau de bord']);agents_frame.pack(fill='x',pady=12)
agent_labels={}
for i,label in enumerate(('Architecture','Développement','Tests','Audit'),1):
    f=ttk.LabelFrame(agents_frame,text=f'IA {i} — {label}',padding=14);f.pack(side='left',fill='both',expand=True,padx=5)
    v=tk.StringVar(value='En attente');ttk.Label(f,textvariable=v,wraplength=160).pack();agent_labels[f'IA {i}']=v
ttk.Label(tabs['Tableau de bord'],text='Une tâche déclarée terminée n’est pas une preuve de test.').pack(anchor='w',pady=20)
tasks=tabs['Tâches']
form=ttk.Frame(tasks);form.pack(fill='x')
task_title=tk.StringVar();priority=tk.StringVar(value='Normale');agent=tk.StringVar(value='IA 1')
ttk.Entry(form,textvariable=task_title,width=45).pack(side='left',padx=4)
ttk.Combobox(form,textvariable=priority,values=['Basse','Normale','Haute','Critique'],state='readonly',width=11).pack(side='left',padx=4)
ttk.Combobox(form,textvariable=agent,values=['IA 1','IA 2','IA 3','IA 4','Humain'],state='readonly',width=10).pack(side='left',padx=4)
def add_task():
    if not project_id() or not task_title.get().strip():return
    execute('INSERT INTO tasks(project_id,title,priority,agent) VALUES(?,?,?,?)',(project_id(),task_title.get().strip()[:300],priority.get(),agent.get()))
    task_title.set('');refresh()
ttk.Button(form,text='+ Tâche',command=add_task).pack(side='left')
tree=ttk.Treeview(tasks,columns=('title','priority','agent','status'),show='headings',selectmode='browse')
for col,width in [('title',380),('priority',90),('agent',100),('status',140)]:
    tree.heading(col,text=col.capitalize());tree.column(col,width=width)
tree.pack(fill='both',expand=True,pady=12)
actions=ttk.Frame(tasks);actions.pack(fill='x')
def set_task(status):
    selection=tree.selection()
    if selection:
        execute('UPDATE tasks SET status=? WHERE id=? AND project_id=?',(status,int(selection[0]),project_id()));refresh()
for s in ('À faire','En cours','Bloquée','Terminée (déclarée)','Validée'):
    ttk.Button(actions,text=s,command=lambda x=s:set_task(x)).pack(side='left',padx=3)
journal=tabs['Journal']
ev_agent=tk.StringVar(value='IA 1');ev_status=tk.StringVar(value='working')
ev_form=ttk.Frame(journal);ev_form.pack(fill='x')
ttk.Combobox(ev_form,textvariable=ev_agent,values=['IA 1','IA 2','IA 3','IA 4','Humain'],state='readonly',width=12).pack(side='left',padx=3)
ttk.Combobox(ev_form,textvariable=ev_status,values=['working','blocked','done','idle'],state='readonly',width=12).pack(side='left',padx=3)
message=tk.StringVar();ttk.Entry(ev_form,textvariable=message,width=65).pack(side='left',padx=3)
def add_event():
    if not project_id() or not message.get().strip():return
    execute('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(project_id(),ev_agent.get(),ev_status.get(),message.get().strip()[:2000]))
    message.set('');refresh()
ttk.Button(ev_form,text='Publier',command=add_event).pack(side='left')
events=tk.Text(journal,bg='#1b1724',fg='#e9e5f1',insertbackground='white',font=('Consolas',10),wrap='word',state='disabled')
events.pack(fill='both',expand=True,pady=12)
connect=tabs['Connexion IA']
for line in ('API locale : http://127.0.0.1:%d/event' % PORT_API,'Méthode : POST, Content-Type: application/json','Champs : project_id (nombre), agent, status, message','Statuts : working / blocked / done / idle','Exemple : {"project_id":1,"agent":"IA 1","status":"working","message":"Analyse commencée"}','IMPORTANT : aucun agent externe n’est connecté automatiquement.','Seules les requêtes provenant de ce PC sont acceptées.'):
    ttk.Label(connect,text=line,font=('Consolas',10)).pack(anchor='w',pady=8)
def export_json():
    path=filedialog.asksaveasfilename(defaultextension='.json',initialfile='dioptre-export.json',filetypes=[('JSON','*.json')])
    if not path:return
    data={'projects':query('SELECT * FROM projects'),'tasks':query('SELECT * FROM tasks'),'events':query('SELECT * FROM events')}
    with open(path,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
    messagebox.showinfo('Export','Export terminé : '+path)
ttk.Button(connect,text='Exporter les données JSON',command=export_json).pack(anchor='w',pady=16)
def refresh():
    p=project_id()
    if not p:return
    rows=query('SELECT id,title,priority,agent,status FROM tasks WHERE project_id=? ORDER BY id DESC',(p,))
    tree.delete(*tree.get_children())
    for i,t,pr,a,s in rows:tree.insert('', 'end',iid=str(i),values=(t,pr,a,s))
    ev=query('SELECT created,agent,status,message FROM events WHERE project_id=? ORDER BY id DESC LIMIT 300',(p,))
    events.config(state='normal');events.delete('1.0','end')
    for dt,a,s,m in ev:events.insert('end',f'[{dt}] {a} • {s}\n{m}\n\n')
    events.config(state='disabled')
    blocked=sum(s=='Bloquée' for _,_,_,_,s in rows)
    summary.set(f'{len(rows)} tâches  •  {blocked} bloquées  •  {len(ev)} événements récents')
    for a,v in agent_labels.items():
        last=next(((s,m) for _,ag,s,m in ev if ag==a),None)
        v.set((last[0]+'\n'+last[1][:90]) if last else 'En attente')
projects.bind('<<ComboboxSelected>>',lambda e:refresh())

# Unified agent tab: no shell execution, no filesystem permissions for Ollama.
agent_tab=ttk.Frame(notebook,padding=12);notebook.add(agent_tab,text='Agent Ollama')
MODELE=os.environ.get('MC_OLLAMA_MODEL') or 'qwen2.5:3b'
ttk.Label(agent_tab,text='Agent local '+MODELE+' — analyse seulement, aucune modification de fichiers').pack(anchor='w')
mission=tk.Text(agent_tab,height=5,bg='#241e2e',fg='white',insertbackground='white',wrap='word')
mission.pack(fill='x',pady=8)
mission.insert('1.0','Analyse le projet et propose trois prochaines actions testables.')
response=tk.Text(agent_tab,bg='#241e2e',fg='white',insertbackground='white',wrap='word')
response.pack(fill='both',expand=True,pady=8)
agent_status=tk.StringVar(value='Prêt')
ttk.Label(agent_tab,textvariable=agent_status).pack(anchor='w')
def show_agent(text,status):
    if not app.winfo_exists():return
    response.delete('1.0','end');response.insert('1.0',text)
    agent_status.set(status);send_btn.configure(state='normal');refresh()
def send_agent():
    p=project_id();prompt=mission.get('1.0','end').strip()
    if not p or not prompt:return
    send_btn.configure(state='disabled');agent_status.set('Génération en cours...')
    execute('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(p,'Ollama','working','Mission : '+prompt[:1900]))
    def worker():
        try:
            payload=json.dumps({'model':MODELE,'stream':False,'messages':[{'role':'system','content':'Tu es un assistant de développement en lecture seule. Ne prétends jamais avoir exécuté de tests ou modifié des fichiers.'},{'role':'user','content':prompt}],'options':{'num_predict':160}}).encode()
            req=urllib.request.Request('http://127.0.0.1:11434/api/chat',data=payload,headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=150) as r:result=json.load(r).get('message',{}).get('content','').strip()
            if not result:raise ValueError('Réponse vide')
            execute('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(p,'Ollama','done',('Réponse IA non vérifiée : '+result)[:2000]))
            app.after(0,lambda:show_agent(result,'Réponse reçue et journalisée'))
        except Exception as exc:
            error=str(exc)
            execute('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(p,'Ollama','blocked',error[:2000]))
            app.after(0,lambda:show_agent('Erreur : '+error,'Agent bloqué'))
    threading.Thread(target=worker,daemon=True).start()
send_btn=ttk.Button(agent_tab,text='▶ Envoyer à Ollama',command=send_agent)
send_btn.pack(anchor='w',pady=8)
# Unified dependency canvas
canvas_tab=ttk.Frame(notebook,padding=12);notebook.add(canvas_tab,text='Canvas')
linkbar=ttk.Frame(canvas_tab);linkbar.pack(fill='x',pady=8)
source=tk.StringVar();target=tk.StringVar()
ttk.Label(linkbar,text='Tâche').pack(side='left')
source_box=ttk.Combobox(linkbar,textvariable=source,state='readonly',width=31);source_box.pack(side='left',padx=5)
ttk.Label(linkbar,text='dépend de').pack(side='left')
target_box=ttk.Combobox(linkbar,textvariable=target,state='readonly',width=31);target_box.pack(side='left',padx=5)
def parse_id(s):
    try:return int(s.split(' | ',1)[0])
    except Exception:return None
def link_tasks():
    a,b=parse_id(source.get()),parse_id(target.get());p=project_id()
    if not a or not b or a==b:
        messagebox.showwarning('Dépendances','Sélectionne deux tâches différentes.');return
    valid={r[0] for r in query('SELECT id FROM tasks WHERE project_id=?',(p,))}
    if a not in valid or b not in valid:return
    graph={}
    for x,y in query('SELECT task_id,depends_on FROM task_dependencies'):graph.setdefault(x,[]).append(y)
    todo=[b];seen=set()
    while todo:
        n=todo.pop()
        if n==a:
            messagebox.showerror('Cycle','Dépendance circulaire refusée.');return
        if n in seen:continue
        seen.add(n);todo.extend(graph.get(n,[]))
    execute('INSERT OR IGNORE INTO task_dependencies(task_id,depends_on) VALUES(?,?)',(a,b))
    refresh_canvas()
ttk.Button(linkbar,text='+ Lier',command=link_tasks).pack(side='left',padx=5)
canvas=tk.Canvas(canvas_tab,bg='#1b1726',highlightthickness=0)
canvas.pack(fill='both',expand=True)
def refresh_canvas():
    if not canvas.winfo_exists():return
    canvas.delete('all')
    p=project_id()
    if not p:return
    rows=query('SELECT id,title,status FROM tasks WHERE project_id=? ORDER BY id',(p,))
    vals=[f'{i} | {title}' for i,title,_ in rows]
    olda,oldb=source.get(),target.get()
    source_box['values']=vals;target_box['values']=vals
    source.set(olda if olda in vals else (vals[0] if vals else ''))
    target.set(oldb if oldb in vals else (vals[-1] if vals else ''))
    width=max(canvas.winfo_width(),700)
    coords={}
    for j,(tid,title,status) in enumerate(rows):
        col=j%3;line=j//3
        coords[tid]=(20+col*(width-20)/3,30+line*125)
    for a,b in query('SELECT task_id,depends_on FROM task_dependencies'):
        if a in coords and b in coords:
            x1,y1=coords[b];x2,y2=coords[a]
            canvas.create_line(x1+90,y1+66,x2+90,y2,fill='#b396e0',width=2,arrow=tk.LAST)
    for tid,title,status in rows:
        x,y=coords[tid]
        canvas.create_rectangle(x,y,x+185,y+65,fill='#30283d',outline='#735b90',width=2)
        canvas.create_text(x+9,y+18,anchor='w',fill='white',text=f'#{tid} {title[:23]}')
        canvas.create_text(x+9,y+45,anchor='w',fill='#c6a9eb',text=status[:22])
    if not rows:canvas.create_text(20,30,anchor='nw',fill='white',text='Ajoute des tâches dans l’onglet Tâches.')
    canvas.configure(scrollregion=canvas.bbox('all'))
canvas.bind('<Configure>',lambda e:refresh_canvas())
old_refresh=refresh
def refresh():
    old_refresh()
    refresh_canvas()

load_projects()
try:
    server=Server(('127.0.0.1',PORT_API),API)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    statusbar.set('API locale active sur 127.0.0.1:%d' % PORT_API)
except OSError as e:statusbar.set('API indisponible : '+str(e))
ttk.Label(main,textvariable=statusbar).pack(anchor='w')
def close():
    try:server.shutdown()
    except Exception:pass
    con.close();app.destroy()
app.protocol('WM_DELETE_WINDOW',close)
app.mainloop()
