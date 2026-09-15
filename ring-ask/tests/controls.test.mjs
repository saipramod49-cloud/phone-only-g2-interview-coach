import test from 'node:test';
import assert from 'node:assert/strict';
import {Recorder,gesture,gestures,pages,MAX_BYTES,controlAction,recoveryDelay} from '../src/controller.mjs';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup(mic=async()=>true,submit=async()=>{}) {const messages=[];return {recorder:new Recorder(mic,x=>messages.push(x),submit),messages};}
test('tap → audio → double tap submits once and ignores idle audio',async()=>{
  const calls=[],audio=[];const {recorder:r}=setup(async x=>{calls.push(x);return true;},async x=>audio.push(x));
  r.audio(new Uint8Array(100));await r.dispatch(0);r.audio(new Uint8Array(6400));await r.dispatch(3);await tick();
  assert.deepEqual(calls,[true,false]);assert.equal(audio.length,1);assert.equal(audio[0].length,6400);assert.equal(r.state,'ready');
});
test('release during pending microphone start still closes and submits',async()=>{
  let opened; const calls=[],audio=[];
  const {recorder:r}=setup(async x=>{calls.push(x);if(x)await new Promise(resolve=>opened=resolve);return true;},async x=>audio.push(x));
  r.mode='hold';const start=r.dispatch(9);await tick();r.audio(new Uint8Array(6400));const stop=r.dispatch(10);opened();await Promise.all([start,stop]);await tick();
  assert.deepEqual(calls,[true,false]);assert.equal(audio.length,1);assert.equal(r.state,'ready');
});
test('microphone failure cannot submit stale audio',async()=>{
  const {recorder:r,messages}=setup(async()=>false);await r.dispatch(0);await r.dispatch(3);assert.equal(r.state,'ready');assert.match(messages.at(-1),/unavailable/);
});
test('duplicate tap while listening does not restart capture',async()=>{
  let opens=0;const {recorder:r}=setup(async x=>{if(x)opens++;return true;});await r.dispatch(0);await r.dispatch(0);assert.equal(opens,1);await r.cancel();
});
test('cancel discards captured question without submitting',async()=>{
  let submissions=0;const {recorder:r}=setup(async()=>true,async()=>submissions++);await r.dispatch(0);r.audio(new Uint8Array(6400));await r.dispatch(5);await r.dispatch(3);assert.equal(submissions,0);assert.equal(r.bytes,0);
});
test('audio cap submits a bounded recording',async()=>{
  let size;const {recorder:r}=setup(async()=>true,async x=>size=x.length);await r.dispatch(0);r.audio(new Uint8Array(MAX_BYTES+100));await r.queue;await tick();assert.equal(size,MAX_BYTES);
});
test('cancellation stays responsive while answer is processing',async()=>{
  let finish;const {recorder:r}=setup(async()=>true,()=>new Promise(resolve=>finish=resolve));await r.dispatch(0);r.audio(new Uint8Array(6400));await r.dispatch(3);assert.equal(r.state,'busy');await r.dispatch(5);assert.equal(r.state,'ready');finish();await tick();
});
test('SDK zero normalization is only a tap for an input envelope',()=>{
  assert.equal(gesture({textEvent:{containerID:1}}),0);assert.equal(gesture({audioEvent:{}}),null);assert.equal(gesture({sysEvent:{eventType:10}}),10);
});
test('input gestures survive a simultaneous non-input system event',()=>{
  assert.deepEqual(gestures({textEvent:{eventType:2},sysEvent:{eventType:8}}),[2]);
  assert.deepEqual(gestures({sysEvent:{eventType:3}}),[3]);
});
test('pagination keeps long answers readable and splits oversized words',()=>{
  const result=pages('A '.repeat(500)+'B'.repeat(100));assert.ok(result.length>1);for(const page of result)for(const line of page.split('\n'))assert.ok(line.length<=40);
});

test('ring routing supports tap, hold, release and swipes',()=>{
 assert.equal(controlAction(0),'listen');assert.equal(controlAction(10),'answer');
 assert.equal(controlAction(1),'previous');assert.equal(controlAction(2),'next');
 for(const type of [3,4,5,6,7,null,undefined])assert.equal(controlAction(type),null);
 for(const type of [0,1,2,3,9,10])assert.equal(controlAction(type,false),null);
});
test('hold and release cannot open the microphone in restored tap mode',async()=>{
 const calls=[];const {recorder:r}=setup(async on=>{calls.push(on);return true;});
 await r.dispatch(9);await r.dispatch(10);assert.deepEqual(calls,[]);
 await r.dispatch(0);r.audio(new Uint8Array(6400));await r.dispatch(3);await tick();assert.deepEqual(calls,[true,false]);
});

test('tap mode starts on first tap and submits on second tap',async()=>{
 const calls=[],audio=[];const {recorder:r}=setup(async on=>{calls.push(on);return true;},async pcm=>audio.push(pcm));r.mode='tap';
 await r.dispatch(0);r.audio(new Uint8Array(6400));assert.equal(r.state,'listening');
 await r.dispatch(0);await tick();assert.deepEqual(calls,[true,false]);assert.equal(audio.length,1);
});
test('hold mode starts on hold and submits on release',async()=>{
 const calls=[];const {recorder:r}=setup(async on=>{calls.push(on);return true;});r.mode='hold';
 await r.dispatch(9);r.audio(new Uint8Array(6400));await r.dispatch(10);await tick();assert.deepEqual(calls,[true,false]);
});

test('connection recovery backs off but continues indefinitely',()=>{
 assert.deepEqual([0,1,2,3,4,5,20].map(recoveryDelay),[1000,2000,4000,8000,12000,15000,15000]);
});
