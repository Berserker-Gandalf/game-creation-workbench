import io
import json
import zipfile
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import app as module, assets, secrets, store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path / 'data')
    with TestClient(module.app) as client:
        client.headers['x-workbench-token'] = client.get('/api/bootstrap').json()['token']
        yield client


def project(client, **extra):
    r = client.post('/api/projects', json={'name': '验证工程', 'engine': 'unreal', **extra})
    assert r.status_code == 200, r.text
    return r.json()


def image_bytes():
    buf = io.BytesIO()
    Image.new('RGBA', (24, 16), (240, 100, 30, 160)).save(buf, format='PNG')
    return buf.getvalue()


def test_project_persists_and_invalid_root_rejected(client, tmp_path):
    p = project(client)
    client.patch('/api/projects/' + p['id'], json={'brief': '正式总纲：无昼夜系统'})
    store.init()
    assert client.get('/api/projects/' + p['id']).json()['project']['brief'] == '正式总纲：无昼夜系统'
    assert client.post('/api/projects', json={'name': '错误路径', 'root': str(tmp_path / 'missing')}).status_code == 400


def test_cross_origin_and_missing_token_rejected(client):
    assert client.post('/api/projects', json={'name': 'bad'}, headers={'origin': 'https://attacker.example'}).status_code == 403
    assert client.post('/api/projects', json={'name': 'bad'}, headers={'x-workbench-token': ''}).status_code == 403
    assert client.get('/api/bootstrap', headers={'host': 'attacker.example'}).status_code == 400
    assert client.post('/api/internal/mcp', json={'method': 'tools/list'}).status_code == 403


def test_document_conflict_history_and_restore(client):
    p = project(client)
    d = client.post(f"/api/projects/{p['id']}/documents", json={'title': '设计', 'content': '原稿'}).json()
    updated = client.patch('/api/documents/' + d['id'], json={'revision': 1, 'content': '正式版', 'authority': 'approved'})
    assert updated.status_code == 200
    assert client.patch('/api/documents/' + d['id'], json={'revision': 1, 'content': '覆盖'}).status_code == 409
    versions = client.get('/api/documents/' + d['id'] + '/versions').json()
    assert versions[0]['content'] == '原稿'
    restored = client.patch('/api/documents/' + d['id'], json={'revision': 2, 'content': versions[0]['content']}).json()
    assert restored['revision'] == 3 and restored['content'] == '原稿'


def test_done_requires_evidence(client):
    p = project(client)
    t = client.post(f"/api/projects/{p['id']}/tasks", json={'title': '导入资产'}).json()
    assert client.patch('/api/tasks/' + t['id'], json={'status': 'done'}).status_code == 400
    assert client.patch('/api/tasks/' + t['id'], json={'status': 'done', 'evidence': '已在测试工程重开确认'}).json()['status'] == 'done'


def test_image_edits_preserve_original_conflict_and_restore(client):
    p = project(client)
    raw = image_bytes()
    a = client.post(f"/api/projects/{p['id']}/upload", files={'file': ('sprite.png', raw, 'image/png')}).json()['asset']
    info = client.get('/api/assets/' + a['id'] + '/info').json()
    r = client.post('/api/assets/' + a['id'] + '/edit', json={'expected_hash': info['hash'], 'width': 12, 'height': 8})
    assert r.status_code == 200, r.text
    assert Path(a['source']).read_bytes() == raw
    assert client.get('/api/assets/' + a['id'] + '/info').json()['width'] == 12
    assert client.post('/api/assets/' + a['id'] + '/edit', json={'expected_hash': info['hash'], 'flip': True}).status_code == 400
    assert client.post('/api/assets/' + a['id'] + '/restore', json={'index': 0}).status_code == 200
    assert client.get('/api/assets/' + a['id'] + '/file').content == raw


def test_asset_path_escape_rejected(client, tmp_path):
    p = project(client)
    outside = tmp_path / 'outside.png'; outside.write_bytes(image_bytes())
    a = assets.register(p['id'], outside)
    assert client.get('/api/assets/' + a['id'] + '/file').status_code == 400
    with pytest.raises(ValueError):
        assets.inside(tmp_path / '../outside', tmp_path)


