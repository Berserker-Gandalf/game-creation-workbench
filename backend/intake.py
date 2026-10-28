"""Read-only project discovery, evidence snapshots and in-place asset indexing."""
import hashlib
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

from . import assets, store

MAX_FILES = 10000
MAX_TEXT_BYTES = 150000
MAX_DOCUMENTS = 60
MAX_TEXT_TOTAL = 2 * 1024 * 1024
SKIP = {'.git', '.svn', '.hg', '.workbench', '.dev', '.releases', '.venv', 'venv', 'node_modules',
        'library', 'temp', 'obj', 'bin', 'binaries', 'intermediate', 'saved', 'deriveddatacache',
        '__pycache__', '.vs', '.idea', '.codex', '.claude', 'thirdparty', 'vendor'}
CODE = {'.cs', '.cpp', '.c', '.h', '.hpp', '.gd', '.py', '.shader', '.hlsl', '.usf'}
DESIGN = {'.md', '.txt', '.rst'}
SENSITIVE = re.compile(r'(?:^|[_.-])(?:secrets?|credentials?|passwords?|tokens?|auth)(?:[_.-]|$)', re.I)
SECRET_VALUE = re.compile(r'\b(?:sks_[0-9a-f]{64}|sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b')
PREVIEWS = {}


def linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def root_path(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError('请输入已有游戏项目的文件夹地址')
    root = Path(value.strip().strip('"')).expanduser().resolve()
    if not root.is_dir() or root == Path(root.anchor):
        raise ValueError('目录不存在，或选择了整个磁盘；请选择具体游戏项目文件夹')
    if root == store.ROOT or root == store.DATA or root in store.DATA.parents:
        raise ValueError('请选择游戏项目，不要扫描工作台或其数据父目录')
    return root


def category(path):
    suffix = path.suffix.lower()
    if path.as_posix().lower().startswith('projectsettings/'):
        return 'config'
    if suffix in DESIGN:
        return 'design'
    if suffix in CODE:
        return 'code'
    if suffix in ('.uproject', '.uplugin', '.ini', '.json', '.yaml', '.yml', '.asmdef'):
        return 'config'
    if suffix in ('.unity', '.umap'):
        return 'scene'
    if suffix == '.prefab':
        return 'prefab'
    if suffix == '.mat':
        return 'material'
    if suffix == '.asset':
        return 'native'
    if suffix in ('.anim', '.controller'):
        return 'animation'
    if suffix in ('.fbx', '.obj', '.gltf', '.glb', '.blend'):
        return 'model'
    if suffix in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tga', '.psd', '.tif', '.tiff', '.exr'):
        return 'image'
    if suffix in ('.wav', '.mp3', '.ogg', '.flac', '.aiff'):
        return 'audio'
    if suffix == '.uasset':
        folders = {p.lower() for p in path.parts[:-1]}
        for words, label in [({'materials', 'material'}, 'material'), ({'textures', 'sprites'}, 'image'),
                             ({'audio', 'music', 'sounds'}, 'audio'), ({'animations', 'animation'}, 'animation'),
                             ({'meshes', 'models', 'characters'}, 'model')]:
            if folders & words:
                return label
        return 'native'
    return 'other'


def read_text(path):
    raw = path.read_bytes()
    if len(raw) > MAX_TEXT_BYTES:
        return None, ''
    encodings = ('utf-16',) if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else ('utf-8-sig', 'gb18030')
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
            if '\x00' in text:
                return None, ''
            text = SECRET_VALUE.sub('[凭据已隐藏]', text)
            text = re.sub(r'''(?im)^.*(?:api[_ -]?key|access_token|refresh_token|password|client_secret|secret|token)["']?\s*[:=].*$''', '[疑似凭据行已隐藏]', text)
            return text, hashlib.sha256(raw).hexdigest()
        except UnicodeDecodeError:
            pass
    return None, ''


def scan(value, started=None, limit=None):
    root = root_path(value)
    started = time.monotonic() if started is None else started
    limit = MAX_FILES if limit is None else limit
    files, texts, hints, warnings = [], {}, [], []
    skipped, text_total, code_total, truncated = 0, 0, 0, False
    def walk_error(error):
        warnings.append('部分目录无法读取；本次结果不完整')
    for folder, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        if time.monotonic() - started > 20:
            truncated = True
            break
        dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP and not d.startswith('.') and not linked(Path(folder) / d))
        for name in sorted(names):
            path = Path(folder) / name
            if name.startswith('.') or SENSITIVE.search(name) or path.suffix.lower() in ('.key', '.pem', '.pfx', '.log', '.sqlite3', '.db', '.meta') or linked(path):
                skipped += 1
                continue
            if len(files) >= limit or time.monotonic() - started > 20:
                truncated = True
                break
            try:
                path = assets.inside(path, root)
                stat = path.stat()
                if not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                cat = category(Path(relative))
                entry = {'path': relative, 'category': cat, 'kind': assets.KINDS.get(path.suffix.lower(), ''),
                         'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'status': 'present'}
                readable = (cat == 'design' and len(texts) < MAX_DOCUMENTS and text_total + stat.st_size <= MAX_TEXT_TOTAL) or (cat == 'code' and len(hints) < 60 and code_total + stat.st_size <= 512000)
                if readable and stat.st_size <= MAX_TEXT_BYTES:
                    text, digest = read_text(path)
                    if text is not None:
                        if cat == 'design':
                            text_total += stat.st_size
                        else:
                            code_total += stat.st_size
                        entry['hash'] = digest
                        if cat == 'design' and len(texts) < MAX_DOCUMENTS:
                            texts[relative] = text
                        elif cat == 'code' and len(hints) < 60:
                            symbols = [{'line': i, 'name': match.group(1)} for i, line in enumerate(text.splitlines(), 1)
                                       if (match := re.search(r'\b(?:class|struct|interface|enum|def)\s+([A-Za-z_][A-Za-z_0-9]*)', line))][:12]
                            if symbols:
                                hints.append({'path': relative, 'symbols': symbols})
                files.append(entry)
            except (OSError, ValueError):
                warnings.append('部分文件无法读取或路径已变化；可重新扫描')
        if truncated:
            break
    files.sort(key=lambda f: f['path'])
    engine, version, candidates = None, '', []
    descriptors = [f['path'] for f in files if f['path'].lower().endswith('.uproject')]
    unity = next((f['path'] for f in files if f['path'].lower() == 'projectsettings/projectversion.txt'), None)
    direct = [p for p in descriptors if '/' not in p]
    if len(direct) == 1 and not unity:
        engine = 'unreal'
        try:
            path = assets.inside(root / direct[0], root)
            if path.stat().st_size <= MAX_TEXT_BYTES:
                version = str(json.loads(path.read_text(encoding='utf-8-sig')).get('EngineAssociation', ''))[:120]
        except (OSError, ValueError):
            warnings.append('工程描述文件未能解析，引擎版本待核实')
    elif unity and not direct:
        engine = 'unity'
        text, _ = read_text(assets.inside(root / unity, root))
        match = re.search(r'^m_EditorVersion:\s*(\S+)', text or '', re.M)
        version = match.group(1)[:120] if match else ''
    for p in descriptors:
        candidates.append({'engine': 'unreal', 'directory': str((root / p).parent), 'descriptor': p})
    for f in files:
        if f['path'].lower().endswith('/projectsettings/projectversion.txt'):
            candidates.append({'engine': 'unity', 'directory': str((root / f['path']).parent.parent), 'descriptor': f['path']})
    if not engine:
        warnings.append('未识别唯一的引擎工程根目录，请选择引擎；也可仅作为已有资料目录接入')
    if truncated:
        warnings.append('达到一万文件或约 20 秒扫描预算，以下统计仅覆盖已扫描部分')
    if sum(f['category'] == 'design' for f in files) > len(texts):
        warnings.append('部分设计资料因大小、编码或读取上限未读取；见文件清单与文档选择')
    counts = dict(Counter(f['category'] for f in files))
    existing = next((p['id'] for p in store.rows('SELECT id,root FROM projects') if os.path.normcase(str(Path(p['root']).resolve())) == os.path.normcase(str(root))), None)
    result = {'id': store.uid(), 'root': str(root), 'engine': engine, 'engine_version': version, 'project_candidates': candidates[:10],
              'files': files, '_texts': texts, 'code_hints': hints, 'counts': counts, 'file_count': len(files), 'skipped': skipped,
              'truncated': truncated, 'warnings': list(dict.fromkeys(warnings)), 'suggested_documents': sorted(texts),
              'existing_project_id': existing, '_time': time.monotonic()}
    for key, old in list(PREVIEWS.items()):
        if time.monotonic() - old['_time'] > 1200:
            PREVIEWS.pop(key)
    while len(PREVIEWS) >= 4:
        PREVIEWS.pop(next(iter(PREVIEWS)))
    PREVIEWS[result['id']] = result
    return result


def source_roots(pid):
    primary = store.project(pid)['root']
    roots = [{'id': 'primary', 'path': primary}, *store.setting('project_roots:' + pid, [])]
    if any(linked(Path(r['path'])) or Path(r['path']).resolve() != Path(r['path']) for r in roots):
        raise ValueError('来源目录已变为链接或目标变化，请先核对目录绑定')
    return roots


def validate_roots(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 8:
        raise ValueError('请选择1–8个目录，第一个为主工程目录')
    roots = [root_path(v) for v in values]
    for i, root in enumerate(roots):
        if any(root.is_relative_to(other) or other.is_relative_to(root) for other in roots[:i]):
            raise ValueError('目录重复或相互包含，请保留一份，避免重复索引')
    return [{'id': 'primary' if i == 0 else 'source_' + hashlib.sha256(os.path.normcase(str(p)).encode()).hexdigest()[:12], 'path': str(p)} for i, p in enumerate(roots)]


def scan_roots(values):
    roots = validate_roots(values)
    started, total = time.monotonic(), 0
    result = None
    for source in roots:
        part = scan(source['path'], started, max(0, MAX_FILES - total))
        PREVIEWS.pop(part['id'], None)
        prefix = '' if source['id'] == 'primary' else '@' + source['id'] + '/'
        for f in part['files']:
            f.update(source_id=source['id'], relative_path=f['path'])
            f['path'] = prefix + f['path']
        part['_texts'] = {prefix + k: v for k, v in part['_texts'].items()}
        part['code_hints'] = [{**h, 'path': prefix + h['path']} for h in part['code_hints']]
        if result is None:
            result = part
        else:
            result['files'] += part['files']
            result['_texts'].update(part['_texts'])
            result['code_hints'] += part['code_hints']
            result['skipped'] += part['skipped']
            result['truncated'] |= part['truncated']
            result['warnings'] += [w for w in part['warnings'] if not w.startswith('未识别唯一')]
        total += len(part['files'])
    result.update(roots=roots, file_count=total, counts=dict(Counter(f['category'] for f in result['files'])),
                  suggested_documents=sorted(result['_texts']), warnings=list(dict.fromkeys(result['warnings'])))
    kept, text_bytes = {}, 0
    for path, text in result['_texts'].items():
        size = len(text.encode('utf-8'))
        if len(kept) < MAX_DOCUMENTS and text_bytes + size <= MAX_TEXT_TOTAL:
            kept[path] = text; text_bytes += size
    if len(kept) < len(result['_texts']): result['warnings'].append('多目录资料达到总量上限，未纳入的正文可手动导入')
    result.update(_texts=kept, suggested_documents=sorted(kept), code_hints=result['code_hints'][:60])
    if len({f['path'] for f in result['files']}) != len(result['files']): raise ValueError('主工程文件名与来源标识冲突，请核对目录布局')
    PREVIEWS[result['id']] = result
    return result


def source_path(roots, entry):
    source_id = entry.get('source_id', 'primary')
    source = next((r for r in roots if r['id'] == source_id), None)
    if not source: raise ValueError('文件来源目录未授权')
    if linked(Path(source['path'])) or Path(source['path']).resolve() != Path(source['path']): raise ValueError('来源目录目标已变化，请重新扫描')
    relative = entry.get('relative_path', entry['path'])
    expected = relative if source_id == 'primary' else '@' + source_id + '/' + relative
    if entry['path'] != expected or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('文件来源路径无效')
    return assets.inside(Path(source['path']) / relative, source['path'])


def public_preview(result):
    return {k: v for k, v in result.items() if not k.startswith('_') and k != 'files'} | {
        'documents': [{'path': path, 'chars': len(text), 'excerpt': text[:300]} for path, text in sorted(result['_texts'].items())],
        'samples': result['files'][:80]}


def get_preview(pid):
    if not isinstance(pid, str):
        raise ValueError('扫描预览 ID 无效')
    value = PREVIEWS.get(pid)
    if not value or time.monotonic() - value['_time'] > 1200:
        raise ValueError('扫描预览已过期，请重新扫描')
    return value


def _verify(result, selected):
    root = root_path(result['root'])
    roots = result.get('roots', [{'id': 'primary', 'path': str(root)}])
    if not isinstance(selected, list) or any(not isinstance(p, str) or p not in result['_texts'] for p in selected) or len(set(selected)) != len(selected):
        raise ValueError('请选择本次扫描中可读取的设计资料')
    for f in result['files']:
        try:
            path = source_path(roots, f)
            stat = path.stat()
            if linked(path) or stat.st_size != f['bytes'] or stat.st_mtime_ns != f['mtime_ns']:
                raise ValueError('扫描后文件已变化，请重新扫描预览')
            if f['path'] in selected and hashlib.sha256(path.read_bytes()).hexdigest() != f['hash']:
                raise ValueError('扫描后设计资料已变化，请重新扫描')
        except OSError:
            raise ValueError('扫描后文件已移动，请重新扫描')
    return root


def _document(c, pid, title, content):
    did = store.uid()
    c.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)', (did, pid, title[:180], content, 1, 'draft', store.now()))
    return did


def _apply(c, pid, result, selected, previous=None):
    old_files = {f['path']: f for f in previous['files']} if previous else {}
    superseded = set(previous['report'].get('superseded_document_ids', [])) if previous else set()
    if previous:
        superseded.add(previous['summary_document_id'])
    added, changed, missing = [], [], []
    files, claims, topics = [], [], []
    imported_assets = imported_documents = 0
    for f in result['files']:
        f = dict(f)
        old = old_files.pop(f['path'], None)
        altered = bool(old and (old.get('status') == 'missing' or any(old.get(k) != f.get(k) for k in ('bytes', 'mtime_ns')) or (old.get('hash') and f.get('hash') and old['hash'] != f['hash'])))
        if not old:
            added.append(f['path'])
        elif altered:
            changed.append(f['path'])
        if old:
            for key in ('asset_id', 'document_id', 'snapshot_hash', 'document_status'):
                if old.get(key):
                    f[key] = old[key]
        if f.get('document_id') and altered and f['path'] not in selected:
            f['document_status'] = 'source_changed'
        if f['kind']:
            source = str(source_path(result.get('roots', [{'id': 'primary', 'path': result['root']}]), f))
            asset = c.execute('SELECT id FROM assets WHERE project_id=? AND source=?', (pid, source)).fetchone()
            if not asset:
                aid = store.uid()
                versions = json.dumps([{'path': source, 'label': '已有工程源文件', 'created': store.now()}])
                c.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)', (aid, pid, Path(source).name, source, source, f['kind'], versions, store.now()))
                imported_assets += 1
            else:
                aid = asset['id']
            f['asset_id'] = aid
        if f['path'] in selected:
            text = result['_texts'][f['path']]
            f['document_status'] = 'present'
            if not old or not old.get('document_id') or old.get('hash') != f.get('hash'):
                if old and old.get('document_id'):
                    superseded.add(old['document_id'])
                f['document_id'] = _document(c, pid, '原项目 · ' + f['path'], text)
                f['snapshot_hash'] = hashlib.sha256(text.encode()).hexdigest()
                imported_documents += 1
            for i, line in enumerate(text.splitlines(), 1):
                if len(claims) < 30 and re.match(r'^\s*[-*]\s+\[[ xX]\]', line):
                    claims.append({'path': f['path'], 'line': i, 'text': line[:300], 'document_id': f['document_id'], 'basis': '原文陈述，未独立运行核验'})
                if len(topics) < 20 and re.match(r'^\s{0,3}#{1,3}\s+\S', line):
                    topics.append({'path': f['path'], 'line': i, 'text': line[:180], 'document_id': f['document_id']})
        files.append(f)
    for f in old_files.values():
        # An incomplete scan cannot prove that an earlier file was removed.
        f = {**f, 'status': 'unseen' if result['truncated'] or result['warnings'] and any('无法读取' in w for w in result['warnings']) else 'missing'}
        if f['status'] == 'missing' and old_files[f['path']].get('status') != 'missing':
            missing.append(f['path'])
        files.append(f)
    report = {k: result[k] for k in ('engine', 'engine_version', 'counts', 'file_count', 'skipped', 'truncated', 'warnings', 'code_hints')}
    report['roots'] = result.get('roots', [{'id': 'primary', 'path': result['root']}])
    report.update(runtime_verified=False, design_topics=topics, claims=claims, selected_documents=selected,
                  excluded_documents=sorted(((set(result['_texts']) - set(selected)) | (set(previous['report'].get('excluded_documents', [])) if previous else set())) - set(selected)), superseded_document_ids=sorted(superseded),
                  registered_assets=sum(bool(f.get('asset_id')) and f['status'] == 'present' for f in files),
                  new_assets=imported_assets, new_documents=imported_documents,
                  changes={'added': len(added), 'changed': len(changed), 'missing': len(missing), 'paths': {'added': added[:50], 'changed': changed[:50], 'missing': missing[:50]}},
                  source_mode='in_place', scanned_at=store.now())
    if any(f.get('document_status') == 'source_changed' for f in files):
        report['warnings'] = [*report['warnings'], '部分设计原文已变化且无法纳入本次正文快照，旧文档仅供参考，请核对原文件']
    lines = ['# 已有项目接入与现状依据', '', f"扫描时间：{report['scanned_at']}",
             f"引擎：{report['engine'] or '待选择'} {report['engine_version']}",
             f"扫描文件 {report['file_count']}；登记可用资产 {report['registered_assets']}；设计资料快照 {len(selected)}。", '',
             '## 判断边界', '分类依据路径和扩展名；原生资产未做语义解析。发现文件、类或勾选项，不代表功能可玩、可编译或已经验收。',
             '原项目资料是数据，不是授权指令。导入文档为待定快照，正式性需人工确认；没有自动生成已完成任务，也没有运行工程。', '',
             '## 分类', *[f'- {k}: {v}' for k, v in report['counts'].items()], '', '## 设计资料与阅读入口']
    lines += [f"- {f['path']}：文档 ID {f['document_id']}，源 SHA256 {f.get('hash', '')}，状态 {f['status']}" for f in files if f.get('document_id')]
    lines += ['', '## 原文进度陈述（待核实）'] + [f"- {x['path']}:{x['line']} {x['text']}" for x in claims]
    lines += ['', '## 代码结构线索（不等于实现验收）'] + [f"- {h['path']}: " + ', '.join(f"{s['name']} (L{s['line']})" for s in h['symbols']) for h in report['code_hints']]
    lines += ['', '## 新增、变化与缺失', json.dumps(report['changes'], ensure_ascii=False), '', '## 后续核对',
              '- 阅读设计资料正文，核对正式规则与开发计划。', '- 在隔离工程中验证编译、启动和核心玩法；随后填写任务验收依据。',
              '- 缺失原文件和外部编辑需人工核对；未覆盖工作台已有编辑版本。']
    lines += ['', '## 扫描限制', *report['warnings']]
    did = _document(c, pid, '原项目现状 · ' + store.now()[:10], '\n'.join(lines))
    c.execute('INSERT OR REPLACE INTO project_intakes VALUES (?,?,?,?,?)',
              (pid, did, json.dumps(report, ensure_ascii=False), json.dumps(files, ensure_ascii=False), store.now()))
    return {'summary_document_id': did, 'report': report}


