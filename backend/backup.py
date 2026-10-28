"""Portable workbench data archive, distinct from a full game-project snapshot."""
import json
import zipfile
from pathlib import Path
from . import assets, store


def write(pid, output=None):
    with store.db() as c:
        c.execute('BEGIN')
        p = c.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
        if not p:
            raise ValueError('项目不存在')
        manifest = {'format': 10, 'project': dict(p)}
        model_defaults = c.execute('SELECT value FROM settings WHERE key=?', ('generation_models:' + pid,)).fetchone()
        if model_defaults: manifest['generation_models'] = json.loads(model_defaults['value'])
        for table in ('documents', 'tasks', 'assets', 'conversations', 'messages', 'runs', 'tool_events', 'music_jobs', 'art_jobs', 'character_jobs', 'project_intakes', 'tripo_jobs', 'task_acceptances', 'work_jobs', 'task_creations'):
            manifest[table] = [dict(r) for r in c.execute(f'SELECT * FROM {table} WHERE project_id=?', (pid,))]
        manifest['document_versions'] = [dict(r) for r in c.execute('SELECT v.* FROM document_versions v JOIN documents d ON v.doc_id=d.id WHERE d.project_id=?', (pid,))]
        for table in ('task_dependencies', 'task_documents', 'task_reviews', 'task_deliveries'):
            manifest[table] = [dict(r) for r in c.execute(f'SELECT l.* FROM {table} l JOIN tasks t ON l.task_id=t.id WHERE t.project_id=?', (pid,))]
        manifest['music_assets'] = [dict(r) for r in c.execute('SELECT m.* FROM music_assets m JOIN music_jobs j ON j.id=m.job_id WHERE j.project_id=?', (pid,))]
        for row in manifest['work_jobs']: row['scope'] = '{}'
    output = Path(output) if output else store.DATA / 'exports' / (store.uid() + '.zip')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for a in manifest['assets']:
            versions, mapped = json.loads(a['versions']), {}
            for i, v in enumerate(versions):
                source = Path(v['path'])
                assets.authorized_path(pid, source)
                if not source.is_file():
                    raise ValueError('有资产已移动，请恢复文件后再导出：' + a['name'])
                before = source.stat()
                dest = f"assets/{a['id']}/{i}{source.suffix}"
                archive.write(source, dest)
                after = source.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('资产在备份时发生变化，请暂停编辑后重试')
                mapped[str(source)] = dest
                v['path'] = dest
            a['active'] = mapped[a['active']]
            a['versions'] = json.dumps(versions)
            a['source'] = a['active']
        archive.writestr('project.json', json.dumps(manifest, ensure_ascii=False))
    return output
