"""Live visual-tool check using a generated, non-user test fixture."""
import io
import json
from pathlib import Path
import httpx
from PIL import Image, ImageDraw

with httpx.Client(base_url='http://127.0.0.1:8765', timeout=300, trust_env=False) as client:
    boot = client.get('/api/bootstrap').json()
    client.headers['x-workbench-token'] = boot['token']
    p = next((p for p in boot['projects'] if p['name'] == '工作台接入验收'), None)
    if p is None:
        created = client.post('/api/projects', json={'name': '工作台接入验收', 'engine': 'unreal'})
        created.raise_for_status()
        p = created.json()
    image = Image.new('RGB', (320, 240), '#1d2735')
    draw = ImageDraw.Draw(image); draw.rectangle((50, 40, 140, 200), fill='#ee944b'); draw.ellipse((180, 70, 270, 160), fill='#6cbca0')
    output = io.BytesIO(); image.save(output, format='PNG')
    a = client.post(f"/api/projects/{p['id']}/upload", files={'file': ('视觉工具验收.png', output.getvalue(), 'image/png')}).json()['asset']
    reply = []
    with client.stream('POST', f"/api/projects/{p['id']}/chat", json={'provider': 'codex', 'execute': True, 'asset_id': a['id'],
        'message': f"这是视觉工具验收。请使用 view_asset 查看 ID={a['id']} 的图片，简短描述其中两个形状及颜色，然后使用 edit_image 将此资产尺寸改为 160×120，flip=false，务必使用工具返回的哈希。不要创建其他文件、文档或任务。"}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith('data: '):
                event = json.loads(line[6:])
                if event['event'] == 'delta': reply.append(event['text'])
                elif event['event'] in ('activity', 'error', 'done'): print(json.dumps(event, ensure_ascii=False), flush=True)
    info = client.get('/api/assets/' + a['id'] + '/info').json()
    result = {'asset_id': a['id'], 'width': info['width'], 'height': info['height'], 'versions': len(info['versions']), 'reply': ''.join(reply)}
    Path('.dev/vision-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)
    assert info['width'] == 160 and info['height'] == 120 and len(info['versions']) == 2
