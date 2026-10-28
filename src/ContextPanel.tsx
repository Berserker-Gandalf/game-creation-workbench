import { serverText } from './i18n';
import { t as tr, dateLocale } from './i18n';
import { useEffect, useState } from 'react';
import { api, post } from './api';
import { loadLocal, saveLocal } from './drafts';

export default function ContextPanel({ pid, cid, mode, setMode, streaming, onError, refresh, compose }: any) {
  const key = `context-notes:${pid}:${cid}`;
  const [notes, setNotes] = useState(() => loadLocal(key, { decisions: '', skills: '', workflow: '' }));
  const [preview, setPreview] = useState<any>(null), [saved, setSaved] = useState<any>(null), [busy, setBusy] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState('');
  const [editing, setEditing] = useState(false);
  const [documents, setDocuments] = useState<any[]>([]);
  useEffect(() => { let active = true; if (editing) api(`/projects/${pid}/catalog/documents?handoff=true&limit=60`).then(v => { if (active) setDocuments(v.items); }).catch(e => { if (active) onError(e.message); }); return () => { active = false; }; }, [editing, pid, saved]);
  const groups: Record<string, any[]> = {};
  for (const doc of documents) { const [name, group] = doc.title.split(' · '); if (group && ['PROJECT_MEMORY.md', 'SKILLS.md', 'WORKFLOW.md'].includes(name)) (groups[group] ||= []).push(doc); }
  const complete = Object.entries(groups).filter(([, docs]) => docs.length === 3).slice(0, 20);
  const chosen = complete.find(([id]) => id === selectedGroup) || complete[0];
  const edit = (name: string, value: string) => { const next = { ...notes, [name]: value }; setNotes(next); try { saveLocal(key, next); } catch (e) { onError((e as Error).message); } };
  const action = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); } catch (e) { onError((e as Error).message); } finally { setBusy(false); } };
  return <details className="session-settings context-settings"><summary>{tr("上下文与 Markdown 留存")}</summary>
    <label>{tr("本轮上下文")}<select aria-label={tr("上下文模式")} value={mode} disabled={streaming} onChange={e => { setMode(e.target.value); setPreview(null); }}><option value="auto">{tr("自动：保留适量正文，超限压缩目录")}</option><option value="compact">{tr("精简：目录与记忆，按需读取原文")}</option></select></label>
    <small>{tr("压缩不删除历史、不批准设计。数量按字符计算，实际模型额度以服务返回为准。")}</small>
    <button disabled={busy || streaming} onClick={() => action(async () => setPreview(await api(`/projects/${pid}/context?conversation_id=${cid}&mode=${mode}`)))}>{tr("预览将发送的上下文")}</button>
    {preview && <div className="context-preview"><p>{tr("项目资料")}{preview.info.project_chars || tr("目录")} {tr("字符 · 历史")}{preview.info.history_chars || 0} {tr("字符 · 未直接附带")}{preview.info.omitted_messages || 0} {tr("条历史，可回查。")}</p><details><summary>{tr("查看资料、分页覆盖和历史正文")}</summary><pre>{JSON.stringify(preview, null, 2)}</pre></details></div>}
    <button disabled={streaming} onClick={() => setEditing(true)}>{tr("管理项目记忆与 Markdown 留存")}</button>
    {editing && <div className="modal-overlay"><section className="modal task-modal context-editor" role="dialog" aria-modal="true" aria-label={tr("项目记忆与Markdown留存")}><div className="modal-heading"><h2>{tr("项目记忆、Skill 约定与工作流")}</h2><button onClick={() => setEditing(false)}>{tr("关闭留存编辑")}</button></div>
    <label>{tr("关键决定与待核实事项")}<textarea aria-label={tr("关键决定留存")} maxLength={20000} value={notes.decisions} onChange={e => edit('decisions', e.target.value)}/></label>
    <label>{tr("Skill 使用约定")}<textarea aria-label={tr("Skill使用约定")} maxLength={20000} value={notes.skills} onChange={e => edit('skills', e.target.value)}/></label>
    <label>{tr("项目工作流")}<textarea aria-label={tr("项目工作流留存")} maxLength={20000} value={notes.workflow} onChange={e => edit('workflow', e.target.value)}/></label>
    <div className="action-bar"><button disabled={busy || streaming} onClick={() => action(async () => { setSaved(await post(`/projects/${pid}/context/checkpoint`, { conversation_id: cid, ...notes })); await refresh(); })}>{tr("按当前记录保存三份 Markdown 草稿")}</button><button disabled={streaming} onClick={() => { compose(tr("请根据当前项目、正式设计和可检索的会话历史，整理关键决定、待核实事项、Skill使用约定及接续工作流。标注资料出处和版本；摘要不替代正式规则。先给出可审阅内容，获得本轮执行许可时可用create_document保存为Markdown草稿，不更改权限或安装Skill。")); setEditing(false); }}>{tr("将 AI 整理请求加入输入框")}</button></div>
    {saved && <p>{serverText(saved.note)}<br/><a className="text-button" href={`/api/projects/${pid}/context/markdown?ids=${saved.documents.map((d: any) => d.id).join(',')}`}>{tr("下载 PROJECT_MEMORY、SKILLS、WORKFLOW")}</a></p>}
    {!!complete.length && <label>{tr("最近保存的留存组（最多20组）")}<select aria-label={tr("已有Markdown留存")} value={chosen?.[0] || ''} onChange={e => setSelectedGroup(e.target.value)}>{complete.map(([id, docs]) => <option key={id} value={id}>{new Date(docs[0].updated).toLocaleString(dateLocale)} · {id.slice(0, 6)}</option>)}</select>{chosen && <a className="text-button" href={`/api/projects/${pid}/context/markdown?ids=${chosen[1].map(d => d.id).join(',')}`}>{tr("下载所选组当前已保存的 Markdown")}</a>}</label>}
    <small>{tr("三份文件记录当前状态与补充约定，作为设计草稿保留并随资料包备份。SKILLS.md不包含第三方Skill源码或凭据，不会自动安装或授予权限。")}</small>
    </section></div>}
  </details>;
}
