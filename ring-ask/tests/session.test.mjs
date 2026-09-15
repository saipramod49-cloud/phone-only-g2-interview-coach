import test from 'node:test';import assert from 'node:assert/strict';
import {AnswerHistory,RingInput,inputGestures,readingFrame,wrap} from '../src/session.mjs';
import {Recorder} from '../src/controller.mjs';
const tick=()=>new Promise(r=>setImmediate(r));
function clock(){let now=0,id=0;const jobs=new Map();return {now:()=>now,set:(f,ms)=>{jobs.set(++id,{f,at:now+ms});return id;},clear:i=>jobs.delete(i),advance(ms){now+=ms;for(const [i,j] of jobs)if(j.at<=now){jobs.delete(i);j.f();}}};}
test('zero enum input reaches recorder, two deliberate taps capture exactly once',async()=>{
 const c=clock(),calls=[],submitted=[];const r=new Recorder(async on=>{calls.push(on);return true;},()=>{},async pcm=>submitted.push(pcm));
 const input=new RingInput(type=>{if(type===0)void r.dispatch(0);},c);
 for(const type of inputGestures({textEvent:{containerID:1}}))input.feed(type);c.advance(450);await r.queue;
 assert.equal(r.state,'listening');r.audio(new Uint8Array(9600));c.advance(1500);
 for(const type of inputGestures({listEvent:{}}))input.feed(type);c.advance(450);await r.queue;await tick();
 assert.deepEqual(calls,[true,false]);assert.equal(submitted.length,1);
});
test('double click cancels pending tap and repeated firmware event changes one page only',()=>{
 const c=clock(),actions=[],input=new RingInput(t=>actions.push(t),c);
 input.feed(0);c.advance(100);input.feed(0);c.advance(30);input.feed(3);c.advance(600);
 assert.deepEqual(actions,[3]);
 input.feed(0);c.advance(100);input.feed(3);c.advance(600);assert.deepEqual(actions,[3,3]);
});
test('third tap changes to previous page without leaking a single tap',()=>{
 const c=clock(),actions=[],input=new RingInput(t=>actions.push(t),c);
 input.feed(0);c.advance(80);input.feed(3);c.advance(80);input.feed(0);c.advance(600);
 assert.deepEqual(actions,[11]);
 input.feed(0);c.advance(80);input.feed(0);c.advance(80);input.feed(0);c.advance(600);
 assert.deepEqual(actions,[11,11]);
});
test('hold/release cancels leading and trailing taps',()=>{
 const c=clock(),actions=[],input=new RingInput(t=>actions.push(t),c);
 input.feed(0);c.advance(200);input.feed(9);c.advance(300000);input.feed(10);input.feed(0);c.advance(1000);
 assert.deepEqual(actions,[9,10]);
});
test('second tap while microphone starts waits and then submits',async()=>{
 let open;const submissions=[];const r=new Recorder(async on=>{if(on)await new Promise(resolve=>open=resolve);return true;},()=>{},async pcm=>submissions.push(pcm));
 const start=r.dispatch(0);await tick();r.audio(new Uint8Array(9600));const stop=r.dispatch(0);open();await Promise.all([start,stop]);await tick();assert.equal(submissions.length,1);
});
test('history retains answers and positions without replacing content during capture',()=>{
 const h=new AnswerHistory();h.add('first?','first answer');h.add('second?','second answer');h.move(-1);assert.equal(h.current.question,'first?');h.move(1);assert.equal(h.current.answer,'second answer');
 const restored=new AnswerHistory(JSON.parse(JSON.stringify(h.entries)));assert.equal(restored.current.question,'second?');assert.equal(restored.entries.length,2);
});
test('both layouts keep every panel inside the lens and every answer page reachable',()=>{
 for(const layout of ['top','side'])for(const font of ['native','18','22','26','30'])for(const width of [360,440,576]){
  const p={font,width,rows:10,words:'auto',x:100};const entry={question:'What is the correct approach to investigate data?',answer:'Read the source and validate the target. '.repeat(30)};
  const first=readingFrame(entry,0,p,t=>t.length*10,layout);let text='';
  for(let i=0;i<first.count;i++){const f=readingFrame(entry,i,p,t=>t.length*10,layout);text+=f.answer+' ';for(const panel of f.panels){assert.ok(panel.x>=0&&panel.x+panel.width<=576);assert.ok(panel.y>=0&&panel.y+panel.height<=288);}}
  assert.equal(text.replace(/\s/g,''),entry.answer.replace(/\s/g,''));assert.ok(first.question);assert.match(first.header,/Page 1/);
 }
});
test('code indentation, blank lines and tokens survive wrapping across pages',()=>{
 const code='def newest(rows):\n    if rows:\n        return max(rows)\n\n    return None';
 const wrapped=wrap('```python\n'+code+'\n```',500,s=>s.length*8);
 assert.equal(wrapped.join('\n'),code);
});
test('audio-only envelopes never imply a tap',()=>assert.deepEqual(inputGestures({audioEvent:{audioPcm:[]}}),[]));

test('history ignores obsolete startup instructions and tolerates corrupt storage',()=>{
 assert.equal(new AnswerHistory({}).entries.length,0);
 const history=new AnswerHistory([{question:'',answer:'Tap to record a question. Double-tap to finish.'},{question:'What is SQL?',answer:'A query language.'}]);
 assert.equal(history.entries.length,1);
 assert.equal(history.current.question,'What is SQL?');
});
