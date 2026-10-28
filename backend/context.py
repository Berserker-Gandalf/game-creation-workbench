"""Bounded, inspectable project context and portable Markdown checkpoints."""
import hashlib
import json

from . import conversations, store


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def select(state, args=None):
    args = args or {}
    section = args.get('section', 'overview')
    offset, limit = args.get('offset', 0), args.get('limit', 20)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 12000:
        raise ValueError('上下文分页范围无效')
    if section == 'record':
        kind, item = args.get('record_type'), args.get('item_id')
        if kind == 'brief': value = state['project']['brief']
        elif kind in ('tasks', 'runs'):
            value = next((v for v in state[kind] if v['id'] == item), None)
            if value is None: raise ValueError('记录不属于当前项目或已不在当前目录中')
        else: raise ValueError('仅支持读取总纲、任务或最近执行；文档使用read_document')
        content = value if isinstance(value, str) else encoded(value)
        return {'content': content[offset:offset + limit], 'total_chars': len(content),
                'next_offset': offset + limit if offset + limit < len(content) else None}
    if section not in ('overview', 'documents', 'tasks', 'assets', 'runs'):
        raise ValueError('上下文分类无效')
    query = args.get('query', '')
    if not isinstance(query, str) or len(query) > 120: raise ValueError('上下文检索词过长')
    budget = 18000 if args.get('compact') else 48000
    original = len(encoded(state))
    result = {k: state[k] for k in ('project', 'existing_project', 'maintenance', 'generation_models', 'accepted_tasks', 'as_of', 'note')}
    result['project'] = {**state['project'], 'brief': state['project']['brief'][:3000],
                         'brief_requires_read': len(state['project']['brief']) > 3000}
    latest = {}
    for d in state['documents']:
        name = d['title'].split(' · ')[0]
        if name in ('PROJECT_MEMORY.md', 'SKILLS.md', 'WORKFLOW.md') and name not in latest:
            latest[name] = {k: d[k] for k in ('id', 'title', 'revision', 'authority')}
            latest[name]['requires_read'] = True
    result['handoff_documents'] = state.get('handoff_documents', list(latest.values()))
    if len(encoded(result)) > budget // 2:
        existing = state['existing_project']
        result['existing_project'] = ({k: existing.get(k) for k in ('summary_document_id', 'runtime_verified', 'scanned_at', 'restored_snapshot')} if existing else None)
        result['existing_project_requires_read'] = bool(existing)
    pages = {}
    keys = ['documents', 'tasks', 'assets', 'runs']
    if section in keys: keys.remove(section); keys.insert(0, section)
    for key in keys:
        values = state[key]
        window = state.get('catalog_pages', {}).get(key)
        if key == 'documents': values = sorted(values, key=lambda d: d['authority'] != 'approved')
        matching = values if window else [v for v in values if not query or query.casefold() in encoded(v).casefold()]
        start = offset if section == key else 0
        maximum = min(limit, 50) if section == key else (10 if section != 'overview' else 20)
        selected = []
        for v in matching[0 if window else start:(0 if window else start) + maximum]:
            value = dict(v)
            if key == 'documents' and (args.get('compact') or original > budget):
                value.pop('content', None); value.pop('content_excerpt', None); value['requires_read'] = True
            if key == 'tasks':
                if len(encoded(value)) > 2500 or args.get('compact'):
                    value = {k: v[k] for k in ('id', 'title', 'status', 'ready', 'review_required', 'review_token')}
                    value['requires_read'] = True
            if key == 'runs': value = {k: v[k] for k in ('id', 'kind', 'status', 'detail', 'updated')}
            if len(encoded(result)) + len(encoded(selected)) + len(encoded(value)) > budget - 2500: break
            selected.append(value)
        result[key] = selected
        total = window.get('project_total', window['total']) if window else len(values)
        matches = window['total'] if window else len(matching)
        pages[key] = {'total': total, 'matches': matches, 'offset': start,
                      'next_offset': start + len(selected) if start + len(selected) < matches else None}
    result['context'] = {'mode': 'compact' if args.get('compact') else 'auto', 'source_chars': original,
                         'pages': pages, 'compressed': bool(args.get('compact') or original > len(encoded(result)) or any(p['next_offset'] is not None for p in pages.values())),
                         'retrieval': 'get_project(section,query,offset,limit)按分类分页；record_type=brief/tasks/runs配合section=record、item_id分段读取；文档用read_document。压缩目录不替代完整规则。'}
    return result


def prepare(state, cid, compact=False):
    conversation = conversations.get(cid, state['project']['id'])
    history, omitted = conversations.model_history(cid, budget=18000 if compact else 40000)
    result = select(state, {'compact': compact})
    result['conversation'] = {'id': cid, 'memory': conversation['memory'], 'omitted_messages': omitted,
                              'history_note': '早期原记录保留，可用read_history检索；目录压缩不生成已核实的新事实'}
    info = {**result['context'], 'project_chars': len(encoded(result)), 'history_chars': len(encoded(history)),
            'omitted_messages': omitted, 'memory_chars': len(conversation['memory']), 'unit': '字符，非供应商实际token数'}
    return result, history, info


