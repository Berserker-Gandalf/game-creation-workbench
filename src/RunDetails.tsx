import { t as tr } from './i18n';
import { useState } from 'react';
import { api, post } from './api';

function decode(value: string) { try { return JSON.parse(value); } catch { return value; } }

export default function RunDetails({ run: summary, onError, refresh }: any) {
  const [events, setEvents] = useState<any[] | null>(null);
  const [full, setFull] = useState<any>(null);
  const run = full ? { ...full, status: summary.status } : summary;
  const inspect = async () => {
    try { const [record, values] = await Promise.all([api(`/runs/${summary.id}`), api(`/runs/${summary.id}/tools`)]); setFull(record); setEvents(values); } catch (e) { onError((e as Error).message); }
  };
  let usage: any = {}, runtime: any = {};
  try { usage = JSON.parse(run.usage || '{}'); runtime = JSON.parse(run.runtime || '{}'); } catch {}
  return <details className="run-details" onToggle={e => { if (e.currentTarget.open) inspect(); }}>
    <summary>{tr("执行详情 ·")}{run.model || tr("模型未记录")} · {run.status}</summary>
    <p>{run.provider || run.kind} · {run.agent || tr("项目操作")}</p>
    {runtime.context && <p>{tr("上下文")}{runtime.context.mode} {tr("· 项目")}{runtime.context.project_chars} {tr("字符 · 历史")}{runtime.context.history_chars} {tr("字符 ·")}{runtime.context.omitted_messages} {tr("条早期记录可检索（非实际token计费）")}</p>}
    {runtime.verified && <p>{tr("工具隔离已核验 ·")}{runtime.tools?.length} {tr("个工具 ·")}{runtime.project_commands ? tr("允许项目命令") : tr("项目命令关闭")}</p>}
    {runtime.permissions && <p>{tr("权限记录：")}{runtime.permissions.full ? tr("工作台全功能") : tr("角色默认")} {tr("· Codex整机")}{runtime.computer_access || runtime.permissions.computer ? tr("已授权") : tr("已关闭")} {tr("· SUNO自动积分")}{runtime.permissions.suno ? tr("允许") : tr("已关闭")} {tr("· Tripo自动积分")}{runtime.permissions.tripo ? tr("允许") : tr("已关闭")}</p>}
    {runtime.action && <><p>{tr("工作台动作：")}{runtime.action} {tr("· 上级对话")}{runtime.parent_run_id || tr("未记录")}</p><pre>{JSON.stringify(runtime.result ?? { error: runtime.error || tr("操作仍在进行，刷新可更新") }, null, 2)}</pre></>}
    <p>{usage.requests ? tr("{0} 次模型请求 · 合计 {1} tokens", usage.requests.length, usage.total_tokens ?? usage.totalTokens ?? tr("未返回")) : tr("供应商未返回可汇总的用量；账号计费以供应商为准")}</p>
    {run.status === 'running' && run.kind.startsWith('chat:') && <button className="secondary" onClick={async () => { try { await post(`/runs/${run.id}/cancel`); await refresh(); } catch (e) { onError((e as Error).message); } }}>{tr("停止本次对话")}</button>}
    {events === null ? <small>{tr("读取调用记录…")}</small> : !events.length ? <small>{tr("本次没有工作台工具调用记录")}</small> : events.map(event => <details key={event.id}><summary>{event.tool} · {event.status}</summary><pre>{JSON.stringify({ parameters: decode(event.arguments), result: decode(event.result) }, null, 2)}</pre></details>)}
  </details>;
}
