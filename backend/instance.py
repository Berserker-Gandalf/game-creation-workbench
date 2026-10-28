"""Local instance identity; path fingerprints distinguish checkouts and data directories."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from . import __version__, store

INSTANCE_ID = uuid4().hex
STARTED_AT = store.now()
PROTOCOL = 1


def fingerprint(path):
    value = str(Path(path).expanduser().resolve())
    return hashlib.sha256(os.path.normcase(value).encode('utf-8')).hexdigest()


def identity(data_directory=None):
    data = Path(data_directory).expanduser().resolve() if data_directory is not None else store.DATA
    return {'product': 'game-workbench', 'version': __version__, 'protocol': PROTOCOL,
            'workspace_id': fingerprint(store.ROOT), 'data_id': fingerprint(data)}


def current():
    launch = os.environ.get('WORKBENCH_LAUNCH_ID', '')
    if len(launch) != 32 or any(c not in '0123456789abcdef' for c in launch): launch = None
    return {**identity(), 'instance_id': INSTANCE_ID, 'launch_id': launch, 'pid': os.getpid(), 'started_at': STARTED_AT}


@contextmanager
def data_lock():
    store.DATA.mkdir(parents=True, exist_ok=True)
    path = store.DATA / '.instance.lock'
    if path.is_symlink(): raise ValueError('数据目录锁文件不能是符号链接，请核对原目录')
    with path.open('a+b') as handle:
        handle.seek(0, 2)
        if not handle.tell(): handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError: raise ValueError('数据目录已被其他实例使用，或无法取得目录锁；请先退出原服务，或另选数据目录') from None
        try: yield
        finally:
            handle.seek(0)
            if os.name == 'nt': msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--identity', action='store_true', required=True)
    parser.add_argument('--data-directory')
    args = parser.parse_args()
    data = Path(args.data_directory).expanduser().resolve() if args.data_directory else store.DATA
    print(json.dumps({**identity(data), 'workspace_directory': str(store.ROOT), 'data_directory': str(data)}, ensure_ascii=False))


if __name__ == '__main__': main()
