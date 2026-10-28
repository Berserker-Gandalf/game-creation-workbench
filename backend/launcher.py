"""Instance-aware local launcher shared by source scripts and future desktop hosts."""
import argparse
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib import error, request
from uuid import uuid4
import webbrowser

from . import instance, store


class UnconfirmedConnection(ValueError):
    pass


def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if os.name == 'nt': probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try: probe.bind(('127.0.0.1', port))
        except OSError: return False
        return True


def read(port, path, data=None, token=''):
    headers = {'Content-Type': 'application/json'}
    if token: headers['X-Workbench-Token'] = token
    payload = json.dumps(data).encode() if data is not None else None
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        with opener.open(request.Request(f'http://127.0.0.1:{port}' + path, data=payload, headers=headers), timeout=2) as response:
            raw = response.read(10 * 1024 * 1024 + 1)
            if len(raw) > 10 * 1024 * 1024: raise ValueError('本机响应过大，未继续操作')
            value = json.loads(raw)
            if not isinstance(value, dict): raise ValueError('端口响应不是可识别的工作台记录')
            return value
    except error.HTTPError as exc: raise ValueError(f'本机接口返回{exc.code}，不能据此确认实例状态') from None
    except error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError) or getattr(exc.reason, 'errno', None) in (errno.ECONNREFUSED, 10061) or getattr(exc.reason, 'winerror', None) == 10061: return None
        if data is None and path == '/api/health' and port_free(port): return None
        raise UnconfirmedConnection('本机连接未确认，请核对端口和实例；不会自动终止进程') from None
    except (TimeoutError, ConnectionError):
        if data is None and path == '/api/health' and port_free(port): return None
        raise UnconfirmedConnection('本机连接暂未确认，请核对实例') from None
    except (json.JSONDecodeError, UnicodeDecodeError): raise ValueError('本机响应格式异常，未继续操作') from None


def owner(health, expected, check_version=False):
    if not health or health.get('product') != 'game-workbench' or health.get('ok') is not True: raise ValueError('此端口不是可识别的工作台，不会复用或停止它')
    iid = health.get('instance_id', '')
    if health.get('protocol') != 1 or not isinstance(iid, str) or len(iid) != 32 or any(c not in '0123456789abcdef' for c in iid): raise ValueError('实例没有受支持的归属标识；旧版请核对原窗口，再按升级说明手动停止')
    if any(health.get(key) != expected[key] for key in ('workspace_id', 'data_id')): raise ValueError('端口属于另一份源码或数据目录，不会复用或停止；请使用原目录或另选端口')
    if check_version and health.get('version') != expected['version']: raise ValueError('运行版本与源码不同，请先正常停止对应实例再重新启动')


def start(port, data_directory=None, no_browser=False):
    data = Path(data_directory).expanduser().resolve() if data_directory else store.DATA
    expected, url = instance.identity(data), f'http://127.0.0.1:{port}'
    health = read(port, '/api/health')
    if health is not None:
        owner(health, expected, True)
        if not no_browser: webbrowser.open(url)
        return {'message': '已核对源码与数据目录，复用工作台：' + url, 'service': health, 'reused': True}
    logs = data / 'logs'; logs.mkdir(parents=True, exist_ok=True)
    launch = uuid4().hex
    stdout, stderr = logs / f'server.{launch}.log', logs / f'server.{launch}.error.log'
    args = [sys.executable, '-X', 'utf8', '-m', 'backend.run', '--port', str(port), '--data-directory', str(data), '--launch-id', launch]
    with stdout.open('wb') as out, stderr.open('wb') as err:
        child = subprocess.Popen(args, cwd=store.ROOT, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                 start_new_session=os.name != 'nt')
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try: health = read(port, '/api/health')
        except UnconfirmedConnection:
            time.sleep(.2)
            continue
        if health is not None:
            owner(health, expected, True)
            if health.get('launch_id') != launch: raise ValueError('另一个启动过程占用了端口，请核对实例；未停止其他服务')
            if not no_browser: webbrowser.open(url)
            return {'message': '工作台已就绪：' + url, 'service': health, 'reused': False, 'error_log': str(stderr)}
        if child.poll() is not None: raise ValueError('服务启动失败，请查看错误日志：' + str(stderr))
        time.sleep(.2)
    raise ValueError('尚未确认服务就绪，请核对错误日志：' + str(stderr) + '；不会自动终止其他进程')


def stop(port, data_directory=None, legacy_confirmed=False):
    data = Path(data_directory).expanduser().resolve() if data_directory else store.DATA
    expected = instance.identity(data)
    health = read(port, '/api/health')
    legacy = False
    if legacy_confirmed and health and health.get('product') == 'game-workbench' and health.get('ok') is True and health.get('protocol') is None and health.get('instance_id') is None:
        version = str(health.get('version', '')).split('.')
        legacy = len(version) == 3 and all(v.isdecimal() for v in version) and tuple(map(int, version)) < (0, 14, 0)
        if not legacy: raise ValueError('无法确认这是可手动迁移的旧版实例')
    if not legacy: owner(health, expected)
    session = read(port, '/api/bootstrap' if legacy else '/api/server/session')
    if not session or not isinstance(session.get('token'), str) or not session['token']: raise ValueError('未取得本机会话，未发送停止请求')
    body = {}
    if not legacy:
        owner(session.get('service'), expected)
        if session['service']['instance_id'] != health['instance_id']: raise ValueError('实例已变化，未发送停止请求')
        body['instance_id'] = health['instance_id']
    result = read(port, '/api/server/stop', body, session['token'])
    if not result or result.get('stopping') is not True: raise ValueError('服务没有确认接受停止请求')
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        time.sleep(.2)
        try: current = read(port, '/api/health')
        except UnconfirmedConnection: continue
        if current is None: return {'message': '原服务已退出；项目数据保留', 'stopped': True, 'legacy': legacy}
        if not legacy and current.get('instance_id') != health['instance_id']:
            return {'message': '原实例不再响应，端口已有其他服务；未停止新服务', 'stopped': True, 'legacy': False}
    raise ValueError('已请求停止，但尚未确认退出；请核对原任务和日志，不会强行结束进程')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start', 'stop'))
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-directory')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--legacy-confirmed', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('port must be between 1 and 65535')
    try:
        result = start(args.port, args.data_directory, args.no_browser) if args.action == 'start' else stop(args.port, args.data_directory, args.legacy_confirmed)
        print(result['message'])
        if result.get('error_log'): print('本次错误日志：' + result['error_log'])
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__': main()
