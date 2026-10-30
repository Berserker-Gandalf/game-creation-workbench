import asyncio
import hashlib
import io
import json
import socket
import time
import wave
import zipfile
from pathlib import Path

import httpx
import pytest

from backend import agent_tools, assets, audio_import, deliveries, jobs, music, store
from test_agent_access import conversation, save_grant, scope_for
from test_workbench import client, image_bytes, project


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(8000); f.writeframes(b'\0\0' * 1600)
    return stream.getvalue()


def seed(client, monkeypatch):
    p = project(client)
    j = music.draft(p['id'], {'title': '探索配乐', 'prompt': '安静木吉他'})
    store.execute("UPDATE music_jobs SET status='completed',serials=?,result=? WHERE id=?", (json.dumps(['track-one', 'track-two']), json.dumps({'tasks': [{'serial_no': s, 'status': 'success'} for s in ('track-one', 'track-two')]}), j['id']))
    calls = []
    async def helper(*args):
        calls.append(args)
        if args[0] == 'auth': return {'status': 'authorized'}
        ids = args[2].split('/task/')[1].split('?')[0].split(',')
        return {'tasks': [{'serial_no': s, 'status': 'success', 'play_url': 'https://audio.example/track.wav?sig=fixture'} for s in ids]}
    async def download(url, path): path.write_bytes(wav_bytes())
    monkeypatch.setattr(music, 'helper', helper); monkeypatch.setattr(audio_import, 'download', download)
    return p, j, calls


def command(client, pid, jid, action='import', **extra):
    return client.post(f'/api/projects/{pid}/jobs/commands', json={'kind': 'music', 'id': jid, 'command': action, **({'serial_no': 'track-one', 'confirmed': True} if action == 'import' else {}), **extra})


def finish(client, pid, operation):
    for _ in range(150):
        result = client.get(f'/api/projects/{pid}/jobs/inspect', params={'kind': 'operation', 'id': operation['id']}).json()
        if result['details']['status'] not in ('queued', 'running'): return result
        time.sleep(.02)
    raise AssertionError('Local queue did not finish')


def pin(client, aid):
    info = client.get(f'/api/assets/{aid}/info').json()
    return {'asset_id': aid, 'version_index': info['version_index'], 'sha256': info['hash']}


def test_music_import_queue_provenance_and_idempotent_asset_registration(client, monkeypatch):
    p, j, calls = seed(client, monkeypatch)
    result = finish(client, p['id'], command(client, p['id'], j['id']).json())
    assert result['details']['status'] == 'succeeded', result
    outputs = client.get(f"/api/music/jobs/{j['id']}/outputs").json()
    assert len(outputs) == 1 and outputs[0]['mime'] == 'audio/wav'
    aid = outputs[0]['asset_id']
    info = client.get(f'/api/assets/{aid}/info').json()
    assert info['hash'] == hashlib.sha256(wav_bytes()).hexdigest() and info['origin']['job_id'] == j['id']
    assert assets.file_for(assets.asset(aid)).read_bytes() == wav_bytes()
    again = finish(client, p['id'], command(client, p['id'], j['id']).json())
    assert again['details']['status'] == 'succeeded' and len(store.rows('SELECT * FROM assets')) == 1
    assert not any(a[:2] == ('request', 'POST') for a in calls)
    assert 'sig=fixture' not in json.dumps(store.rows('SELECT * FROM work_jobs'))
    finish(client, p['id'], command(client, p['id'], j['id'], serial_no='track-two').json())
    values = jobs.list_jobs(p['id'], kind='music')['items']
    assert values[0]['state'] == 'succeeded'


def test_queue_confirmation_project_scope_duplicates_and_stop_without_cloud_cancel(client, monkeypatch):
    p, j, calls = seed(client, monkeypatch); other = project(client)
    async def slow(url, path): await asyncio.sleep(10)
    monkeypatch.setattr(audio_import, 'download', slow)
    assert command(client, p['id'], j['id'], confirmed=False).status_code == 400
    assert command(client, other['id'], j['id']).status_code == 400
    assert command(client, p['id'], j['id'], serial_no='foreign').status_code == 400
    one = command(client, p['id'], j['id']).json()
    assert command(client, p['id'], j['id']).json()['id'] == one['id']
    two = command(client, p['id'], j['id'], 'query').json()
    assert client.post(f"/api/projects/{p['id']}/jobs/stop", json={'kind': 'operation', 'id': two['id']}).status_code == 200
    assert finish(client, p['id'], two)['details']['status'] == 'cancelled'
    assert client.post(f"/api/projects/{p['id']}/jobs/stop", json={'kind': 'operation', 'id': one['id']}).status_code == 200
    assert finish(client, p['id'], one)['details']['status'] == 'cancelled'
    assert music.job(j['id'])['status'] == 'completed' and not music.outputs(j['id'])
    assert not any(a[:2] == ('request', 'POST') for a in calls)
    assert client.post(f"/api/projects/{other['id']}/jobs/stop", json={'kind': 'operation', 'id': one['id']}).status_code == 400


