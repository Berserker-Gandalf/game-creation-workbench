"""Local A1111-compatible API plus read-only model/output inventory."""
import asyncio
import hashlib
import io
import json
import math
import os
import re
import struct
import threading
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image

from . import assets, store

BUSY = False
IMPORT_LOCK = threading.Lock()
DEFAULTS = {'checkpoint': '', 'sampler': 'Euler a', 'width': 512, 'height': 512,
            'steps': 20, 'cfg_scale': 7, 'seed': -1, 'negative_prompt': '',
            'denoising_strength': 0.65, 'loras': []}
MODEL_TYPES = {'.safetensors', '.ckpt', '.pt'}
IMAGE_TYPES = {'.png', '.jpg', '.jpeg', '.webp'}


def config():
    saved = store.setting('webui_config', {})
    return {'root': saved.get('root', ''), 'url': saved.get('url', 'http://127.0.0.1:7860'),
            'defaults': {**DEFAULTS, **saved.get('defaults', {})}}


def root_path(value=None):
    value = config()['root'] if value is None else value
    if not value:
        raise ValueError('请先保存本机 WebUI 安装目录')
    path = Path(value).expanduser().resolve()
    if not (path / 'modules/api/api.py').is_file() or not (path / 'models').is_dir():
        raise ValueError('请选择包含 modules/api/api.py 和 models 的 WebUI 安装目录')
    return path


def local_url(value):
    if not isinstance(value, str):
        raise ValueError('无效的 WebUI 地址')
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment or (port is not None and not 1024 <= port <= 65535)):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('WebUI 地址仅允许本机 HTTP 根地址，例如 http://127.0.0.1:7860') from None
    return value.rstrip('/')


def parameters(data):
    if not isinstance(data, dict):
        raise ValueError('WebUI 参数必须为对象')
    result = {**DEFAULTS, **{k: data[k] for k in DEFAULTS if k in data}}
    for name, low, high in (('width', 64, 2048), ('height', 64, 2048), ('steps', 1, 100), ('seed', -1, 4294967295)):
        value = result[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError('无效的 WebUI 参数：' + name)
    if result['width'] % 8 or result['height'] % 8:
        raise ValueError('WebUI 宽高需为 8 的倍数')
    for name, low, high in (('cfg_scale', 1, 30), ('denoising_strength', 0, 1)):
        value = result[name]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('无效的 WebUI 参数：' + name)
    for name, length in (('checkpoint', 500), ('sampler', 100), ('negative_prompt', 30000)):
        if not isinstance(result[name], str) or len(result[name]) > length:
            raise ValueError('无效的 WebUI 参数：' + name)
    loras = result['loras']
    if not isinstance(loras, list) or len(loras) > 8:
        raise ValueError('单次最多选择 8 个 LoRA')
    seen = set()
    for item in loras:
        if not isinstance(item, dict) or set(item) != {'id', 'weight'} or not isinstance(item['id'], str):
            raise ValueError('LoRA 需包含 id 和 weight')
        weight = item['weight']
        if type(weight) not in (int, float) or not math.isfinite(weight) or not -2 <= weight <= 2 or item['id'] in seen:
            raise ValueError('LoRA 权重需在 -2 到 2 之间，且不能重复选择')
        seen.add(item['id'])
    return result


def save_config(data):
    current = config()
    path = root_path(str(data.get('root', current['root'])))
    value = {'root': str(path), 'url': local_url(data.get('url', current['url'])),
             'defaults': parameters(data.get('defaults', current['defaults']))}
    store.set_setting('webui_config', value)
    return value


def walk_files(folder, root, suffixes, limit=10000):
    if not folder.is_dir() or not folder.resolve().is_relative_to(root):
        return []
    found = []
    for base, dirs, names in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(base) / d).is_symlink())
        for name in sorted(names):
            path = Path(base) / name
            if not path.is_symlink() and path.suffix.lower() in suffixes and path.resolve().is_relative_to(root):
                found.append(path)
                if len(found) >= limit:
                    return found
    return found


def metadata(path):
    if path.suffix.lower() != '.safetensors':
        return {}
    try:
        with path.open('rb') as source:
            size = struct.unpack('<Q', source.read(8))[0]
            if size > 1024 * 1024:
                return {}
            value = json.loads(source.read(size)).get('__metadata__', {})
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, struct.error, AttributeError):
        return {}


def inventory(root, folder):
    result = []
    for path in walk_files(root / folder, root, MODEL_TYPES, 2000):
        info = metadata(path)
        result.append({'id': path.relative_to(root).as_posix(), 'name': path.stem, 'title': path.stem,
                       'bytes': path.stat().st_size, 'base_model': str(info.get('ss_base_model_version', info.get('modelspec.architecture', '')))[:200],
                       'alias': str(info.get('ss_output_name', path.stem))[:200], 'available': False})
    return result


