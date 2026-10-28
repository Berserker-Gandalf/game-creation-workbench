"""Human-only Windows picker. Choosing a path does not grant agent access."""
import asyncio
import json
import hashlib
import os
from pathlib import Path
import subprocess

from . import store

PURPOSES = {'project', 'source', 'webui', 'snapshot', 'restore', 'blender'}
LOCK = asyncio.Lock()


async def executable():
    bundled = store.ROOT / 'ZAOWU-Picker.exe'
    if bundled.is_file(): return bundled
    source = store.ROOT / 'scripts/windows/Picker.cs'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    target = store.DATA / 'tools/picker' / (digest + '.exe')
    if target.is_file(): return target
    target.parent.mkdir(parents=True, exist_ok=True)
    compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    process = await asyncio.create_subprocess_exec(str(compiler), '/nologo', '/target:winexe',
        '/reference:System.Windows.Forms.dll', '/reference:System.Web.Extensions.dll', '/out:' + str(target), str(source),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try: code = await asyncio.wait_for(process.wait(), 30)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        if process.returncode is None: process.kill()
        await process.wait()
        raise ValueError('无法准备目录选择窗口，请手动填写路径') from None
    if code or not target.is_file(): raise ValueError('无法准备目录选择窗口，请手动填写路径')
    return target


async def choose(data):
    if not isinstance(data, dict) or set(data) - {'purpose', 'initial'} or data.get('purpose') not in PURPOSES:
        raise ValueError('目录选择用途无效')
    initial = data.get('initial', '')
    if not isinstance(initial, str) or len(initial) > 4096 or '\x00' in initial:
        raise ValueError('目录选择初始路径无效')
    if os.name != 'nt': raise ValueError('当前系统不支持图形化目录选择，请手动填写路径')
    if LOCK.locked(): raise ValueError('已有目录选择窗口，请先完成或取消')
    async with LOCK:
        picker = await executable()
        env = {**os.environ, 'WORKBENCH_PICK_INITIAL': initial, 'WORKBENCH_PICK_KIND': data['purpose']}
        process = await asyncio.create_subprocess_exec(str(picker), env=env, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 300)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            if process.returncode is None: process.kill()
            await process.wait()
            raise ValueError('目录选择已超时或取消，请重试或手动填写路径') from None
        try:
            result = json.loads(output.decode('utf-8-sig'))
            selected = result['path']
            if process.returncode or (selected is not None and (not isinstance(selected, str) or not Path(selected).exists())):
                raise ValueError()
            return {'path': selected}
        except (ValueError, KeyError, TypeError):
            raise ValueError('无法打开目录选择窗口，请手动填写路径') from None
