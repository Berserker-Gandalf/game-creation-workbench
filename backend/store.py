import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('WORKBENCH_DATA') or (Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'ZAOWU/data' if (ROOT / 'packaged.json').is_file() else ROOT / '.workbench')).resolve()


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid4().hex


@contextmanager
def db():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA / 'workbench.sqlite3', timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init():
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, engine TEXT NOT NULL,
          root TEXT NOT NULL, brief TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
          title TEXT NOT NULL, content TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
          authority TEXT NOT NULL DEFAULT 'draft', updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS document_versions (
          doc_id TEXT NOT NULL REFERENCES documents(id), revision INTEGER NOT NULL,
          content TEXT NOT NULL, title TEXT NOT NULL, authority TEXT NOT NULL,
          created TEXT NOT NULL, PRIMARY KEY(doc_id, revision));
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
          title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'todo', detail TEXT NOT NULL DEFAULT '',
          evidence TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS task_dependencies (
          task_id TEXT NOT NULL REFERENCES tasks(id), depends_on TEXT NOT NULL REFERENCES tasks(id),
          PRIMARY KEY(task_id, depends_on));
        CREATE TABLE IF NOT EXISTS task_documents (
          task_id TEXT NOT NULL REFERENCES tasks(id), doc_id TEXT NOT NULL REFERENCES documents(id),
          revision INTEGER NOT NULL, PRIMARY KEY(task_id, doc_id));
        CREATE TABLE IF NOT EXISTS task_reviews (
          task_id TEXT PRIMARY KEY REFERENCES tasks(id), reason TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS task_deliveries (
          task_id TEXT NOT NULL REFERENCES tasks(id), asset_id TEXT NOT NULL REFERENCES assets(id),
          version_index INTEGER NOT NULL, sha256 TEXT NOT NULL, created TEXT NOT NULL,
          PRIMARY KEY(task_id,asset_id));
        CREATE TABLE IF NOT EXISTS task_acceptances (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), task_id TEXT NOT NULL REFERENCES tasks(id),
          evidence TEXT NOT NULL, snapshot TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assets (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
          name TEXT NOT NULL, source TEXT NOT NULL, active TEXT NOT NULL, kind TEXT NOT NULL,
          versions TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(project_id, source));
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
          role TEXT NOT NULL, content TEXT NOT NULL, provider TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS music_jobs (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
          spec TEXT NOT NULL, status TEXT NOT NULL, serials TEXT NOT NULL, result TEXT NOT NULL,
          created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS music_assets (
          job_id TEXT NOT NULL REFERENCES music_jobs(id), serial_no TEXT NOT NULL, asset_id TEXT NOT NULL UNIQUE REFERENCES assets(id),
          sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, mime TEXT NOT NULL, duration REAL NOT NULL, created TEXT NOT NULL,
          PRIMARY KEY(job_id,serial_no));
        CREATE TABLE IF NOT EXISTS work_jobs (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), source_kind TEXT NOT NULL, source_id TEXT NOT NULL,
          action TEXT NOT NULL, parameters TEXT NOT NULL, scope TEXT NOT NULL, status TEXT NOT NULL,
          result TEXT NOT NULL, error TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
          kind TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL,
          usage TEXT NOT NULL DEFAULT '{}', created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS conversations (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), agent TEXT NOT NULL,
          title TEXT NOT NULL, provider TEXT NOT NULL DEFAULT 'codex', model TEXT NOT NULL DEFAULT '',
          memory TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0,
          created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tool_events (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), project_id TEXT NOT NULL,
          conversation_id TEXT, tool TEXT NOT NULL, arguments TEXT NOT NULL, result TEXT NOT NULL,
          status TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS art_jobs (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), run_id TEXT REFERENCES runs(id),
          asset_id TEXT REFERENCES assets(id), provider TEXT NOT NULL, spec TEXT NOT NULL,
          status TEXT NOT NULL, result TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS task_creations (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), task_id TEXT NOT NULL REFERENCES tasks(id),
          kind TEXT NOT NULL, job_id TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(kind,job_id));
        CREATE TABLE IF NOT EXISTS model_checks (
          provider TEXT NOT NULL, model TEXT NOT NULL, capability TEXT NOT NULL, verified_at TEXT NOT NULL,
          PRIMARY KEY(provider,model,capability));
        CREATE TABLE IF NOT EXISTS character_jobs (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), parent_id TEXT,
          run_id TEXT REFERENCES runs(id), model_id TEXT REFERENCES assets(id), source_id TEXT REFERENCES assets(id),
          preview_id TEXT REFERENCES assets(id), spec TEXT NOT NULL, status TEXT NOT NULL,
          result TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS project_intakes (
          project_id TEXT PRIMARY KEY REFERENCES projects(id), summary_document_id TEXT NOT NULL REFERENCES documents(id),
          report TEXT NOT NULL, files TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tripo_jobs (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), run_id TEXT REFERENCES runs(id),
          model_id TEXT REFERENCES assets(id), preview_id TEXT REFERENCES assets(id), region TEXT NOT NULL,
          spec TEXT NOT NULL, status TEXT NOT NULL, task_id TEXT NOT NULL, result TEXT NOT NULL,
          created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS project_snapshots (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), parent_id TEXT,
          label TEXT NOT NULL, kind TEXT NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL,
          folder TEXT NOT NULL, archive TEXT NOT NULL, archive_sha256 TEXT NOT NULL, result TEXT NOT NULL,
          created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS github_publications (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), snapshot_id TEXT NOT NULL REFERENCES project_snapshots(id),
          repository TEXT NOT NULL, branch TEXT NOT NULL, "commit" TEXT NOT NULL, status TEXT NOT NULL,
          folder TEXT NOT NULL, report TEXT NOT NULL, url TEXT NOT NULL, error TEXT NOT NULL,
          created TEXT NOT NULL, updated TEXT NOT NULL);
        ''')
        for table, additions in {
            'messages': {'conversation_id': 'TEXT', 'run_id': 'TEXT', 'model': "TEXT NOT NULL DEFAULT ''", 'asset_id': 'TEXT'},
            'runs': {'conversation_id': 'TEXT', 'provider': "TEXT NOT NULL DEFAULT ''", 'model': "TEXT NOT NULL DEFAULT ''", 'agent': "TEXT NOT NULL DEFAULT ''", 'runtime': "TEXT NOT NULL DEFAULT '{}'"},
        }.items():
            existing = {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
            for name, kind in additions.items():
                if name not in existing:
                    c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
        c.execute('CREATE INDEX IF NOT EXISTS messages_conversation_order ON messages(conversation_id,created)')
        c.execute('CREATE INDEX IF NOT EXISTS assets_project ON assets(project_id)')
        c.execute('CREATE INDEX IF NOT EXISTS documents_project ON documents(project_id)')
        c.execute("UPDATE runs SET status='interrupted', detail='服务曾中断，请核对外部结果后再重试', updated=? WHERE status='running'", (now(),))
        c.execute("UPDATE music_jobs SET status='unknown' WHERE status='submitting'")
        c.execute("UPDATE work_jobs SET status=CASE WHEN action='query' THEN 'queued' ELSE 'interrupted' END,error='服务曾中断；只读查询可接续，下载需人工核对后继续',updated=? WHERE status='running'", (now(),))
        c.execute("UPDATE tool_events SET status='interrupted',updated=? WHERE status='running'", (now(),))
        c.execute("UPDATE art_jobs SET status='interrupted',updated=? WHERE status='running'", (now(),))
        c.execute("UPDATE character_jobs SET status='interrupted',updated=? WHERE status='building'", (now(),))
        c.execute("UPDATE tripo_jobs SET status='unknown',updated=? WHERE status='submitting'", (now(),))
        c.execute("UPDATE tripo_jobs SET status='ready',updated=? WHERE status='importing'", (now(),))
        c.execute("UPDATE project_snapshots SET status='interrupted',result=?,updated=? WHERE status IN ('pending','copying')", (json.dumps({'error': '服务曾中断，部分归档不视为有效快照'}), now()))
        c.execute("UPDATE github_publications SET status='unknown',error=?,updated=? WHERE status='pushing'", ('服务曾中断，请先核对远端提交，禁止直接重推', now()))
    from .conversations import migrate_legacy
    migrate_legacy()


def rows(sql, args=()):
    with db() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql, args=()):
    result = rows(sql, args)
    return result[0] if result else None


def execute(sql, args=()):
    with db() as c:
        c.execute(sql, args)


def setting(key, default=None):
    row = one('SELECT value FROM settings WHERE key=?', (key,))
    return json.loads(row['value']) if row else default


def set_setting(key, value):
    execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))


def project_dir(project_id):
    path = DATA / 'projects' / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def project(project_id):
    p = one('SELECT * FROM projects WHERE id=?', (project_id,))
    if not p:
        raise ValueError('项目不存在')
    return p


def snapshot(project_id, include_messages=True):
    from .tasks import list_tasks
    from . import intake
    imported = intake.current(project_id, True)
    inventory = {f.get('asset_id'): f for f in (imported or {}).get('files', []) if f.get('asset_id')}
    project_assets = rows('SELECT * FROM assets WHERE project_id=? ORDER BY created DESC', (project_id,))
    for a in project_assets:
        if a['id'] in inventory:
            f = inventory[a['id']]
            a.update(category=f['category'], relative_path=f['path'], source_status=f['status'])
    if imported:
        imported.pop('files')
    return {
        'project': project(project_id),
        'documents': rows('SELECT * FROM documents WHERE project_id=? ORDER BY updated DESC', (project_id,)),
        'tasks': list_tasks(project_id),
        'assets': project_assets,
        'intake': imported,
        'messages': rows('SELECT * FROM messages WHERE project_id=? ORDER BY created', (project_id,)) if include_messages else [],
        'runs': rows('SELECT * FROM runs WHERE project_id=? ORDER BY created DESC LIMIT 30', (project_id,)),
    }


def run_start(project_id, kind, detail, conversation_id=None, provider='', model='', agent=''):
    rid = uid()
    execute('''INSERT INTO runs (id,project_id,kind,status,detail,usage,created,updated,conversation_id,provider,model,agent)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (rid, project_id, kind, 'running', detail, '{}', now(), now(), conversation_id, provider, model, agent))
    return rid


def run_end(rid, status, detail, usage=None):
    execute('UPDATE runs SET status=?, detail=?, usage=?, updated=? WHERE id=?',
            (status, detail, json.dumps(usage or {}), now(), rid))
