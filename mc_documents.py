"""Project cards plus explicit, bounded imports copied into local workspaces."""
import math
import base64
import binascii
import re
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
        revision = _id(data.get('revision'))
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


def delete(c, project, data):
    item = _item(c, project, data.get('id'))
    if _id(data.get('revision')) != item['revision']:
        raise RevisionConflict('Fiche modifiée ailleurs : suppression refusée')
    if c.execute('SELECT 1 FROM mc_documents WHERE parent_id=? AND deleted_at IS NULL', (item['id'],)).fetchone():
        raise ValueError('Dossier non vide : déplace les éléments avant suppression')
    c.execute("UPDATE mc_documents SET deleted_at=CURRENT_TIMESTAMP,revision=revision+1 WHERE id=? AND project_id=? AND revision=?",
              (item['id'],project,item['revision']))
    return {'deleted': item['id']}
