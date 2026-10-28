import asyncio
import base64
import io
import json
import zipfile

import httpx
import pytest

from backend import agent_tools, app as module, assets, context, image_jobs, jobs, store, task_creation
from test_agent_access import call, conversation, save_grant, scope_for
from test_workbench import client, image_bytes, project


def create_task(client, pid, title='场景资源交付'):
    return client.post(f'/api/projects/{pid}/tasks', json={'title': title, 'detail': '核对文件和版本，不代表引擎验收'}).json()


def large_project(pid):
    now = store.now()
    with store.db() as c:
        c.executemany('INSERT INTO documents VALUES (?,?,?,?,?,?,?)',
                      [(store.uid(), pid, f'规范{i}', 'rule-' + str(i) + '规' * 3000, 1, 'approved' if i == 99 else 'draft', now) for i in range(300)])
        c.executemany('INSERT INTO tasks VALUES (?,?,?,?,?,?,?)',
                      [(store.uid(), pid, f'任务{i}', 'todo', '验收条件' * 300, '', now) for i in range(300)])
        c.executemany('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)',
                      [(store.uid(), pid, f'资源{i}', f'fixture{i}', f'fixture{i}', 'image', '[]', now) for i in range(1000)])


def test_large_context_is_bounded_and_retrievable(client):
    p = project(client); large_project(p['id'])
    state = asyncio.run(agent_tools.execute(p['id'], False, 'get_project', {}))
    assert len(context.encoded(state)) < 50000
    assert state['context']['pages']['assets']['total'] == 1000
    assert state['documents'][0]['authority'] == 'approved'
    assert state['documents'][0]['requires_read'] and state['context']['compressed']
    more = asyncio.run(agent_tools.execute(p['id'], False, 'get_project', {'section': 'tasks', 'offset': 25, 'limit': 5}))
    assert more['context']['pages']['tasks']['offset'] == 25 and len(more['tasks']) == 5
    record = asyncio.run(agent_tools.execute(p['id'], False, 'get_project', {'section': 'record', 'record_type': 'tasks', 'item_id': more['tasks'][0]['id'], 'offset': 100, 'limit': 100}))
    assert len(record['content']) == 100 and record['next_offset'] == 200
    found = asyncio.run(agent_tools.execute(p['id'], False, 'get_project', {'section': 'assets', 'query': '资源999'}))
    assert [a['name'] for a in found['assets']] == ['资源999']
    with pytest.raises(ValueError): asyncio.run(agent_tools.execute(p['id'], False, 'get_project', {'offset': True}))
    with pytest.raises(ValueError): asyncio.run(agent_tools.execute(p['id'], False, 'get_project', {'section': 'record', 'record_type': 'tasks', 'item_id': 'other'}))


def test_compact_chat_preserves_memory_and_context_audit_without_deleting_history(client, monkeypatch):
    p = project(client); large_project(p['id']); c = conversation(client, p['id'], 'director')
    client.patch('/api/conversations/' + c['id'], json={'memory': '关键决定：不添加昼夜系统'})
    with store.db() as db:
        db.executemany('INSERT INTO messages (id,project_id,role,content,provider,created,conversation_id) VALUES (?,?,?,?,?,?,?)',
                       [(store.uid(), p['id'], 'user', 'old-' + str(i) + 'x' * 2000, 'openai', store.now(), c['id']) for i in range(50)])
    async def stream(provider, model, messages, rules, tools, execute_tool):
        packet = json.loads(messages[0]['content'].split('\n', 1)[1])
        assert '不添加昼夜系统' in packet['conversation']['memory']
        assert packet['context']['mode'] == 'compact' and packet['conversation']['omitted_messages'] > 0
        assert len(messages[0]['content']) < 33000
        page = await execute_tool('get_project', {'section': 'documents', 'offset': 25, 'limit': 3})
        assert page['context']['pages']['documents']['offset'] == 25
        yield {'event': 'runtime', 'runtime': {'verified': True, 'tools': ['get_project']}}
        yield {'event': 'delta', 'text': '资料目录已压缩，原文可回查'}
    monkeypatch.setattr(module.providers, 'stream', stream)
    r = client.post(f'/api/projects/{p["id"]}/chat', json={'conversation_id': c['id'], 'provider': 'openai', 'model': 'fixture', 'message': '继续', 'context_mode': 'compact'})
    assert '"event": "done"' in r.text, r.text
    runtime = json.loads(store.rows('SELECT runtime FROM runs WHERE project_id=? ORDER BY created DESC', (p['id'],))[0]['runtime'])
    assert runtime['context']['mode'] == 'compact' and runtime['verified'] and 'permissions' in runtime
    assert len(store.rows('SELECT id FROM messages WHERE conversation_id=?', (c['id'],))) == 52