async def catalog(live=True):
    cfg = config()
    if not cfg['root']:
        return {'configured': False, 'online': False, 'checkpoints': [], 'loras': [], 'samplers': [], 'message': '请先保存 WebUI 安装目录与地址'}
    root = root_path()
    checkpoints, loras = await asyncio.gather(asyncio.to_thread(inventory, root, 'models/Stable-diffusion'),
                                             asyncio.to_thread(inventory, root, 'models/Lora'))
    result = {'configured': True, 'online': False, 'checkpoints': checkpoints, 'loras': loras,
              'url': cfg['url'], 'samplers': [], 'current_checkpoint': '', 'message': '离线目录；生成需要启动 WebUI 并启用 --api'}
    if len(checkpoints) >= 2000 or len(loras) >= 2000:
        result['message'] += '；模型扫描已达 2000 项上限'
    if not live:
        return result
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            responses = await asyncio.gather(*(client.get(cfg['url'] + '/sdapi/v1/' + part) for part in ('options', 'sd-models', 'loras', 'samplers')))
        options, models, networks, samplers = responses
        if options.status_code in (401, 403):
            result['message'] = 'WebUI API 需要认证；本版尚未配置该认证，请勿关闭已有保护'
            return result
        for response in (options, models, samplers):
            response.raise_for_status()
        def merge(items, remote, path_key):
            by_id = {v['id']: v for v in items}
            for row in remote:
                try:
                    path = assets.inside(row[path_key], root)
                    item = by_id.get(path.relative_to(root).as_posix())
                    if item:
                        item.update(available=True, title=str(row.get('title', row.get('name', item['name']))),
                                    name=str(row.get('name', item['name'])), sha256=str(row.get('sha256', '')))
                except (ValueError, KeyError, TypeError):
                    continue
        merge(checkpoints, models.json(), 'filename')
        if networks.status_code == 200:
            merge(loras, networks.json(), 'path')
        result.update(online=True, current_checkpoint=options.json().get('sd_model_checkpoint', ''),
                      samplers=[v['name'] for v in samplers.json() if isinstance(v, dict) and isinstance(v.get('name'), str)],
                      message='API 已连接；选择模型仅对本次生成生效，不写入 WebUI 全局配置')
        if networks.status_code != 200:
            result['message'] += '；LoRA API 不可用，LoRA 离线列表仅供浏览'
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return result


async def refresh():
    if BUSY:
        raise ValueError('WebUI 正在生成，请等待后再刷新模型索引')
    cfg = config(); root_path()
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        for part in ('refresh-checkpoints', 'refresh-loras'):
            try:
                response = await client.post(cfg['url'] + '/sdapi/v1/' + part)
                response.raise_for_status()
            except httpx.HTTPError:
                raise ValueError('WebUI 目录刷新失败，请检查 API；没有自动下载或删除模型') from None
    return await catalog()


async def prepare(data, source=None, mask=None):
    cfg = config()
    chosen = parameters({**cfg['defaults'], **data})
    values = await catalog()
    if not values['online']:
        raise ValueError(values['message'])
    model = next((v for v in values['checkpoints'] if v['id'] == chosen['checkpoint'] and v['available']), None)
    if not model or chosen['sampler'] not in values['samplers']:
        raise ValueError('请选择当前 WebUI API 可用的模型和采样器')
    prompt = data['prompt']
    if re.search(r'<(?:lora|lyco|hypernet):', prompt + chosen['negative_prompt'], re.I):
        raise ValueError('请通过 LoRA 选择器添加网络，本版不开放手写额外网络标记')
    tags = []
    for item in chosen['loras']:
        network = next((v for v in values['loras'] if v['id'] == item['id'] and v['available']), None)
        if not network or re.search(r'[<>:\r\n]', network['name']):
            raise ValueError('LoRA 不在当前 WebUI 目录中或名称不受支持')
        tags.append(f"<lora:{network['name']}:{item['weight']:g}>")
    payload = {k: chosen[k] for k in ('width', 'height', 'steps', 'cfg_scale', 'seed', 'negative_prompt')}
    payload.update(prompt=' '.join([prompt, *tags]).strip(), sampler_name=chosen['sampler'], batch_size=1, n_iter=1,
                   save_images=False, send_images=True, override_settings={'sd_model_checkpoint': model['title']},
                   override_settings_restore_afterwards=True, restore_faces=False, enable_hr=False, alwayson_scripts={})
    if source:
        payload.update(init_images=[source], denoising_strength=chosen['denoising_strength'], include_init_images=False)
        if mask:
            payload['mask'] = mask
            payload.update(inpaint_full_res=False, inpainting_mask_invert=0)
    if (config()['root'], config()['url']) != (cfg['root'], cfg['url']):
        raise ValueError('WebUI 连接配置已变化，请重新检查后再提交')
    return payload, {**chosen, 'connection_url': cfg['url'], 'prompt': prompt, 'effective_prompt': payload['prompt'], 'checkpoint_title': model['title'], 'checkpoint_sha256': model.get('sha256', '')}


