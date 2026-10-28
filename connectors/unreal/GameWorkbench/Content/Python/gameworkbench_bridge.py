"""Unreal 4.27 editor bridge. All Unreal operations execute on the editor thread."""
import json
import os
import queue
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import unreal

_queue = queue.Queue()
_server = None
_tick = None
_token = None


def project_root():
    return Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())).resolve()


def handle(data):
    op = data.get('op')
    if op == 'status':
        return {'engine': 'unreal', 'version': unreal.SystemLibrary.get_engine_version(),
                'project_root': str(project_root()), 'capabilities': ['list_assets', 'inspect', 'preview:texture', 'set_material_color']}
    if op == 'list_assets':
        found = unreal.AssetRegistryHelpers.get_asset_registry().get_assets_by_path('/Game', recursive=True)
        return {'assets': [{'path': str(a.object_path), 'name': str(a.asset_name), 'type': str(a.asset_class)} for a in found[:1000]]}
    path = data.get('path', '')
    if not path.startswith('/Game/') or '..' in path:
        raise ValueError('Only /Game project assets are supported')
    obj = unreal.EditorAssetLibrary.load_asset(path)
    if not obj:
        raise ValueError('Asset not found')
    if op == 'inspect':
        result = {'path': obj.get_path_name(), 'name': obj.get_name(), 'type': obj.get_class().get_name()}
        if isinstance(obj, unreal.MaterialInstanceConstant):
            result['vector_parameters'] = [str(n) for n in unreal.MaterialEditingLibrary.get_vector_parameter_names(obj)]
        return result
    if op == 'preview':
        if not isinstance(obj, unreal.Texture):
            raise ValueError('This connector currently exports texture previews only; open other assets in Unreal')
        folder = project_root() / 'Saved/GameWorkbench/previews'
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / (obj.get_name() + '-' + secrets.token_hex(4) + '.tga')
        task = unreal.AssetExportTask()
        task.object, task.filename, task.automated = obj, str(dest), True
        task.prompt, task.replace_identical = False, True
        if not unreal.Exporter.run_asset_export_task(task) or not dest.exists():
            raise ValueError('Texture export failed; inspect Unreal Output Log')
        return {'file': str(dest), 'preview_mode': 'exported_texture'}
    if op == 'set_material_color':
        if not isinstance(obj, unreal.MaterialInstanceConstant):
            raise ValueError('Select a MaterialInstanceConstant, not a base material')
        name, values = data.get('name', ''), data.get('color', [])
        names = [str(n) for n in unreal.MaterialEditingLibrary.get_vector_parameter_names(obj)]
        if name not in names or len(values) != 4 or not all(0 <= v <= 1 for v in values):
            raise ValueError('Unknown vector parameter or invalid RGBA')
        old = unreal.MaterialEditingLibrary.get_material_instance_vector_parameter_value(obj, name)
        before = [old.r, old.g, old.b, old.a]
        backup_folder = '/Game/__WorkbenchBackups'
        unreal.EditorAssetLibrary.make_directory(backup_folder)
        backup_path = backup_folder + '/' + obj.get_name() + '_' + secrets.token_hex(4)
        backup = unreal.EditorAssetLibrary.duplicate_asset(path, backup_path)
        if not backup or not unreal.EditorAssetLibrary.save_loaded_asset(backup):
            raise ValueError('Could not create asset backup')
        with unreal.ScopedEditorTransaction('Game Workbench material color'):
            obj.modify()
            unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(obj, name, unreal.LinearColor(*values))
            unreal.MaterialEditingLibrary.update_material_instance(obj)
            actual = unreal.MaterialEditingLibrary.get_material_instance_vector_parameter_value(obj, name)
            if any(abs(a - b) > 0.0001 for a, b in zip([actual.r, actual.g, actual.b, actual.a], values)):
                raise ValueError('Material parameter did not match requested value')
        if not unreal.EditorAssetLibrary.save_loaded_asset(obj):
            raise ValueError('Save failed; backup is available at ' + backup_path)
        return {'saved': True, 'path': path, 'name': name, 'previous_color': before, 'color': values, 'backup': backup_path}
    raise ValueError('Unsupported operation')


def _drain(delta):
    for _ in range(8):
        try:
            payload, result, ready = _queue.get_nowait()
        except queue.Empty:
            return
        try:
            result.update(handle(payload))
        except Exception as e:
            result['error'] = str(e)
        finally:
            ready.set()


def start():
    global _server, _tick, _token
    if _server:
        return
    _token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/command' or self.headers.get('Authorization') != 'Bearer ' + _token:
                self.send_error(403)
                return
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 65536:
                self.send_error(413)
                return
            try:
                payload = json.loads(self.rfile.read(size))
            except ValueError:
                self.send_error(400)
                return
            result, ready = {}, threading.Event()
            _queue.put((payload, result, ready))
            if not ready.wait(25):
                result = {'error': 'Editor is busy. Check the operation before retrying.'}
            raw = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except OSError:
                pass

        def log_message(self, *args):
            pass

    _server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    _server.daemon_threads = True
    folder = project_root() / 'Saved/GameWorkbench'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'connection.json').write_text(json.dumps({'engine': 'unreal', 'port': _server.server_port,
                                                       'token': _token, 'project_root': str(project_root())}), encoding='utf-8')
    _tick = unreal.register_slate_post_tick_callback(_drain)
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    unreal.log('Game Workbench bridge started on loopback')
