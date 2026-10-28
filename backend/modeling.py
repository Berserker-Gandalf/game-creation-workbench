"""Bounded character recipes executed by our fixed, offline Blender driver."""
import asyncio
import json
import math
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

from PIL import Image
from . import assets, store

DEFAULTS = dict(title='低模探索者', brief='', style='human', height=1.7, head_ratio=.22,
                shoulder_ratio=.26, leg_ratio=.46, arm_ratio=.34, body_scale=1.0,
                outfit='tunic', hair='short', accessory='backpack', pose='a_pose',
                skin_color='#d6aa83', clothing_color='#426e8d', hair_color='#302b30',
                accent_color='#d8ad54', reference_asset_id='')
RANGES = {'height': (1, 3), 'head_ratio': (.15, .30), 'shoulder_ratio': (.18, .36),
          'leg_ratio': (.35, .55), 'arm_ratio': (.2, .45), 'body_scale': (.7, 1.4)}
CHOICES = {'style': ['human', 'chibi', 'robot'], 'outfit': ['plain', 'tunic', 'armor'],
           'hair': ['none', 'short', 'bob'], 'accessory': ['none', 'backpack', 'staff'],
           'pose': ['a_pose', 't_pose']}
PROPERTIES = {k: {'type': 'number', 'minimum': lo, 'maximum': hi} if k in RANGES else
              {'type': 'string', 'enum': CHOICES[k]} if k in CHOICES else {'type': 'string'}
              for k in DEFAULTS for lo, hi in [RANGES.get(k, (0, 0))]}
RUNNING = {}


def executable():
    configured = store.setting('blender_executable', '')
    if configured:
        return configured if Path(configured).is_file() else None
    candidates = [os.environ.get('BLENDER_EXECUTABLE', ''), shutil.which('blender') or '']
    for drive in ('C:', 'D:', 'E:'):
        candidates.append(drive + '/Blender/blender.exe')
        base = Path(drive + '/Program Files/Blender Foundation')
        if base.is_dir():
            candidates.extend(str(p / 'blender.exe') for p in sorted(base.glob('Blender *'), reverse=True))
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), None)


