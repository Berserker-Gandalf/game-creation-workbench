import test from 'node:test';
import assert from 'node:assert/strict';
await import('../examples/beacon-route/game.js');
const {create,move}=globalThis.BeaconRules;
const play=()=>({...create(),status:'playing'});

test('an actual twelve-move route collects three lights and wins with four fuel',()=>{
  let state=play();
  for(const tile of [15,10,5,0,1,2,3,4,9,14,9,4]) state=move(state,tile);
  assert.equal(state.status,'won'); assert.equal(state.collected.length,3); assert.equal(state.fuel,4); assert.equal(state.steps,12);
  assert.equal(move(state,3),state);
});
test('invalid, diagonal and row-wrapping input cannot move the boat',()=>{
  const state=play();
  for(const target of [-1,25,1.5,'15'])assert.equal(move(state,target),state);
  for(const target of [14,0,24,21-5])assert.equal(move(state,target).position,20);
  assert.equal(move({...state,position:4},5).position,4);
});
test('storms consume extra fuel without moving, and fuel exhaustion loses',()=>{
  let state=move(play(),15);state=move(state,16);
  assert.equal(state.position,15);assert.equal(state.fuel,13);assert.equal(state.message,'hit');
  state=move({...state,fuel:2},16);assert.equal(state.status,'lost');assert.equal(state.fuel,0);
});
test('title and pause reject movement; a fresh game restores the initial state',()=>{
  const title=create();assert.equal(move(title,15),title);
  const paused={...play(),status:'paused'};assert.equal(move(paused,15),paused);
  assert.deepEqual(create(),title);
});
test('the beacon requires all lights; arriving on the last fuel can win',()=>{
  const atTop={...play(),position:3,fuel:1};assert.equal(move(atTop,4).status,'lost');
  assert.equal(move({...atTop,collected:[10,2,14]},4).status,'won');
});
