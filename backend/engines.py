import json
import shutil
from pathlib import Path
import httpx
from . import store, assets


def asset_target(a):
    p = store.project(a['project_id'])
    root = Path(p['root']).resolve()
    path = assets.file_for(a)
    base = root / ('Content' if p['engine'] == 'unreal' else 'Assets')
    if a['kind'] != 'native' or not path.is_relative_to(base.resolve()):
        raise ValueError('请选择工程 Content / Assets 内的原生资产，导入文件尚未绑定引擎目标')
    relative = path.relative_to(base.resolve())
    if p['engine'] == 'unreal':
        if path.suffix.lower() != '.uasset':
            raise ValueError('当前材质修改只支持 .uasset')
        return '/Game/' + relative.with_suffix('').as_posix()
    if path.suffix.lower() != '.mat':
        raise ValueError('当前材质修改只支持 .mat')
    return 'Assets/' + relative.as_posix()


def discover():
    found = []
    for drive in ('C:', 'D:', 'E:'):
        unreal = Path(drive + '/Program Files/Epic Games')
        for base in (unreal, Path(drive + '/Epic Games')):
            if base.exists():
                for folder in base.glob('UE_*'):
                    exe = folder / 'Engine/Binaries/Win64/UE4Editor-Cmd.exe'
                    if not exe.exists():
                        exe = folder / 'Engine/Binaries/Win64/UnrealEditor-Cmd.exe'
                    if exe.exists():
                        found.append({'engine': 'unreal', 'version': folder.name[3:], 'executable': str(exe)})
        for base in (Path(drive + '/Program Files/Unity/Hub/Editor'), Path(drive + '/Unity/Hub/Editor')):
            if base.exists():
                for folder in base.iterdir():
                    exe = folder / 'Editor/Unity.exe'
                    if exe.exists():
                        found.append({'engine': 'unity', 'version': folder.name, 'executable': str(exe)})
    return found


def connection(project_id):
    p = store.project(project_id)
    root = Path(p['root']).resolve()
    path = root / ('Saved' if p['engine'] == 'unreal' else 'Library') / 'GameWorkbench/connection.json'
    if not path.exists():
        raise ValueError('编辑器尚未连接。请安装连接器并打开工程。')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if Path(data['project_root']).resolve() != root or data['engine'] != p['engine']:
        raise ValueError('连接器返回的工程不匹配')
    if not 1024 <= int(data['port']) <= 65535:
        raise ValueError('无效连接端口')
    return data


async def command(project_id, op, **params):
    data = connection(project_id)
    async with httpx.AsyncClient(timeout=35, trust_env=False) as client:
        try:
            response = await client.post(f"http://127.0.0.1:{int(data['port'])}/command",
                                         headers={'Authorization': 'Bearer ' + data['token']},
                                         json={'op': op, **params})
        except httpx.TransportError:
            raise ValueError('编辑器没有响应；请确认已打开正确工程，且连接器正在运行')
    if response.is_error:
        raise ValueError('编辑器请求失败，请在引擎日志中检查连接器状态')
    result = response.json()
    if result.get('error'):
        raise ValueError(result['error'])
    return result


def install(project_id):
    p = store.project(project_id)
    root = Path(p['root']).resolve()
    if p['engine'] == 'unreal':
        files = list(root.glob('*.uproject'))
        if len(files) != 1:
            raise ValueError('请选择包含一个 .uproject 文件的真实工程根目录')
        target = root / 'Plugins/GameWorkbench'
        if target.exists():
            raise ValueError('连接器目录已存在，请在编辑器中启用，或手动核对后更新')
        config = json.loads(files[0].read_text(encoding='utf-8-sig'))
        # Keep a recoverable copy of the exact original project descriptor.
        backup = store.project_dir(project_id) / ('uproject-' + store.uid() + '.json')
        shutil.copy2(files[0], backup)
        shutil.copytree(store.ROOT / 'connectors/unreal/GameWorkbench', target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        plugins = config.setdefault('Plugins', [])
        for name in ('PythonScriptPlugin', 'EditorScriptingUtilities', 'GameWorkbench'):
            existing = next((item for item in plugins if item.get('Name') == name), None)
            if existing:
                existing['Enabled'] = True
            else:
                plugins.append({'Name': name, 'Enabled': True})
        files[0].write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'message': '连接器已安装。请重新打开工程；原工程描述文件已备份。', 'backup': str(backup)}
    if not (root / 'ProjectSettings/ProjectVersion.txt').exists():
        raise ValueError('请选择包含 ProjectSettings 的 Unity 工程根目录')
    target = root / 'Assets/Editor/GameWorkbenchBridge.cs'
    if target.exists():
        raise ValueError('连接器已存在，请打开编辑器等待编译完成')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(store.ROOT / 'connectors/unity/GameWorkbenchBridge.cs', target)
    return {'message': '连接器已安装。请在 Unity 打开工程，等待脚本编译完成。'}
