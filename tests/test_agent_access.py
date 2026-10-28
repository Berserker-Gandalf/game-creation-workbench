import asyncio
import io
import json
import zipfile

import pytest

from backend import app as module, agent_tools, codex, generation_models, music, permissions, store, tripo, workbench_actions
from test_workbench import client, project, image_bytes
from test_music import skill


def conversation(client, pid, agent='music'):
    return client.post(f'/api/projects/{pid}/conversations', json={'agent': agent, 'provider': 'openai', 'model': 'fixture'}).json()


def save_grant(client, cid, **changes):
    old = client.get(f'/api/conversations/{cid}/permissions').json()
    data = {**{k: old[k] for k in permissions.FLAGS}, 'version': old['version'], 'acknowledged': True, 'computer_ack': True, **changes}
    result = client.put(f'/api/conversations/{cid}/permissions', json=data)
    assert result.status_code == 200, result.text
    return result.json()


def scope_for(p, c, g, **extra):
    return {'pid': p['id'], 'conversation_id': c['id'], 'agent': c['agent'], 'write': True, 'grant_version': g['version'], **extra}


def invoke(client, scope, name, args):
    return client.portal.call(agent_tools.invoke, scope, name, args)


def call(client, scope, action, **inputs):
    return invoke(client, scope, 'workbench_call', {'action': action, 'input_json': json.dumps(inputs)})


def completed(client, scope, receipt):
    result = client.portal.call(workbench_actions.operation, scope, receipt['operation_id'], 10)
    assert result['status'] == 'completed', result
    return result['result']


def test_grants_require_human_confirmation_and_never_accept_partial_or_stale_input(client):
    p = project(client); c = conversation(client, p['id']); url = f"/api/conversations/{c['id']}/permissions"
    old = client.get(url).json()
    assert not any(old[k] for k in permissions.FLAGS)
    base = {**{k: False for k in permissions.FLAGS}, 'version': '', 'acknowledged': True, 'computer_ack': False}
    for data in ({**base, 'suno': True}, {**base, 'full': True, 'acknowledged': False}, {**base, 'full': True, 'computer': True}, {**base, 'full': 'true'}, {**base, 'unexpected': True}):
        assert client.put(url, json=data).status_code == 400
    saved = save_grant(client, c['id'], full=True)
    assert saved['full'] and saved['version'] and not saved['suno']
    assert module.codex.client.last_policy['verified'] is False
    assert client.put(url, json=base).status_code == 400
    assert client.put(url, json={**base, 'version': saved['version']}, headers={'x-workbench-token': ''}).status_code == 403


def test_full_scope_crosses_roles_but_not_projects_and_revocation_invalidates_old_scope(client):
    p, other = project(client), project(client)
    c = conversation(client, p['id']); g = save_grant(client, c['id'], full=True); scope = scope_for(p, c, g)
    values = invoke(client, scope, 'workbench_actions', {'group': ''})
    assert len(values) >= 50 and all(not v['allowed'] for v in values if v['cost'])
    assert next(v for v in values if v['name'] == 'asset.edit_audio')['input_contract']['data']['expected_hash']
    created = call(client, scope, 'document.create', data={'title': '资产设计', 'content': '原稿'})
    updated = call(client, scope, 'document.update', target_id=created['id'], data={'revision': 1, 'content': '正式版', 'authority': 'approved'})
    assert updated['revision'] == 2 and updated['authority'] == 'approved'
    foreign = client.post(f"/api/projects/{other['id']}/upload", files={'file': ('ref.png', image_bytes())}).json()['asset']
    with pytest.raises(ValueError, match='当前项目'): call(client, scope, 'asset.info', target_id=foreign['id'])
    with pytest.raises(ValueError): call(client, scope, 'permissions.save', data={'full': True})
    with pytest.raises(ValueError): call(client, {**scope, 'write': False}, 'project.get')
    save_grant(client, c['id'], full=False)
    with pytest.raises(ValueError, match='撤销'): call(client, scope, 'project.get')


def test_default_chat_flags_cannot_grant_full_access_and_discussion_keeps_default_tools(client, monkeypatch):
    p = project(client); c = conversation(client, p['id']); captures = []
    async def stream(provider, model, inputs, rules, tools, execute_tool, **kw):
        captures.append({t['name'] for t in tools}); yield {'event': 'delta', 'text': '仅讨论'}
    monkeypatch.setattr(module.providers, 'stream', stream)
    data = {'message': '讨论', 'conversation_id': c['id'], 'agent': 'music', 'provider': 'openai', 'model': 'fixture', 'full': True, 'suno': True, 'computer': True}
    assert 'done' in client.post(f"/api/projects/{p['id']}/chat", json={**data, 'execute': True}).text
    assert 'workbench_call' not in captures[-1] and 'draft_music' in captures[-1]
    save_grant(client, c['id'], full=True, suno=True)
    assert 'done' in client.post(f"/api/projects/{p['id']}/chat", json={**data, 'execute': False}).text
    assert len(captures[-1]) == 6 and 'workbench_call' not in captures[-1]


