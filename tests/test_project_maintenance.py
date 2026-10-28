import asyncio
import io
import json
import zipfile
from pathlib import Path

import pytest

from backend import agent_tools, assets, intake, maintenance, providers, publishing, store
from test_workbench import client, image_bytes, project
from test_intake import attach, existing, fingerprints
from test_management import snapshot


def multi(client, tmp_path, engine='unreal'):
    root = existing(tmp_path / 'Game', engine)
    extra = tmp_path / 'Art'; extra.mkdir()
    (extra / 'hero.png').write_bytes(image_bytes())
    (extra / 'Design.md').write_text('# 外部美术设定\n角色以暖色为主。', encoding='utf-8')
    response = client.post('/api/project-intake/preview', json={'roots': [str(root), str(extra)]})
    assert response.status_code == 200, response.text
    preview = response.json()
    return attach(client, preview), root, extra, preview


def cache_project(client, tmp_path, engine='unreal'):
    p, root, extra, preview = multi(client, tmp_path, engine)
    name = 'Intermediate' if engine == 'unreal' else 'Library'
    directory = root / name; directory.mkdir()
    (directory / 'one.bin').write_bytes(b'generated-cache-1' * 100)
    (directory / 'two.bin').write_bytes(b'generated-cache-2' * 100)
    return p, root, extra, name


def audit(client, pid):
    response = client.post(f'/api/projects/{pid}/maintenance/audit')
    assert response.status_code == 200, response.text
    return response.json()


def archive(client, pid, plan, names):
    return client.post(f'/api/projects/{pid}/maintenance/archive', json={'audit_id': plan['id'], 'candidate_ids': names, 'confirmed': True, 'editor_closed_ack': True})


def test_multi_source_same_names_preview_read_assets_and_portable_backup(client, tmp_path):
    p, root, extra, preview = multi(client, tmp_path)
    assert len(preview['roots']) == 2 and preview['file_count'] >= 7
    before = fingerprints(root), fingerprints(extra)
    data = store.snapshot(p['id'])
    assert len(data['assets']) == 2 and len({a['relative_path'] for a in data['assets']}) == 2
    path = next(d['path'] for d in preview['documents'] if d['path'].startswith('@'))
    read = intake.read_file(p['id'], path, 0, 12000)
    assert '暖色' in read['content']
    for asset in data['assets']:
        assert client.get(f"/api/assets/{asset['id']}/info").status_code == 200
    external = next(a for a in data['assets'] if a['source'].startswith(str(extra)))
    edited = client.post(f"/api/assets/{external['id']}/edit", json={'expected_hash': assets.digest(extra / 'hero.png'), 'width': 12})
    assert edited.status_code == 200 and fingerprints(extra) == before[1]
    outside = extra.parent / 'outside.png'; outside.write_bytes(image_bytes())
    with pytest.raises(ValueError): assets.authorized_path(p['id'], outside)
    raw = client.get(f"/api/projects/{p['id']}/export").content
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert 'project_roots' not in z.read('project.json').decode()
    response = client.post('/api/import-project', files={'file': ('backup.zip', raw)})
    assert response.status_code == 200, response.text
    restored = response.json()
    assert len(intake.source_roots(restored['id'])) == 1
    with pytest.raises(ValueError): assets.authorized_path(restored['id'], extra / 'hero.png')
    for asset in store.snapshot(restored['id'])['assets']: assert assets.file_for(asset).is_file()
    assert (fingerprints(root), fingerprints(extra)) == before


def test_multi_source_rejects_ambiguous_overlapping_missing_and_private_roots(client, tmp_path):
    root = existing(tmp_path / 'Game')
    for roots in ([], [str(root)] * 2, [str(root), str(root / 'Docs')], [str(root), str(tmp_path / 'missing')], [str(root)] * 9, [str(store.DATA)], [str(store.ROOT)]):
        assert client.post('/api/project-intake/preview', json={'roots': roots}).status_code == 400
    assert client.post('/api/project-intake/preview', json={'root': str(root), 'roots': [str(root)]}).status_code == 400
    assert not store.rows('SELECT * FROM projects')


