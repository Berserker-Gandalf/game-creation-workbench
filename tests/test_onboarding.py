import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from backend import app as module, onboarding, store, workbench_actions
from test_workbench import client, project


def test_first_run_existing_user_and_explicit_skip(client, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('No installs or account requests')
    with monkeypatch.context() as scope:
        scope.setattr(module.music, 'helper', forbidden)
        scope.setattr(module.secrets, 'get_key', forbidden)
        scope.setattr(onboarding, 'installed', lambda: dict.fromkeys(['node', 'codex', 'git', 'blender'], False))
        report = client.get('/api/onboarding')
        assert report.status_code == 200 and report.json()['features'] == ['core']
    assert client.get('/api/bootstrap').json()['show_onboarding']
    p = project(client)
    assert not client.get('/api/bootstrap').json()['show_onboarding']
    assert client.put('/api/onboarding', json={'features': ['api'], 'seen': True}).status_code == 200
    assert store.setting('onboarding_features') == ['core', 'api']
    assert store.project(p['id']) == p
    assert not any('/onboarding' in a['path'] for a in workbench_actions.ACTIONS)


@pytest.mark.parametrize('data', [{'tools': ['shell']}, {'tools': []}, {'tools': ['node'], 'command': 'fixture'}, [], {'tools': 'codex'}])
def test_installer_rejects_arbitrary_commands(client, data):
    assert client.post('/api/onboarding/plan', json=data).status_code == 400
    assert not onboarding.history()


def test_practice_project_is_idempotent_free_and_has_no_grants(client, monkeypatch):
    async def forbidden(*args, **kwargs): raise AssertionError('No inference or generation')
    monkeypatch.setattr(module.providers, 'stream', forbidden)
    monkeypatch.setattr(module.codex.client, 'stream', forbidden)
    payload = {'language': 'en', 'engine': 'unity'}
    first = client.post('/api/onboarding/practice', json=payload)
    assert first.status_code == 200
    p = first.json()
    assert client.post('/api/onboarding/practice', json=payload).json()['id'] == p['id']
    assert len(store.rows('SELECT id FROM projects')) == 1
    assert store.rows('SELECT status FROM tasks') == [{'status': 'todo'}]
    assert 'Start here' == store.rows('SELECT title FROM documents')[0]['title']
    assert not store.rows('SELECT id FROM runs') and not store.rows('SELECT id FROM conversations')
    assert client.get('/api/bootstrap').json()['show_onboarding'] is False


def test_fixed_plan_dependency_order_consumption_and_no_shell(client, monkeypatch):
    found = dict.fromkeys(['node', 'codex', 'git', 'blender'], False)
    monkeypatch.setattr(onboarding, 'installed', lambda: found.copy())
    monkeypatch.setattr(onboarding, 'windows', lambda: True)
    monkeypatch.setattr(onboarding.shutil, 'which', lambda name: '/fixture/winget.exe' if name == 'winget' else None)
    monkeypatch.setattr(onboarding, 'npm_command', lambda: ['/fixture/node.exe', '/fixture/npm-cli.js'])
    preview = client.post('/api/onboarding/plan', json={'tools': ['codex', 'node', 'git']}).json()
    assert [s['tool'] for s in preview['steps']] == ['node', 'codex', 'git']
    assert client.post('/api/onboarding/install', json={'plan_id': preview['id'], 'confirmed': 1}).status_code == 400
    args_seen = []
    async def spawn(*args, **kwargs):
        args_seen.append(args)
        assert 'shell' not in kwargs
        async def wait():
            tool = 'codex' if onboarding.CODEX_PACKAGE in args else 'node' if 'OpenJS.NodeJS.LTS' in args else 'git'
            found[tool] = True
            return 0
        return SimpleNamespace(wait=wait)
    monkeypatch.setattr(onboarding.asyncio, 'create_subprocess_exec', spawn)
    started = client.post('/api/onboarding/install', json={'plan_id': preview['id'], 'confirmed': True})
    assert started.status_code == 200
    import time
    for _ in range(100):
        if not onboarding.RUNNING: break
        time.sleep(.01)
    row = onboarding.history()[0]
    assert row['status'] == 'succeeded' and row['completed'] == ['node', 'codex', 'git']
    assert len(args_seen) == 3 and not any('accept' in str(arg) for args in args_seen for arg in args)
    assert '--no-upgrade' in args_seen[0] and onboarding.CODEX_PACKAGE in args_seen[1]
    assert client.post('/api/onboarding/install', json={'plan_id': preview['id'], 'confirmed': True}).status_code == 400


def test_restart_unknown_requires_human_reconciliation_and_does_not_retry(client, monkeypatch):
    row = {'id': 'fixture', 'steps': [{'tool': 'node'}], 'status': 'running'}
    onboarding.persist(row)
    onboarding.recover()
    assert onboarding.history()[0]['status'] == 'unknown'
    monkeypatch.setattr(onboarding, 'installed', lambda: {'node': True})
    assert client.post('/api/onboarding/installations/fixture/check', json={'installer_closed': 1}).status_code == 400
    assert client.post('/api/onboarding/installations/fixture/check', json={'installer_closed': True}).json()['status'] == 'succeeded'


def test_failed_installer_stops_before_dependent_tools(client, monkeypatch):
    monkeypatch.setattr(onboarding, 'installed', lambda: dict.fromkeys(['node', 'codex', 'git', 'blender'], False))
    monkeypatch.setattr(onboarding, 'command', lambda tool: ['fixture-installer', tool])
    calls = []
    async def spawn(*args, **kwargs):
        calls.append(args)
        async def wait(): return 7
        return SimpleNamespace(wait=wait)
    monkeypatch.setattr(onboarding.asyncio, 'create_subprocess_exec', spawn)
    row = {'id': 'failed-fixture', 'steps': [{'tool': 'node'}, {'tool': 'codex'}], 'completed': [], 'status': 'running'}
    asyncio.run(onboarding.worker(row))
    assert row['status'] == 'failed' and row['exit_code'] == 7
    assert calls == [('fixture-installer', 'node')] and not row['completed']


def test_unavailable_platform_is_guided_without_running_installer(client, monkeypatch):
    monkeypatch.setattr(onboarding, 'installed', lambda: dict.fromkeys(['node', 'codex', 'git', 'blender'], False))
    monkeypatch.setattr(onboarding, 'windows', lambda: False)
    response = client.post('/api/onboarding/plan', json={'tools': ['node']})
    assert response.status_code == 400 and 'WinGet' in response.json()['detail']
    assert not onboarding.history()


def test_preview_expires_and_stop_is_blocked_during_install(client, monkeypatch):
    monkeypatch.setattr(onboarding, 'installed', lambda: dict.fromkeys(['node', 'codex', 'git', 'blender'], True))
    preview = onboarding.prepare({'tools': ['codex']})
    onboarding.PLANS[preview['id']]['expires'] = 0
    assert client.post('/api/onboarding/install', json={'plan_id': preview['id'], 'confirmed': True}).status_code == 400
    monkeypatch.setattr(onboarding, 'RUNNING', {'fixture': object()})
    server = SimpleNamespace(should_exit=False)
    monkeypatch.setattr(module.app.state, 'server', server, raising=False)
    assert client.post('/api/server/stop', json={}).status_code == 400
    assert not server.should_exit
    monkeypatch.setattr(onboarding, 'RUNNING', {})


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows setup entry point')
def test_prebuilt_setup_check_needs_no_node_and_detects_damage(tmp_path):
    root = tmp_path / '首次 解压'; (root / 'scripts').mkdir(parents=True); (root / 'dist').mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'scripts/Setup.ps1', root / 'scripts/Setup.ps1')
    (root / 'package.json').write_text('{"version":"0.18.0"}', encoding='utf-8')
    (root / 'dist/index.html').write_bytes(b'fixture prebuilt UI')
    digest = hashlib.sha256((root / 'dist/index.html').read_bytes()).hexdigest()
    (root / 'dist/workbench-build.json').write_text(json.dumps({'format': 1, 'version': '0.18.0', 'files': {'index.html': digest}}), encoding='utf-8')
    powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    env = {**os.environ, 'PATH': '', 'USERPROFILE': str(tmp_path / 'empty'), 'LOCALAPPDATA': str(tmp_path / 'empty'), 'ProgramFiles': str(tmp_path / 'empty')}
    def inspect():
        result = subprocess.run([powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(root / 'scripts/Setup.ps1'), '-CheckOnly'], capture_output=True, env=env, timeout=30)
        assert result.returncode == 0, result.stderr.decode(errors='replace')
        return json.loads(result.stdout)
    assert inspect() == {'python_found': False, 'prebuilt_ready': True, 'node_required': False, 'repair': False, 'core_dependencies_ready': False}
    assert not (root / '.venv').exists() and not (root / '.workbench').exists()
    (root / 'dist/index.html').write_bytes(b'damaged')
    assert inspect()['node_required'] is True