def attach(data):
    if not isinstance(data, dict):
        raise ValueError('导入参数无效')
    result = get_preview(data.get('preview_id', ''))
    selected = data.get('documents', result['suggested_documents'])
    root = _verify(result, selected)
    name, engine = str(data.get('name') or root.name).strip(), data.get('engine') or result['engine']
    if not name or len(name) > 100 or engine not in ('unreal', 'unity'):
        raise ValueError('请填写项目名称并选择引擎')
    if result['engine'] and result['engine'] != engine:
        raise ValueError('选择的引擎与已识别工程不一致')
    pid = store.uid()
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if any(os.path.normcase(str(Path(p['root']).resolve())) == os.path.normcase(str(root)) for p in c.execute('SELECT root FROM projects')):
            raise ValueError('此目录已接入，请打开现有项目并重新扫描')
        c.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)', (pid, name, engine, str(root), '', store.now()))
        c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('project_roots:' + pid, json.dumps(result.get('roots', [])[1:])))
        _apply(c, pid, {**result, 'engine': engine}, selected)
    PREVIEWS.pop(result['id'], None)
    return store.project(pid)


def current(pid, include_files=False):
    row = store.one('SELECT * FROM project_intakes WHERE project_id=?', (pid,))
    if not row:
        return None
    value = {'summary_document_id': row['summary_document_id'], 'report': json.loads(row['report']), 'updated': row['updated']}
    if include_files:
        value['files'] = json.loads(row['files'])
    return value


