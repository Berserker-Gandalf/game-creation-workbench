import asyncio

import pytest

from backend.codex import CodexClient


def test_runtime_disables_inherited_tools_and_requires_own_bridge():
    async def check(leak=False):
        client, calls = CodexClient(), []
        async def start(): pass
        async def rpc(method, params, **kw):
            calls.append((method, params))
            if method == 'config/read': return {'config': {'mcp_servers': {'outside': {}}, 'apps': {'fixture-app': {}}, 'plugins': {'fixture-plugin': {}}}}
            if method == 'model/list': return {'data': [{'model': 'fixture', 'isDefault': True}]}
            if method == 'thread/start': return {'thread': {'id': 'fixture-thread'}}
            if method == 'mcpServerStatus/list':
                if 'threadId' not in params: return {'data': [{'name': 'outside', 'tools': {'external_tool': {}}}]}
                return {'data': [{'name': 'workbench', 'tools': {'get_project': {}}}] + ([{'name': 'outside', 'tools': {'external_tool': {}}}] if leak else [])}
            return {}
        client.start, client.rpc = start, rpc
        if leak:
            with pytest.raises(ValueError, match='隔离'):
                await client.prepare('.', 'fixture', False, {'command': 'fixture'}, ['get_project'], '仅允许项目工具')
        else:
            tid, runtime = await client.prepare('.', 'fixture', False, {'command': 'fixture'}, ['get_project'], '仅允许项目工具')
            assert tid == 'fixture-thread' and runtime['verified']
            params = next(p for m, p in calls if m == 'thread/start')
            assert params['config']['mcp_servers.outside.enabled'] is False
            assert params['config']['mcp_servers.workbench']['required'] is True
            assert params['config']['features.shell_tool'] is False
            assert params['developerInstructions'] == '仅允许项目工具'
    asyncio.run(check())
    asyncio.run(check(leak=True))