def test_existing_project_add_sources_stale_preview_and_unselected_documents(client, tmp_path):
    root = existing(tmp_path / 'Game')
    first = client.post('/api/project-intake/preview', json={'root': str(root)}).json()
    p = attach(client, first, documents=['README.md'])
    extra = tmp_path / 'Design'; extra.mkdir(); (extra / 'Notes.md').write_text('supplementary design')
    url = f"/api/projects/{p['id']}/intake/sources"
    one = client.post(url + '/preview', json={'roots': [str(extra)]}).json()
    two = client.post(url + '/preview', json={'roots': [str(extra)]}).json()
    selected = ['README.md', next(d['path'] for d in one['documents'] if d['path'].startswith('@'))]
    assert client.post(url, json={'preview_id': one['id'], 'documents': selected}).status_code == 200
    assert client.post(url, json={'preview_id': two['id'], 'documents': selected}).status_code == 400
    with pytest.raises(ValueError): intake.read_file(p['id'], 'Docs/Design.md', 0, 100)
    assert len(intake.source_roots(p['id'])) == 2
    third = tmp_path / 'Audio'; third.mkdir(); (third / 'Music.md').write_text('music requirements')
    additional = client.post(url + '/preview', json={'roots': [str(third)]}).json()
    chosen = [d['path'] for d in additional['documents'] if d['path'] != 'Docs/Design.md']
    assert client.post(url, json={'preview_id': additional['id'], 'documents': chosen}).status_code == 200
    assert len(intake.source_roots(p['id'])) == 3
    (extra / 'Notes.md').write_text('updated supplementary design')
    with pytest.raises(ValueError): intake.read_file(p['id'], selected[1], 0, 100)
    assert client.post(f"/api/projects/{p['id']}/intake/refresh").status_code == 200
    assert 'updated' in intake.read_file(p['id'], selected[1], 0, 100)['content']
    with pytest.raises(ValueError):
        asyncio.run(agent_tools.invoke({'pid': p['id'], 'write': True, 'agent': 'director'}, 'workbench_call', {'action': 'project.add_sources', 'input_json': '{}'}))


def test_multiroot_snapshot_restore_and_publication_preview_include_sources(client, tmp_path, monkeypatch):
    p, root, extra, preview = multi(client, tmp_path)
    (extra / 'Notes.cs').write_text('public class ArtNotes {}')
    bad = client.post(f"/api/projects/{p['id']}/snapshots", json={'label': 'bad', 'note': 'test', 'saved_ack': True, 'destination': str(extra)})
    assert bad.status_code == 400
    snap = snapshot(client, p['id'])
    from backend import snapshots
    manifest = snapshots.verify(snap['id'])
    source = next(r for r in manifest['sources'] if r['id'] != 'primary')
    assert any(f['path'] == source['prefix'] + 'Notes.cs' for f in manifest['files'])
    response = client.post(f"/api/snapshots/{snap['id']}/restore", json={'confirmed': True, 'parent': str(tmp_path)})
    assert response.status_code == 200, response.text
    restored = Path(response.json()['folder'])
    assert (restored / source['prefix'] / 'hero.png').read_bytes() == image_bytes()
    assert client.post(f"/api/snapshots/{snap['id']}/restore", json={'confirmed': True, 'parent': str(extra)}).status_code == 400
    async def repo_info(*args): return {'id': 123, 'full_name': 'fixture/game', 'private': True, 'permissions': {'push': True}}
    monkeypatch.setattr(publishing, 'repository', repo_info)
    prepared = client.post(f"/api/snapshots/{snap['id']}/github/prepare", json={'repository': 'https://github.com/fixture/game'}).json()
    assert prepared['status'] == 'prepared', prepared
    assert (Path(prepared['folder']) / 'repo' / source['prefix'] / 'Notes.cs').is_file()


def test_audit_readonly_classification_duplicate_evidence_and_safe_scope(client, tmp_path):
    p, root, extra, name = cache_project(client, tmp_path)
    before = fingerprints(root), fingerprints(extra)
    plan = audit(client, p['id'])
    assert plan['categories']['cache'] > 0 and plan['duplicates']
    assert plan['candidates'][0]['id'] == name and plan['candidates'][0]['eligible']
    assert len(plan['roots']) == 2 and all('仅建议' in g['action'] for g in plan['duplicates'])
    assert (fingerprints(root), fingerprints(extra)) == before
    document = store.one('SELECT * FROM documents WHERE id=?', (plan['document_id'],))
    assert document['authority'] == 'draft' and '非模型结论' in document['content']
    assert str(root) not in document['content']
    listing = client.get(f"/api/projects/{p['id']}/maintenance/files", params={'audit_id': plan['id'], 'candidate_id': name}).json()
    assert listing['total'] == 2 and listing['items'][0]['relative_path'].startswith(name + '/')
    assert archive(client, p['id'], plan, ['Saved']).status_code == 400
    assert archive(client, p['id'], plan, ['Content']).status_code == 400


