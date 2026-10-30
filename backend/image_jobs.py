"""One generation request per action; never retry an ambiguous result."""
import asyncio
import base64
import io
import json

import httpx
from PIL import Image, ImageOps, PngImagePlugin

from . import assets, providers, store, webui

ACTIVE = set()


def input_image(a, mask=False):
    path = assets.file_for(a)
    if a['kind'] != 'image' or path.stat().st_size > 12 * 1024 * 1024:
        raise ValueError('请选择 12 MB 以内的图片资产')
    with Image.open(path) as image:
        if image.width * image.height > 33554432 or getattr(image, 'is_animated', False):
            raise ValueError('AI 编辑支持 3200 万像素以内的静态图片')
        if mask and (image.format != 'PNG' or 'A' not in image.getbands() or image.getchannel('A').getextrema()[0] != 0):
            raise ValueError('遮罩必须为含透明区域的 PNG；完全透明部分表示希望编辑的区域')
        image = ImageOps.exif_transpose(image).convert('RGBA')
        size = image.size
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
    raw = buffer.getvalue()
    if len(raw) > 12 * 1024 * 1024:
        raise ValueError('图片转换为 PNG 后超过 12 MB，请先缩小')
    return 'data:image/png;base64,' + base64.b64encode(raw).decode(), size


def save_result(pid, result):
    items = result.get('data', [])
    encoded = items[0].get('b64_json') if items else None
    if not isinstance(encoded, str) or len(encoded) > 80 * 1024 * 1024:
        raise ValueError('供应商未返回可接受的图片二进制；未下载远程 URL')
    try:
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 33554432:
                raise ValueError('返回图片尺寸过大')
            image.load()
            image = image.convert('RGBA')
    except (OSError, ValueError) as exc:
        raise ValueError('供应商返回的图片无效或过大') from exc
    path = store.project_dir(pid) / 'assets' / (store.uid() + '.png')
    path.parent.mkdir(exist_ok=True)
    pnginfo = PngImagePlugin.PngInfo()
    info = result.get('webui', {}).get('infotexts', [])
    if info:
        pnginfo.add_text('parameters', str(info[0])[:100000])
    image.save(path, pnginfo=pnginfo)
    return path


def draft(pid, data):
    store.project(pid)
    if set(data) - {'title', 'prompt', 'provider', 'width', 'height', 'negative_prompt'}: raise ValueError('美术草稿仅接受名称、提示词、来源、尺寸及负面提示词')
    if not isinstance(data.get('title', ''), str) or len(data.get('title', '')) > 100: raise ValueError('美术方案名称过长')
    prompt, provider = data.get('prompt', ''), data.get('provider', 'webui')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 30000 or provider not in ('openai', 'webui'): raise ValueError('美术需求或来源无效')
    if not isinstance(data.get('negative_prompt', ''), str) or len(data.get('negative_prompt', '')) > 8000: raise ValueError('负面提示词过长')
    for k in ('width', 'height'):
        if type(data.get(k, 512)) is not int or not 256 <= data.get(k, 512) <= 2048 or data.get(k, 512) % 64: raise ValueError('尺寸需为256–2048之间的64倍数')
    spec = {**data, 'prompt': prompt.strip(), 'model': store.setting('image_model', '') if provider == 'openai' else ''}
    jid, now = store.uid(), store.now()
    store.execute('INSERT INTO art_jobs VALUES (?,?,?,?,?,?,?,?,?,?)', (jid, pid, None, None, provider, json.dumps(spec, ensure_ascii=False), 'draft', '{}', now, now))
    return store.one('SELECT * FROM art_jobs WHERE id=?', (jid,))


