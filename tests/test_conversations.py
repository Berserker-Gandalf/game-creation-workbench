import json
import asyncio
import io
import sqlite3
import zipfile

from backend import app as module, store
from test_workbench import client, project


def test_conversation_history_memory_fork_and_cross_project_rejection(client, monkeypatch):
    p, other = project(client), project(client)
    r = client.post(f"/api/projects/{p['id']}/conversations", json={'agent': 'director', 'title': '设计会话'})
    assert r.status_code == 200, r.text
    conversation = r.json()
    cid = conversation['id']
    client.patch('/api/conversations/' + cid, json={'memory': '明确采用：三间房、无昼夜系统'})
    for i in range(40):
        store.execute('INSERT INTO messages (id,project_id,role,content,provider,created,conversation_id) VALUES (?,?,?,?,?,?,?)',
                      (store.uid(), p['id'], 'user' if i % 2 == 0 else 'assistant', 'FIRST_DECISION' if i == 0 else f'later {i}', 'openai', store.now(), cid))
    captured = []
    async def stream(provider, model, messages, instructions, tools, execute_tool):
        captured.append(messages)
        yield {'event': 'delta', 'text': '测试回复'}
    monkeypatch.setattr(module.providers, 'stream', stream)
    payload = {'conversation_id': cid, 'provider': 'openai', 'model': 'fixture', 'message': '继续讨论'}
    assert '"event": "done"' in client.post(f"/api/projects/{p['id']}/chat", json=payload).text
    assert 'FIRST_DECISION' in json.dumps(captured[0])
    assert '无昼夜系统' in json.dumps(captured[0], ensure_ascii=False)
    assert client.post(f"/api/projects/{other['id']}/chat", json=payload).status_code == 400
    found = client.get('/api/conversations/' + cid + '/messages', params={'q': 'FIRST_DECISION'}).json()
    assert len(found) == 1
    fork = client.post('/api/conversations/' + cid + '/fork').json()
    assert fork['id'] != cid and fork['memory'] == '明确采用：三间房、无昼夜系统'
    assert len(client.get('/api/conversations/' + fork['id'] + '/messages', params={'limit': 100}).json()) == 42
    client.patch('/api/conversations/' + cid, json={'archived': True})
    assert client.post(f"/api/projects/{p['id']}/chat", json=payload).status_code == 400


def test_large_documents_are_retrievable_without_blocking_chat(client, monkeypatch):
    p = project(client)
    d = client.post(f"/api/projects/{p['id']}/documents", json={'title': '完整规范', 'content': 'x' * 100100}).json()
    async def stream(provider, model, messages, instructions, tools, execute_tool):
        assert 'read_document' in {t['name'] for t in tools}
        context = json.loads(messages[0]['content'].split('\n', 1)[1])
        assert context['documents'][0]['requires_read']
        result = await execute_tool('read_document', {'document_id': d['id'], 'offset': 100000, 'limit': 2000})
        assert result['content'] == 'x' * 100 and result['next_offset'] is None
        yield {'event': 'delta', 'text': '已读取完整规范最后一段'}
    monkeypatch.setattr(module.providers, 'stream', stream)
    result = client.post(f"/api/projects/{p['id']}/chat", json={'provider': 'openai', 'model': 'fixture', 'message': '读取规范末尾'})
    assert '"event": "done"' in result.text
    state = store.snapshot(p['id'])
    events = client.get('/api/runs/' + state['runs'][0]['id'] + '/tools').json()
    assert events[0]['tool'] == 'read_document' and events[0]['status'] == 'completed'


