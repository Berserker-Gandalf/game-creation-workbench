import asyncio
import hashlib
import io
import json
import zipfile
from pathlib import Path

from backend import agent_tools, intake, store
from test_workbench import client, image_bytes


def existing(root, engine='unreal'):
    root.mkdir()
    if engine == 'unreal':
        (root / 'Demo.uproject').write_text('{"EngineAssociation":"4.27"}')
        asset = root / 'Content/Textures/hero.png'
    else:
        (root / 'ProjectSettings').mkdir()
        (root / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.5.3f1')
        asset = root / 'Assets/Textures/hero.png'
    asset.parent.mkdir(parents=True)
    asset.write_bytes(image_bytes())
    (root / 'Docs').mkdir()
    (root / 'Docs/Design.md').write_text('# 核心设计\n回合制探索，无昼夜系统。\n- [x] 原型完成\n- [ ] 引擎验收', encoding='utf-8')
    (root / 'README.md').write_text('# 旧项目\n已有地图与角色，运行情况需要核对。', encoding='utf-8')
    (root / 'Source').mkdir()
    (root / 'Source/Hero.cs').write_text('public class HeroController { public void Attack() {} }')
    (root / 'Saved').mkdir()
    (root / 'Saved/private.txt').write_text('NEVER_IMPORT_RUNTIME')
    (root / '.env').write_text('API_KEY=NEVER_IMPORT_SECRET')
    return root


def fingerprints(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def preview(client, root):
    r = client.post('/api/project-intake/preview', json={'root': str(root)})
    assert r.status_code == 200, r.text
    return r.json()


def attach(client, scan, **extra):
    r = client.post('/api/project-intake/attach', json={'preview_id': scan['id'], 'name': '接续旧工程', 'engine': scan['engine'], 'documents': scan['suggested_documents'], **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_intake_preview_attach_context_and_source_project_unchanged(client, tmp_path):
    root = existing(tmp_path / 'existing')
    before = fingerprints(root)
    scan = preview(client, root)
    assert scan['engine'] == 'unreal' and scan['engine_version'] == '4.27'
    assert scan['counts']['image'] == 1 and scan['counts']['design'] == 2
    assert not store.rows('SELECT * FROM projects')
    p = attach(client, scan)
    state = store.snapshot(p['id'])
    assert p['root'] == str(root.resolve()) and len(state['assets']) == 1
    assert len(state['documents']) == 3 and not state['tasks']
    assert fingerprints(root) == before
    report = state['intake']['report']
    assert report['runtime_verified'] is False and report['claims'][0]['path'] == 'Docs/Design.md'
    context = asyncio.run(agent_tools.execute(p['id'], False, 'get_project', {}))
    assert context['existing_project']['runtime_verified'] is False
    assert context['existing_project']['summary_document_id']
    assert '无昼夜系统' in json.dumps(context, ensure_ascii=False)
    assert 'NEVER_IMPORT' not in json.dumps(state, ensure_ascii=False)
    assert all(a['source'].startswith(str(root)) for a in state['assets'])


def test_intake_unity_detection_duplicate_roots_and_preview_staleness(client, tmp_path):
    root = existing(tmp_path / 'unity', 'unity')
    scan = preview(client, root)
    assert scan['engine'] == 'unity' and scan['engine_version'] == '6000.5.3f1'
    (root / 'Docs/Design.md').write_text('changed', encoding='utf-8')
    bad = client.post('/api/project-intake/attach', json={'preview_id': scan['id'], 'engine': 'unity', 'documents': scan['suggested_documents']})
    assert bad.status_code == 400 and not store.rows('SELECT * FROM projects')
    p = attach(client, preview(client, root))
    duplicate = client.post('/api/project-intake/attach', json={'preview_id': preview(client, root)['id'], 'engine': 'unity', 'documents': []})
    assert duplicate.status_code == 400 and p['engine'] == 'unity'
    assert client.post('/api/project-intake/preview', json={'root': str(root / 'missing')}).status_code == 400


def test_intake_rescan_preserves_edits_and_marks_changes(client, tmp_path):
    root = existing(tmp_path / 'existing')
    p = attach(client, preview(client, root))
    old = next(d for d in store.snapshot(p['id'])['documents'] if 'Design.md' in d['title'])
    client.patch('/api/documents/' + old['id'], json={'revision': 1, 'content': '工作台人工修订', 'authority': 'approved'})
    a = store.snapshot(p['id'])['assets'][0]
    client.post('/api/assets/' + a['id'] + '/edit', json={'expected_hash': hashlib.sha256(image_bytes()).hexdigest(), 'width': 12})
    (root / 'Docs/Design.md').write_text('# 新设计\n改为即时制', encoding='utf-8')
    (root / 'Content/Textures/hero.png').unlink()
    (root / 'Content/Textures/new.png').write_bytes(image_bytes())
    r = client.post(f"/api/projects/{p['id']}/intake/refresh")
    assert r.status_code == 200, r.text
    state = store.snapshot(p['id'])
    assert next(d for d in state['documents'] if d['id'] == old['id'])['content'] == '工作台人工修订'
    assert state['intake']['report']['changes']['missing'] == 1
    assert state['intake']['report']['changes']['added'] == 1
    assert state['intake']['report']['changes']['changed'] == 1
    assert len(state['assets']) == 2
    assert Path(store.one('SELECT active FROM assets WHERE id=?', (a['id'],))['active']).exists()
    again = client.post(f"/api/projects/{p['id']}/intake/refresh").json()
    assert again['report']['changes']['changed'] == 0


def test_intake_backup_restores_inventory_without_scanning_unrelated_folders(client, tmp_path):
    root = existing(tmp_path / 'existing')
    p = attach(client, preview(client, root))
    raw = client.get(f"/api/projects/{p['id']}/export").content
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        manifest = json.loads(z.read('project.json'))
        assert manifest['format'] == 10 and 'project_intakes' in manifest
    r = client.post('/api/import-project', files={'file': ('backup.zip', raw)})
    assert r.status_code == 200, r.text
    copied = store.snapshot(r.json()['id'])
    assert copied['intake']['report']['restored_snapshot'] is True
    assert copied['intake']['summary_document_id'] != store.snapshot(p['id'])['intake']['summary_document_id']
    summary = next(d['content'] for d in copied['documents'] if d['id'] == copied['intake']['summary_document_id'])
    for f in intake.current(r.json()['id'], True)['files']:
        if f.get('document_id'):
            assert f['document_id'] in summary
    assert client.post(f"/api/projects/{r.json()['id']}/intake/refresh").status_code == 400


def test_intake_caps_sensitive_files_and_symlink_escape(client, tmp_path, monkeypatch):
    root = existing(tmp_path / 'existing')
    (root / 'Docs/secrets.md').write_text('DO_NOT_READ_THIS')
    (root / 'Docs/Large.md').write_text('x' * (intake.MAX_TEXT_BYTES + 1))
    try:
        (root / 'Docs/outside.md').symlink_to(tmp_path / 'elsewhere.md')
    except OSError:
        pass
    scan = preview(client, root)
    assert 'Docs/Large.md' not in scan['suggested_documents']
    p = attach(client, scan)
    assert 'DO_NOT_READ_THIS' not in json.dumps(store.snapshot(p['id']))
    monkeypatch.setattr(intake, 'MAX_FILES', 2)
    limited = preview(client, root)
    assert limited['truncated'] is True


def test_intake_file_tools_scope_selection_and_changed_content(client, tmp_path):
    import pytest
    root = existing(tmp_path / 'existing')
    (root / 'ProjectSettings').mkdir()
    (root / 'ProjectSettings/NotSelected.md').write_text('Not selected for model reading')
    scan = preview(client, root)
    p = attach(client, scan, documents=['README.md'])
    scope = {'pid': p['id'], 'agent': 'director', 'write': False}
    def call(name, args): return asyncio.run(agent_tools.invoke(scope, name, args))
    source = call('read_project_file', {'path': 'Source/Hero.cs', 'offset': 0, 'limit': 12000})
    assert 'class HeroController' in source['content']
    assert call('search_project_files', {'query': 'Hero', 'category': 'code', 'offset': 0, 'limit': 10})['total'] == 1
    for path in ('../outside.md', '.env', 'Docs/Design.md', 'ProjectSettings/NotSelected.md', 'Content/Textures/hero.png'):
        with pytest.raises(ValueError): call('read_project_file', {'path': path, 'offset': 0, 'limit': 100})
    for agent in ('music', 'modeler'):
        with pytest.raises(ValueError):
            asyncio.run(agent_tools.invoke({**scope, 'agent': agent}, 'read_project_file', {'path': 'Source/Hero.cs', 'offset': 0, 'limit': 100}))
    (root / 'Source/Hero.cs').write_text('public class ChangedHero {}')
    with pytest.raises(ValueError, match='变化'):
        call('read_project_file', {'path': 'Source/Hero.cs', 'offset': 0, 'limit': 100})
    client.post(f"/api/projects/{p['id']}/intake/refresh")
    assert 'ChangedHero' in call('read_project_file', {'path': 'Source/Hero.cs', 'offset': 0, 'limit': 100})['content']


def test_partial_rescan_cannot_mark_unseen_files_missing(client, tmp_path, monkeypatch):
    root = existing(tmp_path / 'existing')
    (root / 'Content/model.obj').write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3')
    p = attach(client, preview(client, root))
    assert any(a['kind'] == 'source' and a['category'] == 'model' for a in store.snapshot(p['id'])['assets'])
    monkeypatch.setattr(intake, 'MAX_FILES', 2)
    result = client.post(f"/api/projects/{p['id']}/intake/refresh").json()
    assert result['report']['truncated'] and result['report']['changes']['missing'] == 0
    inventory = client.get(f"/api/projects/{p['id']}/intake/files").json()['items']
    assert any(f['status'] == 'unseen' for f in inventory) and not any(f['status'] == 'missing' for f in inventory)


def test_unreadable_changed_design_never_becomes_current_context(client, tmp_path):
    root = existing(tmp_path / 'existing')
    p = attach(client, preview(client, root))
    (root / 'Docs/Design.md').write_text('x' * (intake.MAX_TEXT_BYTES + 1))
    client.post(f"/api/projects/{p['id']}/intake/refresh")
    context = asyncio.run(agent_tools.execute(p['id'], False, 'get_project', {}))
    doc = next(d for d in context['documents'] if 'Design.md' in d['title'])
    assert doc['source']['status'] == 'source_changed' and doc['content_excerpt'] == ''
