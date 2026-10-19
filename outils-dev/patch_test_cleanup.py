from pathlib import Path
p=Path('test_mission_control.py')
s=p.read_text(encoding='utf-8').replace('tempfile.TemporaryDirectory()','tempfile.TemporaryDirectory(ignore_cleanup_errors=True)')
p.write_text(s,encoding='utf-8')