def test_context_preview_and_checkpoint_validate_ownership_and_inputs(client):
    p, other = project(client), project(client)
    c = conversation(client, other['id'])
    assert client.get(f'/api/projects/{p["id"]}/context', params={'conversation_id': c['id']}).status_code == 400
    assert client.get(f'/api/projects/{p["id"]}/context', params={'mode': 'unlimited'}).status_code == 400
    for body in ([], {'skills': 1}, {'conversation_id': {}}, {'permission': True}, {'decisions': 'x' * 20001}):
        assert client.post(f'/api/projects/{p["id"]}/context/checkpoint', json=body).status_code == 400
    assert not store.rows('SELECT id FROM documents WHERE project_id=?', (p['id'],))


def test_markdown_checkpoint_retains_reviewable_information_without_overwrite(client):
    p = project(client); t = create_task(client, p['id']); c = conversation(client, p['id'])
    client.patch('/api/conversations/' + c['id'], json={'memory': '保留音乐节奏决定'})
    d = client.post(f'/api/projects/{p["id"]}/documents', json={'title': '关卡Skill工作流', 'content': '规则正文：先检查引用，再执行导入'}).json()
    body = {'conversation_id': c['id'], 'decisions': '采用固定镜头；运行效果待核实', 'skills': '美术负责人先读取风格规范', 'workflow': '音乐先试听，再做引擎导入'}
    saved = client.post(f'/api/projects/{p["id"]}/context/checkpoint', json=body).json()
    ids = ','.join(v['id'] for v in saved['documents'])
    r = client.get(f'/api/projects/{p["id"]}/context/markdown', params={'ids': ids})
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert set(z.namelist()) == {'PROJECT_MEMORY.md', 'SKILLS.md', 'WORKFLOW.md'}
        memory = z.read('PROJECT_MEMORY.md').decode()
        assert '采用固定镜头' in memory and '保留音乐节奏决定' in memory and d['id'] in memory and t['id'] in memory
        assert '先读取风格规范' in z.read('SKILLS.md').decode()
        assert '先检查引用' in z.read('SKILLS.md').decode()
        assert '先试听' in z.read('WORKFLOW.md').decode()
    assert all(store.one('SELECT authority FROM documents WHERE id=?', (v['id'],))['authority'] == 'draft' for v in saved['documents'])
    client.post(f'/api/projects/{p["id"]}/context/checkpoint', json=body)
    assert len(store.rows('SELECT id FROM documents WHERE project_id=?', (p['id'],))) == 7
    packet = asyncio.run(agent_tools.execute(p['id'], False, 'get_project', {'compact': True}))
    assert len(packet['handoff_documents']) == 3
    other = project(client)
    assert client.get(f'/api/projects/{other["id"]}/context/markdown', params={'ids': ids}).status_code == 400


@pytest.mark.parametrize('kind,data', [
    ('music', {'title': '配乐', 'prompt': '安静探索'}),
    ('art', {'provider': 'webui', 'prompt': '探索者概念图'}),
    ('blender', {'title': '探索者', 'brief': '背包低模角色'}),
    ('tripo', {'title': '角色', 'prompt': 'low poly explorer', 'mode': 'text'})
])
def test_task_drafts_are_free_and_linked(client, monkeypatch, kind, data):
    p = project(client); t = create_task(client, p['id'])
    async def forbidden(*args, **kwargs): raise AssertionError('Drafting must not call a generation service')
    monkeypatch.setattr(module.music, 'helper', forbidden)
    monkeypatch.setattr(module.tripo, 'request', forbidden)
    r = client.post(f'/api/tasks/{t["id"]}/creations', json={'kind': kind, 'data': data})
    assert r.status_code == 200, r.text
    rows = client.get(f'/api/tasks/{t["id"]}/creations').json()
    assert len(rows) == 1 and rows[0]['kind'] == kind and rows[0]['status'] == 'draft' and not rows[0]['outputs']
    assert jobs.inspect(p['id'], kind, r.json()['id'])['details']['origin_task_id'] == t['id']
    assert not store.rows('SELECT id FROM runs WHERE project_id=?', (p['id'],))
    client.patch(f'/api/tasks/{t["id"]}', json={'status': 'done', 'evidence': '任务文件范围人工核对'})
    assert client.post(f'/api/tasks/{t["id"]}/creations', json={'kind': kind, 'data': data}).status_code == 400


