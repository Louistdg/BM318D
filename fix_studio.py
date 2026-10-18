from pathlib import Path
p=Path('BM318d-Studio.pyw')
s=p.read_text(encoding='utf-8')
s=s.replace("bg=bg or C['bg']","bg=C.get(bg,bg) if bg else C['bg']")
p.write_text(s,encoding='utf-8')
print('PATCHED')
