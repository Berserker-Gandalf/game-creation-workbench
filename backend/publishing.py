"""Review a frozen snapshot and publish a new GitHub branch, without touching source Git."""
import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import urlsplit, quote

import httpx
from . import assets, secrets, snapshots, store
from scripts.check_release import SECRET, HOME, TOKEN

ASSETS = set(assets.KINDS) | {'.stl', '.mp4', '.mov', '.pak', '.dll', '.exe'}
LFS_THRESHOLD = 1024 * 1024


def repo_name(value):
    if not isinstance(value, str): raise ValueError('请输入 GitHub 仓库地址')
    p = urlsplit(value)
    if p.scheme != 'https' or p.hostname != 'github.com' or p.username or p.password or p.port not in (None, 443) or p.query or p.fragment:
        raise ValueError('仅支持 https://github.com/所有者/仓库，不接受带凭据的地址')
    parts = p.path.strip('/').removesuffix('.git').split('/')
    if len(parts) != 2 or any(not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', v) or v in ('.', '..') for v in parts): raise ValueError('GitHub 仓库路径无效')
    return tuple(parts)


def config():
    return {'configured': bool(secrets.get_key('github')), 'git': bool(shutil.which('git')), 'lfs': lfs_available(),
            'note': '上传到已存在且有写入权限的 GitHub 仓库；不复制原 Git 历史，不改原工程暂存区'}


def save_config(data):
    if not isinstance(data, dict) or set(data) - {'key', 'clear_key'}: raise ValueError('GitHub 配置无效')
    key = data.get('key', '')
    if not isinstance(key, str) or len(key) > 500 or any(c.isspace() for c in key) or ('clear_key' in data and type(data['clear_key']) is not bool): raise ValueError('GitHub Token 无效')
    if key or data.get('clear_key'): secrets.save_key('github', '' if data.get('clear_key') else key)
    return config()


async def repository(owner, name):
    key = secrets.get_key('github')
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    if key: headers['Authorization'] = 'Bearer ' + key
    async with httpx.AsyncClient(timeout=25, trust_env=False, follow_redirects=False) as client:
        r = await client.get(f'https://api.github.com/repos/{owner}/{name}', headers=headers)
    if r.status_code != 200: raise ValueError('仓库不可读取，请先在 GitHub 创建仓库，并核对 Token、仓库地址和权限')
    data = r.json()
    if data.get('full_name', '').lower() != f'{owner}/{name}'.lower(): raise ValueError('GitHub 返回仓库身份不匹配')
    return {k: data.get(k) for k in ('id', 'full_name', 'private', 'permissions')}


def env(repo, authenticated=False):
    e = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'GH_'))}
    e.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')
    hooks = Path(repo).parent / 'disabled-hooks'; hooks.mkdir(exist_ok=True)
    values = [('core.hooksPath', str(hooks)), ('credential.helper', ''), ('commit.gpgsign', 'false'), ('tag.gpgSign', 'false')]
    if authenticated:
        key = secrets.get_key('github')
        if not key: raise ValueError('请先配置 GitHub Token')
        token = base64.b64encode(('x-access-token:' + key).encode()).decode()
        values.append(('http.https://github.com/.extraheader', 'AUTHORIZATION: basic ' + token))
    e['GIT_CONFIG_COUNT'] = str(len(values))
    for i, (key, value) in enumerate(values): e[f'GIT_CONFIG_KEY_{i}'] = key; e[f'GIT_CONFIG_VALUE_{i}'] = value
    return e