def test_backup_preserves_conversations_model_usage_and_tool_journal(client, monkeypatch):
    p = project(client)
    cid = client.post(f"/api/projects/{p['id']}/conversations", json={'title': '独立会话', 'agent': 'music'}).json()['id']
    client.patch('/api/conversations/' + cid, json={'memory': '音乐决定：无鼓点'})
    async def stream(provider, model, messages, instructions, tools, execute_tool):
        await execute_tool('get_project', {})
        yield {'event': 'delta', 'text': '已核对项目'}
        yield {'event': 'usage', 'usage': {'total_tokens': 35}, 'request': {'model': model}}
    monkeypatch.setattr(module.providers, 'stream', stream)
    client.post(f"/api/projects/{p['id']}/chat", json={'conversation_id': cid, 'agent': 'music', 'provider': 'openai', 'model': 'fixture-B', 'message': '继续'})
    raw = client.get(f"/api/projects/{p['id']}/export").content
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert json.loads(archive.read('project.json'))['format'] == 10
    r = client.post('/api/import-project', files={'file': ('backup.zip', raw)})
    assert r.status_code == 200, r.text
    copied = client.get(f"/api/projects/{r.json()['id']}/conversations", params={'agent': 'music'}).json()[0]
    assert copied['memory'] == '音乐决定：无鼓点' and copied['id'] != cid
    messages = client.get('/api/conversations/' + copied['id'] + '/messages').json()
    assert len(messages) == 2 and messages[0]['model'] == 'fixture-B'
    run = client.get('/api/projects/' + r.json()['id']).json()['runs'][0]
    assert run['conversation_id'] == copied['id'] and run['model'] == 'fixture-B'
    assert json.loads(run['usage'])['total_tokens'] == 35
    event = client.get('/api/runs/' + run['id'] + '/tools').json()[0]
    assert event['conversation_id'] == copied['id'] and event['tool'] == 'get_project'


def test_legacy_database_migration_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    with sqlite3.connect(tmp_path / 'workbench.sqlite3') as c:
        c.executescript('''CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT,engine TEXT,root TEXT,brief TEXT,created TEXT);
        CREATE TABLE messages(id TEXT PRIMARY KEY,project_id TEXT,role TEXT,content TEXT,provider TEXT,created TEXT);
        CREATE TABLE runs(id TEXT PRIMARY KEY,project_id TEXT,kind TEXT,status TEXT,detail TEXT,usage TEXT,created TEXT,updated TEXT);''')
        c.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)', ('p', '历史工程', 'unreal', str(tmp_path), '', store.now()))
        c.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)', ('m', 'p', 'user', '原有音乐决定', 'codex:music', store.now()))
    store.init()
    first = store.one('SELECT * FROM messages WHERE id=?', ('m',))
    store.init()
    assert first == store.one('SELECT * FROM messages WHERE id=?', ('m',))
    sessions = store.rows('SELECT * FROM conversations')
    assert len(sessions) == 1 and sessions[0]['agent'] == 'music'
    assert first['conversation_id'] == sessions[0]['id'] and first['content'] == '原有音乐决定'


def test_cancel_is_explicit_and_preserves_partial_response(client, monkeypatch):
    p = project(client)
    async def exercise():
        from backend import chat
        class Request:
            async def json(self): return {'provider': 'openai', 'model': 'fixture', 'message': '开始'}
            async def is_disconnected(self): return False
        async def stream(*args):
            yield {'event': 'delta', 'text': '已输出片段'}
            await asyncio.Event().wait()
        monkeypatch.setattr(module.providers, 'stream', stream)
        response = await chat.handle(p['id'], Request())
        iterator = response.body_iterator
        event = json.loads((await anext(iterator))[6:])
        while json.loads((await anext(iterator))[6:])['event'] != 'delta': pass
        pending = asyncio.create_task(anext(iterator))
        await asyncio.sleep(0)
        result = chat.cancel(event['run_id'])
        assert result['cancelling']
        try: await pending
        except asyncio.CancelledError: pass
        assert p['id'] not in chat.ACTIVE and not chat.RUNNING
        assert store.one('SELECT status FROM runs WHERE id=?', (event['run_id'],))['status'] == 'interrupted'
        assert '已输出片段' in store.rows("SELECT content FROM messages WHERE role='assistant'")[0]['content']
    asyncio.run(exercise())


def test_denied_tool_attempt_is_recorded_without_running_it(client, monkeypatch):
    p = project(client)
    async def stream(provider, model, messages, instructions, tools, execute_tool):
        try:
            await execute_tool('create_document', {'title': '未授权', 'content': '不会保存', 'api_key': 'fixture-value'})
        except ValueError:
            pass
        yield {'event': 'delta', 'text': '讨论模式不能保存文档'}
    monkeypatch.setattr(module.providers, 'stream', stream)
    client.post(f"/api/projects/{p['id']}/chat", json={'provider': 'openai', 'model': 'fixture', 'message': '讨论'})
    run = store.snapshot(p['id'])['runs'][0]
    events = client.get('/api/runs/' + run['id'] + '/tools').json()
    assert events[0]['status'] == 'failed'
    assert json.loads(events[0]['arguments'])['api_key'] == '[不记录]'
    assert store.snapshot(p['id'])['documents'] == []
