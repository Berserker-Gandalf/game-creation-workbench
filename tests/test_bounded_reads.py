import asyncio
import contextlib
import json

import pytest

from backend import agent_tools, catalog, conversations, intake, store
from test_workbench import client, project
from test_agent_access import call, conversation, save_grant, scope_for


def fixture_rows(pid, n=121):
    stamp = store.now()
    cid = conversations.create(pid, {})['id']
    with store.db() as c:
        c.executemany('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)', [(f'a{i}', pid, f'资源{i}', f'fixture{i}', f'fixture{i}', 'image', '[]', stamp) for i in range(n)])
        c.executemany('INSERT INTO documents VALUES (?,?,?,?,?,?,?)', [(f'd{i}', pid, f'规范{i}', '不应首屏读取' * 2000, 1, 'draft', stamp) for i in range(n)])
        c.executemany('INSERT INTO messages (id,project_id,role,content,provider,created,conversation_id) VALUES (?,?,?,?,?,?,?)', [(f'm{i}', pid, 'user', f'原文{i}' + '历史' * 3000, 'fixture', stamp, cid) for i in range(n)])
    return cid


def test_workspace_and_asset_tool_never_use_full_snapshot(client, monkeypatch):
    p = project(client); fixture_rows(p['id'])
    def forbidden(*a, **kw): raise AssertionError('Unbounded snapshot used')
    monkeypatch.setattr(store, 'snapshot', forbidden)
    value = client.get(f'/api/projects/{p["id"]}/workspace').json()
    assert value['counts']['documents'] == value['counts']['assets'] == 121
    assert value['documents'] == value['assets'] == value['messages'] == value['tasks'] == []
    assert len(json.dumps(value, ensure_ascii=False)) < 5000
    page = asyncio.run(agent_tools.execute(p['id'], False, 'list_assets', {}))
    assert len(page['items']) == 50 and page['next_before'] and page['total'] == 121
    assert all(set(a) == {'id', 'name', 'kind'} for a in page['items'])


def test_catalog_cursors_survive_insert_delete_and_equal_timestamps(client):
    p = project(client); fixture_rows(p['id'])
    first = catalog.page(p['id'], 'assets', limit=50)
    with store.db() as c:
        c.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)', ('new', p['id'], '新登记', '', '', 'image', '[]', store.now()))
        c.execute('DELETE FROM assets WHERE id=?', (first['items'][0]['id'],))
    found = [a['id'] for a in first['items']]
    cursor = first['next_before']
    while cursor:
        value = catalog.page(p['id'], 'assets', limit=50, before=cursor)
        found += [a['id'] for a in value['items']]; cursor = value['next_before']
    assert len(found) == len(set(found)) == 121 and 'new' not in found
    assert catalog.page(p['id'], 'assets', query='新登记')['items'][0]['id'] == 'new'
    assert catalog.page(p['id'], 'assets', query='%')['items'] == []


def test_document_metadata_and_explicit_body_ownership(client):
    p = project(client); fixture_rows(p['id']); other = project(client)
    value = client.get(f'/api/projects/{p["id"]}/catalog/documents?limit=50').json()
    assert len(value['items']) == 50 and all('content' not in d for d in value['items'])
    assert value['items'][0]['chars'] > 10000
    assert client.get(f'/api/projects/{p["id"]}/documents/d120').json()['content'].startswith('不应首屏读取')
    assert client.get(f'/api/projects/{other["id"]}/documents/d120').status_code == 400
    assert client.get(f'/api/projects/{p["id"]}/catalog/credentials').status_code == 400
    for params in ({'limit': 101}, {'limit': 0}, {'before': -1}, {'offset': -1}, {'before': 100, 'offset': 1}, {'q': 'x' * 201}):
        assert client.get(f'/api/projects/{p["id"]}/catalog/assets', params=params).status_code == 400


def test_model_history_bounds_sql_rows_and_oversized_message_with_retrieval(client, monkeypatch):
    p = project(client); cid = fixture_rows(p['id'])
    before = store.one('SELECT content FROM messages WHERE id=?', ('m120',))['content']
    trace, original = [], store.db
    @contextlib.contextmanager
    def observed():
        with original() as c:
            c.set_trace_callback(trace.append); yield c
    monkeypatch.setattr(store, 'db', observed)
    result, omitted = conversations.model_history(cid, budget=2000)
    assert len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))) <= 2000
    assert len(result) == 1 and omitted == 120 and 'm120' in result[0]['content'] and 'read_history' in result[0]['content']
    assert any('LIMIT 100' in sql and 'substr(content' in sql for sql in trace)
    assert store.one('SELECT content FROM messages WHERE id=?', ('m120',))['content'] == before
    pieces, offset = [], 0
    while offset is not None:
        value = conversations.read_message(cid, 'm120', offset, 1000)
        pieces.append(value['content']); offset = value['next_offset']
    assert ''.join(pieces) == before