def git(repo, *args, authenticated=False, timeout=300):
    exe = shutil.which('git')
    if not exe: raise ValueError('请先安装 Git')
    r = subprocess.run([exe, '-C', str(repo), *args], env=env(repo, authenticated), capture_output=True, timeout=timeout,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if r.returncode: raise ValueError('Git 操作未成功，请核对仓库权限、网络和 Git LFS；未强制推送')
    return r.stdout.decode('utf-8', errors='replace').strip()


def lfs_available():
    exe = shutil.which('git')
    if not exe: return False
    try: return subprocess.run([exe, 'lfs', 'version'], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired): return False


def job(jid):
    row = store.one('SELECT * FROM github_publications WHERE id=?', (jid,))
    if not row: raise ValueError('GitHub 发布记录不存在')
    row['report'] = json.loads(row['report'])
    return row


def jobs(pid):
    store.project(pid)
    return [job(r['id']) for r in store.rows('SELECT id FROM github_publications WHERE project_id=? ORDER BY created DESC,rowid DESC LIMIT 100', (pid,))]


def sensitive(path):
    # Read chunks with overlap so a credential across a chunk boundary is detected.
    tail = b''
    with path.open('rb') as f:
        while chunk := f.read(1024 * 1024):
            raw = tail + chunk
            text = raw.decode('utf-8', errors='ignore')
            if SECRET.search(text) or TOKEN.search(text) or re.search(r'-----BEGIN [A-Z ]*PRIVATE KEY-----', text): return '发现疑似密钥或账户令牌'
            if b'\x00' not in raw and HOME.search(text): return '发现个人绝对路径，请排除或处理后重新预览'
            tail = raw[-1024:]
    return ''


def publication_skip(name):
    parts = Path(name).parts
    return any(p.lower() in {'thirdparty', 'vendor', '.github', '.codex', '.claude', '.vscode', '.git', '.gitmodules', '.lfsconfig', '.gitattributes'} for p in parts)


async def prepare(sid, data):
    if not isinstance(data, dict) or type(data.get('include_assets', True)) is not bool: raise ValueError('发布选项无效')
    owner, name = repo_name(data.get('repository'))
    meta = await repository(owner, name)
    if type(meta.get('private')) is not bool: raise ValueError('仓库可见性未确认')
    exclusions = data.get('exclude', [])
    if not isinstance(exclusions, list) or any(not isinstance(v, str) or len(v) > 1000 for v in exclusions) or len(exclusions) > 1000: raise ValueError('排除清单无效')
    j = snapshots.job(sid)
    return await asyncio.to_thread(build, j, owner, name, meta, data.get('include_assets', True), exclusions)


def build(snapshot, owner, name, meta, include_assets, exclusions):
    manifest = snapshots.verify(snapshot['id'])
    jid = store.uid(); folder = (store.DATA / 'publications' / snapshot['project_id'] / jid).resolve()
    folder.mkdir(parents=True, exist_ok=False); repo = folder / 'repo'; repo.mkdir()
    report = {'repository': meta, 'snapshot_sha256': snapshot['archive_sha256'], 'include_assets': include_assets,
              'files': [], 'blocked': [], 'excluded': [], 'lfs_files': [], 'history_mode': '独立快照分支，不复制原 Git 历史'}
    with zipfile.ZipFile(snapshot['archive']) as z:
        for record in manifest['files']:
            path = record['path']
            if not path.startswith(('game/', 'sources/')): continue
            if path in exclusions or publication_skip(path) or (not include_assets and Path(path).suffix.lower() in ASSETS):
                report['excluded'].append(path); continue
            dest = assets.inside(repo / path, repo); dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(path) as src, dest.open('xb') as dst: shutil.copyfileobj(src, dst, 1024 * 1024)
        with z.open('workbench/project.zip') as src, (folder / 'workbench.zip').open('xb') as dst: shutil.copyfileobj(src, dst, 1024 * 1024)
    with zipfile.ZipFile(folder / 'workbench.zip') as z:
        if z.getinfo('project.json').file_size > 50 * 1024 ** 2: raise ValueError('工作台资料包过大，请分项目发布')
        original = json.loads(z.read('project.json'))
        workbench = repo / 'workbench'; workbench.mkdir()
        public = {'project': {k: original['project'][k] for k in ('name', 'engine', 'brief')},
                  'documents': original['documents'], 'tasks': original['tasks'],
                  'task_dependencies': original.get('task_dependencies', []), 'task_documents': original.get('task_documents', []),
                  'note': '不含对话、账号、运行日志、工具事件或本机设置；资产仅保留当前版本'}
        if 'workbench/project.json' not in exclusions: (workbench / 'project.json').write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding='utf-8')
        if include_assets:
            for a in original['assets']:
                path = f"workbench/assets/{a['id']}{Path(a['active']).suffix}"
                if path in exclusions: report['excluded'].append(path); continue
                dest = assets.inside(repo / path, repo); dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(a['active']) as src, dest.open('xb') as dst: shutil.copyfileobj(src, dst, 1024 * 1024)
    safe = {k: manifest[k] for k in ('snapshot_id', 'project', 'label', 'kind', 'note', 'started_at', 'finished_at', 'parent_id', 'parent_sha256')}
    safe['workbench_version'] = manifest.get('workbench_version')
    safe['archive_sha256'] = snapshot['archive_sha256']
    (repo / 'SNAPSHOT.json').write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding='utf-8')
    (repo / 'README.md').write_text('# ' + manifest['project']['name'] + '\n\n这是经工作台审阅的项目快照分支。工程位于 game/，设计与任务位于 workbench/。\n\n原始 Git 历史、对话和账号凭据不在此分支。第三方依赖、缓存与被排除文件需要另行准备。\n\n快照 SHA-256：' + snapshot['archive_sha256'] + '\n', encoding='utf-8')
    lfs = lfs_available()
    for path in sorted(repo.rglob('*')):
        if not path.is_file(): continue
        rel = path.relative_to(repo).as_posix(); size = path.stat().st_size
        reason = sensitive(path)
        if reason: report['blocked'].append({'path': rel, 'reason': reason})
        if size > LFS_THRESHOLD:
            report['lfs_files'].append({'path': rel, 'bytes': size})
            if not lfs: report['blocked'].append({'path': rel, 'reason': '超过 1 MiB 的文件需要 Git LFS'})
        report['files'].append({'path': rel, 'bytes': size, 'sha256': snapshots.digest(path)})
    if sum(f['bytes'] for f in report['files'] if f['bytes'] <= LFS_THRESHOLD) > 256 * 1024 ** 2:
        report['blocked'].append({'path': '*', 'reason': '普通 Git 文件总量超过 256 MiB，请拆分工程'})
    branch = 'codex/snapshot-' + snapshot['id'][:12] + '-' + jid[:8]
    commit, status = '', 'blocked' if report['blocked'] else 'prepared'
    if not report['blocked']:
        if report['lfs_files']:
            # Quoted UTF-8 paths; control characters were already rejected during snapshotting.
            lines = []
            for item in report['lfs_files']:
                if any(c in item['path'] for c in '*?[]'): raise ValueError('LFS 文件名含通配符，请核对后发布')
                lines.append('"' + item['path'].replace('\\', '\\\\').replace('"', '\\"') + '" filter=lfs diff=lfs merge=lfs -text')
            (repo / '.gitattributes').write_text('\n'.join(lines) + '\n', encoding='utf-8')
            path = repo / '.gitattributes'
            report['files'].append({'path': '.gitattributes', 'bytes': path.stat().st_size, 'sha256': snapshots.digest(path)})
        git(repo, 'init', '--initial-branch=' + branch)
        git(repo, 'config', 'user.name', 'Game Workbench')
        git(repo, 'config', 'user.email', 'snapshot@local.invalid')
        git(repo, 'config', 'core.autocrlf', 'false')
        if report['lfs_files']:
            git(repo, 'config', 'filter.lfs.process', 'git-lfs filter-process')
            git(repo, 'config', 'filter.lfs.required', 'true')
        git(repo, 'add', '--all', '--force')
        git(repo, 'commit', '-m', 'Snapshot: ' + snapshot['label'])
        commit = git(repo, 'rev-parse', 'HEAD')
        git(repo, 'remote', 'add', 'origin', f'https://github.com/{owner}/{name}.git')
    report['total_bytes'] = sum(f['bytes'] for f in report['files'])
    store.execute('INSERT INTO github_publications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (jid, snapshot['project_id'], snapshot['id'], f'{owner}/{name}', branch, commit, status, str(folder), json.dumps(report, ensure_ascii=False), '', '', store.now(), store.now()))
    return job(jid)


def verify_prepared(j):
    repo = Path(j['folder']) / 'repo'
    for f in j['report']['files']:
        path = assets.inside(repo / f['path'], repo)
        if not path.is_file() or snapshots.digest(path) != f['sha256']: raise ValueError('待发布文件已变化，请重新生成发布预览')
    if git(repo, 'rev-parse', 'HEAD') != j['commit'] or git(repo, 'status', '--porcelain'): raise ValueError('待发布提交或工作区发生变化，请重新预览')
    tracked = set(git(repo, 'ls-files', '-z').rstrip('\0').split('\0'))
    if tracked != {f['path'] for f in j['report']['files']}: raise ValueError('待发布提交的文件清单不匹配，请重新预览')
    if git(repo, 'remote', 'get-url', 'origin') != 'https://github.com/' + j['repository'] + '.git': raise ValueError('待发布远端地址已变化，请重新预览')
    return repo


def remote_head(j):
    text = git(Path(j['folder']) / 'repo', 'ls-remote', 'origin', 'refs/heads/' + j['branch'], authenticated=True)
    return text.split()[0] if text else None


def send(j):
    repo = verify_prepared(j)
    head = remote_head(j)
    if head and head != j['commit']: raise ValueError('远端分支已存在不同提交，禁止覆盖')
    if head == j['commit']: return
    if j['report']['lfs_files']: git(repo, 'lfs', 'push', 'origin', j['branch'], authenticated=True, timeout=1800)
    git(repo, 'push', 'origin', 'HEAD:refs/heads/' + j['branch'], authenticated=True, timeout=1800)
    if remote_head(j) != j['commit']: raise ValueError('远端提交尚未确认')


async def push(jid, data):
    j = job(jid)
    if not isinstance(data, dict) or data.get('confirmed') is not True or data.get('rights_ack') is not True:
        raise ValueError('请审阅发布清单并确认上传权利、文件范围和可能的 LFS 配额消耗')
    if j['status'] != 'prepared' or j['report']['blocked']: raise ValueError('此发布尚未准备好，或结果未知需先核对')
    owner, name = j['repository'].split('/')
    meta = await repository(owner, name)
    if meta['id'] != j['report']['repository']['id'] or meta['private'] != j['report']['repository']['private']: raise ValueError('仓库身份或可见性已变化，请重新预览')
    if not (meta.get('permissions') or {}).get('push'): raise ValueError('当前 GitHub Token 没有此仓库写入权限')
    if not meta['private'] and data.get('public_ack') is not True: raise ValueError('目标是公开仓库，请明确确认公开此清单内容')
    with store.db() as c:
        if not c.execute("UPDATE github_publications SET status='pushing',updated=? WHERE id=? AND status='prepared'", (store.now(), jid)).rowcount: raise ValueError('此发布已开始，请勿重复提交')
    rid = store.run_start(j['project_id'], 'github_push', '上传快照分支 ' + j['branch'])
    try:
        await asyncio.to_thread(send, j)
        mark_published(j)
        store.run_end(rid, 'completed', 'GitHub 快照分支与提交已核对')
    except BaseException as exc:
        store.execute("UPDATE github_publications SET status='unknown',error=?,updated=? WHERE id=?", ('推送结果未确认，请先核对远端；未自动重试或强制推送', store.now(), jid))
        store.run_end(rid, 'interrupted', 'GitHub 推送结果待核对')
        if isinstance(exc, asyncio.CancelledError): raise
    return job(jid)


def mark_published(j):
    url = 'https://github.com/' + j['repository'] + '/tree/' + quote(j['branch'], safe='')
    store.execute("UPDATE github_publications SET status='published',url=?,error='',updated=? WHERE id=?", (url, store.now(), j['id']))


async def check(jid):
    j = job(jid)
    if j['status'] not in ('unknown', 'prepared', 'published'): raise ValueError('当前发布状态不能核对')
    head = await asyncio.to_thread(remote_head, j)
    if head == j['commit']: mark_published(j)
    elif not head: store.execute("UPDATE github_publications SET status='prepared',error=?,updated=? WHERE id=?", ('远端尚无此分支；可再次明确确认同一提交，未自动上传', store.now(), jid))
    else: raise ValueError('远端存在其他提交，禁止覆盖')
    return job(jid)
