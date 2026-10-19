from pathlib import Path
p=Path('improve_canvas.py')
s=p.read_text(encoding='utf-8')
s='\n'.join(line for line in s.splitlines() if not line.startswith('s=s.replace("const svg='))+'\n'
p.write_text(s,encoding='utf-8')
