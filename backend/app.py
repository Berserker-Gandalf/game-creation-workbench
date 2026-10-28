import asyncio
import io
import json
import mimetypes
import re
import secrets as random_secrets
import shutil
import zipfile
import wave
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from PIL import Image

from . import accounts, backup, agent_tools, assets, chat, codex, conversations, deliveries, engines, generation_models, image_jobs, intake, jobs, maintenance, modeling, music, permissions, providers, publishing, secrets, snapshots, store, tasks, tripo, webui, workbench_actions
from . import __version__, catalog, context, diagnostics, hardware, instance, onboarding, path_picker, task_creation, updates

CSRF = random_secrets.token_urlsafe(32)
AGENTS = chat.AGENTS
ACTIVE = chat.ACTIVE


@asynccontextmanager
async def lifespan(app):
    with instance.data_lock():
        store.init()
        onboarding.recover()
        await jobs.start()
        try: yield
        finally:
            await jobs.shutdown()
            await workbench_actions.shutdown()
            await snapshots.shutdown()
            await modeling.shutdown()
            await onboarding.shutdown()
            await codex.client.stop()


app = FastAPI(title='造物间 · 游戏创作工作台', version=__version__, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])


@app.middleware('http')
async def local_access(request, call_next):
    if request.method in ('POST', 'PATCH', 'PUT', 'DELETE') and request.url.path != '/api/internal/mcp':
        origin = request.headers.get('origin')
        if origin and origin not in (str(request.base_url).rstrip('/'), 'http://127.0.0.1:5173', 'http://localhost:5173'):
            return JSONResponse({'detail': '不允许此来源访问本机工作台'}, status_code=403)
        if request.headers.get('x-workbench-token') != CSRF:
            return JSONResponse({'detail': '本地会话已变化，请刷新工作台'}, status_code=403)
    try:
        length = int(request.headers.get('content-length', 0) or 0)
    except ValueError:
        return JSONResponse({'detail': '无效的请求长度'}, status_code=400)
    if length > 60 * 1024 * 1024:
        return JSONResponse({'detail': '上传文件不能超过 60 MB'}, status_code=413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=400)


@app.get('/api/health')
async def health():
    return {'ok': True, **instance.current()}


@app.post('/api/server/stop')
async def stop_server(request: Request):
    raw = await request.body()
    data = json.loads(raw) if raw else {}
    if not isinstance(data, dict) or set(data) - {'instance_id'}: raise ValueError('停止参数无效')
    if 'instance_id' in data and data['instance_id'] != instance.INSTANCE_ID: raise ValueError('工作台实例已变化，请重新核对后停止')
    if onboarding.RUNNING: raise ValueError('工具正在装配，请等待安装器结束后再停止工作台')
    server = getattr(app.state, 'server', None)
    if not server:
        raise ValueError('此服务不是通过标准启动入口运行，请在原控制台停止')
    for rid in list(chat.RUNNING):
        chat.cancel(rid)
    server.should_exit = True
    return {'stopping': True}


@app.get('/api/server/session')
async def server_session():
    return {'token': CSRF, 'service': {'ok': True, **instance.current()}}


@app.get('/api/bootstrap')
async def bootstrap():
    return {'token': CSRF, 'service': instance.current(), 'projects': store.rows('SELECT * FROM projects ORDER BY created DESC'),
            'providers': {p: {'configured': bool(secrets.get_key(p)), 'model': store.setting(p + '_model', ''),
                              'verified': bool(store.one('SELECT * FROM model_checks WHERE provider=? AND model=? AND capability=?', (p, store.setting(p + '_model', ''), 'text'))),
                              'checks': store.rows('SELECT model,capability,verified_at FROM model_checks WHERE provider=? ORDER BY verified_at DESC', (p,))} for p in providers.BASES},
            'image_model': store.setting('image_model', ''), 'codex_installed': bool(codex.executable()),
            'show_onboarding': not store.setting('onboarding_seen', bool(store.one('SELECT id FROM projects LIMIT 1')))}


@app.get('/api/environment')
async def environment():
    return {'engines': engines.discover(), 'codex_installed': bool(codex.executable())}


@app.get('/api/diagnostics')
async def diagnostic_overview():
    return await asyncio.to_thread(diagnostics.inspect)


@app.get('/api/onboarding')
async def onboarding_overview():
    return await asyncio.to_thread(onboarding.overview)


@app.post('/api/system/path-picker')
async def system_path_picker(request: Request):
    return await path_picker.choose(await request.json())


@app.post('/api/webui/preflight')
async def webui_preflight(request: Request):
    return await asyncio.to_thread(hardware.inspect, await request.json())


@app.put('/api/onboarding')
async def onboarding_save(request: Request):
    return onboarding.save(await request.json())


@app.post('/api/onboarding/plan')
async def onboarding_plan(request: Request):
    return await asyncio.to_thread(onboarding.prepare, await request.json())


@app.post('/api/onboarding/install')
async def onboarding_install(request: Request):
    return await onboarding.start(await request.json())


@app.post('/api/onboarding/installations/{jid}/check')
async def onboarding_reconcile(jid: str, request: Request):
    return onboarding.reconcile(jid, await request.json())


@app.post('/api/onboarding/practice')
async def onboarding_practice(request: Request):
    return onboarding.practice(await request.json())


@app.post('/api/diagnostics/check')
async def diagnostic_check(request: Request):
    data = await request.json()
    if not isinstance(data, dict) or set(data) != {'write_probe'} or data['write_probe'] is not True: raise ValueError('请明确运行本机数据写入检测')
    return await asyncio.to_thread(diagnostics.inspect, True)


@app.get('/api/music/connection')
async def music_connection():
    return await music.connection()


@app.post('/api/music/authorize')
async def music_authorize():
    return await music.connection(verify=True)


@app.get('/api/projects/{pid}/music')
async def music_jobs(pid: str):
    store.project(pid)
    return music.jobs(pid)


@app.post('/api/projects/{pid}/music')
async def music_draft(pid: str, request: Request):
    return music.draft(pid, await request.json())


@app.post('/api/music/jobs/{jid}/submit')
async def music_submit(jid: str, request: Request):
    return await music.submit(jid, (await request.json()).get('confirmed'))


@app.post('/api/music/jobs/{jid}/refresh')
async def music_refresh(jid: str):
    return await music.poll(jid)


@app.get('/api/music/jobs/{jid}/outputs')
async def music_outputs(jid: str):
    return music.outputs(jid)


@app.post('/api/music/jobs/{jid}/import')
async def import_music_output(jid: str, request: Request):
    data = await request.json()
    if not isinstance(data, dict) or set(data) - {'serial_no', 'confirmed'}: raise ValueError('音乐接入参数无效')
    return jobs.enqueue(music.job(jid)['project_id'], {'kind': 'music', 'id': jid, 'command': 'import', **data})