def preview_sources(pid, values):
    state = current(pid)
    if state and state['report'].get('restored_snapshot'): raise ValueError('历史恢复副本不能直接授权原目录，请重新接入真实工程')
    if not isinstance(values, list) or not values: raise ValueError('请填写要补充的目录')
    old = source_roots(pid)
    result = scan_roots([r['path'] for r in old] + values)
    result.update(project_id=pid, expected_roots=old)
    return result


def attach_sources(pid, data):
    result = get_preview(data.get('preview_id'))
    if result.get('project_id') != pid or result.get('expected_roots') != source_roots(pid):
        raise ValueError('来源目录已变化或预览不属于当前项目，请重新扫描')
    p = store.project(pid)
    if result['engine'] and result['engine'] != p['engine']: raise ValueError('主工程引擎已变化，请重新核对')
    selected = data.get('documents', [])
    _verify(result, selected)
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        stored = c.execute('SELECT value FROM settings WHERE key=?', ('project_roots:' + pid,)).fetchone()
        if (json.loads(stored['value']) if stored else []) != result['expected_roots'][1:]:
            raise ValueError('来源目录已变化，请重新扫描')
        c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('project_roots:' + pid, json.dumps(result['roots'][1:])))
        value = _apply(c, pid, {**result, 'engine': p['engine']}, selected, current(pid, True))
    PREVIEWS.pop(result['id'], None)
    return value


