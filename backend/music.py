"""Suno.cn integration through the unmodified, user-installed Skill helper."""
import asyncio
import json
import os
import shutil
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import assets, audio_import, generation_models, skill_setup, store

IMPORTING = set()


class UserActionRequired(ValueError):
    pass

MODELS = [{'id': 'chirp-hawk', 'label': 'V6 · chirp-hawk'},
          {'id': 'chirp-hawk-wild', 'label': 'V6 Wild · chirp-hawk-wild'},
          {'id': 'chirp-goose', 'label': 'V6 Mini · chirp-goose'}]


def installation():
    root = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'skills/suno-cn-music'
    if skill_setup.valid(skill_setup.root()): root = skill_setup.root()
    node = shutil.which('node')
    return root, node


async def helper(*arguments):
    root, node = installation()
    script = root / 'scripts/suno-client.mjs'
    if not node or not script.is_file():
        raise ValueError('请先安装 Node.js 和 suno-cn-music Skill；工作台不会代读或复制其凭据')
    process = await asyncio.create_subprocess_exec(node, str(script), *arguments, cwd=root,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 150)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise ValueError('音乐请求中断，结果尚未确认；未自动重试') from None
    try:
        result = json.loads(output)
    except (ValueError, UnicodeDecodeError):
        raise ValueError('音乐 Skill 未返回有效结果；请检查安装和网络，未自动重试') from None
    if not isinstance(result, dict):
        raise ValueError('音乐 Skill 返回格式不受支持')
    return result


def action(result):
    candidate = result.get('action') or {}
    url = candidate.get('url', '')
    parsed = urlsplit(url)
    if candidate.get('type') == 'open_url' and parsed.scheme == 'https' and parsed.hostname in ('www.suno.cn', 'mcp.suno.cn') and not parsed.username and not parsed.password and parsed.port in (None, 443):
        return {'type': 'open_url', 'url': url}
    return None


async def connection(verify=False):
    root, node = installation()
    installed = bool(node and (root / 'scripts/suno-client.mjs').is_file())
    if not installed:
        return {'installed': False, 'status': 'not_installed'}
    result = await helper('auth', 'verify' if verify else 'status')
    public = {k: result[k] for k in ('status', 'error', 'message', 'expires_at', 'permanent', 'renewal_recommended') if k in result}
    public['installed'] = True
    if action(result):
        public['action'] = action(result)
    if verify and result.get('status') == 'authorized':
        account = await helper('account')
        public['account'] = {k: account[k] for k in ('nickname', 'points', 'vip_status') if k in account}
        if account.get('status') == 'error':
            public.update(status='error', message=account.get('message', '账号查询失败'))
    return public


def jobs(pid):
    values = store.rows('SELECT * FROM music_jobs WHERE project_id=? ORDER BY created DESC', (pid,))
    mapped = {}
    for item in store.rows('SELECT m.* FROM music_assets m JOIN music_jobs j ON j.id=m.job_id WHERE j.project_id=?', (pid,)): mapped.setdefault(item['job_id'], []).append(item)
    return [{**j, 'outputs': mapped.get(j['id'], [])} for j in values]


def outputs(jid):
    job(jid)
    return store.rows('SELECT * FROM music_assets WHERE job_id=? ORDER BY created', (jid,))


def job(jid):
    result = store.one('SELECT * FROM music_jobs WHERE id=?', (jid,))
    if not result:
        raise ValueError('音乐方案不存在')
    return result


def draft(pid, data):
    store.project(pid)
    fields = {k: str(data.get(k, '')).strip() for k in ('title', 'prompt', 'tags')}
    if not fields['title'] or not fields['prompt'] or len(fields['title']) > 120 or len(fields['prompt']) > 8000 or len(fields['tags']) > 1000 or not isinstance(data.get('instrumental', True), bool):
        raise ValueError('请填写有效的音乐名称、创作描述和纯音乐选项')
    fields['instrumental'] = data.get('instrumental', True)
    fields['mv'] = data.get('mv', generation_models.selected(pid)['suno'])
    if fields['mv'] not in [m['id'] for m in MODELS]: raise ValueError('请选择已接入的 SUNO 模型')
    jid = store.uid()
    store.execute('INSERT INTO music_jobs VALUES (?,?,?,?,?,?,?,?)',
                  (jid, pid, json.dumps(fields, ensure_ascii=False), 'draft', '[]', '{}', store.now(), store.now()))
    return job(jid)


