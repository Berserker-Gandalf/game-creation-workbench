import asyncio
import json

import httpx
import pytest

from backend import app as module, conversations, permissions, providers, store
from backend.codex import CodexClient
from test_workbench import client, project


def test_preferences_persist_per_conversation_but_are_not_inherited(client):
    p = project(client)
    cid = conversations.create(p['id'], {'title': 'Persistent settings'})['id']
    path = '/api/conversations/' + cid + '/preferences'
    assert client.get(path).json() == {'execute': False, 'reasoning_effort': ''}
    assert client.put(path, json={'execute': True, 'reasoning_effort': 'high'}).status_code == 200
    store.init()
    assert client.get(path).json() == {'execute': True, 'reasoning_effort': 'high'}
    assert not any(permissions.get(cid)[k] for k in permissions.FLAGS)
    copied = conversations.fork(cid)
    assert conversations.preferences(copied['id']) == {'execute': False, 'reasoning_effort': ''}
    raw = client.get(f"/api/projects/{p['id']}/export").content
    restored = client.post('/api/import-project', files={'file': ('backup.zip', raw)}).json()
    for c in client.get(f"/api/projects/{restored['id']}/conversations").json():
        assert conversations.preferences(c['id']) == {'execute': False, 'reasoning_effort': ''}
    client.put(path, json={'execute': False})
    assert client.get(path).json() == {'execute': False, 'reasoning_effort': 'high'}


@pytest.mark.parametrize('payload', [{'execute': 'true'}, {'execute': 1}, {'reasoning_effort': None}, {'reasoning_effort': '../bad'}, {'full': True}])
def test_preferences_validate_without_granting_permissions(client, payload):
    cid = conversations.create(project(client)['id'], {'title': 'Validation'})['id']
    assert client.put('/api/conversations/' + cid + '/preferences', json=payload).status_code == 400
    assert conversations.preferences(cid) == {'execute': False, 'reasoning_effort': ''}


def test_saved_execution_is_used_until_disabled_and_readonly_override_is_temporary(client, monkeypatch):
    pid = project(client)['id']
    cid = conversations.create(pid, {'title': 'Execution', 'provider': 'openai', 'model': 'fixture'})['id']
    conversations.save_preferences(cid, {'execute': True, 'reasoning_effort': 'high'})
    calls = []
    async def stream(provider, model, messages, rules, tools, invoke, **options):
        calls.append(('create_document' in {t['name'] for t in tools}, options))
        yield {'event': 'delta', 'text': 'fixture'}
    monkeypatch.setattr(module.providers, 'stream', stream)
    payload = {'conversation_id': cid, 'message': 'Continue'}
    for overrides in ({}, {'execute': False}, {}):
        assert '"event": "done"' in client.post(f'/api/projects/{pid}/chat', json={**payload, **overrides}).text
    conversations.save_preferences(cid, {'execute': False})
    client.post(f'/api/projects/{pid}/chat', json=payload)
    assert [v[0] for v in calls] == [True, False, True, False]
    assert all(v[1] == {'reasoning_effort': 'high'} for v in calls)
    assert all(json.loads(r['runtime'])['reasoning_effort'] == 'high' for r in store.rows('SELECT runtime FROM runs'))


@pytest.mark.parametrize('provider,effort', [('openai', 'high'), ('deepseek', 'max'), ('openai', '')])
def test_responses_effort_reaches_every_tool_loop_request(monkeypatch, provider, effort):
    payloads = []
    def upstream(request):
        payloads.append(json.loads(request.content))
        output = [{'type': 'function_call', 'name': 'get_project', 'call_id': 'call', 'arguments': '{}'}] if len(payloads) == 1 else []
        event = {'type': 'response.completed', 'response': {'output': output}}
        return httpx.Response(200, text='data: ' + json.dumps(event) + '\n\n')
    original = httpx.AsyncClient
    monkeypatch.setattr(providers, 'config', lambda p: ('https://fixture.invalid', 'fixture'))
    monkeypatch.setattr(providers.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(upstream), **kw))
    async def exercise():
        async def tool(*args): return {'fixture': True}
        return [event async for event in providers.stream(provider, 'fixture', [], 'rules', [], tool, reasoning_effort=effort)]
    asyncio.run(exercise())
    assert len(payloads) == 2
    for p in payloads:
        assert (p.get('reasoning') == {'effort': effort}) if effort else ('reasoning' not in p)
    with pytest.raises(ValueError): providers.reasoning('deepseek', 'medium')


def test_codex_effort_uses_runtime_catalog_and_turn_parameter():
    async def exercise(effort):
        c, calls = CodexClient(), []
        async def start(): pass
        async def prepare(*args, **kwargs): return 'thread', {'verified': True}
        async def rpc(method, params, **kwargs):
            calls.append((method, params))
            if method == 'model/list': return {'data': [{'model': 'fixture', 'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}]}
            if method == 'turn/start':
                await c.subscribers['thread'].put({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}})
                return {'turn': {'id': 'turn'}}
            return {}
        c.start, c.prepare, c.rpc = start, prepare, rpc
        if effort == 'low':
            with pytest.raises(ValueError, match='推理强度'):
                _ = [e async for e in c.stream('.', 'prompt', 'fixture', bridge_config={'fixture': True}, allowed_tools=[], reasoning_effort=effort)]
            assert not any(m == 'turn/start' for m, _ in calls)
        else:
            events = [e async for e in c.stream('.', 'prompt', 'fixture', bridge_config={'fixture': True}, allowed_tools=[], reasoning_effort=effort)]
            assert next(p for m, p in calls if m == 'turn/start')['effort'] == 'high'
            assert events[0]['runtime']['reasoning_effort'] == 'high'
    asyncio.run(exercise('high'))
    asyncio.run(exercise('low'))