def document_sources(pid):
    state = current(pid, True)
    if not state:
        return {}
    result = {did: {'status': 'superseded', 'note': '较早的接入快照或原文已有更新，请核对最新现状文档'} for did in state['report'].get('superseded_document_ids', [])}
    for f in state['files']:
        if f.get('document_id'):
            result[f['document_id']] = {'path': f['path'], 'status': f.get('document_status', 'present') if f['status'] == 'present' else f['status'], 'source_hash': f.get('hash', ''), 'note': '从原工程复制的设计快照，工作台编辑不会同步回原文件'}
    result[state['summary_document_id']] = {'status': 'current_snapshot', 'note': '扫描摘要；原文陈述和结构线索尚未独立运行验收'}
    return result


def refresh(pid):
    p = store.project(pid)
    previous = current(pid, True)
    if previous and previous['report'].get('restored_snapshot'):
        raise ValueError('恢复副本只有历史清单；如需扫描原工程，请从真实工程目录重新接入')
    result = scan_roots([r['path'] for r in source_roots(pid)])
    if result['engine'] and result['engine'] != p['engine']:
        raise ValueError('原目录引擎与项目配置不一致，请通过接入向导核对正确工程')
    result['engine'] = result['engine'] or p['engine']
    excluded = set(previous['report'].get('excluded_documents', [])) if previous else set()
    selected = sorted(set(result['_texts']) - excluded)
    _verify(result, selected)
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        value = _apply(c, pid, result, selected, previous)
    PREVIEWS.pop(result['id'], None)
    return value


