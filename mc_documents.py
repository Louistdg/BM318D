"""Project cards plus explicit, bounded imports copied into local workspaces."""
import math
import base64
import binascii
import datetime
import re
import shutil
import sqlite3
import unicodedata
from pathlib import Path


class RevisionConflict(Exception):
    """An item was changed after the client read it."""


def migrate(c):
    c.execute("""CREATE TABLE IF NOT EXISTS mc_documents(
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        parent_id INTEGER REFERENCES mc_documents(id),
        kind TEXT NOT NULL CHECK(kind IN ('folder','file')),
        title TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        content_type TEXT NOT NULL DEFAULT 'note' CHECK(content_type IN ('note','link','info')),
        x REAL NOT NULL DEFAULT 100,
        y REAL NOT NULL DEFAULT 100,
        revision INTEGER NOT NULL DEFAULT 1,
        storage_path TEXT,
        storage_root TEXT,
        deleted_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mc_documents_project_parent ON mc_documents(project_id,parent_id)")
    columns={row[1] for row in c.execute('PRAGMA table_info(mc_documents)')}
    if 'storage_path' not in columns:c.execute('ALTER TABLE mc_documents ADD COLUMN storage_path TEXT')
    if 'storage_root' not in columns:c.execute('ALTER TABLE mc_documents ADD COLUMN storage_root TEXT')


IMPORT_MAX=8*1024*1024

# A SQLite backup does not contain imported file bytes. Keep the companion
# archive tied to its database snapshot; never follow a path outside imports.
def _import_target(project, storage_root, storage_path):
    root=Path(storage_root)
    relative=Path(storage_path)
    if not root.is_absolute() or relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Chemin de fichier importé invalide')
    parts=relative.parts
    if len(parts)<3 or parts[:2]!=('p%d'%project,'fichiers-importes'):
        raise ValueError('Chemin hors des fichiers importés')
    base=(root/parts[0]/parts[1]).resolve()
    target=(root/relative).resolve()
    if target.parent!=base and base not in target.parents:
        raise ValueError('Fichier importé hors espace projet')
    return target


def _import_rows(snapshot):
    c=sqlite3.connect(snapshot)
    try:
        cols={r[1] for r in c.execute('PRAGMA table_info(mc_documents)')}
        if not {'id','project_id','deleted_at','storage_root','storage_path'}.issubset(cols):
            # Snapshots created before the documents/import migration.
            return []
        return c.execute("""SELECT id,project_id,storage_root,storage_path
            FROM mc_documents WHERE deleted_at IS NULL AND storage_path IS NOT NULL
            ORDER BY id""").fetchall()
    finally:
        c.close()


def backup_imports(snapshot, archive):
    """Archive exactly the imported files referenced by the SQLite snapshot."""
    import hashlib
    import json
    import tempfile
    import zipfile

    archive=Path(archive)
    if archive.exists():
        raise FileExistsError('Archive de sauvegarde déjà présente')
    rows=_import_rows(snapshot)
    with tempfile.NamedTemporaryFile(prefix='.imports-',suffix='.partial',
                                     dir=archive.parent,delete=False) as tmp:
        temporary=Path(tmp.name)
    try:
        manifest=[]
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,
                             allowZip64=True) as z:
            for ident,project,root,relative in rows:
                if not root or not relative:
                    raise ValueError('Emplacement importé incomplet')
                target=_import_target(project,root,relative)
                if not target.is_file():
                    raise FileNotFoundError('Fichier importé manquant : '+str(target))
                entry='imports/%d-%d'%(project,ident)
                digest=hashlib.sha256()
                length=0
                with target.open('rb') as source,z.open(entry,'w') as output:
                    while block:=source.read(1024*1024):
                        length+=len(block)
                        if length>IMPORT_MAX:
                            raise ValueError('Fichier importé trop volumineux')
                        digest.update(block)
                        output.write(block)
                manifest.append({'id':ident,'project':project,'root':root,
                                 'relative':relative,'entry':entry,
                                 'size':length,'sha256':digest.hexdigest()})
            z.writestr('manifest.json',json.dumps({'version':1,'files':manifest},
                                                  ensure_ascii=False))
        # No replacement of an existing backup archive.
        if archive.exists():
            raise FileExistsError('Archive de sauvegarde déjà présente')
        temporary.rename(archive)
        return len(manifest)
    finally:
        temporary.unlink(missing_ok=True)


def restore_imports(snapshot, archive):
    """Preflight every file, then restore absent bytes; never overwrite local files."""
    import hashlib
    import json
    import zipfile

    snapshot=Path(snapshot)
    expected={(project,ident):(root,relative)
              for ident,project,root,relative in _import_rows(snapshot)}
    if not Path(archive).is_file():
        if expected:
            raise FileNotFoundError('Archive des fichiers importés absente : restauration refusée')
        return 0
    with zipfile.ZipFile(archive) as z:
        # Taille declaree verifiee avant toute decompression, puis lecture bornee.
        entree=z.getinfo('manifest.json')
        if entree.file_size>8*1024*1024:
            raise ValueError('Manifeste de sauvegarde trop volumineux')
        with z.open('manifest.json') as flux:
            data=flux.read(8*1024*1024+1)
        if len(data)>8*1024*1024:
            raise ValueError('Manifeste de sauvegarde trop volumineux')
        doc=json.loads(data)
        if not isinstance(doc,dict) or doc.get('version')!=1 or not isinstance(doc.get('files'),list):
            raise ValueError('Manifeste de sauvegarde invalide')
        files=doc['files']
        if len(files)!=len(expected):
            raise ValueError('Fichiers de la sauvegarde incomplets')
        seen=set()
        pending=[]
        names=set(z.namelist())
        if names!={'manifest.json'}|{f.get('entry') for f in files if isinstance(f,dict)}:
            raise ValueError('Contenu ZIP inattendu')
        for f in files:
            if not isinstance(f,dict):
                raise ValueError('Entrée de sauvegarde invalide')
            key=(f.get('project'),f.get('id'))
            if key not in expected or key in seen:
                raise ValueError('Fichier du manifeste non référencé par la base')
            seen.add(key)
            root,relative=expected[key]
            entry='imports/%d-%d'%key
            if (f.get('root'),f.get('relative'),f.get('entry'))!=(root,relative,entry):
                raise ValueError('Archive différente de la base SQLite')
            target=_import_target(key[0],root,relative)
            size=f.get('size')
            if type(size) is not int or size<0 or size>IMPORT_MAX:
                raise ValueError('Taille du fichier archivé invalide')
            if z.getinfo(entry).file_size!=size:
                raise ValueError('Taille du ZIP incohérente')
            digest=hashlib.sha256()
            with z.open(entry) as source:
                while block:=source.read(1024*1024):
                    digest.update(block)
            if digest.hexdigest()!=f.get('sha256'):
                raise ValueError('Empreinte du fichier archivé invalide')
            if target.exists():
                if not target.is_file():
                    raise ValueError('Emplacement de restauration occupé')
                with target.open('rb') as existing:
                    local=hashlib.file_digest(existing,'sha256').hexdigest()
                if local!=f['sha256']:
                    raise FileExistsError('Fichier local différent : '+str(target))
            else:
                pending.append((entry,target,key[0],root,relative))
        for entry,target,project,root,relative in pending:
            target.parent.mkdir(parents=True,exist_ok=True)
            if _import_target(project,root,relative)!=target:
                raise ValueError('Chemin restauré changé')
            with z.open(entry) as source,target.open('xb') as output:
                while block:=source.read(1024*1024):
                    output.write(block)
        return len(pending)

def import_file(c, project, data, workspace_root):
    """Copy a user-selected file into the project workspace; SQLite keeps metadata only."""
    name=data.get('name')
    if (not isinstance(name,str) or not name.strip() or len(name)>255 or
            any(ch in name for ch in ('\\','/','\x00','<','>',':','"','|','?','*')) or
            any(ord(ch)<32 for ch in name) or name in ('.','..') or name.endswith(('.',' '))):
        raise ValueError('Nom de fichier invalide')
    title=Path(name).name
    if not title or title in ('.','..'):
        raise ValueError('Nom de fichier invalide')
    if Path(title).stem.upper() in {'CON','PRN','AUX','NUL',*(('COM%d'%i) for i in range(1,10)),*(('LPT%d'%i) for i in range(1,10))}:
        raise ValueError('Nom de fichier réservé par Windows')
    encoded=data.get('data')
    if not isinstance(encoded,str) or len(encoded)>((IMPORT_MAX+2)//3)*4:
        raise ValueError('Fichier trop volumineux (maximum 8 Mo)')
    try:content=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error):raise ValueError('Fichier importé invalide')
    if not content or len(content)>IMPORT_MAX:
        raise ValueError('Fichier vide ou supérieur à 8 Mo')
    x=_position(data.get('x',100));y=_position(data.get('y',100))
    parent_id=data.get('parent_id')
    if parent_id not in (None,''):
        parent_id=_id(parent_id);folder=_item(c,project,parent_id)
        if folder['kind']!='folder':raise ValueError('Le dossier de destination est invalide')
        _parent(c,project,parent_id)
        folder_chain=[];current=folder
        while current:
            slug=unicodedata.normalize('NFKD',current['title']).encode('ascii','ignore').decode('ascii').lower()
            slug=re.sub(r'[^a-z0-9]+','-',slug).strip('-')[:40] or 'dossier'
            folder_chain.append('dossier-%d-%s'%(current['id'],slug))
            current=_item(c,project,current['parent_id']) if current['parent_id'] is not None else None
        folder_chain.reverse()
    else:folder_chain=[]
    root=Path(workspace_root).resolve()
    target_dir=root/('p%d'%project)/'fichiers-importes'
    for segment in folder_chain:target_dir/=segment
    target_dir.mkdir(parents=True,exist_ok=True)
    resolved_dir=target_dir.resolve()
    if root not in resolved_dir.parents:raise ValueError('Dossier de destination hors de l’espace du projet')
    stem=Path(title).stem[:180] or 'fichier';suffix=Path(title).suffix[:32]
    target=resolved_dir/(stem+suffix);index=2
    while target.exists():
        target=resolved_dir/('%s (%d)%s'%(stem,index,suffix));index+=1
    try:
        with target.open('xb') as stream:stream.write(content)
    except FileExistsError:
        raise ValueError('Un fichier de même nom vient d’être importé, recommence')
    relative=target.relative_to(root).as_posix()
    try:
        ident=c.execute("""INSERT INTO mc_documents(project_id,parent_id,kind,title,content,content_type,x,y,storage_path,storage_root)
            VALUES(?,?,'file',?,'','info',?,?,?,?)""",(project,parent_id,title,x,y,relative,str(root))).lastrowid
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {'item':_item(c,project,ident),'saved_to':str(target),'bytes':len(content)}


def local_file(c,project,item_id,workspace_root):
    item=_item(c,project,item_id)
    if item['kind']!='file' or not item.get('storage_path'):raise ValueError('Fichier local introuvable')
    root=Path(item.get('storage_root') or workspace_root).resolve()
    candidate=root/item['storage_path']
    target=candidate.resolve()
    if root not in target.parents or not target.is_file():raise ValueError('Fichier local absent ou hors du dossier du projet')
    return target,item['title']


def _id(value):
    if type(value) is not int or value <= 0:
        raise ValueError('Identifiant invalide')
    return value


def _revision(value, action):
    if type(value) is not int or value <= 0:
        raise ValueError('Revision requise pour ' + action + ' : recharge la fiche avant de reessayer')
    return value


def _vers_corbeille(item, projet, workspace_root):
    """Deplace le fichier importe d'une fiche supprimee dans corbeille/ (recuperable)."""
    relatif = item.get('storage_path')
    if not relatif:
        return None
    racine = Path(item.get('storage_root') or workspace_root).resolve()
    source = racine / relatif
    if not source.is_file():
        return None
    dossier = racine / 'corbeille'
    dossier.mkdir(parents=True, exist_ok=True)
    nom = '%s-p%d-%d-%s' % (datetime.datetime.now().strftime('%Y%m%d-%H%M%S'), projet, item['id'], source.name)
    cible = dossier / nom
    shutil.move(str(source), str(cible))
    return cible


def _text(value, max_length, required=False):
    if not isinstance(value, str) or len(value) > max_length or (required and not value.strip()):
        raise ValueError('Texte invalide')
    return value.strip() if required else value


def _position(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 10000:
        raise ValueError('Position invalide')
    return value


def _item(c, project, item_id):
    row = c.execute('SELECT * FROM mc_documents WHERE id=? AND project_id=? AND deleted_at IS NULL',
                    (_id(item_id), project)).fetchone()
    if row is None:
        raise ValueError('Fiche introuvable dans ce projet')
    return dict(row)


def items(c, project):
    result=[]
    for row in c.execute('SELECT * FROM mc_documents WHERE project_id=? AND deleted_at IS NULL ORDER BY id',(project,)):
        item=dict(row)
        if item.get('storage_path') and item.get('storage_root'):
            item['local_path']=str(Path(item['storage_root'])/Path(item['storage_path']))
        result.append(item)
    return {'items':result}


def _parent(c, project, parent_id, item_id=None):
    if parent_id is None:
        return
    folder = _item(c, project, _id(parent_id))
    if folder['kind'] != 'folder':
        raise ValueError('Le parent doit être un dossier')
    seen = set()
    while folder:
        if folder['id'] == item_id or folder['id'] in seen:
            raise ValueError('Déplacement circulaire refusé')
        seen.add(folder['id'])
        folder = _item(c, project, folder['parent_id']) if folder['parent_id'] is not None else None


def save(c, project, data):
    existing = None
    if 'id' in data:
        existing = _item(c, project, data['id'])
        revision = _revision(data.get('revision'), 'modifier la fiche')
        if revision != existing['revision']:
            raise RevisionConflict('Fiche modifiée ailleurs : recharge avant de réessayer')
    kind = data.get('kind', existing['kind'] if existing else 'file')
    if kind not in ('folder', 'file'):
        raise ValueError('Type de fiche invalide')
    title = _text(data.get('title', existing['title'] if existing else ''), 160, True)
    content = _text(data.get('content', existing['content'] if existing else ''), 8000)
    content_type = data.get('content_type', existing['content_type'] if existing else 'note')
    if content_type not in ('note', 'link', 'info'):
        raise ValueError('Contenu de fiche invalide')
    if kind == 'folder' and (content or content_type != 'note'):
        raise ValueError('Un dossier ne contient pas de texte')
    x = _position(data.get('x', existing['x'] if existing else 100))
    y = _position(data.get('y', existing['y'] if existing else 100))
    parent_id = data.get('parent_id', existing['parent_id'] if existing else None)
    if parent_id is not None:
        _id(parent_id)
    _parent(c, project, parent_id, existing['id'] if existing else None)
    if existing:
        if kind == 'file' and existing['kind'] == 'folder':
            if c.execute('SELECT 1 FROM mc_documents WHERE parent_id=? AND deleted_at IS NULL', (existing['id'],)).fetchone():
                raise ValueError('Déplace les éléments du dossier avant de le convertir')
        c.execute("""UPDATE mc_documents SET parent_id=?,kind=?,title=?,content=?,content_type=?,
                  x=?,y=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP
                  WHERE id=? AND project_id=? AND revision=? AND deleted_at IS NULL""",
                  (parent_id,kind,title,content,content_type,x,y,existing['id'],project,existing['revision']))
        ident = existing['id']
    else:
        ident = c.execute("""INSERT INTO mc_documents(project_id,parent_id,kind,title,content,content_type,x,y)
                  VALUES(?,?,?,?,?,?,?,?)""",
                  (project,parent_id,kind,title,content,content_type,x,y)).lastrowid
    return {'item': _item(c, project, ident)}


def delete(c, project, data, workspace_root=None):
    item = _item(c, project, data.get('id'))
    if _revision(data.get('revision'), 'supprimer la fiche') != item['revision']:
        raise RevisionConflict('Fiche modifiée ailleurs : suppression refusée')
    if c.execute('SELECT 1 FROM mc_documents WHERE parent_id=? AND deleted_at IS NULL', (item['id'],)).fetchone():
        raise ValueError('Dossier non vide : déplace les éléments avant suppression')
    c.execute("UPDATE mc_documents SET deleted_at=CURRENT_TIMESTAMP,revision=revision+1 WHERE id=? AND project_id=? AND revision=?",
              (item['id'],project,item['revision']))
    try:
        rangee = _vers_corbeille(item, project, workspace_root)
    except OSError:
        rangee = None
    return {'deleted': item['id'], 'corbeille': str(rangee) if rangee else None}
