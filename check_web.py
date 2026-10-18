from pathlib import Path
s=Path('BM318d-Railway.html').read_text(encoding='utf-8')
a=s.split('<script>',1)[1].split('</script>',1)[0]
a=a.replace("$('links').innerHTML=$('links').innerHTML.replace(/<path d=\"M[\\s\\S]*$/,'');/* full refresh on release */",'')
s=s.split('<script>',1)[0]+'<script>'+a+'</script></body></html>'
Path('BM318d-Railway.html').write_text(s,encoding='utf-8')
Path('check_web.js').write_text(a,encoding='utf-8')
print('SCRIPT_BYTES',len(a))
