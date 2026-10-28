import contextlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from backend import __version__, app as module, diagnostics, instance, launcher as runtime_launcher, store
from test_workbench import client, project

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell.exe') if os.name == 'nt' else None
windows = pytest.mark.skipif(not POWERSHELL, reason='Windows PowerShell launcher integration')


def test_identity_is_stable_for_paths_but_distinguishes_data_directories(client, tmp_path):
    one = instance.identity(tmp_path / '数据 A')
    two = instance.identity(tmp_path / '数据 B')
    assert one['workspace_id'] == two['workspace_id'] and one['data_id'] != two['data_id']
    assert one['data_id'] == instance.fingerprint(tmp_path / '数据 A' / '..' / '数据 A')
    assert not (tmp_path / '数据 A').exists()
    health = client.get('/api/health').json()
    assert health['instance_id'] == client.get('/api/bootstrap').json()['service']['instance_id']
    assert health['data_id'] == instance.fingerprint(store.DATA) and health['protocol'] == 1
    assert str(store.DATA) not in json.dumps(health) and 'token' not in health
    session = client.get('/api/server/session').json()
    runtime_launcher.owner(session['service'], instance.identity())
    assert 'projects' not in session


def test_stop_rejects_stale_instance_before_requesting_exit(client, monkeypatch):
    server = SimpleNamespace(should_exit=False)
    monkeypatch.setattr(module.app.state, 'server', server, raising=False)
    assert client.post('/api/server/stop', json={'instance_id': '0' * 32}).status_code == 400
    assert not server.should_exit
    assert client.post('/api/server/stop', json={'unknown': True}).status_code == 400
    assert not server.should_exit
    assert client.post('/api/server/stop', json={'instance_id': instance.INSTANCE_ID}).json()['stopping']
    assert server.should_exit


def test_diagnostics_never_query_services_install_or_read_credentials(client, monkeypatch):
    p = project(client)
    store.set_setting('not_a_diagnostic_setting', 'private-fixture-marker')
    def forbidden(*a, **kw): raise AssertionError('No subprocess or credentials in diagnosis')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(module.secrets, 'get_key', forbidden)
    monkeypatch.setattr(module.music, 'helper', forbidden)
    monkeypatch.setattr(module.tripo, 'request', forbidden)
    first = client.get('/api/diagnostics').json()
    assert first['write_probe'] is False
    assert next(c for c in first['checks'] if c['key'] == 'data_write')['status'] == 'pending'
    assert 'private-fixture-marker' not in json.dumps(first)
    checked = client.post('/api/diagnostics/check', json={'write_probe': True})
    assert checked.status_code == 200, checked.text
    assert next(c for c in checked.json()['checks'] if c['key'] == 'data_write')['status'] == 'found'
    assert store.project(p['id']) == p and not list(store.DATA.glob('.workbench-check-*'))
    assert store.rows('SELECT * FROM projects') == [p]


@pytest.mark.parametrize('body', [{}, [], {'write_probe': False}, {'write_probe': 1}, {'write_probe': True, 'path': 'other'}])
def test_write_probe_requires_exact_request(client, body):
    assert client.post('/api/diagnostics/check', json=body).status_code == 400


def test_missing_optional_tools_do_not_make_core_dependencies_missing(client, monkeypatch):
    monkeypatch.setattr(diagnostics.shutil, 'which', lambda name: None)
    monkeypatch.setattr(diagnostics.codex, 'executable', lambda: None)
    result = client.get('/api/diagnostics').json()
    rows = {c['key']: c for c in result['checks']}
    assert rows['git']['status'] == rows['codex']['status'] == rows['node']['status'] == 'optional_missing'
    assert not rows['git']['core'] and rows['httpx']['status'] in ('found', 'different')
    assert rows['database']['status'] == 'found'


