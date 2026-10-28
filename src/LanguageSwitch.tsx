import { Globe2 } from 'lucide-react';
import { changeLanguage, language, t as tr } from './i18n';

export default function LanguageSwitch({ disabled, page }: { disabled: boolean; page: string }) {
  return <label className="language-switch"><Globe2 size={15} aria-hidden="true"/><select aria-label={tr('界面语言')} value={language} disabled={disabled} onChange={e => changeLanguage(e.target.value === 'en' ? 'en' : 'zh-CN', page)}>
    <option value="zh-CN">简体中文</option><option value="en">English</option>
  </select></label>;
}
