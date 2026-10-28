import { serverText } from './i18n';
import { t as tr, dateLocale } from './i18n';
import { useEffect, useState } from 'react';
import { ExternalLink, RefreshCw } from 'lucide-react';
import { api, post } from './api';

const names: Record<string, string> = { codex: tr("Codex · 会员额度"), suno: tr("Suno.cn · 积分"), tripo: tr("Tripo · API 积分"), deepseek: tr("DeepSeek · API 余额"), openai: tr("OpenAI · API 账单") };
const labels: Record<string, string> = { ok: tr("查询成功"), error: tr("本次查询未成功"), not_checked: tr("尚未查询"), unsupported: tr("未提供余额查询"), stale: tr("上次数据") };
const time = (value: string | null) => value ? new Date(value).toLocaleString(dateLocale) : tr("尚无成功记录");
const duration = (minutes: number | null) => minutes == null ? tr("服务额度窗口") : minutes >= 1440 ? tr("{0} 天窗口", minutes / 1440) : minutes >= 60 ? tr("{0} 小时窗口", minutes / 60) : tr("{0} 分钟窗口", minutes);

export default function Accounts({ run, busy }: any) {
  const [values, setValues] = useState<any>(null);
  useEffect(() => { run(async () => setValues(await api('/accounts'))); }, []);
  const refresh = (providers?: string[]) => run(async () => setValues(await post('/accounts/refresh', providers ? { providers } : {})), tr("额度读取已结束；失败项保留上次数据，不会生成或消耗重置次数"));
  return <div className="page-content accounts-page"><div className="card management-intro"><h2>{tr("看清额度，再安排创作。")}</h2><p>{tr("这里显示账户级额度，并非当前项目的独占预算。不同服务的百分比、积分和货币分别显示，不互相换算。")}</p><button className="secondary" disabled={busy} onClick={() => refresh()}><RefreshCw size={15}/>{tr("刷新所有服务")}</button><small>{tr("仅在你点击时查询；每项有独立超时。未返回、未配置或失败不会显示为零。")}</small></div>
    <div className="account-grid">{Object.entries(names).map(([provider, title]) => {
      const item = values?.[provider], data = item?.data;
      return <section className="card account-card" key={provider}><div className="section-heading"><h2>{title}</h2><span className={'status ' + (item?.status === 'ok' ? 'review' : 'blocked')}>{labels[item?.status] || tr("读取记录")}</span></div>
        {item?.stale && <p className="intake-warning">{tr("当前显示上次成功数据，不能作为实时额度。")}</p>}
        {provider === 'codex' && <>{data?.windows?.map((w: any, i: number) => <div className="quota-window" key={i}><div><strong>{w.remaining_percent}{tr("% 剩余")}</strong><span>{w.bucket} · {duration(w.window_minutes)}</span></div><div className="quota-meter"><span style={{ width: `${w.remaining_percent}%` }}/></div><small>{tr("重置：")}{w.resets_at == null ? tr("服务未返回") : new Date(w.resets_at * 1000).toLocaleString(dateLocale)}</small></div>)}{data?.monthly?.map((m: any, i: number) => <p key={i}>{tr("服务月度限制：")}{m.remainingPercent ?? tr("未知")}{tr("% 剩余 ·")}{m.bucket}</p>)}{data?.credits?.map((c: any, i: number) => <p key={i}>{tr("服务 credits：")}{c.unlimited ? tr("服务标为 unlimited") : c.balance ?? tr("未返回余额")} · {c.bucket}</p>)}</>}
        {provider === 'suno' && <div className="balance-value">{data?.points ?? '—'}<small>{tr("积分")}</small></div>}
        {provider === 'tripo' && <><div className="balance-value">{data?.balance ?? '—'}<small>{tr("可用 API 积分")}</small></div><p className="hint">{tr("冻结：")}{data?.frozen ?? tr("未返回")} · {data?.region === 'global' ? tr("全球站") : data?.region === 'cn' ? tr("中国站") : tr("区域待查询")}</p></>}
        {provider === 'deepseek' && (data?.balances?.length ? data.balances.map((b: any) => <div key={b.currency}><div className="balance-value">{b.total_balance}<small>{b.currency}</small></div><p className="hint">{tr("赠送：")}{b.granted_balance ?? tr("未返回")} {tr("· 充值：")}{b.topped_up_balance ?? tr("未返回")}</p></div>) : <div className="balance-value">—<small>{tr("服务余额未确认")}</small></div>)}
        {provider === 'openai' ? <><p className="hint">{tr("当前适配没有可用的通用现金余额查询。已有对话/图片用量记录保留，不能据此估算账户余额。")}</p><a className="text-button" href="https://platform.openai.com/settings/organization/billing/overview" target="_blank" rel="noreferrer">{tr("打开官方账单台")}<ExternalLink size={13}/></a></> : <button className="secondary" disabled={busy} onClick={() => refresh([provider])}><RefreshCw size={13}/>{tr("查询此账户")}</button>}
        {item?.message && <p className="hint">{serverText(item.message)}</p>}<small>{tr("上次成功：")}{time(item?.checked_at)}</small>
      </section>;
    })}</div>
  </div>;
}
