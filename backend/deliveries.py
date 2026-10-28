"""Pinned asset versions and immutable acceptance receipts, without inferred quality claims."""
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from . import assets, store


@lru_cache(maxsize=1024)
def file_hash(path, size, mtime, ctime, inode):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk := f.read(1024 * 1024): h.update(chunk)
    after = Path(path).stat()
    if (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino) != (size, mtime, ctime, inode): raise ValueError('交付文件在核对时变化，请暂停写入后重试')
    return h.hexdigest()


def version(a, index=None):
    values = json.loads(a['versions'])
    active = next((i for i, v in enumerate(values) if v['path'] == a['active']), None)
    index = active if index is None else index
    if type(index) is not int or not 0 <= index < len(values): raise ValueError('资产版本不存在')
    path = assets.authorized_path(a['project_id'], values[index]['path'])
    info = path.stat()
    if not path.is_file(): raise ValueError('交付文件不可读取')
    return {'version_index': index, 'sha256': file_hash(str(path), info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino), 'active_index': active}


def origin(aid, c):
    for kind, table, fields in [('music', 'music_jobs', ('asset_id',)), ('art', 'art_jobs', ('asset_id',)), ('blender', 'character_jobs', ('model_id', 'source_id', 'preview_id')), ('tripo', 'tripo_jobs', ('model_id', 'preview_id'))]:
        if kind == 'music':
            row = c.execute('SELECT j.*,m.serial_no FROM music_assets m JOIN music_jobs j ON j.id=m.job_id WHERE m.asset_id=?', (aid,)).fetchone()
        else:
            row = c.execute(f'SELECT * FROM {table} WHERE ' + ' OR '.join(f'{k}=?' for k in fields) + ' ORDER BY created DESC LIMIT 1', (aid,) * len(fields)).fetchone()
        if row:
            j = dict(row); spec = json.loads(j['spec'])
            return {'kind': kind, 'job_id': j['id'], 'run_id': j.get('run_id'), 'output_id': j.get('serial_no'), 'model': spec.get('mv', spec.get('model', spec.get('checkpoint_title', ''))), 'spec_sha256': hashlib.sha256(j['spec'].encode()).hexdigest()}
    return None


def bind(c, tid, pid, values):
    if not isinstance(values, list) or len(values) > 100: raise ValueError('任务交付最多关联100项资产版本')
    pins, seen = [], set()
    for v in values:
        if not isinstance(v, dict) or set(v) != {'asset_id', 'version_index', 'sha256'} or not isinstance(v['asset_id'], str) or v['asset_id'] in seen or not isinstance(v['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', v['sha256']): raise ValueError('交付需包含不重复的资产ID、版本索引和SHA-256')
        row = c.execute('SELECT * FROM assets WHERE id=? AND project_id=?', (v['asset_id'], pid)).fetchone()
        if not row: raise ValueError('交付资产必须属于当前项目')
        try: checked = version(dict(row), v['version_index'])
        except OSError: raise ValueError('交付文件缺失，请先恢复或重新导入') from None
        if checked['sha256'] != v['sha256']: raise ValueError('交付内容已变化，请刷新后重新选择')
        seen.add(v['asset_id']); pins.append((tid, v['asset_id'], v['version_index'], v['sha256'], store.now()))
    c.execute('DELETE FROM task_deliveries WHERE task_id=?', (tid,))
    c.executemany('INSERT INTO task_deliveries VALUES (?,?,?,?,?)', pins)


def links(pid, c):
    values = {}
    for row in c.execute('SELECT l.*,a.name,a.kind,a.active,a.versions,a.project_id FROM task_deliveries l JOIN assets a ON a.id=l.asset_id WHERE a.project_id=?', (pid,)):
        row = dict(row); missing, changed = False, True
        try:
            current = version(row)
            pinned = version(row, row['version_index'])
            changed = current['version_index'] != row['version_index'] or current['sha256'] != row['sha256'] or pinned['sha256'] != row['sha256']
        except (OSError, ValueError):
            current, missing = {}, True
        value = {k: row[k] for k in ('asset_id', 'name', 'kind', 'version_index', 'sha256', 'created')}
        value.update(changed=changed, missing=missing, current_version_index=current.get('version_index'), current_hash=current.get('sha256'), origin=origin(row['asset_id'], c))
        values.setdefault(row['task_id'], []).append(value)
    return values


def accept(c, task, evidence):
    snapshot = {'deliveries': [{k: v[k] for k in ('asset_id', 'name', 'kind', 'version_index', 'sha256', 'origin')} for v in task['asset_links']],
                'documents': [{'doc_id': d['doc_id'], 'revision': d['revision']} for d in task['document_links']], 'dependency_ids': sorted(task['dependency_ids']),
                'note': '记录本次声明与确切版本；不自动证明可玩性、商用权利或人工质量验收'}
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    last = c.execute('SELECT evidence,snapshot FROM task_acceptances WHERE task_id=? ORDER BY created DESC,rowid DESC LIMIT 1', (task['id'],)).fetchone()
    if task['status'] != 'done' or not last or (last['evidence'], last['snapshot']) != (evidence, encoded):
        c.execute('INSERT INTO task_acceptances VALUES (?,?,?,?,?,?)', (store.uid(), task['project_id'], task['id'], evidence, encoded, store.now()))


def history(tid):
    if not store.one('SELECT id FROM tasks WHERE id=?', (tid,)): raise ValueError('任务不存在')
    return [{**r, 'snapshot': json.loads(r['snapshot'])} for r in store.rows('SELECT * FROM task_acceptances WHERE task_id=? ORDER BY created DESC,rowid DESC', (tid,))]