async def run(pid, data, aid=None, draft_id=None):
    store.project(pid)
    prompt = str(data.get('prompt', '')).strip()
    provider = data.get('provider', 'openai')
    if provider not in ('openai', 'webui'):
        raise ValueError('不支持的绘画来源')
    model = store.setting('image_model', '')
    if draft_id:
        pending = store.one('SELECT * FROM art_jobs WHERE id=? AND project_id=?', (draft_id, pid))
        if not pending or pending['status'] != 'draft': raise ValueError('方案已执行或结果待核对，不能重复提交')
        model = json.loads(pending['spec']).get('model') or model
    if not prompt or len(prompt) > 30000 or (provider == 'openai' and not model):
        raise ValueError('请填写图片需求，并在连接设置中指定图像模型 ID')
    if pid in ACTIVE:
        raise ValueError('此项目已有图片请求进行中，请等待其结果后再提交')
    a, expected = None, data.get('expected_hash')
    source = mask_url = None
    payload = {'model': model, 'prompt': prompt, 'n': 1, 'size': '1024x1024', 'output_format': 'png'}
    if aid:
        a = assets.asset(aid)
        if a['project_id'] != pid or not expected or assets.digest(assets.file_for(a)) != expected:
            raise ValueError('图片不属于此项目或版本已变化，请刷新后重试')
        source, size = input_image(a)
        payload['images'] = [{'image_url': source}]
        if data.get('mask_asset_id'):
            mask = assets.asset(data['mask_asset_id'])
            if mask['project_id'] != pid:
                raise ValueError('遮罩必须属于同一项目')
            mask_url, mask_size = input_image(mask, mask=True)
            if size != mask_size:
                raise ValueError('遮罩与原图的尺寸必须一致')
            payload['mask'] = {'image_url': mask_url}
    spec = {'prompt': prompt, 'model': model}
    if provider == 'webui':
        mask_image = None
        if mask_url:
            with Image.open(io.BytesIO(base64.b64decode(mask_url.split(',', 1)[1]))) as mask:
                buffer = io.BytesIO()
                ImageOps.invert(mask.getchannel('A')).save(buffer, 'PNG')
                mask_image = base64.b64encode(buffer.getvalue()).decode()
        payload, spec = await webui.prepare({**data, 'prompt': prompt}, source, mask_image)
        model = spec['checkpoint_title']
    if pid in ACTIVE:
        raise ValueError('此项目已有图片请求进行中，请等待其结果后再提交')
    spec.update(source_asset_id=aid, mask_asset_id=data.get('mask_asset_id'), expected_hash=expected)
    if draft_id: spec['title'] = json.loads(pending['spec']).get('title', '美术方案')
    rid = store.run_start(pid, 'image_ai_edit' if aid else 'image_generation', prompt[:150], provider=provider, model=model)
    jid, now = draft_id or store.uid(), store.now()
    if draft_id:
        with store.db() as c:
            changed = c.execute("UPDATE art_jobs SET run_id=?,spec=?,status='running',updated=? WHERE id=? AND status='draft'", (rid, json.dumps(spec, ensure_ascii=False), now, jid)).rowcount
        if not changed:
            store.run_end(rid, 'cancelled', '方案已处理，本次未发出生成请求')
            raise ValueError('此方案已在处理，不能重复提交')
    else:
        store.execute('INSERT INTO art_jobs VALUES (?,?,?,?,?,?,?,?,?,?)', (jid, pid, rid, None, provider, json.dumps(spec, ensure_ascii=False), 'running', '{}', now, now))
    ACTIVE.add(pid)
    try:
        if provider == 'webui':
            result = await webui.generate(payload, bool(aid), spec['connection_url'])
        else:
            base, key = providers.config('openai')
            async with httpx.AsyncClient(timeout=httpx.Timeout(240, connect=20)) as client:
                response = await client.post(base + ('/images/edits' if aid else '/images/generations'),
                                             headers={'Authorization': 'Bearer ' + key}, json=payload)
            providers.check(response)
            result = response.json()
        path = save_result(pid, result)
        applied = False
        # A long request must not replace a version selected or edited in the meantime.
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            current = c.execute('SELECT * FROM assets WHERE id=?', (aid,)).fetchone() if aid else None
            if current and current['active'] == a['active'] and assets.digest(assets.file_for(dict(current))) == expected:
                versions = json.loads(current['versions'])
                versions.append({'path': str(path), 'label': 'AI 编辑 · ' + prompt[:60], 'created': store.now()})
                c.execute('UPDATE assets SET active=?,versions=? WHERE id=?', (str(path), json.dumps(versions), aid))
                applied = True
        if applied:
            output = assets.asset(aid)
            note = 'AI 编辑已保存新版本，原图保留；请人工验收'
        else:
            output = assets.register(pid, path)
            name = ('AI 编辑候选 · ' if aid else 'AI 美术 · ') + prompt[:40]
            store.execute('UPDATE assets SET name=? WHERE id=?', (name, output['id']))
            output = assets.asset(output['id'])
            note = '原图版本已变化，结果保存为独立候选，请比较后采用' if aid else '图像文件已保存，等待人工验收'
        store.execute('UPDATE art_jobs SET asset_id=?,status=?,result=?,updated=? WHERE id=?', (output['id'], 'completed', json.dumps(result.get('webui', {'usage': result.get('usage')}), ensure_ascii=False), store.now(), jid))
        store.run_end(rid, 'completed', note, result.get('usage'))
        return {'asset': output, 'applied': applied, 'note': note}
    except (Exception, asyncio.CancelledError) as exc:
        store.execute('UPDATE art_jobs SET status=?,result=?,updated=? WHERE id=?', ('interrupted' if isinstance(exc, asyncio.CancelledError) else 'failed', json.dumps({'message': '请求未确认，请先核对产出，未自动重试'}), store.now(), jid))
        store.run_end(rid, 'interrupted' if isinstance(exc, asyncio.CancelledError) else 'failed',
                      '未确认图片交付；请先核对供应商记录，不要盲目重试')
        if isinstance(exc, httpx.RequestError):
            raise ValueError('图片请求连接异常，交付状态尚未确认；请先核对供应商记录，未自动重试') from None
        raise
    finally:
        ACTIVE.discard(pid)