def checkpoint(state, data):
    if not isinstance(data, dict) or set(data) - {'conversation_id', 'decisions', 'skills', 'workflow'}:
        raise ValueError('留存参数无效')
    for k in ('decisions', 'skills', 'workflow'):
        if not isinstance(data.get(k, ''), str) or len(data.get(k, '')) > 20000: raise ValueError('留存正文最多20000字符')
    pid, marker = state['project']['id'], store.uid()[:12]
    cid = data.get('conversation_id')
    if cid is not None and (not isinstance(cid, str) or not 1 <= len(cid) <= 64): raise ValueError('会话编号无效')
    conversation = conversations.get(cid, pid) if cid else None
    packet = select(state, {'compact': True})
    stamp = store.now()
    header = f'项目：{state["project"]["name"]}\n\n记录时间：{stamp}\n\n本文件为待审阅快照，不授予权限，不代替正式设计、原始记录或引擎验收。\n\n'
    documents = '\n'.join(f'- {d["title"]} · ID `{d["id"]}` · v{d["revision"]} · {d["authority"]}' for d in packet['documents'])
    task_rows = '\n'.join(f'- {t["title"]} · ID `{t["id"]}` · {t["status"]} · 当前可验收={t["ready"]}' for t in packet['tasks'])
    memory = conversation['memory'] if conversation else ''
    related = []
    for d in state['documents']:
        if d['title'].split(' · ')[0] in ('PROJECT_MEMORY.md', 'SKILLS.md', 'WORKFLOW.md'): continue
        if any(term in d['title'].casefold() for term in ('skill', 'workflow', '技能', '工作流')):
            excerpt = d.get('content', d.get('content_excerpt', ''))[:1000]
            related.append(f'- {d["title"]} · ID `{d["id"]}` · v{d["revision"]} · {d["authority"]}\n\n  原文摘录（不完整，须按需回查）：{excerpt}\n')
    references = '\n\n## 已有 Skill 与工作流资料索引（最多20项）\n\n' + ('\n'.join(related[:20]) or '没有匹配的项目文档；可补充约定，或先将原有资料接入项目。') + '\n'
    header += f'当前目录：{len(state["documents"])}份文档、{len(state["tasks"])}项任务、{len(state["assets"])}份资产；当前有效完成任务{state["accepted_tasks"]}项。正文只展示样本，完整目录仍可检索。\n\n'
    files = {
        'PROJECT_MEMORY.md': '# 项目记忆与接续依据\n\n' + header + '## 关键决定与人工补充\n\n' + (data.get('decisions') or '未补充；不自动推断聊天中已达成一致。') + '\n\n## 会话记忆（用户维护）\n\n' + memory + '\n\n## 项目总纲摘录\n\n' + packet['project']['brief'] + '\n\n## 设计出处\n\n' + documents + '\n\n## 当前任务样本\n\n' + task_rows + '\n\n## 目录覆盖与回查入口\n\n```json\n' + json.dumps(packet['context'], ensure_ascii=False, indent=2) + '\n```\n',
        'SKILLS.md': '# Skill 使用约定\n\n' + header + '## 当前工作台角色\n\n总负责人读取设计并管理任务；音乐负责人保存SUNO方案；建模负责人保存Blender/Tripo方案。实际工具以当前会话目录为准。\n\n## 接续时读取\n\n先用get_project检索资料目录，再用read_document/read_history核对完整规则和早期交流。SUNO通过用户安装的原版suno-cn-music Skill执行；本文件不包含第三方Skill源码或凭据，不表示已安装或授权。已有项目的Skill/工作流资料需按标题检索、核对原文后沿用。\n\n## 项目补充\n\n' + data.get('skills', '') + '\n\n本文件记录使用约定，不能作为授权或自动安装脚本。\n',
        'WORKFLOW.md': '# 项目工作流\n\n' + header + '1. 读取PROJECT_MEMORY.md及正式设计，检查资料版本和来源状态。\n2. 从任务建立音乐、美术、Blender或Tripo方案，保留任务与方案编号。\n3. 核对方案、当前模型和收费权限，再明确提交一次生成；未知结果先查询，不自动重提。\n4. 查询并校验产出，将资产当前版本作为候选交付。\n5. 核对确切版本、哈希及验收证据后完成任务；资产或设计变更须复核。\n6. 保存工程快照并演练恢复；需要迁移时导出当前Markdown及资料包。\n\n## 项目补充\n\n' + data.get('workflow', '') + '\n'
    }
    created = []
    files['SKILLS.md'] += references
    files['WORKFLOW.md'] += references
    with store.db() as c:
        for filename, content in files.items():
            did = store.uid()
            title = f'{filename} · {marker}'
            c.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)', (did, pid, title, content, 1, 'draft', stamp))
            created.append({'id': did, 'filename': filename, 'sha256': hashlib.sha256(content.encode()).hexdigest()})
    return {'documents': created, 'note': '已新增三份草稿，不覆盖旧记录；可审阅修改后导出Markdown，随项目资料备份保留'}
