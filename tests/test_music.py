import json

import pytest

from backend import app as module, music, store
from test_workbench import client, project


@pytest.fixture
def skill(monkeypatch):
    calls = []
    async def helper(*args):
        calls.append(args)
        if args == ('auth', 'verify'):
            return {'status': 'authorized'}
        if args[0] == 'account':
            return {'nickname': 'fixture', 'points': 100, 'vip_status': 'test', 'private_id': 'NEVER_RETURN'}
        if args[:2] == ('request', 'POST'):
            return {'serial_nos': ['task-1', 'task-2']}
        if args[:2] == ('request', 'GET'):
            return {'tasks': [{'serial_no': 'task-1', 'status': 'success', 'play_url': 'https://example.com/1.mp3'},
                              {'serial_no': 'task-2', 'status': 'success', 'play_url': 'https://example.com/2.mp3'}]}
        return {'status': 'authorized'}
    monkeypatch.setattr(music, 'helper', helper)
    return calls


def draft(client, pid):
    response = client.post(f'/api/projects/{pid}/music', json={'title': '探索配乐', 'prompt': '木吉他、安静、适合探索', 'tags': '温暖', 'instrumental': True})
    assert response.status_code == 200, response.text
    return response.json()


def test_draft_is_free_and_submit_requires_confirmation_and_cannot_repeat(client, skill):
    p = project(client)
    j = draft(client, p['id'])
    assert not skill and j['status'] == 'draft'
    url = '/api/music/jobs/' + j['id'] + '/submit'
    assert client.post(url, json={}).status_code == 400
    assert client.post(url, json={'confirmed': 'true'}).status_code == 400
    assert not skill
    assert client.post(url, json={'confirmed': True}).status_code == 200
    assert client.post(url, json={'confirmed': True}).status_code == 400
    submissions = [args for args in skill if args[:2] == ('request', 'POST')]
    assert len(submissions) == 1
    assert json.loads(submissions[0][3])['instrumental'] is True
    refreshed = client.post('/api/music/jobs/' + j['id'] + '/refresh')
    assert refreshed.json()['status'] == 'completed'
    assert len(json.loads(refreshed.json()['result'])['tasks']) == 2


def test_unauthorized_draft_does_not_generate_or_persist_authorization_url(client, monkeypatch):
    p = project(client)
    j = draft(client, p['id'])
    calls = []
    url = 'https://www.suno.cn/home/#/mcp/authorize?code=fixture&source=skill'
    async def pending(*args):
        calls.append(args)
        return {'status': 'pending', 'action': {'type': 'open_url', 'url': url}}
    monkeypatch.setattr(music, 'helper', pending)
    result = client.post('/api/music/jobs/' + j['id'] + '/submit', json={'confirmed': True})
    assert result.json()['action']['url'] == url
    assert calls == [('auth', 'verify')]
    assert music.job(j['id'])['status'] == 'draft'
    assert url not in json.dumps(store.rows('SELECT * FROM music_jobs'))
    assert url not in json.dumps(store.snapshot(p['id'])['runs'])


def test_ambiguous_submission_survives_restart_without_replay(client, monkeypatch):
    p = project(client)
    j = draft(client, p['id'])
    calls = []
    async def lost(*args):
        calls.append(args)
        if args[0] == 'auth': return {'status': 'authorized'}
        raise ValueError('连接中断，结果未知')
    monkeypatch.setattr(music, 'helper', lost)
    url = '/api/music/jobs/' + j['id'] + '/submit'
    assert client.post(url, json={'confirmed': True}).status_code == 400
    assert music.job(j['id'])['status'] == 'unknown'
    store.init()
    assert client.post(url, json={'confirmed': True}).status_code == 400
    assert len(calls) == 2
    store.execute("UPDATE music_jobs SET status='submitting' WHERE id=?", (j['id'],))
    store.init()
    assert music.job(j['id'])['status'] == 'unknown'