def test_bad_audio_never_registers_partial_file_or_changes_generation(client, monkeypatch):
    p, j, calls = seed(client, monkeypatch)
    async def fake_html(url, path): path.write_bytes(b'<html>not an audio file</html>')
    monkeypatch.setattr(audio_import, 'download', fake_html)
    result = finish(client, p['id'], command(client, p['id'], j['id']).json())
    assert result['details']['status'] == 'failed'
    assert not store.rows('SELECT * FROM assets') and not music.outputs(j['id'])
    assert not list(store.project_dir(p['id']).rglob('*.part'))
    assert music.job(j['id'])['status'] == 'completed'


def test_audio_validator_pcm_truncation_and_mp3_frame_metadata(tmp_path):
    path = tmp_path / 'file.part'; path.write_bytes(wav_bytes())
    assert audio_import.verify(path)['duration'] == .2
    path.write_bytes(wav_bytes()[:-8])
    with pytest.raises(ValueError): audio_import.verify(path)
    path.write_bytes((b'\xff\xfb\x90\x00' + b'\0' * 413) * 20)
    assert audio_import.verify(path)['suffix'] == '.mp3'
    for body in (b'', b'ID3not-valid', b'MZnot-audio', b'\xff\xfb'):
        path.write_bytes(body)
        with pytest.raises(ValueError): audio_import.verify(path)


def test_audio_download_pins_public_ip_and_rejects_redirect_types_and_limits(tmp_path, monkeypatch):
    original = httpx.AsyncClient
    async def address(url): return 'audio.example', '8.8.8.8'
    monkeypatch.setattr(audio_import, 'public_target', address)
    captured = []
    def response(request):
        captured.append(request)
        return httpx.Response(200, headers={'content-type': 'audio/wav'}, content=wav_bytes())
    monkeypatch.setattr(audio_import.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    path = tmp_path / 'valid.part'
    asyncio.run(audio_import.download('https://audio.example/track.wav?sig=fixture', path))
    assert path.read_bytes() == wav_bytes()
    assert captured[0].url.host == '8.8.8.8' and captured[0].headers['host'] == 'audio.example'
    assert captured[0].extensions['sni_hostname'] == 'audio.example' and 'authorization' not in captured[0].headers
    for status, headers in ((302, {'location': 'http://127.0.0.1/secret'}), (200, {'content-type': 'text/html'}), (200, {'content-type': 'audio/wav', 'content-encoding': 'gzip'}), (200, {'content-type': 'audio/wav', 'content-length': str(audio_import.MAX_BYTES + 1)})):
        monkeypatch.setattr(audio_import.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(lambda r: httpx.Response(status, headers=headers, content=b'')), **kw))
        with pytest.raises(ValueError): asyncio.run(audio_import.download('https://audio.example/test', tmp_path / 'rejected.part'))


def test_audio_private_dns_and_credential_urls_rejected(monkeypatch):
    def resolve(*args, **kw): return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
    monkeypatch.setattr(audio_import.socket, 'getaddrinfo', resolve)
    for url in ('http://audio.example/a', 'https://user:pass@audio.example/a', 'https://audio.example:444/a', 'https://audio.example:bad/a', 'https://audio.example/a#fragment', 'https://audio.example/a'):
        with pytest.raises(ValueError): asyncio.run(audio_import.public_target(url))