@app.get('/api/projects/{pid}/jobs')
async def project_jobs(pid: str, request: Request, kind: str = '', state: str = '', q: str = '', offset: int = 0, limit: int = 30):
    return updates.conditional(await asyncio.to_thread(jobs.list_jobs, pid, kind, state, q, offset, limit), request)


@app.get('/api/projects/{pid}/jobs/inspect')
async def inspect_project_job(pid: str, kind: str, id: str, request: Request):
    return updates.conditional(jobs.inspect(pid, kind, id), request)


@app.post('/api/projects/{pid}/jobs/commands')
async def enqueue_project_job(pid: str, request: Request):
    return jobs.enqueue(pid, await request.json())


@app.post('/api/projects/{pid}/jobs/stop')
async def stop_project_job(pid: str, request: Request):
    data = await request.json()
    if not isinstance(data, dict) or set(data) != {'kind', 'id'}: raise ValueError('请指定要停止的当前项目作业')
    return jobs.stop(pid, data['kind'], data['id'])


@app.post('/api/projects')
async def create_project(request: Request):
    data = await request.json()
    name = str(data.get('name', '')).strip()
    engine = data.get('engine', 'unreal')
    if not name or len(name) > 100 or engine not in ('unreal', 'unity'):
        raise ValueError('请填写有效项目名称并选择引擎')
    pid = store.uid()
    root = Path(data['root']).expanduser().resolve() if data.get('root', '').strip() else store.project_dir(pid)
    if not root.is_dir():
        raise ValueError('工程目录不存在，请先创建或选择已有目录')
    store.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)',
                  (pid, name, engine, str(root), str(data.get('brief', ''))[:30000], store.now()))
    return store.project(pid)


@app.get('/api/projects/{pid}')
async def get_project(pid: str):
    return await asyncio.to_thread(store.snapshot, pid)


@app.get('/api/projects/{pid}/conversations')
async def list_conversations(pid: str, agent: str = 'director', archived: bool = False):
    store.project(pid)
    conversations.migrate_legacy(pid)
    return store.rows('SELECT * FROM conversations WHERE project_id=? AND agent=? AND archived=? ORDER BY updated DESC', (pid, agent, int(archived)))


@app.get('/api/projects/{pid}/workspace')
async def workspace(pid: str):
    return await asyncio.to_thread(catalog.workspace, pid)


@app.get('/api/projects/{pid}/catalog/{section}')
async def project_catalog(pid: str, section: str, q: str = '', kind: str = '', category: str = '', offset: int = 0, limit: int = 48, before: int = 0, handoff: bool = False):
    return await asyncio.to_thread(catalog.page, pid, section, q, kind, category, offset, limit, before, handoff)


@app.get('/api/projects/{pid}/documents/{did}')
async def project_document(pid: str, did: str):
    return catalog.document(pid, did)


@app.get('/api/projects/{pid}/assets/{aid}')
async def project_asset(pid: str, aid: str):
    value = store.one('SELECT id,name,kind,source,active,created FROM assets WHERE project_id=? AND id=?', (pid, aid))
    if not value: raise ValueError('资产不属于当前项目')
    return value


@app.get('/api/projects/{pid}/task-board')
async def project_task_board(pid: str, q: str = '', before: int = 0, limit: int = 48):
    store.project(pid)
    page = await asyncio.to_thread(catalog.page, pid, 'tasks', q, before=before, limit=limit)
    checked = await asyncio.to_thread(tasks.list_tasks, pid)
    by_id = {t['id']: t for t in checked}
    return {**page, 'items': [by_id[t['id']] for t in page['items'] if t['id'] in by_id],
            'accepted_tasks': sum(t['status'] == 'done' and t['ready'] for t in checked), 'total_tasks': len(checked)}


@app.post('/api/projects/{pid}/conversations')
async def create_conversation(pid: str, request: Request):
    return conversations.create(pid, await request.json())


@app.patch('/api/conversations/{cid}')
async def update_conversation(cid: str, request: Request):
    return conversations.update(cid, await request.json())


@app.get('/api/conversations/{cid}/messages')
async def conversation_messages(cid: str, q: str = '', limit: int = 100):
    return conversations.history(cid, q, limit)


@app.get('/api/conversations/{cid}/window')
async def conversation_window(cid: str, q: str = '', before: int = 0):
    return conversations.window(cid, q, before)


@app.get('/api/conversations/{cid}/messages/{mid}')
async def conversation_record(cid: str, mid: str, offset: int = 0, limit: int = 6000):
    return conversations.read_message(cid, mid, offset, limit)


@app.post('/api/conversations/{cid}/fork')
async def fork_conversation(cid: str):
    return conversations.fork(cid)


@app.get('/api/conversations/{cid}/preferences')
async def conversation_preferences(cid: str):
    return conversations.preferences(cid)


@app.put('/api/conversations/{cid}/preferences')
async def save_conversation_preferences(cid: str, request: Request):
    return conversations.save_preferences(cid, await request.json())


@app.get('/api/conversations/{cid}/permissions')
async def get_agent_permissions(cid: str):
    return permissions.get(cid)


@app.put('/api/conversations/{cid}/permissions')
async def save_agent_permissions(cid: str, request: Request):
    result = permissions.save(cid, await request.json())
    jobs.revoke(cid)
    codex.client.last_policy = {'verified': False, 'note': '授权已变化，请重新核验当前会话'}
    chat.revoke_conversation(cid)
    workbench_actions.revoke(cid)
    return result


@app.get('/api/conversations/{cid}/actions')
async def agent_actions(cid: str):
    return workbench_actions.catalog(permissions.get(cid))


@app.get('/api/projects/{pid}/generation-models')
async def generation_model_catalog(pid: str):
    return generation_models.catalog(pid)


@app.put('/api/projects/{pid}/generation-models')
async def generation_model_defaults(pid: str, request: Request):
    return generation_models.save(pid, await request.json())


@app.get('/api/runs/{rid}/tools')
async def run_tools(rid: str):
    if not store.one('SELECT id FROM runs WHERE id=?', (rid,)):
        raise ValueError('执行记录不存在')
    return store.rows('SELECT * FROM tool_events WHERE run_id=? ORDER BY created,rowid', (rid,))


@app.get('/api/runs/{rid}')
async def run_record(rid: str):
    value = store.one('SELECT * FROM runs WHERE id=?', (rid,))
    if not value: raise ValueError('执行记录不存在')
    return value


@app.post('/api/runs/{rid}/cancel')
async def cancel_run(rid: str):
    return chat.cancel(rid)


@app.get('/api/mcp/policy')
async def mcp_policy():
    return {'profiles': {agent: {mode: agent_tools.definitions(mode == 'execute', agent) for mode in ('discussion', 'execute')}
                         for agent in ('director', 'music', 'modeler')}, 'last_check': codex.client.last_policy}


