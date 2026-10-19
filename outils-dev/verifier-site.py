"""Contrôle de livraison : HTML, ressources et empreintes du fichier réellement livré."""
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import urlsplit

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'site'
release = json.loads((root / 'release.json').read_text())
installer = root / 'telechargements' / release['installer']['filename']
assert installer.stat().st_size == release['installer']['size'], 'Taille installateur incohérente'
assert hashlib.sha256(installer.read_bytes()).hexdigest() == release['installer']['sha256'], 'Empreinte installateur incohérente'

class Inspect(HTMLParser):
    def handle_starttag(self, tag, attributes):
        a = dict(attributes)
        if tag == 'img':
            assert a.get('alt') and a.get('width') and a.get('height'), 'Image sans description/dimensions'
            assert not a['src'].startswith('data:'), 'Image incorporée au HTML'
            assert (root / a['src']).is_file(), a['src']
        if tag == 'a' and '.exe' in a.get('href', ''):
            assert a['href'].startswith('https://dioptre.socle-construction.be/'), 'Téléchargement non HTTPS'
            assert Path(urlsplit(a['href']).path).name == installer.name, 'Mauvais installateur'
        if tag == 'a' and a.get('href', '').startswith('assets/'):
            assert (root / a['href']).is_file(), 'Agrandissement absent'

for name in ('index.html', 'installation.html'):
    html = (root / name).read_text()
    Inspect().feed(html)
    assert installer.name in html
    assert '2.6.0' not in html
    assert "b.setAttribute('aria-pressed', String(sombre()))" in html
homepage = (root / 'index.html').read_text()
for artifact in ('installer', 'audit'):
    assert release[artifact]['sha256'] in homepage, f'Empreinte {artifact} absente'
    assert str(release[artifact]['size']) in homepage, f'Taille {artifact} absente'
assert homepage.index('class="hero-preview"') < homepage.index('id="fonctions"')
assert 'Fermez la fenêtre noire' not in (root / 'installation.html').read_text()
assert 'Données 100 % locales' not in homepage
print('OK : artefact, empreintes, liens HTTPS, captures, agrandissements, version et état du thème.')