def test_music_agent_can_only_draft_and_is_project_scoped(client, skill):
    p, other = project(client), project(client)
    module.AGENTS['music-fixture'] = {'pid': p['id'], 'write': True, 'agent': 'music'}
    try:
        headers = {'authorization': 'Bearer music-fixture'}
        def call(name, args):
            return client.post('/api/internal/mcp', headers=headers, json={'method': 'tools/call', 'params': {'name': name, 'arguments': args}}).json()
        tools = client.post('/api/internal/mcp', headers=headers, json={'method': 'tools/list'}).json()['tools']
        names = {t['name'] for t in tools}
        assert 'draft_music' in names and 'edit_image' not in names
        assert not any('submit' in name for name in names)
        assert call('edit_image', {})['isError']
        created = call('draft_music', {'title': '关卡配乐', 'prompt': '明亮木吉他', 'tags': '', 'instrumental': True})
        assert not created.get('isError') and len(music.jobs(p['id'])) == 1 and not music.jobs(other['id'])
        module.AGENTS['music-fixture']['write'] = False
        assert call('draft_music', {'title': '禁止', 'prompt': '不可写入'})['isError']
        assert not skill
    finally:
        module.AGENTS.pop('music-fixture')


def test_music_backup_preserves_remote_ids_but_cannot_replay_restored_draft(client, skill):
    p = project(client)
    submitted = draft(client, p['id'])
    client.post('/api/music/jobs/' + submitted['id'] + '/submit', json={'confirmed': True})
    draft(client, p['id'])
    raw = client.get(f"/api/projects/{p['id']}/export").content
    restored = client.post('/api/import-project', files={'file': ('music.zip', raw)}).json()
    records = client.get(f"/api/projects/{restored['id']}/music").json()
    assert all(r['status'] == 'restored' for r in records)
    assert any(json.loads(r['serials']) == ['task-1', 'task-2'] for r in records)
    before = len(skill)
    for record in records:
        assert client.post('/api/music/jobs/' + record['id'] + '/submit', json={'confirmed': True}).status_code == 400
    assert len(skill) == before


def test_account_is_queried_only_after_verified_authorization_and_filters_private_fields(client, skill, monkeypatch):
    # Exercise the authorization branch without depending on a locally installed Skill.
    from unittest.mock import patch
    with patch('backend.music.Path.is_file', return_value=True):
        monkeypatch.setattr(music, 'installation', lambda: (store.ROOT, 'fixture-node'))
        result = client.post('/api/music/authorize').json()
    assert skill == [('auth', 'verify'), ('account',)]
    assert result['account']['points'] == 100 and 'NEVER_RETURN' not in json.dumps(result)


def test_music_chat_has_separate_history_and_never_receives_paid_tool(client, monkeypatch):
    p = project(client)
    store.execute('INSERT INTO messages (id,project_id,role,content,provider,created) VALUES (?,?,?,?,?,?)', (store.uid(), p['id'], 'user', 'DIRECTOR_ONLY_HISTORY', 'openai', store.now()))
    captured = []
    async def stream(provider, model, messages, instructions, tools, execute_tool):
        captured.append({'messages': messages, 'instructions': instructions, 'tools': tools})
        yield {'event': 'delta', 'text': '音乐负责人仅保存方案，等待确认'}
    monkeypatch.setattr(module.providers, 'stream', stream)
    response = client.post(f"/api/projects/{p['id']}/chat", json={'provider': 'openai', 'agent': 'music', 'model': 'fixture', 'message': '讨论温暖的探索配乐'})
    assert 'done' in response.text
    assert 'DIRECTOR_ONLY_HISTORY' not in json.dumps(captured[0]['messages'])
    assert '专职音乐负责人' in captured[0]['instructions']
    assert all(t['name'] not in ('edit_image', 'submit_music') for t in captured[0]['tools'])
    assert store.snapshot(p['id'])['messages'][-1]['provider'] == 'openai:music'
