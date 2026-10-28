import json
import subprocess
import sys

import httpx

from backend import app as module, assets, providers, store
from test_workbench import client, project


def test_engine_write_binds_checked_asset_to_actual_target(client, tmp_path, monkeypatch):
    root = tmp_path / 'Unity'
    (root / 'Assets').mkdir(parents=True)
    path = root / 'Assets/Selected.mat'
    path.write_text('fixture material', encoding='utf-8')
    p = project(client, engine='unity', root=str(root))
    a = assets.register(p['id'], path)
    calls = []
    async def command(pid, op, **params):
        calls.append(params); return {'saved': True}
    monkeypatch.setattr(module.engines, 'command', command)
    payload = {'op': 'set_material_color', 'asset_id': a['id'], 'expected_hash': assets.digest(path),
               'path': 'Assets/Other.mat', 'name': '_Color', 'color': [1, 0, 0, 1]}
    assert client.post(f"/api/projects/{p['id']}/engine/command", json=payload).status_code == 400
    assert not calls
    payload['path'] = 'Assets/Selected.mat'
    assert client.post(f"/api/projects/{p['id']}/engine/command", json=payload).status_code == 200
    assert calls[0]['path'] == 'Assets/Selected.mat'


def test_usage_accumulates_requests_and_verification_is_model_specific(client, monkeypatch):
    p = project(client)
    store.set_setting('openai_model', 'configured-A')
    original = httpx.AsyncClient
    calls = []
    def upstream(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            output = [{'type': 'function_call', 'name': 'create_task', 'call_id': 'fixture-call',
                       'arguments': json.dumps({'title': '测试任务', 'detail': '验收'})}]
            usage = {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
            events = []
        else:
            output = [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '已创建'}]}]
            usage = {'input_tokens': 12, 'output_tokens': 8, 'total_tokens': 20}
            events = [{'type': 'response.output_text.delta', 'delta': '已创建'}]
        events.append({'type': 'response.completed', 'response': {'id': 'fixture-' + str(len(calls)), 'output': output, 'usage': usage}})
        return httpx.Response(200, text=''.join('data: ' + json.dumps(e) + '\n\n' for e in events))
    monkeypatch.setattr(providers, 'config', lambda p: ('https://fixture.invalid/v1', 'fixture-key'))
    monkeypatch.setattr(providers.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(upstream), **kw))
    result = client.post(f"/api/projects/{p['id']}/chat", json={'provider': 'openai', 'model': 'override-B', 'message': '创建任务', 'execute': True})
    assert '"event": "done"' in result.text
    state = store.snapshot(p['id'])
    usage = json.loads(state['runs'][0]['usage'])
    assert usage['total_tokens'] == 35 and len(usage['requests']) == 2
    assert client.get('/api/bootstrap').json()['providers']['openai']['verified'] is False
    assert state['runs'][0]['model'] == 'override-B'


def test_mcp_bad_message_does_not_kill_bridge_and_unknown_methods_are_errors():
    lines = ['not-json', json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}}),
             json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'fixture/unknown'})]
    result = subprocess.run([sys.executable, str(store.ROOT / 'backend/mcp_bridge.py')], input='\n'.join(lines) + '\n',
                            text=True, encoding='utf-8', capture_output=True)
    assert result.returncode == 0, result.stderr
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert replies[0]['error']['code'] == -32700 and replies[0]['id'] is None
    assert replies[1]['result']['serverInfo']['version'] == __import__('backend').__version__
    assert replies[2]['error']['code'] == -32601
