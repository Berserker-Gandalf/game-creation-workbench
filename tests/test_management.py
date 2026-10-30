import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from backend import accounts, snapshots, publishing, store
from test_workbench import client, project, image_bytes


def test_account_quota_windows_missing_data_and_failure_preserve_last_result(client, monkeypatch):
    async def limits(*a, **kw):
        return {'rateLimitsByLimitId': {'codex': {'primary': {'usedPercent': 27, 'windowDurationMins': 300, 'resetsAt': 2000000000}, 'secondary': None}}}
    monkeypatch.setattr(accounts.codex.client, 'rpc', limits)
    async def start(): pass
    monkeypatch.setattr(accounts.codex.client, 'start', start)
    r = client.post('/api/accounts/refresh', json={'providers': ['codex']})
    assert r.status_code == 200, r.text
    item = r.json()['codex']
    assert item['data']['windows'][0]['remaining_percent'] == 73 and len(item['data']['windows']) == 1
    async def fail(*a, **kw): raise ValueError('Do not expose account secrets')
    monkeypatch.setattr(accounts.codex.client, 'rpc', fail)
    failed = client.post('/api/accounts/refresh', json={'providers': ['codex']}).json()['codex']
    assert failed['status'] == 'error' and failed['data']['windows'][0]['remaining_percent'] == 73
    assert failed['stale'] is True and 'secrets' not in json.dumps(failed)


def test_account_suno_tripo_are_readonly_and_unavailable_is_not_zero(client, monkeypatch):
    calls = []
    async def helper(*args):
        calls.append(args)
        return {'status': 'authorized'} if args == ('auth', 'status') else {'points': 12.5, 'vip_status': 1}
    async def balance(): return {'balance': 42, 'frozen': 3}
    monkeypatch.setattr(accounts.music, 'helper', helper)
    monkeypatch.setattr(accounts.tripo, 'balance', balance)
    monkeypatch.setattr(accounts.tripo.secrets, 'get_key', lambda name: 'fixture')
    result = client.post('/api/accounts/refresh', json={'providers': ['suno', 'tripo']}).json()
    assert result['suno']['data']['points'] == 12.5 and result['tripo']['data']['balance'] == 42
    assert calls == [('auth', 'status'), ('account',)]
    assert not store.rows('SELECT * FROM music_jobs') and not store.rows('SELECT * FROM tripo_jobs')
    assert client.get('/api/accounts').json()['openai']['status'] == 'unsupported'


def source_project(client, tmp_path):
    root = tmp_path / 'Game'
    (root / 'Source').mkdir(parents=True)
    (root / 'Content').mkdir()
    (root / 'Saved').mkdir()
    (root / 'Game.uproject').write_text('{"EngineAssociation":"4.27"}')
    (root / 'Source/Game.cpp').write_text('int main() { return 0; }')
    (root / 'Content/hero.png').write_bytes(image_bytes())
    (root / 'Saved/private.txt').write_text('runtime')
    (root / '.env').write_text('SHOULD_NOT_LEAVE_MACHINE')
    return project(client, root=str(root)), root


def snapshot(client, pid, **extra):
    r = client.post(f'/api/projects/{pid}/snapshots', json={'label': '原型基线', 'note': '设计评审前留存', 'kind': 'milestone', 'saved_ack': True, **extra})
    assert r.status_code == 200, r.text
    jid = r.json()['id']
    # Execute on the server loop because the worker belongs to its lifetime.
    async def wait():
        control = snapshots.RUNNING.get(jid)
        if control: await control['task']
    client.portal.call(wait)
    result = client.get(f'/api/snapshots/{jid}').json()
    assert result['status'] == 'ready', result
    return result


