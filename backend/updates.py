"""Section fingerprints avoid returning unchanged project bodies during local polling."""
import hashlib
import json

from . import intake, store, tasks


def conditional(value, request):
    from fastapi.responses import JSONResponse, Response
    fingerprint = {k: v for k, v in value.items() if k != 'as_of'} if isinstance(value, dict) else value
    etag = '"' + hashlib.sha256(json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode()).hexdigest() + '"'
    headers = {'ETag': etag, 'Cache-Control': 'private, no-cache'}
    return Response(status_code=304, headers=headers) if request.headers.get('if-none-match') == etag else JSONResponse(value, headers=headers)


def read(pid, sections, since):
    store.project(pid)
    names = sections.split(',')
    allowed = {'project', 'tasks', 'assets', 'documents', 'runs'}
    if not names or len(names) > 5 or len(set(names)) != len(names) or any(n not in allowed for n in names): raise ValueError('刷新分类无效')
    if len(since) > 1000: raise ValueError('刷新游标过长')
    try: cursors = json.loads(since)
    except ValueError: raise ValueError('刷新游标无效') from None
    if not isinstance(cursors, dict) or any(k not in allowed or not isinstance(v, str) or len(v) != 64 for k, v in cursors.items()): raise ValueError('刷新游标无效')
    changed, current = {}, {}
    for name in names:
        if name == 'project': value = store.project(pid)
        elif name == 'tasks': value = tasks.list_tasks(pid)
        elif name == 'runs': value = store.rows('SELECT * FROM runs WHERE project_id=? ORDER BY created DESC LIMIT 30', (pid,))
        else:
            order = 'updated' if name == 'documents' else 'created'
            value = store.rows(f'SELECT * FROM {name} WHERE project_id=? ORDER BY {order} DESC', (pid,))
            if name == 'assets':
                inventory = {f.get('asset_id'): f for f in (intake.current(pid, True) or {}).get('files', []) if f.get('asset_id')}
                for a in value:
                    if a['id'] in inventory:
                        f = inventory[a['id']]
                        a.update(category=f['category'], relative_path=f['path'], source_status=f['status'])
        digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        current[name] = digest
        if cursors.get(name) != digest: changed[name] = value
    return {'changes': changed, 'cursors': current, 'as_of': store.now(), 'note': '本机分类增量；不查询云任务，不保证跨分类文件系统原子快照'}
