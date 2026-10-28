"""Project-scoped business actions reuse the same validated routes as the UI."""
import asyncio
import json
import re
from pathlib import Path

import httpx
from . import assets, backup, permissions, store

RUNNING = {}


def action(name, group, method, path, description, target='', background=False, cost='', example=None):
    return dict(name=name, group=group, method=method, path=path, description=description,
                target=target, background=background, cost=cost, example=example or {'data': {}})


ACTIONS = [
    action('project.get', 'project', 'GET', '/projects/{pid}/workspace', '读取有界概览与计数；资料使用get_project分页，资产使用list_assets，当前交付使用task.get'),
    action('context.preview', 'project', 'GET', '/projects/{pid}/context', '预览有容量上限的项目上下文与覆盖范围，不调用模型'),
    action('context.checkpoint', 'documents', 'POST', '/projects/{pid}/context/checkpoint', '按当前记录及补充决定保存PROJECT_MEMORY/SKILLS/WORKFLOW三份Markdown草稿，不覆盖旧记录'),
    action('project.update', 'project', 'PATCH', '/projects/{pid}', '修改项目总纲', example={'data': {'brief': '项目总纲'}}),
    action('project.scan', 'project', 'POST', '/projects/{pid}/scan', '扫描工程资产', background=True),
    action('project.refresh_intake', 'project', 'POST', '/projects/{pid}/intake/refresh', '刷新已接入工程与设计来源', background=True),
    action('project.audit', 'project', 'POST', '/projects/{pid}/maintenance/audit', '只读审计多来源目录体积、重复样本和缓存候选，保存待定报告；不移除文件', background=True),
    action('project.maintenance', 'project', 'GET', '/projects/{pid}/maintenance', '读取最近空间审计与用户确认的缓存归档记录；归档和恢复由用户审阅后在界面确认'),
    action('project.export', 'retention', 'EXPORT', '', '导出格式10工作台资料包，返回下载位置', background=True),
    action('jobs.list', 'jobs', 'GET', '/projects/{pid}/jobs', '统一查看业务作业与持久查询/下载队列，支持筛选分页'),
    action('jobs.inspect', 'jobs', 'GET', '/projects/{pid}/jobs/inspect', '查看具体作业、生成参数、产出与可用操作'),
    action('jobs.enqueue', 'jobs', 'POST', '/projects/{pid}/jobs/commands', '已记录音乐/Tripo任务的只读查询或免费文件接入；绝不提交生成'),
    action('jobs.stop', 'jobs', 'POST', '/projects/{pid}/jobs/stop', '请求停止支持的本机操作；不会取消云端生成或删除已有产出'),
    action('document.create', 'documents', 'POST', '/projects/{pid}/documents', '创建设计文档', example={'data': {'title': '设计', 'content': '正文'}}),
    action('document.update', 'documents', 'PATCH', '/documents/{id}', '按 revision 更新正文或批准/废弃；设计变化会触发任务复核', 'documents', example={'target_id': '文档ID', 'data': {'revision': 1, 'content': '正文', 'authority': 'draft'}}),
    action('document.versions', 'documents', 'GET', '/documents/{id}/versions', '读取文档历史版本', 'documents'),
    action('task.create', 'tasks', 'POST', '/projects/{pid}/tasks', '创建任务及依赖/文档关联', example={'data': {'title': '任务', 'detail': '验收条件', 'dependency_ids': [], 'document_ids': []}}),
    action('task.update', 'tasks', 'PATCH', '/tasks/{id}', '更新任务与验收；done 仍必须填写真实 evidence', 'tasks', example={'target_id': '任务ID', 'data': {'status': 'review', 'evidence': '已保存交付，待人工检查'}}),
    action('task.acceptances', 'tasks', 'GET', '/tasks/{id}/acceptances', '读取任务验收证据和当时固定的资产/设计版本快照', 'tasks'),
    action('task.get', 'tasks', 'GET', '/tasks/{id}', '读取当前任务、确切交付与验收令牌', 'tasks'),
    action('task.creations', 'tasks', 'GET', '/tasks/{id}/creations', '当前任务的创作方案及候选产出，不代表已采用或验收', 'tasks'),
    action('task.draft', 'tasks', 'POST', '/tasks/{id}/creations', '保存与当前任务关联的music/art/blender/tripo免费方案，data内含kind和data；不执行生成', 'tasks'),
    action('task.adopt', 'tasks', 'POST', '/tasks/{id}/creations/adopt', '明确采用该任务候选资产当前版本，并重置待执行；不自动验收', 'tasks'),
    action('asset.info', 'assets', 'GET', '/assets/{id}/info', '资产信息、版本哈希和本地预览地址', 'assets'),
    action('asset.import_file', 'assets', 'UPLOAD', '/projects/{pid}/upload', '导入工程或工作台项目目录内的文件；整机授权时可选择其他目录', example={'data': {'path': '文件绝对路径'}}, background=True),
    action('asset.edit_image', 'assets', 'POST', '/assets/{id}/edit', '尺寸/翻转/裁剪派生新版本；需 expected_hash', 'assets'),
    action('asset.edit_audio', 'assets', 'POST', '/assets/{id}/edit-audio', 'WAV 裁剪/淡入淡出；需版本哈希', 'assets', True),
    action('asset.restore', 'assets', 'POST', '/assets/{id}/restore', '按 index 恢复资产版本指针', 'assets', example={'target_id': '资产ID', 'data': {'index': 0}}),
    action('image.generate', 'images', 'POST', '/projects/{pid}/generate-image', '通过已配置 OpenAI/WebUI 生成美术，可能消耗图像服务额度', background=True, example={'data': {'provider': 'webui', 'prompt': '图像描述', 'width': 512, 'height': 512}}),
    action('image.edit', 'images', 'POST', '/assets/{id}/ai-edit', '参考图/遮罩 AI 编辑；可能消耗图像服务额度', 'assets', True),
    action('image.jobs', 'images', 'GET', '/projects/{pid}/art-jobs', '项目美术记录'),
    action('image.submit_draft', 'images', 'POST', '/art-jobs/{id}/generate', '执行已保存的美术方案，可能消耗图像服务额度；同方案只提交一次', 'art_jobs', True),
    action('webui.config', 'images', 'GET', '/webui/config', '已配置的本机 WebUI 状态'),
    action('webui.catalog', 'images', 'GET', '/webui/catalog', '绘画模型和 LoRA 目录'),
    action('webui.refresh', 'images', 'POST', '/webui/refresh', '刷新 WebUI 模型目录', background=True),
    action('webui.outputs', 'images', 'GET', '/webui/outputs', '浏览配置内的绘画产出，query/offset/limit 分页'),
    action('webui.import', 'images', 'POST', '/projects/{pid}/webui/import', '导入配置产出目录内的图片', background=True),
    action('music.jobs', 'music', 'GET', '/projects/{pid}/music', '本机音乐方案与结果'),
    action('music.draft', 'music', 'POST', '/projects/{pid}/music', '保存 SUNO 方案，默认使用项目所选模型，不收费', example={'data': {'title': '探索配乐', 'prompt': '安静木吉他', 'tags': '', 'instrumental': True}}),
    action('music.submit', 'music', 'POST', '/music/jobs/{id}/submit', '按冻结模型提交 SUNO；仅用户已授予 SUNO 自动积分时可调用', 'music_jobs', True, 'suno'),
    action('music.refresh', 'music', 'POST', '/music/jobs/{id}/refresh', '只查询已记录 SUNO 任务，不重新生成', 'music_jobs', True),
    action('music.outputs', 'music', 'GET', '/music/jobs/{id}/outputs', '查看已校验接入的SUNO本地音频资产与哈希', 'music_jobs'),
    action('music.import', 'music', 'POST', '/music/jobs/{id}/import', '将指定成功音轨的免费文件接入排队；使用原编号，不触发生成/转换', 'music_jobs'),
    action('blender.config', 'modeling', 'GET', '/blender/config', '读取 Blender 连接状态'),
    action('blender.jobs', 'modeling', 'GET', '/projects/{pid}/characters', '参数化建模方案与交付'),
    action('blender.draft', 'modeling', 'POST', '/projects/{pid}/characters', '保存参数化角色方案，可含 parent_id'),
    action('blender.build', 'modeling', 'POST', '/characters/{id}/build', '启动固定本机建模驱动；不会执行 Agent 提供的脚本', 'character_jobs'),
    action('blender.cancel', 'modeling', 'POST', '/characters/{id}/cancel', '停止工作台创建的本机生成', 'character_jobs'),
    action('blender.logs', 'modeling', 'GET', '/characters/{id}/logs', '读取本机建模日志', 'character_jobs'),
    action('blender.open', 'modeling', 'POST', '/characters/{id}/open', '在 Blender 打开已有源文件', 'character_jobs'),
    action('tripo.config', 'modeling', 'GET', '/tripo/config', '读取 Tripo 区域/可选模型；不返回 Key'),
    action('tripo.jobs', 'modeling', 'GET', '/projects/{pid}/tripo', 'Tripo 方案与已记录任务'),
    action('tripo.draft', 'modeling', 'POST', '/projects/{pid}/tripo', '保存方案，未指定 model 时使用项目默认；不收费'),
    action('tripo.submit', 'modeling', 'POST', '/tripo/jobs/{id}/submit', '提交冻结方案/参考图；仅用户已授予 Tripo 自动积分时可调用', 'tripo_jobs', True, 'tripo'),
    action('tripo.refresh', 'modeling', 'POST', '/tripo/jobs/{id}/refresh', '查询已存在远端任务，不重新生成', 'tripo_jobs', True),
    action('tripo.recover', 'modeling', 'POST', '/tripo/jobs/{id}/recover', '按已核对 task_id 关联未知结果，不创建远端任务', 'tripo_jobs', True),
    action('tripo.import', 'modeling', 'POST', '/tripo/jobs/{id}/import', '下载校验 GLB 并纳入本项目', 'tripo_jobs', True),
    action('engine.install', 'engine', 'POST', '/projects/{pid}/engine/install', '安装工作台连接器到当前工程', background=True),
    action('engine.command', 'engine', 'POST', '/projects/{pid}/engine/command', '执行已有引擎操作；材质修改仍校验资产/目标/版本', background=True, example={'data': {'op': 'status'}}),
    action('snapshot.list', 'retention', 'GET', '/projects/{pid}/snapshots', '读取工程快照记录'),
    action('snapshot.create', 'retention', 'POST', '/projects/{pid}/snapshots', '保存工程快照；先完成文件写入再调用，明确说明一致性前提', example={'data': {'label': 'Agent检查点', 'note': '变更和验收范围', 'saved_ack': True}}),
    action('snapshot.get', 'retention', 'GET', '/snapshots/{id}', '查看快照保存进度与归档路径', 'project_snapshots'),
    action('snapshot.verify', 'retention', 'POST', '/snapshots/{id}/verify', '逐文件/整包校验', 'project_snapshots', True),
    action('snapshot.restore', 'retention', 'POST', '/snapshots/{id}/restore', '校验后恢复到工程外的新目录，data.parent 为已有父目录', 'project_snapshots', True),
    action('github.config', 'retention', 'GET', '/github/config', 'Git/LFS 和 Token 配置状态；不返回 Token'),
    action('github.list', 'retention', 'GET', '/projects/{pid}/publications', '读取 GitHub 发布记录'),
    action('github.prepare', 'retention', 'POST', '/snapshots/{id}/github/prepare', '生成指定仓库的本机文件预览；data.repository 为 HTTPS GitHub 地址', 'project_snapshots', True),
    action('github.push', 'retention', 'POST', '/publications/{id}/push', '上传已准备快照分支；需 rights_ack 和公开仓库的 public_ack，不覆盖主分支', 'github_publications', True),
    action('github.check', 'retention', 'POST', '/publications/{id}/check', '只读核对未知推送，不自动重推', 'github_publications', True),
    action('accounts.get', 'accounts', 'GET', '/accounts', '读取额度缓存与过期标记'),
    action('accounts.refresh', 'accounts', 'POST', '/accounts/refresh', '只读刷新额度；可用 data.providers 指定服务', background=True),
    action('models.get', 'models', 'GET', '/projects/{pid}/generation-models', '读取用户所选 SUNO/Tripo 默认模型及支持目录'),
    action('conversation.list', 'project', 'GET', '/projects/{pid}/conversations', '读取本项目会话目录，query.agent 选择角色'),
    action('conversation.messages', 'project', 'GET', '/conversations/{id}/messages', '读取本项目会话历史，query.q 可搜索', 'conversations'),
    action('conversation.update', 'project', 'PATCH', '/conversations/{id}', '更新会话名称/记忆或归档，不授予权限', 'conversations'),
    action('conversation.fork', 'project', 'POST', '/conversations/{id}/fork', '复制会话；新会话不继承授权', 'conversations'),
]
BY_NAME = {a['name']: a for a in ACTIONS}
DATA_FIELDS = {
    'context.checkpoint': {'conversation_id': '可选当前项目会话ID；保存其用户维护记忆', 'decisions': '已核对的关键决定和待核实事项，最多20000字符', 'skills': 'Skill使用约定，不含凭据或第三方源码', 'workflow': '可接续的项目流程'},
    'task.draft': {'kind': 'music/art/blender/tripo', 'data': '对应原业务方案参数；仅保存免费草稿，不提交生成'},
    'task.adopt': {'asset_id': '本任务已登记的候选资产ID', 'confirmed': '必须true；采用当前版本并重置todo，不验收'},
    'image.submit_draft': {'confirmed': '全功能调用沿用现有图像生成授权；同描述未核对失败/中断时拒绝自动重提'},
    'jobs.enqueue': {'kind': 'music/tripo', 'id': '当前项目源作业ID', 'command': 'query/import，均不重新生成', 'serial_no': '仅music import必填，必须为此方案已记录编号'},
    'jobs.stop': {'kind': 'operation/chat/blender/snapshot', 'id': '对应当前项目作业ID'},
    'music.import': {'serial_no': '必填，原方案已记录且已成功的音轨编号'},
    'project.update': {'brief': '项目总纲字符串，最多30000字符'},
    'document.create': {'title': '标题', 'content': '正文'},
    'document.update': {'revision': '必填，当前整数版本', 'title': '可选标题', 'content': '可选正文', 'authority': '可选 draft/approved/archived'},
    'task.create': {'deliveries': '可选[{asset_id,version_index,sha256}]，替换当前交付关联；修改已验收依据须先重置todo', 'title': '必填标题', 'detail': '交付/验收说明', 'dependency_ids': '可选任务ID列表', 'document_ids': '可选文档ID列表'},
    'task.update': {'review_token': '有资产交付的done操作必填；先从get_project读取并审阅当前任务', 'deliveries': '可选[{asset_id,version_index,sha256}]，替换当前交付关联；修改已验收依据须先重置todo', 'title': '可选标题', 'detail': '可选说明', 'status': 'todo/running/review/done/blocked/cancelled', 'evidence': 'done 必须有真实验收依据', 'dependency_ids': '可选任务ID列表', 'document_ids': '可选文档ID列表'},
    'asset.import_file': {'path': '必填，本机文件路径'},
    'asset.edit_image': {'expected_hash': '必填，asset.info 返回的 hash', 'width': '可选宽1–8192', 'height': '可选高1–8192', 'flip': '可选布尔', 'crop': '可选[x,y,width,height]整数数组'},
    'asset.edit_audio': {'expected_hash': '必填，当前哈希', 'start': '起点秒数', 'end': '终点秒数', 'fade': '可选布尔，默认短淡入淡出'},
    'asset.restore': {'index': '必填，asset.info.versions 数组内索引'},
    'image.generate': {'provider': 'openai/webui', 'prompt': '必填描述', 'checkpoint': 'WebUI目录返回ID', 'sampler': 'WebUI采样器名称', 'width': 'WebUI尺寸64–2048且8倍数', 'height': '同width', 'steps': '1–100', 'cfg_scale': 'WebUI参数', 'seed': '-1或种子整数', 'negative_prompt': '负面词', 'loras': '[{id:目录ID,weight:权重}]；不手写LoRA标记'},
    'image.edit': {'expected_hash': '必填，原图当前哈希', 'provider': 'openai/webui', 'prompt': '必填描述', 'mask_asset_id': '可选同尺寸透明PNG资产ID', 'denoising_strength': 'WebUI可选0–1；其余参数同image.generate'},
    'webui.import': {'path': '必填，webui.outputs返回的相对路径', 'version': '必填，该输出记录的version'},
    'music.draft': {'title': '必填标题', 'prompt': '必填创作描述', 'tags': '可选风格', 'instrumental': '布尔', 'mv': '可选models.get中的SUNO模型；省略用项目默认'},
    'blender.draft': {'spec': '可省略的参数对象，字段参照draft_character工具schema；默认可生成人形草稿', 'parent_id': '可选同项目原方案ID；使用parent_id时必须含spec'},
    'tripo.draft': {'title': '可选标题', 'mode': 'text/image', 'prompt': 'text必填，image时留空', 'source_asset_id': 'image必填项目图片ID', 'model': '可选，默认项目所选', 'face_limit': '500–100000整数', 'texture': '布尔', 'pbr': '布尔，开启时texture须为true'},
    'tripo.recover': {'task_id': '必填，已人工核对的task_编号，不创建新任务'},
    'engine.command': {'op': 'status/list_assets/inspect/preview/set_material_color', 'path': 'inspect/preview/材质操作需当前工程的引擎目标', 'name': '材质参数名称', 'color': '材质RGBA四元组，0–1', 'asset_id': '材质操作必填项目资产ID', 'expected_hash': '材质操作必填当前哈希'},
    'snapshot.create': {'label': '必填快照名', 'note': '必填变更和验收说明', 'kind': 'checkpoint/milestone/pre_publish', 'saved_ack': '必须true；先保存工程并暂停写入', 'destination': '可选工程外备份目录'},
    'snapshot.restore': {'parent': '必填，工程外已有父目录；总是恢复到新目录'},
    'github.prepare': {'repository': '必填https://github.com/owner/repo', 'include_assets': '布尔，默认true', 'exclude': '可选预览相对文件路径数组'},
    'github.push': {'rights_ack': '必须true；先核对文件与上传权利', 'public_ack': '公开仓库必须true；先核对目标及公开范围'},
    'accounts.refresh': {'providers': '可选codex/suno/tripo/deepseek/openai数组'},
    'conversation.update': {'title': '可选名称', 'memory': '可选会话记忆', 'archived': '可选布尔；不授予权限'},
}
QUERY_FIELDS = {'webui.catalog': {'live': '可选布尔'}, 'webui.outputs': {'query': '检索词', 'offset': '偏移', 'limit': '每页数量'},
                'context.preview': {'conversation_id': '可选当前项目会话ID', 'mode': 'auto/compact'},
                'jobs.list': {'kind': '可选music/art/blender/tripo/snapshot/publication/chat/operation', 'state': '可选queued/running/succeeded/failed/unknown/needs_user/cancelled/interrupted', 'q': '标题搜索', 'offset': '偏移', 'limit': '1–100'},
                'jobs.inspect': {'kind': '必填来源类型', 'id': '必填当前项目作业ID'},
                'conversation.list': {'agent': 'director/music/modeler', 'archived': '布尔'}, 'conversation.messages': {'q': '可选检索词'}}