def test_full_api_agent_can_draft_submit_and_query_with_model_audit(client, monkeypatch, skill):
    p = project(client); c = conversation(client, p['id']); save_grant(client, c['id'], full=True, suno=True)
    generation_models.save(p['id'], {'suno': 'chirp-goose'})
    seen = []
    async def stream(provider, model, inputs, rules, tools, execute_tool, **kw):
        assert kw['max_requests'] == 20 and len(tools) == 21
        assert 'SUNO 自动积分授权：True' in rules
        j = await execute_tool('workbench_call', {'action': 'music.draft', 'input_json': json.dumps({'data': {'title': '探索', 'prompt': '安静木吉他', 'instrumental': True}})})
        op = await execute_tool('workbench_call', {'action': 'music.submit', 'input_json': json.dumps({'target_id': j['id']})})
        result = await execute_tool('workbench_operation', {'operation_id': op['operation_id'], 'wait_seconds': 10})
        seen.append(result)
        yield {'event': 'delta', 'text': '已提交，等待生成查询'}
    monkeypatch.setattr(module.providers, 'stream', stream)
    result = client.post(f"/api/projects/{p['id']}/chat", json={'message': '生成探索配乐', 'conversation_id': c['id'], 'agent': 'music', 'provider': 'openai', 'model': 'fixture', 'execute': True})
    assert 'done' in result.text and seen[0]['result']['status'] == 'submitted'
    submitted = [args for args in skill if args[:2] == ('request', 'POST')]
    assert len(submitted) == 1 and json.loads(submitted[0][3])['mv'] == 'chirp-goose'
    run = store.one("SELECT * FROM runs WHERE kind='music:suno-cn'")
    assert run['model'] == 'chirp-goose'
    assert store.rows("SELECT * FROM tool_events WHERE tool='workbench_call'")


def test_credit_permissions_are_independent_and_do_not_bypass_original_submit_once(client, monkeypatch, skill):
    p = project(client); c = conversation(client, p['id']); g = save_grant(client, c['id'], full=True, suno=True)
    scope = scope_for(p, c, g)
    sj = call(client, scope, 'music.draft', data={'title': '探索', 'prompt': '安静', 'instrumental': True})
    tj = call(client, scope, 'tripo.draft', data={'prompt': 'A robot'})
    with pytest.raises(ValueError, match='tripo'): call(client, scope, 'tripo.submit', target_id=tj['id'])
    assert not skill and tripo.job(tj['id'])['status'] == 'draft'
    assert completed(client, scope, call(client, scope, 'music.submit', target_id=sj['id']))['status'] == 'submitted'
    second = client.portal.call(workbench_actions.operation, scope, call(client, scope, 'music.submit', target_id=sj['id'])['operation_id'], 10)
    assert second['status'] == 'failed' and len([x for x in skill if x[:2] == ('request', 'POST')]) == 1
    g = save_grant(client, c['id'], suno=False, tripo=True); scope = scope_for(p, c, g)
    with pytest.raises(ValueError, match='suno'): call(client, scope, 'music.submit', target_id=sj['id'])
    requests = []
    async def request(region, method, path, **kwargs): requests.append(kwargs['json']); return {'task_id': 'task_fixture1'}
    monkeypatch.setattr(tripo.secrets, 'get_key', lambda name: 'fixture')
    monkeypatch.setattr(tripo, 'request', request)
    assert completed(client, scope, call(client, scope, 'tripo.submit', target_id=tj['id']))['status'] == 'queued'
    assert len(requests) == 1


def test_unknown_paid_result_blocks_automatic_clone_even_with_changed_title(client, monkeypatch):
    p = project(client); c = conversation(client, p['id']); g = save_grant(client, c['id'], full=True, suno=True); scope = scope_for(p, c, g)
    calls = []
    async def helper(*args):
        if args[:2] == ('auth', 'verify'): return {'status': 'authorized'}
        calls.append(args); raise ValueError('response lost')
    monkeypatch.setattr(music, 'helper', helper)
    first = call(client, scope, 'music.draft', data={'title': '曲一', 'prompt': '安静', 'instrumental': True})
    op = call(client, scope, 'music.submit', target_id=first['id'])
    outcome = client.portal.call(workbench_actions.operation, scope, op['operation_id'], 10)
    assert outcome['status'] == 'failed' and music.job(first['id'])['status'] == 'unknown'
    clone = call(client, scope, 'music.draft', data={'title': '曲二', 'prompt': '安静', 'instrumental': True})
    with pytest.raises(ValueError, match='未知'): call(client, scope, 'music.submit', target_id=clone['id'])
    assert len(calls) == 1


