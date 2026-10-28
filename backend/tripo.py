"""Tripo V3: human-confirmed generation, recoverable tasks and local GLB assets."""
import asyncio
import io
import ipaddress
import json
import math
import re
import socket
import struct
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps
from . import assets, generation_models, secrets, store

BASES = {'cn': 'https://openapi.tripo3d.com/v3', 'global': 'https://openapi.tripo3d.ai/v3'}
MODELS = ['v3.1-20260211', 'v3.0-20250812', 'v2.5-20250123']
DEFAULTS = dict(title='Tripo 角色方案', mode='text', prompt='', source_asset_id='', model=MODELS[0], face_limit=20000, texture=True, pbr=True)
PROPERTIES = {k: {'type': 'boolean'} if isinstance(v, bool) else {'type': 'integer', 'minimum': 500, 'maximum': 100000} if isinstance(v, int) else {'type': 'string'} for k, v in DEFAULTS.items()}
PROPERTIES['mode']['enum'] = ['text', 'image']
PROPERTIES['model']['enum'] = MODELS
DOWNLOAD_DOMAINS = ('tripo3d.ai', 'tripo3d.com', 'amazonaws.com', 'cloudfront.net', 'myqcloud.com', 'aliyuncs.com')
TASK = re.compile(r'task_[A-Za-z0-9_-]{1,150}')
MAX_MODEL_BYTES = 150 * 1024 * 1024


def config():
    return {'configured': bool(secrets.get_key('tripo')), 'region': store.setting('tripo_region', 'cn'),
            'models': MODELS, 'defaults': DEFAULTS, 'api_version': 'v3',
            'verified': store.setting('tripo_verified', None)}


def save_config(data):
    if not isinstance(data, dict) or set(data) - {'key', 'clear_key', 'region'}:
        raise ValueError('Tripo 设置字段无效')
    region = data.get('region', store.setting('tripo_region', 'cn'))
    key = data.get('key', '')
    if not isinstance(region, str) or region not in BASES or not isinstance(key, str) or len(key) > 500 or any(c.isspace() for c in key):
        raise ValueError('Tripo 区域或 API Key 无效')
    if 'clear_key' in data and not isinstance(data['clear_key'], bool):
        raise ValueError('清除密钥选项无效')
    if key or data.get('clear_key'):
        secrets.save_key('tripo', '' if data.get('clear_key') else key)
        store.set_setting('tripo_verified', None)
    if region != store.setting('tripo_region', 'cn'):
        store.set_setting('tripo_verified', None)
    store.set_setting('tripo_region', region)
    return config()


async def request(region, method, path, **kwargs):
    key = secrets.get_key('tripo')
    if not key:
        raise ValueError('请先配置 Tripo API Key')
    async with httpx.AsyncClient(timeout=90, trust_env=False, follow_redirects=False) as client:
        response = await client.request(method, BASES[region] + path, headers={'Authorization': 'Bearer ' + key}, **kwargs)
    try:
        body = response.json()
    except ValueError:
        raise ValueError('Tripo 返回内容无法确认；请核对控制台，未自动重试') from None
    if not isinstance(body, dict) or response.is_error or body.get('code') != 0:
        code = body.get('code', 'unknown') if isinstance(body, dict) else 'unknown'
        raise ValueError(f'Tripo 请求未成功（HTTP {response.status_code}，code {str(code)[:40]}）；请检查 Key、区域、参数与 API 积分')
    if not isinstance(body.get('data'), dict):
        raise ValueError('Tripo 返回数据不完整；请核对控制台')
    return body['data']