def test_art_draft_generation_returns_to_task_and_requires_explicit_adoption(client, monkeypatch):
    p = project(client); t = create_task(client, p['id']); store.set_setting('image_model', 'fixture-image')
    row = client.post(f'/api/tasks/{t["id"]}/creations', json={'kind': 'art', 'data': {'provider': 'openai', 'prompt': '探索者概念图'}}).json()
    calls = []
    def handler(request):
        calls.append(json.loads(request.content)); return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(image_bytes()).decode()}]})
    real = httpx.AsyncClient
    monkeypatch.setattr(image_jobs.providers, 'config', lambda provider: ('https://fixture.invalid', 'fixture-key'))
    monkeypatch.setattr(image_jobs.httpx, 'AsyncClient', lambda *a, **kw: real(transport=httpx.MockTransport(handler)))
    url = f'/api/art-jobs/{row["id"]}/generate'
    for bad in ({}, {'confirmed': False}, {'confirmed': 1}): assert client.post(url, json=bad).status_code == 400
    assert client.post(url, json={'confirmed': True}).status_code == 200
    assert client.post(url, json={'confirmed': True}).status_code == 400 and len(calls) == 1
    candidates = client.get(f'/api/tasks/{t["id"]}/creations').json()[0]['outputs']
    assert len(candidates) == 1
    current = client.get(f'/api/tasks/{t["id"]}').json()
    assert current['status'] == 'todo' and not current['asset_links']
    aid = candidates[0]['asset_id']
    assert client.post(f'/api/tasks/{t["id"]}/creations/adopt', json={'asset_id': aid, 'confirmed': False}).status_code == 400
    adopted = client.post(f'/api/tasks/{t["id"]}/creations/adopt', json={'asset_id': aid, 'confirmed': True}).json()
    assert adopted['status'] == 'todo' and adopted['asset_links'][0]['asset_id'] == aid
    assert not client.get(f'/api/tasks/{t["id"]}/acceptances').json()


def test_candidate_adoption_rejects_unrelated_assets(client):
    p = project(client); t = create_task(client, p['id'])
    a = client.post(f'/api/projects/{p["id"]}/upload', files={'file': ('unrelated.png', image_bytes())}).json()['asset']
    for aid in (a['id'], {}, 'other'):
        assert client.post(f'/api/tasks/{t["id"]}/creations/adopt', json={'asset_id': aid, 'confirmed': True}).status_code == 400


def test_incremental_updates_omit_unchanged_bodies_and_detect_deliveries(client):
    p = project(client); t = create_task(client, p['id'])
    a = client.post(f'/api/projects/{p["id"]}/upload', files={'file': ('linked.png', image_bytes())}).json()['asset']
    info = client.get(f'/api/assets/{a["id"]}/info').json()
    client.patch(f'/api/tasks/{t["id"]}', json={'deliveries': [{'asset_id': a['id'], 'version_index': info['version_index'], 'sha256': info['hash']}]})
    url = f'/api/projects/{p["id"]}/updates'
    first = client.get(url).json(); cursors = json.dumps(first['cursors'])
    assert set(first['changes']) == {'tasks', 'runs', 'assets'}
    assert client.get(url, params={'since': cursors}).json()['changes'] == {}
    assets.file_for(assets.asset(a['id'])).write_bytes(b'external change')
    changed = client.get(url, params={'since': cursors}).json()['changes']
    assert set(changed) == {'tasks'} and changed['tasks'][0]['asset_links'][0]['changed'] and not changed['tasks'][0]['ready']
    assert client.get(url, params={'since': '[]'}).status_code == 400
    assert client.get(url, params={'sections': 'settings'}).status_code == 400


def test_conditional_job_and_creation_polling(client):
    p = project(client); t = create_task(client, p['id'])
    source = task_creation.create(t['id'], {'kind': 'music', 'data': {'title': '配乐', 'prompt': '探索'}})
    urls = [f'/api/projects/{p["id"]}/jobs', f'/api/projects/{p["id"]}/jobs/inspect?kind=music&id={source["id"]}', f'/api/tasks/{t["id"]}/creations']
    for url in urls:
        first = client.get(url)
        second = client.get(url, headers={'if-none-match': first.headers['etag']})
        assert second.status_code == 304 and not second.content
    store.execute("UPDATE music_jobs SET status='failed' WHERE id=?", (source['id'],))
    assert client.get(urls[-1], headers={'if-none-match': first.headers['etag']}).status_code == 200