@app.post('/api/projects/{pid}/mcp/check')
async def check_mcp(pid: str, request: Request):
    project, data = store.project(pid), await request.json()
    agent, write = data.get('agent', 'director'), data.get('execute', False)
    if agent not in ('director', 'music', 'modeler') or not isinstance(write, bool):
        raise ValueError('角色或权限模式无效')
    cid = data.get('conversation_id')
    if cid: conversations.get(cid, pid, agent)
    grant = permissions.get(cid) if cid and write else dict.fromkeys(permissions.FLAGS, False)
    token, tid = random_secrets.token_urlsafe(32), None
    rid = store.run_start(pid, 'mcp_check', '正在核验当前角色工具隔离', agent=agent)
    AGENTS[token] = {'pid': pid, 'write': write, 'agent': agent, 'run_id': rid}
    if cid:
        AGENTS[token].update(conversation_id=cid, grant_version=permissions.get(cid)['version'], codex_computer=bool(grant.get('computer')))
    try:
        allowed = [t['name'] for t in agent_tools.definitions(write, agent, grant)]
        tid, runtime = await codex.client.prepare(project['root'], data.get('model') or None, write and (agent == 'director' or grant.get('computer')), chat.bridge(token), allowed, chat.instructions(agent, write, grant), **({'full_access': True} if grant.get('computer') else {}))
        runtime.update(agent=agent, mode='execute' if write else 'discussion', checked_at=store.now(), permissions=grant, grant_version=AGENTS[token].get('grant_version', ''))
        store.execute('UPDATE runs SET runtime=?,model=? WHERE id=?', (json.dumps(runtime), runtime['model'], rid))
        store.run_end(rid, 'completed', '工具隔离核验通过；未调用模型推理')
        return runtime
    except Exception:
        store.run_end(rid, 'failed', '工具隔离核验失败，本轮不会开始模型执行')
        raise
    finally:
        AGENTS.pop(token, None)
        if tid:
            try:
                await codex.client.rpc('thread/archive', {'threadId': tid}, timeout=10)
            except Exception:
                pass


@app.patch('/api/projects/{pid}')
async def update_project(pid: str, request: Request):
    p, data = store.project(pid), await request.json()
    brief = str(data.get('brief', p['brief']))
    if len(brief) > 30000:
        raise ValueError('总纲过长')
    store.execute('UPDATE projects SET brief=? WHERE id=?', (brief, pid))
    return store.project(pid)


@app.post('/api/projects/{pid}/documents')
async def create_document(pid: str, request: Request):
    data = await request.json()
    store.project(pid)
    return agent_tools.document(pid, str(data.get('title', '未命名文档')), str(data.get('content', '')))


@app.patch('/api/documents/{did}')
async def update_document(did: str, request: Request):
    data = await request.json()
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM documents WHERE id=?', (did,)).fetchone()
        if not row:
            raise ValueError('文档不存在')
        d = dict(row)
        if data.get('revision') != d['revision']:
            raise HTTPException(409, '文档已有新版本，请刷新后比较修改')
        title, content = str(data.get('title', d['title'])), str(data.get('content', d['content']))
        authority = data.get('authority', d['authority'])
        if not title.strip() or len(title) > 180 or len(content) > 300000 or authority not in ('draft', 'approved', 'archived'):
            raise ValueError('无效文档内容或状态')
        c.execute('INSERT INTO document_versions VALUES (?,?,?,?,?,?)',
                  (did, d['revision'], d['content'], d['title'], d['authority'], store.now()))
        c.execute('UPDATE documents SET title=?, content=?, authority=?, revision=revision+1, updated=? WHERE id=?',
                  (title, content, authority, store.now(), did))
        tasks.document_changed(c, did)
    return store.one('SELECT * FROM documents WHERE id=?', (did,))


@app.get('/api/documents/{did}/versions')
async def document_versions(did: str):
    return store.rows('SELECT * FROM document_versions WHERE doc_id=? ORDER BY revision DESC', (did,))


@app.post('/api/projects/{pid}/tasks')
async def create_task(pid: str, request: Request):
    return await asyncio.to_thread(tasks.create, pid, await request.json())


@app.patch('/api/tasks/{tid}')
async def update_task(tid: str, request: Request):
    return await asyncio.to_thread(tasks.update, tid, await request.json())


@app.get('/api/tasks/{tid}/acceptances')
async def task_acceptances(tid: str):
    return deliveries.history(tid)


@app.post('/api/projects/{pid}/scan')
async def scan_assets(pid: str):
    return await asyncio.to_thread(assets.scan, pid)


@app.post('/api/projects/{pid}/upload')
async def upload(pid: str, file: UploadFile = File(...)):
    store.project(pid)
    name = Path(file.filename or 'file').name
    content = await file.read(60 * 1024 * 1024 + 1)
    if len(content) > 60 * 1024 * 1024:
        raise ValueError('上传文件过大')
    suffix = Path(name).suffix.lower()
    if suffix in ('.md', '.txt'):
        if len(content) > 300000:
            raise ValueError('文档过长，请拆分后导入')
        return {'document': agent_tools.document(pid, name, content.decode('utf-8-sig'))}
    if suffix not in assets.KINDS:
        raise ValueError('支持图片、音频、GLB 和已支持的引擎资产，以及 Markdown/TXT 文档')
    dest = store.project_dir(pid) / 'assets' / (store.uid() + suffix)
    dest.parent.mkdir(exist_ok=True)
    dest.write_bytes(content)
    if assets.KINDS[suffix] == 'image':
        try:
            with Image.open(dest) as im:
                im.verify()
        except Exception:
            dest.unlink(missing_ok=True)
            raise ValueError('图片文件无效')
    a = assets.register(pid, dest)
    store.execute('UPDATE assets SET name=? WHERE id=?', (name, a['id']))
    return {'asset': assets.asset(a['id'])}


@app.get('/api/assets/{aid}/file')
async def asset_file(aid: str):
    a = assets.asset(aid)
    return FileResponse(assets.file_for(a), media_type=mimetypes.guess_type(a['active'])[0] or 'application/octet-stream')


@app.get('/api/assets/{aid}/info')
async def asset_info(aid: str):
    a = assets.asset(aid)
    path = assets.file_for(a)
    info = {'asset': a, 'hash': await asyncio.to_thread(assets.digest, path), 'bytes': path.stat().st_size,
            'versions': json.loads(a['versions'])}
    info['version_index'] = next(i for i, v in enumerate(info['versions']) if v['path'] == a['active'])
    with store.db() as c: info['origin'] = deliveries.origin(aid, c)
    if a['kind'] == 'image':
        with Image.open(path) as image:
            info.update(width=image.width, height=image.height, mode=image.mode)
    elif path.suffix.lower() == '.wav':
        with wave.open(str(path), 'rb') as audio:
            info.update(duration=audio.getnframes() / audio.getframerate(), sample_rate=audio.getframerate(), channels=audio.getnchannels())
    info['generations'] = store.rows('SELECT * FROM art_jobs WHERE asset_id=? ORDER BY created DESC', (aid,))
    return info


