"""Run with Unreal -ExecCmds=py <script> in the isolated test project."""
import json
import threading
import urllib.request
from pathlib import Path
import unreal
import gameworkbench_bridge

gameworkbench_bridge.start()
root = gameworkbench_bridge.project_root()
finished = threading.Event()


def request(path, payload=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['X-Workbench-Token'] = token
    req = urllib.request.Request('http://127.0.0.1:8765/api' + path,
                                 data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=35) as response:
        return json.load(response)


def verify():
    result = {}
    try:
        boot = request('/bootstrap'); token = boot['token']
        project = next((p for p in boot['projects'] if p['name'] == '虚幻连接器验收'), None)
        if not project:
            project = request('/projects', {'name': '虚幻连接器验收', 'engine': 'unreal', 'root': str(root)}, token)
        pid = project['id']
        result['status'] = request('/projects/' + pid + '/engine/command', {'op': 'status'}, token)
        result['scan'] = request('/projects/' + pid + '/scan', {}, token)
        result['preview'] = request('/projects/' + pid + '/engine/command', {'op': 'preview', 'path': '/Game/WorkbenchTest/test'}, token)
        preview_info = request('/assets/' + result['preview']['preview_asset_id'] + '/info')
        assert preview_info['width'] == 32 and preview_info['height'] == 32
        state = request('/projects/' + pid)
        material = next(a for a in state['assets'] if a['name'] == 'TestInstance.uasset')
        info = request('/assets/' + material['id'] + '/info')
        args = {'op': 'set_material_color', 'path': '/Game/WorkbenchTest/TestInstance', 'name': 'Tint',
                'color': [0.7, 0.3, 0.2, 1], 'asset_id': material['id'], 'expected_hash': info['hash']}
        result['changed'] = request('/projects/' + pid + '/engine/command', args, token)
        # A fresh editor process must read the value saved by the previous verification.
        assert result['changed']['previous_color'] == [1, 1, 1, 1]
        args['expected_hash'] = request('/assets/' + material['id'] + '/info')['hash']
        args['color'] = result['changed']['previous_color']
        result['restored'] = request('/projects/' + pid + '/engine/command', args, token)
        result['passed'] = bool(result['changed']['saved'] and result['restored']['saved'])
    except Exception as e:
        result['passed'] = False; result['error'] = str(e)
    (root / 'http-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    finished.set()


def tick(delta):
    if finished.is_set():
        unreal.unregister_slate_post_tick_callback(tick_handle)
        unreal.SystemLibrary.quit_editor()


tick_handle = unreal.register_slate_post_tick_callback(tick)
threading.Thread(target=verify, daemon=True).start()
