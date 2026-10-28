"""Full filtered project snapshots with a portable workbench archive and hash receipt."""
import asyncio
import hashlib
import json
import os
import shutil
import stat
import subprocess
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath

from . import assets, backup, intake, store
from . import __version__

RUNNING = {}
MAX_FILES = 100000
MAX_BYTES = 100 * 1024 ** 3
SKIP_DIRS = {'.git', '.svn', '.hg', '.workbench', '.dev', '.releases', '.venv', 'venv', 'node_modules',
             'library', 'temp', 'obj', 'bin', 'binaries', 'intermediate', 'saved', 'deriveddatacache', '__pycache__', '.vs', '.idea', '.suno-cn', '.codex', '.claude'}
PRIVATE_FILES = {'auth.json', 'credentials.json', '.ds_store', 'thumbs.db', '.git', '.svn', '.hg', '.instance.lock'}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk := f.read(4 * 1024 * 1024): h.update(chunk)
    return h.hexdigest()


def job(sid):
    row = store.one('SELECT * FROM project_snapshots WHERE id=?', (sid,))
    if not row: raise ValueError('项目快照不存在')
    row['result'] = json.loads(row['result'])
    return row


def jobs(pid):
    store.project(pid)
    return [job(r['id']) for r in store.rows('SELECT id FROM project_snapshots WHERE project_id=? ORDER BY created DESC,rowid DESC LIMIT 100', (pid,))]