@app.post('/api/assets/{aid}/edit')
async def image_edit(aid: str, request: Request):
    changes = await request.json()
    a = assets.asset(aid)
    rid = store.run_start(a['project_id'], 'image_edit', a['name'])
    try:
        result = await asyncio.to_thread(assets.edit_image, aid, changes)
        store.run_end(rid, 'completed', '已保存新版本，原始文件未覆盖')
        return result
    except Exception:
        store.run_end(rid, 'failed', '图片编辑失败，原始文件未改动')
        raise


@app.post('/api/assets/{aid}/restore')
async def asset_restore(aid: str, request: Request):
    return assets.restore(aid, int((await request.json())['index']))


@app.post('/api/assets/{aid}/edit-audio')
async def audio_edit(aid: str, request: Request):
    return await asyncio.to_thread(assets.edit_audio, aid, await request.json())


@app.put('/api/providers/{provider}')
async def save_provider(provider: str, request: Request):
    if provider not in providers.BASES:
        raise ValueError('不支持的服务商')
    data = await request.json()
    if 'key' in data and data['key']:
        secrets.save_key(provider, str(data['key']))
        store.execute('DELETE FROM model_checks WHERE provider=?', (provider,))
    if data.get('clear_key'):
        secrets.save_key(provider, '')
        store.execute('DELETE FROM model_checks WHERE provider=?', (provider,))
    next_model = str(data.get('model', ''))[:120]
    store.set_setting(provider + '_model', next_model)
    if 'image_model' in data:
        store.set_setting('image_model', str(data['image_model'])[:120])
    return {'configured': bool(secrets.get_key(provider)), 'model': store.setting(provider + '_model', '')}


@app.post('/api/providers/{provider}/test')
async def test_provider(provider: str):
    models = await providers.models(provider)
    return {'models': models, 'note': '模型列表访问成功，推理能力需一次真实对话验证'}


@app.get('/api/codex/status')
async def codex_status():
    try:
        return await codex.client.status()
    except Exception as e:
        return {'available': False, 'error': str(e), 'models': []}


@app.post('/api/codex/login')
async def codex_login():
    return await codex.client.login()


@app.post('/api/internal/mcp')
async def internal_mcp(request: Request):
    token = request.headers.get('authorization', '').removeprefix('Bearer ')
    scope = AGENTS.get(token)
    if not scope:
        raise HTTPException(403, '工具会话已结束')
    data = await request.json()
    if data['method'] == 'tools/list':
        tools = agent_tools.definitions(scope['write'], scope.get('agent', 'director'), permissions.effective(scope))
        return {'tools': [{'name': t['name'], 'description': t['description'], 'inputSchema': t['parameters'], 'annotations': {'readOnlyHint': t['name'] not in agent_tools.WRITE_TOOLS, 'destructiveHint': t['name'] == 'workbench_call'}} for t in tools]}
    if data['method'] == 'tools/call':
        try:
            result = await agent_tools.invoke(scope, data['params']['name'], data['params'].get('arguments', {}))
            image = result.pop('_image', None) if isinstance(result, dict) else None
            content = [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}]
            if image:
                content.append({'type': 'image', 'data': image, 'mimeType': 'image/png'})
            return {'content': content}
        except (ValueError, KeyError, TypeError) as e:
            return {'isError': True, 'content': [{'type': 'text', 'text': str(e)}]}
    raise ValueError('不支持的工具请求')


@app.post('/api/projects/{pid}/chat')
async def chat_project(pid: str, request: Request):
    return await chat.handle(pid, request)


@app.post('/api/projects/{pid}/generate-image')
async def generate_image(pid: str, request: Request):
    result = await image_jobs.run(pid, await request.json())
    return result['asset']


@app.post('/api/assets/{aid}/ai-edit')
async def ai_image_edit(aid: str, request: Request):
    a = assets.asset(aid)
    return await image_jobs.run(a['project_id'], await request.json(), aid)


@app.post('/api/projects/{pid}/engine/install')
async def install_engine(pid: str):
    return await asyncio.to_thread(engines.install, pid)


@app.post('/api/projects/{pid}/engine/command')
async def engine_command(pid: str, request: Request):
    data = await request.json()
    op = data.pop('op', '')
    if op not in ('status', 'list_assets', 'inspect', 'preview', 'set_material_color'):
        raise ValueError('此引擎操作尚未开放')
    if op == 'set_material_color':
        color = data.get('color')
        if not isinstance(color, list) or len(color) != 4 or not all(isinstance(v, (float, int)) and 0 <= v <= 1 for v in color):
            raise ValueError('颜色需为 0–1 的 RGBA 四元组')
        a = assets.asset(data.get('asset_id', ''))
        if a['project_id'] != pid or assets.digest(assets.file_for(a)) != data.pop('expected_hash', ''):
            raise ValueError('资产版本已变化，请重新检查后再修改')
        target = engines.asset_target(a)
        if data.get('path') != target:
            raise ValueError('引擎目标与已校验的资产不一致，请重新选择资产')
        data['path'] = target
    data.pop('asset_id', None)
    result = await engines.command(pid, op, **data)
    if op == 'preview' and result.get('file'):
        path = assets.inside(result['file'], store.project(pid)['root'])
        if path.suffix.lower() == '.tga':
            converted = store.project_dir(pid) / 'assets' / (store.uid() + '.png')
            converted.parent.mkdir(exist_ok=True)
            with Image.open(path) as im:
                im.save(converted)
            path = converted
        a = assets.register(pid, path)
        result['preview_asset_id'] = a['id']
    return result


@app.get('/api/projects/{pid}/export')
async def export_project(pid: str):
    output = await asyncio.to_thread(backup.write, pid)
    return FileResponse(output, filename='game-project-backup.zip')


