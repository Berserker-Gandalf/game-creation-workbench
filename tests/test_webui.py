import base64
import io
import json
import struct
import zipfile

import httpx
import pytest
from PIL import Image, PngImagePlugin

from backend import store
from test_workbench import client, project, image_bytes, upload_image


@pytest.fixture
def library(client, tmp_path):
    root = tmp_path / 'webui'
    (root / 'modules/api').mkdir(parents=True)
    (root / 'modules/api/api.py').write_text('# fixture', encoding='utf-8')
    for directory in ('models/Stable-diffusion', 'models/Lora', 'outputs/txt2img-images'):
        (root / directory).mkdir(parents=True)
    metadata = json.dumps({'__metadata__': {'ss_base_model_version': 'sd_v1', 'ss_output_name': 'fixture_style'}}).encode()
    for name in ('models/Stable-diffusion/base.safetensors', 'models/Lora/style.safetensors'):
        (root / name).write_bytes(struct.pack('<Q', len(metadata)) + metadata)
    Image.new('RGB', (24, 16), 'orange').save(root / 'outputs/txt2img-images/sample.png')
    response = client.put('/api/webui/config', json={'root': str(root), 'url': 'http://127.0.0.1:7860'})
    assert response.status_code == 200, response.text
    return root


def online(monkeypatch, root, on_generate=None):
    original, calls = httpx.AsyncClient, []
    def handler(request):
        calls.append(request)
        path = request.url.path
        if path.endswith('/options'):
            assert request.method == 'GET', 'must not change global WebUI options'
            value = {'sd_model_checkpoint': 'base [fixture]'}
        elif path.endswith('/sd-models'):
            value = [{'title': 'base [fixture]', 'model_name': 'base', 'sha256': 'fixture-sha', 'filename': str(root / 'models/Stable-diffusion/base.safetensors')}]
        elif path.endswith('/loras'):
            value = [{'name': 'style', 'alias': 'fixture_style', 'path': str(root / 'models/Lora/style.safetensors'), 'metadata': {}}]
        elif path.endswith('/samplers'):
            value = [{'name': 'Euler a'}]
        elif path.endswith('/txt2img') or path.endswith('/img2img'):
            if on_generate:
                return on_generate(request)
            value = {'images': [base64.b64encode(image_bytes()).decode()], 'info': json.dumps({'seed': 42, 'sd_model_name': 'base', 'infotexts': ['fixture generation parameters']})}
        else:
            return httpx.Response(404)
        return httpx.Response(200, json=value)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    return calls


def test_webui_offline_inventory_and_local_url_boundary(client, library):
    values = client.get('/api/webui/catalog', params={'live': False}).json()
    assert not values['online'] and len(values['checkpoints']) == len(values['loras']) == 1
    assert values['loras'][0]['base_model'] == 'sd_v1'
    for url in ('https://example.com', 'http://127.0.0.1:7860/path', 'http://localhost:7860@evil.example', 'http://127.0.0.1:7860?secret=x'):
        assert client.put('/api/webui/config', json={'root': str(library), 'url': url}).status_code == 400
    assert client.get('/api/webui/config').json()['url'] == 'http://127.0.0.1:7860'


def test_webui_generation_uses_scoped_model_lora_and_records_provenance(client, library, monkeypatch):
    p = project(client)
    calls = online(monkeypatch, library)
    response = client.post(f"/api/projects/{p['id']}/generate-image", json={
        'provider': 'webui', 'prompt': 'a small room', 'checkpoint': 'models/Stable-diffusion/base.safetensors',
        'loras': [{'id': 'models/Lora/style.safetensors', 'weight': 0.7}], 'sampler': 'Euler a', 'seed': -1,
        'width': 512, 'height': 512, 'steps': 12, 'cfg_scale': 7})
    assert response.status_code == 200, response.text
    aid = response.json()['id']
    request = next(r for r in calls if r.url.path.endswith('/txt2img'))
    payload = json.loads(request.content)
    assert payload['override_settings'] == {'sd_model_checkpoint': 'base [fixture]'}
    assert payload['override_settings_restore_afterwards'] is True
    assert '<lora:style:0.7>' in payload['prompt']
    assert payload['batch_size'] == payload['n_iter'] == 1 and payload['save_images'] is False
    records = client.get(f"/api/projects/{p['id']}/art-jobs").json()
    assert records[0]['asset_id'] == aid and json.loads(records[0]['result'])['seed'] == 42
    raw = client.get(f"/api/projects/{p['id']}/export").content
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert json.loads(archive.read('project.json'))['format'] == 10
    restored = client.post('/api/import-project', files={'file': ('backup.zip', raw)}).json()
    copy = client.get(f"/api/projects/{restored['id']}/art-jobs").json()[0]
    assert copy['asset_id'] != aid and copy['run_id'] != records[0]['run_id']


