import base64
import io
import json
import re
from PIL import Image
from . import store, engines, assets, tasks, music, conversations, modeling, intake, tripo, generation_models, permissions, workbench_actions, context, task_creation, catalog

SPECS = [
    ('get_project', '读取有容量上限的项目目录；section支持overview/documents/tasks/assets/runs分页，record分段读取总纲或任务，文档用read_document',
     {'section': {'type': 'string'}, 'query': {'type': 'string'}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'},
      'record_type': {'type': 'string'}, 'item_id': {'type': 'string'}, 'compact': {'type': 'boolean'}}),
    ('list_assets', '分页列出项目资产及ID、类型；按query/kind筛选，继续使用next_before；无参默认第一页，不代表全部资产',
     {'query': {'type': 'string'}, 'kind': {'type': 'string'}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}, 'before': {'type': 'integer'}}),
    ('search_project_files', '搜索已接入原项目的分类文件清单；空查询列出文件，category 留空表示所有类型',
     {'query': {'type': 'string'}, 'category': {'type': 'string'}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}}),
    ('read_project_file', '分段读取已接入目录中的代码、已选设计正文或工程描述，以判断真实实现；不执行文件，不读取未授权路径或原生二进制',
     {'path': {'type': 'string'}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}}),
    ('read_document', '分段读取完整设计文档；requires_read 文档不能只根据片段推断规则',
     {'document_id': {'type': 'string'}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}}),
    ('search_documents', '检索项目文档标题与正文，返回文档 ID 和匹配片段', {'query': {'type': 'string'}}),
    ('read_history', '搜索当前会话的早期交流；返回有界片段与next_before。指定message_id、offset、limit分段读取原文',
     {'query': {'type': 'string'}, 'before': {'type': 'integer'}, 'message_id': {'type': 'string'}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}}),
    ('get_music_jobs', '读取本项目音乐方案和已记录的生成结果，不发起收费请求', {}),
    ('get_character_jobs', '读取角色参数方案与 Blender 生成状态、资产 ID；不启动生成', {}),
    ('get_tripo_jobs', '读取 Tripo 云端建模方案与已记录状态，不提交或查询远程收费生成', {}),
    ('draft_tripo', '保存 Tripo 文生3D或图生3D方案，不上传图片、不提交收费生成；用户需在 Tripo 页确认。图生模式 prompt 留空，仅使用 source_asset_id 项目图片', tripo.PROPERTIES),
    ('draft_character', '保存参数化低模角色方案，由用户审阅后在本机 Blender 生成；brief 仅记录设计说明，不会执行脚本。height 为米，其余比例相对身高，参考图只用于设计交流，不做自动重建', modeling.PROPERTIES),
    ('draft_music', '保存待用户确认的音乐方案，不提交生成、不消耗音乐积分',
     {'title': {'type': 'string'}, 'prompt': {'type': 'string'}, 'tags': {'type': 'string'}, 'instrumental': {'type': 'boolean'}, 'mv': {'type': 'string', 'enum': [m['id'] for m in music.MODELS]}}),
    ('create_document', '创建一份待定文档，不覆盖正式设计', {'title': {'type': 'string'}, 'content': {'type': 'string'}}),
    ('create_task', '创建待执行任务，可关联 get_project 中的前置任务和设计文档 ID，不代表已经执行',
     {'title': {'type': 'string'}, 'detail': {'type': 'string'},
      'deliveries': {'type': 'array', 'items': {'type': 'object', 'properties': {'asset_id': {'type': 'string'}, 'version_index': {'type': 'integer'}, 'sha256': {'type': 'string'}}, 'required': ['asset_id', 'version_index', 'sha256'], 'additionalProperties': False}},
      'dependency_ids': {'type': 'array', 'items': {'type': 'string'}},
      'document_ids': {'type': 'array', 'items': {'type': 'string'}}}),
    ('engine_status', '读取当前引擎连接状态', {}),
    ('view_asset', '实际查看图片资产预览，返回元数据与版本哈希', {'asset_id': {'type': 'string'}}),
    ('edit_image', '对图片保存尺寸修改或水平翻转的新版本，必须先读取其哈希',
     {'asset_id': {'type': 'string'}, 'expected_hash': {'type': 'string'}, 'width': {'type': 'integer'}, 'height': {'type': 'integer'}, 'flip': {'type': 'boolean'}}),
]
WRITE_TOOLS = {'create_document', 'create_task', 'edit_image', 'draft_music', 'draft_character', 'draft_tripo'}
MUSIC_TOOLS = {'get_project', 'list_assets', 'get_music_jobs', 'draft_music', 'create_document', 'create_task', 'read_document', 'search_documents', 'read_history'}
MODELER_TOOLS = {'get_project', 'list_assets', 'read_document', 'search_documents', 'read_history', 'view_asset', 'get_character_jobs', 'draft_character', 'get_tripo_jobs', 'draft_tripo', 'create_document', 'create_task'}
FULL_SPECS = [
    ('workbench_actions', '查询工作台可用功能、输入示例和积分授权。group 留空列出全部；先查询再调用', {'group': {'type': 'string'}}),
    ('workbench_call', '按目录调用当前项目功能；input_json 为 JSON 对象字符串，可含 target_id、data、query。耗时操作返回 operation_id，必须查询结果，不重复提交', {'action': {'type': 'string'}, 'input_json': {'type': 'string'}}),
    ('workbench_operation', '读取已登记操作的结果，wait_seconds 为0–10秒。completed 只表示操作调用结束，仍需核对其中的生成/上传状态', {'operation_id': {'type': 'string'}, 'wait_seconds': {'type': 'integer', 'minimum': 0, 'maximum': 10}}),
]
WRITE_TOOLS.add('workbench_call')
for name, description, properties in SPECS:
    if name in ('draft_music', 'draft_character', 'draft_tripo'):
        properties['task_id'] = {'type': 'string', 'description': '可选当前项目任务ID；保存方案时关联候选交付，不自动生成或验收'}


