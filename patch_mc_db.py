from pathlib import Path
p=Path('MissionControl.py')
s=p.read_text(encoding='utf-8')
s=s.replace('def connect():\n c=sqlite3.connect(DB,timeout=20)','class ManagedConnection(sqlite3.Connection):\n def __exit__(self,typ,value,tb):\n  try:return super().__exit__(typ,value,tb)\n  finally:self.close()\ndef connect():\n c=sqlite3.connect(DB,timeout=20,factory=ManagedConnection)')
p.write_text(s,encoding='utf-8')
print('PATCHED_CONNECTIONS')