def test_project_model_defaults_are_used_by_both_drafts_and_frozen_at_creation(client):
    p = project(client); endpoint = f"/api/projects/{p['id']}/generation-models"
    models = client.get(endpoint).json()
    assert len(models['suno']) == 3 and len(models['tripo']) == 3
    assert client.put(endpoint, json={'suno': 'invented-model'}).status_code == 400
    assert client.put(endpoint, json={'suno': 'chirp-hawk-wild', 'tripo': tripo.MODELS[1]}).status_code == 200
    sj = music.draft(p['id'], {'title': '草稿', 'prompt': '安静'})
    tj = tripo.draft(p['id'], {'prompt': 'A cat'})
    client.put(endpoint, json={'suno': 'chirp-goose', 'tripo': tripo.MODELS[2]})
    assert json.loads(music.job(sj['id'])['spec'])['mv'] == 'chirp-hawk-wild'
    assert json.loads(tripo.job(tj['id'])['spec'])['model'] == tripo.MODELS[1]


def test_export_restore_and_fork_keep_models_but_never_inherit_authority(client):
    p = project(client); c = conversation(client, p['id']); save_grant(client, c['id'], full=True, computer=True, suno=True, tripo=True)
    generation_models.save(p['id'], {'suno': 'chirp-goose', 'tripo': tripo.MODELS[1]})
    copied = client.post(f"/api/conversations/{c['id']}/fork").json()
    assert not permissions.get(copied['id'])['full']
    raw = client.get(f"/api/projects/{p['id']}/export").content
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        manifest = json.loads(z.read('project.json'))
        assert manifest['format'] == 10 and 'settings' not in manifest
        assert manifest['generation_models']['suno'] == 'chirp-goose'
    restored = client.post('/api/import-project', files={'file': ('backup.zip', raw)}).json()
    assert generation_models.selected(restored['id'])['suno'] == 'chirp-goose'
    assert all(not permissions.get(r['id'])['full'] for r in store.rows('SELECT id FROM conversations WHERE project_id=?', (restored['id'],)))


def test_revoke_cancels_background_work_and_marks_it_interrupted(client, monkeypatch):
    p = project(client); c = conversation(client, p['id']); g = save_grant(client, c['id'], full=True); scope = scope_for(p, c, g)
    entered = asyncio.Event()
    async def hold(*args):
        entered.set(); await asyncio.Event().wait(); return {}
    monkeypatch.setattr(workbench_actions, 'dispatch', hold)
    op = call(client, scope, 'accounts.refresh')
    client.portal.call(entered.wait)
    save_grant(client, c['id'], full=False)
    async def drained():
        values = [v['task'] for v in workbench_actions.RUNNING.values()]
        if values: await asyncio.gather(*values, return_exceptions=True)
    client.portal.call(drained)
    assert store.one('SELECT status FROM runs WHERE id=?', (op['operation_id'],))['status'] == 'interrupted'
    assert not workbench_actions.RUNNING


def test_codex_machine_access_is_explicit_and_preserves_tool_isolation():
    async def check():
        client = codex.CodexClient(); seen = []
        async def start(): pass
        async def rpc(method, params, **kw):
            if method == 'config/read': return {'config': {}}
            if method == 'model/list': return {'data': [{'model': 'fixture', 'isDefault': True}]}
            if method == 'thread/start': seen.append(params); return {'thread': {'id': 'fixture'}}
            if method == 'mcpServerStatus/list': return {'data': [{'name': 'workbench', 'tools': {'get_project': {}}}]} if params.get('threadId') else {'data': []}
            return {}
        client.start, client.rpc = start, rpc
        with pytest.raises(ValueError): await client.prepare('.', 'fixture', False, {}, ['get_project'], 'rules', full_access=True)
        _, runtime = await client.prepare('.', 'fixture', True, {}, ['get_project'], 'rules', full_access=True)
        assert seen[0]['sandbox'] == 'danger-full-access' and seen[0]['approvalPolicy'] == 'never'
        assert seen[0]['config']['features.shell_tool'] is True and runtime['computer_access'] is True
    asyncio.run(check())


