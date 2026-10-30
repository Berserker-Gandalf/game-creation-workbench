import asyncio
import io
import json
import struct
import zipfile

import httpx
import pytest

from backend import agent_tools, assets, store, tripo
from test_workbench import client, project, image_bytes


def plan(client, pid, **extra):
    r = client.post(f'/api/projects/{pid}/tripo', json={'title': '低模探索者', 'mode': 'text', 'prompt': 'A low-poly explorer with a blue coat', **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_tripo_plan_permissions_and_validation(client):
    p, other = project(client), project(client)
    url = f"/api/projects/{p['id']}/tripo"
    for args in ({'mode': 'text', 'prompt': ''}, {'face_limit': True}, {'face_limit': 9999999}, {'model': 'unknown'}, {'source_asset_id': '../private'}, {'url': 'http://localhost'}, []):
        assert client.post(url, json=args).status_code == 400
    a = client.post(f"/api/projects/{other['id']}/upload", files={'file': ('ref.png', image_bytes())}).json()['asset']
    assert client.post(url, json={'title': '图生', 'mode': 'image', 'prompt': '', 'source_asset_id': a['id']}).status_code == 400
    scope = {'pid': p['id'], 'agent': 'modeler', 'write': True}
    spec = {**tripo.DEFAULTS, 'prompt': 'A robot'}
    j = asyncio.run(agent_tools.invoke(scope, 'draft_tripo', spec))
    assert j['status'] == 'draft' and not j['task_id']
    for agent, write in [('music', True), ('modeler', False)]:
        with pytest.raises(ValueError):
            asyncio.run(agent_tools.invoke({**scope, 'agent': agent, 'write': write}, 'draft_tripo', spec))
    assert client.post('/api/tripo/jobs/' + j['id'] + '/submit', json={'confirmed': False}).status_code == 400


def test_tripo_submit_once_query_and_region_are_bound(client, monkeypatch):
    p = project(client)
    monkeypatch.setattr(tripo.secrets, 'get_key', lambda name: 'fixture-key')
    requests = []
    async def request(region, method, path, **kw):
        requests.append((region, method, path, kw))
        if method == 'POST': return {'task_id': 'task_fixture1'}
        return {'task_id': 'task_fixture1', 'type': 'text_to_model', 'status': 'success', 'progress': 100,
                'output': {'model_url': 'https://cdn.tripo3d.ai/model.glb?signature=PRIVATE_URL_CAPABILITY'}, 'credits_consumed': 20}
    monkeypatch.setattr(tripo, 'request', request)
    j = plan(client, p['id'])
    r = client.post('/api/tripo/jobs/' + j['id'] + '/submit', json={'confirmed': True})
    assert r.status_code == 200 and r.json()['task_id'] == 'task_fixture1'
    assert client.post('/api/tripo/jobs/' + j['id'] + '/submit', json={'confirmed': True}).status_code == 400
    store.set_setting('tripo_region', 'global')
    polled = client.post('/api/tripo/jobs/' + j['id'] + '/refresh').json()
    assert polled['status'] == 'ready' and json.loads(polled['result'])['credits_consumed'] == 20
    assert requests[0][0] == requests[-1][0] == 'cn'
    assert requests[0][3]['json']['model'] == tripo.DEFAULTS['model']
    assert 'PRIVATE_URL_CAPABILITY' not in json.dumps(polled)


def test_tripo_ambiguous_submit_recover_and_restart(client, monkeypatch):
    p = project(client)
    monkeypatch.setattr(tripo.secrets, 'get_key', lambda name: 'fixture-key')
    calls = []
    async def timeout(region, method, path, **kw):
        calls.append(path)
        raise httpx.ReadTimeout('uncertain')
    monkeypatch.setattr(tripo, 'request', timeout)
    j = plan(client, p['id'])
    result = client.post('/api/tripo/jobs/' + j['id'] + '/submit', json={'confirmed': True}).json()
    assert result['status'] == 'unknown' and len(calls) == 1
    assert client.post('/api/tripo/jobs/' + j['id'] + '/submit', json={'confirmed': True}).status_code == 400
    raw = client.get(f"/api/projects/{p['id']}/export").content
    copied = client.post('/api/import-project', files={'file': ('unknown.zip', raw)}).json()
    restored = tripo.jobs(copied['id'])[0]
    assert restored['status'] == 'unknown' and not restored['task_id']
    assert client.post('/api/tripo/jobs/' + restored['id'] + '/submit', json={'confirmed': True}).status_code == 400
    async def recover(region, method, path, **kw):
        assert method == 'GET'
        return {'task_id': 'task_recovered', 'type': 'text_to_model', 'status': 'running', 'progress': 33}
    monkeypatch.setattr(tripo, 'request', recover)
    r = client.post('/api/tripo/jobs/' + j['id'] + '/recover', json={'task_id': 'task_recovered', 'confirmed': True})
    assert r.status_code == 200 and r.json()['status'] == 'running'
    store.execute("UPDATE tripo_jobs SET status='submitting' WHERE id=?", (j['id'],))
    store.init()
    assert tripo.job(j['id'])['status'] == 'unknown'


def test_image_upload_is_explicit_and_rejects_stale_reference(client, monkeypatch):
    p = project(client)
    monkeypatch.setattr(tripo.secrets, 'get_key', lambda name: 'fixture-key')
    a = client.post(f"/api/projects/{p['id']}/upload", files={'file': ('ref.png', image_bytes())}).json()['asset']
    j = plan(client, p['id'], mode='image', prompt='', source_asset_id=a['id'])
    calls = []
    async def request(region, method, path, **kw):
        calls.append(path)
        if path == '/files':
            assert kw['files']['file'][2] == 'image/png'
            return {'file_token': 'file_fixture'}
        assert kw['json']['input'] == 'file_fixture' and 'prompt' not in kw['json']
        return {'task_id': 'task_image'}
    monkeypatch.setattr(tripo, 'request', request)
    assert not calls
    r = client.post('/api/tripo/jobs/' + j['id'] + '/submit', json={'confirmed': True})
    assert r.json()['status'] == 'queued' and calls == ['/files', '/generation/image-to-model']
    stale = plan(client, p['id'], mode='image', prompt='', source_asset_id=a['id'])
    client.post('/api/assets/' + a['id'] + '/edit', json={'expected_hash': assets.digest(assets.file_for(a)), 'width': 12})
    assert client.post('/api/tripo/jobs/' + stale['id'] + '/submit', json={'confirmed': True}).status_code == 400
    assert len(calls) == 2


def glb_bytes():
    doc = json.dumps({'asset': {'version': '2.0'}, 'meshes': [{'primitives': [{}]}]}).encode()
    doc += b' ' * (-len(doc) % 4)
    return struct.pack('<III', 0x46546c67, 2, 20 + len(doc)) + struct.pack('<II', len(doc), 0x4e4f534a) + doc


def test_import_glb_is_once_and_backup_remaps_reference(client, monkeypatch):
    p = project(client)
    a = client.post(f"/api/projects/{p['id']}/upload", files={'file': ('ref.png', image_bytes())}).json()['asset']
    j = plan(client, p['id'], mode='image', prompt='', source_asset_id=a['id'])
    store.execute("UPDATE tripo_jobs SET status='ready',task_id=? WHERE id=?", ('task_fixture', j['id']))
    async def query(current):
        return {'task_id': 'task_fixture', 'type': 'image_to_model', 'status': 'success', 'progress': 100,
                'output': {'model_url': 'https://cdn.tripo3d.ai/asset.glb'}}
    async def download(url, target, maximum): target.write_bytes(glb_bytes())
    monkeypatch.setattr(tripo, 'query', query)
    monkeypatch.setattr(tripo, 'download', download)
    r = client.post('/api/tripo/jobs/' + j['id'] + '/import')
    assert r.status_code == 200, r.text
    assert r.json()['status'] == 'imported' and r.json()['model_id']
    assert client.post('/api/tripo/jobs/' + j['id'] + '/import').status_code == 400
    raw = client.get(f"/api/projects/{p['id']}/export").content
    with zipfile.ZipFile(io.BytesIO(raw)) as z: assert json.loads(z.read('project.json'))['format'] == 10
    restored = client.post('/api/import-project', files={'file': ('backup.zip', raw)}).json()
    copied = tripo.jobs(restored['id'])[0]
    assert copied['model_id'] != r.json()['model_id']
    assert json.loads(copied['spec'])['source_asset_id'] != a['id']
    assert copied['task_id'] == 'task_fixture'
    assert client.post('/api/tripo/jobs/' + copied['id'] + '/submit', json={'confirmed': True}).status_code == 400


def test_bad_import_and_untrusted_download_hosts_publish_no_assets(client, monkeypatch):
    p = project(client)
    j = plan(client, p['id'])
    store.execute("UPDATE tripo_jobs SET status='ready',task_id=? WHERE id=?", ('task_bad', j['id']))
    async def query(current): return {'task_id': 'task_bad', 'type': 'text_to_model', 'status': 'success', 'progress': 100, 'output': {'model_url': 'https://cdn.tripo3d.ai/bad.glb'}}
    async def download(url, target, maximum): target.write_bytes(b'not-a-model')
    monkeypatch.setattr(tripo, 'query', query)
    monkeypatch.setattr(tripo, 'download', download)
    assert client.post('/api/tripo/jobs/' + j['id'] + '/import').status_code == 400
    assert tripo.job(j['id'])['status'] == 'ready' and not store.rows('SELECT * FROM assets')
    for url in ['http://cdn.tripo3d.ai/a', 'https://127.0.0.1/a', 'https://cdn.tripo3d.ai.evil.test/a', 'https://user:pass@cdn.tripo3d.ai/a', 'https://cdn.tripo3d.ai:8765/a']:
        with pytest.raises(ValueError): asyncio.run(tripo.validate_download(url))


def test_v3_http_auth_and_download_have_separate_credentials(client, tmp_path, monkeypatch):
    monkeypatch.setattr(tripo.secrets, 'get_key', lambda name: 'fixture-private-key')
    monkeypatch.setattr(tripo.socket, 'getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('8.8.8.8', 443))])
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.host == 'openapi.tripo3d.ai':
            assert request.headers['authorization'] == 'Bearer fixture-private-key'
            assert request.url.path == '/v3/account/balance'
            return httpx.Response(200, json={'code': 0, 'data': {'balance': 50, 'frozen': 0}})
        assert 'authorization' not in request.headers
        if request.url.path == '/redirect': return httpx.Response(302, headers={'location': 'https://127.0.0.1/private'})
        return httpx.Response(200, content=glb_bytes())
    original = httpx.AsyncClient
    monkeypatch.setattr(tripo.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    assert asyncio.run(tripo.request('global', 'GET', '/account/balance'))['balance'] == 50
    asyncio.run(tripo.download('https://cdn.tripo3d.ai/model.glb', tmp_path / 'model.glb', 10000))
    tripo.verify_glb(tmp_path / 'model.glb')
    with pytest.raises(ValueError): asyncio.run(tripo.download('https://cdn.tripo3d.ai/redirect', tmp_path / 'redirect', 10000))
    assert len(calls) == 3
    monkeypatch.setattr(tripo.socket, 'getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(ValueError): asyncio.run(tripo.validate_download('https://cdn.tripo3d.ai/model.glb'))


def test_duplicate_inflight_submit_and_cancellation_do_not_retry(client, monkeypatch):
    p = project(client)
    monkeypatch.setattr(tripo.secrets, 'get_key', lambda name: 'fixture-key')
    calls = []
    async def request(region, method, path, **kw):
        calls.append(path)
        await asyncio.sleep(.01)
        return {'task_id': 'task_once'}
    monkeypatch.setattr(tripo, 'request', request)
    j = plan(client, p['id'])
    async def race(): return await asyncio.gather(tripo.submit(j['id'], True), tripo.submit(j['id'], True), return_exceptions=True)
    result = asyncio.run(race())
    assert len(calls) == 1 and sum(isinstance(r, ValueError) for r in result) == 1
    async def cancelled(*a, **kw): raise asyncio.CancelledError()
    monkeypatch.setattr(tripo, 'request', cancelled)
    j = plan(client, p['id'])
    with pytest.raises(asyncio.CancelledError): asyncio.run(tripo.submit(j['id'], True))
    assert tripo.job(j['id'])['status'] == 'unknown'


def test_connection_config_keeps_keys_private_and_balance_is_readonly(client, monkeypatch):
    monkeypatch.setenv('TRIPO_API_KEY', 'fixture-local-key')
    r = client.put('/api/tripo/config', json={'region': 'cn'})
    assert r.status_code == 200 and r.json()['configured'] and 'fixture-local-key' not in r.text
    calls = []
    async def request(region, method, path, **kwargs):
        calls.append((method, path))
        return {'balance': 50.5, 'frozen': 1, 'private_account_field': 'do-not-return'}
    monkeypatch.setattr(tripo, 'request', request)
    result = client.post('/api/tripo/test')
    assert result.json() == {'balance': 50.5, 'frozen': 1}
    assert calls == [('GET', '/account/balance')] and not store.rows('SELECT * FROM tripo_jobs')
    assert client.put('/api/tripo/config', json={'region': {}}).status_code == 400
    assert client.put('/api/tripo/config', json={'endpoint': 'http://localhost'}).status_code == 400
    from scripts.check_release import problems
    from pathlib import Path
    assert 'possible secret' in problems(Path('fixture.txt'), ('tsk_' + 'x' * 32).encode())