def catalog(grant, group=''):
    return [{k: a[k] for k in ('name', 'group', 'description', 'target', 'background', 'cost', 'example')}
            | {'allowed': bool(grant.get('full') and (not a['cost'] or grant.get(a['cost']))),
               'input_contract': {'target_id': '必填，当前项目内的' + a['target'] + '记录ID' if a['target'] else '不需要',
                                  'data': DATA_FIELDS.get(a['name'], {}), 'query': QUERY_FIELDS.get(a['name'], {})}}
            for a in ACTIONS if not group or a['group'] == group]


def checked(scope, name, inputs):
    grant = permissions.effective(scope)
    if not grant['full']: raise ValueError('此会话未获工作台全功能授权，或当前为讨论模式')
    spec = BY_NAME.get(name)
    if not spec or not isinstance(inputs, dict) or set(inputs) - {'target_id', 'data', 'query'}: raise ValueError('未知操作或输入字段无效，请先查询操作目录')
    if any(not isinstance(inputs.get(k, {}), dict) for k in ('data', 'query')): raise ValueError('data 和 query 必须为 JSON 对象')
    if spec['cost'] and not grant[spec['cost']]: raise ValueError('用户未授权自由消耗 ' + spec['cost'] + ' 积分，请保存方案交由用户确认')
    if spec['target']:
        target = inputs.get('target_id')
        if not isinstance(target, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', target): raise ValueError('请选择当前项目内的有效目标 ID')
        row = store.one(f"SELECT * FROM {spec['target']} WHERE id=? AND project_id=?", (target, scope['pid']))
        if not row: raise ValueError('操作目标不属于当前项目')
        if name == 'image.submit_draft':
            wanted = json.loads(row['spec'])
            for other in store.rows("SELECT provider,spec FROM art_jobs WHERE project_id=? AND status IN ('failed','interrupted')", (scope['pid'],)):
                if other['provider'] == row['provider'] and json.loads(other['spec']).get('prompt') == wanted.get('prompt'):
                    raise ValueError('同描述美术请求存在未核对失败/中断结果，请用户先核对服务记录，不自动重提')
        if spec['cost']:
            original = json.loads(row['spec']); original.pop('title', None)
            for other in store.rows(f"SELECT spec FROM {spec['target']} WHERE project_id=? AND status='unknown'", (scope['pid'],)):
                previous = json.loads(other['spec']); previous.pop('title', None)
                if previous == original: raise ValueError('同参数任务存在未知结果，禁止自动新建方案重提；请先人工核对')
    return spec, grant


def public_result(value):
    if isinstance(value, dict):
        if value.get('type') == 'open_url': return {'type': 'user_action_required', 'message': '请在对应工作区完成登录或账户处理'}
        return {k: public_result(v) for k, v in value.items() if not re.search(r'authorization|credential|password|api_key|secret|access_token|refresh_token', k, re.I)}
    if isinstance(value, list): return [public_result(v) for v in value]
    return value


async def dispatch(scope, spec, inputs):
    from .app import app, CSRF
    checked(scope, spec['name'], inputs)
    pid = scope['pid']
    if spec['method'] == 'EXPORT':
        path = await asyncio.to_thread(backup.write, pid)
        return {'path': str(path), 'download_url': f'/api/projects/{pid}/export', 'note': '格式10工作台资料包，不是完整工程快照'}
    path = '/api' + spec['path'].format(pid=pid, id=inputs.get('target_id', ''))
    body = dict(inputs.get('data', {}))
    if spec['name'] in ('jobs.enqueue', 'music.import'):
        from . import jobs
        values = body if spec['name'] == 'jobs.enqueue' else {'kind': 'music', 'id': inputs['target_id'], 'command': 'import', **body}
        if values.get('command') == 'import': values['confirmed'] = True
        return jobs.enqueue(pid, values, scope)
    if spec['name'] in ('music.submit', 'tripo.submit', 'blender.build', 'snapshot.restore', 'tripo.recover', 'github.push', 'image.submit_draft'): body['confirmed'] = True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1', timeout=None, trust_env=False) as client:
        headers = {'x-workbench-token': CSRF}
        if spec['method'] == 'UPLOAD':
            source = Path(body.get('path', '')).expanduser().resolve()
            grant = permissions.effective(scope)
            if not grant['computer']:
                try: assets.authorized_path(pid, source)
                except ValueError: raise ValueError('工作台授权仅导入当前工程文件；工程外文件需用户上传或 Codex 整机授权') from None
            if not source.is_file() or source.stat().st_size > 59 * 1024 ** 2: raise ValueError('请选择 59 MiB 内的普通文件')
            response = await client.post(path, files={'file': (source.name, source.read_bytes())}, headers=headers)
        else:
            response = await client.request(spec['method'], path, json=body if spec['method'] != 'GET' else None,
                                            params=inputs.get('query', {}), headers=headers)
    if response.status_code >= 400:
        try: detail = response.json().get('detail')
        except ValueError: detail = None
        raise ValueError(detail if isinstance(detail, str) else '工作台操作未完成，请核对执行记录；未自动重试')
    return public_result(response.json())


async def call(scope, name, inputs):
    spec, grant = checked(scope, name, inputs)
    if not spec['background']: return await dispatch(scope, spec, inputs)
    rid = store.run_start(scope['pid'], 'agent_action:' + name, 'Agent 工作台操作：' + spec['description'], scope['conversation_id'], agent=scope['agent'])
    context = {'action': name, 'parent_run_id': scope.get('run_id'), 'grant_version': grant['version'], 'target_id': inputs.get('target_id')}
    async def worker():
        status, detail = 'completed', '工作台操作已完成；生成/上传还需依据返回状态核对'
        try:
            result = await dispatch(scope, spec, inputs)
            if len(json.dumps(result, ensure_ascii=False)) > 1000000:
                from .agent_tools import summary
                result = {'truncated': True, 'summary': summary(result), 'note': '大结果请在对应工作区或分页接口查看'}
            context['result'] = result
        except BaseException as exc:
            status = 'interrupted' if isinstance(exc, asyncio.CancelledError) else 'failed'
            detail = str(exc)[:500] if isinstance(exc, ValueError) else '操作中断或连接异常；请核对任务，未自动重试'
            context['error'] = detail
        finally:
            store.execute('UPDATE runs SET runtime=? WHERE id=?', (json.dumps(context, ensure_ascii=False), rid))
            store.run_end(rid, status, detail)
            RUNNING.pop(rid, None)
    store.execute('UPDATE runs SET runtime=? WHERE id=?', (json.dumps(context), rid))
    RUNNING[rid] = {'conversation_id': scope['conversation_id'], 'parent_run_id': scope.get('run_id'), 'task': asyncio.create_task(worker())}
    def ended(task):
        if rid in RUNNING:
            store.execute('UPDATE runs SET runtime=? WHERE id=?', (json.dumps({**context, 'error': '操作启动前已取消，未自动重试'}), rid))
            store.run_end(rid, 'interrupted', '操作启动前已取消')
            RUNNING.pop(rid, None)
    RUNNING[rid]['task'].add_done_callback(ended)
    return {'operation_id': rid, 'status': 'running', 'note': '操作已登记，请使用 workbench_operation 核对返回结果，不要重复提交'}


async def operation(scope, rid, wait_seconds=0):
    if not permissions.effective(scope)['full']: raise ValueError('请在执行模式使用已授权的全功能会话')
    row = store.one("SELECT * FROM runs WHERE id=? AND project_id=? AND kind LIKE 'agent_action:%'", (rid, scope['pid']))
    if not row: raise ValueError('执行编号不属于当前项目')
    if type(wait_seconds) is not int or not 0 <= wait_seconds <= 10: raise ValueError('单次等待需为0–10秒')
    if rid in RUNNING and wait_seconds: await asyncio.wait({RUNNING[rid]['task']}, timeout=wait_seconds)
    permissions.effective(scope)
    row = store.one('SELECT * FROM runs WHERE id=?', (rid,))
    return {'operation_id': rid, 'status': row['status'], 'detail': row['detail'], **json.loads(row['runtime'])}


def revoke(cid):
    for value in list(RUNNING.values()):
        if value['conversation_id'] == cid: value['task'].cancel()


def cancel_run(rid):
    for value in list(RUNNING.values()):
        if value['parent_run_id'] == rid: value['task'].cancel()


async def shutdown():
    tasks = [v['task'] for v in RUNNING.values()]
    for task in tasks: task.cancel()
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)
