"""Evidence-based storage audit and explicitly confirmed, reversible cache archiving."""
import hashlib
import json
import os
import shutil
import stat
import threading
import time
import zipfile
from collections import Counter
from pathlib import Path

from . import assets, intake, store

LOCKS = {}
MAX_FILES = 20000
MAX_BYTES = 10 * 1024 ** 3
CACHES = {'unreal': ('DerivedDataCache', 'Intermediate'), 'unity': ('Library', 'Temp')}


def digest(path):
    with Path(path).open('rb') as f: return stream_digest(f)


def stream_digest(f):
    h = hashlib.sha256()
    while chunk := f.read(1024 * 1024): h.update(chunk)
    return h.hexdigest()


def public(value):
    return {k: v for k, v in value.items() if not k.startswith('_')}


def state(pid):
    store.project(pid)
    audit = store.setting('project_audit:' + pid)
    history = store.rows("SELECT id,status,detail,created,runtime FROM runs WHERE project_id=? AND kind='project_cleanup' ORDER BY created DESC,rowid DESC LIMIT 20", (pid,))
    return {'audit': public(audit) if audit else None, 'history': history}


def candidate_files(pid, audit_id, candidate_id, offset=0):
    store.project(pid)
    plan = store.setting('project_audit:' + pid)
    if not plan or plan['id'] != audit_id or candidate_id not in plan['_cache_files']: raise ValueError('审计或候选已变化，请刷新')
    files = plan['_cache_files'][candidate_id]
    offset = max(0, offset)
    return {'candidate_id': candidate_id, 'total': len(files), 'offset': offset, 'items': files[offset:offset + 30]}


def cache_names(pid):
    p = store.project(pid); root = Path(p['root'])
    recognized = len(list(root.glob('*.uproject'))) == 1 if p['engine'] == 'unreal' else (root / 'ProjectSettings/ProjectVersion.txt').is_file()
    return CACHES[p['engine']] if recognized else ()