def test_missing_package_corrupt_database_and_failed_write_are_reported_without_reset(client, monkeypatch, tmp_path):
    original = diagnostics.metadata.version
    def version(name):
        if name == 'httpx': raise diagnostics.metadata.PackageNotFoundError(name)
        return original(name)
    monkeypatch.setattr(diagnostics.metadata, 'version', version)
    damaged = tmp_path / 'damaged'; damaged.mkdir()
    database = damaged / 'workbench.sqlite3'; database.write_bytes(b'synthetic-corrupt-db')
    monkeypatch.setattr(store, 'DATA', damaged)
    def no_write(**kwargs): raise PermissionError('fixture')
    monkeypatch.setattr(diagnostics.tempfile, 'TemporaryFile', no_write)
    report = diagnostics.inspect(True)
    rows = {c['key']: c for c in report['checks']}
    assert rows['httpx']['status'] == rows['database']['status'] == rows['data_write']['status'] == 'missing'
    assert database.read_bytes() == b'synthetic-corrupt-db'


def test_identity_and_diagnostics_cli_do_not_initialize_data(tmp_path):
    folder = tmp_path / '未建立的 数据目录'
    env = {**os.environ, 'WORKBENCH_DATA': str(folder)}
    result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'backend.instance', '--identity'], cwd=ROOT, env=env, capture_output=True, check=True)
    value = json.loads(result.stdout)
    assert value['data_id'] == instance.fingerprint(folder)
    result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'backend.diagnostics'], cwd=ROOT, env=env, capture_output=True, check=True)
    assert next(c for c in json.loads(result.stdout)['checks'] if c['key'] == 'database')['status'] == 'pending'
    assert not folder.exists()


def test_connection_refusal_and_reset_are_not_treated_as_http_failures(monkeypatch):
    from urllib.error import URLError
    def refused(*args, **kwargs): raise URLError(OSError(10061, 'fixture refused'))
    monkeypatch.setattr(runtime_launcher.request, 'build_opener', lambda *args: SimpleNamespace(open=refused))
    assert runtime_launcher.read(12345, '/api/health') is None
    def reset(*args, **kwargs): raise ConnectionResetError('fixture reset')
    monkeypatch.setattr(runtime_launcher.request, 'build_opener', lambda *args: SimpleNamespace(open=reset))
    monkeypatch.setattr(runtime_launcher, 'port_free', lambda port: False)
    with pytest.raises(runtime_launcher.UnconfirmedConnection): runtime_launcher.read(12345, '/api/health')


def test_timeout_means_absent_only_for_health_with_exclusively_free_port(monkeypatch):
    from urllib.error import URLError
    def timeout(*args, **kwargs): raise URLError(TimeoutError('fixture'))
    monkeypatch.setattr(runtime_launcher.request, 'build_opener', lambda *args: SimpleNamespace(open=timeout))
    monkeypatch.setattr(runtime_launcher, 'port_free', lambda port: False)
    with pytest.raises(runtime_launcher.UnconfirmedConnection): runtime_launcher.read(12345, '/api/health')
    monkeypatch.setattr(runtime_launcher, 'port_free', lambda port: True)
    assert runtime_launcher.read(12345, '/api/health') is None
    with pytest.raises(runtime_launcher.UnconfirmedConnection): runtime_launcher.read(12345, '/api/server/stop', {})


def test_port_probe_does_not_bind_over_existing_listener():
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0)); listener.listen()
        port = listener.getsockname()[1]
        assert not runtime_launcher.port_free(port)
    assert runtime_launcher.port_free(port)


def test_stop_rechecks_after_reset_without_repeating_stop_request(monkeypatch, tmp_path):
    health = owner(store.ROOT, tmp_path)
    sequence = iter([health, {'token': 'fixture-token', 'service': health}, {'stopping': True}, runtime_launcher.UnconfirmedConnection('reset'), None])
    paths = []
    def read(port, path, *args):
        paths.append(path); value = next(sequence)
        if isinstance(value, Exception): raise value
        return value
    monkeypatch.setattr(runtime_launcher, 'read', read)
    monkeypatch.setattr(runtime_launcher.time, 'sleep', lambda duration: None)
    assert runtime_launcher.stop(12345, tmp_path)['stopped']
    assert paths.count('/api/server/stop') == 1