def test_task_delivery_pins_hash_acceptance_and_change_invalidates_downstream(client):
    p = project(client)
    a = client.post(f"/api/projects/{p['id']}/upload", files={'file': ('hero.png', image_bytes())}).json()['asset']
    v = pin(client, a['id'])
    t = client.post(f"/api/projects/{p['id']}/tasks", json={'title': '角色贴图验收', 'deliveries': [v]}).json()
    done = client.patch(f"/api/tasks/{t['id']}", json={'status': 'done', 'evidence': '核对贴图尺寸和色彩', 'review_token': next(x for x in store.snapshot(p['id'])['tasks'] if x['id'] == t['id'])['review_token']}).json()
    child = client.post(f"/api/projects/{p['id']}/tasks", json={'title': '引擎接入', 'dependency_ids': [t['id']]}).json()
    assert done['ready'] and done['asset_links'][0]['sha256'] == v['sha256']
    history = client.get(f"/api/tasks/{t['id']}/acceptances").json()
    assert len(history) == 1 and {k: history[0]['snapshot']['deliveries'][0][k] for k in v} == v
    client.post(f"/api/assets/{a['id']}/edit", json={'expected_hash': v['sha256'], 'width': 12})
    state = store.snapshot(p['id']); by_id = {x['id']: x for x in state['tasks']}
    assert not by_id[t['id']]['ready'] and not by_id[child['id']]['ready']
    assert client.patch(f"/api/tasks/{t['id']}", json={'status': 'done', 'evidence': 'still old'}).status_code == 400
    assert client.get(f"/api/tasks/{t['id']}/acceptances").json() == history
    new = pin(client, a['id'])
    assert client.patch(f"/api/tasks/{t['id']}", json={'status': 'todo', 'deliveries': [new]}).status_code == 200
    assert client.patch(f"/api/tasks/{t['id']}", json={'status': 'done', 'evidence': '验收新版尺寸', 'review_token': next(x for x in store.snapshot(p['id'])['tasks'] if x['id'] == t['id'])['review_token']}).status_code == 200
    assert len(client.get(f"/api/tasks/{t['id']}/acceptances").json()) == 2


def test_task_delivery_rejects_stale_cross_project_and_external_changes(client):
    p, other = project(client), project(client)
    a = client.post(f"/api/projects/{p['id']}/upload", files={'file': ('hero.png', image_bytes())}).json()['asset']
    v = pin(client, a['id'])
    assert client.post(f"/api/projects/{other['id']}/tasks", json={'title': 'bad', 'deliveries': [v]}).status_code == 400
    for update in ({'sha256': '0' * 64}, {'version_index': True}, {'version_index': 999}):
        assert client.post(f"/api/projects/{p['id']}/tasks", json={'title': 'bad', 'deliveries': [{**v, **update}]}).status_code == 400
    t = client.post(f"/api/projects/{p['id']}/tasks", json={'title': '验收', 'deliveries': [v]}).json()
    client.patch(f"/api/tasks/{t['id']}", json={'status': 'done', 'evidence': 'accepted', 'review_token': next(x for x in store.snapshot(p['id'])['tasks'] if x['id'] == t['id'])['review_token']})
    path = assets.file_for(assets.asset(a['id'])); path.write_bytes(b'changed outside workbench')
    assert not store.snapshot(p['id'])['tasks'][0]['ready']
    path.write_bytes(image_bytes())
    assert not store.snapshot(p['id'])['tasks'][0]['ready']  # Reverting bytes cannot erase the review requirement.


def test_restored_backup_remaps_deliveries_music_assets_and_queue_without_authority(client, monkeypatch):
    p, j, calls = seed(client, monkeypatch)
    operation = command(client, p['id'], j['id']).json(); finish(client, p['id'], operation)
    a = music.outputs(j['id'])[0]['asset_id']; v = pin(client, a)
    t = client.post(f"/api/projects/{p['id']}/tasks", json={'title': '配乐验收', 'deliveries': [v]}).json()
    client.patch(f"/api/tasks/{t['id']}", json={'status': 'done', 'evidence': '已试听自制音频夹具', 'review_token': next(x for x in store.snapshot(p['id'])['tasks'] if x['id'] == t['id'])['review_token']})
    raw = client.get(f"/api/projects/{p['id']}/export").content
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        manifest = json.loads(z.read('project.json'))
        assert manifest['format'] == 10 and manifest['work_jobs'][0]['scope'] == '{}'
    response = client.post('/api/import-project', files={'file': ('project.zip', raw)})
    assert response.status_code == 200, response.text
    restored = response.json(); task = store.snapshot(restored['id'])['tasks'][0]
    assert task['ready'] and task['asset_links'][0]['asset_id'] != a
    assert task['asset_links'][0]['origin']['job_id'] != j['id']
    receipt = deliveries.history(task['id'])[0]
    assert receipt['snapshot']['deliveries'][0]['asset_id'] == task['asset_links'][0]['asset_id']
    assert receipt['snapshot']['deliveries'][0]['origin']['job_id'] == task['asset_links'][0]['origin']['job_id']
    assert all(r['scope'] == '{}' for r in store.rows('SELECT * FROM work_jobs WHERE project_id=?', (restored['id'],)))


