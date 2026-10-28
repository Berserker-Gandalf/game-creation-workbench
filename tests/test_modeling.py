import asyncio
import io
import json
import struct
import zipfile

import pytest
from PIL import Image

from backend import agent_tools, modeling, store
from test_workbench import client, project, image_bytes


def test_character_drafts_validate_parameters_and_reference_scope(client):
    p, other = project(client), project(client)
    url = f"/api/projects/{p['id']}/characters"
    for invalid in ({'height': True}, {'height': 99}, {'head_ratio': .3, 'leg_ratio': .55},
                    {'skin_color': 'red'}, {'python': 'print(1)'}, {'style': 'sculpt'}, {'height': '1.8'},
                    [], {'spec': {}, 'python': 'print(1)'}, {'spec': {}, 'parent_id': {}}):
        assert client.post(url, json=invalid).status_code == 400
    a = client.post(f"/api/projects/{other['id']}/upload", files={'file': ('ref.png', image_bytes())}).json()['asset']
    assert client.post(url, json={'reference_asset_id': a['id']}).status_code == 400
    draft = client.post(url, json={'title': '低模探索者'}).json()
    assert draft['status'] == 'draft' and json.loads(draft['spec'])['height'] == 1.7
    assert not store.rows('SELECT * FROM assets WHERE project_id=?', (p['id'],))
    assert client.post('/api/characters/' + draft['id'] + '/build', json={'confirmed': False}).status_code == 400


def test_modeler_tools_and_chat_keep_shell_disabled(client, monkeypatch):
    from backend import app as module
    p = project(client)
    scope = {'pid': p['id'], 'agent': 'modeler', 'write': True}
    draft = asyncio.run(agent_tools.invoke(scope, 'draft_character', dict(modeling.DEFAULTS)))
    assert draft['status'] == 'draft'
    for agent, write in [('music', True), ('modeler', False)]:
        with pytest.raises(ValueError):
            asyncio.run(agent_tools.invoke({**scope, 'agent': agent, 'write': write}, 'draft_character', dict(modeling.DEFAULTS)))
    assert 'edit_image' not in {t['name'] for t in agent_tools.definitions(True, 'modeler')}
    captured = []
    async def stream(root, prompt, model, allow_write, bridge, image, **kw):
        captured.append((allow_write, kw))
        yield {'event': 'delta', 'text': '方案尚未在 Blender 执行'}
    async def resolve(model): return 'fixture'
    monkeypatch.setattr(module.codex.client, 'stream', stream)
    monkeypatch.setattr(module.codex.client, 'resolve_model', resolve)
    r = client.post(f"/api/projects/{p['id']}/chat", json={'agent': 'modeler', 'provider': 'codex', 'execute': True, 'message': '设计一个角色'})
    assert '"event": "done"' in r.text and captured[0][0] is False
    assert 'draft_character' in captured[0][1]['allowed_tools']
    assert client.get(f"/api/projects/{p['id']}/conversations?agent=modeler").json()[0]['agent'] == 'modeler'


def outputs(folder, valid=True):
    (folder / 'character.blend').write_bytes(b'BLENDER-v500' + b'fixture')
    doc = json.dumps({'asset': {'version': '2.0'}, 'meshes': [{'primitives': [{}]}]}).encode()
    doc += b' ' * (-len(doc) % 4)
    raw = struct.pack('<III', 0x46546c67, 2, 20 + len(doc)) + struct.pack('<II', len(doc), 0x4e4f534a) + doc
    (folder / 'character.glb').write_bytes(raw if valid else b'invalid')
    Image.new('RGB', (512, 512), 'gray').save(folder / 'preview.png')
    (folder / 'build.json').write_text(json.dumps({'blender': 'fixture', 'objects': 12, 'triangles': 500, 'rigged': False}), encoding='utf-8')


