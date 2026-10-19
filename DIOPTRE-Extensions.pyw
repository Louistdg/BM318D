import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3, threading, json, urllib.request, urllib.error, html, webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DB=ROOT/'dioptre.sqlite3'
MODEL=os.environ.get('MC_OLLAMA_MODEL') or 'qwen2.5:3b'
def db(sql,args=(),write=False):
    with sqlite3.connect(DB,timeout=15) as c:
        c.execute('PRAGMA busy_timeout=15000')
        cur=c.execute(sql,args)
        return cur.lastrowid if write else cur.fetchall()
db('CREATE TABLE IF NOT EXISTS task_dependencies(task_id INTEGER NOT NULL, depends_on INTEGER NOT NULL, PRIMARY KEY(task_id,depends_on))',write=True)
root=tk.Tk();root.title('DIOPTRE — Agent Ollama & Canvas');root.geometry('1000x720');root.configure(bg='#14111e')
style=ttk.Style();style.theme_use('clam')
style.configure('TFrame',background='#14111e')
style.configure('TLabel',background='#14111e',foreground='#f0eaf8',font=('Segoe UI',10))
style.configure('TButton',background='#41304e',foreground='#fff',padding=8)
style.configure('TCombobox',fieldbackground='#292234',foreground='#fff')
panel=ttk.Frame(root,padding=18);panel.pack(fill='both',expand=True)
ttk.Label(panel,text='◆ DIOPTRE / AGENT & CANVAS',font=('Segoe UI',18,'bold')).pack(anchor='w')
ttk.Label(panel,text='Agent réel Ollama local • Réponses journalisées • Dépendances entre tâches').pack(anchor='w',pady=8)
proj=tk.StringVar();task=tk.StringVar();dep=tk.StringVar();state=tk.StringVar(value='Prêt')
top=ttk.Frame(panel);top.pack(fill='x',pady=8)
ttk.Label(top,text='Projet').pack(side='left')
pc=ttk.Combobox(top,textvariable=proj,state='readonly',width=45);pc.pack(side='left',padx=10)
def id_of(s):
    try:return int(s.split(' | ',1)[0])
    except Exception:return None
def projects():
    rows=db('SELECT id,name FROM projects ORDER BY id')
    pc['values']=[f'{i} | {name}' for i,name in rows]
    if rows:pc.current(0)
    tasks()
def tasks(*_):
    p=id_of(proj.get())
    rows=db('SELECT id,title FROM tasks WHERE project_id=? ORDER BY id',(p,)) if p else []
    values=[f'{i} | {name}' for i,name in rows]
    tc['values']=values;dc['values']=values
    if values:tc.current(0);dc.current(0)
    else:task.set('');dep.set('')