def test_restart_only_requeues_reads_and_never_replays_generation_or_import(client, monkeypatch):
    p, j, calls = seed(client, monkeypatch)
    client.portal.call(jobs.shutdown)
    for action in ('query', 'import'):
        now = store.now()
        store.execute('INSERT INTO work_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (action, p['id'], 'music', j['id'], action, json.dumps({'serial_no': 'track-one'} if action == 'import' else {}), '{}', 'running', '{}', '', now, now))
    store.init()
    assert source_status('import') == 'interrupted' and source_status('query') == 'queued'
    client.portal.call(jobs.start)
    assert finish(client, p['id'], {'id': 'query'})['details']['status'] == 'succeeded'
    assert not music.outputs(j['id']) and source_status('import') == 'interrupted'
    assert not any(a[:2] == ('request', 'POST') for a in calls)


def source_status(jid): return store.one('SELECT status FROM work_jobs WHERE id=?', (jid,))['status']


def test_unified_list_filters_pagination_and_unknown_states_without_network(client, monkeypatch):
    p, j, calls = seed(client, monkeypatch)
    store.execute("UPDATE music_jobs SET status='processing' WHERE id=?", (j['id'],))
    assert jobs.list_jobs(p['id'], kind='music')['items'][0]['state'] == 'running'
    store.execute("UPDATE music_jobs SET status='unknown',serials='[]' WHERE id=?", (j['id'],))
    music.draft(p['id'], {'title': '另一首', 'prompt': 'test'})
    result = client.get(f"/api/projects/{p['id']}/jobs", params={'state': 'unknown', 'limit': 1}).json()
    assert result['total'] == 1 and result['items'][0]['raw_status'] == 'unknown' and not calls
    assert jobs.list_jobs(p['id'], kind='music', offset=1, limit=1)['total'] == 2
    assert jobs.list_jobs(p['id'], query='另一首')['total'] == 1
    assert command(client, p['id'], j['id'], 'query').status_code == 400


def test_agent_free_output_queue_respects_revoke_without_credit_grant(client, monkeypatch):
    p, j, calls = seed(client, monkeypatch)
    c = conversation(client, p['id']); grant = save_grant(client, c['id'], full=True)
    scope = scope_for(p, c, grant)
    async def slow(url, path): await asyncio.sleep(10)
    monkeypatch.setattr(audio_import, 'download', slow)
    receipt = client.portal.call(agent_tools.invoke, scope, 'workbench_call', {'action': 'music.import', 'input_json': json.dumps({'target_id': j['id'], 'data': {'serial_no': 'track-one'}})})
    assert receipt['kind'] == 'operation' and not grant['suno']
    save_grant(client, c['id'], full=False)
    assert finish(client, p['id'], receipt)['details']['status'] in ('cancelled', 'failed')
    assert not music.outputs(j['id']) and not any(a[:2] == ('request', 'POST') for a in calls)


def test_acceptance_rejects_stale_review_and_never_silently_adopts_new_basis(client):
    p = project(client)
    a = client.post(f"/api/projects/{p['id']}/upload", files={'file': ('hero.png', image_bytes())}).json()['asset']
    t = client.post(f"/api/projects/{p['id']}/tasks", json={'title': '原验收任务', 'deliveries': [pin(client, a['id'])]}).json()
    client.patch(f"/api/tasks/{t['id']}", json={'title': '更新验收范围'})
    assert client.patch(f"/api/tasks/{t['id']}", json={'status': 'done', 'evidence': 'old review', 'review_token': t['review_token']}).status_code == 400
    assert client.patch(f"/api/tasks/{t['id']}", json={'status': 'done', 'evidence': 'no review token'}).status_code == 400
    assert not deliveries.history(t['id'])


def test_expired_music_auth_needs_user_and_existing_modified_audio_is_not_overwritten(client, monkeypatch):
    p, j, calls = seed(client, monkeypatch)
    async def expired(*args): return {'status': 'pending'}
    with monkeypatch.context() as local:
        local.setattr(music, 'helper', expired)
        result = finish(client, p['id'], command(client, p['id'], j['id']).json())
        assert result['details']['status'] == 'needs_user' and not music.outputs(j['id'])
    finish(client, p['id'], command(client, p['id'], j['id']).json())
    aid = music.outputs(j['id'])[0]['asset_id']; path = assets.file_for(assets.asset(aid))
    path.write_bytes(b'externally changed audio')
    result = finish(client, p['id'], command(client, p['id'], j['id']).json())
    assert result['details']['status'] == 'failed' and path.read_bytes() == b'externally changed audio'


def test_other_job_sources_normalize_states_and_route_supported_stops(client, monkeypatch):
    from backend import chat, modeling, snapshots, tripo
    import threading
    p = project(client); pid = p['id']; now = store.now()
    store.execute('INSERT INTO art_jobs VALUES (?,?,?,?,?,?,?,?,?,?)', ('art-fixture', pid, None, None, 'openai', '{}', 'interrupted', '{}', now, now))
    character = modeling.draft(pid, {})
    store.execute("UPDATE character_jobs SET status='building' WHERE id=?", (character['id'],))
    model = tripo.draft(pid, {'prompt': 'fixture'})
    store.execute("UPDATE tripo_jobs SET status='ready' WHERE id=?", (model['id'],))
    store.execute('INSERT INTO project_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', ('snapshot-fixture', pid, None, 'fixture', 'checkpoint', 'test', 'pending', '', '', '', '{}', now, now))
    store.execute('INSERT INTO github_publications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', ('publication-fixture', pid, 'snapshot-fixture', 'https://github.com/fixture/game', 'fixture', '', 'prepared', '', '{}', '', '', now, now))
    run = store.run_start(pid, 'chat:openai:director', 'fixture chat')
    rows = {r['kind']: r['state'] for r in jobs.list_jobs(pid)['items']}
    assert rows == {'art': 'unknown', 'blender': 'running', 'tripo': 'needs_user', 'snapshot': 'queued', 'publication': 'needs_user', 'chat': 'running'}
    stopped = []
    monkeypatch.setattr(modeling, 'cancel', lambda jid: stopped.append(('blender', jid)))
    monkeypatch.setattr(chat, 'cancel', lambda jid: stopped.append(('chat', jid)))
    flag = threading.Event()
    monkeypatch.setitem(snapshots.RUNNING, 'snapshot-fixture', {'stop': flag})
    try:
        for kind, jid in [('blender', character['id']), ('chat', run), ('snapshot', 'snapshot-fixture')]: assert jobs.stop(pid, kind, jid)['requested']
        assert flag.is_set() and len(stopped) == 2
        assert client.post(f'/api/projects/{pid}/jobs/commands', json={'kind': 'tripo', 'id': model['id'], 'command': 'submit', 'confirmed': True}).status_code == 400
    finally:
        snapshots.RUNNING.pop('snapshot-fixture', None)


def test_art_acceptance_provenance_maps_to_restored_generation_record(client):
    p = project(client)
    a = client.post(f"/api/projects/{p['id']}/upload", files={'file': ('hero.png', image_bytes())}).json()['asset']
    jid = store.uid(); now = store.now()
    store.execute('INSERT INTO art_jobs VALUES (?,?,?,?,?,?,?,?,?,?)', (jid, p['id'], None, a['id'], 'webui', json.dumps({'checkpoint_title': 'fixture-art-model'}), 'completed', '{}', now, now))
    task = client.post(f"/api/projects/{p['id']}/tasks", json={'title': '图片文件验收', 'deliveries': [pin(client, a['id'])]}).json()
    assert client.patch(f"/api/tasks/{task['id']}", json={'status': 'done', 'evidence': 'fixture only', 'review_token': task['review_token']}).status_code == 200
    raw = client.get(f"/api/projects/{p['id']}/export").content
    copied = client.post('/api/import-project', files={'file': ('backup.zip', raw)}).json()
    receipt = deliveries.history(store.snapshot(copied['id'])['tasks'][0]['id'])[0]
    origin = receipt['snapshot']['deliveries'][0]['origin']
    assert origin['job_id'] != jid and origin['model'] == 'fixture-art-model'
    assert store.one('SELECT project_id FROM art_jobs WHERE id=?', (origin['job_id'],))['project_id'] == copied['id']