def test_worker_publication_failure_and_backup_remap(client, monkeypatch):
    p = project(client)
    monkeypatch.setattr(modeling, 'executable', lambda: 'fixture-blender')
    async def render(exe, folder, control): outputs(folder)
    monkeypatch.setattr(modeling, 'render', render)
    async def build():
        job = modeling.draft(p['id'], {'title': '原始版本'})
        await modeling.start(job['id'], True)
        with pytest.raises(ValueError): await modeling.start(job['id'], True)
        await modeling.RUNNING[job['id']]['task']
        return modeling.job(job['id'])
    result = asyncio.run(build())
    assert result['status'] == 'review'
    assert {a['kind'] for a in store.rows('SELECT * FROM assets')} == {'model', 'blender', 'image'}
    parent = modeling.draft(p['id'], {'title': '调整比例'}, result['id'])
    raw = client.get(f"/api/projects/{p['id']}/export").content
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert json.loads(z.read('project.json'))['format'] == 10
    restored = client.post('/api/import-project', files={'file': ('backup.zip', raw)}).json()
    copied = modeling.jobs(restored['id'])
    copied_parent = next(j for j in copied if json.loads(j['spec'])['title'] == '调整比例')
    copied_result = next(j for j in copied if j['status'] == 'review')
    assert copied_parent['parent_id'] == copied_result['id'] != result['id']
    assert copied_result['model_id'] != result['model_id']
    async def bad_render(exe, folder, control): outputs(folder, False)
    monkeypatch.setattr(modeling, 'render', bad_render)
    async def fail():
        await modeling.start(parent['id'], True)
        await modeling.RUNNING[parent['id']]['task']
    asyncio.run(fail())
    assert modeling.job(parent['id'])['status'] == 'failed'
    assert len(store.rows('SELECT * FROM assets WHERE project_id=?', (p['id'],))) == 3


def test_character_cancel_and_stale_reference(client, monkeypatch):
    p = project(client)
    monkeypatch.setattr(modeling, 'executable', lambda: 'fixture-blender')
    a = client.post(f"/api/projects/{p['id']}/upload", files={'file': ('ref.png', image_bytes())}).json()['asset']
    job = modeling.draft(p['id'], {'reference_asset_id': a['id']})
    from pathlib import Path
    Path(a['active']).write_bytes(image_bytes() + b'changed')
    with pytest.raises(ValueError, match='参考图'):
        asyncio.run(modeling.start(job['id'], True))
    async def render(exe, folder, control):
        await asyncio.sleep(.01)
        outputs(folder)
    monkeypatch.setattr(modeling, 'render', render)
    async def cancel():
        j = modeling.draft(p['id'], {})
        await modeling.start(j['id'], True)
        task = modeling.RUNNING[j['id']]['task']
        modeling.cancel(j['id'])
        await task
        return modeling.job(j['id'])
    cancelled = asyncio.run(cancel())
    assert cancelled['status'] == 'interrupted' and cancelled['model_id'] is None


def test_character_timeout_shutdown_and_restart_preserve_data(client, monkeypatch):
    p = project(client)
    monkeypatch.setattr(modeling, 'executable', lambda: 'fixture-blender')
    async def timeout(exe, folder, control): raise TimeoutError()
    monkeypatch.setattr(modeling, 'render', timeout)
    async def fail():
        j = modeling.draft(p['id'], {})
        await modeling.start(j['id'], True)
        await modeling.RUNNING[j['id']]['task']
        return modeling.job(j['id'])
    j = asyncio.run(fail())
    assert j['status'] == 'failed' and '3 分钟' in json.loads(j['result'])['error']
    async def terminated(exe, folder, control):
        await asyncio.sleep(.01)
        raise ValueError('Blender process terminated')
    monkeypatch.setattr(modeling, 'render', terminated)
    async def stop():
        j = modeling.draft(p['id'], {})
        await modeling.start(j['id'], True)
        await asyncio.sleep(0)
        await modeling.shutdown()
        return modeling.job(j['id'])
    stopped = asyncio.run(stop())
    assert stopped['status'] == 'interrupted' and not modeling.RUNNING
    store.execute("UPDATE character_jobs SET status='building' WHERE id=?", (stopped['id'],))
    store.init()
    assert modeling.job(stopped['id'])['status'] == 'interrupted'
    assert store.project(p['id']) and not store.rows('SELECT * FROM assets')
