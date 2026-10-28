import { serverText } from './i18n';
import { t as tr } from './i18n';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { api } from './api';

export default function AgentPermissions({ cid, pid, agent, execute, provider, streaming, onSaved, onError }: any) {
  const [grant, setGrant] = useState<any>(null), [saving, setSaving] = useState(false), [ack, setAck] = useState(false), [computerAck, setComputerAck] = useState(false);
  const [actions, setActions] = useState<any[] | null>(null);
  const [applied, setApplied] = useState<any>(null);
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false), [runtime, setRuntime] = useState<any>(null);
  const check = async () => { setChecking(true); try { setRuntime(await api(`/projects/${pid}/mcp/check`, { method: 'POST', body: JSON.stringify({ conversation_id: cid, agent, execute }) })); } catch (e) { onError((e as Error).message); } finally { setChecking(false); } };
  useEffect(() => { let active = true; api(`/conversations/${cid}/permissions`).then(g => { if (active) { setGrant(g); setApplied(g); } }).catch(e => onError(e.message)); return () => { active = false; }; }, [cid]);
  const edit = (values: any) => { setGrant((g: any) => ({ ...g, ...values })); setAck(false); setComputerAck(false); };
  const save = async (revoke = false) => {
    if (!grant || saving) return;
    setSaving(true);
    try {
      const flags = revoke ? { full: false, computer: false, suno: false, tripo: false } : grant;
      const next = await api(`/conversations/${cid}/permissions`, { method: 'PUT', body: JSON.stringify({ full: flags.full, computer: flags.computer, suno: flags.suno, tripo: flags.tripo, version: grant.version, acknowledged: revoke ? false : ack, computer_ack: revoke ? false : computerAck }) });
      setGrant(next); setApplied(next); setAck(false); setComputerAck(false); setActions(null); setRuntime(null); onSaved(next, revoke);
    } catch (e) { onError((e as Error).message); try { const g = await api(`/conversations/${cid}/permissions`); setGrant(g); setApplied(g); } catch {} }
    finally { setSaving(false); }
  };
  return <div className="agent-permissions"><button aria-haspopup="dialog" onClick={() => setOpen(true)}>{tr("Agent 访问与积分授权 ·")}{applied?.full ? tr("已授全功能") : tr("默认角色权限")}</button>
    {open && createPortal(<div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) setOpen(false); }} onKeyDown={e => {
      if (e.key === 'Escape') setOpen(false);
      if (e.key === 'Tab') { const items = [...e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled)')];
        const edge = e.shiftKey ? items[0] : items[items.length - 1]; if (document.activeElement === edge) { e.preventDefault(); (e.shiftKey ? items[items.length - 1] : items[0])?.focus(); } }
    }}><section className="modal agent-permission-modal" role="dialog" aria-modal="true" aria-label={tr("Agent 访问与积分授权")}><div className="modal-heading"><h2>{tr("Agent 访问与积分授权")}</h2><button autoFocus aria-label={tr("关闭授权面板")} onClick={() => setOpen(false)}>{tr("关闭")}</button></div>
    {!grant ? <p>{tr("正在读取授权…")}</p> : <>
      <p>{tr("授权仅绑定当前会话。执行模式生效；新会话、复制和恢复不会继承授权。")}</p>
      {applied && ['full', 'computer', 'suno', 'tripo'].some(k => applied[k] !== grant[k]) && <p className="intake-warning">{tr("授权选择尚未保存，当前仍采用上次保存的权限。")}</p>}
      <label><input type="checkbox" aria-label={tr("工作台全功能授权")} checked={grant.full} disabled={streaming || saving} onChange={e => edit(e.target.checked ? { full: true } : { full: false, computer: false, suno: false, tripo: false })}/>{tr("允许 Agent 使用当前项目全部已接入业务功能")}</label>
      <small>{tr("包括跨工作区读写、设计/任务状态、美术 API、本机建模、引擎、快照/恢复和 GitHub 发布。可能修改文件、上传内容或消耗图像 API 额度；密钥、安装路径、权限和服务管理仍由用户设置。")}</small>
      <label><input type="checkbox" aria-label={tr("SUNO 自动积分授权")} checked={grant.suno} disabled={!grant.full || streaming || saving} onChange={e => edit({ suno: e.target.checked })}/>{tr("允许 Agent 自由消耗 SUNO 积分")}</label>
      <label><input type="checkbox" aria-label={tr("Tripo 自动积分授权")} checked={grant.tripo} disabled={!grant.full || streaming || saving} onChange={e => edit({ tripo: e.target.checked })}/>{tr("允许 Agent 自由消耗 Tripo API 积分并上传参考图")}</label>
      <small>{tr("未勾选时只保存方案，需你逐次确认。勾选后不逐次询问、不设积分总额上限；未知结果不自动重提。模型在音乐/Tripo 页选择。")}</small>
      <label><input type="checkbox" aria-label={tr("Codex 整台电脑访问")} checked={grant.computer} disabled={!grant.full || (provider !== 'codex' && !grant.computer) || streaming || saving} onChange={e => edit({ computer: e.target.checked })}/>{tr("Codex 整台电脑访问（文件、命令与网络）")}</label>
      <small>{tr("仅 Codex 生效，使用当前系统账户权限；不是自动获得鼠标键盘工具。整机模式可绕过工作台调用其他程序，因此积分开关仅约束工作台请求，无法约束直接运行的脚本。组织或运行时策略可能拒绝整机模式。")}</small>
      {grant.full && <label><input type="checkbox" aria-label={tr("确认全功能授权范围")} checked={ack} disabled={streaming || saving} onChange={e => setAck(e.target.checked)}/>{tr("我理解上述文件修改、外传和费用范围，并确认授予本会话")}</label>}
      {grant.computer && <label><input type="checkbox" aria-label={tr("确认整机访问边界")} checked={computerAck} disabled={streaming || saving} onChange={e => setComputerAck(e.target.checked)}/>{tr("我理解整机访问会解除工程限制，积分开关无法提供系统级隔离")}</label>}
      <div className="action-bar"><button className="secondary" disabled={streaming || saving || (grant.full && !ack) || (grant.computer && !computerAck)} onClick={() => save()}>{tr("保存授权")}</button><button disabled={saving} onClick={() => save(true)}>{tr("撤销增强授权并停止当前调用")}</button><button disabled={saving} onClick={async () => { try { setActions(await api(`/conversations/${cid}/actions`)); } catch (e) { onError((e as Error).message); } }}>{tr("查看可用功能目录")}</button></div>
      <small>{tr("撤销会阻止新调用并尝试中断当前调用；已提交云端任务、已写入文件及独立后台生成不会自动撤销。")}</small>
      <button className="text-button" disabled={streaming || saving || checking || provider !== 'codex'} onClick={check}>{checking ? tr("正在核验…") : tr("核验本轮 Codex 工具与权限（不推理）")}</button>
      {runtime && runtime.grant_version === applied?.version && runtime.mode === (execute ? 'execute' : 'discussion') && provider === 'codex' && <p>{tr("已核验")}{runtime.tools.length} {tr("个应用工具 ·")}{runtime.computer_access ? tr("整机通道已启用") : tr("整机通道关闭")} · {runtime.mode === 'execute' ? tr("执行模式") : tr("讨论模式")}</p>}
      {actions && <div className="agent-action-list">{actions.map(a => <p key={a.name}><code>{a.name}</code> · {a.allowed ? tr("已授权") : a.cost ? tr("需全功能及对应积分授权") : tr("需全功能授权")}<small>{serverText(a.description)}</small></p>)}</div>}
    </>}
    </section></div>, document.body)}
  </div>;
}
