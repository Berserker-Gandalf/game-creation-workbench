import hashlib
import json
import array
import wave
from pathlib import Path
from PIL import Image, ImageOps
from . import store

KINDS = {'.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.webp': 'image',
         '.gif': 'image', '.wav': 'audio', '.mp3': 'audio', '.ogg': 'audio',
         '.glb': 'model', '.blend': 'blender', '.fbx': 'native', '.uasset': 'native', '.prefab': 'native',
         '.mat': 'native', '.unity': 'native', '.umap': 'native', '.asset': 'native',
         '.obj': 'source', '.gltf': 'source', '.tga': 'source', '.psd': 'source', '.tif': 'source',
         '.tiff': 'source', '.exr': 'source', '.anim': 'source', '.controller': 'source',
         '.aiff': 'source', '.flac': 'audio', '.bmp': 'image'}


def inside(path, root):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(Path(root).resolve()):
        raise ValueError('路径超出项目范围')
    return resolved


def asset(asset_id):
    a = store.one('SELECT * FROM assets WHERE id=?', (asset_id,))
    if not a:
        raise ValueError('资产不存在')
    return a


def file_for(a):
    path = authorized_path(a['project_id'], a['active'])
    if not path.is_file():
        raise ValueError('资产文件不存在，可能已移动')
    return path


def authorized_path(pid, value):
    from . import intake
    path = Path(value).resolve()
    roots = [Path(r['path']).resolve() for r in intake.source_roots(pid)] + [store.project_dir(pid).resolve()]
    if not any(path.is_relative_to(root) for root in roots): raise ValueError('资产路径不在授权目录')
    return path


def register(project_id, path, source=None):
    path = Path(path).resolve()
    kind = KINDS.get(path.suffix.lower())
    if not kind:
        raise ValueError('暂不支持此资产格式')
    source = str(source or path)
    existing = store.one('SELECT * FROM assets WHERE project_id=? AND source=?', (project_id, source))
    if existing:
        return existing
    aid = store.uid()
    versions = [{'path': str(path), 'label': '原始版本', 'created': store.now()}]
    store.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)',
                  (aid, project_id, path.name, source, str(path), kind, json.dumps(versions), store.now()))
    return asset(aid)


def scan(project_id):
    p = store.project(project_id)
    root = Path(p['root'])
    scan_root = root / ('Content' if p['engine'] == 'unreal' else 'Assets')
    scan_root = scan_root if scan_root.exists() else root
    count = 0
    skipped = {'.git', 'node_modules', 'Library', 'Temp', 'Binaries', 'Intermediate', 'Saved', '.workbench', '.venv'}
    import os
    for folder, dirs, files in os.walk(scan_root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in skipped and not (Path(folder) / d).is_symlink()]
        for name in files:
            path = Path(folder) / name
            if path.suffix.lower() in KINDS and not path.is_symlink():
                inside(path, root)
                register(project_id, path)
                count += 1
                if count >= 3000:
                    return {'count': count, 'truncated': True}
    return {'count': count, 'truncated': False}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def edit_image(aid, changes):
    a = asset(aid)
    if a['kind'] != 'image':
        raise ValueError('仅图片支持此编辑操作')
    src = file_for(a)
    expected = changes.get('expected_hash')
    if not expected or expected != digest(src):
        raise ValueError('图片已变化，请刷新预览后再编辑')
    with Image.open(src) as image:
        image = ImageOps.exif_transpose(image).convert('RGBA')
        if changes.get('crop'):
            x, y, w, h = changes['crop']
            if x < 0 or y < 0 or w < 1 or h < 1 or x + w > image.width or y + h > image.height:
                raise ValueError('裁剪范围超出图片')
            image = image.crop((x, y, x + w, y + h))
        if changes.get('width') or changes.get('height'):
            w, h = int(changes.get('width') or image.width), int(changes.get('height') or image.height)
            if not (1 <= w <= 8192 and 1 <= h <= 8192 and w * h <= 33554432):
                raise ValueError('图片尺寸超出允许范围')
            image = image.resize((w, h), Image.Resampling.LANCZOS)
        if changes.get('flip'):
            image = ImageOps.mirror(image)
        dest = store.project_dir(a['project_id']) / 'assets' / (store.uid() + '.png')
        dest.parent.mkdir(exist_ok=True)
        image.save(dest)
    return add_version(a, dest, '图片编辑')


def add_version(a, path, label):
    versions = json.loads(a['versions'])
    versions.append({'path': str(path), 'label': label, 'created': store.now()})
    store.execute('UPDATE assets SET active=?, versions=? WHERE id=?', (str(path), json.dumps(versions), a['id']))
    return asset(a['id'])


def restore(aid, index):
    a = asset(aid)
    versions = json.loads(a['versions'])
    if not 0 <= index < len(versions):
        raise ValueError('版本不存在')
    store.execute('UPDATE assets SET active=? WHERE id=?', (versions[index]['path'], aid))
    file_for(asset(aid))
    return asset(aid)


def edit_audio(aid, changes):
    a = asset(aid)
    src = file_for(a)
    if src.suffix.lower() != '.wav' or changes.get('expected_hash') != digest(src):
        raise ValueError('音频仅支持未变化的 PCM WAV，请刷新后重试')
    with wave.open(str(src), 'rb') as audio:
        params = audio.getparams()
        if params.sampwidth != 2 or params.comptype != 'NONE':
            raise ValueError('此版支持 16 位 PCM WAV，其他格式可试听但需先转换才能编辑')
        duration = params.nframes / params.framerate
        start, end = float(changes.get('start', 0)), float(changes.get('end', duration))
        if not 0 <= start < end <= duration:
            raise ValueError('裁剪时间超出音频范围')
        audio.setpos(int(start * params.framerate))
        raw = audio.readframes(int((end - start) * params.framerate))
    samples = array.array('h', raw)
    fade = min(int(0.05 * params.framerate) * params.nchannels, len(samples) // 2)
    if changes.get('fade', True):
        for i in range(fade):
            samples[i] = int(samples[i] * i / max(fade, 1))
            samples[-i - 1] = int(samples[-i - 1] * i / max(fade, 1))
    dest = store.project_dir(a['project_id']) / 'assets' / (store.uid() + '.wav')
    dest.parent.mkdir(exist_ok=True)
    with wave.open(str(dest), 'wb') as audio:
        audio.setparams(params)
        audio.writeframes(samples.tobytes())
    return add_version(a, dest, f'音频裁剪 {start:.2f}–{end:.2f}s')