def test_api_agents_never_receive_codex_machine_access_from_saved_grant(client, monkeypatch):
    p = project(client); c = conversation(client, p['id']); save_grant(client, c['id'], full=True, computer=True)
    seen = []
    async def stream(provider, model, inputs, rules, tools, execute_tool, **kw):
        assert '未授权整机访问' in rules
        seen.append(len(tools)); yield {'event': 'delta', 'text': '使用工作台功能'}
    monkeypatch.setattr(module.providers, 'stream', stream)
    response = client.post(f"/api/projects/{p['id']}/chat", json={'message': '检查项目', 'conversation_id': c['id'], 'agent': 'music', 'provider': 'openai', 'model': 'fixture', 'execute': True})
    assert 'done' in response.text and seen == [21]


def test_full_mcp_catalogue_uses_saved_grant_and_marks_business_calls_mutating(client):
    p = project(client); c = conversation(client, p['id']); g = save_grant(client, c['id'], full=True)
    module.AGENTS['access-fixture'] = scope_for(p, c, g)
    try:
        headers = {'authorization': 'Bearer access-fixture'}
        result = client.post('/api/internal/mcp', headers=headers, json={'method': 'tools/list'}).json()
        assert len(result['tools']) == 21
        broker = next(t for t in result['tools'] if t['name'] == 'workbench_call')
        assert broker['annotations']['readOnlyHint'] is False and broker['annotations']['destructiveHint'] is True
        other = project(client)
        assert client.post(f"/api/projects/{other['id']}/mcp/check", json={'conversation_id': c['id'], 'agent': 'music', 'execute': True}).status_code == 400
    finally: module.AGENTS.pop('access-fixture', None)


def test_stop_parent_chat_interrupts_its_pending_business_calls(client, monkeypatch):
    p = project(client); c = conversation(client, p['id']); g = save_grant(client, c['id'], full=True)
    rid = store.run_start(p['id'], 'chat:fixture', '父对话', c['id'])
    module.chat.RUNNING[rid] = {'pid': p['id'], 'task': None, 'cancelled': False}
    entered = asyncio.Event()
    async def hold(*a): entered.set(); await asyncio.Event().wait()
    monkeypatch.setattr(workbench_actions, 'dispatch', hold)
    try:
        op = call(client, scope_for(p, c, g, run_id=rid), 'accounts.refresh')
        client.portal.call(entered.wait)
        assert client.post(f'/api/runs/{rid}/cancel').status_code == 200
        async def drain():
            tasks = [v['task'] for v in workbench_actions.RUNNING.values()]
            if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        client.portal.call(drain)
        assert store.one('SELECT status FROM runs WHERE id=?', (op['operation_id'],))['status'] == 'interrupted'
    finally:
        module.chat.RUNNING.pop(rid, None)
        store.run_end(rid, 'interrupted', '测试结束')


def test_external_file_import_requires_effective_codex_machine_grant(client, tmp_path):
    p = project(client); c = conversation(client, p['id']); g = save_grant(client, c['id'], full=True, computer=True)
    outside = tmp_path / 'outside.md'; outside.write_text('Only a fixture document.')
    scope = scope_for(p, c, g)
    receipt = call(client, scope, 'asset.import_file', data={'path': str(outside)})
    result = client.portal.call(workbench_actions.operation, scope, receipt['operation_id'], 10)
    assert result['status'] == 'failed' and '工程外' in result['error']
    imported = completed(client, {**scope, 'codex_computer': True}, call(client, {**scope, 'codex_computer': True}, 'asset.import_file', data={'path': str(outside)}))
    assert imported['document']['content'] == outside.read_text()


def test_async_action_does_not_persist_one_time_authorization_urls(client, monkeypatch):
    p = project(client); c = conversation(client, p['id']); g = save_grant(client, c['id'], full=True, suno=True); scope = scope_for(p, c, g)
    url = 'https://www.suno.cn/home/#/mcp/authorize?code=fixture-private-code&source=skill'
    async def helper(*a): return {'status': 'pending', 'action': {'type': 'open_url', 'url': url}}
    monkeypatch.setattr(music, 'helper', helper)
    j = call(client, scope, 'music.draft', data={'title': '授权前草稿', 'prompt': '安静'})
    result = completed(client, scope, call(client, scope, 'music.submit', target_id=j['id']))
    assert result['action']['type'] == 'user_action_required'
    assert url not in json.dumps(store.rows('SELECT * FROM runs'))
    assert url not in json.dumps(store.rows('SELECT * FROM music_jobs'))
