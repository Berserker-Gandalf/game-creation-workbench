"""Small workspace payloads and database-paged asset/document catalogs."""
import json

from . import store


def page(pid, section, query='', kind='', category='', offset=0, limit=48, before=0, handoff=False, preview=False, approved_first=False):
    store.project(pid)
    if section not in ('assets', 'documents', 'tasks'): raise ValueError('目录分类无效')
    if any(type(v) is not int or v < 0 for v in (offset, before)) or type(limit) is not int or not 1 <= limit <= 100: raise ValueError('分页范围无效')
    if before and offset: raise ValueError('请使用游标或页偏移其中一种分页方式')
    if any(not isinstance(v, str) or len(v) > 200 for v in (query, kind, category)): raise ValueError('目录筛选无效')
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    args, where = [pid], ['a.project_id=?']
    prefix, join = '', ''
    if section == 'assets':
        prefix = '''WITH inventory AS MATERIALIZED (
            SELECT json_extract(f.value,'$.asset_id') AS aid, json_extract(f.value,'$.category') AS category,
                   json_extract(f.value,'$.path') AS relative_path, json_extract(f.value,'$.status') AS source_status
            FROM project_intakes p,json_each(p.files) f WHERE p.project_id=?) '''
        args.insert(0, pid)
        join = ' LEFT JOIN inventory i ON i.aid=a.id '
        fields = 'a.id,a.name,a.kind,a.source,a.active,a.created,i.category,i.relative_path,i.source_status'
        if kind: where.append('a.kind=?'); args.append(kind)
        if category: where.append('i.category=?'); args.append(category)
        if query: where.append("(a.name LIKE ? ESCAPE '\\' OR i.relative_path LIKE ? ESCAPE '\\')"); args += [pattern, pattern]
    elif section == 'documents':
        fields = 'a.id,a.title,a.revision,a.authority,a.updated,length(a.content) AS chars'
        if preview: fields += ',substr(a.content,1,4000) AS content_excerpt'
        if query: where.append("(a.title LIKE ? ESCAPE '\\' OR a.content LIKE ? ESCAPE '\\')"); args += [pattern, pattern]
        if handoff: where.append("(a.title LIKE 'PROJECT_MEMORY.md · %' OR a.title LIKE 'SKILLS.md · %' OR a.title LIKE 'WORKFLOW.md · %')")
    else:
        fields = 'a.id,a.title,a.status'
        if query: where.append("a.title LIKE ? ESCAPE '\\'"); args.append(pattern)
    # COUNT reads no document bodies into Python. Rowid cursors avoid offset shifts on insert/delete.
    sql = prefix + f'SELECT COUNT(*) AS n FROM {section} a' + join + ' WHERE ' + ' AND '.join(where)
    total = store.one(sql, args)['n']
    if before: where.append('a.rowid<?'); args.append(before)
    sql = prefix + f'SELECT a.rowid AS _cursor,{fields} FROM {section} a' + join + ' WHERE ' + ' AND '.join(where)
    order = "(a.authority!='approved'),a.rowid DESC" if approved_first and section == 'documents' else 'a.rowid DESC'
    values = store.rows(sql + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?', (*args, limit + 1, offset))
    more = len(values) > limit
    values = values[:limit]
    cursor = values[-1]['_cursor'] if values and more else None
    for value in values: value.pop('_cursor')
    return {'items': values, 'total': total, 'offset': offset, 'next_offset': offset + len(values) if more else None,
            'next_before': cursor, 'limit': limit, 'as_of': store.now(),
            'note': '按登记顺序分页；继续使用next_before避免新登记记录挤动页面。筛选或刷新后从第一页开始，目录不是不可变快照。'}


def document(pid, did):
    value = store.one('SELECT * FROM documents WHERE project_id=? AND id=?', (pid, did))
    if not value: raise ValueError('文档不属于当前项目')
    return value


def workspace(pid):
    project = store.project(pid)
    counts = {name: store.one(f'SELECT COUNT(*) AS n FROM {name} WHERE project_id=?', (pid,))['n'] for name in ('documents', 'assets', 'tasks')}
    counts['marked_done'] = store.one("SELECT COUNT(*) AS n FROM tasks WHERE project_id=? AND status='done'", (pid,))['n']
    row = store.one('SELECT summary_document_id,report,updated FROM project_intakes WHERE project_id=?', (pid,))
    imported = {**row, 'report': json.loads(row['report'])} if row else None
    return {'project': project, 'documents': [], 'assets': [], 'tasks': [], 'messages': [], 'intake': imported,
            'runs': store.rows('''SELECT id,project_id,kind,status,substr(detail,1,500) AS detail,created,updated,
                conversation_id,provider,model,agent FROM runs WHERE project_id=? ORDER BY created DESC,rowid DESC LIMIT 30''', (pid,)),
            'counts': counts, 'as_of': store.now(), 'note': '首屏计数不执行任务交付复核；有效验收以任务看板的完整核对为准。'}
