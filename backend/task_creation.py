"""Free task-scoped drafts and candidate outputs, separate from accepted deliveries."""
from . import assets, image_jobs, jobs, modeling, music, store, tripo


def task(tid, pid=None):
    row = store.one('SELECT * FROM tasks WHERE id=?', (tid,))
    if not row or pid and row['project_id'] != pid: raise ValueError('任务不属于当前项目')
    return row


def create(tid, data):
    current = task(tid)
    if not isinstance(data, dict) or set(data) != {'kind', 'data'} or not isinstance(data['data'], dict): raise ValueError('请选择创作类型及方案参数')
    kind, parameters = data['kind'], data['data']
    if kind not in ('music', 'art', 'blender', 'tripo'): raise ValueError('创作类型无效')
    if current['status'] in ('done', 'cancelled'): raise ValueError('请先将任务重新安排为待执行，再创建新方案')
    if kind == 'music': source = music.draft(current['project_id'], parameters)
    elif kind == 'blender': source = modeling.draft(current['project_id'], parameters)
    elif kind == 'tripo': source = tripo.draft(current['project_id'], parameters)
    else: source = image_jobs.draft(current['project_id'], {**parameters, 'title': current['title'][:100]})
    store.execute('INSERT INTO task_creations VALUES (?,?,?,?,?,?)', (store.uid(), current['project_id'], tid, kind, source['id'], store.now()))
    return {'kind': kind, 'id': source['id'], 'task_id': tid, 'status': 'draft', 'note': '仅保存方案，尚未生成或消耗生成积分；产出将回到此任务的候选列表，仍需选择版本并验收'}


def list_for(tid):
    current = task(tid)
    result = []
    for row in store.rows('SELECT * FROM task_creations WHERE task_id=? ORDER BY created DESC', (tid,)):
        value = jobs.inspect(current['project_id'], row['kind'], row['job_id'])
        result.append({**row, 'title': value['title'], 'status': value['details']['status'], 'spec': value['details'].get('spec', {}), 'outputs': value['outputs']})
    return result


def adopt(tid, aid):
    from . import deliveries, tasks
    current = task(tid)
    candidates = {o['asset_id'] for row in list_for(tid) for o in row['outputs']}
    if not isinstance(aid, str): raise ValueError('候选资产编号无效')
    if aid not in candidates: raise ValueError('此资产不是当前任务已登记的候选产出')
    a = assets.asset(aid)
    version = deliveries.version(a)
    old = next(t for t in tasks.list_tasks(current['project_id']) if t['id'] == tid)
    pins = [{k: v[k] for k in ('asset_id', 'version_index', 'sha256')} for v in old['asset_links'] if v['asset_id'] != aid]
    return tasks.update(tid, {'status': 'todo', 'deliveries': [*pins, {'asset_id': aid, 'version_index': version['version_index'], 'sha256': version['sha256']}]})
