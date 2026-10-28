"""Workbench-owned conversations persist independently of a provider's runtime."""
import json
from . import store


def get(cid, pid=None, agent=None):
    row = store.one('SELECT * FROM conversations WHERE id=?', (cid,))
    if not row or (pid and row['project_id'] != pid) or (agent and row['agent'] != agent):
        raise ValueError('会话不属于当前项目或负责人')
    return row


def preferences(cid):
    get(cid)
    return store.setting('conversation_preferences:' + cid, {'execute': False, 'reasoning_effort': ''})


def save_preferences(cid, data):
    current = preferences(cid)
    if not isinstance(data, dict) or set(data) - {'execute', 'reasoning_effort'}:
        raise ValueError('会话偏好字段无效')
    value = {**current, **data}
    effort = value['reasoning_effort']
    if type(value['execute']) is not bool or not isinstance(effort, str) or len(effort) > 40 or (effort and not all(c in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in effort)):
        raise ValueError('执行开关或推理强度无效')
    store.set_setting('conversation_preferences:' + cid, value)
    return value


def create(pid, data):
    store.project(pid)
    agent = data.get('agent', 'director')
    title = str(data.get('title', '新对话')).strip()
    provider, model = data.get('provider', 'codex'), str(data.get('model', ''))
    if agent not in ('director', 'music', 'modeler') or provider not in ('codex', 'openai', 'deepseek') or not title or len(title) > 100 or len(model) > 120:
        raise ValueError('会话名称、角色或模型无效')
    cid = store.uid()
    store.execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (cid, pid, agent, title, provider, model, '', 0, store.now(), store.now()))
    return get(cid)


def migrate_legacy(pid=None):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        query = 'SELECT * FROM messages WHERE conversation_id IS NULL'
        pending = c.execute(query + (' AND project_id=?' if pid else '') + ' ORDER BY created', (pid,) if pid else ()).fetchall()
        mapping = {}
        for message in pending:
            suffix = message['provider'].split(':')[-1]
            agent = suffix if suffix in ('music', 'modeler') else 'director'
            key = (message['project_id'], agent)
            if key not in mapping:
                existing = c.execute('SELECT id FROM conversations WHERE project_id=? AND agent=? ORDER BY created LIMIT 1', key).fetchone()
                cid = existing['id'] if existing else store.uid()
                if not existing:
                    c.execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?,?,?)',
                              (cid, key[0], agent, '历史对话', message['provider'].split(':')[0], '', '', 0, message['created'], store.now()))
                mapping[key] = cid
            c.execute('UPDATE messages SET conversation_id=? WHERE id=?', (mapping[key], message['id']))


def default(pid, agent):
    migrate_legacy(pid)
    row = store.one('SELECT * FROM conversations WHERE project_id=? AND agent=? AND archived=0 ORDER BY updated DESC LIMIT 1', (pid, agent))
    return row or create(pid, {'agent': agent})


def update(cid, data):
    row = get(cid)
    title, memory = str(data.get('title', row['title'])).strip(), str(data.get('memory', row['memory']))
    provider, model = data.get('provider', row['provider']), str(data.get('model', row['model']))
    if not title or len(title) > 100 or len(memory) > 12000 or len(model) > 120 or provider not in ('codex', 'openai', 'deepseek'):
        raise ValueError('会话配置过长或无效')
    if 'archived' in data and not isinstance(data['archived'], bool):
        raise ValueError('会话归档状态无效')
    store.execute('UPDATE conversations SET title=?,memory=?,provider=?,model=?,archived=?,updated=? WHERE id=?',
                  (title, memory, provider, model, int(data.get('archived', row['archived'])), store.now(), cid))
    return get(cid)


def history(cid, query='', limit=30):
    get(cid)
    if len(query) > 120:
        raise ValueError('历史搜索词过长')
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    return store.rows("SELECT * FROM messages WHERE conversation_id=? AND content LIKE ? ESCAPE '\\' ORDER BY created DESC,rowid DESC LIMIT ?", (cid, pattern, max(1, min(int(limit), 100))))[::-1]


def model_history(cid, budget=60000):
    if type(budget) is not int or not 256 <= budget <= 60000: raise ValueError('历史字符预算无效')
    result = []
    with store.db() as c:
        total = c.execute('SELECT COUNT(*) FROM messages WHERE conversation_id=?', (cid,)).fetchone()[0]
        records = c.execute('''SELECT id,role,substr(content,1,?) AS content,length(content) AS chars,asset_id
            FROM messages WHERE conversation_id=? ORDER BY created DESC,rowid DESC LIMIT 100''', (budget, cid))
        for row in records:
            message = {'role': row['role'], 'content': row['content']}
            suffix = '\n[附图资产 ID：' + row['asset_id'] + '；需要查看时使用 view_asset]' if row['asset_id'] else ''
            message['content'] += suffix
            size = lambda value: len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
            if row['chars'] <= len(row['content']) and size([*result, message]) <= budget:
                result.append(message); continue
            if result: break
            notice = f'\n[消息{row["id"]}原文共{row["chars"]}字符，未完整附带；使用read_history(message_id,offset,limit)回查。]'
            # Keep the newest oversized message useful while bounding the actual encoded array.
            low, high = 0, len(row['content'])
            while low < high:
                middle = (low + high + 1) // 2
                message['content'] = row['content'][:middle] + suffix + notice
                if size([message]) <= budget: low = middle
                else: high = middle - 1
            message['content'] = row['content'][:low] + suffix + notice
            if size([message]) <= budget: result.append(message)
            break
    return result[::-1], total - len(result)


def window(cid, query='', before=0):
    get(cid)
    if not isinstance(query, str) or len(query) > 120 or type(before) is not int or before < 0: raise ValueError('历史分页参数无效')
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    values = store.rows('''SELECT rowid AS cursor,id,role,substr(content,1,4000) AS content,length(content) AS chars,
        provider,created,model,asset_id,run_id FROM messages WHERE conversation_id=? AND content LIKE ? ESCAPE '\\'
        AND (?=0 OR rowid<?) ORDER BY rowid DESC LIMIT 31''', (cid, pattern, before, before))
    more = len(values) > 30
    values = values[:30]
    for value in values: value['truncated'] = value['chars'] > len(value['content'])
    return {'items': values[::-1], 'next_before': values[-1]['cursor'] if more and values else None}


def read_message(cid, mid, offset=0, limit=6000):
    get(cid)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 12000: raise ValueError('历史分段范围无效')
    value = store.one('''SELECT id,role,substr(content,?,?) AS content,length(content) AS total_chars,asset_id
        FROM messages WHERE id=? AND conversation_id=?''', (offset + 1, limit, mid, cid))
    if not value: raise ValueError('历史消息不属于当前会话')
    return {**value, 'offset': offset, 'next_offset': offset + len(value['content']) if offset + len(value['content']) < value['total_chars'] else None}


def fork(cid):
    original = get(cid)
    copy = create(original['project_id'], {**original, 'title': original['title'][:90] + ' · 副本'})
    update(copy['id'], {'memory': original['memory']})
    with store.db() as c:
        for m in c.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY created,rowid', (cid,)).fetchall():
            c.execute('''INSERT INTO messages (id,project_id,role,content,provider,created,conversation_id,model,asset_id)
                         VALUES (?,?,?,?,?,?,?,?,?)''', (store.uid(), m['project_id'], m['role'], m['content'], m['provider'], m['created'], copy['id'], m['model'], m['asset_id']))
    return get(copy['id'])