def test_http_error_after_stop_is_not_reported_as_confirmed_exit(monkeypatch, tmp_path):
    health = owner(store.ROOT, tmp_path)
    sequence = iter([health, {'token': 'fixture-token', 'service': health}, {'stopping': True}, ValueError('HTTP503')])
    paths = []
    def read(port, path, *args):
        paths.append(path); value = next(sequence)
        if isinstance(value, Exception): raise value
        return value
    monkeypatch.setattr(runtime_launcher, 'read', read)
    monkeypatch.setattr(runtime_launcher.time, 'sleep', lambda duration: None)
    with pytest.raises(ValueError, match='HTTP503'): runtime_launcher.stop(12345, tmp_path)
    assert paths.count('/api/server/stop') == 1


def copy_workspace(tmp_path):
    root = tmp_path / '工作台 source with spaces'
    root.mkdir()
    shutil.copytree(ROOT / 'backend', root / 'backend', ignore=shutil.ignore_patterns('__pycache__'))
    (root / 'scripts').mkdir()
    for name in ('Start-Workbench.ps1', 'Stop-Workbench.ps1', 'check_release.py'):
        shutil.copy2(ROOT / 'scripts' / name, root / 'scripts' / name)
        if name.endswith('.ps1'): assert (root / 'scripts' / name).read_bytes().startswith(b'\xef\xbb\xbf')
    shutil.copy2(ROOT / 'requirements.lock.txt', root / 'requirements.lock.txt')
    (root / 'dist').mkdir(); (root / 'dist/index.html').write_text('<title>Synthetic launcher fixture</title>')
    return root


def launcher(root, name, port, data, *extra):
    return subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(root / 'scripts' / name),
                           '-Port', str(port), '-DataDirectory', str(data), '-PythonExecutable', sys.executable, *extra],
                          cwd=root, capture_output=True, timeout=40)


