"""Real Blender verification in a fresh local test project; never uses normal data."""
import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--blender', required=True, help='Path to the installed Blender executable')
args = parser.parse_args()
folder = ROOT / '.dev' / ('blender-check-' + uuid4().hex[:12])
folder.mkdir(parents=True)
os.environ['WORKBENCH_DATA'] = str(folder / 'data')
import sys
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from backend import app as module, modeling, store

CHECK = '''
import bpy,json,sys
from pathlib import Path
folder=Path(sys.argv[sys.argv.index('--')+1])
bpy.ops.wm.open_mainfile(filepath=str(folder/'character.blend'),load_ui=False,use_scripts=False)
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
assert len(meshes)>=20 and not any(o.type=='ARMATURE' for o in bpy.context.scene.objects)
assert json.loads(bpy.context.scene['workbench_recipe'])['height']>0
assert len(bpy.data.materials)>=4
source_count=len(meshes)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=str(folder/'character.glb'))
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
assert len(meshes)==source_count and all(len(o.data.vertices)>0 for o in meshes)
assert all(o.data.materials for o in meshes)
print('WORKBENCH_REOPEN_OK '+str(source_count))
'''


async def generate(pid):
    results = []
    for recipe in ({'title': '探索者'}, {'title': '大头法师', 'style': 'chibi', 'head_ratio': .29, 'leg_ratio': .38, 'hair': 'bob', 'accessory': 'staff'},
                   {'title': '机器人', 'style': 'robot', 'outfit': 'armor', 'hair': 'none', 'accessory': 'none', 'pose': 't_pose'}):
        j = modeling.draft(pid, recipe)
        await modeling.start(j['id'], True)
        await modeling.RUNNING[j['id']]['task']
        result = modeling.job(j['id'])
        assert result['status'] == 'review', result
        output = store.project_dir(pid) / 'modeling' / j['id']
        checked = subprocess.run([str(Path(args.blender).resolve()), '--background', '--factory-startup', '--disable-autoexec',
                                  '--offline-mode', '--python-exit-code', '1', '--python-expr', CHECK, '--', str(output)],
                                 capture_output=True, timeout=120)
        (output / 'reopen.log').write_bytes(checked.stdout + checked.stderr)
        assert checked.returncode == 0 and b'WORKBENCH_REOPEN_OK' in checked.stdout, 'Inspect reopen.log'
        results.append({'style': recipe.get('style', 'human'), **json.loads(result['result'])['stats'], 'source_reopened': True, 'glb_imported': True})
    return results


with TestClient(module.app) as client:
    client.headers['x-workbench-token'] = client.get('/api/bootstrap').json()['token']
    store.set_setting('blender_executable', str(Path(args.blender).resolve()))
    p = client.post('/api/projects', json={'name': 'Blender 独立验证', 'engine': 'unreal'}).json()
    results = asyncio.run(generate(p['id']))
    backup = client.get(f"/api/projects/{p['id']}/export").content
    restored = client.post('/api/import-project', files={'file': ('blender.zip', backup)})
    assert restored.status_code == 200, restored.text
    copied = modeling.jobs(restored.json()['id'])
    assert len(copied) == 3 and all(j['status'] == 'review' for j in copied)
    for j in copied:
        for key in ('model_id', 'source_id', 'preview_id'):
            assert client.get('/api/assets/' + j[key] + '/file').status_code == 200
    report = {'recipes': results, 'backup_restore': True, 'cloud_requests': 0, 'engine_runtime_verified': False}
    (folder / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    print('Evidence: ' + str(folder))