def definitions(allow_write, agent='director', grant=None):
    full = allow_write and bool(grant and grant.get('full'))
    return [{'type': 'function', 'name': name, 'description': desc,
             'parameters': {'type': 'object', 'properties': props,
                            'required': [p for p in props if name not in ('get_project', 'list_assets', 'read_history') and not (name in ('draft_music', 'draft_character', 'draft_tripo') and p == 'task_id') and (name != 'create_task' or p in ('title', 'detail')) and not (name == 'draft_music' and p == 'mv') and not (name == 'draft_tripo' and p == 'model')],
                            'additionalProperties': False}}
            for name, desc, props in [*SPECS, *(FULL_SPECS if full else [])] if (allow_write or name not in WRITE_TOOLS) and (full or agent != 'music' or name in MUSIC_TOOLS) and (full or agent != 'modeler' or name in MODELER_TOOLS)]


def document(project_id, title, content):
    if not title.strip() or len(title) > 180 or len(content) > 300000:
        raise ValueError('文档标题为空或内容过长')
    did = store.uid()
    store.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)',
                  (did, project_id, title, content, 1, 'draft', store.now()))
    return store.one('SELECT * FROM documents WHERE id=?', (did,))


def project_state(project_id, args=None, full=False):
    args = args or {}
    pages = {}
    if full:
        s = store.snapshot(project_id, include_messages=False)
    else:
        s = {'project': store.project(project_id), 'tasks': tasks.list_tasks(project_id),
             'runs': store.rows('SELECT * FROM runs WHERE project_id=? ORDER BY created DESC,rowid DESC LIMIT 30', (project_id,)),
             'intake': intake.current(project_id)}
        for section in ('documents', 'assets'):
            values = catalog.page(project_id, section, args.get('query', ''), offset=args.get('offset', 0) if args.get('section') == section else 0,
                                  limit=50, preview=True, approved_first=True)
            s[section] = values['items']; pages[section] = values
            pages[section]['project_total'] = (store.one(f'SELECT COUNT(*) AS n FROM {section} WHERE project_id=?', (project_id,))['n']
                                                if args.get('query') else values['total'])
    documents = []
    sources = intake.document_sources(project_id)
    for doc in s['documents']:
        info = {k: doc[k] for k in ('id', 'title', 'authority', 'revision', 'updated')}
        source = sources.get(doc['id'])
        limit = 600 if source else 4000
        content = doc.get('content', doc.get('content_excerpt', ''))
        chars = doc.get('chars', len(content))
        info.update(chars=chars, requires_read=chars > limit)
        if source:
            info['source'] = source
            if source['status'] != 'present' and source['status'] != 'current_snapshot':
                limit = 0
                info['requires_read'] = True
        info['content_excerpt' if info['requires_read'] else 'content'] = content[:limit]
        documents.append(info)
    imported = s['intake']
    existing = ({'summary_document_id': imported['summary_document_id'],
                 **{k: imported['report'][k] for k in ('runtime_verified', 'counts', 'changes', 'design_topics', 'claims', 'warnings', 'scanned_at')},
                 'restored_snapshot': imported['report'].get('restored_snapshot', False)} if imported else None)
    if existing: existing['roots'] = imported['report'].get('roots', [])
    audit = store.setting('project_audit:' + project_id)
    maintenance = {'document_id': audit['document_id'], 'created': audit['created'], 'truncated': audit['truncated']} if audit else None
    handoff = []
    for title in ('PROJECT_MEMORY.md', 'SKILLS.md', 'WORKFLOW.md'):
        value = store.one('SELECT id,title,revision,authority FROM documents WHERE project_id=? AND title LIKE ? ORDER BY rowid DESC LIMIT 1', (project_id, title + ' · %'))
        if value: handoff.append({**value, 'requires_read': True})
    return {'assets': [{k: a[k] for k in ('id', 'name', 'kind')} for a in s['assets']], 'project': s['project'], 'documents': documents, 'tasks': s['tasks'], 'runs': s['runs'],
            'catalog_pages': pages, 'handoff_documents': handoff,
            'existing_project': existing, 'maintenance': maintenance, 'generation_models': generation_models.catalog(project_id),
            'accepted_tasks': sum(t['status'] == 'done' and t['ready'] for t in s['tasks']),
            'as_of': store.now(), 'note': '只依据工作台已记录证据；done 且 ready 才计入当前验收，不推断未连接引擎的实际状态'}


