"""Task dependencies and the document revisions used for acceptance."""
import hashlib
import json
from . import deliveries, store


STATUSES = ('todo', 'running', 'review', 'done', 'blocked', 'cancelled')


def id_list(value):
    if not isinstance(value, list) or len(value) > 200 or any(not isinstance(v, str) for v in value):
        raise ValueError('关联项必须为 ID 列表，最多 200 项')
    return list(dict.fromkeys(value))


def set_links(c, tid, pid, data):
    if 'deliveries' in data: deliveries.bind(c, tid, pid, data['deliveries'])
    if 'dependency_ids' in data:
        ids = id_list(data['dependency_ids'])
        for dep in ids:
            row = c.execute('SELECT project_id FROM tasks WHERE id=?', (dep,)).fetchone()
            if not row or row['project_id'] != pid:
                raise ValueError('依赖任务必须属于同一项目')
        graph = {}
        for row in c.execute('SELECT d.task_id,d.depends_on FROM task_dependencies d JOIN tasks t ON d.task_id=t.id WHERE t.project_id=?', (pid,)):
            graph.setdefault(row['task_id'], []).append(row['depends_on'])
        graph[tid] = ids
        pending, visited = ids[:], set()
        while pending:
            current = pending.pop()
            if current == tid:
                raise ValueError('任务不能依赖自身或形成循环依赖')
            if current not in visited:
                visited.add(current)
                pending.extend(graph.get(current, []))
        c.execute('DELETE FROM task_dependencies WHERE task_id=?', (tid,))
        c.executemany('INSERT INTO task_dependencies VALUES (?,?)', [(tid, dep) for dep in ids])
    if 'document_ids' in data:
        pins = []
        for did in id_list(data['document_ids']):
            doc = c.execute('SELECT project_id,revision FROM documents WHERE id=?', (did,)).fetchone()
            if not doc or doc['project_id'] != pid:
                raise ValueError('关联文档必须属于同一项目')
            pins.append((tid, did, doc['revision']))
        c.execute('DELETE FROM task_documents WHERE task_id=?', (tid,))
        c.executemany('INSERT INTO task_documents VALUES (?,?,?)', pins)


def invalidate(c, ids, reason):
    """Keep downstream acceptance invalid until that task is explicitly reopened."""
    downstream = {}
    for row in c.execute('SELECT * FROM task_dependencies'):
        downstream.setdefault(row['depends_on'], []).append(row['task_id'])
    pending, seen = list(ids), set()
    while pending:
        tid = pending.pop()
        if tid in seen:
            continue
        seen.add(tid)
        c.execute('''INSERT OR REPLACE INTO task_reviews SELECT id,?,? FROM tasks
                     WHERE id=? AND status IN ('running','review','done')''', (reason, store.now(), tid))
        pending.extend(downstream.get(tid, []))


def document_changed(c, did):
    ids = [r['task_id'] for r in c.execute('SELECT task_id FROM task_documents WHERE doc_id=?', (did,))]
    invalidate(c, ids, '设计依据或上游依据发生变化，请重新安排并验收')


