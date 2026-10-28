import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from backend import hardware, music, onboarding, path_picker, skill_setup, store, workbench_actions
from test_workbench import client


def skill_archive(files=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name in files or skill_setup.FILES: archive.writestr(zipfile.ZipInfo('suno-cn-music/' + name), 'fixture original content')
    return buffer.getvalue()


def test_skill_download_pin_atomic_activation_and_global_preservation(client, monkeypatch, tmp_path):
    global_root = tmp_path / 'global/skills/suno-cn-music'
    (global_root / 'scripts').mkdir(parents=True)
    (global_root / 'scripts/suno-client.mjs').write_text('existing helper')
    (global_root / 'SKILL.md').write_text('existing skill')
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'global'))
    assert music.installation()[0] == global_root
    raw = skill_archive()
    monkeypatch.setattr(skill_setup, 'download', lambda: raw)
    with pytest.raises(ValueError, match='校验失败'): skill_setup.install()
    assert not skill_setup.root().exists()
    monkeypatch.setattr(skill_setup, 'SHA256', hashlib.sha256(raw).hexdigest())
    assert skill_setup.install()['installed']
    assert music.installation()[0] == skill_setup.root()
    assert (global_root / 'scripts/suno-client.mjs').read_text() == 'existing helper'
    assert skill_setup.install()['reused']
    assert not list(skill_setup.root().parent.glob('.suno-stage-*'))
    assert not store.rows('SELECT id FROM music_jobs')