def test_webui_outputs_import_is_idempotent_and_refuses_outside_or_changed_file(client, library):
    p = project(client)
    listing = client.get('/api/webui/outputs').json()
    item = listing['items'][0]
    endpoint = f"/api/projects/{p['id']}/webui/import"
    first = client.post(endpoint, json={'path': item['path'], 'version': item['version']})
    assert first.status_code == 200, first.text
    second = client.post(endpoint, json={'path': item['path'], 'version': item['version']})
    assert first.json()['asset']['id'] == second.json()['asset']['id']
    assert len(client.get(f"/api/projects/{p['id']}/art-jobs").json()) == 1
    assert client.get('/api/webui/output-file', params={'path': '../config.json'}).status_code == 400
    assert client.get('/api/webui/output-file', params={'path': 'models/Stable-diffusion/base.safetensors'}).status_code == 400
    (library / item['path']).write_bytes(image_bytes())
    assert client.post(endpoint, json={'path': item['path'], 'version': item['version']}).status_code == 400


def test_webui_img2img_converts_alpha_mask_and_rejects_bad_parameters(client, library, monkeypatch):
    p = project(client)
    a = upload_image(client, p['id'])
    mask = io.BytesIO(); Image.new('RGBA', (24, 16), (0, 0, 0, 0)).save(mask, 'PNG')
    m = upload_image(client, p['id'], 'mask.png', mask.getvalue())
    calls = online(monkeypatch, library)
    base = {'provider': 'webui', 'prompt': 'a room', 'checkpoint': 'models/Stable-diffusion/base.safetensors',
            'sampler': 'Euler a', 'expected_hash': client.get('/api/assets/' + a['id'] + '/info').json()['hash'], 'mask_asset_id': m['id']}
    endpoint = '/api/assets/' + a['id'] + '/ai-edit'
    assert client.post(endpoint, json={**base, 'steps': True}).status_code == 400
    assert client.post(endpoint, json={**base, 'loras': [{'id': '../outside', 'weight': 1}]}).status_code == 400
    assert not any(r.method == 'POST' for r in calls)
    result = client.post(endpoint, json=base)
    assert result.status_code == 200 and result.json()['applied'], result.text
    payload = json.loads(next(r for r in calls if r.url.path.endswith('/img2img')).content)
    with Image.open(io.BytesIO(base64.b64decode(payload['mask']))) as image:
        assert image.getextrema() == (255, 255)


def test_webui_timeout_is_not_retried(client, library, monkeypatch):
    p = project(client)
    def timeout(request): raise httpx.ReadTimeout('fixture')
    calls = online(monkeypatch, library, timeout)
    r = client.post(f"/api/projects/{p['id']}/generate-image", json={'provider': 'webui', 'prompt': 'room', 'checkpoint': 'models/Stable-diffusion/base.safetensors', 'sampler': 'Euler a'})
    assert r.status_code == 400
    assert len([r for r in calls if r.url.path.endswith('/txt2img')]) == 1
    record = client.get(f"/api/projects/{p['id']}/art-jobs").json()[0]
    assert record['status'] == 'failed' and record['asset_id'] is None


def test_webui_import_preserves_png_parameters_and_concurrent_calls_reuse_asset(client, library):
    from concurrent.futures import ThreadPoolExecutor
    from backend import webui
    p = project(client)
    info = PngImagePlugin.PngInfo(); info.add_text('parameters', 'room\nSteps: 12, Seed: 77')
    Image.new('RGB', (32, 32), 'orange').save(library / 'outputs/metadata.png', pnginfo=info)
    item = next(i for i in webui.outputs()['items'] if i['name'] == 'metadata.png')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: webui.import_output(p['id'], item), range(2)))
    assert results[0]['asset']['id'] == results[1]['asset']['id']
    records = client.get(f"/api/projects/{p['id']}/art-jobs").json()
    assert len(records) == 1 and 'Seed: 77' in json.loads(records[0]['result'])['infotext']


def test_webui_edit_backup_remaps_source_and_mask_ids(client, library, monkeypatch):
    p = project(client)
    a = upload_image(client, p['id'])
    online(monkeypatch, library)
    r = client.post('/api/assets/' + a['id'] + '/ai-edit', json={
        'provider': 'webui', 'prompt': 'room', 'checkpoint': 'models/Stable-diffusion/base.safetensors',
        'sampler': 'Euler a', 'expected_hash': client.get('/api/assets/' + a['id'] + '/info').json()['hash']})
    assert r.status_code == 200, r.text
    raw = client.get(f"/api/projects/{p['id']}/export").content
    copied = client.post('/api/import-project', files={'file': ('backup.zip', raw)}).json()
    record = client.get(f"/api/projects/{copied['id']}/art-jobs").json()[0]
    assert json.loads(record['spec'])['source_asset_id'] == record['asset_id'] != a['id']


def test_webui_rejects_connection_change_during_catalog_without_generation(client, library, monkeypatch):
    from backend import webui
    p = project(client)
    calls = online(monkeypatch, library)
    original = webui.catalog
    async def changing(*args, **kwargs):
        value = await original(*args, **kwargs)
        webui.save_config({'url': 'http://127.0.0.1:7862'})
        return value
    monkeypatch.setattr(webui, 'catalog', changing)
    r = client.post(f"/api/projects/{p['id']}/generate-image", json={
        'provider': 'webui', 'prompt': 'room', 'checkpoint': 'models/Stable-diffusion/base.safetensors', 'sampler': 'Euler a'})
    assert r.status_code == 400 and '配置已变化' in r.json()['detail']
    assert not any(r.method == 'POST' for r in calls)
