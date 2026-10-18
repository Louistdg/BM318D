from pathlib import Path
p=Path('BM318d.pyw')
s=p.read_text(encoding='utf-8')
assert "app.mainloop()" in s and "load_projects()" in s
s=s.replace('import sqlite3, json, datetime, threading, http.server, os','import sqlite3, json, datetime, threading, http.server, os, urllib.request')
s=s.replace("    con.commit()\n\ndef query", "    con.execute('CREATE TABLE IF NOT EXISTS task_dependencies(task_id INTEGER NOT NULL, depends_on INTEGER NOT NULL, PRIMARY KEY(task_id,depends_on))')\n    con.commit()\n\ndef query")
extension=r'''
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
'''
s=s.replace('load_projects()\ntry:\n    server=',extension+'\nload_projects()\ntry:\n    server=')
assert "Unified agent tab" in s
Path('BM318d-Unifie.pyw').write_text(s,encoding='utf-8')
print('UNIFIED_WRITTEN',len(s))