def test_backup_retains_draft_task_links_and_markdown_remaps(client):
    p = project(client); t = create_task(client, p['id'])
    source = task_creation.create(t['id'], {'kind': 'music', 'data': {'title': '配乐', 'prompt': '探索'}})
    client.post(f'/api/projects/{p["id"]}/context/checkpoint', json={})
    raw = client.get(f'/api/projects/{p["id"]}/export').content
    with zipfile.ZipFile(io.BytesIO(raw)) as z: assert json.loads(z.read('project.json'))['format'] == 10
    restored = client.post('/api/import-project', files={'file': ('backup.zip', raw)})
    assert restored.status_code == 200, restored.text
    state = client.get('/api/projects/' + restored.json()['id']).json()
    new_task = state['tasks'][0]
    row = client.get(f'/api/tasks/{new_task["id"]}/creations').json()[0]
    assert row['job_id'] != source['id'] and row['status'] == 'restored'
    memory = next(d for d in state['documents'] if d['title'].startswith('PROJECT_MEMORY.md'))
    assert new_task['id'] in memory['content'] and t['id'] not in memory['content']
    assert not state['runs']


def test_agent_task_and_checkpoint_actions_remain_scoped(client):
    p, other = project(client), project(client); t = create_task(client, p['id']); foreign = create_task(client, other['id'])
    c = conversation(client, p['id']); g = save_grant(client, c['id'], full=True)
    scope = scope_for(p, c, g)
    result = call(client, scope, 'task.draft', target_id=t['id'], data={'kind': 'music', 'data': {'title': '配乐', 'prompt': '探索'}})
    assert result['task_id'] == t['id']
    with pytest.raises(ValueError): call(client, scope, 'task.draft', target_id=foreign['id'], data={'kind': 'music', 'data': {'title': '越界', 'prompt': '不应保存'}})
    saved = call(client, scope, 'context.checkpoint', data={'skills': '仅使用当前工具目录'})
    assert len(saved['documents']) == 3
    save_grant(client, c['id'], full=False)
    with pytest.raises(ValueError): call(client, scope, 'context.checkpoint', data={})


def test_default_music_agent_can_link_draft_without_full_access(client):
    p, other = project(client), project(client); t = create_task(client, p['id']); foreign = create_task(client, other['id'])
    c = conversation(client, p['id'])
    scope = {'pid': p['id'], 'conversation_id': c['id'], 'agent': 'music', 'write': True}
    data = {'title': '音乐', 'prompt': '探索', 'tags': '', 'instrumental': True, 'task_id': t['id']}
    result = client.portal.call(agent_tools.invoke, scope, 'draft_music', data)
    assert result['task_id'] == t['id'] and result['status'] == 'draft'
    with pytest.raises(ValueError): client.portal.call(agent_tools.invoke, scope, 'draft_music', {**data, 'task_id': foreign['id']})


def test_blender_derived_recipe_retains_original_task(client):
    p = project(client); t = create_task(client, p['id'])
    source = task_creation.create(t['id'], {'kind': 'blender', 'data': {'title': '初稿'}})
    derived = client.post(f'/api/projects/{p["id"]}/characters', json={'spec': {'title': '调整比例'}, 'parent_id': source['id']})
    assert derived.status_code == 200, derived.text
    linked = client.get(f'/api/tasks/{t["id"]}/creations').json()
    assert len(linked) == 2 and any(v['job_id'] == derived.json()['id'] for v in linked)


def test_automated_art_submission_refuses_unresolved_same_prompt(client):
    p = project(client); t = create_task(client, p['id'])
    first = task_creation.create(t['id'], {'kind': 'art', 'data': {'provider': 'openai', 'prompt': '探索者'}})
    store.execute("UPDATE art_jobs SET status='interrupted' WHERE id=?", (first['id'],))
    second = task_creation.create(t['id'], {'kind': 'art', 'data': {'provider': 'openai', 'prompt': '探索者'}})
    c = conversation(client, p['id']); g = save_grant(client, c['id'], full=True)
    with pytest.raises(ValueError, match='不自动重提'):
        call(client, scope_for(p, c, g), 'image.submit_draft', target_id=second['id'])
    assert store.one('SELECT status FROM art_jobs WHERE id=?', (second['id'],))['status'] == 'draft'
