"""Project-scoped cards and folders: additive storage, no filesystem access."""
import math
import sqlite3


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
        deleted_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mc_documents_project_parent ON mc_documents(project_id,parent_id)")


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
    return {'items': [dict(row) for row in c.execute(
        'SELECT * FROM mc_documents WHERE project_id=? AND deleted_at IS NULL ORDER BY id', (project,))]}


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