def list_tasks(pid, c=None):
    if c is None:
        with store.db() as connection:
            return list_tasks(pid, connection)
    tasks = [dict(r) for r in c.execute('SELECT * FROM tasks WHERE project_id=? ORDER BY created', (pid,))]
    by_id = {t['id']: t for t in tasks}
    for t in tasks:
        t.update(dependency_ids=[], document_links=[], asset_links=[], issues=[], review_required=False)
    asset_links = deliveries.links(pid, c)
    changed = [tid for tid, links in asset_links.items() if any(l['changed'] for l in links)]
    reviewed = {r['task_id'] for r in c.execute('SELECT task_id FROM task_reviews')}
    if set(changed) - reviewed: invalidate(c, set(changed) - reviewed, '资产交付版本或文件内容变化，请重新核对并验收')
    for tid, links in asset_links.items(): by_id[tid]['asset_links'] = links
    for row in c.execute('SELECT r.* FROM task_reviews r JOIN tasks t ON r.task_id=t.id WHERE t.project_id=?', (pid,)):
        by_id[row['task_id']]['review_required'] = True
    for row in c.execute('SELECT d.* FROM task_dependencies d JOIN tasks t ON d.task_id=t.id WHERE t.project_id=?', (pid,)):
        by_id[row['task_id']]['dependency_ids'].append(row['depends_on'])
    for row in c.execute('''SELECT l.*,d.title,d.revision AS current_revision,d.authority
                            FROM task_documents l JOIN documents d ON l.doc_id=d.id
                            JOIN tasks t ON l.task_id=t.id WHERE t.project_id=?''', (pid,)):
        link = dict(row)
        link['changed'] = link['revision'] != link['current_revision']
        by_id[row['task_id']]['document_links'].append(link)
    for t in tasks:
        pending, seen = [t['id']], set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            item = by_id[current]
            if item['review_required']:
                t['issues'].append('交付需重新复核：' + item['title'])
            if current != t['id'] and item['status'] != 'done':
                t['issues'].append('前置任务未完成：' + item['title'])
            for link in item['document_links']:
                if link['changed'] or link['authority'] == 'archived':
                    t['issues'].append('设计依据需复核：' + link['title'] + '（任务：' + item['title'] + '）')
            for link in item['asset_links']:
                if link['changed']: t['issues'].append('资产交付需复核：' + link['name'] + '（任务：' + item['title'] + '）')
            pending.extend(item['dependency_ids'])
        t['ready'] = not t['issues']
        reviewed = {k: t[k] for k in ('title', 'detail', 'status', 'evidence', 'dependency_ids', 'document_links', 'asset_links', 'issues')}
        t['review_token'] = hashlib.sha256(json.dumps(reviewed, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return tasks


def create(pid, data):
    store.project(pid)
    tid = store.uid()
    title, detail = str(data.get('title', '')).strip(), str(data.get('detail', ''))
    if not title or len(title) > 180 or len(detail) > 10000:
        raise ValueError('任务标题为空或内容过长')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?)', (tid, pid, title, 'todo', detail, '', store.now()))
        set_links(c, tid, pid, data)
    return next(t for t in list_tasks(pid) if t['id'] == tid)


def update(tid, data):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone()
        if not row:
            raise ValueError('任务不存在')
        task = dict(row)
        status, evidence = data.get('status', task['status']), str(data.get('evidence', task['evidence']))
        title, detail = str(data.get('title', task['title'])).strip(), str(data.get('detail', task['detail']))
        if status not in STATUSES or not title or len(title) > 180 or len(detail) > 10000 or len(evidence) > 10000:
            raise ValueError('任务内容或状态无效')
        if status == 'done' and not evidence.strip():
            raise ValueError('请填写验收依据，再标记完成')
        before = (list(c.execute('SELECT depends_on FROM task_dependencies WHERE task_id=? ORDER BY depends_on', (tid,))),
                  list(c.execute('SELECT doc_id,revision FROM task_documents WHERE task_id=? ORDER BY doc_id', (tid,))),
                  list(c.execute('SELECT asset_id,version_index,sha256 FROM task_deliveries WHERE task_id=? ORDER BY asset_id', (tid,))))
        set_links(c, tid, task['project_id'], data)
        after = (list(c.execute('SELECT depends_on FROM task_dependencies WHERE task_id=? ORDER BY depends_on', (tid,))),
                 list(c.execute('SELECT doc_id,revision FROM task_documents WHERE task_id=? ORDER BY doc_id', (tid,))),
                 list(c.execute('SELECT asset_id,version_index,sha256 FROM task_deliveries WHERE task_id=? ORDER BY asset_id', (tid,))))
        if before != after or detail != task['detail']:
            invalidate(c, [tid], '任务依据或验收条件已调整，请重新验收')
        if status == 'todo':
            c.execute('DELETE FROM task_reviews WHERE task_id=?', (tid,))
        if task['status'] == 'done' and status != 'done':
            dependents = [r['task_id'] for r in c.execute('SELECT task_id FROM task_dependencies WHERE depends_on=?', (tid,))]
            invalidate(c, dependents, '上游任务已重新安排，请重新验收本任务')
        current = next(t for t in list_tasks(task['project_id'], c) if t['id'] == tid)
        if status in ('running', 'review', 'done') and not current['ready']:
            raise ValueError('任务受阻：' + '；'.join(current['issues']))
        if status == 'done':
            if current['asset_links'] and data.get('review_token') != current['review_token']: raise ValueError('验收页面或交付依据已变化，请重新读取任务、审阅具体版本后再确认')
            deliveries.accept(c, current, evidence)
        c.execute('UPDATE tasks SET title=?,detail=?,status=?,evidence=? WHERE id=?', (title, detail, status, evidence, tid))
    return next(t for t in list_tasks(task['project_id']) if t['id'] == tid)