def test_export_restore_preserves_versions_and_excludes_credentials(client):
    p = project(client)
    d = client.post(f"/api/projects/{p['id']}/documents", json={'title': '设计', 'content': 'v1'}).json()
    client.patch('/api/documents/' + d['id'], json={'revision': 1, 'content': 'v2'})
    a = client.post(f"/api/projects/{p['id']}/upload", files={'file': ('sprite.png', image_bytes(), 'image/png')}).json()['asset']
    info = client.get('/api/assets/' + a['id'] + '/info').json()
    client.post('/api/assets/' + a['id'] + '/edit', json={'expected_hash': info['hash'], 'flip': True})
    store.set_setting('secret_openai', 'NEVER_EXPORT_THIS')
    raw = client.get(f"/api/projects/{p['id']}/export").content
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert 'NEVER_EXPORT_THIS' not in archive.read('project.json').decode()
    restored = client.post('/api/import-project', files={'file': ('backup.zip', raw, 'application/zip')})
    assert restored.status_code == 200, restored.text
    new = client.get('/api/projects/' + restored.json()['id']).json()
    assert new['documents'][0]['content'] == 'v2'
    versions = client.get('/api/documents/' + new['documents'][0]['id'] + '/versions').json()
    assert versions[0]['content'] == 'v1'
    assert len(json.loads(new['assets'][0]['versions'])) == 2
    assert new['assets'][0]['id'] != a['id']


def test_zip_traversal_blocked(client):
    p = project(client)
    export = client.get(f"/api/projects/{p['id']}/export").content
    buf = io.BytesIO(export)
    with zipfile.ZipFile(buf, 'a') as archive:
        archive.writestr('../escape.txt', 'no')
    result = client.post('/api/import-project', files={'file': ('bad.zip', buf.getvalue(), 'application/zip')})
    assert result.status_code == 400
    assert not (store.DATA / 'projects/escape.txt').exists()