def test_full_snapshot_manifest_hash_chain_restore_and_original_unchanged(client, tmp_path):
    p, root = source_project(client, tmp_path)
    before = {str(f): f.read_bytes() for f in root.rglob('*') if f.is_file()}
    first = snapshot(client, p['id'])
    second = snapshot(client, p['id'])
    assert second['parent_id'] == first['id']
    path = Path(first['archive'])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == first['archive_sha256']
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read('snapshot.json'))
        names = {f['path'] for f in manifest['files']}
        assert 'game/Source/Game.cpp' in names and 'workbench/project.zip' in names
        assert not any('Saved/' in f or '.env' in f for f in names)
        for f in manifest['files']: assert hashlib.sha256(z.read(f['path'])).hexdigest() == f['sha256']
    dest = tmp_path / 'Restore'; dest.mkdir()
    r = client.post(f"/api/snapshots/{first['id']}/restore", json={'parent': str(dest), 'confirmed': True})
    assert r.status_code == 200, r.text
    restored = Path(r.json()['folder'])
    assert (restored / 'game/Source/Game.cpp').read_bytes() == (root / 'Source/Game.cpp').read_bytes()
    assert {str(f): f.read_bytes() for f in root.rglob('*') if f.is_file()} == before
    path.write_bytes(path.read_bytes() + b'tamper')
    assert client.post(f"/api/snapshots/{first['id']}/verify").status_code == 400
    assert client.post(f"/api/snapshots/{first['id']}/restore", json={'parent': str(dest), 'confirmed': True}).status_code == 400


def test_snapshot_requires_saved_ack_and_rejects_recursive_destination(client, tmp_path):
    p, root = source_project(client, tmp_path)
    for args in ({'saved_ack': False}, {'destination': str(root / 'Backup'), 'saved_ack': True}):
        r = client.post(f"/api/projects/{p['id']}/snapshots", json={'label': 'baseline', 'note': 'before edit', **args})
        assert r.status_code == 400


def test_github_preparation_uses_frozen_snapshot_and_never_touches_source_git(client, tmp_path, monkeypatch):
    p, root = source_project(client, tmp_path)
    snap = snapshot(client, p['id'])
    (root / 'Source/Game.cpp').write_text('later changes')
    async def repo_info(owner, name): return {'id': 123, 'full_name': 'fixture/game', 'private': True, 'permissions': {'push': True}}
    monkeypatch.setattr(publishing, 'repository', repo_info)
    prepared = client.post(f"/api/snapshots/{snap['id']}/github/prepare", json={'repository': 'https://github.com/fixture/game', 'include_assets': True}).json()
    assert prepared['status'] == 'prepared', prepared
    repo = Path(prepared['folder']) / 'repo'
    assert (repo / 'game/Source/Game.cpp').read_text() != 'later changes'
    assert not (root / '.git').exists()
    assert not (repo / 'game/.env').exists()
    assert prepared['commit'] and prepared['branch'].startswith('codex/snapshot-')
    assert client.post('/api/publications/' + prepared['id'] + '/push', json={'confirmed': False}).status_code == 400
    assert client.post('/api/publications/' + prepared['id'] + '/push', json={'confirmed': True, 'rights_ack': False}).status_code == 400


def test_github_secret_scan_blocks_publication_and_url_credentials(client, tmp_path, monkeypatch):
    p, root = source_project(client, tmp_path)
    (root / 'Source/key.txt').write_text('sk-' + 'x' * 32)
    snap = snapshot(client, p['id'])
    async def repo_info(*a): return {'id': 123, 'full_name': 'fixture/game', 'private': False, 'permissions': {'push': True}}
    monkeypatch.setattr(publishing, 'repository', repo_info)
    r = client.post(f"/api/snapshots/{snap['id']}/github/prepare", json={'repository': 'https://github.com/fixture/game'})
    assert r.status_code == 200 and r.json()['status'] == 'blocked'
    assert any('密钥' in f['reason'] for f in r.json()['report']['blocked'])
    assert 'sk-' + 'x' * 32 not in r.text
    for url in ['https://token@github.com/owner/repo', 'https://example.com/a/b', '../repo']:
        with pytest.raises(ValueError): publishing.repo_name(url)