@pytest.mark.parametrize('engine', ['unreal', 'unity'])
def test_archive_verified_backup_and_restore_without_overwrite(client, tmp_path, engine):
    p, root, extra, name = cache_project(client, tmp_path, engine)
    before = fingerprints(root), fingerprints(extra)
    plan = audit(client, p['id'])
    response = archive(client, p['id'], plan, [name])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'completed' and result['removed_bytes'] > 0
    assert not (root / name / 'one.bin').exists()
    folder = Path(result['folder'])
    assert maintenance.digest(folder / 'cache.zip') == result['archive_sha256']
    receipt = json.loads((folder / 'receipt.json').read_text(encoding='utf-8'))
    assert len(receipt['files']) == 2
    (root / name / 'one.bin').write_text('new editor output')
    endpoint = f"/api/projects/{p['id']}/maintenance/{result['id']}/restore"
    restored = client.post(endpoint, json={'confirmed': True, 'editor_closed_ack': True}).json()
    assert restored['status'] == 'partial' and restored['restored_files'] == 1 and len(restored['conflicts']) == 1
    assert (root / name / 'one.bin').read_text() == 'new editor output'
    (root / name / 'one.bin').unlink()
    assert client.post(endpoint, json={'confirmed': True, 'editor_closed_ack': True}).json()['status'] == 'restored'
    assert (fingerprints(root), fingerprints(extra)) == before


def test_archive_confirmation_stale_inventory_project_ownership_and_csrf(client, tmp_path, monkeypatch):
    p, root, extra, name = cache_project(client, tmp_path)
    plan = audit(client, p['id'])
    url = f"/api/projects/{p['id']}/maintenance/archive"
    body = {'audit_id': plan['id'], 'candidate_ids': [name], 'confirmed': True, 'editor_closed_ack': True}
    for change in ({'confirmed': False}, {'editor_closed_ack': False}, {'audit_id': 'stale'}, {'candidate_ids': [name, name]}):
        assert client.post(url, json={**body, **change}).status_code == 400
    assert client.post(url, json=body, headers={'x-workbench-token': ''}).status_code == 403
    with monkeypatch.context() as local:
        local.setattr(maintenance, 'MAX_BYTES', 1)
        assert client.post(url, json=body).status_code == 400
    (root / name / 'new.bin').write_text('new cache file')
    assert client.post(url, json=body).status_code == 400
    assert (root / name / 'one.bin').is_file()
    new = audit(client, p['id'])
    result = archive(client, p['id'], new, [name]).json()
    other = project(client)
    assert client.post(f"/api/projects/{other['id']}/maintenance/{result['id']}/restore", json={'confirmed': True, 'editor_closed_ack': True}).status_code == 400


def test_partial_removal_retains_full_backup_and_manual_restore(client, tmp_path, monkeypatch):
    p, root, extra, name = cache_project(client, tmp_path)
    before = fingerprints(root)
    plan = audit(client, p['id'])
    original = Path.unlink
    def locked(path, *args, **kwargs):
        if path == root / name / 'two.bin': raise PermissionError('simulated file lock')
        return original(path, *args, **kwargs)
    with monkeypatch.context() as local:
        local.setattr(Path, 'unlink', locked)
        result = archive(client, p['id'], plan, [name]).json()
    assert result['status'] == 'partial' and result['removed_bytes'] > 0
    response = client.post(f"/api/projects/{p['id']}/maintenance/{result['id']}/restore", json={'confirmed': True, 'editor_closed_ack': True})
    assert response.status_code == 200, response.text
    assert fingerprints(root) == before


