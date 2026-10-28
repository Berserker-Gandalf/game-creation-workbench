import { t as tr } from './i18n';
import { useEffect, useState } from 'react';
import { api } from './api';

const stateLabels: Record<string, string> = { draft: tr("草稿"), approved: tr("正式"), archived: tr("废弃"), todo: tr("待执行"), running: tr("进行中"), review: tr("待验收"), done: tr("已完成"), blocked: tr("受阻"), cancelled: tr("已取消") };

export function useCatalog(pid: string, section: string, query = '', kind = '', category = '', revision = '', handoff = false) {
  const key = JSON.stringify([pid, section, query, kind, category, handoff]);
  const [position, setPosition] = useState({ key, cursors: [0] });
  const cursors = position.key === key ? position.cursors : [0], before = cursors[cursors.length - 1];
  const [value, setValue] = useState<any>({ items: [], total: 0 }), [loading, setLoading] = useState(true), [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(''); setValue({ items: [], total: 0 });
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ q: query, kind, category, before: String(before), limit: '48', handoff: String(handoff) });
      api(`/projects/${pid}/${section === 'task-board' ? section : 'catalog/' + section}?${params}`, { signal: controller.signal }).then(v => { if (!controller.signal.aborted) setValue(v); }).catch(e => { if (!controller.signal.aborted) setError(e.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 120);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [key, before, revision]);
  return { ...value, loading, error, page: cursors.length,
    previous: () => setPosition({ key, cursors: cursors.slice(0, -1) }),
    next: () => setPosition({ key, cursors: [...cursors, value.next_before] }) };
}

export function CatalogPages({ catalog }: any) {
  return <div className="action-bar"><button disabled={catalog.loading || catalog.page <= 1} onClick={catalog.previous}>{tr("上一页")}</button><small>{catalog.loading ? tr("正在读取目录…") : tr("共 {0} 项 · 第 {1} 页", catalog.total, catalog.page)}</small><button disabled={catalog.loading || !catalog.next_before} onClick={catalog.next}>{tr("下一页")}</button>{catalog.error && <span role="alert">{catalog.error}</span>}</div>;
}

export function AssetChoice({ pid, value, change, label, disabled = false, exclude = '' }: any) {
  const [query, setQuery] = useState(''), [selected, setSelected] = useState<any>(null);
  const catalog = useCatalog(pid, 'assets', query, 'image');
  useEffect(() => { let active = true; setSelected(null); if (value) api(`/projects/${pid}/assets/${value}`).then(v => { if (active) setSelected(v); }).catch(() => {}); return () => { active = false; }; }, [pid, value]);
  const items = catalog.items.filter((a: any) => a.id !== exclude);
  return <div><input aria-label={tr("搜索") + label} value={query} disabled={disabled} onChange={e => setQuery(e.target.value)} placeholder={tr("搜索全部项目图片")}/><select aria-label={label} value={value} disabled={disabled || catalog.loading} onChange={e => change(e.target.value)}><option value="">{tr("不使用 / 请选择图片")}</option>{value && !items.some((a: any) => a.id === value) && <option value={value}>{selected?.name || value} {tr("· 当前选择")}</option>}{items.map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}</select><CatalogPages catalog={catalog}/></div>;
}

export function CatalogChecks({ pid, section, selected, pinned, change, disabled, exclude = '' }: any) {
  const [query, setQuery] = useState('');
  const catalog = useCatalog(pid, section, query);
  const [labels, setLabels] = useState<Record<string, any>>({});
  useEffect(() => { setLabels(old => Object.fromEntries(selected.map((id: string) => [id, catalog.items.find((v: any) => v.id === id) || pinned.find((v: any) => v.id === id) || old[id] || { id }]))); }, [selected.join(','), catalog.items]);
  return <><input aria-label={tr("搜索关联") + (section === 'assets' ? tr("资产") : section === 'tasks' ? tr("任务") : tr("设计"))} placeholder={tr("搜索全部项目记录")} value={query} onChange={e => setQuery(e.target.value)}/>
    <p className="hint">{tr("已选")}{selected.length} {tr("项；搜索或翻页会保留已有选择。")}</p>
    {selected.filter((id: string) => !catalog.items.some((x: any) => x.id === id)).map((id: string) => <label className="check-row" key={id}><input type="checkbox" checked disabled={disabled} onChange={() => change({ ...labels[id], id })}/>{labels[id]?.name || labels[id]?.title || id} {tr("· 已关联")}</label>)}
    {catalog.items.map((v: any) => <label className="check-row" key={v.id}><input type="checkbox" checked={selected.includes(v.id)} disabled={disabled || catalog.loading || v.id === exclude} onChange={() => change(v)}/><span>{v.name || v.title}<small>{section === 'documents' ? tr("当前v{0} · {1}", v.revision, stateLabels[v.authority] || v.authority) : section === 'tasks' ? stateLabels[v.status] || v.status : tr("选择时核对当前版本与哈希")}</small></span></label>)}<CatalogPages catalog={catalog}/></>;
}
