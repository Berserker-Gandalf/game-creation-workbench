import { t as tr } from './i18n';
import { useEffect, useRef, useState } from 'react';
import { ArrowUp, Image as ImageIcon, LoaderCircle, Plus, Sparkles, Square, X } from 'lucide-react';
import { api, chatStream, patch, post } from './api';
import { loadLocal, saveLocal } from './drafts';
import RunDetails from './RunDetails';
import AgentPermissions from './AgentPermissions';
import ContextPanel from './ContextPanel';

export default function Chat(props: any) {
  const { data, agent, onError } = props;
  const [sessions, setSessions] = useState<any[]>([]), [id, setId] = useState(''), [archived, setArchived] = useState(false);
  const [loading, setLoading] = useState(true), [streaming, setStreaming] = useState(false);
  const key = `session:${data.project.id}:${agent}`;
  const reload = async (select = '') => {
    let values = await api(`/projects/${data.project.id}/conversations?agent=${agent}&archived=${archived}`);
    if (!values.length && !archived) values = [await post(`/projects/${data.project.id}/conversations`, { agent, title: tr("新建会话") })];
    setSessions(values);
    const remembered = select || id || loadLocal(key, '');
    const next = values.some((v: any) => v.id === remembered) ? remembered : values[0]?.id || '';
    setId(next); saveLocal(key, next);
  };
  useEffect(() => { let active = true; setLoading(true); (async () => {
    try {
      let values = await api(`/projects/${data.project.id}/conversations?agent=${agent}&archived=${archived}`);
      if (!values.length && !archived) values = [await post(`/projects/${data.project.id}/conversations`, { agent, title: tr("新建会话") })];
      if (!active) return;
      setSessions(values); const remembered = loadLocal(key, '');
      setId(values.find((v: any) => v.id === remembered)?.id || values[0]?.id || '');
    } catch (e) { if (active) onError((e as Error).message); } finally { if (active) setLoading(false); }
  })(); return () => { active = false; }; }, [archived]);
  const current = sessions.find(s => s.id === id);
  const action = async (fn: () => Promise<any>) => { try { await fn(); } catch (e) { onError((e as Error).message); } };
  return <section className="chat-panel">
    <div className="chat-heading"><span className="assistant-avatar"><Sparkles size={17}/></span><div><strong>{agent === 'music' ? tr("音乐负责人") : agent === 'modeler' ? tr("角色建模负责人") : tr("项目负责人")}</strong><small>{tr("会话独立保存 · 工具调用可追溯")}</small></div></div>
    <div className="session-bar"><select aria-label={tr("当前会话")} value={id} disabled={streaming || loading} onChange={e => { setId(e.target.value); saveLocal(key, e.target.value); }}>{sessions.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select><button aria-label={tr("新建会话")} disabled={streaming || archived} onClick={() => action(async () => { const s = await post(`/projects/${data.project.id}/conversations`, { agent, title: tr("新建会话") }); await reload(s.id); })}><Plus size={16}/></button><label><input type="checkbox" checked={archived} disabled={streaming} onChange={e => setArchived(e.target.checked)}/>{tr("已归档")}</label></div>
    {current && !loading ? <Session key={id} {...props} conversation={current} reload={reload} onStreaming={(value: boolean) => { setStreaming(value); props.onRunning(value); }}/> : <div className="chat-messages"><p>{loading ? tr("正在恢复会话…") : tr("没有已归档的会话")}</p></div>}
  </section>;
}

function Session({ data, agent, conversation, reload, onStreaming, codexInfo, providers, attachment, setAttachment, onRefresh, onError, analysisRequest, onAnalysisConsumed }: any) {
  const cid = conversation.id, draftKey = 'chat:' + cid;
  const [draft, setDraft] = useState(() => loadLocal(draftKey, { message: '', title: conversation.title, memory: conversation.memory, context_mode: 'auto' }));
  const [messages, setMessages] = useState<any[]>([]), [query, setQuery] = useState(''), [streaming, setStreaming] = useState(false);
  const [older, setOlder] = useState<number | null>(null), [historyBusy, setHistoryBusy] = useState(false), [record, setRecord] = useState<any>(null), [recordPage, setRecordPage] = useState<any>(null);
  const messageSequence = useRef(0);
  const [partial, setPartial] = useState(''), [pending, setPending] = useState(''), [activity, setActivity] = useState('');
  const [provider, setProvider] = useState(conversation.provider), [model, setModel] = useState(conversation.model), [preferences, setPreferences] = useState({ execute: false, reasoning_effort: '' });
  const [preferencesLoading, setPreferencesLoading] = useState(true), [preferencesSaving, setPreferencesSaving] = useState(false);
  const execute = preferences.execute;
  useEffect(() => { let active = true; api(`/conversations/${cid}/preferences`).then(value => { if (active) { setPreferences(value); setPreferencesLoading(false); } }).catch(e => onError(e.message)); return () => { active = false; }; }, [cid]);
  const savePreferences = async (changes: any) => {
    setPreferencesSaving(true);
    try { const value = await api(`/conversations/${cid}/preferences`, { method: 'PUT', body: JSON.stringify(changes) }); setPreferences(value); return true; }
    catch (e) { onError((e as Error).message); return false; }
    finally { setPreferencesSaving(false); }
  };
  const selectedModel = codexInfo?.models?.find((m: any) => model ? m.model === model : m.isDefault) || (!model ? codexInfo?.models?.[0] : null);
  const efforts: string[] = provider === 'codex' ? (selectedModel?.supportedReasoningEfforts || []).map((v: any) => v.reasoningEffort) : provider === 'deepseek' ? ['none', 'low', 'high', 'max'] : ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
  const effortNames: Record<string, string> = { none: tr("不推理"), minimal: tr("极低"), low: tr("低"), medium: tr("中"), high: tr("高"), xhigh: tr("很高"), max: tr("最高"), ultra: tr("超高") };
  const configuring = preferencesLoading || preferencesSaving;
  const controller = useRef<AbortController | null>(null), runId = useRef(''), bottom = useRef<HTMLDivElement>(null);
  const roleName = agent === 'music' ? tr("音乐负责人") : agent === 'modeler' ? tr("角色建模负责人") : tr("项目负责人");
  const editDraft = (changes: any) => { const value = { ...draft, ...changes }; setDraft(value); try { saveLocal(draftKey, value); } catch (e) { onError((e as Error).message); } };
  const readMessages = async (before = 0) => {
    const sequence = ++messageSequence.current; setHistoryBusy(true);
    try { const value = await api(`/conversations/${cid}/window?q=${encodeURIComponent(query)}&before=${before}`); if (sequence !== messageSequence.current) return; setOlder(value.next_before); setMessages(old => before ? [...value.items.filter((m: any) => !old.some(v => v.id === m.id)), ...old] : value.items); }
    finally { if (sequence === messageSequence.current) setHistoryBusy(false); }
  };
  useEffect(() => { readMessages().catch(e => onError(e.message)); return () => { messageSequence.current += 1; }; }, [query]);
  useEffect(() => { let active = true; setRecordPage(null); if (record) api(`/conversations/${cid}/messages/${record.id}?offset=${record.offset}`).then(v => { if (active) setRecordPage(v); }).catch(e => { if (active) onError(e.message); }); return () => { active = false; }; }, [record]);
  useEffect(() => { bottom.current?.scrollIntoView({ block: 'nearest' }); }, [partial, pending]);
  useEffect(() => () => { controller.current?.abort(); }, []);
  const stop = async () => {
    try { if (runId.current) await post(`/runs/${runId.current}/cancel`); } catch (e) { onError((e as Error).message); }
    finally { controller.current?.abort(); }
  };
  const send = async (externalMessage = '', analysis = false) => {
    const value = externalMessage || draft.message;
    if (!value.trim() || streaming || configuring || conversation.archived) return;
    controller.current = new AbortController(); runId.current = ''; setStreaming(true); onStreaming(true); setPartial(''); setPending(value); setActivity(tr("连接模型")); onError('');
    let accepted = false;
    try {
      await chatStream(data.project.id, { message: value, conversation_id: cid, provider, model, agent, context_mode: draft.context_mode || 'auto', execute: analysis ? false : execute, reasoning_effort: preferences.reasoning_effort, asset_id: analysis ? undefined : attachment?.id }, controller.current.signal, event => {
        if (event.event === 'run') { accepted = true; runId.current = event.run_id; if (!analysis) { editDraft({ message: '' }); setAttachment(null); } }
        if (event.event === 'context') setActivity(tr("上下文：{0}字符，{1}条早期记录可回查", event.context.project_chars, event.context.omitted_messages));
        if (event.event === 'delta') setPartial(old => old + event.text);
        if (event.event === 'activity') setActivity(event.text);
        if (event.event === 'runtime') setActivity(tr("已核验 {0} 个工具", event.runtime.tools.length));
      });
    } catch (e) { if ((e as Error).name !== 'AbortError') onError((e as Error).message); }
    finally {
      setStreaming(false); onStreaming(false); setActivity(''); setPartial(''); setPending('');
      try { await readMessages(); await onRefresh(); await reload(cid); } catch (e) { onError((e as Error).message); }
      if (!accepted) setActivity(tr("消息尚未确认接收，草稿已保留；请核对执行记录"));
    }
  };
  useEffect(() => {
    if (!analysisRequest || analysisRequest.pid !== data.project.id || agent !== 'director' || configuring) return;
    onAnalysisConsumed();
    if (conversation.archived || streaming) { onError(tr("当前会话不可发送，请选择未归档会话后重试分析")); return; }
    send(analysisRequest.message, true);
  }, [analysisRequest?.id, configuring]);
  const configure = async (changes: any) => { try { if ((('model' in changes && changes.model !== conversation.model) || ('provider' in changes && changes.provider !== conversation.provider)) && !await savePreferences({ reasoning_effort: '' })) return; await patch(`/conversations/${cid}`, changes); await reload(cid); } catch (e) { onError((e as Error).message); } };
  return <>
    <AgentPermissions cid={cid} pid={data.project.id} agent={agent} execute={execute} provider={provider} streaming={streaming} onError={onError} onSaved={(g: any, revoked: boolean) => { savePreferences({ execute: g.full }); if (revoked && streaming) stop(); onRefresh().catch((e: Error) => onError(e.message)); }}/>
    <ContextPanel pid={data.project.id} cid={cid} documents={data.documents} mode={draft.context_mode || 'auto'} setMode={(value: string) => editDraft({ context_mode: value })} streaming={streaming} onError={onError} refresh={onRefresh} compose={(text: string) => editDraft({ message: [draft.message, text].filter(Boolean).join('\n\n') })}/>
    <details className="session-settings"><summary>{tr("会话设置与记忆")}</summary><input aria-label={tr("会话名称")} value={draft.title} maxLength={100} onChange={e => editDraft({ title: e.target.value })}/><textarea aria-label={tr("会话记忆")} value={draft.memory} maxLength={12000} onChange={e => editDraft({ memory: e.target.value })} placeholder={tr("明确记录需要持续沿用的决定；保存后每轮读取")}/><div className="action-bar"><button disabled={streaming} onClick={() => configure({ title: draft.title, memory: draft.memory })}>{tr("保存设置")}</button><button disabled={streaming} onClick={async () => { try { const s = await post(`/conversations/${cid}/fork`); await reload(s.id); } catch (e) { onError((e as Error).message); } }}>{tr("复制会话")}</button><button disabled={streaming} onClick={() => configure({ archived: !conversation.archived })}>{conversation.archived ? tr("取消归档") : tr("归档")}</button></div><small>{tr("记忆需手动维护。超出上下文的早期交流可由 AI 检索。")}</small></details>
    <input className="history-search" aria-label={tr("搜索会话记录")} disabled={streaming} value={query} onChange={e => setQuery(e.target.value)} placeholder={tr("搜索全部历史，每次读取最近30条")}/>
    <div className="chat-messages">
      {older !== null && <button disabled={historyBusy || streaming} onClick={() => readMessages(older).catch(e => onError(e.message))}>{tr("加载更早记录")}</button>}
      {!messages.length && <div className="chat-intro"><h2>{query ? tr("没有匹配记录") : tr("从一个想法开始。")}</h2><p>{tr("讨论玩法、设计与资产。允许修改按当前会话记住，直到手动关闭。")}</p></div>}
      {messages.map(m => <div className={'message ' + m.role} key={m.id}><span className="message-label">{m.role === 'user' ? tr("你") : roleName}<small>{m.model || m.provider}</small></span><div>{m.content}</div>{m.truncated && <button onClick={() => setRecord({ id: m.id, offset: 0 })}>{tr("分段查看完整原文（")}{m.chars}{tr("字符）")}</button>}{m.asset_id && <small>{tr("附图：")}{data.assets.find((a: any) => a.id === m.asset_id)?.name || m.asset_id}</small>}{m.role === 'assistant' && data.runs.find((r: any) => r.id === m.run_id) && <RunDetails run={data.runs.find((r: any) => r.id === m.run_id)} refresh={onRefresh} onError={onError}/>}</div>)}
      {pending && <div className="message user">{pending}</div>}{streaming && <div className="message assistant"><small><LoaderCircle size={12} className="spin"/>{activity}</small><div>{partial || tr("正在读取项目资料…")}</div></div>}<div ref={bottom}/>
    </div>
    {record && <div className="modal-overlay"><section className="modal task-modal" role="dialog" aria-modal="true" aria-label={tr("历史消息原文")}><div className="modal-heading"><h2>{tr("历史消息原文")}</h2><button onClick={() => setRecord(null)}>{tr("关闭原文")}</button></div>{recordPage ? <><p>{tr("共")}{recordPage.total_chars}{tr("字符 · 从第")}{recordPage.offset + 1}{tr("字符读取；原始记录保留。")}</p><pre style={{ whiteSpace: 'pre-wrap' }}>{recordPage.content}</pre><div className="action-bar"><button disabled={!record.offset} onClick={() => setRecord({ ...record, offset: Math.max(0, record.offset - 6000) })}>{tr("上一段")}</button><button disabled={recordPage.next_offset === null} onClick={() => setRecord({ ...record, offset: recordPage.next_offset })}>{tr("下一段")}</button></div></> : <p>{tr("正在读取原文…")}</p>}</section></div>}
    <div className="composer-area">{attachment && <div className="attachment"><ImageIcon size={14}/>{attachment.name}<button aria-label={tr("移除附图")} onClick={() => setAttachment(null)}><X size={13}/></button></div>}
      <div className="composer"><textarea aria-label={tr("向{0}发送消息", roleName)} value={draft.message} placeholder={conversation.archived ? tr("已归档，请先取消归档或复制会话") : tr("聊聊设计细节…未发送内容保存在此浏览器")} disabled={streaming || !!conversation.archived} onChange={e => editDraft({ message: e.target.value })} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}/><div className="composer-bottom"><label className="execute-toggle"><input type="checkbox" checked={execute} disabled={streaming || configuring} onChange={e => savePreferences({ execute: e.target.checked })}/>{execute ? tr("执行：允许修改（持续开启）") : tr("讨论：只读工具")}</label><button className="send-button" aria-label={streaming ? tr("停止生成") : tr("发送消息")} disabled={!streaming && (!draft.message.trim() || !!conversation.archived || configuring)} onClick={() => streaming ? stop() : send()}>{streaming ? <Square size={15}/> : <ArrowUp size={18}/>}</button></div></div>
      {activity && !streaming && <small>{activity}</small>}
      <div className="model-row"><select aria-label={tr("对话服务")} disabled={streaming || configuring} value={provider} onChange={e => { const value = e.target.value, next = value === 'codex' ? '' : providers[value]?.model || ''; setProvider(value); setModel(next); configure({ provider: value, model: next }); }}><option value="codex">{tr("Codex · 会员")}</option><option value="openai">OpenAI · API</option><option value="deepseek">DeepSeek · API</option></select>{provider === 'codex' ? <select aria-label={tr("Codex 模型")} value={model} disabled={streaming || configuring} onChange={e => { setModel(e.target.value); configure({ model: e.target.value }); }}><option value="">{tr("官方默认模型")}</option>{codexInfo?.models?.map((m: any) => <option key={m.id} value={m.model}>{m.displayName || m.model}</option>)}</select> : <input aria-label={tr("模型 ID")} value={model} disabled={streaming || configuring} onChange={e => setModel(e.target.value)} onBlur={() => configure({ model })}/>}<label className="reasoning-choice"><span>{tr("推理强度")}</span><select aria-label={tr("推理强度")} value={preferences.reasoning_effort} disabled={streaming || configuring} onChange={e => savePreferences({ reasoning_effort: e.target.value })}><option value="">{tr("模型默认")}</option>{efforts.map(value => <option key={value} value={value}>{effortNames[value] || value} · {value}</option>)}{preferences.reasoning_effort && !efforts.includes(preferences.reasoning_effort) && <option value={preferences.reasoning_effort}>{tr("需重新选择：")}{preferences.reasoning_effort}</option>}</select></label></div><small className="reasoning-hint">{configuring ? tr("正在保存或读取会话偏好…") : provider === 'codex' ? tr("强度按 Codex 模型目录显示；未声明时使用默认值。") : tr("API 强度以模型支持为准；不支持时会报错，不自动降级或重试。")}</small>
    </div>
  </>;
}
