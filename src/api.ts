import { t as tr } from './i18n';
import { presentApi, serverText } from './i18n';
let token = '';

export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { 'X-Workbench-Token': token };
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api' + path, { ...options, headers: { ...headers, ...options.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? serverText(body.detail) : tr("请求失败 ({0})", response.status));
  }
  const result = await response.json();
  if (path === '/bootstrap') token = result.token;
  return presentApi(path, result) as T;
}

export const post = (path: string, body: unknown = {}) => api(path, { method: 'POST', body: JSON.stringify(body) });
export const patch = (path: string, body: unknown) => api(path, { method: 'PATCH', body: JSON.stringify(body) });

export async function apiIfChanged(path: string, etag = '') {
  const response = await fetch('/api' + path, { headers: { 'X-Workbench-Token': token, ...(etag ? { 'If-None-Match': etag } : {}) } });
  if (response.status === 304) return { etag, changed: false, value: null };
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(serverText(body.detail) || tr("状态刷新失败")); }
  return { etag: response.headers.get('ETag') || '', changed: true, value: await response.json() };
}

export async function chatStream(pid: string, body: unknown, signal: AbortSignal, onEvent: (event: any) => void) {
  const response = await fetch(`/api/projects/${pid}/chat`, {
    method: 'POST', body: JSON.stringify(body), signal,
    headers: { 'Content-Type': 'application/json', 'X-Workbench-Token': token },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(serverText(error.detail) || tr("对话连接失败"));
  }
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let pending = '', doneReceived = false, explicitError = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    pending += decoder.decode(value, { stream: true });
    let end: number;
    while ((end = pending.indexOf('\n\n')) >= 0) {
      const frame = pending.slice(0, end); pending = pending.slice(end + 2);
      for (const line of frame.split('\n')) if (line.startsWith('data: ')) {
        const event = JSON.parse(line.slice(6));
        if (event.event === 'done') doneReceived = true;
        if (event.event === 'error') explicitError = event.message;
        onEvent(event);
      }
    }
  }
  if (explicitError) throw new Error(serverText(explicitError));
  if (!doneReceived) throw new Error(tr("连接结束但未确认完成；请核对结果后重试"));
}