async def execute(project_id, allow_write, name, args, agent='director'):
    store.project(project_id)
    if agent == 'music' and name not in MUSIC_TOOLS:
        raise ValueError('音乐负责人未获准使用此工具')
    if agent == 'modeler' and name not in MODELER_TOOLS:
        raise ValueError('角色建模负责人未获准使用此工具')
    if name == 'get_project':
        import asyncio
        return context.select(await asyncio.to_thread(project_state, project_id, args), args)
    if name == 'read_document':
        doc = store.one('SELECT * FROM documents WHERE id=? AND project_id=?', (args['document_id'], project_id))
        if not doc:
            raise ValueError('文档不属于此项目')
        offset, limit = args['offset'], args['limit']
        if not 0 <= offset <= len(doc['content']) or not 1 <= limit <= 12000:
            raise ValueError('文档分段范围无效，单次最多 12000 字符')
        return {'id': doc['id'], 'revision': doc['revision'], 'authority': doc['authority'],
                'content': doc['content'][offset:offset + limit], 'total_chars': len(doc['content']),
                'next_offset': offset + limit if offset + limit < len(doc['content']) else None}
    if name == 'search_documents':
        query = args['query'].strip()
        if not query or len(query) > 120:
            raise ValueError('请填写 1–120 字符的检索词')
        matches = []
        for d in store.rows('SELECT * FROM documents WHERE project_id=?', (project_id,)):
            offset = d['content'].lower().find(query.lower())
            if offset >= 0 or query.lower() in d['title'].lower():
                matches.append({'id': d['id'], 'title': d['title'], 'authority': d['authority'], 'revision': d['revision'],
                                'offset': max(0, offset - 100), 'excerpt': d['content'][max(0, offset - 100):max(0, offset) + 500]})
        return {'matches': matches[:20], 'truncated': len(matches) > 20}
    if name == 'list_assets':
        page = catalog.page(project_id, 'assets', args.get('query', ''), args.get('kind', ''),
                            offset=args.get('offset', 0), limit=args.get('limit', 50), before=args.get('before', 0))
        return {**page, 'items': [{k: a[k] for k in ('id', 'name', 'kind')} for a in page['items']]}
    if name == 'search_project_files':
        return intake.file_list(project_id, args['query'][:200], args['category'][:30], args['offset'], args['limit'])
    if name == 'read_project_file':
        return intake.read_file(project_id, args['path'], args['offset'], args['limit'])
    if name == 'get_music_jobs':
        return music.jobs(project_id)
    if name == 'get_character_jobs':
        return modeling.jobs(project_id)
    if name == 'get_tripo_jobs':
        return tripo.jobs(project_id)
    if name == 'engine_status':
        return await engines.command(project_id, 'status')
    if name in ('view_asset', 'edit_image'):
        a = assets.asset(args['asset_id'])
        if a['project_id'] != project_id or a['kind'] != 'image':
            raise ValueError('只能处理本项目中的图片资产')
        if name == 'view_asset':
            path = assets.file_for(a)
            with Image.open(path) as im:
                size = im.size
                im = im.convert('RGBA')
                im.thumbnail((1536, 1536))
                buffer = io.BytesIO(); im.save(buffer, format='PNG')
            return {'id': a['id'], 'name': a['name'], 'width': size[0], 'height': size[1], 'hash': assets.digest(path),
                    '_image': base64.b64encode(buffer.getvalue()).decode()}
    if not allow_write:
        raise ValueError('此轮为讨论模式，不能修改项目；请由用户开启执行模式')
    if name in ('draft_music', 'draft_character', 'draft_tripo') and 'task_id' in args:
        task_creation.task(args['task_id'], project_id)
        kind = {'draft_music': 'music', 'draft_character': 'blender', 'draft_tripo': 'tripo'}[name]
        return task_creation.create(args['task_id'], {'kind': kind, 'data': {k: v for k, v in args.items() if k != 'task_id'}})
    if name == 'draft_music':
        return music.draft(project_id, args)
    if name == 'draft_character':
        return modeling.draft(project_id, args)
    if name == 'draft_tripo':
        return tripo.draft(project_id, args)
    if name == 'edit_image':
        return assets.edit_image(args['asset_id'], args)
    if name == 'create_document':
        title, content = str(args['title']), str(args['content'])
        return document(project_id, title, content)
    if name == 'create_task':
        return tasks.create(project_id, args)
    raise ValueError('此工具未开放')


