import { t as tr } from './i18n';
import { useState } from 'react';
import Blender from './Blender';
import Tripo from './Tripo';
import { loadLocal, saveLocal } from './drafts';

export default function Modeling(props: any) {
  const key = 'modeling-source:' + props.data.project.id;
  const [source, setSource] = useState(() => loadLocal(key, 'blender'));
  return <><div className="modeling-sources"><button className={source === 'blender' ? 'selected' : ''} onClick={() => { setSource('blender'); try { saveLocal(key, 'blender'); } catch (e) { props.onError((e as Error).message); } }}>{tr("本机 Blender · 参数化草稿")}</button><button className={source === 'tripo' ? 'selected' : ''} onClick={() => { setSource('tripo'); try { saveLocal(key, 'tripo'); } catch (e) { props.onError((e as Error).message); } }}>{tr("Tripo · 云端生成")}</button></div>{source === 'tripo' ? <Tripo {...props}/> : <Blender {...props}/>}</>;
}