def audit(pid):
    roots = intake.source_roots(pid)
    categories, large, groups, hashed = Counter(), [], {}, 0
    entries, candidates, warnings = [], [], []
    started = time.monotonic()
    cache_entries = {name: [] for name in cache_names(pid)}
    blocked, truncated = set(), False
    for source in roots:
        root = Path(source['path'])
        if not root.is_dir(): raise ValueError('来源目录缺失，请先恢复目录或核对项目接入')
        def error(_):
            warnings.append('部分目录无法读取，不能据此执行瘦身')
        for folder, dirs, names in os.walk(root, followlinks=False, onerror=error):
            rel_folder = Path(folder).relative_to(root)
            top = rel_folder.parts[0] if rel_folder.parts else ''
            cache = top if source['id'] == 'primary' and top in cache_entries else None
            allowed = []
            for name in sorted(dirs):
                path = Path(folder) / name
                if intake.linked(path):
                    if cache: blocked.add(cache)
                elif name.lower() not in {'.git', '.svn', '.hg', '.workbench', '.dev', '.venv', 'node_modules', '.codex', '.claude'}:
                    allowed.append(name)
                elif cache: blocked.add(cache)
            dirs[:] = allowed
            for name in sorted(names):
                if len(entries) >= MAX_FILES or time.monotonic() - started > 20:
                    truncated = True; break
                path = Path(folder) / name
                try:
                    if intake.linked(path) or name.startswith('.') or intake.SENSITIVE.search(name) or path.suffix.lower() in ('.key', '.pem', '.pfx', '.p12', '.db', '.sqlite3'):
                        if cache: blocked.add(cache)
                        continue
                    path = assets.inside(path, root); info = path.stat()
                    if not stat.S_ISREG(info.st_mode):
                        if cache: blocked.add(cache)
                        continue
                    relative = path.relative_to(root).as_posix()
                    entry = {'source_id': source['id'], 'relative_path': relative, 'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns}
                    entries.append(entry)
                    categories['cache' if cache else intake.category(Path(relative))] += info.st_size
                    display = relative if source['id'] == 'primary' else '@' + source['id'] + '/' + relative
                    large.append({'path': display, 'bytes': info.st_size, 'category': 'cache' if cache else intake.category(Path(relative))})
                    large = sorted(large, key=lambda v: v['bytes'], reverse=True)[:15]
                    if cache: cache_entries[cache].append(entry)
                    elif info.st_size and info.st_size <= 32 * 1024 ** 2 and hashed + info.st_size <= 128 * 1024 ** 2:
                        sha = digest(path); hashed += info.st_size
                        groups.setdefault((info.st_size, sha), []).append(display)
                except (OSError, ValueError):
                    warnings.append('文件读取失败或变化，不能据此执行瘦身')
                    if cache: blocked.add(cache)
            if truncated: break
        if truncated: break
    for name, files in cache_entries.items():
        if files:
            eligible = not truncated and not warnings and name not in blocked and sum(f['bytes'] for f in files) <= MAX_BYTES
            candidates.append({'id': name, 'path': name, 'bytes': sum(f['bytes'] for f in files), 'file_count': len(files), 'eligible': eligible,
                               'reason': '已识别主工程的可重建缓存；关闭引擎后可归档，重开可能重新生成' if eligible else '扫描不完整、含受保护条目或超出归档上限；仅供人工核对'})
    if truncated: warnings.append('达到两万文件或约20秒审计预算，体积统计不完整；瘦身已禁用')
    duplicates = [{'bytes_each': size, 'sha256': sha, 'paths': paths[:20], 'count': len(paths), 'action': '仅建议：相同内容可能有独立GUID或引用，不自动删除'} for (size, sha), paths in groups.items() if len(paths) > 1][:20]
    value = {'id': store.uid(), 'created': store.now(), 'roots': roots, 'file_count': len(entries), 'bytes': sum(f['bytes'] for f in entries),
             'categories': dict(categories), 'largest_files': large, 'duplicates': duplicates, 'candidates': candidates,
             'truncated': truncated, 'warnings': list(dict.fromkeys(warnings)), '_cache_files': cache_entries,
             'note': '逻辑文件体积，不等于磁盘实际占用。重复检查仅覆盖最多128 MiB、单文件32 MiB以内的样本；原生资产引用未解析。归档仍占备份空间。'}
    from .agent_tools import document
    report_data = {**public(value), 'roots': [{'id': r['id'], 'label': Path(r['path']).name} for r in roots]}
    report = document(pid, '项目整理与空间审计 · ' + store.now()[:10], '# 项目整理与空间审计（规则扫描，非模型结论）\n\n' + json.dumps(report_data, ensure_ascii=False, indent=2))
    value['document_id'] = report['id']
    store.set_setting('project_audit:' + pid, value)
    return public(value)


def prepare_analysis(pid):
    current = intake.current(pid)
    if not current or current['report'].get('restored_snapshot'): raise ValueError('请先接入真实项目目录并完成扫描')
    intake.refresh(pid)
    result = audit(pid)
    return {'audit': result, 'message': '分析当前游戏项目并制定整理、瘦身方案。先阅读最新项目接入摘要、设计资料和空间审计，按需核对代码。请区分设计目标、已有实现、原文进度与待验证事项，说明各来源目录职责；给出分类建议、瘦身候选及风险和分阶段计划，并注明出处与阅读覆盖。重复内容不等于无用，原生资产引用尚未解析。本次只分析，请将文件改动、缓存归档和收费创作留待用户审阅确认。'}


def checked_file(roots, entry):
    root = Path(next(r['path'] for r in roots if r['id'] == entry['source_id']))
    raw = root / entry['relative_path']
    if Path(entry['relative_path']).is_absolute() or '..' in Path(entry['relative_path']).parts: raise ValueError('归档路径无效')
    for part in [raw, *raw.parents]:
        if intake.linked(part): raise ValueError('归档路径包含链接，已停止')
        if part == root: break
    return assets.inside(raw, root)


def receipt_path(pid, rid):
    if not store.one("SELECT id FROM runs WHERE id=? AND project_id=? AND kind='project_cleanup'", (rid, pid)):
        raise ValueError('归档记录不属于当前项目')
    return store.DATA / 'maintenance' / pid / rid


def save_receipt(folder, value):
    temp = folder / 'receipt.part.json'
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(folder / 'receipt.json')


def archive(pid, data):
    with LOCKS.setdefault(pid, threading.Lock()):
        plan = store.setting('project_audit:' + pid)
        if not isinstance(data, dict) or data.get('confirmed') is not True or data.get('editor_closed_ack') is not True:
            raise ValueError('请关闭游戏编辑器、暂停写入，并确认具体缓存清单')
        if not plan or plan['id'] != data.get('audit_id') or plan['roots'] != intake.source_roots(pid): raise ValueError('审计已变化，请重新审计并确认')
        selected = data.get('candidate_ids')
        allowed = {c['id'] for c in plan['candidates'] if c['eligible'] and c['id'] in cache_names(pid)}
        if not isinstance(selected, list) or not selected or any(not isinstance(k, str) or k not in allowed for k in selected) or len(set(selected)) != len(selected):
            raise ValueError('只能归档本次完整审计中可执行的缓存目录')
        files = [f for k in selected for f in plan['_cache_files'][k]]
        if sum(f['bytes'] for f in files) > MAX_BYTES: raise ValueError('本次所选缓存合计超过10 GiB归档上限，请分批处理')
        # Freshly enumerate every selected directory; new files invalidate the old plan.
        started = time.monotonic()
        for name in selected:
            directory = Path(plan['roots'][0]['path']) / name
            fresh = []
            def unreadable(_): raise ValueError('缓存无法读取')
            for base, dirs, names in os.walk(directory, followlinks=False, onerror=unreadable):
                if time.monotonic() - started > 20: raise ValueError('缓存清单核对超时，请重新审计或分批处理')
                if any(intake.linked(Path(base) / d) for d in dirs): raise ValueError('缓存包含链接，请重新核对')
                for leaf in names:
                    if len(fresh) >= MAX_FILES: raise ValueError('缓存清单已超过审计范围，请重新核对')
                    path = Path(base) / leaf
                    if intake.linked(path) or not path.is_file(): raise ValueError('缓存包含链接或特殊文件')
                    info = path.stat()
                    fresh.append({'source_id': 'primary', 'relative_path': path.relative_to(plan['roots'][0]['path']).as_posix(), 'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns})
            if sorted(fresh, key=lambda f: f['relative_path']) != sorted(plan['_cache_files'][name], key=lambda f: f['relative_path']): raise ValueError('缓存清单已变化，请重新审计')
        rid = store.run_start(pid, 'project_cleanup', '归档已确认的可重建缓存')
        folder = receipt_path(pid, rid); folder.mkdir(parents=True, exist_ok=False)
        value = {'id': rid, 'roots': plan['roots'], 'candidate_ids': selected, 'files': [], 'status': 'archiving', 'removed_bytes': 0, 'created': store.now()}
        save_receipt(folder, value)
        try:
            with zipfile.ZipFile(folder / 'cache.part.zip', 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                for entry in files:
                    path = checked_file(value['roots'], entry)
                    before = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (entry['bytes'], entry['mtime_ns']): raise ValueError('缓存已变化，归档中止')
                    sha = digest(path)
                    z.write(path, entry['relative_path'])
                    if digest(path) != sha or (path.stat().st_size, path.stat().st_mtime_ns) != (entry['bytes'], entry['mtime_ns']): raise ValueError('归档时缓存变化，未移除源文件')
                    value['files'].append({**entry, 'sha256': sha})
            (folder / 'cache.part.zip').replace(folder / 'cache.zip')
            value['archive_sha256'] = digest(folder / 'cache.zip')
            with zipfile.ZipFile(folder / 'cache.zip') as z:
                for entry in value['files']:
                    with z.open(entry['relative_path']) as src:
                        if stream_digest(src) != entry['sha256']: raise ValueError('备份校验失败，未移除源文件')
            value['status'] = 'archived'; save_receipt(folder, value)
            for entry in value['files']:
                path = checked_file(value['roots'], entry)
                if digest(path) != entry['sha256']: raise ValueError('移除前缓存变化，已停止；备份仍可恢复')
                path.unlink()
                value['removed_bytes'] += entry['bytes']
            value['status'] = 'completed'
        except Exception as exc:
            value.update(status='partial' if value['removed_bytes'] else 'failed', error=str(exc)[:300])
        save_receipt(folder, value)
        store.execute('UPDATE runs SET runtime=? WHERE id=?', (json.dumps({'folder': str(folder), 'removed_bytes': value['removed_bytes'], 'error': value.get('error', '')}), rid))
        store.run_end(rid, value['status'], '缓存归档结束；备份保留，原目录可能在重开编辑器后重新生成')
        return public(value) | {'folder': str(folder)}


def restore(pid, rid, data):
    with LOCKS.setdefault(pid, threading.Lock()):
        if not isinstance(data, dict) or data.get('confirmed') is not True or data.get('editor_closed_ack') is not True: raise ValueError('请关闭编辑器并确认恢复；已有不同内容的文件不会覆盖')
        folder = receipt_path(pid, rid)
        if not (folder / 'receipt.json').is_file(): raise ValueError('归档恢复清单缺失，请核对备份目录')
        value = json.loads((folder / 'receipt.json').read_text(encoding='utf-8'))
        archive = folder / 'cache.zip'
        if value['roots'] != intake.source_roots(pid) or not archive.is_file() or digest(archive) != value.get('archive_sha256'): raise ValueError('目录绑定变化或备份校验失败，请人工核对')
        conflicts, restored = [], 0
        with zipfile.ZipFile(archive) as z:
            for entry in value['files']:
                with z.open(entry['relative_path']) as src:
                    if stream_digest(src) != entry['sha256']: raise ValueError('备份文件校验失败')
            for entry in value['files']:
                path = checked_file(value['roots'], entry)
                if path.exists():
                    if not path.is_file() or digest(path) != entry['sha256']: conflicts.append(entry['relative_path'])
                    continue
                temp = path.with_name('.gameworkbench-restore-' + store.uid() + '.part')
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(entry['relative_path']) as src, temp.open('xb') as out: shutil.copyfileobj(src, out, 1024 * 1024)
                    if digest(temp) != entry['sha256']: raise ValueError('恢复副本校验失败，原文件未覆盖')
                    if os.name == 'nt': temp.rename(path)
                    else: os.link(temp, path)
                    restored += 1
                except OSError:
                    conflicts.append(entry['relative_path'])
                finally:
                    if temp.exists(): temp.unlink()
        result = {'restored_files': restored, 'conflicts': conflicts, 'status': 'partial' if conflicts else 'restored'}
        value['restore_result'] = result; save_receipt(folder, value)
        store.execute('UPDATE runs SET runtime=?,updated=? WHERE id=?', (json.dumps({'folder': str(folder), **result}), store.now(), rid))
        return result