def test_missing_api_key_is_explicit_failed_run(client, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    p = project(client)
    raw = client.post(f"/api/projects/{p['id']}/chat", json={'message': '你好', 'provider': 'openai', 'model': 'test'}).text
    assert '请先' in raw and 'error' in raw
    state = client.get('/api/projects/' + p['id']).json()
    assert state['runs'][0]['status'] == 'failed'
    assert not any(m['role'] == 'assistant' for m in state['messages'])


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows DPAPI')
def test_credentials_are_protected_and_not_returned(client):
    raw = 'unit-test-key-not-a-real-secret'
    assert client.put('/api/providers/openai', json={'key': raw, 'model': 'test'}).status_code == 200
    assert secrets.get_key('openai') == raw
    assert raw not in json.dumps(store.setting('secret_openai'))
    assert raw not in client.get('/api/bootstrap').text


def test_agent_scope_cannot_write_in_discussion(client):
    p = project(client)
    module.AGENTS['test-session'] = {'pid': p['id'], 'write': False}
    try:
        headers = {'authorization': 'Bearer test-session'}
        tools = client.post('/api/internal/mcp', json={'method': 'tools/list'}, headers=headers).json()
        assert 'create_task' not in [t['name'] for t in tools['tools']]
        assert 'edit_image' not in [t['name'] for t in tools['tools']]
        result = client.post('/api/internal/mcp', json={'method': 'tools/call', 'params': {'name': 'create_task', 'arguments': {'title': 'no', 'detail': ''}}}, headers=headers).json()
        assert result['isError'] is True
        assert not store.snapshot(p['id'])['tasks']
    finally:
        module.AGENTS.pop('test-session')


def test_audio_crop_preserves_source_and_rejects_invalid_range(client):
    p = project(client)
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\x10\x10' * 8000)
    raw = buffer.getvalue()
    a = client.post(f"/api/projects/{p['id']}/upload", files={'file': ('test.wav', raw, 'audio/wav')}).json()['asset']
    info = client.get('/api/assets/' + a['id'] + '/info').json()
    assert info['duration'] == 1
    assert client.post('/api/assets/' + a['id'] + '/edit-audio', json={'expected_hash': info['hash'], 'start': 0, 'end': 2}).status_code == 400
    assert client.post('/api/assets/' + a['id'] + '/edit-audio', json={'expected_hash': info['hash'], 'start': 0.25, 'end': 0.75}).status_code == 200
    assert client.get('/api/assets/' + a['id'] + '/info').json()['duration'] == 0.5
    assert Path(a['source']).read_bytes() == raw


def test_mcp_returns_real_image_and_enforces_project_ownership(client):
    p, other = project(client), project(client)
    a = client.post(f"/api/projects/{p['id']}/upload", files={'file': ('test.png', image_bytes(), 'image/png')}).json()['asset']
    module.AGENTS['image-session'] = {'pid': p['id'], 'write': False}
    module.AGENTS['other-session'] = {'pid': other['id'], 'write': True}
    try:
        payload = {'method': 'tools/call', 'params': {'name': 'view_asset', 'arguments': {'asset_id': a['id']}}}
        result = client.post('/api/internal/mcp', json=payload, headers={'authorization': 'Bearer image-session'}).json()
        assert result['content'][1]['type'] == 'image'
        assert result['content'][1]['mimeType'] == 'image/png'
        assert client.post('/api/internal/mcp', json=payload, headers={'authorization': 'Bearer other-session'}).json()['isError']
    finally:
        module.AGENTS.pop('image-session'); module.AGENTS.pop('other-session')


def task(client, pid, title, **links):
    result = client.post(f'/api/projects/{pid}/tasks', json={'title': title, **links})
    assert result.status_code == 200, result.text
    return result.json()


def test_dependencies_gate_execution_reject_cycles_and_cross_project_links(client):
    p, other = project(client), project(client)
    first = task(client, p['id'], '设计确认')
    second = task(client, p['id'], '制作贴图', dependency_ids=[first['id']])
    third = task(client, p['id'], '引擎集成', dependency_ids=[second['id']])
    assert not second['ready'] and '设计确认' in second['issues'][0]
    for status in ('running', 'review', 'done'):
        assert client.patch('/api/tasks/' + second['id'], json={'status': status, 'evidence': '有依据'}).status_code == 400
    for dependencies in ([first['id']], [third['id']]):
        assert client.patch('/api/tasks/' + first['id'], json={'dependency_ids': dependencies}).status_code == 400
    assert client.post(f"/api/projects/{other['id']}/tasks", json={'title': '跨项目', 'dependency_ids': [first['id']]}).status_code == 400
    assert client.patch('/api/tasks/' + first['id'], json={'status': 'done', 'evidence': '设计文档通过'}).status_code == 200
    assert client.patch('/api/tasks/' + second['id'], json={'status': 'running'}).status_code == 200
    # Reopening a parent also invalidates downstream acceptance, without deleting history.
    client.patch('/api/tasks/' + second['id'], json={'status': 'done', 'evidence': '贴图通过'})
    client.patch('/api/tasks/' + third['id'], json={'status': 'done', 'evidence': '集成通过'})
    client.patch('/api/tasks/' + first['id'], json={'status': 'todo'})
    state = client.get('/api/projects/' + p['id']).json()
    final = next(t for t in state['tasks'] if t['id'] == third['id'])
    assert final['status'] == 'done' and not final['ready'] and final['evidence'] == '集成通过'


def test_document_changes_propagate_to_dependents_and_require_explicit_review(client):
    p = project(client)
    doc = client.post(f"/api/projects/{p['id']}/documents", json={'title': '美术规范', 'content': '橙色'}).json()
    a = task(client, p['id'], '美术', document_ids=[doc['id']])
    b = task(client, p['id'], '导入', dependency_ids=[a['id']])
    client.patch('/api/tasks/' + a['id'], json={'status': 'done', 'evidence': 'v1 验收'})
    client.patch('/api/tasks/' + b['id'], json={'status': 'done', 'evidence': '导入验收'})
    client.patch('/api/documents/' + doc['id'], json={'revision': 1, 'content': '蓝色'})
    state = client.get('/api/projects/' + p['id']).json()
    assert all(not t['ready'] for t in state['tasks'])
    assert client.patch('/api/tasks/' + a['id'], json={'title': '不能悄悄接受新版'}).status_code == 400
    reviewed = client.patch('/api/tasks/' + a['id'], json={'document_ids': [doc['id']], 'status': 'todo'}).json()
    assert reviewed['document_links'][0]['revision'] == 2 and reviewed['ready']
    assert client.patch('/api/tasks/' + b['id'], json={'status': 'done'}).status_code == 400
    assert client.patch('/api/tasks/' + a['id'], json={'status': 'done', 'evidence': 'v2 重新验收'}).status_code == 200
    downstream = next(t for t in client.get('/api/projects/' + p['id']).json()['tasks'] if t['id'] == b['id'])
    assert downstream['review_required'] and not downstream['ready']
    client.patch('/api/tasks/' + b['id'], json={'status': 'todo'})
    assert client.patch('/api/tasks/' + b['id'], json={'status': 'done', 'evidence': '按 v2 重验'}).status_code == 200
    assert all(t['ready'] for t in client.get('/api/projects/' + p['id']).json()['tasks'])


def test_task_relationship_backup_restores_ids_and_outdated_pins(client):
    p = project(client)
    doc = client.post(f"/api/projects/{p['id']}/documents", json={'title': '规范', 'content': 'v1'}).json()
    a = task(client, p['id'], '上游', document_ids=[doc['id']])
    task(client, p['id'], '下游', dependency_ids=[a['id']])
    client.patch('/api/documents/' + doc['id'], json={'revision': 1, 'content': 'v2'})
    raw = client.get(f"/api/projects/{p['id']}/export").content
    restored = client.post('/api/import-project', files={'file': ('backup.zip', raw)}).json()
    state = client.get('/api/projects/' + restored['id']).json()
    upper, lower = sorted(state['tasks'], key=lambda t: t['title'])
    assert upper['title'] == '上游'
    assert upper['id'] != a['id'] and lower['dependency_ids'] == [upper['id']]
    assert upper['document_links'][0]['doc_id'] == state['documents'][0]['id']
    assert upper['document_links'][0]['revision'] == 1 and not upper['ready'] and not lower['ready']


def test_legacy_backup_imports_without_relationship_tables(client):
    p = project(client)
    task(client, p['id'], '旧任务')
    raw = client.get(f"/api/projects/{p['id']}/export").content
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest = json.loads(archive.read('project.json'))
    manifest['format'] = 1
    manifest.pop('task_documents'); manifest.pop('task_dependencies')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('project.json', json.dumps(manifest))
    result = client.post('/api/import-project', files={'file': ('legacy.zip', output.getvalue())})
    assert result.status_code == 200
    assert client.get('/api/projects/' + result.json()['id']).json()['tasks'][0]['ready']


def test_changing_completed_task_links_requires_reacceptance(client):
    p = project(client)
    a, b = task(client, p['id'], '设计'), task(client, p['id'], '制作')
    for t in (a, b):
        client.patch('/api/tasks/' + t['id'], json={'status': 'done', 'evidence': '原验收'})
    assert client.patch('/api/tasks/' + b['id'], json={'dependency_ids': [a['id']]}).status_code == 400
    response = client.patch('/api/tasks/' + b['id'], json={'dependency_ids': [a['id']], 'status': 'todo'})
    assert response.status_code == 200 and response.json()['status'] == 'todo'


def test_agent_can_create_scoped_dependencies_and_reports_current_acceptance(client):
    p, other = project(client), project(client)
    a = task(client, p['id'], '前置设计')
    doc = client.post(f"/api/projects/{p['id']}/documents", json={'title': '规则', 'content': 'v1'}).json()
    module.AGENTS['task-links'] = {'pid': p['id'], 'write': True}
    try:
        headers = {'authorization': 'Bearer task-links'}
        def call(name, arguments):
            return client.post('/api/internal/mcp', json={'method':'tools/call','params':{'name':name,'arguments':arguments}},headers=headers).json()
        result = call('create_task', {'title':'AI 创建的下游','detail':'先完成设计','dependency_ids':[a['id']],'document_ids':[doc['id']]})
        created = json.loads(result['content'][0]['text'])
        assert created['dependency_ids'] == [a['id']] and not created['ready']
        foreign = task(client, other['id'], '其他项目任务')
        assert call('create_task', {'title':'非法关联','detail':'','dependency_ids':[foreign['id']]})['isError']
        state = json.loads(call('get_project', {})['content'][0]['text'])
        assert len(state['tasks']) == 2 and state['accepted_tasks'] == 0
    finally:
        module.AGENTS.pop('task-links')


@pytest.fixture
def image_provider(monkeypatch):
    import base64
    import httpx
    from backend import image_jobs
    original_client = httpx.AsyncClient
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(image_bytes()).decode()}], 'usage': {'total_tokens': 12}})
    monkeypatch.setattr(image_jobs.httpx, 'AsyncClient', lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(secrets, 'get_key', lambda provider: 'test-only-placeholder')
    store.set_setting('image_model', 'fixture-image-model')
    return requests


def upload_image(client, pid, name='source.png', raw=None):
    return client.post(f'/api/projects/{pid}/upload', files={'file': (name, raw or image_bytes(), 'image/png')}).json()['asset']


def test_ai_image_edit_sends_reference_and_alpha_mask_preserves_versions(client, image_provider):
    import base64
    p = project(client)
    a = upload_image(client, p['id'])
    buffer = io.BytesIO()
    Image.new('RGBA', (24, 16), (0, 0, 0, 0)).save(buffer, format='PNG')
    mask = upload_image(client, p['id'], 'mask.png', buffer.getvalue())
    fingerprint = client.get('/api/assets/' + a['id'] + '/info').json()['hash']
    result = client.post('/api/assets/' + a['id'] + '/ai-edit', json={'prompt': '改成青绿色', 'expected_hash': fingerprint, 'mask_asset_id': mask['id']})
    assert result.status_code == 200, result.text
    assert result.json()['applied'] and result.json()['asset']['id'] == a['id']
    payload = json.loads(image_provider[0].content)
    assert image_provider[0].url.path == '/v1/images/edits'
    assert payload['images'][0]['image_url'].startswith('data:image/png;base64,')
    with Image.open(io.BytesIO(base64.b64decode(payload['mask']['image_url'].split(',')[1]))) as image:
        assert image.getchannel('A').getextrema() == (0, 0)
    assert Path(a['source']).read_bytes() == image_bytes()
    assert len(client.get('/api/assets/' + a['id'] + '/info').json()['versions']) == 2
    state = client.get('/api/projects/' + p['id']).json()
    assert json.loads(state['runs'][0]['usage'])['total_tokens'] == 12


def test_ai_image_edit_rejects_stale_hash_foreign_or_invalid_mask_before_request(client, image_provider):
    p, other = project(client), project(client)
    a, foreign = upload_image(client, p['id']), upload_image(client, other['id'])
    fingerprint = client.get('/api/assets/' + a['id'] + '/info').json()['hash']
    url = '/api/assets/' + a['id'] + '/ai-edit'
    assert client.post(url, json={'prompt': '改色', 'expected_hash': 'old'}).status_code == 400
    assert client.post(url, json={'prompt': '改色', 'expected_hash': fingerprint, 'mask_asset_id': foreign['id']}).status_code == 400
    opaque = io.BytesIO(); Image.new('RGB', (24, 16)).save(opaque, format='PNG')
    invalid = upload_image(client, p['id'], 'opaque.png', opaque.getvalue())
    assert client.post(url, json={'prompt': '改色', 'expected_hash': fingerprint, 'mask_asset_id': invalid['id']}).status_code == 400
    assert not image_provider


def test_ai_edit_keeps_result_as_candidate_if_asset_changes_during_request(client, monkeypatch):
    import base64
    import httpx
    from backend import image_jobs
    p = project(client)
    a = upload_image(client, p['id'])
    fingerprint = client.get('/api/assets/' + a['id'] + '/info').json()['hash']
    original_client = httpx.AsyncClient
    changed = []
    def handler(request):
        changed.append(assets.edit_image(a['id'], {'expected_hash': fingerprint, 'width': 12, 'height': 8}))
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(image_bytes()).decode()}]})
    monkeypatch.setattr(image_jobs.httpx, 'AsyncClient', lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(secrets, 'get_key', lambda provider: 'fixture-only')
    store.set_setting('image_model', 'fixture-image-model')
    response = client.post('/api/assets/' + a['id'] + '/ai-edit', json={'prompt': '编辑', 'expected_hash': fingerprint})
    assert response.status_code == 200
    assert not response.json()['applied'] and response.json()['asset']['id'] != a['id']
    assert assets.asset(a['id'])['active'] == changed[0]['active']
    assert client.get('/api/assets/' + a['id'] + '/info').json()['width'] == 12


def test_ai_image_timeout_does_not_retry_and_records_failure(client, monkeypatch):
    import httpx
    from backend import image_jobs
    p = project(client)
    original_client, calls = httpx.AsyncClient, []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('fixture timeout')
    monkeypatch.setattr(image_jobs.httpx, 'AsyncClient', lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(secrets, 'get_key', lambda provider: 'fixture-only')
    store.set_setting('image_model', 'fixture-image-model')
    response = client.post(f"/api/projects/{p['id']}/generate-image", json={'prompt': '测试'})
    assert response.status_code == 400 and '未自动重试' in response.json()['detail']
    state = client.get('/api/projects/' + p['id']).json()
    assert len(calls) == 1 and state['runs'][0]['status'] == 'failed' and not state['assets']
    assert p['id'] not in image_jobs.ACTIVE
