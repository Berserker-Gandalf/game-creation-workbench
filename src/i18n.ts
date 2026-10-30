import english from './locales/en.json';
import serverEnglish from './locales/server-en.json';

export type Language = 'zh-CN' | 'en';
const requested = new URLSearchParams(window.location.search).get('lang');
let remembered = '';
try { remembered = localStorage.getItem('workbench-language') || ''; } catch {}
export const language: Language = (requested || remembered) === 'en' ? 'en' : 'zh-CN';
export const dateLocale = language === 'en' ? 'en-GB' : 'zh-CN';
const translations: Record<string, string> = { ...english, ...serverEnglish };

export function t(source: string, ...values: unknown[]): string {
  const text = language === 'en' && Object.hasOwn(translations, source) ? translations[source] : source;
  return text.replace(/\{(\d+)\}/g, (match, index) => Number(index) < values.length ? String(values[Number(index)]) : match);
}

const escaped = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const patterns = Object.entries(serverEnglish).filter(([key]) => /\{\d+\}/.test(key)).map(([key, value]) => ({
  expression: new RegExp('^' + key.split(/\{\d+\}/).map(escaped).join('([\\s\\S]*?)') + '$'),
  indices: [...key.matchAll(/\{(\d+)\}/g)].map(match => match[1]), value,
}));

export function serverText(value: unknown): string {
  if (typeof value !== 'string') return value == null ? '' : String(value);
  if (language !== 'en') return value;
  if (Object.hasOwn(translations, value)) return translations[value];
  for (const pattern of patterns) {
    const match = pattern.expression.exec(value);
    if (match) return pattern.value.replace(/\{(\d+)\}/g, (whole, index) => match[pattern.indices.indexOf(index) + 1] ?? whole);
  }
  return value;
}

export function presentApi(path: string, value: any): any {
  if (language !== 'en' || !value || typeof value !== 'object') return value;
  if (['/blender/config', '/tripo/config'].includes(path) && value.defaults) {
    const defaults = { ...value.defaults };
    for (const field of ['title', 'brief']) if (typeof defaults[field] === 'string') defaults[field] = serverText(defaults[field]);
    value = { ...value, defaults };
  }
  if (path === '/music/connection') value = { ...value, message: serverText(value.message) };
  return value;
}

export function changeLanguage(next: Language, page: string) {
  if (next === language) return;
  try { localStorage.setItem('workbench-language', next); sessionStorage.setItem('workbench-page', page); } catch {}
  const url = new URL(window.location.href); url.searchParams.set('lang', next);
  window.location.assign(url.href);
}

document.documentElement.lang = language;
document.title = t('游织工坊 · AI 独立游戏制作工作台');