def test_cached_accounts_expire_and_tripo_region_change_is_not_live(client):
    store.set_setting('account_balances', {'suno': {'status': 'ok', 'data': {'points': 15}, 'checked_at': '2020-01-01T00:00:00+00:00', 'stale': False},
                                          'tripo': {'status': 'ok', 'data': {'balance': 3, 'region': 'global'}, 'checked_at': store.now(), 'stale': False}})
    values = client.get('/api/accounts').json()
    assert values['suno']['status'] == 'stale' and values['suno']['data']['points'] == 15
    assert values['tripo']['stale'] is True
    with pytest.raises(ValueError): accounts.quota({'rateLimits': {'primary': {'usedPercent': None}}})


def test_deepseek_reads_official_balance_preserves_real_zero_and_never_returns_key(client, monkeypatch):
    calls = []
    class Response:
        status_code = 200
        def json(self): return {'is_available': False, 'balance_infos': [{'currency': 'CNY', 'total_balance': '0.00', 'granted_balance': 'NaN', 'topped_up_balance': '0.00'}]}
    class Remote:
        def __init__(self, **kwargs): assert kwargs['trust_env'] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kwargs):
            assert kwargs['headers']['Authorization'] == 'Bearer fixture-key'
            calls.append(url)
            return Response()
    monkeypatch.setattr(accounts.httpx, 'AsyncClient', Remote)
    monkeypatch.setattr(accounts.secrets, 'get_key', lambda provider: 'fixture-key')
    result = client.post('/api/accounts/refresh', json={'providers': ['deepseek']})
    value = result.json()['deepseek']
    assert value['status'] == 'ok' and value['data']['balances'][0]['total_balance'] == '0.00'
    assert 'granted_balance' not in value['data']['balances'][0] and 'fixture-key' not in result.text
    assert calls == ['https://api.deepseek.com/user/balance']


def test_source_change_during_snapshot_is_failed_not_valid(client, tmp_path, monkeypatch):
    p, root = source_project(client, tmp_path)
    original = snapshots.backup.write
    def changing(*args):
        output = original(*args)
        (root / 'Source/Game.cpp').write_text('changed after inventory')
        return output
    monkeypatch.setattr(snapshots.backup, 'write', changing)
    r = client.post(f"/api/projects/{p['id']}/snapshots", json={'label': '基线', 'note': '变化保护', 'saved_ack': True}).json()
    async def wait():
        control = snapshots.RUNNING.get(r['id'])
        if control: await control['task']
    client.portal.call(wait)
    result = snapshots.job(r['id'])
    assert result['status'] == 'failed' and not result['archive_sha256']
    assert client.post(f"/api/snapshots/{r['id']}/verify").status_code == 400


