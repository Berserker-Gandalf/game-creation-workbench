import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from . import __version__, store


def executable():
    override = os.environ.get('CODEX_EXECUTABLE')
    if override and Path(override).is_file():
        return [override]
    shim = shutil.which('codex.cmd') or shutil.which('codex')
    if not shim:
        managed = store.DATA / ('tools/npm/codex.cmd' if os.name == 'nt' else 'tools/npm/bin/codex')
        if managed.is_file(): shim = str(managed)
    if not shim:
        return None
    if os.name != 'nt':
        return [shim]
    if Path(shim).suffix.lower() == '.exe':
        return [shim]
    base = Path(shim).parent / 'node_modules' / '@openai' / 'codex'
    matches = list(base.glob('node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe'))
    if matches:
        return [str(matches[0])]
    node = shutil.which('node')
    script = base / 'bin' / 'codex.js'
    return [node, str(script)] if node and script.exists() else None


class CodexClient:
    def __init__(self):
        self.process = None
        self.pending = {}
        self.subscribers = {}
        self.sequence = 0
        self.start_lock = asyncio.Lock()
        self.reader_task = None
        self.last_tools = []
        self.last_policy = None

    async def start(self):
        async with self.start_lock:
            if self.process and self.process.returncode is None:
                return
            cmd = executable()
            if not cmd:
                raise ValueError('未找到官方 Codex CLI，请安装后重新检测')
            self.process = await asyncio.create_subprocess_exec(
                *cmd, 'app-server', '--listen', 'stdio://',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=16 * 1024 * 1024)
            self.reader_task = asyncio.create_task(self.read_loop())
            await self.rpc('initialize', {'clientInfo': {'name': 'game_creation_workbench', 'title': '游戏创作工作台', 'version': __version__}}, timeout=30)
            await self.send({'method': 'initialized'})

    async def send(self, payload):
        if not self.process or self.process.returncode is not None:
            raise ValueError('Codex 进程未运行')
        self.process.stdin.write((json.dumps(payload, ensure_ascii=False) + '\n').encode())
        await self.process.stdin.drain()

    async def rpc(self, method, params, timeout=60):
        self.sequence += 1
        rid = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        try:
            await self.send({'id': rid, 'method': method, 'params': params})
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(rid, None)

    async def read_loop(self):
        try:
            while raw := await self.process.stdout.readline():
                try:
                    event = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    continue
                if 'id' in event and 'method' not in event:
                    future = self.pending.get(event['id'])
                    if future and not future.done():
                        if 'error' in event:
                            future.set_exception(ValueError(event['error'].get('message', 'Codex 请求失败')))
                        else:
                            future.set_result(event.get('result', {}))
                elif 'method' in event:
                    # This version only runs tasks inside the selected sandbox and
                    # declines unexpected approval requests instead of granting them.
                    if 'id' in event:
                        self.last_tools.append({'request': event['method'], 'keys': list(event.get('params', {}))})
                        method = event['method']
                        if method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
                            answer = {'result': {'decision': 'decline'}}
                        elif method == 'item/permissions/requestApproval':
                            answer = {'result': {'permissions': {}, 'scope': 'turn'}}
                        elif method == 'mcpServer/elicitation/request':
                            answer = {'result': {'action': 'decline', 'content': None}}
                        else:
                            answer = {'error': {'code': -32601, 'message': '此工作台未开放该交互'}}
                        await self.send({'id': event['id'], **answer})
                    params = event.get('params', {})
                    if event['method'] == 'item/completed' and params.get('item', {}).get('type') == 'mcpToolCall':
                        item = params['item']
                        self.last_tools.append({k: item.get(k) for k in ('server', 'tool', 'status', 'error')})
                        self.last_tools = self.last_tools[-8:]
                    for tid, queue in list(self.subscribers.items()):
                        if tid == '*' or params.get('threadId') == tid:
                            await queue.put(event)
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(ValueError('Codex 连接中断'))
            for queue in list(self.subscribers.values()):
                await queue.put({'method': 'workbench/disconnected', 'params': {}})

    async def status(self):
        await self.start()
        account = await self.rpc('account/read', {'refreshToken': False})
        models = await self.rpc('model/list', {})
        return {'available': True, 'account': account.get('account'), 'requires_auth': account.get('requiresOpenaiAuth'),
                'models': models.get('data', []), 'diagnostics': self.last_tools, 'isolation': self.last_policy}

    async def resolve_model(self, model=None):
        await self.start()
        if model:
            return model
        catalog = (await self.rpc('model/list', {})).get('data', [])
        default = next((m for m in catalog if m.get('isDefault')), catalog[0] if catalog else None)
        if not default:
            raise ValueError('Codex 未返回可选择的模型，请检查账号连接')
        return default['model']

    async def server_catalog(self, thread_id=None):
        records, cursor = [], None
        while True:
            params = {'limit': 100}
            if thread_id:
                params['threadId'] = thread_id
            if cursor:
                params['cursor'] = cursor
            result = await self.rpc('mcpServerStatus/list', params)
            records.extend(result.get('data', []))
            cursor = result.get('nextCursor')
            if not cursor:
                return records

    async def prepare(self, root, model, allow_write, bridge, allowed_tools, instructions, full_access=False):
        if full_access and not allow_write: raise ValueError('Codex 整机访问需要明确的执行授权')
        self.last_policy = {'verified': False}
        await self.start()
        model = await self.resolve_model(model)
        config = (await self.rpc('config/read', {'includeLayers': False})).get('config', {})
        inherited = await self.server_catalog()
        names = set(config.get('mcp_servers', {})) | {r['name'] for r in inherited}
        policy = {f'mcp_servers.{name}.enabled': False for name in names if name != 'workbench'}
        # Runtime-injected servers have no user config transport to merge with.
        for name in names - set(config.get('mcp_servers', {})) - {'workbench'}:
            policy[f'mcp_servers.{name}'] = {'enabled': False, 'command': sys.executable, 'args': ['-c', 'pass']}
        for category in ('apps', 'plugins'):
            for name in (config.get(category) or {}):
                policy[f'{category}.{json.dumps(name)}.enabled'] = False
        policy.update({'apps._default.enabled': False, 'features.shell_tool': allow_write,
                       'features.js_repl': False, 'agents.enabled': False, 'web_search': 'disabled',
                       'mcp_optional_startup_grace_ms': 0,
                       'mcp_servers.workbench': {**bridge, 'enabled': True, 'required': True, 'enabled_tools': allowed_tools}})
        params = {'cwd': str(root), 'ephemeral': True, 'approvalPolicy': 'never', 'model': model,
                  'modelProvider': 'openai', 'sandbox': 'danger-full-access' if full_access else 'workspace-write' if allow_write else 'read-only',
                  'developerInstructions': instructions, 'config': policy}
        thread = await self.rpc('thread/start', params, timeout=90)
        tid = thread['thread']['id']
        try:
            catalog = await self.server_catalog(tid)
            own = next((r for r in catalog if r['name'] == 'workbench'), None)
            unexpected = [r['name'] for r in catalog if r['name'] != 'workbench' and r.get('tools')]
            if unexpected or not own or set(own.get('tools', {})) != set(allowed_tools):
                raise ValueError('运行时工具隔离核验失败，已停止本轮执行；请检查 Codex 版本或管理策略')
            runtime = {'verified': True, 'model': model, 'tools': sorted(allowed_tools),
                       'blocked_servers': sorted(names - {'workbench'}), 'project_commands': allow_write, 'computer_access': full_access,
                       'sandbox': params['sandbox']}
            self.last_policy = runtime
            return tid, runtime
        except BaseException:
            self.last_policy = {'verified': False}
            try:
                await self.rpc('thread/archive', {'threadId': tid}, timeout=10)
            except Exception:
                pass
            raise

    async def login(self):
        await self.start()
        return await self.rpc('account/login/start', {'type': 'chatgpt'})

    async def stream(self, root, prompt, model=None, allow_write=False, bridge_config=None, image=None, handle=None, allowed_tools=None, instructions=None, full_access=False, reasoning_effort=''):
        await self.start()
        if not bridge_config or allowed_tools is None:
            raise ValueError('缺少工作台作用域工具配置，拒绝启动未隔离会话')
        if reasoning_effort:
            catalog = (await self.rpc('model/list', {})).get('data', [])
            selected = next((m for m in catalog if m.get('model') == model), None)
            if not selected or reasoning_effort not in [v.get('reasoningEffort') for v in selected.get('supportedReasoningEfforts', [])]:
                raise ValueError('当前 Codex 模型未声明支持此推理强度，请刷新模型或使用默认值')
        tid, runtime = await self.prepare(root, model, allow_write, bridge_config, allowed_tools, instructions or '仅使用已授权的项目工具，不读取凭据。', **({'full_access': True} if full_access else {}))
        queue = asyncio.Queue()
        self.subscribers[tid] = queue
        turn_id = None
        finished = False
        try:
            yield {'event': 'runtime', 'runtime': {**runtime, 'reasoning_effort': reasoning_effort}}
            inputs = [{'type': 'text', 'text': prompt}]
            if image:
                inputs.append({'type': 'localImage', 'path': str(image)})
            turn = await self.rpc('turn/start', {'threadId': tid, 'input': inputs, **({'effort': reasoning_effort} if reasoning_effort else {})}, timeout=90)
            turn_id = turn['turn']['id']
            if handle is not None:
                handle.update(thread_id=tid, turn_id=turn_id)
            while True:
                event = await asyncio.wait_for(queue.get(), 240)
                method, p = event['method'], event.get('params', {})
                if method == 'item/agentMessage/delta':
                    yield {'event': 'delta', 'text': p.get('delta', '')}
                elif method == 'item/started':
                    item_type = p.get('item', {}).get('type', '')
                    if item_type in ('commandExecution', 'mcpToolCall', 'fileChange'):
                        yield {'event': 'activity', 'text': {'commandExecution': '正在运行项目工具', 'mcpToolCall': '正在读取或更新项目', 'fileChange': '正在修改项目文件'}[item_type]}
                elif method == 'item/completed' and p.get('item', {}).get('type') in ('commandExecution', 'fileChange'):
                    item = p['item']
                    yield {'event': 'runtime_action', 'tool': item['type'], 'status': item.get('status', 'unknown'),
                           'summary': str(item.get('command', item.get('changes', '')))[:2000]}
                elif method == 'turn/completed':
                    completed = p.get('turn', {})
                    if completed.get('status') != 'completed':
                        raise ValueError((completed.get('error') or {}).get('message') or 'Codex 任务未完成或已停止')
                    finished = True
                    yield {'event': 'usage', 'usage': {'billing': 'ChatGPT/Codex 账号额度，具体以官方账号为准'}}
                    break
                elif method == 'workbench/disconnected':
                    raise ValueError('Codex 连接中断，请核对任务结果后再重试')
        finally:
            self.subscribers.pop(tid, None)
            if not finished and turn_id:
                try:
                    await self.rpc('turn/interrupt', {'threadId': tid, 'turnId': turn_id}, timeout=10)
                except Exception:
                    pass
            try:
                await self.rpc('thread/archive', {'threadId': tid}, timeout=10)
            except Exception:
                pass

    async def stop(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 10)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()


client = CodexClient()
