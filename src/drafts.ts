import { t as tr } from './i18n';
export function loadLocal<T>(key: string, fallback: T): T {
  try { const value = localStorage.getItem('workbench:' + key); return value === null ? fallback : JSON.parse(value); }
  catch { return fallback; }
}

export function saveLocal(key: string, value: unknown) {
  try { localStorage.setItem('workbench:' + key, JSON.stringify(value)); }
  catch { throw new Error(tr("浏览器无法保存草稿，请复制当前内容后再离开页面")); }
}

export function clearLocal(key: string) {
  try { localStorage.removeItem('workbench:' + key); }
  catch { throw new Error(tr("浏览器无法清除草稿，请核对已保存内容后再离开页面")); }
}
