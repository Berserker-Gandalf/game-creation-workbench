"""Unified durable job view and serial queue for explicit queries/free output imports."""
import asyncio
import json

from . import music, permissions, store, tripo

TYPES = {'music': 'music_jobs', 'art': 'art_jobs', 'blender': 'character_jobs', 'tripo': 'tripo_jobs',
         'snapshot': 'project_snapshots', 'publication': 'github_publications', 'chat': 'runs', 'operation': 'work_jobs'}
WORKER = CURRENT = WAKE = None
CURRENT_ID = ''
CLOSING = False
CANCELLED = set()


def source(pid, kind, jid):
    if kind not in TYPES or not isinstance(jid, str): raise ValueError('作业类型或编号无效')
    row = store.one(f'SELECT * FROM {TYPES[kind]} WHERE id=? AND project_id=?', (jid, pid))
    if not row or kind == 'chat' and not row['kind'].startswith('chat:'): raise ValueError('作业不属于当前项目')
    return row


def union():
    generic = "CASE WHEN status IN ('running','processing','building','copying','pushing','importing','submitting') THEN 'running' WHEN status IN ('queued','pending','submitted') THEN 'queued' WHEN status IN ('unknown','restored') THEN 'unknown' WHEN status IN ('completed','review','imported','ready','published') THEN 'succeeded' WHEN status IN ('draft','needs_credits','prepared') THEN 'needs_user' WHEN status IN ('failed','cancelled','interrupted') THEN status ELSE 'needs_user' END"
    parts = []
    for kind, table in TYPES.items():
        state = generic
        if kind == 'operation': state = 'status'
        if kind == 'music':
            state = "CASE WHEN status='completed' AND ((SELECT COUNT(*) FROM music_assets m WHERE m.job_id=j.id)<json_array_length(serials) OR json_array_length(serials)=0) THEN 'needs_user' ELSE " + generic + ' END'
        if kind == 'tripo': state = "CASE WHEN status='ready' THEN 'needs_user' ELSE " + generic + ' END'
        if kind == 'art': state = "CASE WHEN status='interrupted' THEN 'unknown' ELSE " + generic + ' END'
        title = "COALESCE(json_extract(spec,'$.title'), '图像创作')" if kind in ('music', 'art', 'blender', 'tripo') else 'label' if kind == 'snapshot' else 'repository' if kind == 'publication' else 'detail' if kind == 'chat' else "CASE action WHEN 'query' THEN '接续查询' ELSE '下载纳入资产' END"
        condition = " WHERE kind LIKE 'chat:%'" if kind == 'chat' else ''
        parts.append(f"SELECT '{kind}' AS kind,id,project_id,{state} AS state,status AS raw_status,{title} AS title,created,updated FROM {table} j{condition}")
    return ' UNION ALL '.join(parts)


def list_jobs(pid, kind='', state='', query='', offset=0, limit=30):
    store.project(pid)
    if kind and kind not in TYPES or state and state not in ('queued', 'running', 'succeeded', 'failed', 'unknown', 'needs_user', 'cancelled', 'interrupted'): raise ValueError('作业筛选无效')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100: raise ValueError('作业分页无效')
    sql = ' FROM (' + union() + ') WHERE project_id=?'
    args = [pid]
    if kind: sql += ' AND kind=?'; args.append(kind)
    if state: sql += ' AND state=?'; args.append(state)
    if query: sql += ' AND instr(lower(title),lower(?))>0'; args.append(query[:200])
    with store.db() as c:
        c.execute('BEGIN')
        total = c.execute('SELECT COUNT(*)' + sql, args).fetchone()[0]
        counts = {r['state']: r['n'] for r in c.execute('SELECT state,COUNT(*) AS n' + sql + ' GROUP BY state', args)}
        rows = [dict(r) for r in c.execute('SELECT *' + sql + ' ORDER BY updated DESC,kind,id LIMIT ? OFFSET ?', [*args, limit, offset])]
    return {'total': total, 'counts': counts, 'items': rows, 'offset': offset, 'limit': limit, 'as_of': store.now()}


