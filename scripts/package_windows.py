"""Build Windows x64 portable ZIP and graphical installer with private CPython.

Run on Windows using a build Python with pip. Never packages the build environment.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

from check_release import ROOT, check

PYTHON = '3.13.17'
PYTHON_SHA256 = '9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38'
PYTHON_URL = f'https://www.python.org/ftp/python/{PYTHON}/python-{PYTHON}-embed-amd64.zip'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_python(cache):
    path = cache / 'python-embed.zip'
    if not path.is_file() or sha(path) != PYTHON_SHA256:
        with urllib.request.urlopen(PYTHON_URL, timeout=60) as response:
            raw = response.read(30 * 1024 * 1024 + 1)
        if len(raw) > 30 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != PYTHON_SHA256:
            raise ValueError('CPython download failed SHA-256 validation')
        path.write_bytes(raw)
    return path


def compile_cs(source, output, resources=()):
    compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:anycpu', '/reference:System.Windows.Forms.dll',
        '/reference:System.IO.Compression.dll', '/reference:System.Web.Extensions.dll', '/reference:Microsoft.CSharp.dll', '/win32icon:' + str(ROOT / 'public/brand/app.ico'), '/out:' + str(output),
        *['/resource:' + str(path) + ',' + name for path, name in resources], str(source)], check=True)


def main():
    if os.name != 'nt': raise ValueError('Build the Windows distribution on Windows x64')
    files = check()
    version = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version']
    build_info = json.loads((ROOT / 'dist/workbench-build.json').read_text(encoding='utf-8'))
    if build_info['version'] != version: raise ValueError('Build the current UI before packaging')
    for relative, digest in build_info['files'].items():
        target = (ROOT / 'dist' / relative).resolve()
        if not target.is_relative_to(ROOT / 'dist') or sha(target) != digest: raise ValueError('UI checksum mismatch')
    cache = ROOT / '.dev/windows-build'
    cache.mkdir(parents=True, exist_ok=True)
    # Every invocation stages a new directory. No recursive delete of a computed path.
    from uuid import uuid4
    app = cache / ('stage-' + uuid4().hex)
    app.mkdir()
    include = list(files)
    include += [p.relative_to(ROOT) for p in (ROOT / 'dist').rglob('*') if p.is_file()]
    for relative in include:
        source = ROOT / relative
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT): raise ValueError('Unsupported source path')
        destination = app / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    runtime = app / '.runtime/python'
    runtime.mkdir(parents=True)
    with zipfile.ZipFile(fetch_python(cache)) as archive: archive.extractall(runtime)
    (runtime / 'python313._pth').write_text('python313.zip\n.\nLib\\site-packages\n..\\..\\\nimport site\n', encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--only-binary=:all:',
        '--platform', 'win_amd64', '--python-version', '313', '--implementation', 'cp', '--abi', 'cp313', '--no-compile',
        '--target', str(runtime / 'Lib/site-packages'), '-r', str(ROOT / 'requirements.lock.txt')], check=True)
    subprocess.run([str(runtime / 'python.exe'), '-B', '-X', 'utf8', '-c', 'import backend.app,sqlite3,ssl,PIL._imaging,pydantic_core; print("Private runtime imports OK")'], cwd=app, check=True)
    (app / 'packaged.json').write_text(json.dumps({'format': 1, 'version': version, 'python': PYTHON, 'python_sha256': PYTHON_SHA256, 'python_source': PYTHON_URL}, indent=2) + '\n', encoding='utf-8')
    compile_cs(ROOT / 'scripts/windows/Launcher.cs', app / 'Questweft.exe')
    picker = ROOT / 'scripts/windows/Picker.cs'
    compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/reference:System.Windows.Forms.dll', '/reference:System.Web.Extensions.dll', '/win32icon:' + str(ROOT / 'public/brand/app.ico'), '/out:' + str(app / 'Questweft-Picker.exe'), str(picker)], check=True)
    hashes = {p.relative_to(app).as_posix(): sha(p) for p in sorted(app.rglob('*')) if p.is_file()}
    (app / 'SHA256SUMS.json').write_text(json.dumps(hashes, indent=2) + '\n', encoding='utf-8')
    releases = ROOT / '.releases'
    releases.mkdir(exist_ok=True)
    portable = releases / f'Questweft-{version}-windows-x64.zip'
    with zipfile.ZipFile(portable, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob('*')):
            if path.is_file(): archive.write(path, path.relative_to(app).as_posix())
    version_file = cache / 'version.txt'
    version_file.write_text(version, encoding='utf-8')
    installer = releases / f'Questweft-{version}-windows-x64-setup.exe'
    compile_cs(ROOT / 'scripts/windows/Installer.cs', installer, [(portable, 'payload'), (version_file, 'version')])
    for artifact in (portable, installer):
        artifact.with_suffix(artifact.suffix + '.sha256').write_text(sha(artifact) + '  ' + artifact.name + '\n', encoding='utf-8')
        print(f'{artifact.name}: {artifact.stat().st_size:,} bytes; SHA256 {sha(artifact)}')
    print('Unsigned Windows x64 package. Python and wheel licenses are retained in .runtime/python.')


if __name__ == '__main__': main()