async def balance():
    region = store.setting('tripo_region', 'cn')
    data = await request(region, 'GET', '/account/balance')
    result = {k: v for k in ('balance', 'frozen') if isinstance((v := data.get(k)), (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
    if 'balance' not in result:
        raise ValueError('Tripo 未返回可核验的 API 余额')
    store.set_setting('tripo_verified', {'region': region, 'checked_at': store.now()})
    return result


def validate(data):
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValueError('Tripo 方案包含未开放字段')
    spec = {**DEFAULTS, **data}
    for key, size in (('title', 100), ('prompt', 1024), ('source_asset_id', 64)):
        if not isinstance(spec[key], str) or len(spec[key]) > size:
            raise ValueError('Tripo 参数过长或类型无效：' + key)
    if not spec['title'].strip() or spec['mode'] not in ('text', 'image') or spec['model'] not in MODELS:
        raise ValueError('请选择有效的名称、生成方式与 Tripo 模型')
    if type(spec['face_limit']) is not int or not 500 <= spec['face_limit'] <= 100000 or type(spec['texture']) is not bool or type(spec['pbr']) is not bool:
        raise ValueError('面数需为 500–100000 的整数，贴图/PBR 需为开关')
    if spec['pbr'] and not spec['texture']:
        raise ValueError('开启 PBR 时需同时开启贴图')
    if spec['mode'] == 'text' and (not spec['prompt'].strip() or spec['source_asset_id']):
        raise ValueError('文生 3D 需填写提示词，不接受参考图')
    if spec['mode'] == 'image' and (not spec['source_asset_id'] or spec['prompt']):
        raise ValueError('图生 3D 需选择项目图片；当前接口仅使用图片，请将提示词留空')
    return spec


def source(pid, spec):
    a = assets.asset(spec['source_asset_id'])
    if a['project_id'] != pid or a['kind'] != 'image':
        raise ValueError('Tripo 参考图必须属于当前项目')
    path = assets.file_for(a)
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('Tripo 参考图需小于 20 MB')
    return path


def image_data(path):
    try:
        with Image.open(path) as im:
            if im.width * im.height > 33554432 or getattr(im, 'is_animated', False):
                raise ValueError('请选择 3200 万像素以内的静态参考图')
            buf = io.BytesIO()
            ImageOps.exif_transpose(im).convert('RGBA').save(buf, format='PNG')
    except (OSError, Image.DecompressionBombError):
        raise ValueError('参考图不是可读取的静态图片') from None
    raw = buf.getvalue()
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError('参考图转为 PNG 后超过 20 MB，请先缩小')
    return raw


def job(jid):
    value = store.one('SELECT * FROM tripo_jobs WHERE id=?', (jid,))
    if not value:
        raise ValueError('Tripo 方案不存在')
    return value


def jobs(pid):
    store.project(pid)
    return store.rows('SELECT * FROM tripo_jobs WHERE project_id=? ORDER BY created DESC,rowid DESC LIMIT 100', (pid,))


def draft(pid, data):
    store.project(pid)
    if not isinstance(data, dict): raise ValueError('Tripo 方案无效')
    spec = validate({'model': generation_models.selected(pid)['tripo'], **data})
    result = {'source_hash': assets.digest(source(pid, spec))} if spec['mode'] == 'image' else {}
    jid = store.uid()
    store.execute('INSERT INTO tripo_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                  (jid, pid, None, None, None, store.setting('tripo_region', 'cn'), json.dumps(spec, ensure_ascii=False), 'draft', '', json.dumps(result), store.now(), store.now()))
    return job(jid)


def update(jid, status, result, task_id=None):
    if task_id is None:
        store.execute('UPDATE tripo_jobs SET status=?,result=?,updated=? WHERE id=?', (status, json.dumps(result, ensure_ascii=False), store.now(), jid))
    else:
        store.execute('UPDATE tripo_jobs SET status=?,task_id=?,result=?,updated=? WHERE id=?', (status, task_id, json.dumps(result, ensure_ascii=False), store.now(), jid))


async def submit(jid, confirmed):
    if confirmed is not True:
        raise ValueError('请先审阅方案并确认本次 Tripo API 积分消耗与图片上传')
    j = job(jid)
    if not secrets.get_key('tripo'):
        raise ValueError('请先配置 Tripo API Key')
    spec, result = validate(json.loads(j['spec'])), json.loads(j['result'])
    raw = None
    if spec['mode'] == 'image':
        path = source(j['project_id'], spec)
        if assets.digest(path) != result.get('source_hash'):
            raise ValueError('参考图已变化，请重新保存并审阅方案')
        raw = image_data(path)
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute("UPDATE tripo_jobs SET status='submitting',updated=? WHERE id=? AND status='draft'", (store.now(), jid)).rowcount:
            raise ValueError('此方案已提交或结果待核对；禁止重复提交')
    rid = store.run_start(j['project_id'], 'tripo_submit', '提交用户已确认的 Tripo 方案', provider='tripo', model=spec['model'], agent='modeler')
    store.execute('UPDATE tripo_jobs SET run_id=? WHERE id=?', (rid, jid))
    status, task_id, attempted = 'draft', '', False
    try:
        payload = {k: spec[k] for k in ('model', 'face_limit', 'texture', 'pbr')}
        if raw is not None:
            uploaded = await request(j['region'], 'POST', '/files', files={'file': ('reference.png', raw, 'image/png')})
            token = uploaded.get('file_token')
            if not isinstance(token, str) or not re.fullmatch(r'file_[A-Za-z0-9_-]{1,200}', token):
                raise ValueError('Tripo 未确认图片上传，尚未提交生成')
            payload['input'] = token
        else:
            payload['prompt'] = spec['prompt']
        attempted = True
        created = await request(j['region'], 'POST', '/generation/' + ('image-to-model' if raw is not None else 'text-to-model'), json=payload)
        task_id = created.get('task_id', '')
        if not isinstance(task_id, str) or not TASK.fullmatch(task_id):
            task_id = ''
            raise ValueError('Tripo 未返回有效任务 ID')
        status = 'queued'
        result.update(message='已提交 Tripo，生成尚未完成', progress=0)
    except asyncio.CancelledError:
        status = 'unknown' if attempted else 'draft'
        result['message'] = '提交曾中断，请先在 Tripo 控制台核对任务；未自动重试'
        raise
    except Exception:
        status = 'unknown' if attempted else 'draft'
        result['message'] = '提交结果无法确认，请先在 Tripo 控制台核对；可手工关联已存在的 V3 任务，禁止直接重试' if attempted else '图片上传未确认，尚未提交生成；请检查图片与连接后重新确认'
    finally:
        update(jid, status, result, task_id)
        store.run_end(rid, 'completed' if status == 'queued' else 'interrupted' if status == 'unknown' else 'failed', result['message'])
    return job(jid)


async def query(j):
    if not TASK.fullmatch(j['task_id']):
        raise ValueError('暂无可查询的 Tripo V3 任务编号，请先核对提交结果')
    data = await request(j['region'], 'GET', '/tasks/' + j['task_id'])
    spec = json.loads(j['spec'])
    if data.get('task_id') != j['task_id'] or data.get('type') != ('text_to_model' if spec['mode'] == 'text' else 'image_to_model'):
        raise ValueError('Tripo 返回任务与当前方案不匹配')
    return data


def task_result(data, previous):
    status = data.get('status')
    if status not in ('queued', 'running', 'success', 'failed', 'cancelled'):
        raise ValueError('Tripo 返回了未识别的任务状态')
    result = dict(previous)
    progress = data.get('progress')
    result['progress'] = progress if type(progress) is int and 0 <= progress <= 100 else None
    result['message'] = {'queued': '任务排队中', 'running': 'Tripo 正在生成', 'success': '云端生成完成，等待下载并验收', 'failed': 'Tripo 任务失败，请在控制台核对原因与积分', 'cancelled': 'Tripo 任务已取消'}[status]
    credit = data.get('credits_consumed')
    if isinstance(credit, (int, float)) and not isinstance(credit, bool) and math.isfinite(credit):
        result['credits_consumed'] = credit
    output = data.get('output') or {}
    if not isinstance(output, dict):
        raise ValueError('Tripo 模型输出格式无效')
    result['has_model'] = isinstance(output.get('model_url'), str) and bool(output['model_url'])
    if status == 'success' and not result['has_model']:
        result['message'] = 'Tripo 声称生成成功，但未返回模型地址，请在控制台核对'
    return ('ready' if status == 'success' else status), result


async def poll(jid):
    j = job(jid)
    if j['status'] in ('submitting', 'importing'):
        raise ValueError('此方案正在提交或导入，请等待本次操作结束')
    data = await query(j)
    status, result = task_result(data, json.loads(j['result']))
    update(jid, 'imported' if j['model_id'] else status, result)
    return job(jid)


async def recover(jid, task_id, confirmed):
    j = job(jid)
    if confirmed is not True or j['status'] != 'unknown' or j['task_id'] or not isinstance(task_id, str) or not TASK.fullmatch(task_id):
        raise ValueError('仅能在核对控制台后，为结果未知的方案关联一个有效 V3 任务')
    data = await query({**j, 'task_id': task_id})
    status, result = task_result(data, json.loads(j['result']))
    with store.db() as c:
        if not c.execute("UPDATE tripo_jobs SET task_id=?,status=?,result=?,updated=? WHERE id=? AND status='unknown' AND task_id=''", (task_id, status, json.dumps(result), store.now(), jid)).rowcount:
            raise ValueError('任务关联已变化，请刷新后核对')
    return job(jid)


async def validate_download(url):
    if not isinstance(url, str) or len(url) > 16000:
        raise ValueError('模型下载地址无效')
    p = urlsplit(url)
    host = p.hostname or ''
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443) or not any(host == d or host.endswith('.' + d) for d in DOWNLOAD_DOMAINS):
        raise ValueError('仅接受 Tripo 或受支持的云存储 HTTPS 下载地址')
    addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('不允许从本机、私有网络或非公网地址获取模型')


async def download(url, target, maximum):
    await validate_download(url)
    total = 0
    async with httpx.AsyncClient(timeout=120, trust_env=False, follow_redirects=False) as client:
        async with client.stream('GET', url) as response:
            if response.status_code != 200:
                raise ValueError('模型下载未成功；请重新查询任务获取有效结果')
            if int(response.headers.get('content-length', '0')) > maximum:
                raise ValueError('Tripo 输出超过文件接入上限')
            with target.open('wb') as f:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > maximum:
                        raise ValueError('Tripo 输出超过文件接入上限')
                    f.write(chunk)


def verify_glb(path):
    raw = path.read_bytes()
    if len(raw) < 20 or struct.unpack('<III', raw[:12]) != (0x46546c67, 2, len(raw)):
        raise ValueError('Tripo 输出不是有效 GLB；本版未自动提交收费格式转换')
    size, kind = struct.unpack('<II', raw[12:20])
    if kind != 0x4e4f534a or size > len(raw) - 20:
        raise ValueError('GLB 场景清单无效')
    doc = json.loads(raw[20:20 + size])
    if not isinstance(doc, dict) or not doc.get('meshes') or any(v.get('uri') and not v['uri'].startswith('data:') for k in ('buffers', 'images') for v in doc.get(k, [])):
        raise ValueError('GLB 缺少网格或依赖未内嵌的外部文件')


async def import_model(jid):
    j = job(jid)
    folder = assets.inside(store.project_dir(j['project_id']) / 'tripo' / jid, store.project_dir(j['project_id']))
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute("UPDATE tripo_jobs SET status='importing',updated=? WHERE id=? AND status IN ('ready','restored') AND model_id IS NULL", (store.now(), jid)).rowcount:
            raise ValueError('请先查询成功的任务；模型已导入或正在导入时不能重复操作')
    result, success = json.loads(j['result']), False
    rid = store.run_start(j['project_id'], 'tripo_import', '下载并校验 Tripo 模型')
    try:
        data = await query(j)
        status, summary = task_result(data, result)
        if status != 'ready' or not summary['has_model']:
            raise ValueError('服务尚未确认生成完成或未返回模型')
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'model.part'
        await download(data['output']['model_url'], path, MAX_MODEL_BYTES)
        verify_glb(path)
        model = folder / 'model.glb'
        path.replace(model)
        files = [(model, 'model', '模型.glb')]
        if data['output'].get('rendered_image_url'):
            try:
                preview = folder / 'preview.part'
                await download(data['output']['rendered_image_url'], preview, 20 * 1024 * 1024)
                with Image.open(preview) as im:
                    if im.width * im.height > 33554432:
                        raise ValueError('预览图过大')
                    image = im.convert('RGB')
                    image.thumbnail((1536, 1536))
                    image.save(folder / 'preview.png')
                files.append((folder / 'preview.png', 'image', '预览.png'))
            except Exception:
                summary['preview_note'] = '预览图未能接入；GLB 模型仍可交互查看'
        title = json.loads(j['spec'])['title']
        ids = [store.uid() for _ in files]
        summary.update(hashes={p.name: assets.digest(p) for p, _, _ in files}, message='模型已纳入项目资产，尚未进行美术或引擎验收')
        with store.db() as c:
            for aid, (p, kind, label) in zip(ids, files):
                versions = json.dumps([{'path': str(p), 'label': 'Tripo V3 生成', 'created': store.now()}])
                c.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)', (aid, j['project_id'], title + ' · ' + label, str(p), str(p), kind, versions, store.now()))
            c.execute("UPDATE tripo_jobs SET status='imported',model_id=?,preview_id=?,result=?,updated=? WHERE id=?", (ids[0], ids[1] if len(ids) > 1 else None, json.dumps(summary, ensure_ascii=False), store.now(), jid))
        success = True
        return job(jid)
    except (asyncio.CancelledError, Exception) as exc:
        result['message'] = '模型导入未完成；可再次查询或下载，不会重新生成'
        update(jid, 'ready', result)
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise ValueError('模型下载或校验失败；请核对任务与网络，本次未发布部分资产') from None
    finally:
        for p in (folder / 'model.part', folder / 'preview.part'):
            p.unlink(missing_ok=True)
        store.run_end(rid, 'completed' if success else 'failed', 'Tripo 模型已纳入项目，等待验收' if success else 'Tripo 模型未导入，可重新查询或下载')