def config():
    exe = executable()
    version, error = '', ''
    if exe:
        try:
            result = subprocess.run([exe, '--version'], capture_output=True, timeout=15,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            version = result.stdout.decode('utf-8', errors='replace').splitlines()[0]
            if result.returncode or not version.startswith('Blender '):
                raise ValueError('程序未返回有效 Blender 版本')
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
            error = str(exc) or '无法检查 Blender 版本'
    return {'executable': exe or '', 'available': bool(version and not error), 'version': version,
            'error': error, 'defaults': DEFAULTS, 'ranges': RANGES, 'choices': CHOICES}


def save_config(data):
    if not isinstance(data, dict) or set(data) - {'executable'}:
        raise ValueError('Blender 设置字段无效')
    value = data.get('executable', '')
    if not isinstance(value, str):
        raise ValueError('Blender 路径无效')
    path = Path(value).expanduser().resolve() if value.strip() else None
    if path and (not path.is_file() or path.name.lower() not in ('blender.exe', 'blender')):
        raise ValueError('请选择已安装的 blender.exe；留空使用自动发现')
    store.set_setting('blender_executable', str(path) if path else '')
    return config()


def validate(pid, data):
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValueError('角色参数包含未开放字段；不接收脚本或文件路径')
    spec = {**DEFAULTS, **data}
    for k, (lo, hi) in RANGES.items():
        v = spec[k]
        if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not lo <= v <= hi:
            raise ValueError(f'{k} 必须为 {lo}–{hi} 的数值')
    if spec['head_ratio'] + spec['leg_ratio'] > .8:
        raise ValueError('头部与腿长合计不得超过身高的 80%，需保留躯干')
    for k, values in CHOICES.items():
        if spec[k] not in values:
            raise ValueError('无效角色选项：' + k)
    for k in ('skin_color', 'clothing_color', 'hair_color', 'accent_color'):
        if not isinstance(spec[k], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', spec[k]):
            raise ValueError('颜色需为 #RRGGBB：' + k)
    for k, maximum in (('title', 100), ('brief', 4000), ('reference_asset_id', 64)):
        if not isinstance(spec[k], str) or len(spec[k]) > maximum:
            raise ValueError('参数过长或类型无效：' + k)
    if not spec['title'].strip():
        raise ValueError('请填写角色名称')
    return spec


def reference(pid, spec):
    if not spec['reference_asset_id']:
        return ''
    a = assets.asset(spec['reference_asset_id'])
    if a['project_id'] != pid or a['kind'] != 'image':
        raise ValueError('参考图必须属于当前项目')
    return assets.digest(assets.file_for(a))


def job(jid):
    row = store.one('SELECT * FROM character_jobs WHERE id=?', (jid,))
    if not row:
        raise ValueError('角色方案不存在')
    return row


def jobs(pid):
    store.project(pid)
    return store.rows('SELECT * FROM character_jobs WHERE project_id=? ORDER BY created DESC,rowid DESC LIMIT 100', (pid,))


def draft(pid, data, parent_id=None):
    store.project(pid)
    spec = validate(pid, data)
    if parent_id is not None and (not isinstance(parent_id, str) or not parent_id or len(parent_id) > 64):
        raise ValueError('原始角色方案 ID 无效')
    if parent_id and job(parent_id)['project_id'] != pid:
        raise ValueError('原始角色方案不属于此项目')
    result = {'reference_hash': reference(pid, spec)}
    jid = store.uid()
    store.execute('INSERT INTO character_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                  (jid, pid, parent_id, None, None, None, None, json.dumps(spec, ensure_ascii=False),
                   'draft', json.dumps(result), store.now(), store.now()))
    if parent_id:
        linked = store.one("SELECT task_id FROM task_creations WHERE kind='blender' AND job_id=? AND project_id=?", (parent_id, pid))
        if linked: store.execute('INSERT INTO task_creations VALUES (?,?,?,?,?,?)', (store.uid(), pid, linked['task_id'], 'blender', jid, store.now()))
    return job(jid)


async def start(jid, confirmed):
    if confirmed is not True:
        raise ValueError('请先审阅参数并确认在本机生成')
    j = job(jid)
    if j['status'] != 'draft' or RUNNING:
        raise ValueError('方案已执行或 Blender 正在生成；请等待或复制方案')
    spec = validate(j['project_id'], json.loads(j['spec']))
    if reference(j['project_id'], spec) != json.loads(j['result']).get('reference_hash', ''):
        raise ValueError('参考图版本已变化，请复制并重新审阅方案')
    exe = executable()
    if not exe:
        raise ValueError('未找到 Blender，请配置程序路径')
    # No await between checking the worker slot and reserving it.
    rid = store.run_start(j['project_id'], 'blender_character', spec['title'], agent='modeler')
    store.execute("UPDATE character_jobs SET status='building',run_id=?,updated=? WHERE id=?", (rid, store.now(), jid))
    control = RUNNING[jid] = {'cancelled': False, 'process': None, 'task': None}
    control['task'] = asyncio.create_task(build(jid, exe, control))
    return job(jid)


async def render(exe, folder, control):
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    for name in ('BLENDER_USER_CONFIG', 'BLENDER_USER_SCRIPTS', 'BLENDER_USER_EXTENSIONS'):
        path = folder / name.lower()
        path.mkdir()
        env[name] = str(path)
    command = [exe, '--background', '--factory-startup', '--disable-autoexec', '--offline-mode',
               '--python-exit-code', '1', '--python', str(store.ROOT / 'connectors/blender/build_character.py'), '--', str(folder)]
    with (folder / 'blender.log').open('wb') as log:
        proc = await asyncio.create_subprocess_exec(*command, cwd=folder, env=env, stdout=log, stderr=log,
                                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        control['process'] = proc
        if control['cancelled']:
            proc.terminate()
        try:
            code = await asyncio.wait_for(proc.wait(), timeout=180)
        except (TimeoutError, asyncio.CancelledError):
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            raise
    if code:
        raise ValueError('Blender 执行失败，请查看生成日志；未自动重试')


def verify_outputs(folder):
    blend, glb, png = (folder / name for name in ('character.blend', 'character.glb', 'preview.png'))
    if not blend.is_file() or not blend.read_bytes().startswith(b'BLENDER'):
        raise ValueError('未导出有效 Blender 源文件')
    raw = glb.read_bytes()
    if len(raw) < 20 or struct.unpack('<III', raw[:12]) != (0x46546c67, 2, len(raw)):
        raise ValueError('GLB 文件头或长度无效')
    size, kind = struct.unpack('<II', raw[12:20])
    if kind != 0x4e4f534a or size > len(raw) - 20:
        raise ValueError('GLB 场景清单无效')
    doc = json.loads(raw[20:20 + size])
    if not doc.get('meshes') or any(item.get('uri') and not item['uri'].startswith('data:') for key in ('images', 'buffers') for item in doc.get(key, [])):
        raise ValueError('GLB 缺少网格或引用了外部文件')
    with Image.open(png) as im:
        if im.size != (512, 512):
            raise ValueError('角色预览尺寸不符合约定')
        im.verify()
    stats = json.loads((folder / 'build.json').read_text(encoding='utf-8'))
    if not isinstance(stats, dict) or not stats.get('objects') or stats.get('rigged') is not False:
        raise ValueError('缺少建模验证信息')
    return stats, (glb, blend, png)


async def build(jid, exe, control):
    j = job(jid)
    folder = store.project_dir(j['project_id']) / 'modeling' / jid
    result = json.loads(j['result'])
    status = 'failed'
    try:
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'recipe.json').write_text(j['spec'], encoding='utf-8')
        if not control['cancelled']:
            await render(exe, folder, control)
        if control['cancelled']:
            raise asyncio.CancelledError()
        stats, files = verify_outputs(folder)
        ids = [store.uid() for _ in files]
        result.update(stats=stats, hashes={p.name: assets.digest(p) for p in files}, note='参数化低模草稿；未绑定、未做引擎运行验收')
        with store.db() as c:
            title = json.loads(j['spec'])['title']
            for aid, path, label in zip(ids, files, ('模型.glb', '源文件.blend', '预览.png')):
                versions = json.dumps([{'path': str(path), 'label': 'Blender 参数化草稿', 'created': store.now()}])
                c.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)',
                          (aid, j['project_id'], title + ' · ' + label, str(path), str(path), assets.KINDS[path.suffix], versions, store.now()))
            c.execute("UPDATE character_jobs SET model_id=?,source_id=?,preview_id=?,status='review',result=?,updated=? WHERE id=?",
                      (*ids, json.dumps(result, ensure_ascii=False), store.now(), jid))
        status = 'completed'
    except asyncio.CancelledError:
        status = 'interrupted'
        result['error'] = '生成已停止；未发布未完成的资产'
    except Exception as exc:
        status = 'interrupted' if control['cancelled'] else 'failed'
        result['error'] = '生成已停止；未发布未完成的资产' if control['cancelled'] else ('Blender 生成超过 3 分钟，已停止本次进程' if isinstance(exc, TimeoutError) else str(exc)[:1000] or '生成失败，请查看日志')
    finally:
        if status != 'completed':
            store.execute('UPDATE character_jobs SET status=?,result=?,updated=? WHERE id=?', (status, json.dumps(result, ensure_ascii=False), store.now(), jid))
        store.run_end(j['run_id'], status, '角色草稿已生成，等待美术验收' if status == 'completed' else result['error'])
        RUNNING.pop(jid, None)


