"""Régression d'installation propre, exécutée dans un processus jetable."""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
tmp=Path(tempfile.mkdtemp(prefix="dioptre-clean-"))
db=tmp/"clean.sqlite3"
env=dict(os.environ,MC_DB=str(db),MC_WORKSPACES=str(tmp/"workspaces"))
code=r'''
from pathlib import Path
import MissionControl as mc
mc.DB=Path(__import__("os").environ["MC_DB"])
mc.init()
with mc.connect() as c:
 tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 assert {"projects","tasks","events","task_dependencies","canvas_positions"}<=tables
 project=c.execute("SELECT id,name FROM projects").fetchall()
 assert len(project)==1 and project[0][1]=="Mon premier projet"
 c.execute("INSERT INTO tasks(project_id,title) VALUES(?,?)",(project[0][0],"Conserver"))
mc.init()
with mc.connect() as c:assert c.execute("SELECT title FROM tasks").fetchone()[0]=="Conserver"
missing=Path(__import__("os").environ["MC_DB"]).with_name("missing.sqlite3")
mc.DB=missing
assert mc.sauvegarder() is None and not missing.exists()
print("CLEAN_INSTALL_OK")
'''
try:
 result=subprocess.run([sys.executable,"-c",code],cwd=root,env=env,text=True,capture_output=True,timeout=30)
 if result.returncode:raise SystemExit(result.stdout+result.stderr)
 print(result.stdout.strip()+": tables legacy, premier projet et lignes conservées; aucune base vide créée pour une sauvegarde")
finally:
 shutil.rmtree(tmp,ignore_errors=True)