@app.post('/api/import-project')
async def import_project(file: UploadFile = File(...)):
    raw = await file.read(60 * 1024 * 1024 + 1)
    if len(raw) > 60 * 1024 * 1024:
        raise ValueError('备份包过大')
    pid = store.uid()
    root = store.project_dir(pid)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(e.file_size for e in entries) > 500 * 1024 * 1024:
                raise ValueError('备份解压规模过大')
            manifest = json.loads(archive.read('project.json'))
            model_defaults = generation_models.validate(manifest['generation_models']) if 'generation_models' in manifest else None
            if manifest.get('format') not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
                raise ValueError('不支持此备份版本')
            for item in entries:
                target = assets.inside(root / item.filename, root)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(item))
        p = manifest['project']
        with store.db() as c:
            c.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)', (pid, str(p['name']) + ' · 恢复副本', p['engine'], str(root), p['brief'], store.now()))
            if model_defaults: c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('generation_models:' + pid, json.dumps(model_defaults)))
            doc_ids = {}
            for d in manifest['documents']:
                did = doc_ids[d['id']] = store.uid()
                c.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)', (did, pid, d['title'], d['content'], d['revision'], d['authority'], d['updated']))
            for v in manifest.get('document_versions', []):
                c.execute('INSERT INTO document_versions VALUES (?,?,?,?,?,?)', (doc_ids[v['doc_id']], v['revision'], v['content'], v['title'], v['authority'], v['created']))
            task_ids = {}
            for t in manifest['tasks']:
                tid = task_ids[t['id']] = store.uid()
                c.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?)', (tid, pid, t['title'], t['status'], t['detail'], t['evidence'], t['created']))
            for old_id, tid in task_ids.items():
                dependencies = [task_ids[l['depends_on']] for l in manifest.get('task_dependencies', []) if l['task_id'] == old_id]
                tasks.set_links(c, tid, pid, {'dependency_ids': dependencies})
            for link in manifest.get('task_documents', []):
                c.execute('INSERT INTO task_documents VALUES (?,?,?)', (task_ids[link['task_id']], doc_ids[link['doc_id']], int(link['revision'])))
            for review in manifest.get('task_reviews', []):
                c.execute('INSERT INTO task_reviews VALUES (?,?,?)', (task_ids[review['task_id']], review['reason'], review['created']))
            asset_ids = {}
            for a in manifest['assets']:
                versions = json.loads(a['versions'])
                for v in versions:
                    v['path'] = str(assets.inside(root / v['path'], root))
                active = str(assets.inside(root / a['active'], root))
                if active not in [v['path'] for v in versions]:
                    raise ValueError('资产版本清单无效')
                c.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)', (asset_ids.setdefault(a['id'], store.uid()), pid, a['name'], active, active, a['kind'], json.dumps(versions), a['created']))
            conversation_ids, run_ids = {}, {}
            for item in manifest.get('conversations', []):
                cid = conversation_ids[item['id']] = store.uid()
                if item['agent'] not in ('director', 'music', 'modeler') or item['provider'] not in ('codex', 'openai', 'deepseek'):
                    raise ValueError('无效会话角色或服务')
                c.execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?,?,?)',
                          (cid, pid, item['agent'], item['title'], item['provider'], item['model'], item['memory'], int(bool(item['archived'])), item['created'], item['updated']))
            for r in manifest.get('runs', []):
                rid = run_ids[r['id']] = store.uid()
                status = 'interrupted' if r['status'] == 'running' else r['status']
                c.execute('INSERT INTO runs (id,project_id,kind,status,detail,usage,created,updated,conversation_id,provider,model,agent,runtime) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (rid, pid, r['kind'], status, r['detail'], r['usage'], r['created'], r['updated'], conversation_ids[r['conversation_id']] if r.get('conversation_id') else None,
                           r.get('provider', ''), r.get('model', ''), r.get('agent', ''), r.get('runtime', '{}')))
            for m in manifest['messages']:
                c.execute('INSERT INTO messages (id,project_id,role,content,provider,created,conversation_id,run_id,model,asset_id) VALUES (?,?,?,?,?,?,?,?,?,?)',
                          (store.uid(), pid, m['role'], m['content'], m['provider'], m['created'], conversation_ids[m['conversation_id']] if m.get('conversation_id') else None,
                           run_ids[m['run_id']] if m.get('run_id') else None, m.get('model', ''), asset_ids[m['asset_id']] if m.get('asset_id') else None))
            for event in manifest.get('tool_events', []):
                status = 'interrupted' if event['status'] == 'running' else event['status']
                c.execute('INSERT INTO tool_events VALUES (?,?,?,?,?,?,?,?,?,?)',
                          (store.uid(), run_ids[event['run_id']], pid, conversation_ids[event['conversation_id']] if event.get('conversation_id') else None,
                           event['tool'], event['arguments'], event['result'], status, event['created'], event['updated']))
            art_ids = {item['id']: store.uid() for item in manifest.get('art_jobs', [])}
            for item in manifest.get('art_jobs', []):
                spec = json.loads(item['spec'])
                if not isinstance(spec, dict) or not c.execute('SELECT json_valid(?)', (item['spec'],)).fetchone()[0]:
                    raise ValueError('创作参数清单无效')
                for key in ('source_asset_id', 'mask_asset_id'):
                    if spec.get(key):
                        if not isinstance(spec[key], str) or spec[key] not in asset_ids:
                            raise ValueError('创作参考图关联无效')
                        spec[key] = asset_ids[spec[key]]
                c.execute('INSERT INTO art_jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                          (art_ids[item['id']], pid, run_ids[item['run_id']] if item.get('run_id') else None,
                           asset_ids[item['asset_id']] if item.get('asset_id') else None, item['provider'], json.dumps(spec, ensure_ascii=False),
                           'interrupted' if item['status'] == 'running' else item['status'], item['result'], item['created'], item['updated']))
            character_ids = {j['id']: store.uid() for j in manifest.get('character_jobs', [])}
            for j in manifest.get('character_jobs', []):
                spec = modeling.validate(pid, json.loads(j['spec']))
                if spec.get('reference_asset_id'):
                    spec['reference_asset_id'] = asset_ids[spec['reference_asset_id']]
                status = 'interrupted' if j['status'] == 'building' else j['status']
                c.execute('INSERT INTO character_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                          (character_ids[j['id']], pid, character_ids[j['parent_id']] if j.get('parent_id') else None,
                           run_ids[j['run_id']] if j.get('run_id') else None,
                           *[asset_ids[j[k]] if j.get(k) else None for k in ('model_id', 'source_id', 'preview_id')],
                           json.dumps(spec, ensure_ascii=False), status, j['result'], j['created'], j['updated']))
            for item in manifest.get('project_intakes', []):
                report, files = json.loads(item['report']), json.loads(item['files'])
                if not isinstance(report, dict) or not isinstance(files, list) or len(files) > 30000:
                    raise ValueError('原项目清单无效')
                report['restored_snapshot'] = True
                report['source_mode'] = 'restored_snapshot'
                report['superseded_document_ids'] = [doc_ids[d] for d in report.get('superseded_document_ids', [])]
                for key in ('claims', 'design_topics'):
                    for evidence in report.get(key, []):
                        if evidence.get('document_id'):
                            evidence['document_id'] = doc_ids[evidence['document_id']]
                for f in files:
                    if not isinstance(f.get('path'), str) or Path(f['path']).is_absolute() or '..' in Path(f['path']).parts:
                        raise ValueError('原项目相对路径无效')
                    for key, mapping in (('asset_id', asset_ids), ('document_id', doc_ids)):
                        if f.get(key):
                            f[key] = mapping[f[key]]
                summary_id = doc_ids[item['summary_document_id']]
                summary = c.execute('SELECT content FROM documents WHERE id=?', (summary_id,)).fetchone()['content']
                for old_id, new_id in doc_ids.items():
                    summary = summary.replace('文档 ID ' + old_id, '文档 ID ' + new_id)
                c.execute('UPDATE documents SET content=? WHERE id=?', (summary, summary_id))
                c.execute('INSERT INTO project_intakes VALUES (?,?,?,?,?)', (pid, summary_id, json.dumps(report, ensure_ascii=False), json.dumps(files, ensure_ascii=False), item['updated']))
            tripo_ids = {item['id']: store.uid() for item in manifest.get('tripo_jobs', [])}
            for item in manifest.get('tripo_jobs', []):
                spec = tripo.validate(json.loads(item['spec']))
                if spec['source_asset_id']:
                    spec['source_asset_id'] = asset_ids[spec['source_asset_id']]
                if not isinstance(item['region'], str) or item['region'] not in tripo.BASES or not isinstance(item['task_id'], str) or (item['task_id'] and not tripo.TASK.fullmatch(item['task_id'])):
                    raise ValueError('Tripo 区域或任务 ID 无效')
                status = 'imported' if item.get('model_id') else 'unknown' if item['status'] in ('unknown', 'submitting') and not item['task_id'] else 'restored'
                c.execute('INSERT INTO tripo_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                          (tripo_ids[item['id']], pid, run_ids[item['run_id']] if item.get('run_id') else None,
                           asset_ids[item['model_id']] if item.get('model_id') else None,
                           asset_ids[item['preview_id']] if item.get('preview_id') else None, item['region'],
                           json.dumps(spec, ensure_ascii=False), status, item['task_id'], item['result'], item['created'], item['updated']))
            music_ids = {j['id']: store.uid() for j in manifest.get('music_jobs', [])}
            for j in manifest.get('music_jobs', []):
                spec, serials = json.loads(j['spec']), json.loads(j['serials'])
                if not isinstance(spec, dict) or not c.execute('SELECT json_valid(?)', (j['spec'],)).fetchone()[0] or not isinstance(serials, list) or any(not isinstance(k, str) or not 0 < len(k) <= 160 for k in serials): raise ValueError('音乐历史参数或任务编号无效')
                # Restored copies may query known IDs but cannot resubmit old drafts.
                c.execute('INSERT INTO music_jobs VALUES (?,?,?,?,?,?,?,?)', (music_ids[j['id']], pid, j['spec'], 'restored', j['serials'], j['result'], j['created'], j['updated']))
            for m in manifest.get('music_assets', []):
                if not isinstance(m['serial_no'], str) or m['serial_no'] not in json.loads({j['id']: j['serials'] for j in manifest['music_jobs']}[m['job_id']]) or not isinstance(m['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', m['sha256']): raise ValueError('音乐产出关联无效')
                c.execute('INSERT INTO music_assets VALUES (?,?,?,?,?,?,?,?)', (music_ids[m['job_id']], m['serial_no'], asset_ids[m['asset_id']], m['sha256'], m['bytes'], m['mime'], m['duration'], m['created']))
            for link in manifest.get('task_deliveries', []):
                a = c.execute('SELECT versions FROM assets WHERE id=?', (asset_ids[link['asset_id']],)).fetchone()
                index = link['version_index']
                if type(index) is not int or not 0 <= index < len(json.loads(a['versions'])) or not isinstance(link['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', link['sha256']): raise ValueError('任务交付版本无效')
                c.execute('INSERT INTO task_deliveries VALUES (?,?,?,?,?)', (task_ids[link['task_id']], asset_ids[link['asset_id']], index, link['sha256'], link['created']))
            for receipt in manifest.get('task_acceptances', []):
                snapshot = json.loads(receipt['snapshot'])
                for link in snapshot['deliveries']:
                    link['asset_id'] = asset_ids[link['asset_id']]
                    if link.get('origin'):
                        origin = link['origin']; mapping = {'art': art_ids, 'music': music_ids, 'blender': character_ids, 'tripo': tripo_ids}[origin['kind']]
                        origin['job_id'] = mapping[origin['job_id']]
                        if origin.get('run_id'): origin['run_id'] = run_ids[origin['run_id']]
                for link in snapshot['documents']: link['doc_id'] = doc_ids[link['doc_id']]
                snapshot['dependency_ids'] = [task_ids[k] for k in snapshot['dependency_ids']]
                c.execute('INSERT INTO task_acceptances VALUES (?,?,?,?,?,?)', (store.uid(), pid, task_ids[receipt['task_id']], receipt['evidence'], json.dumps(snapshot, ensure_ascii=False, sort_keys=True), receipt['created']))
            for creation in manifest.get('task_creations', []):
                mapping = {'art': art_ids, 'music': music_ids, 'blender': character_ids, 'tripo': tripo_ids}.get(creation['kind'])
                if mapping is None: raise ValueError('创作关联类型无效')
                c.execute('INSERT INTO task_creations VALUES (?,?,?,?,?,?)', (store.uid(), pid, task_ids[creation['task_id']], creation['kind'], mapping[creation['job_id']], creation['created']))
            for old_id, did in doc_ids.items():
                doc = c.execute('SELECT title,content FROM documents WHERE id=?', (did,)).fetchone()
                if doc['title'].split(' · ')[0] in ('PROJECT_MEMORY.md', 'SKILLS.md', 'WORKFLOW.md'):
                    content = doc['content']
                    for mapping in (doc_ids, task_ids, run_ids):
                        for old, new in mapping.items(): content = content.replace('`' + old + '`', '`' + new + '`')
                    c.execute('UPDATE documents SET content=? WHERE id=?', (content, did))
            for operation in manifest.get('work_jobs', []):
                kind = operation['source_kind']; mappings = {'music': music_ids, 'tripo': tripo_ids}
                if kind not in mappings or operation['action'] not in ('query', 'import'): raise ValueError('作业记录类型无效')
                params = json.loads(operation['parameters'])
                result = json.loads(operation['result'])
                if not isinstance(params, dict) or not isinstance(result, dict) or operation['status'] not in ('queued', 'running', 'succeeded', 'failed', 'unknown', 'needs_user', 'cancelled', 'interrupted'): raise ValueError('作业历史字段无效')
                if kind == 'music' and operation['action'] == 'import':
                    serials = json.loads({j['id']: j['serials'] for j in manifest['music_jobs']}[operation['source_id']])
                    if set(params) != {'serial_no'} or params['serial_no'] not in serials: raise ValueError('音乐接入历史编号无效')
                elif params: raise ValueError('只读作业历史参数无效')
                if result.get('source_id'): result['source_id'] = mappings[kind][result['source_id']]
                if result.get('asset_id'): result['asset_id'] = asset_ids[result['asset_id']]
                if result.get('parent_run_id'): result['parent_run_id'] = run_ids.get(result['parent_run_id'])
                if result.get('conversation_id'): result['conversation_id'] = conversation_ids.get(result['conversation_id'])
                status = 'interrupted' if operation['status'] in ('queued', 'running') else operation['status']
                c.execute('INSERT INTO work_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (store.uid(), pid, kind, mappings[kind][operation['source_id']], operation['action'], operation['parameters'], '{}', status, json.dumps(result), operation['error'], operation['created'], operation['updated']))
        conversations.migrate_legacy(pid)
        return store.project(pid)
    except (ValueError, KeyError, TypeError, IndexError, zipfile.BadZipFile, json.JSONDecodeError):
        # Only remove the fresh directory created for this import, never user roots.
        resolved = root.resolve()
        if resolved.parent == (store.DATA / 'projects').resolve() and resolved.name == pid:
            shutil.rmtree(resolved)
        raise ValueError('备份无效，或包含超出项目范围的路径')


@app.get('/api/webui/config')
async def webui_config():
    return webui.config()


@app.put('/api/webui/config')
async def save_webui_config(request: Request):
    return await asyncio.to_thread(webui.save_config, await request.json())


@app.get('/api/webui/catalog')
async def webui_catalog(live: bool = True):
    return await webui.catalog(live)


@app.post('/api/webui/refresh')
async def webui_refresh():
    return await webui.refresh()


@app.get('/api/webui/outputs')
async def webui_outputs(query: str = '', offset: int = 0, limit: int = 48):
    return await asyncio.to_thread(webui.outputs, query[:120], offset, limit)


@app.get('/api/webui/output-file')
async def webui_output_file(path: str, thumbnail: bool = False):
    if thumbnail:
        return Response(await asyncio.to_thread(webui.preview, path), media_type='image/jpeg')
    return FileResponse(webui.output_path(path))


@app.post('/api/projects/{pid}/webui/import')
async def webui_import(pid: str, request: Request):
    return await asyncio.to_thread(webui.import_output, pid, await request.json())


@app.get('/api/projects/{pid}/art-jobs')
async def art_jobs(pid: str):
    store.project(pid)
    return store.rows('SELECT * FROM art_jobs WHERE project_id=? ORDER BY created DESC,rowid DESC LIMIT 100', (pid,))


@app.get('/api/blender/config')
async def blender_config():
    return await asyncio.to_thread(modeling.config)


@app.put('/api/blender/config')
async def save_blender_config(request: Request):
    return await asyncio.to_thread(modeling.save_config, await request.json())


@app.get('/api/projects/{pid}/characters')
async def character_jobs(pid: str):
    return modeling.jobs(pid)


@app.post('/api/projects/{pid}/characters')
async def character_draft(pid: str, request: Request):
    data = await request.json()
    if not isinstance(data, dict) or ('spec' in data and set(data) - {'spec', 'parent_id'}):
        raise ValueError('角色方案字段无效')
    return modeling.draft(pid, data.get('spec', data), data.get('parent_id') if 'spec' in data else None)


@app.post('/api/characters/{jid}/build')
async def character_build(jid: str, request: Request):
    data = await request.json()
    if not isinstance(data, dict) or set(data) != {'confirmed'}:
        raise ValueError('请确认待生成的角色方案')
    return await modeling.start(jid, data.get('confirmed'))


@app.post('/api/characters/{jid}/cancel')
async def character_cancel(jid: str):
    return modeling.cancel(jid)


@app.get('/api/characters/{jid}/logs')
async def character_logs(jid: str):
    return modeling.logs(jid)


@app.post('/api/characters/{jid}/open')
async def character_open(jid: str):
    return await asyncio.to_thread(modeling.open_source, jid)


@app.post('/api/project-intake/preview')
async def preview_existing(request: Request):
    data = await request.json()
    if not isinstance(data, dict):
        raise ValueError('请输入工程文件夹地址')
    if 'root' in data and 'roots' in data: raise ValueError('请使用一个主目录或一个多目录列表，不要同时提供')
    result = await asyncio.to_thread(intake.scan_roots, data.get('roots', [data.get('root')]))
    return intake.public_preview(result)


@app.post('/api/project-intake/attach')
async def attach_existing(request: Request):
    return await asyncio.to_thread(intake.attach, await request.json())


@app.post('/api/projects/{pid}/intake/sources/preview')
async def preview_sources(pid: str, request: Request):
    data = await request.json()
    if not isinstance(data, dict): raise ValueError('目录参数无效')
    return intake.public_preview(await asyncio.to_thread(intake.preview_sources, pid, data.get('roots')))


@app.post('/api/projects/{pid}/intake/sources')
async def attach_sources(pid: str, request: Request):
    data = await request.json()
    if not isinstance(data, dict): raise ValueError('目录参数无效')
    return await asyncio.to_thread(intake.attach_sources, pid, data)


@app.get('/api/projects/{pid}/maintenance')
async def project_maintenance(pid: str):
    return maintenance.state(pid)


@app.post('/api/projects/{pid}/maintenance/audit')
async def audit_project(pid: str):
    return await asyncio.to_thread(maintenance.audit, pid)


@app.get('/api/projects/{pid}/maintenance/files')
async def maintenance_files(pid: str, audit_id: str, candidate_id: str, offset: int = 0):
    return maintenance.candidate_files(pid, audit_id, candidate_id, offset)


@app.post('/api/projects/{pid}/intake/analyze')
async def prepare_project_analysis(pid: str):
    return await asyncio.to_thread(maintenance.prepare_analysis, pid)


@app.post('/api/projects/{pid}/maintenance/archive')
async def archive_project_cache(pid: str, request: Request):
    return await asyncio.to_thread(maintenance.archive, pid, await request.json())


@app.post('/api/projects/{pid}/maintenance/{rid}/restore')
async def restore_project_cache(pid: str, rid: str, request: Request):
    return await asyncio.to_thread(maintenance.restore, pid, rid, await request.json())


@app.get('/api/projects/{pid}/intake/files')
async def existing_files(pid: str, q: str = '', category: str = '', offset: int = 0, limit: int = 60):
    return await asyncio.to_thread(intake.file_list, pid, q[:200], category[:30], offset, limit)


@app.post('/api/projects/{pid}/intake/refresh')
async def refresh_existing(pid: str):
    store.project(pid)
    rid = store.run_start(pid, 'project_intake', '正在只读扫描原项目与设计资料')
    try:
        result = await asyncio.to_thread(intake.refresh, pid)
        store.run_end(rid, 'completed', '扫描与资料接入已完成；未运行或修改原工程')
        return result
    except Exception:
        store.run_end(rid, 'failed', '原项目扫描失败，原工程未改动')
        raise


@app.get('/api/tripo/config')
async def tripo_config():
    return tripo.config()


@app.put('/api/tripo/config')
async def save_tripo_config(request: Request):
    return tripo.save_config(await request.json())


@app.post('/api/tripo/test')
async def tripo_test():
    return await tripo.balance()


@app.get('/api/projects/{pid}/tripo')
async def tripo_jobs(pid: str):
    return tripo.jobs(pid)


@app.post('/api/projects/{pid}/tripo')
async def tripo_draft(pid: str, request: Request):
    return tripo.draft(pid, await request.json())


@app.post('/api/tripo/jobs/{jid}/submit')
async def tripo_submit(jid: str, request: Request):
    data = await request.json()
    return await tripo.submit(jid, data.get('confirmed') if isinstance(data, dict) else None)


@app.post('/api/tripo/jobs/{jid}/refresh')
async def tripo_refresh(jid: str):
    return await tripo.poll(jid)


@app.post('/api/tripo/jobs/{jid}/recover')
async def tripo_recover(jid: str, request: Request):
    data = await request.json()
    if not isinstance(data, dict):
        raise ValueError('请填写任务 ID 并确认已核对 Tripo 控制台')
    return await tripo.recover(jid, data.get('task_id'), data.get('confirmed'))


@app.post('/api/tripo/jobs/{jid}/import')
async def tripo_import(jid: str):
    return await tripo.import_model(jid)


@app.get('/api/accounts')
async def account_balances():
    return accounts.cached()


@app.post('/api/accounts/refresh')
async def refresh_balances(request: Request):
    data = await request.json()
    return await accounts.refresh(data.get('providers', list(accounts.PROVIDERS)) if isinstance(data, dict) else None)


@app.get('/api/projects/{pid}/snapshots')
async def list_snapshots(pid: str):
    return snapshots.jobs(pid)


@app.post('/api/projects/{pid}/snapshots')
async def create_snapshot(pid: str, request: Request):
    return await snapshots.start(pid, await request.json())


@app.get('/api/snapshots/{sid}')
async def get_snapshot(sid: str):
    return snapshots.job(sid)


@app.get('/api/snapshots/{sid}/file')
async def snapshot_file(sid: str):
    j = snapshots.job(sid)
    if j['status'] != 'ready': raise ValueError('快照未完成')
    return FileResponse(j['archive'], filename='project-snapshot-' + sid[:8] + '.zip')


@app.post('/api/snapshots/{sid}/verify')
async def verify_snapshot(sid: str):
    result = await asyncio.to_thread(snapshots.verify, sid)
    return {'verified': True, 'files': len(result['files']), 'sha256': snapshots.job(sid)['archive_sha256']}


@app.post('/api/snapshots/{sid}/restore')
async def restore_snapshot(sid: str, request: Request):
    return await asyncio.to_thread(snapshots.restore, sid, await request.json())


@app.get('/api/github/config')
async def github_config():
    return await asyncio.to_thread(publishing.config)


@app.put('/api/github/config')
async def github_save(request: Request):
    return await asyncio.to_thread(publishing.save_config, await request.json())


@app.get('/api/projects/{pid}/publications')
async def github_publications(pid: str):
    return publishing.jobs(pid)


@app.post('/api/snapshots/{sid}/github/prepare')
async def github_prepare(sid: str, request: Request):
    return await publishing.prepare(sid, await request.json())


@app.post('/api/publications/{jid}/push')
async def github_push(jid: str, request: Request):
    return await publishing.push(jid, await request.json())


@app.post('/api/publications/{jid}/check')
async def github_check(jid: str):
    return await publishing.check(jid)


@app.get('/api/projects/{pid}/updates')
async def project_updates(pid: str, sections: str = 'tasks,runs,assets', since: str = '{}'):
    return await asyncio.to_thread(updates.read, pid, sections, since)


@app.get('/api/projects/{pid}/context')
async def context_preview(pid: str, conversation_id: str = '', mode: str = 'auto'):
    if mode not in ('auto', 'compact'): raise ValueError('上下文模式无效')
    state = await asyncio.to_thread(agent_tools.project_state, pid)
    if conversation_id:
        packet, history, info = context.prepare(state, conversation_id, mode == 'compact')
        return {'packet': packet, 'history': history, 'info': info, 'note': '当前预览不含尚未发送的消息；原文保留，压缩目录不代替正式设计'}
    packet = context.select(state, {'compact': mode == 'compact'})
    return {'packet': packet, 'info': packet['context']}


@app.post('/api/projects/{pid}/context/checkpoint')
async def context_checkpoint(pid: str, request: Request):
    data = await request.json()
    state = await asyncio.to_thread(agent_tools.project_state, pid, full=True)
    return await asyncio.to_thread(context.checkpoint, state, data)


@app.get('/api/projects/{pid}/context/markdown')
async def context_markdown(pid: str, ids: str):
    store.project(pid)
    values = ids.split(',')
    if len(values) != 3 or len(set(values)) != 3: raise ValueError('请选择本次留存的三份文档')
    files = {}
    for did in values:
        doc = store.one('SELECT * FROM documents WHERE id=? AND project_id=?', (did, pid))
        if not doc: raise ValueError('留存文档不属于当前项目')
        name = doc['title'].split(' · ')[0]
        if name not in ('PROJECT_MEMORY.md', 'SKILLS.md', 'WORKFLOW.md') or name in files: raise ValueError('留存文件名称无效；请保留三个文件的标题前缀')
        files[name] = doc['content']
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items(): archive.writestr(name, content)
    return Response(buffer.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="project-context.zip"'})


@app.get('/api/tasks/{tid}')
async def current_task(tid: str):
    current = task_creation.task(tid)
    return next(t for t in await asyncio.to_thread(tasks.list_tasks, current['project_id']) if t['id'] == tid)


@app.get('/api/tasks/{tid}/creations')
async def task_creations(tid: str, request: Request):
    return updates.conditional(task_creation.list_for(tid), request)


@app.post('/api/tasks/{tid}/creations')
async def create_task_draft(tid: str, request: Request):
    return task_creation.create(tid, await request.json())


@app.post('/api/tasks/{tid}/creations/adopt')
async def adopt_task_candidate(tid: str, request: Request):
    data = await request.json()
    if not isinstance(data, dict) or set(data) != {'asset_id', 'confirmed'} or data['confirmed'] is not True: raise ValueError('请确认采用候选当前版本并重新安排任务')
    return await asyncio.to_thread(task_creation.adopt, tid, data['asset_id'])


@app.post('/api/art-jobs/{jid}/generate')
async def generate_art_draft(jid: str, request: Request):
    data = await request.json()
    if not isinstance(data, dict) or set(data) != {'confirmed'} or data['confirmed'] is not True: raise ValueError('请核对美术方案并明确确认本次生成及可能的服务费用')
    row = store.one('SELECT * FROM art_jobs WHERE id=?', (jid,))
    if not row: raise ValueError('美术方案不存在')
    return await image_jobs.run(row['project_id'], {**json.loads(row['spec']), 'provider': row['provider']}, draft_id=jid)


dist = store.ROOT / 'dist'
if dist.exists():
    app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