def cancel(jid):
    j = job(jid)
    control = RUNNING.get(jid)
    if control:
        control['cancelled'] = True
        proc = control['process']
        if proc and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
    return {'status': j['status'], 'cancelling': bool(control)}


async def shutdown():
    pending = [v['task'] for v in RUNNING.values()]
    for jid in list(RUNNING):
        cancel(jid)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def logs(jid):
    j = job(jid)
    path = store.project_dir(j['project_id']) / 'modeling' / jid / 'blender.log'
    if not path.is_file():
        return {'text': '暂无本机生成日志（恢复副本不包含运行日志）'}
    with path.open('rb') as f:
        f.seek(max(0, path.stat().st_size - 12000))
        return {'text': f.read().decode('utf-8', errors='replace')}


def open_source(jid):
    j = job(jid)
    if j['status'] != 'review' or not j['source_id']:
        raise ValueError('请先生成可编辑源文件')
    path = assets.file_for(assets.asset(j['source_id']))
    if assets.digest(path) != json.loads(j['result']).get('hashes', {}).get('character.blend'):
        raise ValueError('源文件已变化，请手动核对后在 Blender 中打开')
    exe = executable()
    if not exe:
        raise ValueError('未找到 Blender')
    subprocess.Popen([exe, '--factory-startup', '--disable-autoexec', '--offline-mode', str(path)], cwd=path.parent)
    return {'opened': True, 'note': '源文件将在 Blender 中打开；另存为后可导入资产工作区'}