async def submit(jid, confirmed):
    if confirmed is not True:
        raise ValueError('请先核对音乐方案，并明确确认本次积分消耗')
    current = job(jid)
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        changed = c.execute("UPDATE music_jobs SET status='submitting',updated=? WHERE id=? AND status='draft'", (store.now(), jid)).rowcount
        if not changed:
            raise ValueError('此方案已提交或结果待确认，不能重复提交')
    spec = json.loads(current['spec'])
    spec.setdefault('mv', MODELS[0]['id'])
    rid = store.run_start(current['project_id'], 'music:suno-cn', '提交已确认的音乐方案', provider='suno-cn', model=spec['mv'], agent='music')
    store.execute('UPDATE runs SET runtime=? WHERE id=?', (json.dumps({'source_kind': 'music', 'source_id': jid}), rid))
    status, detail, serials = 'unknown', {}, []
    try:
        verified = await helper('auth', 'verify')
        if verified.get('status') != 'authorized':
            status, detail = 'draft', {'message': '请先完成 Suno.cn 网页授权，再重新确认提交'}
            return {'job': current, 'connection': {k: verified[k] for k in ('status', 'message') if k in verified}, 'action': action(verified)}
        result = await helper('request', 'POST', '/mcp/api/generate', json.dumps(spec, ensure_ascii=False))
        serials = result.get('serial_nos', [])
        if not isinstance(serials, list) or not all(isinstance(s, str) and 0 < len(s) <= 160 for s in serials):
            serials = []
        if serials:
            status, detail = 'submitted', {'message': '已提交，尚未确认生成完成'}
        else:
            error = result.get('error', 'result_unknown')
            status = 'needs_credits' if error == 'insufficient_credits' else 'unknown'
            detail = {'error': error, 'message': result.get('message', '提交结果不确定，请在作品列表核对，禁止直接重试')}
        return {'job_id': jid, 'status': status, 'action': action(result)}
    finally:
        store.execute('UPDATE music_jobs SET status=?,serials=?,result=?,updated=? WHERE id=?',
                      (status, json.dumps(serials), json.dumps(detail, ensure_ascii=False), store.now(), jid))
        store.run_end(rid, 'completed' if status == 'submitted' else 'interrupted' if status == 'unknown' else 'failed',
                      detail.get('message', '音乐请求结果尚未确认；请核对外部作品，不自动重试'))


async def poll(jid):
    current = job(jid)
    serials = json.loads(current['serials'])
    if not serials:
        raise ValueError('尚无任务编号，请先确认提交结果；不能自动重新生成')
    result = await helper('request', 'GET', '/mcp/api/task/' + quote(','.join(serials), safe=',') + '?wait=0')
    if result.get('status') == 'error':
        return {'status': 'error', 'message': result.get('message', '音乐任务查询失败'), 'action': action(result)}
    items = result.get('tasks', [])
    if not isinstance(items, list) or not items or any(not isinstance(t, dict) for t in items):
        raise ValueError('尚未取得可确认的音乐任务状态')
    public = []
    for t in items:
        if t.get('serial_no') not in serials:
            raise ValueError('服务端返回的任务编号与本项目记录不匹配')
        item = {k: t[k] for k in ('serial_no', 'status', 'title', 'duration', 'fail_msg_show') if k in t}
        url = t.get('play_url', '')
        parsed = urlsplit(url)
        if parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password:
            item['play_url'] = url
        public.append(item)
    states = [str(t.get('status', '')) for t in public]
    complete_set = {t['serial_no'] for t in public} == set(serials)
    status = 'completed' if complete_set and all(s in ('success', '2') for s in states) else 'failed' if complete_set and all(s in ('success', '2', 'failed', '3') for s in states) else 'processing'
    store.execute('UPDATE music_jobs SET status=?,result=?,updated=? WHERE id=?',
                  (status, json.dumps({'tasks': public}, ensure_ascii=False), store.now(), jid))
    return job(jid)