def test_history_window_pagination_and_cross_session_record(client):
    p = project(client); cid = fixture_rows(p['id'])
    values, cursor = [], 0
    while cursor is not None:
        result = client.get(f'/api/conversations/{cid}/window', params={'before': cursor}).json()
        assert len(result['items']) <= 30 and all(len(m['content']) <= 4000 and m['truncated'] for m in result['items'])
        values += [m['id'] for m in result['items']]; cursor = result['next_before']
    assert len(values) == len(set(values)) == 121
    other = conversations.create(p['id'], {})['id']
    assert client.get(f'/api/conversations/{other}/messages/m120').status_code == 400
    assert client.get(f'/api/conversations/{cid}/messages/m120?offset=-1').status_code == 400


def test_agent_project_catalog_is_paged_before_serialization(client, monkeypatch):
    p = project(client); fixture_rows(p['id'])
    def forbidden(*a, **kw): raise AssertionError('Full snapshot used before context selection')
    monkeypatch.setattr(store, 'snapshot', forbidden)
    packet = asyncio.run(agent_tools.execute(p['id'], False, 'get_project', {'section': 'documents', 'offset': 100, 'limit': 5}))
    assert len(packet['documents']) == 5 and packet['context']['pages']['documents']['total'] == 121
    assert packet['context']['pages']['documents']['offset'] == 100
    assert all(d['requires_read'] for d in packet['documents'])
    found = asyncio.run(agent_tools.execute(p['id'], False, 'get_project', {'section': 'assets', 'query': '资源120'}))
    assert found['context']['pages']['assets']['total'] == 121 and found['context']['pages']['assets']['matches'] == 1


def test_task_board_pages_output_but_checks_full_project(client):
    p = project(client)
    with store.db() as c:
        c.executemany('INSERT INTO tasks VALUES (?,?,?,?,?,?,?)', [(f't{i}', p['id'], f'任务{i}', 'todo', '', '', store.now()) for i in range(101)])
    result = client.get(f'/api/projects/{p["id"]}/task-board?limit=48').json()
    assert len(result['items']) == 48 and result['total_tasks'] == 101 and result['accepted_tasks'] == 0
    more = client.get(f'/api/projects/{p["id"]}/task-board', params={'limit': 48, 'before': result['next_before']}).json()
    assert not set(t['id'] for t in result['items']) & set(t['id'] for t in more['items'])
    assert all('review_token' in t and 'asset_links' in t for t in more['items'])


def test_asset_inventory_filter_does_not_load_document_bodies(client):
    p = project(client); fixture_rows(p['id'], n=2)
    files = [{'asset_id': 'a0', 'path': 'Concept/示例.png', 'category': 'art', 'status': 'present'}]
    store.execute('INSERT INTO project_intakes VALUES (?,?,?,?,?)', (p['id'], 'd0', '{}', json.dumps(files), store.now()))
    result = catalog.page(p['id'], 'assets', query='Concept', category='art')
    assert result['total'] == 1 and result['items'][0]['id'] == 'a0'
    assert result['items'][0]['source_status'] == 'present' and 'versions' not in result['items'][0]


def test_workspace_defers_runtime_body_until_explicit_inspection(client):
    p = project(client)
    rid = store.run_start(p['id'], 'fixture', '仅模拟运行记录')
    store.execute('UPDATE runs SET runtime=? WHERE id=?', (json.dumps({'fixture': 'x' * 100000}), rid))
    value = client.get(f'/api/projects/{p["id"]}/workspace').json()
    assert 'runtime' not in value['runs'][0] and len(json.dumps(value)) < 10000
    assert len(client.get('/api/runs/' + rid).json()['runtime']) > 100000


def test_project_file_listing_uses_sql_page_not_full_inventory(client, monkeypatch):
    p = project(client); fixture_rows(p['id'], n=1)
    files = [{'path': f'Code/文件{i}.cs', 'category': 'code', 'status': 'present'} for i in range(120)]
    store.execute('INSERT INTO project_intakes VALUES (?,?,?,?,?)', (p['id'], 'd0', '{}', json.dumps(files), store.now()))
    def forbidden(*a, **kw): raise AssertionError('Full inventory loaded for one page')
    monkeypatch.setattr(intake, 'current', forbidden)
    result = intake.file_list(p['id'], '文件', 'code', 60, 60)
    assert result['total'] == 120 and len(result['items']) == 60
    assert result['items'][0]['path'] == 'Code/文件60.cs'


def test_full_access_project_action_also_uses_bounded_workspace(client, monkeypatch):
    p = project(client); fixture_rows(p['id'])
    c = conversation(client, p['id']); grant = save_grant(client, c['id'], full=True)
    def forbidden(*a, **kw): raise AssertionError('Full-access action must not bypass bounded project reads')
    monkeypatch.setattr(store, 'snapshot', forbidden)
    value = call(client, scope_for(p, c, grant), 'project.get')
    assert value['project']['id'] == p['id'] and value['counts']['assets'] == 121 and value['assets'] == []