async def generate(payload, editing=False, url=None):
    global BUSY
    if BUSY:
        raise ValueError('工作台已有 WebUI 生成请求，请等待并核对结果')
    BUSY = True
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=10), trust_env=False) as client:
            response = await client.post((url or config()['url']) + '/sdapi/v1/' + ('img2img' if editing else 'txt2img'), json=payload)
        if response.is_error:
            raise ValueError(f'WebUI 请求失败（HTTP {response.status_code}），请在原生界面检查模型与显存；未自动重试')
        value = response.json()
        images = value.get('images', [])
        if not images or not isinstance(images[0], str):
            raise ValueError('WebUI 未返回图片，请先核对原生界面结果')
        raw_info = value.get('info', '{}')
        info = json.loads(raw_info) if isinstance(raw_info, str) else raw_info
        if not isinstance(info, dict):
            raise ValueError('WebUI 返回的生成信息无效，请核对原生结果')
        public = {k: info[k] for k in ('seed', 'all_seeds', 'sd_model_name', 'sd_model_hash', 'infotexts') if k in info}
        return {'data': [{'b64_json': images[0].split(',', 1)[-1]}], 'webui': public}
    except httpx.RequestError:
        raise ValueError('WebUI 连接中断或超时，远端可能仍在生成；请先核对结果，未自动重试') from None
    finally:
        BUSY = False


def output_roots(root):
    roots = {root / 'outputs', root / 'log/images'}
    try:
        options = json.loads((root / 'config.json').read_text(encoding='utf-8-sig'))
        for key, value in options.items():
            if key.startswith('outdir_') and isinstance(value, str) and value:
                path = (root / value).resolve()
                if path.is_relative_to(root) and path != root:
                    roots.add(path)
    except (OSError, ValueError):
        pass
    return [p.resolve() for p in roots if p.resolve().is_relative_to(root) and p.is_dir()]


def output_path(relative):
    root = root_path()
    path = assets.inside(root / relative, root)
    if path.suffix.lower() not in IMAGE_TYPES or not path.is_file() or not any(path.is_relative_to(p) for p in output_roots(root)):
        raise ValueError('只能读取已配置 WebUI 产出目录中的图片')
    if path.stat().st_size > 60 * 1024 * 1024:
        raise ValueError('产出图片超过 60 MB')
    return path


def version(path):
    stat = path.stat()
    return hashlib.sha256(f'{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()


def outputs(query='', offset=0, limit=48):
    root = root_path()
    paths = set()
    for folder in output_roots(root):
        paths.update(walk_files(folder, root, IMAGE_TYPES))
    filtered = sorted((p for p in paths if query.lower() in p.name.lower()), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    values = [{'path': p.relative_to(root).as_posix(), 'name': p.name, 'bytes': p.stat().st_size,
               'modified': p.stat().st_mtime, 'version': version(p)} for p in filtered[max(0, offset):max(0, offset) + max(1, min(limit, 100))]]
    return {'items': values, 'total': len(filtered), 'truncated': len(paths) >= 10000}


def preview(relative):
    with Image.open(output_path(relative)) as image:
        if image.width * image.height > 33554432:
            raise ValueError('产出图片像素过大')
        image.thumbnail((320, 320)); image = image.convert('RGB')
        output = io.BytesIO(); image.save(output, 'JPEG')
        return output.getvalue()


def import_output(pid, data):
    with IMPORT_LOCK:
        return _import_output(pid, data)


def _import_output(pid, data):
    store.project(pid)
    path = output_path(data.get('path', ''))
    if data.get('version') != version(path):
        raise ValueError('WebUI 产出已变化，请刷新列表后再导入')
    raw = path.read_bytes()
    if data['version'] != version(path):
        raise ValueError('WebUI 产出正在变化，请稍后重新读取')
    fingerprint = hashlib.sha256(raw).hexdigest()
    source = 'webui-output:' + hashlib.sha256(str(root_path()).encode()).hexdigest()[:16] + ':' + data['path'] + ':' + fingerprint
    existing = store.one('SELECT * FROM assets WHERE project_id=? AND source=?', (pid, source))
    if existing:
        return {'asset': existing, 'existing': True}
    with Image.open(io.BytesIO(raw)) as image:
        if image.width * image.height > 33554432:
            raise ValueError('产出图片像素过大')
        result = {'width': image.width, 'height': image.height, 'sha256': fingerprint, 'infotext': str(image.info.get('parameters', ''))[:100000]}
        image.verify()
    dest = store.project_dir(pid) / 'assets' / (store.uid() + path.suffix.lower())
    dest.parent.mkdir(exist_ok=True)
    dest.write_bytes(raw)
    a = assets.register(pid, dest, source)
    store.execute('UPDATE assets SET name=? WHERE id=?', (path.name, a['id']))
    rid = store.run_start(pid, 'webui_import', '导入 WebUI 产出：' + path.name, provider='webui')
    now = store.now()
    store.execute('INSERT INTO art_jobs VALUES (?,?,?,?,?,?,?,?,?,?)', (store.uid(), pid, rid, a['id'], 'webui-import', json.dumps({'source_path': data['path']}), 'completed', json.dumps(result, ensure_ascii=False), now, now))
    store.run_end(rid, 'completed', 'WebUI 产出已复制到项目；原文件保留')
    return {'asset': assets.asset(a['id']), 'existing': False}
