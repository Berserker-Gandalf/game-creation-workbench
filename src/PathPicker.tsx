import { useState } from 'react';
import { FolderOpen } from 'lucide-react';
import { post } from './api';
import { t as tr } from './i18n';

export default function PathPicker({ purpose, value = '', change, run, disabled = false }: { purpose: string; value?: string; change: (path: string) => void; run: any; disabled?: boolean }) {
  const [opening, setOpening] = useState(false);
  return <button type="button" className="secondary path-picker" disabled={disabled || opening} onClick={() => run(async () => {
    setOpening(true);
    try { const result = await post('/system/path-picker', { purpose, initial: value }); if (result.path) change(result.path); }
    finally { setOpening(false); }
  })}><FolderOpen size={14}/>{opening ? tr('请在系统窗口选择') : tr('浏览选择')}</button>;
}
