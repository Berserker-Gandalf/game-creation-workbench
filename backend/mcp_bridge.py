"""Small stdio MCP adapter exposing only scoped workbench tools to Codex."""
import json
import os
import sys
from pathlib import Path
import urllib.request
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import __version__

PROTOCOLS = ('2024-11-05', '2025-03-26', '2025-06-18')


def request(method, params):
    payload = json.dumps({'method': method, 'params': params}).encode()
    req = urllib.request.Request(os.environ['WORKBENCH_AGENT_URL'], data=payload,
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + os.environ['WORKBENCH_AGENT_TOKEN']})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=40) as response:
        return json.load(response)


def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    initialized = False
    for line in sys.stdin:
        request_id = None
        try:
            try:
                message = json.loads(line)
            except ValueError:
                response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': '无效 JSON'}}
                print(json.dumps(response, ensure_ascii=False), flush=True)
                continue
            if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
                raise ValueError('无效 JSON-RPC 请求')
            request_id = message.get('id')
            if 'id' not in message:
                continue
            method, params = message['method'], message.get('params', {})
            if not isinstance(params, dict):
                response = {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32602, 'message': '参数必须为对象'}}
                print(json.dumps(response, ensure_ascii=False), flush=True)
                continue
            if method == 'initialize':
                version = params.get('protocolVersion')
                result = {'protocolVersion': version if version in PROTOCOLS else PROTOCOLS[-1],
                          'capabilities': {'tools': {}}, 'serverInfo': {'name': 'game-workbench', 'version': __version__}}
                initialized = True
            elif method == 'ping':
                result = {}
            elif initialized and method in ('tools/list', 'tools/call'):
                result = request(method, params)
            else:
                response = {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32601, 'message': '方法未开放或尚未初始化'}}
                print(json.dumps(response, ensure_ascii=False), flush=True)
                continue
            response = {'jsonrpc': '2.0', 'id': request_id, 'result': result}
        except ValueError:
            response = {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32600, 'message': '无效 JSON-RPC 请求'}}
        except Exception:
            response = {'jsonrpc': '2.0', 'id': request_id,
                        'error': {'code': -32603, 'message': '工作台工具调用失败，请检查连接或执行权限'}}
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