@contextlib.contextmanager
def fake_service(health, bootstrap=None, stop=False):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def send(self, value):
            raw = json.dumps(value).encode(); self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw); self.wfile.flush()
        def do_GET(self):
            requests.append(self.path)
            self.send(health if self.path == '/api/health' else bootstrap or {'token': 'fixture-token'})
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('content-length', 0))))
            requests.append((self.path, body)); self.send({'stopping': True})
            if stop:
                def close(): server.shutdown(); server.server_close()
                threading.Thread(target=close, daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield server.server_port, requests
    finally: server.shutdown(); server.server_close(); thread.join(timeout=3)


def owner(root, data):
    return {'ok': True, 'product': 'game-workbench', 'version': __version__, 'protocol': 1, 'instance_id': 'a' * 32,
            'workspace_id': instance.fingerprint(root), 'data_id': instance.fingerprint(data)}


@windows
@pytest.mark.parametrize('field,value', [('workspace_id', '0' * 64), ('data_id', '0' * 64), ('protocol', 2)])
def test_launchers_reject_foreign_identity_before_bootstrap(tmp_path, field, value):
    root = copy_workspace(tmp_path); data = tmp_path / '数据 space'
    health = {**owner(root, data), field: value}
    with fake_service(health) as (port, requests):
        assert launcher(root, 'Start-Workbench.ps1', port, data, '-NoBrowser').returncode != 0
        assert launcher(root, 'Stop-Workbench.ps1', port, data, '-LegacyConfirmed').returncode != 0
        assert requests == ['/api/health', '/api/health']
    assert not data.exists()


@windows
def test_launcher_refuses_version_mismatch_and_stop_checks_bootstrap_instance(tmp_path):
    root = copy_workspace(tmp_path); data = tmp_path / '数据 space'; health = owner(root, data)
    with fake_service({**health, 'version': '0.0.0'}) as (port, requests):
        assert launcher(root, 'Start-Workbench.ps1', port, data, '-NoBrowser').returncode != 0
        assert requests == ['/api/health']
    with fake_service(health, {'token': 'fixture-token', 'service': {**health, 'instance_id': 'b' * 32}}) as (port, requests):
        assert launcher(root, 'Stop-Workbench.ps1', port, data).returncode != 0
        assert requests == ['/api/health', '/api/server/session']


@windows
def test_legacy_stop_is_never_automatic(tmp_path):
    root = copy_workspace(tmp_path); data = tmp_path / '数据 space'
    health = {'product': 'game-workbench', 'version': '0.13.0', 'ok': True}
    with fake_service(health, stop=True) as (port, requests):
        assert launcher(root, 'Stop-Workbench.ps1', port, data).returncode != 0
        result = launcher(root, 'Stop-Workbench.ps1', port, data, '-LegacyConfirmed')
        assert result.returncode == 0, result.stderr.decode(errors='replace')
        assert ('/api/server/stop', {}) in requests
    assert not data.exists()


@windows
def test_real_launcher_reuse_custom_directory_restart_and_stop(tmp_path):
    root = copy_workspace(tmp_path); data = tmp_path / '保留 data with spaces'
    with socket.socket() as sock: sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    with httpx.Client(base_url=url, timeout=3, trust_env=False) as client:
        try:
            result = launcher(root, 'Start-Workbench.ps1', port, data, '-NoBrowser')
            assert result.returncode == 0, result.stderr.decode(errors='replace')
            first = client.get('/api/health').json()
            assert first['data_id'] == instance.fingerprint(data) and first['launch_id']
            assert not (root / '.workbench').exists() and (data / 'workbench.sqlite3').is_file()
            boot = client.get('/api/bootstrap').json()
            p = client.post('/api/projects', headers={'x-workbench-token': boot['token']}, json={'name': '保留的自制项目', 'engine': 'unreal', 'root': ''}).json()
            with sqlite3.connect(data / 'workbench.sqlite3') as db:
                db.execute('INSERT INTO runs (id,project_id,kind,status,detail,created,updated) VALUES (?,?,?,?,?,?,?)',
                           ('synthetic-running', p['id'], 'fixture', 'running', 'not an actual generation', store.now(), store.now()))
            with socket.socket() as sock: sock.bind(('127.0.0.1', 0)); other_port = sock.getsockname()[1]
            blocked = launcher(root, 'Start-Workbench.ps1', other_port, data, '-NoBrowser')
            assert blocked.returncode != 0
            with sqlite3.connect(data / 'workbench.sqlite3') as db:
                assert db.execute("SELECT status FROM runs WHERE id='synthetic-running'").fetchone()[0] == 'running'
            assert client.get('/api/health').json()['instance_id'] == first['instance_id']
            logs = set((data / 'logs').glob('*.log'))
            assert launcher(root, 'Start-Workbench.ps1', port, data, '-NoBrowser').returncode == 0
            assert client.get('/api/health').json()['instance_id'] == first['instance_id'] and set((data / 'logs').glob('*.log')) == logs
            assert launcher(root, 'Stop-Workbench.ps1', port, tmp_path / 'other').returncode != 0
            assert client.get('/api/health').json()['instance_id'] == first['instance_id']
            result = launcher(root, 'Stop-Workbench.ps1', port, data)
            assert result.returncode == 0, result.stderr.decode(errors='replace')
            assert launcher(root, 'Start-Workbench.ps1', port, data, '-NoBrowser').returncode == 0
            second = client.get('/api/health').json()
            assert second['instance_id'] != first['instance_id'] and second['data_id'] == first['data_id']
            assert any(x['id'] == p['id'] for x in client.get('/api/bootstrap').json()['projects'])
            assert len(set((data / 'logs').glob('*.log'))) == len(logs) + 2
        finally:
            try:
                health = client.get('/api/health').json()
                if health.get('workspace_id') == instance.fingerprint(root) and health.get('data_id') == instance.fingerprint(data):
                    token = client.get('/api/bootstrap').json()['token']
                    client.post('/api/server/stop', headers={'x-workbench-token': token}, json={'instance_id': health['instance_id']})
                    for _ in range(50):
                        time.sleep(.1)
                        try: client.get('/api/health')
                        except httpx.HTTPError: break
            except httpx.HTTPError: pass
