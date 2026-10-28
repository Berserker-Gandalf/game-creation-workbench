import json
import httpx
from . import secrets, store

BASES = {'openai': 'https://api.openai.com/v1', 'deepseek': 'https://api.deepseek.com'}


def accumulate_usage(total, usage, request=None):
    def add(a, b):
        if isinstance(b, dict):
            return {**(a if isinstance(a, dict) else {}), **{k: add(a.get(k, 0) if isinstance(a, dict) else 0, v) for k, v in b.items()}}
        return (a if isinstance(a, (int, float)) else 0) + b if isinstance(b, (int, float)) and not isinstance(b, bool) else b
    previous = total.get('requests', [])
    result = add({k: v for k, v in total.items() if k != 'requests'}, usage)
    result['requests'] = previous + [{**(request or {}), 'usage': usage}]
    return result


def config(provider):
    if provider not in BASES:
        raise ValueError('不支持的模型服务')
    key = secrets.get_key(provider)
    if not key:
        raise ValueError('请先在连接设置中配置此服务的 API Key')
    return BASES[provider], key


async def models(provider):
    base, key = config(provider)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(base + '/models', headers={'Authorization': 'Bearer ' + key})
        check(r)
        return r.json().get('data', [])


def check(response):
    if response.is_error:
        # Never return raw request headers or echoed credentials from upstream.
        raise ValueError(f'供应商请求失败（HTTP {response.status_code}）。请检查权限、额度或稍后重试。')


def reasoning(provider, effort):
    allowed = ('none', 'low', 'high', 'max') if provider == 'deepseek' else ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
    if not isinstance(effort, str) or (effort and effort not in allowed):
        raise ValueError('此服务不支持所选推理强度')
    return {'reasoning': {'effort': effort}} if effort else {}


async def stream(provider, model, messages, instructions, tools, execute_tool, max_requests=5, reasoning_effort=''):
    if not model:
        raise ValueError('请先选择或填写经过验证的模型 ID')
    options = reasoning(provider, reasoning_effort)
    base, key = config(provider)
    inputs = messages[:]
    async with httpx.AsyncClient(timeout=httpx.Timeout(240, connect=20)) as client:
        for _ in range(max_requests):
            output = []
            payload = {'model': model, 'instructions': instructions, 'input': inputs,
                       'stream': True, 'store': False, 'tools': tools, **options}
            async with client.stream('POST', base + '/responses', json=payload,
                                     headers={'Authorization': 'Bearer ' + key}) as response:
                check(response)
                completed = False
                async for line in response.aiter_lines():
                    if not line.startswith('data: '):
                        continue
                    raw = line[6:]
                    if raw == '[DONE]':
                        continue
                    event = json.loads(raw)
                    kind = event.get('type')
                    if kind == 'response.output_text.delta':
                        yield {'event': 'delta', 'text': event.get('delta', '')}
                    elif kind == 'response.completed':
                        result = event['response']
                        output = result.get('output', [])
                        completed = True
                        yield {'event': 'usage', 'usage': result.get('usage', {}), 'request': {'response_id': result.get('id'), 'model': model}}
                    elif kind in ('error', 'response.failed', 'response.incomplete'):
                        raise ValueError('模型响应未完成，请检查额度或缩短输入后再试')
                if not completed:
                    raise ValueError('模型流式连接提前结束，未收到完成确认')
            calls = [item for item in output if item.get('type') == 'function_call']
            if not calls:
                return
            inputs.extend(output)
            for call in calls:
                yield {'event': 'activity', 'text': '正在处理项目：' + call['name']}
                try:
                    result = await execute_tool(call['name'], json.loads(call['arguments']))
                except (ValueError, TypeError, KeyError) as e:
                    result = {'error': str(e)}
                image = result.pop('_image', None) if isinstance(result, dict) else None
                content = json.dumps(result, ensure_ascii=False)
                inputs.append({'type': 'function_call_output', 'call_id': call['call_id'],
                               'output': [{'type': 'input_text', 'text': content}, {'type': 'input_image', 'image_url': 'data:image/png;base64,' + image}] if image else content})
        raise ValueError('已达到单次任务的工具循环上限，请缩小任务范围')
