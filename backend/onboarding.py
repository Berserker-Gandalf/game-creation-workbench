"""Human-operated setup: fixed installers, no model calls or project execution."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from . import codex, diagnostics, modeling, music, skill_setup, store

FEATURES = ('core', 'codex', 'api', 'music', 'blender', 'tripo', 'webui', 'github', 'engines')
PACKAGES = {'node': 'OpenJS.NodeJS.LTS', 'git': 'Git.Git', 'blender': 'BlenderFoundation.Blender'}
CODEX_PACKAGE = '@openai/codex@0.163.0'
PLANS = {}
RUNNING = {}


def windows():
    return os.name == 'nt'


def refresh_path():
    candidates = [store.DATA / 'tools/npm', store.DATA / 'tools/npm/bin']
    if windows():
        candidates += [Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / p for p in ('nodejs', 'Git/cmd')]
        candidates += [Path(os.environ.get('APPDATA', str(Path.home()))) / 'npm',
                       Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Programs/Git/cmd']
    current = os.environ.get('PATH', '').split(os.pathsep)
    os.environ['PATH'] = os.pathsep.join(current + [str(p) for p in candidates if p.is_dir() and str(p) not in current])


def installed():
    refresh_path()
    return {'node': bool(shutil.which('node')), 'codex': bool(codex.executable()),
            'git': bool(shutil.which('git')), 'blender': bool(modeling.executable()), 'suno': skill_setup.valid(music.installation()[0])}


def history():
    return [json.loads(r['value']) for r in store.rows("SELECT value FROM settings WHERE key LIKE 'onboarding_install:%' ORDER BY rowid DESC LIMIT 20")]


def overview():
    return {'features': store.setting('onboarding_features', ['core']), 'seen': store.setting('onboarding_seen', False),
            'installed': installed(), 'winget': bool(windows() and shutil.which('winget')),
            'report': diagnostics.inspect(), 'installations': history()}


def save(data):
    if not isinstance(data, dict) or set(data) - {'features', 'seen'}:
        raise ValueError('上手设置字段无效')
    features = data.get('features', store.setting('onboarding_features', ['core']))
    if not isinstance(features, list) or len(features) > len(FEATURES) or any(v not in FEATURES for v in features) or ('seen' in data and type(data['seen']) is not bool):
        raise ValueError('请选择有效功能并确认上手设置')
    store.set_setting('onboarding_features', list(dict.fromkeys(['core', *features])))
    if 'seen' in data: store.set_setting('onboarding_seen', data['seen'])
    return {'saved': True}


def prepare(data):
    if not isinstance(data, dict) or set(data) != {'tools'} or not isinstance(data['tools'], list) or not data['tools'] or len(data['tools']) > 5 or any(v not in (*PACKAGES, 'codex', 'suno') for v in data['tools']):
        raise ValueError('请选择支持的装配工具')
    found = installed()
    requested = set(data['tools'])
    if requested & {'codex', 'suno'}: requested.add('node')
    steps = [v for v in ('node', 'codex', 'suno', 'git', 'blender') if v in requested and not found.get(v, False)]
    if any(v in PACKAGES for v in steps) and not (windows() and shutil.which('winget')):
        raise ValueError('本机缺少 WinGet，请使用官方安装指引后重新检测')
    free = shutil.disk_usage(store.DATA).free
    if free < (2 * 1024 ** 3 if 'blender' in steps else 512 * 1024 ** 2):
        raise ValueError('装配所需可用磁盘空间不足，请先释放空间')
    for key, plan in list(PLANS.items()):
        if plan['expires'] < time.monotonic(): PLANS.pop(key)
    if len(PLANS) >= 30: PLANS.pop(next(iter(PLANS)))
    pid = store.uid()
    plan = {'id': pid, 'steps': [{'tool': v, 'source': 'Suno.cn · ' + skill_setup.VERSION + ' · SHA256 ' + skill_setup.SHA256 if v == 'suno' else 'npm · ' + CODEX_PACKAGE if v == 'codex' else 'WinGet · ' + PACKAGES[v],
                                 'destination': str(skill_setup.root()) if v == 'suno' else str(store.DATA / 'tools/npm') if v == 'codex' else 'Windows installer'} for v in steps]}
    PLANS[pid] = {**plan, 'expires': time.monotonic() + 600}
    return plan


def npm_command():
    node = shutil.which('node')
    npm = shutil.which('npm.cmd') or shutil.which('npm')
    if node and npm:
        script = Path(npm).parent / 'node_modules/npm/bin/npm-cli.js' if windows() else Path(npm).resolve()
        if script.is_file(): return [node, str(script)]
    raise ValueError('未找到可调用的 Node 与 npm，请先装配 Node 后重新检测')


def command(tool):
    if tool == 'codex':
        return [*npm_command(), 'install', '--global', '--prefix', str(store.DATA / 'tools/npm'), '--registry', 'https://registry.npmjs.org', '--no-audit', '--no-fund', CODEX_PACKAGE]
    winget = shutil.which('winget')
    if tool not in PACKAGES or not windows() or not winget: raise ValueError('当前工具没有可用的自动安装入口')
    return [winget, 'install', '--id', PACKAGES[tool], '--exact', '--source', 'winget', '--disable-interactivity', '--no-upgrade']


def persist(row):
    row['updated'] = store.now()
    store.set_setting('onboarding_install:' + row['id'], row)


async def start(data):
    if not isinstance(data, dict) or set(data) != {'plan_id', 'confirmed'} or data['confirmed'] is not True:
        raise ValueError('请先审阅装配清单并确认安装')
    plan = PLANS.get(data['plan_id']) if isinstance(data['plan_id'], str) else None
    if not plan or plan['expires'] < time.monotonic(): raise ValueError('装配预览已失效，请重新检测并预览')
    if RUNNING or any(r['status'] == 'unknown' for r in history()):
        raise ValueError('已有装配进行中或结果未确认，请先核对原安装器')
    PLANS.pop(plan['id'])
    row = {'id': store.uid(), 'steps': plan['steps'], 'status': 'running', 'current': '', 'completed': [],
           'created': store.now(), 'message': '开始装配；系统许可或管理员确认由用户完成'}
    persist(row)
    RUNNING[row['id']] = asyncio.create_task(worker(row))
    return row.copy()


async def worker(row):
    row['log_file'] = str(store.DATA / 'logs' / ('setup.' + row['id'] + '.log'))
    Path(row['log_file']).parent.mkdir(exist_ok=True)
    try:
        with Path(row['log_file']).open('ab') as log:
            for step in row['steps']:
                tool = step['tool']
                row['current'] = tool; persist(row)
                if not installed().get(tool, False):
                    if tool == 'suno':
                        await asyncio.to_thread(skill_setup.install)
                    else:
                        args = command(tool)
                        process = await asyncio.create_subprocess_exec(*args, cwd=store.DATA, stdout=log, stderr=subprocess.STDOUT,
                            **({'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)} if windows() else {}))
                        code = await asyncio.wait_for(process.wait(), 1800)
                        if code != 0:
                            row.update(status='failed', exit_code=code, message='安装器未成功结束，请查看本机日志或使用官方指引；未自动重试')
                            persist(row); return
                row['completed'].append(tool); persist(row)
        row.update(status='succeeded', message='装配命令已完成，请重新检测并在对应工作区验证连接')
        refresh_path()
    except (asyncio.CancelledError, asyncio.TimeoutError):
        row.update(status='unknown', message='装配状态未确认，系统安装器可能仍在运行；请先核对，禁止自动重提')
    except (OSError, ValueError):
        row.update(status='failed', message='装配入口或网络不可用，请查看本机日志并按官方指引处理')
    finally:
        persist(row); RUNNING.pop(row['id'], None)


def reconcile(jid, data):
    row = store.setting('onboarding_install:' + jid)
    if not row or row['status'] != 'unknown' or not isinstance(data, dict) or set(data) != {'installer_closed'} or data['installer_closed'] is not True:
        raise ValueError('请先确认原系统安装器已结束，再重新检测')
    found = installed()
    row.update(status='succeeded' if all(found[s['tool']] for s in row['steps']) else 'interrupted',
               message='已按用户确认重新核对程序文件；仍需独立验证连接')
    persist(row)
    return row


def recover():
    PLANS.clear()
    for row in history():
        if row['status'] == 'running':
            row.update(status='unknown', message='工作台曾中断；请确认系统安装器是否结束后重新检测')
            persist(row)


async def shutdown():
    pending = list(RUNNING.values())
    for task in pending: task.cancel()
    if pending: await asyncio.gather(*pending, return_exceptions=True)


def practice(data):
    if not isinstance(data, dict) or set(data) != {'language', 'engine'} or data['language'] not in ('zh-CN', 'en') or data['engine'] not in ('unreal', 'unity'):
        raise ValueError('请选择练习项目的界面语言与引擎偏好')
    previous = store.setting('onboarding_practice', '')
    if previous and store.one('SELECT id FROM projects WHERE id=?', (previous,)): return store.project(previous)
    en = data['language'] == 'en'
    name = 'My first game · Practice' if en else '我的第一个游戏 · 练习'
    brief = 'A local practice workspace. Edit the brief and review the task. No engine project, model call or generated content is included.' if en else '这是本机练习空间。先修改总纲，再查看任务。未创建引擎工程，没有调用模型或生成内容。'
    title = 'Start here' if en else '从这里开始'
    content = '# First steps\n\n1. Edit the project brief.\n2. Open Tasks and record what you changed.\n3. Configure an optional creation tool when needed.\n\nThis is practice data, not verified gameplay.' if en else '# 第一次使用\n\n1. 在总览修改项目总纲。\n2. 打开任务看板，记录你修改了什么。\n3. 需要创作时再按向导配置工具。\n\n这些是练习资料，不代表游戏已经实现或运行。'
    pid, stamp = store.uid(), store.now()
    folder = store.project_dir(pid)
    with store.db() as c:
        c.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)', (pid, name, data['engine'], str(folder), brief, stamp))
        c.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)', (store.uid(), pid, title, content, 1, 'draft', stamp))
        c.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?)', (store.uid(), pid, 'Write the project brief' if en else '完善项目总纲', 'todo', 'Save your brief, then record the change as acceptance evidence.' if en else '保存总纲后，在验收依据中说明具体修改。', '', stamp))
        c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('onboarding_practice', json.dumps(pid)))
        c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('onboarding_seen', 'true'))
    return store.project(pid)
