"""Read-only account balances. Missing or failed readings are never zero."""
import asyncio
import math
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

import httpx
from . import codex, music, secrets, store, tripo

PROVIDERS = ('codex', 'suno', 'tripo', 'deepseek', 'openai')
LOCKS = {}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def quota(data):
    buckets = data.get('rateLimitsByLimitId') or {'codex': data.get('rateLimits')}
    windows, credits, monthly = [], [], []
    if not isinstance(buckets, dict):
        raise ValueError('额度格式不可识别')
    for name, item in buckets.items():
        if not isinstance(item, dict):
            continue
        for key in ('primary', 'secondary'):
            window = item.get(key)
            if not isinstance(window, dict) or not number(window.get('usedPercent')):
                continue
            used = max(0, min(100, window['usedPercent']))
            windows.append({'bucket': str(name)[:100], 'window': key, 'remaining_percent': 100 - used,
                            'window_minutes': window.get('windowDurationMins') if number(window.get('windowDurationMins')) else None,
                            'resets_at': window.get('resetsAt') if number(window.get('resetsAt')) else None})
        c = item.get('credits')
        if isinstance(c, dict):
            credits.append({'bucket': str(name)[:100], **{k: c[k] for k in ('hasCredits', 'unlimited', 'balance') if k in c}})
        individual = item.get('individualLimit')
        if isinstance(individual, dict):
            monthly.append({'bucket': str(name)[:100], **{k: individual[k] for k in ('limit', 'used', 'remainingPercent', 'resetsAt') if k in individual}})
    if not windows and not credits and not monthly:
        raise ValueError('服务未返回可显示的额度')
    return {'windows': windows, 'credits': credits, 'monthly': monthly, 'note': '账户共享额度；比例与点数按服务原义显示，不换算成剩余 token 或现金'}


async def read(provider):
    if provider == 'codex':
        await codex.client.start()
        return quota(await codex.client.rpc('account/rateLimits/read', {}, timeout=20))
    if provider == 'suno':
        state = await music.helper('auth', 'status')
        if state.get('status') != 'authorized':
            raise ValueError('请在音乐页完成授权')
        account = await music.helper('account')
        points = account.get('points')
        try:
            valid = not isinstance(points, bool) and Decimal(str(points)).is_finite()
        except InvalidOperation:
            valid = False
        if not valid:
            raise ValueError('服务未返回积分')
        return {'points': points, 'vip_status': account.get('vip_status')}
    if provider == 'tripo':
        return {**await tripo.balance(), 'region': store.setting('tripo_region', 'cn')}
    if provider == 'deepseek':
        key = secrets.get_key('deepseek')
        if not key:
            raise ValueError('尚未配置 DeepSeek')
        async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as client:
            response = await client.get('https://api.deepseek.com/user/balance', headers={'Authorization': 'Bearer ' + key})
        if response.status_code != 200:
            raise ValueError('余额查询未成功')
        data = response.json()
        values = []
        for item in data.get('balance_infos', []):
            if item.get('currency') in ('CNY', 'USD'):
                row = {'currency': item['currency']}
                for key in ('total_balance', 'granted_balance', 'topped_up_balance'):
                    value = item.get(key)
                    try:
                        if isinstance(value, str) and len(value) <= 50 and Decimal(value).is_finite():
                            row[key] = value
                    except InvalidOperation:
                        pass
                if 'total_balance' in row:
                    values.append(row)
        if not values:
            raise ValueError('服务未返回余额')
        return {'balances': values, 'is_available': data.get('is_available') if isinstance(data.get('is_available'), bool) else None}
    raise ValueError('此服务没有接入余额接口')


def cached():
    result = store.setting('account_balances', {})
    values = {p: result.get(p, {'status': 'unsupported' if p == 'openai' else 'not_checked', 'data': None, 'checked_at': None, 'attempted_at': None,
                             'stale': False, 'message': '本版不提供 OpenAI API 现金余额查询，可到官方账单台查看' if p == 'openai' else '尚未查询'}) for p in PROVIDERS}
    for p, item in values.items():
        if item.get('data') is None: continue
        try: expired = (datetime.now(timezone.utc) - datetime.fromisoformat(item['checked_at'])).total_seconds() > 300
        except (KeyError, TypeError, ValueError): expired = True
        changed_region = p == 'tripo' and item['data'].get('region') != store.setting('tripo_region', 'cn')
        if expired or changed_region:
            item['stale'] = True
            if item['status'] == 'ok': item['status'] = 'stale'
    return values


async def refresh(providers):
    if not isinstance(providers, list) or not providers or any(p not in PROVIDERS or not isinstance(p, str) for p in providers):
        raise ValueError('请选择有效的额度服务')
    async def one(p):
        if p == 'openai':
            return p, cached()[p]
        lock = LOCKS.setdefault(p, asyncio.Lock())
        async with lock:
            old = cached()[p]
            try:
                data = await asyncio.wait_for(read(p), 35)
                return p, {'status': 'ok', 'data': data, 'checked_at': store.now(), 'attempted_at': store.now(), 'stale': False, 'message': '服务账户只读查询；不创建任务、不消耗重置次数'}
            except Exception:
                return p, {**old, 'status': 'error', 'attempted_at': store.now(), 'stale': old.get('data') is not None,
                           'message': '查询未成功，请检查连接、授权或服务可用性；上次数据仅供参考，未将未知余额记为零'}
    values = await asyncio.gather(*(one(p) for p in dict.fromkeys(providers)))
    result = cached()
    for p, item in values:
        if (item.get('attempted_at') or '') >= (result[p].get('attempted_at') or ''): result[p] = item
    store.set_setting('account_balances', result)
    return result