def inspect(pid, kind, jid):
    row = source(pid, kind, jid)
    outputs = []
    if kind == 'music': outputs = music.outputs(jid)
    if kind in ('art', 'blender', 'tripo'):
        outputs = [{'asset_id': row[k]} for k in ('asset_id', 'model_id', 'source_id', 'preview_id') if row.get(k)]
    for item in outputs:
        a = store.one('SELECT name,kind FROM assets WHERE id=?', (item['asset_id'],))
        item.update(name=a['name'], kind=a['kind'])
    actions = []
    import_serials = []
    if kind == 'music':
        known = json.loads(row['serials'])
        import_serials = [t.get('serial_no') for t in json.loads(row['result']).get('tasks', []) if isinstance(t, dict) and t.get('serial_no') in known and str(t.get('status')) in ('success', '2')]
        if row['status'] == 'completed' and not import_serials: import_serials = known
    if kind == 'music' and json.loads(row['serials']) or kind == 'tripo' and row['task_id']:
        actions.append('query')
    if kind == 'music' and import_serials or kind == 'tripo' and row['status'] in ('ready', 'imported'):
        actions.append('import')
    if kind == 'operation' and row['status'] in ('queued', 'running') or kind == 'blender' and row['status'] == 'building' or kind == 'snapshot' and row['status'] in ('pending', 'copying') or kind == 'chat' and row['status'] == 'running': actions.append('stop')
    details = {k: row[k] for k in ('id', 'status', 'created', 'updated', 'task_id', 'evidence', 'error', 'run_id', 'provider') if k in row}
    for key in ('spec', 'result', 'runtime', 'serials', 'parameters'):
        if key in row: details[key] = json.loads(row[key])
    if kind == 'operation': details.update(source_kind=row['source_kind'], source_id=row['source_id'], action=row['action'])
    if kind == 'art' and row['status'] == 'draft': actions.append('generate')
    linked = store.one('SELECT task_id FROM task_creations WHERE kind=? AND job_id=? AND project_id=?', (kind, jid, pid))
    if linked: details['origin_task_id'] = linked['task_id']
    title = json.loads(row['spec']).get('title', '绘画产出') if 'spec' in row else row.get('label', row.get('repository', row.get('detail', '查询 / 文件接入')))
    return {'kind': kind, 'id': jid, 'title': title, 'details': details, 'outputs': outputs, 'actions': actions, 'import_serials': import_serials,
            'note': '成功表示相应作业结束或文件已交付，不代表任务已验收；停止本机查询/下载不取消云端生成。收费提交不进入恢复队列。'}


def check_scope(scope):
    if scope and not permissions.effective(scope)['full']: raise ValueError('原会话授权已失效，请由用户重新发起')


