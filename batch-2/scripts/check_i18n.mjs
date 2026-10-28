import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const english=JSON.parse(fs.readFileSync('src/locales/en.json','utf8'));
const server=JSON.parse(fs.readFileSync('src/locales/server-en.json','utf8'));
const catalog={...english,...server};
const placeholders=value=>[...value.matchAll(/\{(\d+)\}/g)].map(m=>m[1]).sort().join(',');
for(const [key,value] of Object.entries(catalog)) {
  assert.equal(placeholders(key),placeholders(value),`Placeholder mismatch: ${key}`);
  assert(!/[\u3400-\u9fff]/.test(value),`Untranslated English value: ${key}`);
}
let calls=0;
for(const name of fs.readdirSync('src').filter(v=>/\.tsx?$/.test(v)&&v!=='i18n.ts')) {
  const file=ts.createSourceFile(name,fs.readFileSync('src/'+name,'utf8'),ts.ScriptTarget.Latest,true,name.endsWith('.tsx')?ts.ScriptKind.TSX:ts.ScriptKind.TS);
  function visit(node) {
    if(ts.isStringLiteral(node)&&/[\u3400-\u9fff]/.test(node.text)) {
      assert(ts.isCallExpression(node.parent)&&['tr','t'].includes(node.parent.expression.getText(file))&&node.parent.arguments[0]===node,`Raw interface string: ${name}: ${node.text}`);
      assert(Object.hasOwn(catalog,node.text),`Missing translation: ${name}: ${node.text}`); calls++;
    }
    if(ts.isJsxText(node)&&/[\u3400-\u9fff]/.test(node.text)) assert(name==='LanguageSwitch.tsx'&&node.text.trim()==='简体中文',`Raw JSX label: ${name}: ${node.text}`);
    ts.forEachChild(node,visit);
  }
  visit(file);
}

function runtime(lang, storageFails=false) {
  const writes=[], exported={}; let assigned='';
  const storage={getItem:()=>lang,setItem:(...args)=>{if(storageFails)throw Error('Storage disabled');writes.push(args);}};
  const context={exports:exported,require:name=>name.endsWith('server-en.json')?server:english,
    URL,URLSearchParams,window:{location:{search:'?lang='+lang,href:'http://127.0.0.1:8765/?lang='+lang,assign:url=>{assigned=url;}}},
    localStorage:storage,sessionStorage:storage,document:{documentElement:{},title:''}};
  const compiled=ts.transpileModule(fs.readFileSync('src/i18n.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText;
  vm.runInNewContext(compiled,context);
  return {api:exported,context,writes,get assigned(){return assigned;}};
}
const en=runtime('en'), zh=runtime('zh-CN');
assert.equal(en.context.document.documentElement.lang,'en');
assert.equal(zh.api.t('项目总览'),'项目总览');
assert.equal(en.api.t('项目总览'),'Overview');
assert.equal(en.api.t('共 {0} 项 · 第 {1} 页',84,2),'Items: 84 · Page 2');
assert.equal(en.api.serverText('fastapi 依赖'),'fastapi dependency');
assert.equal(en.api.serverText('可用约 123.4 GiB'),'About 123.4 GiB available');
assert.equal(en.api.serverText('前置任务未完成：保留原文'),'Prerequisite incomplete: 保留原文');
assert.equal(en.api.serverText('Unknown provider response'),'Unknown provider response');
assert.equal(en.api.serverText('constructor'),'constructor');
assert.equal(en.api.t('__proto__'),'__proto__');
const userData={project:{name:'保留原文'},documents:[{title:'项目总览',content:'设计正文不翻译'}],messages:[{content:'原始交流'}]};
assert.strictEqual(en.api.presentApi('/projects/project-id',userData),userData);
assert.equal(en.api.presentApi('/blender/config',{defaults:{title:'低模探索者'}}).defaults.title,'Low-poly explorer');
assert.deepEqual(Object.keys(en.api.presentApi('/tripo/config',{defaults:{title:'Tripo 角色方案',mode:'text'}}).defaults).sort(),['mode','title']);
const webui={defaults:{width:512,height:512}};
assert.strictEqual(en.api.presentApi('/webui/config',webui),webui);
en.api.changeLanguage('zh-CN','tasks');
assert.equal(new URL(en.assigned).searchParams.get('lang'),'zh-CN');
assert(en.writes.some(([key,value])=>key==='workbench-page'&&value==='tasks'));
const fallback=runtime('en',true); fallback.api.changeLanguage('zh-CN','assets'); assert(fallback.assigned.includes('lang=zh-CN'));

// Exercise the actual presentation expressions, including text that collides with UI keys.
const chat=ts.createSourceFile('Chat.tsx',fs.readFileSync('src/Chat.tsx','utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let composerValue='';
function composer(node) {
  if(ts.isJsxAttribute(node)&&node.name.getText(chat)==='value'&&node.initializer?.expression?.getText(chat).includes('draft.message')) composerValue=node.initializer.expression.getText(chat);
  ts.forEachChild(node,composer);
}
composer(chat); assert(composerValue,'Chat composer value not found');
for(const message of ['项目总览','No translation','前置任务未完成：保留原文']) assert.equal(vm.runInNewContext(composerValue,{draft:{message},serverText:en.api.serverText}),message);
const management=fs.readFileSync('src/Management.tsx','utf8');
assert(management.includes('<p>{s.note}</p>'),'User snapshot notes must remain original');

// Run the App's real project-selection initializer and effect with blocked storage.
const main=ts.createSourceFile('main.tsx',fs.readFileSync('src/main.tsx','utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let projectInitial='',projectEffect='';
function projectStorage(node) {
  if(ts.isVariableDeclaration(node)&&node.name.getText(main).includes('setProjectId')) projectInitial=node.initializer.arguments[0].getText(main);
  if(ts.isCallExpression(node)&&node.expression.getText(main)==='useEffect'&&node.arguments[0]?.getText(main).includes("localStorage.setItem('workbench-project'")) projectEffect=node.arguments[0].getText(main);
  ts.forEachChild(node,projectStorage);
}
projectStorage(main);
assert(projectInitial&&projectEffect,'Project preference paths not found');
const blocked={getItem:()=>{throw Error('Storage blocked');},setItem:()=>{throw Error('Storage blocked');}};
assert.equal(vm.runInNewContext(`(${projectInitial})()`,{localStorage:blocked}),'');
let refreshed=false,warned=false;
vm.runInNewContext(`(${projectEffect})()`,{localStorage:blocked,projectId:'fixture',setData:()=>{},setAttachment:()=>{},setError:()=>{warned=true;},tr:en.api.t,refresh:()=>{refreshed=true;return Promise.resolve();}});
assert(refreshed&&warned,'Storage failure must warn and still load the selected project');
console.log(`Language checks passed: ${Object.keys(catalog).length} translated strings, ${calls} source uses, placeholders, messages, user data and preference fallback.`);
