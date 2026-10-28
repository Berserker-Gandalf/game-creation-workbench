"""Local dependency discovery; no provider requests, installs or credential reads."""
import argparse
from importlib import metadata, util
import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from . import codex, instance, store

PACKAGES = {'fastapi': 'fastapi', 'uvicorn': 'uvicorn', 'httpx': 'httpx', 'Pillow': 'PIL',
            'python-multipart': 'python_multipart', 'tinytag': 'tinytag'}


def inspect(write_probe=False):
    checks = []
    def add(key, title, status, message, action, page='diagnostics', core=False, details=None):
        checks.append(dict(key=key, title=title, status=status, message=message, action=action, page=page, core=core, details=details or {}))
    add('python', 'Python 运行环境', 'found' if sys.version_info >= (3, 12) else 'missing',
        platform.python_version(), '使用 Python 3.12 或更新的兼容环境，再按锁定依赖安装。', core=True,
        details={'executable': sys.executable})
    locked = {}
    lock = store.ROOT / 'requirements.lock.txt'
    if lock.is_file(): locked = dict(line.split('==', 1) for line in lock.read_text(encoding='utf-8').splitlines() if '==' in line)
    for package, module in PACKAGES.items():
        try:
            version = metadata.version(package)
            found = util.find_spec(module) is not None
        except (metadata.PackageNotFoundError, ImportError, ValueError): version, found = '', False
        expected = locked.get(package.casefold())
        status = 'missing' if not found else 'different' if expected and version != expected else 'found'
        add(package, package + ' 依赖', status, version or '未找到安装记录',
            '使用当前 Python 安装 requirements.lock.txt；本页不会安装或升级。', core=True,
            details={'installed': version, 'locked': expected, 'scope': '安装元数据及模块文件检测，不执行模型调用'})
    built = (store.ROOT / 'dist/index.html').is_file()
    add('frontend', '生产界面', 'found' if built else 'missing', '已找到构建入口' if built else '未找到构建后的界面',
        '源码模式先安装前端依赖并运行 npm run build；发行包应包含 dist。', core=True)
    data = store.DATA
    add('data_directory', '工作台数据目录', 'found' if data.is_dir() else 'pending',
        '目录存在；写入能力需另行检测' if data.is_dir() else '目录尚未建立',
        '通过 WORKBENCH_DATA 或启动器的 DataDirectory 选择数据目录；搬迁前先留存备份。', core=True,
        details={'path': str(data), 'workspace': str(store.ROOT), 'logs': str(data / 'logs')})
    database = data / 'workbench.sqlite3'
    if database.is_file():
        try:
            connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)
            try: valid = connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='projects'").fetchone()[0] == 1
            finally: connection.close()
            status, message = ('found', '数据库可读取，已找到项目表') if valid else ('missing', '尚未找到工作台项目表')
        except sqlite3.Error: status, message = 'missing', '数据库无法读取；未尝试修复或重建'
    else: status, message = 'pending', '数据库尚未初始化，标准服务首次启动时建立'
    add('database', '本机数据库', status, message, '先核对数据目录及备份；不要删除数据库来重置程序。', core=True)
    status, message = 'pending', '尚未进行实际写入检测'
    if write_probe:
        try:
            with tempfile.TemporaryFile(dir=data, prefix='.workbench-check-') as probe:
                probe.write(b'workbench-check'); probe.flush(); os.fsync(probe.fileno())
                probe.seek(0)
                if probe.read() != b'workbench-check': raise OSError('write mismatch')
            status, message = 'found', '临时文件写入、读取及清理通过，项目文件未修改'
        except OSError: status, message = 'missing', '无法完成临时文件写入/清理，请核对目录和磁盘'
    add('data_write', '数据写入检测', status, message, '点击运行本机诊断检测写入，或选择可写的数据目录。', core=True)
    try:
        target = next(p for p in (data, *data.parents) if p.is_dir())
        free = shutil.disk_usage(target).free
        add('disk', '数据磁盘空间', 'different' if free < 1024 ** 3 else 'found', f'可用约 {free / 1024 ** 3:.1f} GiB',
            '实际生成和快照另行检查所需空间；本项不预留磁盘。')
    except OSError: add('disk', '数据磁盘空间', 'pending', '无法读取可用空间', '核对数据目录所在磁盘。')
    settings = {}
    if database.is_file():
        try:
            connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)
            try: settings = {k: json.loads(v) for k, v in connection.execute("SELECT key,value FROM settings WHERE key IN ('blender_executable','webui_config')")}
            finally: connection.close()
        except (sqlite3.Error, ValueError): pass
    node = shutil.which('node')
    for key, label, path, page in [('node', 'Node.js（可选）', node, 'music'), ('npm', 'npm（源码构建可选）', shutil.which('npm.cmd') or shutil.which('npm'), 'connections'),
                                   ('git', 'Git（项目发布可选）', shutil.which('git'), 'management')]:
        add(key, label, 'found' if path else 'optional_missing', '已发现程序文件' if path else '未发现程序路径', '按需安装可信发行版后重新检测；发现文件不代表功能已验证。', page, details={'path': path})
    command = codex.executable()
    add('codex', 'Codex 本机入口（可选）', 'found' if command else 'optional_missing', '已发现可调用入口，未登录或推理核验' if command else '未找到本机入口',
        '在“模型与引擎”检查连接与登录；本次不启动 Codex 或读取账号凭据。', 'connections', details={'command': command})
    skill = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'skills/suno-cn-music/scripts/suno-client.mjs'
    add('suno', 'Suno.cn Skill（可选）', 'found' if skill.is_file() and node else 'optional_missing',
        '已发现原版 helper 和 Node.js；授权状态未查询' if skill.is_file() and node else '需要原版 Skill helper 及 Node.js',
        '选择项目后到音乐工作区检查 Skill 与授权。', 'music')
    blender = settings.get('blender_executable') or shutil.which('blender')
    found = isinstance(blender, str) and Path(blender).is_file()
    add('blender', 'Blender（可选）', 'found' if found else 'optional_missing', '已发现程序文件，未运行建模' if found else '未找到已配置的程序文件',
        '在角色建模工作区选择可信安装，再做独立建模验收。', 'blender', details={'path': blender})
    config = settings.get('webui_config')
    root = Path(config['root']) if isinstance(config, dict) and isinstance(config.get('root'), str) and config['root'] else None
    found = bool(root and (root / 'modules/api/api.py').is_file() and (root / 'models').is_dir())
    add('webui', 'WebUI 本机目录（可选）', 'found' if found else 'optional_missing', '目录结构已发现，API在线状态未查询' if found else '尚未发现有效配置目录',
        '在 WebUI 绘画页配置路径，并显式连接检查模型。', 'webui', details={'root': str(root) if root else None})
    return {'service': instance.current(), 'checked_at': store.now(), 'checks': checks,
            'core_missing': sum(c['core'] and c['status'] == 'missing' for c in checks),
            'core_pending': sum(c['core'] and c['status'] in ('pending', 'different') for c in checks),
            'write_probe': write_probe, 'note': '本机文件和运行环境检查；不查询余额、不调用模型、不安装工具，不代表真实生成或引擎运行已验收。'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write-probe', action='store_true')
    args = parser.parse_args()
    print(json.dumps(inspect(args.write_probe), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