pc.bind('<<ComboboxSelected>>',tasks)
notebook=ttk.Notebook(panel);notebook.pack(fill='both',expand=True)
agent_tab=ttk.Frame(notebook,padding=12);canvas_tab=ttk.Frame(notebook,padding=12)
notebook.add(agent_tab,text='Agent Ollama');notebook.add(canvas_tab,text='Canvas des tâches')
ttk.Label(agent_tab,text='Mission à confier à '+MODEL+' (analyse et conseil, aucun accès aux fichiers)').pack(anchor='w')
mission=tk.Text(agent_tab,height=5,bg='#241e2e',fg='white',insertbackground='white',wrap='word')
mission.pack(fill='x',pady=8)
mission.insert('1.0','Analyse les risques du projet et propose trois prochaines actions vérifiables.')
ttk.Label(agent_tab,text='Réponse de l’agent').pack(anchor='w')
answer=tk.Text(agent_tab,bg='#241e2e',fg='white',insertbackground='white',wrap='word')
answer.pack(fill='both',expand=True,pady=8)
def record(p,status,message):
    db('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(p,'Ollama / '+MODEL,status,message[:2000]),True)
def run_agent():
    p=id_of(proj.get());prompt=mission.get('1.0','end').strip()
    if not p or not prompt:return
    run_btn.configure(state='disabled');state.set('Agent en cours...')
    record(p,'working','Mission reçue : '+prompt)
    def work():
        try:
            data=json.dumps({'model':MODEL,'stream':False,'messages':[{'role':'system','content':'Tu es un assistant de développement. Analyse uniquement. Ne prétends jamais avoir modifié des fichiers, exécuté des tests ou utilisé des outils.'},{'role':'user','content':prompt}],'options':{'num_predict':600}}).encode()
            req=urllib.request.Request('http://127.0.0.1:11434/api/chat',data=data,headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=180) as response:
                obj=json.load(response)
            result=obj.get('message',{}).get('content','').strip()
            if not result:raise ValueError('Réponse vide')
            record(p,'done','Réponse IA (non vérifiée) : '+result)
            root.after(0,lambda:show(result,'Réponse reçue et journalisée'))
        except Exception as e:
            record(p,'blocked','Erreur Ollama : '+str(e))
            root.after(0,lambda:show('ERREUR : '+str(e),'Agent bloqué'))
    threading.Thread(target=work,daemon=True).start()
def show(text,status):
    answer.delete('1.0','end');answer.insert('1.0',text)
    state.set(status);run_btn.configure(state='normal')
run_btn=ttk.Button(agent_tab,text='▶ Envoyer à Ollama',command=run_agent);run_btn.pack(anchor='w')
row=ttk.Frame(canvas_tab);row.pack(fill='x',pady=10)
ttk.Label(row,text='Tâche').pack(side='left')
tc=ttk.Combobox(row,textvariable=task,state='readonly',width=36);tc.pack(side='left',padx=8)
ttk.Label(row,text='Dépend de').pack(side='left')
dc=ttk.Combobox(row,textvariable=dep,state='readonly',width=36);dc.pack(side='left',padx=8)
def add_dependency():
    a=id_of(task.get());b=id_of(dep.get());p=id_of(proj.get())
    if not a or not b or a==b:messagebox.showwarning('Dépendance','Sélectionne deux tâches différentes.');return
    edges=db('SELECT task_id,depends_on FROM task_dependencies')
    graph={}
    for x,y in edges:graph.setdefault(x,[]).append(y)
    stack=[b];seen=set()
    while stack:
        n=stack.pop()
        if n==a:messagebox.showerror('Cycle','Cette relation créerait une dépendance circulaire.');return
        if n in seen:continue
        seen.add(n);stack.extend(graph.get(n,[]))
    if not db('SELECT 1 FROM tasks WHERE id=? AND project_id=?',(a,p)) or not db('SELECT 1 FROM tasks WHERE id=? AND project_id=?',(b,p)):return
    db('INSERT OR IGNORE INTO task_dependencies(task_id,depends_on) VALUES(?,?)',(a,b),True)
    state.set('Dépendance enregistrée');refresh_canvas()
ttk.Button(canvas_tab,text='+ Ajouter dépendance',command=add_dependency).pack(anchor='w')
ttk.Label(canvas_tab,text='Une flèche part du prérequis vers la tâche qui en dépend. Les cycles sont refusés.').pack(anchor='w',pady=12)
canvas=tk.Canvas(canvas_tab,bg='#1b1726',highlightthickness=0)
canvas.pack(fill='both',expand=True)
def refresh_canvas():
    canvas.delete('all')
    p=id_of(proj.get())
    rows=db('SELECT id,title,status FROM tasks WHERE project_id=? ORDER BY id',(p,)) if p else []
    if not rows:
        canvas.create_text(25,30,anchor='nw',fill='#ddd',text='Ajoute des tâches dans DIOPTRE pour voir le canvas.')
        return
    width=max(canvas.winfo_width(),600)
    pos={}
    for i,(tid,title,status) in enumerate(rows):
        col=i%3;line=i//3;x=30+col*(width-35)/3;y=35+line*135
        pos[tid]=(x,y)
    edges=db('SELECT task_id,depends_on FROM task_dependencies')
    for target,source in edges:
        if target in pos and source in pos:
            x1,y1=pos[source];x2,y2=pos[target]
            canvas.create_line(x1+95,y1+70,x2+95,y2,fill='#a98bd7',width=2,arrow=tk.LAST)
    for tid,title,status in rows:
        x,y=pos[tid]
        canvas.create_rectangle(x,y,x+190,y+70,fill='#30283d',outline='#66517e',width=2)
        canvas.create_text(x+10,y+15,anchor='w',fill='white',width=170,text=f'#{tid} {title[:26]}')
        canvas.create_text(x+10,y+48,anchor='w',fill='#bfa6dd',text=status[:24])
    canvas.configure(scrollregion=canvas.bbox('all'))
canvas.bind('<Configure>',lambda e:refresh_canvas())
ttk.Button(canvas_tab,text='↻ Actualiser le canvas',command=refresh_canvas).pack(anchor='w',pady=8)
ttk.Label(panel,textvariable=state).pack(anchor='w',pady=5)
projects()
root.mainloop()