async def import_audio(jid, serial_no, confirmed, check=None):
    j = job(jid)
    serials = json.loads(j['serials'])
    if confirmed is not True or not isinstance(serial_no, str) or serial_no not in serials: raise ValueError('请选择本项目已记录的音乐结果，并确认下载纳入资产')
    previous = store.one('SELECT * FROM music_assets WHERE job_id=? AND serial_no=?', (jid, serial_no))
    if previous:
        original = json.loads(assets.asset(previous['asset_id'])['versions'])[0]['path']
        try:
            path = assets.authorized_path(j['project_id'], original)
            if await asyncio.to_thread(assets.digest, path) != previous['sha256']: raise ValueError('已登记的原始音轨内容变化，请从备份恢复或人工导入新版本')
        except OSError: raise ValueError('已登记的原始音轨缺失，请先恢复备份；未覆盖其他编辑版本') from None
        return previous
    key = (jid, serial_no)
    if key in IMPORTING: raise ValueError('此音轨正在下载，请查询当前操作，不要重复提交')
    IMPORTING.add(key)
    part = target = None; saved = False
    rid = store.run_start(j['project_id'], 'music_import', '查询并下载已完成音乐，不提交生成', provider='suno-cn', agent='music')
    try:
        verified = await helper('auth', 'verify')
        if verified.get('status') != 'authorized': raise UserActionRequired('请在音乐工作区完成授权后再接入音频')
        fresh = await helper('request', 'GET', '/mcp/api/task/' + quote(serial_no, safe='') + '?wait=0')
        values = fresh.get('tasks')
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict) or values[0].get('serial_no') != serial_no or str(values[0].get('status')) not in ('success', '2'): raise ValueError('服务尚未确认该音轨成功，请先查询或完成账户处理')
        if check: check()
        folder = store.project_dir(j['project_id']) / 'music' / jid
        folder.mkdir(parents=True, exist_ok=True)
        part = folder / (store.uid() + '.part')
        await audio_import.download(values[0].get('play_url'), part)
        info = await asyncio.to_thread(audio_import.verify, part)
        sha = await asyncio.to_thread(assets.digest, part)
        if check: check()
        target = part.with_suffix(info['suffix']); part.replace(target)
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if check: check()
            previous = c.execute('SELECT * FROM music_assets WHERE job_id=? AND serial_no=?', (jid, serial_no)).fetchone()
            if previous: return dict(previous)
            aid = store.uid(); spec = json.loads(j['spec'])
            versions = json.dumps([{'path': str(target), 'label': 'SUNO已完成音轨 · 原始下载', 'created': store.now()}])
            c.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)', (aid, j['project_id'], spec['title'] + ' · ' + serial_no[:24] + info['suffix'], str(target), str(target), 'audio', versions, store.now()))
            c.execute('INSERT INTO music_assets VALUES (?,?,?,?,?,?,?,?)', (jid, serial_no, aid, sha, target.stat().st_size, info['mime'], info['duration'], store.now()))
        saved = True
        store.execute('UPDATE runs SET runtime=? WHERE id=?', (json.dumps({'source_kind': 'music', 'source_id': jid, 'asset_id': aid, 'sha256': sha}), rid))
        return store.one('SELECT * FROM music_assets WHERE job_id=? AND serial_no=?', (jid, serial_no))
    finally:
        IMPORTING.discard(key)
        if part: part.unlink(missing_ok=True)
        if target and not saved: target.unlink(missing_ok=True)
        store.run_end(rid, 'completed' if saved else 'interrupted', '音频已纳入项目资产，等待试听与验收' if saved else '下载未确认；没有提交生成或收费转换，未登记部分文件')