def test_corrupt_backup_linked_paths_and_incomplete_audit_block_execution(client, tmp_path, monkeypatch):
    p, root, extra, name = cache_project(client, tmp_path)
    with monkeypatch.context() as local:
        local.setattr(maintenance, 'MAX_FILES', 2)
        plan = audit(client, p['id'])
        assert plan['truncated'] and not any(c['eligible'] for c in plan['candidates'])
        assert archive(client, p['id'], plan, [name]).status_code == 400
    plan = audit(client, p['id'])
    original = intake.linked
    with monkeypatch.context() as local:
        local.setattr(intake, 'linked', lambda path: Path(path) == root / name / 'one.bin' or original(path))
        assert archive(client, p['id'], plan, [name]).status_code == 400
    result = archive(client, p['id'], audit(client, p['id']), [name]).json()
    (Path(result['folder']) / 'cache.zip').write_bytes(b'corrupted archive')
    assert client.post(f"/api/projects/{p['id']}/maintenance/{result['id']}/restore", json={'confirmed': True, 'editor_closed_ack': True}).status_code == 400
    assert not (root / name / 'one.bin').exists()


def test_interrupted_archive_can_restore_from_persisted_receipt_after_restart(client, tmp_path, monkeypatch):
    p, root, extra, name = cache_project(client, tmp_path)
    before = fingerprints(root)
    plan = audit(client, p['id'])
    original = Path.unlink
    def interrupted(path, *args, **kw):
        if path == root / name / 'two.bin': raise KeyboardInterrupt('simulated process interruption')
        return original(path, *args, **kw)
    with monkeypatch.context() as local:
        local.setattr(Path, 'unlink', interrupted)
        with pytest.raises(KeyboardInterrupt): maintenance.archive(p['id'], {'audit_id': plan['id'], 'candidate_ids': [name], 'confirmed': True, 'editor_closed_ack': True})
    job = store.one("SELECT id FROM runs WHERE project_id=? AND kind='project_cleanup'", (p['id'],))
    store.init()
    assert store.one('SELECT status FROM runs WHERE id=?', (job['id'],))['status'] == 'interrupted'
    response = client.post(f"/api/projects/{p['id']}/maintenance/{job['id']}/restore", json={'confirmed': True, 'editor_closed_ack': True})
    assert response.status_code == 200 and response.json()['status'] == 'restored'
    assert fingerprints(root) == before


def test_analysis_prepare_and_selected_api_model_use_readonly_evidence(client, tmp_path, monkeypatch):
    p, root, extra, preview = multi(client, tmp_path)
    captured = []
    async def stream(provider, model, inputs, rules, tools, execute_tool, **kw):
        captured.append((provider, model))
        assert 'workbench_call' not in {t['name'] for t in tools}
        assert 'edit_image' not in {t['name'] for t in tools}
        assert '重复哈希不等于无引用' in rules
        context = await execute_tool('get_project', {})
        assert len(context['existing_project']['roots']) == 2
        yield {'event': 'delta', 'text': '模拟分析：已核对结构，仍需实际运行验收；未移动或删除文件。'}
    monkeypatch.setattr(providers, 'stream', stream)
    before = fingerprints(root), fingerprints(extra)
    result = client.post(f"/api/projects/{p['id']}/intake/analyze")
    assert result.status_code == 200, result.text
    assert not captured  # Preparation performs no model call or paid request.
    conversation = client.post(f"/api/projects/{p['id']}/conversations", json={'agent': 'director', 'provider': 'deepseek', 'model': 'fixture-reviewer'}).json()
    response = client.post(f"/api/projects/{p['id']}/chat", json={'message': result.json()['message'], 'conversation_id': conversation['id'], 'agent': 'director', 'provider': 'deepseek', 'model': 'fixture-reviewer', 'execute': False})
    assert 'done' in response.text and captured == [('deepseek', 'fixture-reviewer')]
    assert (fingerprints(root), fingerprints(extra)) == before
    assert not store.rows('SELECT * FROM music_jobs') and not store.rows('SELECT * FROM tripo_jobs')


def test_changed_source_link_never_expands_asset_or_source_authority(client, tmp_path, monkeypatch):
    p, root, extra, preview = multi(client, tmp_path)
    original = intake.linked
    monkeypatch.setattr(intake, 'linked', lambda path: Path(path) == extra or original(path))
    with pytest.raises(ValueError, match='目标变化'):
        assets.authorized_path(p['id'], extra / 'hero.png')
    with pytest.raises(ValueError, match='目标变化'):
        intake.read_file(p['id'], next(d['path'] for d in preview['documents'] if d['path'].startswith('@')), 0, 100)
