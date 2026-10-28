"""Human-managed conversation grants; never exported or inherited by a fork."""
import json
from . import conversations, store

FLAGS = ('full', 'computer', 'suno', 'tripo')


def get(cid):
    conversations.get(cid)
    return store.setting('agent_grant:' + cid, {**dict.fromkeys(FLAGS, False), 'version': '', 'updated': None})


def save(cid, data):
    conversation = conversations.get(cid)
    if not isinstance(data, dict) or set(data) != {*FLAGS, 'version', 'acknowledged', 'computer_ack'}:
        raise ValueError('授权字段无效，请刷新授权面板')
    if any(type(data[k]) is not bool for k in (*FLAGS, 'acknowledged', 'computer_ack')):
        raise ValueError('授权选项必须为开关')
    if data['version'] != get(cid)['version']: raise ValueError('授权已有变更，请刷新后再操作')
    if any(data[k] for k in ('computer', 'suno', 'tripo')) and not data['full']:
        raise ValueError('请先授予工作台全功能权限')
    if data['full'] and not data['acknowledged']: raise ValueError('请明确确认全功能授权的范围')
    if data['computer'] and not data['computer_ack']: raise ValueError('请明确确认 Codex 整机访问及积分开关的约束边界')
    grant = {**{k: data[k] for k in FLAGS}, 'version': store.uid(), 'updated': store.now()}
    store.set_setting('agent_grant:' + cid, grant)
    rid = store.run_start(conversation['project_id'], 'agent_permission', '用户更新会话授权', cid, agent=conversation['agent'])
    store.execute('UPDATE runs SET runtime=? WHERE id=?', (json.dumps({'permissions': grant}), rid))
    store.run_end(rid, 'completed', '会话授权已更新；旧运行权限已失效')
    return grant


def effective(scope):
    if not scope.get('grant_version'): return dict.fromkeys(FLAGS, False)
    cid = scope.get('conversation_id')
    conversations.get(cid, scope['pid'], scope.get('agent', 'director'))
    current = get(cid)
    if current['version'] != scope['grant_version']: raise ValueError('用户已更改或撤销授权，请重新开始对话')
    return {**current, 'computer': bool(current['computer'] and scope.get('codex_computer'))} if scope['write'] else dict.fromkeys(FLAGS, False)