def summary(value, key=''):
    if re.search(r'token|authorization|api_key|credential|password|_image', key, re.I):
        return '[不记录]'
    if isinstance(value, dict):
        return {k: summary(v, k) for k, v in list(value.items())[:30]}
    if isinstance(value, list):
        return [summary(v) for v in value[:20]]
    if isinstance(value, str):
        value = re.sub(r'\b(?:sks_[0-9a-f]{64}|sk-[A-Za-z0-9_-]{16,}|tsk_[A-Za-z0-9_-]{16,})\b', '[不记录]', value)
        return value[:1500] + ('…' if len(value) > 1500 else '')
    return value


async def invoke(scope, name, args):
    eid = store.uid() if scope.get('run_id') else None
    if eid:
        store.execute('INSERT INTO tool_events VALUES (?,?,?,?,?,?,?,?,?,?)',
                      (eid, scope['run_id'], scope['pid'], scope.get('conversation_id'), str(name)[:120],
                       json.dumps(summary(args), ensure_ascii=False), '{}', 'running', store.now(), store.now()))
    try:
        grant = permissions.effective(scope)
        spec = next((t for t in definitions(scope['write'], scope.get('agent', 'director'), grant) if t['name'] == name), None)
        if not spec or not isinstance(args, dict):
            raise ValueError('此会话未开放该工具或参数无效')
        schema = spec['parameters']
        if any(k not in args for k in schema['required']) or any(k not in schema['properties'] for k in args):
            raise ValueError('工具参数缺失或包含未开放字段')
        types = {'string': str, 'integer': int, 'number': (float, int), 'boolean': bool, 'array': list}
        for key, value in args.items():
            kind = schema['properties'][key]['type']
            if not isinstance(value, types[kind]) or (kind in ('integer', 'number') and isinstance(value, bool)):
                raise ValueError('工具参数类型无效：' + key)
        if name == 'workbench_actions':
            result = workbench_actions.catalog(grant, args['group'])
        elif name == 'workbench_call':
            if len(args['input_json']) > 400000: raise ValueError('工作台操作输入过长')
            try: inputs = json.loads(args['input_json'])
            except ValueError: raise ValueError('input_json 必须是有效 JSON 对象') from None
            result = await workbench_actions.call(scope, args['action'], inputs)
        elif name == 'workbench_operation':
            result = await workbench_actions.operation(scope, args['operation_id'], args['wait_seconds'])
        elif name == 'read_history':
            cid = scope.get('conversation_id')
            if not cid:
                raise ValueError('当前工具会话没有绑定对话记录')
            conversations.get(cid, scope['pid'], scope.get('agent', 'director'))
            result = (conversations.read_message(cid, args['message_id'], args.get('offset', 0), args.get('limit', 6000))
                      if args.get('message_id') else conversations.window(cid, args.get('query', ''), args.get('before', 0)))
        else:
            result = await execute(scope['pid'], scope['write'], name, args, 'director' if grant['full'] else scope.get('agent', 'director'))
        if eid:
            store.execute('UPDATE tool_events SET result=?,status=?,updated=? WHERE id=?',
                          (json.dumps(summary(result), ensure_ascii=False), 'completed', store.now(), eid))
        return result
    except BaseException as exc:
        if eid:
            store.execute('UPDATE tool_events SET result=?,status=?,updated=? WHERE id=?',
                          (json.dumps({'error': summary(str(exc) or '调用中断，请核对产物')}), 'failed' if isinstance(exc, Exception) else 'interrupted', store.now(), eid))
        raise