def enqueue(pid, data, scope=None):
    if not isinstance(data, dict) or set(data) - {'kind', 'id', 'command', 'serial_no', 'confirmed'}: raise ValueError('作业操作字段无效')
    kind, jid, command = data.get('kind'), data.get('id'), data.get('command')
    row = source(pid, kind, jid)
    if kind not in ('music', 'tripo') or command not in ('query', 'import'): raise ValueError('只支持已记录任务的查询或免费文件接入，不能在此重提交生成')
    if command == 'import' and data.get('confirmed') is not True: raise ValueError('请确认下载所选产出到项目资产')
    if command not in inspect(pid, kind, jid)['actions']: raise ValueError('此作业尚不能执行所选操作，请先核对远端结果')
    params = {}
    if kind == 'music' and command == 'import':
        serial = data.get('serial_no')
        if not isinstance(serial, str) or serial not in json.loads(row['serials']): raise ValueError('请选择本项目已记录的音轨编号')
        params['serial_no'] = serial
    elif 'serial_no' in data: raise ValueError('此操作不接收音轨编号')
    scope = {k: scope[k] for k in ('pid', 'conversation_id', 'agent', 'write', 'grant_version', 'codex_computer', 'run_id') if k in scope} if scope else {}
    check_scope(scope)
    encoded = json.dumps(params, sort_keys=True)
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        previous = c.execute("SELECT * FROM work_jobs WHERE project_id=? AND source_kind=? AND source_id=? AND action=? AND parameters=? AND status IN ('queued','running')", (pid, kind, jid, command, encoded)).fetchone()
        if previous: return public_operation(dict(previous))
        if c.execute("SELECT COUNT(*) FROM work_jobs WHERE status IN ('queued','running')").fetchone()[0] >= 50: raise ValueError('队列已满，请等待或停止旧操作')
        rid = store.uid(); now = store.now()
        origin = {'initiator': 'agent' if scope else 'user', 'parent_run_id': scope.get('run_id'), 'conversation_id': scope.get('conversation_id')}
        c.execute('INSERT INTO work_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (rid, pid, kind, jid, command, encoded, json.dumps(scope), 'queued', json.dumps(origin), '', now, now))
    if WAKE: WAKE.set()
    return public_operation(source(pid, 'operation', rid))


def public_operation(row):
    return {k: row[k] for k in ('id', 'source_kind', 'source_id', 'action', 'status', 'created', 'updated')} | {'kind': 'operation', 'note': '已进入持久队列，请查询此作业；不会重新生成或自动重试收费操作'}


async def perform(row):
    scope = json.loads(row['scope']); check_scope(scope)
    kind, jid = row['source_kind'], row['source_id']
    source(row['project_id'], kind, jid)
    if row['action'] == 'query':
        result = await (music.poll(jid) if kind == 'music' else tripo.poll(jid))
        if result.get('status') == 'error': return 'needs_user', {'message': '查询需要账户处理，请在对应工作区核验授权'}
    elif kind == 'music':
        result = await music.import_audio(jid, json.loads(row['parameters'])['serial_no'], True, lambda: check_scope(scope))
    else:
        current = tripo.job(jid)
        result = current if current['model_id'] else await tripo.import_model(jid)
    check_scope(scope)
    return 'succeeded', {'source_kind': kind, 'source_id': jid, 'source_status': source(row['project_id'], kind, jid)['status'], 'asset_id': result.get('asset_id') or result.get('model_id'), 'note': '本次查询/接入结束，请核对业务作业及资产状态；未自动验收任务'}


async def loop():
    global CURRENT, CURRENT_ID
    while not CLOSING:
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT * FROM work_jobs WHERE status='queued' ORDER BY created,rowid LIMIT 1").fetchone()
            if row: c.execute("UPDATE work_jobs SET status='running',updated=? WHERE id=?", (store.now(), row['id']))
        if not row:
            WAKE.clear()
            try: await asyncio.wait_for(WAKE.wait(), 1)
            except TimeoutError: pass
            continue
        row = dict(row); CURRENT_ID = row['id']; status, result, error = 'failed', {}, ''
        try:
            CURRENT = asyncio.create_task(perform(row))
            status, result = await CURRENT
        except BaseException as exc:
            status = 'queued' if CLOSING and row['action'] == 'query' else 'interrupted' if CLOSING else 'cancelled' if row['id'] in CANCELLED else 'needs_user' if isinstance(exc, music.UserActionRequired) else 'failed'
            error = str(exc)[:500] if isinstance(exc, ValueError) else '本机操作中断或连接异常；请核对原业务作业，不自动重提生成'
        finally:
            store.execute('UPDATE work_jobs SET status=?,result=?,error=?,updated=? WHERE id=?', (status, json.dumps({**json.loads(row['result']), **result}, ensure_ascii=False), error, store.now(), row['id']))
            CANCELLED.discard(row['id']); CURRENT = None; CURRENT_ID = ''


async def start():
    global WORKER, WAKE, CLOSING
    CLOSING = False; WAKE = asyncio.Event(); CANCELLED.clear()
    WORKER = asyncio.create_task(loop())


def stop(pid, kind, jid):
    row = source(pid, kind, jid)
    if 'stop' not in inspect(pid, kind, jid)['actions']: raise ValueError('当前作业没有可用的本机停止入口，云端任务请到服务网站核对')
    if kind == 'operation':
        store.execute("UPDATE work_jobs SET status='cancelled',updated=? WHERE id=? AND status='queued'", (store.now(), jid))
        if CURRENT_ID == jid and CURRENT:
            CANCELLED.add(jid); CURRENT.cancel()
    elif kind == 'blender':
        from . import modeling
        modeling.cancel(jid)
    elif kind == 'snapshot':
        from . import snapshots
        if jid in snapshots.RUNNING: snapshots.RUNNING[jid]['stop'].set()
    elif kind == 'chat':
        from . import chat
        chat.cancel(jid)
    return {'requested': True, 'note': '已请求停止本机操作；已提交的云端生成及已保存文件不会自动撤销'}


def revoke(cid):
    for row in store.rows("SELECT * FROM work_jobs WHERE status IN ('queued','running')"):
        if json.loads(row['scope']).get('conversation_id') == cid: stop(row['project_id'], 'operation', row['id'])


async def shutdown():
    global CLOSING, WORKER
    CLOSING = True
    if WAKE: WAKE.set()
    if CURRENT: CURRENT.cancel()
    if WORKER: await WORKER
    WORKER = None