def test_github_native_git_push_uncertain_recovery_and_source_index_unchanged(client, tmp_path, monkeypatch):
    p, root = source_project(client, tmp_path)
    native = publishing.git
    native(root, 'init', '--initial-branch=main')
    native(root, 'config', 'user.name', 'Fixture')
    native(root, 'config', 'user.email', 'fixture@local.invalid')
    native(root, 'add', 'Source/Game.cpp')
    native(root, 'commit', '-m', 'Existing game')
    before_index = snapshots.digest(root / '.git/index')
    before_head = native(root, 'rev-parse', 'HEAD')
    snap = snapshot(client, p['id'])
    async def meta(*a): return {'id': 123, 'full_name': 'fixture/game', 'private': True, 'permissions': {'push': True}}
    monkeypatch.setattr(publishing, 'repository', meta)
    prepared = client.post(f"/api/snapshots/{snap['id']}/github/prepare", json={'repository': 'https://github.com/fixture/game'}).json()
    assert prepared['status'] == 'prepared', prepared
    bare = tmp_path / 'remote.git'; bare.mkdir()
    native(bare, 'init', '--bare', '--initial-branch=main')
    uploads = []
    def isolated(repo, *args, **kwargs):
        if args[0] in ('push', 'ls-remote') and args[1] == 'origin':
            args = (args[0], str(bare), *args[2:])
            kwargs['authenticated'] = False
            result = native(repo, *args, **kwargs)
            if args[0] == 'push':
                uploads.append(args)
                raise TimeoutError('simulate response lost after successful native Git push')
            return result
        return native(repo, *args, **kwargs)
    monkeypatch.setattr(publishing, 'git', isolated)
    response = client.post(f"/api/publications/{prepared['id']}/push", json={'confirmed': True, 'rights_ack': True})
    assert response.status_code == 200 and response.json()['status'] == 'unknown'
    assert len(uploads) == 1
    assert client.post(f"/api/publications/{prepared['id']}/push", json={'confirmed': True, 'rights_ack': True}).status_code == 400
    checked = client.post(f"/api/publications/{prepared['id']}/check")
    assert checked.json()['status'] == 'published' and len(uploads) == 1
    assert native(bare, 'rev-parse', 'refs/heads/' + prepared['branch']) == prepared['commit']
    assert native(bare, 'show-ref', '--heads').count('\n') == 0  # Only the new snapshot branch.
    assert snapshots.digest(root / '.git/index') == before_index and native(root, 'rev-parse', 'HEAD') == before_head


@pytest.mark.skipif(not publishing.lfs_available(), reason='native Git LFS is not installed')
def test_lfs_manifest_matches_commit_and_changed_preview_rejected(client, tmp_path, monkeypatch):
    p, root = source_project(client, tmp_path)
    # A deeper attributes file must not override the generated LFS rules.
    (root / '.gitattributes').write_text('* -filter\n')
    (root / '.gitignore').write_text('Content/\n')
    (root / 'Content/large.binasset').write_bytes(b'game-asset' * 120000)
    snap = snapshot(client, p['id'])
    async def meta(*a): return {'id': 123, 'full_name': 'fixture/game', 'private': False, 'permissions': {'push': True}}
    monkeypatch.setattr(publishing, 'repository', meta)
    prepared = client.post(f"/api/snapshots/{snap['id']}/github/prepare", json={'repository': 'https://github.com/fixture/game'}).json()
    assert prepared['status'] == 'prepared', prepared
    repo = publishing.verify_prepared(prepared)
    pointer = publishing.git(repo, 'show', 'HEAD:game/Content/large.binasset')
    assert pointer.startswith('version https://git-lfs.github.com/spec/v1')
    assert '.gitattributes' in [f['path'] for f in prepared['report']['files']]
    assert 'game/.gitattributes' in prepared['report']['excluded']
    assert client.post(f"/api/publications/{prepared['id']}/push", json={'confirmed': True, 'rights_ack': True}).status_code == 400
    (repo / 'game/Source/Game.cpp').write_text('unexpected edit')
    with pytest.raises(ValueError, match='变化'): publishing.verify_prepared(prepared)


def test_restart_never_marks_incomplete_retention_or_push_as_success(client, tmp_path, monkeypatch):
    p, _ = source_project(client, tmp_path)
    snap = snapshot(client, p['id'])
    async def meta(*a): return {'id': 123, 'full_name': 'fixture/game', 'private': True, 'permissions': {'push': True}}
    monkeypatch.setattr(publishing, 'repository', meta)
    prepared = client.post(f"/api/snapshots/{snap['id']}/github/prepare", json={'repository': 'https://github.com/fixture/game'}).json()
    store.execute("UPDATE project_snapshots SET status='copying' WHERE id=?", (snap['id'],))
    store.execute("UPDATE github_publications SET status='pushing' WHERE id=?", (prepared['id'],))
    store.init()
    assert snapshots.job(snap['id'])['status'] == 'interrupted'
    assert publishing.job(prepared['id'])['status'] == 'unknown'
