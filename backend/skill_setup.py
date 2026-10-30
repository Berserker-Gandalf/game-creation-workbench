"""Install the pinned original Suno.cn package, without reading account files."""
import hashlib
import io
from pathlib import Path, PurePosixPath
import tempfile
import urllib.request
import zipfile

from . import store

URL = 'https://mcp.suno.cn/mcp/skill/download'
VERSION = '2.4.0'
SHA256 = '30983208ed2b8c4f8a90a0505159abf580b986384d19b032aa734c59d8bcb319'
FILES = {'SKILL.md', 'INSTALL.md', 'references/api.md', 'scripts/suno-client.mjs', 'install.sh'}


def root():
    return store.DATA / 'tools/skills/suno-cn-music'


def valid(path):
    path = Path(path)
    return (path / 'SKILL.md').is_file() and (path / 'scripts/suno-client.mjs').is_file()


def download():
    request = urllib.request.Request(URL, headers={'User-Agent': 'Questweft-Workbench-Setup'})
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.geturl().split('?', 1)[0] != URL: raise ValueError('音乐 Skill 下载来源发生变化，请核对供应方指引')
        return response.read(2 * 1024 * 1024 + 1)


def install():
    raw = download()
    if len(raw) > 2 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError('音乐 Skill 安装包校验失败，原有安装保留；请核对供应方版本')
    parent = root().parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.suno-stage-', dir=parent) as temporary:
        stage = Path(temporary) / 'suno-cn-music'
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if len(archive.infolist()) != len(FILES): raise ValueError('音乐 Skill 安装包内容无效')
            seen = set()
            for item in archive.infolist():
                path = PurePosixPath(item.filename)
                relative = path.relative_to('suno-cn-music').as_posix() if path.parts and path.parts[0] == 'suno-cn-music' else ''
                if relative not in FILES or relative in seen or '\\' in item.filename or item.file_size > 1024 * 1024 or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('音乐 Skill 安装包内容无效')
                seen.add(relative)
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))
        if not valid(stage): raise ValueError('音乐 Skill 安装包内容无效')
        # Existing managed installations are never overwritten; global Skills and credentials are untouched.
        if root().exists():
            if valid(root()): return {'installed': True, 'version': VERSION, 'reused': True}
            raise ValueError('音乐 Skill 目标目录已有不完整文件，请先人工检查，未覆盖')
        stage.rename(root())
    return {'installed': True, 'version': VERSION, 'sha256': SHA256}
