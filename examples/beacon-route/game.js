/* Original sample game. No account, network request or third-party game assets. */
(() => {
  const seeds = [10, 2, 14], storms = [16, 12, 8];
  const create = () => ({position:20,fuel:16,steps:0,collected:[],visited:[20],status:'title',message:'welcome'});
  function move(state, target) {
    if (state.status !== 'playing' || !Number.isInteger(target) || target < 0 || target > 24) return state;
    const adjacent = Math.abs(target % 5 - state.position % 5) + Math.abs(Math.floor(target / 5) - Math.floor(state.position / 5)) === 1;
    if (!adjacent) return {...state,message:'adjacent'};
    const hit = storms.includes(target), position = hit ? state.position : target;
    const collected = !hit && seeds.includes(position) ? [...new Set([...state.collected,position])] : [...state.collected];
    const next = {...state,position,collected,fuel:Math.max(0,state.fuel-(hit?2:1)),steps:state.steps+1,visited:[...new Set([...state.visited,position])],message:hit?'hit':collected.length>state.collected.length?'found':'sail'};
    if (position === 4 && collected.length === 3) next.status = 'won';
    else if (!next.fuel) next.status = 'lost';
    else if (position === 4) next.message = 'needLights';
    return next;
  }
  globalThis.BeaconRules = {create,move,seeds,storms};
  if (typeof document === 'undefined') return;
  const copy = {
    title:['灯塔航线','Beacon Route'],subtitle:['在风暴之间，找回回家的光。','Find your way home between the storms.'],description:['规划一条航线，收集三枚光种，再抵达东北角的灯塔。每一步消耗一点燃料；撞上风暴会额外消耗燃料。','Collect three light seeds, then reach the lighthouse in the northeast. Every move uses fuel; a storm costs extra.'],light:['光种','Light'],storm:['风暴','Storm'],beacon:['灯塔','Beacon'],controls:['方向键或点击相邻海格移动 · P / Esc 暂停 · R 重来','Arrow keys or click an adjacent tile · P / Esc to pause · R to restart'],note:['原创浏览器原型 · 无需账号 · 无外部模型调用','Original browser prototype · No account · No model calls'],fuel:['燃料','Fuel'],collected:['光种','Lights'],steps:['步数','Moves'],pause:['暂停','Pause'],restart:['重新开始','Restart'],footer:['小型、可复现、可玩的工作台案例','A small, reproducible, playable workbench case'],welcome:['先规划航线，再开始航行。','Plan the route before you sail.'],adjacent:['只能移动到上下左右相邻的海格。','Move to an adjacent tile, with no diagonals.'],hit:['风暴挡住航线，消耗了 2 点燃料。','A storm blocked the route and cost 2 fuel.'],found:['收集到一枚光种，继续寻找归途。','A light seed collected. Keep finding your way.'],sail:['航线已记录，留意剩余燃料。','Route recorded. Watch your remaining fuel.'],needLights:['先收集全部三枚光种，再点亮灯塔。','Collect all three light seeds before lighting the beacon.'],titleTitle:['点亮归途','Light the way home'],titleBody:['十六格燃料，三枚光种。先看好航线，再出发。','Sixteen fuel, three lights. Find a route, then set sail.'],titleButton:['开始航行','Set sail'],pausedTitle:['让风暴等一会','The storm can wait'],pausedBody:['游戏已暂停。继续后，航线和燃料保持原样。','Paused. Your route and fuel will be waiting.'],pausedButton:['继续航行','Resume'],wonTitle:['灯塔亮了','The beacon is lit'],wonBody:['三枚光种已归位，航线已经完成。','All three lights are home. Your route is complete.'],wonButton:['再玩一局','Play again'],lostTitle:['燃料用尽','Out of fuel'],lostBody:['试着绕开风暴，用更短的路线连接三枚光种。','Avoid the storms and find a shorter route between the lights.'],lostButton:['重新规划','Try again']
  };
  let state = create(), language = 'zh';
  const text = key => copy[key][language === 'en' ? 1 : 0];
  const board = document.querySelector('#board');
  for (let index=0;index<25;index++) { const button=document.createElement('button'); button.className='tile'; button.dataset.cell=index; button.addEventListener('click',()=>{state=move(state,index);render();}); board.append(button); }
  function render() {
    document.documentElement.lang=language==='zh'?'zh-CN':'en';
    document.querySelectorAll('[data-text]').forEach(node=>{node.textContent=text(node.dataset.text);});
    document.querySelector('#language').textContent=language==='zh'?'English':'简体中文';
    for (const key of ['fuel','steps']) document.querySelector('#'+key).textContent=state[key];
    document.querySelector('#collected').textContent=state.collected.length;
    document.querySelector('#message').textContent=text(state.message);
    board.querySelectorAll('button').forEach((button,index)=>{
      const near=Math.abs(index%5-state.position%5)+Math.abs(Math.floor(index/5)-Math.floor(state.position/5))===1;
      button.className='tile'+(state.visited.includes(index)?' visited':'')+(index===state.position?' current':near?' near':'');
      button.replaceChildren();
      const icon=document.createElement('span');
      if(index===state.position){icon.className='boat';icon.setAttribute('aria-hidden','true');}
      else {icon.className=storms.includes(index)?'storm':seeds.includes(index)?(state.collected.includes(index)?'collected':'seed'):index===4?'beacon':'';icon.textContent=storms.includes(index)?'≈':seeds.includes(index)?(state.collected.includes(index)?'·':'✦'):index===4?'♜':'';}
      button.append(icon);
      const detail=index===state.position?(language==='zh'?'船':'Boat'):storms.includes(index)?text('storm'):seeds.includes(index)?text('light'):index===4?text('beacon'):(language==='zh'?'海面':'Sea');
      button.setAttribute('aria-label',`${language==='zh'?'海格':'Tile'} ${Math.floor(index/5)+1},${index%5+1} · ${detail}`);
    });
    const overlay=document.querySelector('#overlay'); overlay.hidden=state.status==='playing';
    if(!overlay.hidden){const key=state.status==='title'?'title':state.status==='paused'?'paused':state.status;for(const part of ['title','body'])document.querySelector('#overlay-'+part).textContent=text(key+part[0].toUpperCase()+part.slice(1));document.querySelector('#primary').textContent=text(key+'Button');}
  }
  function start(){state=state.status==='paused'?{...state,status:'playing'}:{...create(),status:'playing'};render();board.querySelector(`[data-cell="${state.position}"]`).focus();}
  function pause(){if(['playing','paused'].includes(state.status)){state={...state,status:state.status==='playing'?'paused':'playing'};render();if(state.status==='paused')document.querySelector('#primary').focus();else board.querySelector(`[data-cell="${state.position}"]`).focus();}}
  document.querySelector('#primary').addEventListener('click',start);
  document.querySelector('#restart').addEventListener('click',()=>{state=create();render();document.querySelector('#primary').focus();});
  document.querySelector('#pause').addEventListener('click',pause);
  document.querySelector('#language').addEventListener('click',()=>{language=language==='zh'?'en':'zh';render();});
  document.addEventListener('keydown',event=>{const delta={ArrowUp:-5,ArrowDown:5,ArrowLeft:-1,ArrowRight:1}[event.key];if(delta!==undefined){event.preventDefault();state=move(state,state.position+delta);render();}else if(event.key==='Escape'||event.key.toLowerCase()==='p'){event.preventDefault();pause();}else if(event.key.toLowerCase()==='r'){state=create();render();document.querySelector('#primary').focus();}});
  render(); document.querySelector('#primary').focus();
})();
