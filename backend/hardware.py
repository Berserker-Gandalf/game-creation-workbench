"""Bounded, read-only hardware probes; never import a project's Python or torch."""
import csv
import ctypes
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from . import store

GIB = 1024 ** 3


def run(args):
    try:
        result = subprocess.run(args, capture_output=True, timeout=12, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return result.stdout[:65536].decode('utf-8-sig', errors='replace') if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired): return ''


def memory():
    if os.name != 'nt': return None
    class Status(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [(key, ctypes.c_ulonglong) for key in ('total', 'available', 'page_total', 'page_available', 'virtual_total', 'virtual_available', 'extended')]
    status = Status()
    status.length = ctypes.sizeof(status)
    return {'total': status.total, 'available': status.available} if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None


def gpus():
    executable = shutil.which('nvidia-smi')
    if executable:
        output = run([executable, '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader,nounits'])
        found = []
        for row in csv.reader(io.StringIO(output)):
            if len(row) != 3: continue
            try: size = int(row[1].strip()) * 1024 ** 2
            except ValueError: size = None
            found.append({'name': row[0].strip()[:200], 'vram': size, 'driver': row[2].strip()[:100], 'source': 'nvidia-smi'})
        if found: return found
    if os.name == 'nt':
        powershell = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        output = run([str(powershell), '-NoProfile', '-Command', "[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false); @(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion) | ConvertTo-Json -Compress"])
        try:
            rows = json.loads(output)
            if isinstance(rows, dict): rows = [rows]
            return [{'name': str(r.get('Name', ''))[:200], 'vram': None, 'driver': str(r.get('DriverVersion', ''))[:100], 'source': 'Windows CIM'} for r in rows[:8]]
        except (ValueError, TypeError, AttributeError): pass
    return []


def inspect(data):
    if not isinstance(data, dict) or set(data) - {'root', 'family', 'download_gib'}:
        raise ValueError('硬件预检参数无效')
    root, family, download = data.get('root', ''), data.get('family', 'sd15'), data.get('download_gib', 0)
    if not isinstance(root, str) or len(root) > 4096 or '\x00' in root or family not in ('sd15', 'sdxl') or type(download) not in (int, float) or not 0 <= download <= 1000:
        raise ValueError('硬件预检参数无效')
    path = Path(root).expanduser().resolve() if root.strip() else store.DATA
    if not path.is_dir(): raise ValueError('请选择现有目录后进行硬件预检')
    ram, cards = memory(), gpus()
    disk = shutil.disk_usage(path)
    ram_target, vram_target = (8, 4) if family == 'sd15' else (16, 8)
    checks = []
    def add(key, status, message): checks.append({'key': key, 'status': status, 'message': message})
    add('ram', 'unknown' if not ram else 'advisory' if ram['total'] < ram_target * GIB else 'ready', '系统内存建议值为 8 GiB（SD 1.5）或 16 GiB（SDXL），不代表运行保证')
    known = [g['vram'] for g in cards if g['vram'] is not None]
    add('gpu', 'unknown' if not known else 'advisory' if max(known) < vram_target * GIB else 'ready', '显存建议值为 4 GiB（SD 1.5）或 8 GiB（SDXL）；未知显存和非 CUDA 后端需单独验证')
    required = (download + 10) * GIB
    add('disk', 'advisory' if disk.free < required else 'ready', '磁盘预算包含计划下载量和额外 10 GiB 余量，不包含所有模型及后续产出')
    found = bool(root.strip() and (path / 'modules/api/api.py').is_file() and (path / 'models').is_dir())
    add('webui', 'ready' if found else 'advisory', '仅检查 WebUI 标识文件；Python、torch、驱动兼容性和实际出图尚未验证')
    return {'family': family, 'cpu': platform.machine(), 'cpu_count': os.cpu_count(), 'ram': ram, 'gpus': cards,
            'disk': {'free': disk.free, 'total': disk.total, 'required': int(required)}, 'webui_found': found,
            'checks': checks, 'starting_size': 512 if family == 'sd15' else 1024,
            'guidance': '建议先以 batch 1 验证；显存紧张时可参考原 WebUI 的 medvram / lowvram 指引，预检不会修改启动参数或下载模型',
            'source': 'https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/Optimizations'}
