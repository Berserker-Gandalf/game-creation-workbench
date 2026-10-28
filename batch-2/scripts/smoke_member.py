"""Live integration check. Creates an explicitly named disposable validation project."""
import json
import sys
import httpx


def main():
    with httpx.Client(base_url='http://127.0.0.1:8765', timeout=300, trust_env=False) as client:
        client.headers['x-workbench-token'] = client.get('/api/bootstrap').json()['token']
        status = client.get('/api/codex/status').json()
        print(json.dumps({'available': status.get('available'), 'logged_in': bool(status.get('account')), 'models': len(status.get('models', [])), 'error': status.get('error')}, ensure_ascii=False), flush=True)
        if not status.get('account'):
            sys.exit(1)
        project = next((p for p in client.get('/api/bootstrap').json()['projects'] if p['name'] == '工作台接入验收'), None)
        if project is None:
            project = client.post('/api/projects', json={'name': '工作台接入验收', 'engine': 'unreal',
                'brief': '这是独立的工作台测试项目。验证规则：游戏只有三个房间，主角是一只橙色小机器人。'}).json()
        output = []
        with client.stream('POST', f"/api/projects/{project['id']}/chat", json={
            'provider': 'codex', 'execute': True,
            'message': '请使用 workbench 工具读取项目，再创建一项名为“验证房间交互”的待执行任务，验收条件为三个房间都能触发交互。最后简短回答已记录的房间数量和主角设定。不要修改其他文件。'
        }) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith('data: '):
                    event = json.loads(line[6:])
                    if event['event'] in ('activity', 'error', 'done'):
                        print(json.dumps(event, ensure_ascii=False), flush=True)
                    if event['event'] == 'delta':
                        output.append(event['text'])
        snapshot = client.get('/api/projects/' + project['id']).json()
        result = {'project_id': project['id'], 'assistant': ''.join(output), 'tasks': snapshot['tasks'], 'runs': snapshot['runs']}
        from pathlib import Path
        path = Path('.dev/member-verification.json'); path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'reply': ''.join(output), 'tasks_created': len(snapshot['tasks']), 'run_status': snapshot['runs'][0]['status']}, ensure_ascii=False), flush=True)
        if snapshot['runs'][0]['status'] != 'completed' or not snapshot['tasks']:
            sys.exit(1)


if __name__ == '__main__':
    main()