def file_list(pid, query='', category_filter='', offset=0, limit=60):
    store.project(pid)
    if not isinstance(query, str) or len(query) > 200 or not isinstance(category_filter, str) or len(category_filter) > 30:
        raise ValueError('文件检索范围无效')
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    sql = '''FROM project_intakes p,json_each(p.files) f WHERE p.project_id=?
        AND json_extract(f.value,'$.path') LIKE ? ESCAPE '\\'
        AND (?='' OR json_extract(f.value,'$.category')=?)'''
    args = (pid, pattern, category_filter, category_filter)
    total = store.one('SELECT COUNT(*) AS n ' + sql, args)['n']
    values = store.rows('SELECT f.value ' + sql + ' ORDER BY CAST(f.key AS INTEGER) LIMIT ? OFFSET ?', (*args, max(1, min(limit, 100)), max(0, offset)))
    return {'total': total, 'items': [json.loads(f['value']) for f in values]}


def read_file(pid, relative, offset, limit):
    store.project(pid)
    state = current(pid, True)
    if not state or state['report'].get('restored_snapshot'):
        raise ValueError('此项目没有可读取的原工程目录，请使用已导入的文档快照')
    f = next((f for f in state['files'] if f['path'] == relative and f['status'] == 'present'), None)
    if not f or Path(relative).suffix.lower() not in CODE | DESIGN | {'.uproject', '.uplugin', '.asmdef'}:
        raise ValueError('只能读取接入清单中的设计正文、代码或受支持的工程描述文件')
    design_text = Path(relative).suffix.lower() in DESIGN and relative.lower() != 'projectsettings/projectversion.txt'
    if design_text and relative not in state['report']['selected_documents']:
        raise ValueError('此文档未选择纳入 AI 资料，请先人工导入')
    path = source_path(source_roots(pid), f)
    try:
        stat = path.stat()
    except OSError:
        raise ValueError('原文件无法读取或已移动，请重新扫描')
    if linked(path) or stat.st_size != f['bytes'] or stat.st_mtime_ns != f['mtime_ns']:
        raise ValueError('原文件已变化，请先重新扫描并核对')
    if stat.st_size > MAX_TEXT_BYTES:
        raise ValueError('原文件超出单文件读取上限，请拆分资料')
    try:
        text, digest = read_text(path)
    except OSError:
        raise ValueError('原文件无法读取或已移动，请重新扫描')
    if text is None or (f.get('hash') and f['hash'] != digest):
        raise ValueError('原文件不是支持的文本，或内容已变化，请重新扫描')
    if isinstance(offset, bool) or isinstance(limit, bool) or not isinstance(offset, int) or not isinstance(limit, int) or not 0 <= offset <= len(text) or not 1 <= limit <= 12000:
        raise ValueError('分段范围无效，单次最多读取 12000 字符')
    return {'path': relative, 'category': f['category'], 'hash': digest, 'content': text[offset:offset + limit],
            'total_chars': len(text), 'next_offset': offset + limit if offset + limit < len(text) else None,
            'note': '原工程当前文本，按字符分段；未执行或编译。常见凭据已尽力隐藏，不能保证识别所有私密内容'}