def inventory(root):
    root = Path(root).resolve()
    files, excluded, total = [], [], 0
    def error(_): raise ValueError('工程存在无法读取的目录，不能发布为完整快照')
    for folder, dirs, names in os.walk(root, followlinks=False, onerror=error):
        allowed = []
        for name in sorted(dirs):
            p = Path(folder) / name
            if name.lower() in SKIP_DIRS or intake.linked(p):
                if len(excluded) < 200: excluded.append(p.relative_to(root).as_posix() + '/')
            else: allowed.append(name)
        dirs[:] = allowed
        for name in sorted(names):
            p = Path(folder) / name
            if intake.linked(p) or name.lower() in PRIVATE_FILES or name.lower().startswith('.env') or p.suffix.lower() in ('.pem', '.key', '.pfx', '.p12', '.log', '.sqlite3', '.db') or intake.SENSITIVE.search(name):
                if len(excluded) < 200: excluded.append(p.relative_to(root).as_posix())
                continue
            path = assets.inside(p, root)
            relative = path.relative_to(root).as_posix()
            if any(ord(c) < 32 for c in relative): raise ValueError('工程文件名含控制字符，请先核对')
            info = path.stat()
            if not stat.S_ISREG(info.st_mode): raise ValueError('工程含特殊文件，请先核对')
            total += info.st_size
            files.append({'path': relative, 'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns})
            if len(files) > MAX_FILES or total > MAX_BYTES:
                raise ValueError('超出本版快照上限（十万文件 / 100 GiB），请按子工程留存')
    return files, excluded, total


def git_state(root):
    git = shutil.which('git')
    if not git or not (root / '.git').exists(): return {'repository': False}
    def read(*args):
        r = subprocess.run([git, '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=', '--no-optional-locks', '-C', str(root), *args], capture_output=True, timeout=15)
        return r.stdout.decode('utf-8', errors='replace').strip() if r.returncode == 0 else None
    status = read('status', '--porcelain')
    return {'repository': True, 'head': read('rev-parse', 'HEAD'), 'branch': read('symbolic-ref', '--short', 'HEAD'),
            'dirty': bool(status) if status is not None else None, 'note': '保存的是过滤后的工作文件，不复制 Git 对象库或宣称等同于 HEAD'}


def inventory_sources(pid):
    files, excluded, total = [], [], 0
    for source in intake.source_roots(pid):
        if not Path(source['path']).is_dir(): raise ValueError('来源目录缺失，不能保存完整多目录快照')
        current, skipped, size = inventory(source['path'])
        prefix = 'game/' if source['id'] == 'primary' else 'sources/' + source['id'] + '/'
        files += [{**f, 'source_id': source['id'], 'archive_path': prefix + f['path']} for f in current]
        excluded += [prefix + f for f in skipped][:max(0, 200 - len(excluded))]
        total += size
        if len(files) > MAX_FILES or total > MAX_BYTES: raise ValueError('多目录合计超出快照上限')
    return files, excluded, total


async def start(pid, data):
    p = store.project(pid)
    if not isinstance(data, dict) or data.get('saved_ack') is not True:
        raise ValueError('请先保存工程并暂停资产写入，再确认创建快照')
    label, note, kind = data.get('label', ''), data.get('note', ''), data.get('kind', 'checkpoint')
    if not isinstance(label, str) or not label.strip() or len(label) > 100 or not isinstance(note, str) or not note.strip() or len(note) > 4000 or kind not in ('checkpoint', 'milestone', 'pre_publish'):
        raise ValueError('请填写快照名称、说明并选择留存类型')
    if any(v['pid'] == pid for v in RUNNING.values()): raise ValueError('此项目正在留存快照，请等待')
    destination = data.get('destination', '')
    if not isinstance(destination, str): raise ValueError('备份目录无效')
    parent = Path(destination).expanduser().resolve() if destination.strip() else (store.DATA / 'snapshots' / pid).resolve()
    root = Path(p['root']).resolve()
    if any(parent.is_relative_to(Path(r['path']).resolve()) for r in intake.source_roots(pid)): raise ValueError('快照目录必须在全部来源目录之外，避免递归备份')
    if not root.is_dir(): raise ValueError('原工程目录不存在')
    parent.mkdir(parents=True, exist_ok=True)
    sid = store.uid()
    folder = parent / sid
    folder.mkdir(exist_ok=False)
    previous = store.one("SELECT id,archive_sha256 FROM project_snapshots WHERE project_id=? AND status='ready' ORDER BY created DESC,rowid DESC LIMIT 1", (pid,))
    rid = store.run_start(pid, 'project_snapshot', '创建完整工程快照：' + label)
    store.execute('INSERT INTO project_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (sid, pid, previous['id'] if previous else None, label.strip(), kind, note, 'pending', str(folder), '', '', '{}', store.now(), store.now()))
    control = RUNNING[sid] = {'pid': pid, 'stop': threading.Event(), 'task': None}
    control['task'] = asyncio.create_task(worker(sid, rid, previous, control))
    return job(sid)


async def worker(sid, rid, previous, control):
    try: await asyncio.to_thread(build, sid, previous, control)
    finally:
        result = job(sid)
        store.run_end(rid, 'completed' if result['status'] == 'ready' else result['status'], '快照已保存并附校验清单' if result['status'] == 'ready' else result['result'].get('error', '快照未完成'))
        RUNNING.pop(sid, None)


def build(sid, previous, control):
    j = job(sid); p = store.project(j['project_id']); root = Path(p['root']).resolve(); folder = Path(j['folder'])
    result, success = {}, False
    try:
        store.execute("UPDATE project_snapshots SET status='copying',updated=? WHERE id=?", (store.now(), sid))
        files, excluded, total = inventory_sources(p['id'])
        roots = intake.source_roots(p['id'])
        root_map = {r['id']: Path(r['path']) for r in roots}
        if shutil.disk_usage(folder).free < total + 256 * 1024 ** 2: raise ValueError('备份目标空间不足，请选择其他磁盘')
        metadata = backup.write(j['project_id'], folder / 'workbench.part.zip')
        total_bytes = total + metadata.stat().st_size
        records, copied, last = [], 0, 0
        manifest = {'format': 2, 'workbench_version': __version__, 'snapshot_id': sid, 'project': {'id': p['id'], 'name': p['name'], 'engine': p['engine']},
                    'sources': [{'id': r['id'], 'label': Path(r['path']).name, 'prefix': 'game/' if r['id'] == 'primary' else 'sources/' + r['id'] + '/'} for r in roots],
                    'label': j['label'], 'kind': j['kind'], 'note': j['note'], 'started_at': j['created'],
                    'parent_id': j['parent_id'], 'parent_sha256': previous['archive_sha256'] if previous else None,
                    'git': git_state(root), 'excluded_samples': excluded, 'saved_ack': True,
                    'consistency': '应用层静态文件检查；非 VSS/文件系统级原子快照，要求用户暂停写入'}
        with zipfile.ZipFile(folder / 'snapshot.part.zip', 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            for entry in [*files, {'path': None, 'bytes': metadata.stat().st_size, 'mtime_ns': metadata.stat().st_mtime_ns}]:
                if control['stop'].is_set(): raise InterruptedError('服务关闭或用户停止，快照不完整')
                source = assets.inside(root_map[entry['source_id']] / entry['path'], root_map[entry['source_id']]) if entry['path'] else metadata
                before = source.stat()
                if (before.st_size, before.st_mtime_ns) != (entry['bytes'], entry['mtime_ns']): raise ValueError('扫描后文件已变化，请暂停写入后重试')
                name = entry['archive_path'] if entry['path'] else 'workbench/project.zip'
                h = hashlib.sha256()
                with source.open('rb') as src, z.open(name, 'w', force_zip64=True) as dst:
                    while chunk := src.read(4 * 1024 * 1024):
                        if control['stop'].is_set(): raise InterruptedError('快照已停止，未标记完成')
                        h.update(chunk); dst.write(chunk); copied += len(chunk)
                        if time.monotonic() - last > .5:
                            store.execute('UPDATE project_snapshots SET result=?,updated=? WHERE id=?', (json.dumps({'copied_bytes': copied, 'total_bytes': total_bytes, 'copied_files': len(records), 'total_files': len(files) + 1}), store.now(), sid))
                            last = time.monotonic()
                after = source.stat()
                if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns): raise ValueError('复制时文件发生变化，请暂停写入后重试')
                records.append({'path': name, 'bytes': before.st_size, 'sha256': h.hexdigest()})
            current, _, _ = inventory_sources(p['id'])
            if current != files or roots != intake.source_roots(p['id']): raise ValueError('快照期间工程文件清单或来源目录发生变化，未标记完成')
            manifest.update(files=records, finished_at=store.now(), bytes=copied)
            z.writestr('snapshot.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        archive = folder / 'snapshot.zip'
        (folder / 'snapshot.part.zip').replace(archive)
        sha = digest(archive)
        (folder / 'snapshot.zip.sha256').write_text(sha + '  snapshot.zip\n', encoding='utf-8')
        (folder / 'snapshot.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        result = {'files': len(records), 'bytes': copied, 'excluded_samples': excluded, 'finished_at': manifest['finished_at']}
        store.execute("UPDATE project_snapshots SET status='ready',archive=?,archive_sha256=?,result=?,updated=? WHERE id=?", (str(archive), sha, json.dumps(result, ensure_ascii=False), store.now(), sid))
        success = True
    except Exception as exc:
        status = 'interrupted' if isinstance(exc, InterruptedError) else 'failed'
        store.execute('UPDATE project_snapshots SET status=?,result=?,updated=? WHERE id=?', (status, json.dumps({'error': str(exc)[:500]}, ensure_ascii=False), store.now(), sid))
    finally:
        if success: (folder / 'workbench.part.zip').unlink(missing_ok=True)


def verify(sid):
    j = job(sid)
    if j['status'] != 'ready' or not j['archive']: raise ValueError('快照未完成，不能校验或恢复')
    path = Path(j['archive'])
    if not path.is_file() or digest(path) != j['archive_sha256']: raise ValueError('快照文件缺失或归档 SHA-256 不匹配，禁止使用')
    with zipfile.ZipFile(path) as z:
        if z.getinfo('snapshot.json').file_size > 64 * 1024 ** 2: raise ValueError('快照清单过大')
        manifest = json.loads(z.read('snapshot.json'))
        records = manifest.get('files', [])
        if manifest.get('snapshot_id') != sid or len(records) > MAX_FILES + 1: raise ValueError('快照清单身份无效')
        names = [r['path'] for r in records]
        if len(names) != len(set(names)) or len(z.namelist()) != len(names) + 1 or set(z.namelist()) != {*names, 'snapshot.json'}: raise ValueError('快照条目不匹配')
        for r in records:
            name = PurePosixPath(r['path'])
            if name.is_absolute() or '..' in name.parts or '\\' in r['path'] or ':' in r['path'] or name.parts[0] not in ('game', 'workbench', 'sources'): raise ValueError('快照包含不安全路径')
            h, total = hashlib.sha256(), 0
            with z.open(r['path']) as f:
                while chunk := f.read(4 * 1024 * 1024): h.update(chunk); total += len(chunk)
            if h.hexdigest() != r['sha256'] or total != r['bytes']: raise ValueError('快照文件校验失败：' + r['path'])
    return manifest


def restore(sid, data):
    if not isinstance(data, dict) or data.get('confirmed') is not True or not isinstance(data.get('parent'), str): raise ValueError('请选择恢复父目录并确认创建独立副本')
    parent = Path(data['parent']).expanduser().resolve()
    roots = intake.source_roots(job(sid)['project_id'])
    if not parent.is_dir() or any(parent.is_relative_to(Path(r['path']).resolve()) for r in roots): raise ValueError('请选择全部来源目录之外的已有恢复父目录')
    manifest = verify(sid)
    target = parent / ('restored-' + sid[:8] + '-' + store.uid()[:8])
    target.mkdir(exist_ok=False)
    with zipfile.ZipFile(job(sid)['archive']) as z:
        for r in manifest['files']:
            dest = assets.inside(target / r['path'], target)
            dest.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            with z.open(r['path']) as src, dest.open('xb') as out:
                while chunk := src.read(4 * 1024 * 1024): h.update(chunk); out.write(chunk)
            if h.hexdigest() != r['sha256']: raise ValueError('恢复副本校验失败，保留副本供核对')
        (target / 'snapshot.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'folder': str(target), 'game': str(target / 'game'), 'sources': str(target / 'sources'), 'workbench_backup': str(target / 'workbench/project.zip'), 'verified': True}


async def shutdown():
    pending = [v['task'] for v in RUNNING.values()]
    for control in RUNNING.values(): control['stop'].set()
    if pending: await asyncio.gather(*pending, return_exceptions=True)