@pytest.mark.parametrize('bad', ['../escape', '/absolute', 'scripts/../../escape', 'auth.json', 'scripts\\evil.mjs'])
def test_skill_rejects_unsafe_or_unexpected_zip(client, monkeypatch, bad):
    files = set(skill_setup.FILES) - {'install.sh'} | {bad}
    raw = skill_archive(files)
    monkeypatch.setattr(skill_setup, 'download', lambda: raw)
    monkeypatch.setattr(skill_setup, 'SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError): skill_setup.install()
    assert not skill_setup.root().exists()


def test_suno_plan_orders_node_and_installs_without_account_requests(client, monkeypatch):
    found = {key: False for key in ['node', 'suno', 'codex', 'blender', 'git']}
    monkeypatch.setattr(onboarding, 'installed', lambda: found.copy())
    monkeypatch.setattr(onboarding, 'windows', lambda: True)
    monkeypatch.setattr(onboarding.shutil, 'which', lambda v: 'fixture' if v == 'winget' else None)
    plan = client.post('/api/onboarding/plan', json={'tools': ['suno']}).json()
    assert [s['tool'] for s in plan['steps']] == ['node', 'suno']
    assert skill_setup.SHA256 in plan['steps'][1]['source']
    calls = []
    def install(): calls.append('download-only'); found['suno'] = True
    async def forbidden(*a): raise AssertionError('No account or generation request')
    found['node'] = True
    monkeypatch.setattr(music, 'helper', forbidden)
    monkeypatch.setattr(skill_setup, 'install', install)
    row = {'id': 'skill', 'steps': plan['steps'], 'status': 'running', 'completed': []}
    asyncio.run(onboarding.worker(row))
    assert row['status'] == 'succeeded' and row['completed'] == ['node', 'suno']
    assert calls == ['download-only']


def test_native_picker_cancel_selection_and_human_only(client, monkeypatch, tmp_path):
    if os.name != 'nt':
        response = client.post('/api/system/path-picker', json={'purpose': 'source'})
        assert response.status_code == 400 and '手动填写' in response.json()['detail']
        return
    result = {'path': None}
    async def executable(): return tmp_path / 'fixture-picker.exe'
    monkeypatch.setattr(path_picker, 'executable', executable)
    async def spawn(*args, **kwargs):
        assert args == (str(tmp_path / 'fixture-picker.exe'),) and 'shell' not in kwargs
        assert kwargs['env']['WORKBENCH_PICK_KIND'] == 'source'
        async def communicate(): return json.dumps(result).encode(), b''
        return SimpleNamespace(communicate=communicate, returncode=0)
    monkeypatch.setattr(path_picker.asyncio, 'create_subprocess_exec', spawn)
    assert client.post('/api/system/path-picker', json={'purpose': 'source'}).json() == {'path': None}
    result['path'] = str(tmp_path)
    assert client.post('/api/system/path-picker', json={'purpose': 'source', 'initial': str(tmp_path)}).json() == result
    assert client.post('/api/system/path-picker', json={'purpose': 'shell'}).status_code == 400
    assert client.post('/api/system/path-picker', json={'purpose': 'source', 'command': 'fixture'}).status_code == 400
    assert not any('/system/path-picker' in a['path'] or '/webui/preflight' in a['path'] for a in workbench_actions.ACTIONS)


def test_preflight_advisories_and_unknown_vram_without_running_project(client, monkeypatch, tmp_path):
    monkeypatch.setattr(hardware, 'memory', lambda: {'total': 8 * hardware.GIB, 'available': 3 * hardware.GIB})
    monkeypatch.setattr(hardware, 'gpus', lambda: [{'name': 'AMD fixture', 'vram': None, 'driver': 'fixture', 'source': 'Windows CIM'}])
    monkeypatch.setattr(hardware.shutil, 'disk_usage', lambda p: SimpleNamespace(free=9 * hardware.GIB, total=100 * hardware.GIB))
    response = client.post('/api/webui/preflight', json={'root': str(tmp_path), 'family': 'sdxl', 'download_gib': 5})
    assert response.status_code == 200
    report = response.json()
    assert {c['key']: c['status'] for c in report['checks']} == {'ram': 'advisory', 'gpu': 'unknown', 'disk': 'advisory', 'webui': 'advisory'}
    assert report['starting_size'] == 1024 and report['disk']['required'] == 15 * hardware.GIB
    for invalid in [{'family': 'arbitrary'}, {'download_gib': float('inf')}, {'root': str(tmp_path / 'missing')}, {'root': 1}, {'command': 'fixture'}]:
        if invalid.get('download_gib') == float('inf'): invalid['download_gib'] = 1001
        assert client.post('/api/webui/preflight', json=invalid).status_code == 400


def test_gpu_parse_and_no_wmi_32bit_ram_fallback(monkeypatch):
    monkeypatch.setattr(hardware.shutil, 'which', lambda _: 'fixture-nvidia-smi')
    calls = []
    def run(args): calls.append(args); return 'NVIDIA fixture, 12288, 999.00\n'
    monkeypatch.setattr(hardware, 'run', run)
    assert hardware.gpus()[0]['vram'] == 12 * hardware.GIB
    assert '--query-gpu=name,memory.total,driver_version' in calls[0]
    monkeypatch.setattr(hardware.shutil, 'which', lambda _: None)
    monkeypatch.setattr(hardware, 'run', lambda args: '[{"Name":"AMD fixture","DriverVersion":"1","AdapterRAM":4294967295}]')
    if os.name == 'nt': assert hardware.gpus()[0]['vram'] is None
    else: assert hardware.gpus() == []


def test_non_windows_picker_and_gpu_fallback_do_not_launch_windows_tools(client, monkeypatch):
    monkeypatch.setattr(path_picker, 'os', SimpleNamespace(name='posix'))
    monkeypatch.setattr(hardware, 'os', SimpleNamespace(name='posix'))
    monkeypatch.setattr(hardware.shutil, 'which', lambda _: None)
    async def forbidden(*args, **kwargs): raise AssertionError('No Windows helper on other systems')
    monkeypatch.setattr(path_picker.asyncio, 'create_subprocess_exec', forbidden)
    assert client.post('/api/system/path-picker', json={'purpose': 'project'}).status_code == 400
    assert hardware.gpus() == []


def test_packaged_default_data_separate_and_override(tmp_path):
    import subprocess
    import sys
    import shutil
    (tmp_path / 'backend').mkdir()
    shutil.copy(store.ROOT / 'backend/store.py', tmp_path / 'backend/store.py')
    (tmp_path / 'packaged.json').write_text('{}')
    environment = {**os.environ, 'LOCALAPPDATA': str(tmp_path / 'user')}
    environment.pop('WORKBENCH_DATA', None)
    code = 'from backend.store import DATA; print(DATA)'
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=environment, capture_output=True, text=True, check=True)
    assert Path(result.stdout.strip()) == tmp_path / 'user/ZAOWU/data'
    environment['WORKBENCH_DATA'] = str(tmp_path / 'custom')
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=environment, capture_output=True, text=True, check=True)
    assert Path(result.stdout.strip()) == tmp_path / 'custom'
