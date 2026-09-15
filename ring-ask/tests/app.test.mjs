import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import fs from 'node:fs';
import ts from 'typescript';
import * as controller from '../src/controller.mjs';import * as session from '../src/session.mjs';import * as reader from '../src/reader.mjs';
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function element(){return {value:'',textContent:'',disabled:false,open:false,checked:false,children:[],style:{},classList:{toggle(){}},replaceChildren(){this.children=[];},append(n){this.children.push(n);},setPointerCapture(){}};}
async function app(mode='tap'){
 const ids=new Map([...fs.readFileSync(new URL('../index.html',import.meta.url),'utf8').matchAll(/id="([^"]+)"/g)].map(m=>[m[1],element()]));
 const storage=new Map([['ring-ask-settings',JSON.stringify({token:'test',backend:'https://test.invalid',listenMode:mode,reading:{font:'native',rows:10,words:'auto'}})],['ring-ask-history',JSON.stringify([{question:'Old question?',answer:'Old answer kept safe.',time:1}])]]);
 const mic=[],requests=[],pages=[],timeouts=new Set(),intervals=new Set();let eventHandler;
 const bridge={audioControl:async on=>{mic.push(on);return true;},onEvenHubEvent:f=>eventHandler=f,onDeviceStatusChanged(){},getLocalStorage:async()=>'',setLocalStorage:async()=>true,createStartUpPageContainer:async p=>{pages.push(p);return 0;},rebuildPageContainer:async p=>{pages.push(p);return true;},textContainerUpgrade:async()=>true};
 class Model{constructor(p){Object.assign(this,p);}}
 const sdk={waitForEvenAppBridge:async()=>bridge,CreateStartUpPageContainer:Model,RebuildPageContainer:Model,MenuContainerProperty:Model,MenuItemProperty:Model,TextContainerProperty:Model,TextContainerUpgrade:Model,AudioInputSource:{Glasses:1}};
 const context=vm.createContext({console,Blob,AbortController,TextDecoder,Uint8Array,performance,URL,
  document:{getElementById:id=>ids.get(id),createElement:element,addEventListener(){},visibilityState:'visible'},window:{addEventListener(){}},navigator:{onLine:true},
  localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
  setTimeout:(f,ms)=>{const t=setTimeout(f,ms);timeouts.add(t);return t;},clearTimeout:t=>{clearTimeout(t);timeouts.delete(t);},setInterval:(f,ms)=>{const t=setInterval(f,ms);intervals.add(t);return t;},clearInterval,
  fetch:async(url,options)=>{
   if(url.endsWith('/api/health'))return {ok:true,json:async()=>({configured:true,model:'test',version:'0.7.0'})};
   requests.push(options);return new Response([
    {type:'transcript',text:'New SQL question?',transcriptionMs:20},
    {type:'delta',text:'```sql\nSELECT customer_id\nFROM customers;\n```\n\nKeep the identifiers.'},{type:'done',model:'test'}].map(x=>JSON.stringify(x)).join('\n'));
  },exports:{},require:name=>{
   if(name==='@evenrealities/even_hub_sdk')return sdk;
   if(name==='./controller.mjs')return controller;if(name==='./session.mjs')return session;if(name==='./reader.mjs')return reader;
   if(name==='./bitmap')return {BitmapDisplay:class{reset(){}async paintFrame(){}},imageContainers:()=>[],measureFont:t=>t.length*10};if(name==='./style.css')return {};throw Error(name);
  }});
 vm.runInContext(ts.transpileModule(fs.readFileSync(new URL('../src/main.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
 await delay(30);
 return {ids,storage,mic,requests,pages,event:e=>eventHandler(e),dispose(){for(const t of timeouts)clearTimeout(t);for(const t of intervals)clearInterval(t);}};
}
test('app bridge omitted-zero tap starts, second tap submits, old answer remains during capture',async()=>{
 const a=await app();try{
  a.event({textEvent:{containerID:1}});await delay(500);assert.deepEqual(a.mic,[true]);assert.equal(a.ids.get('question').textContent,'Old question?');
  a.event({audioEvent:{audioPcm:new Uint8Array(9600)}});a.event({textEvent:{eventType:0}});await delay(550);
  assert.deepEqual(a.mic,[true,false]);assert.equal(a.requests.length,1);assert.equal(a.ids.get('question').textContent,'New SQL question?');
  assert.equal(JSON.parse(a.storage.get('ring-ask-history')).length,2);
 }finally{a.dispose();}
});
test('app double tap changes page without microphone and swipes restore old/current answers',async()=>{
 const a=await app();try{
  a.ids.get('demo').onclick();a.event({textEvent:{}});await delay(80);a.event({sysEvent:{eventType:3}});await delay(500);
  assert.deepEqual(a.mic,[]);assert.match(a.ids.get('page').textContent,/Page 2\//);
  a.event({textEvent:{eventType:1}});assert.equal(a.ids.get('question').textContent,'Old question?');
  a.event({textEvent:{eventType:2}});assert.match(a.ids.get('question').textContent,/website events/);
 }finally{a.dispose();}
});
test('phone tap toggle and Stop button both submit; hold uses release',async()=>{
 for(const mode of ['tap','hold']){
  const a=await app(mode);try{
   if(mode==='tap')a.ids.get('start').onclick();else a.ids.get('start').onpointerdown({pointerId:1});await delay(10);
   a.event({audioEvent:{audioPcm:new Uint8Array(9600)}});
   if(mode==='tap')a.ids.get('start').onclick();else a.ids.get('start').onpointerup();await delay(30);
   assert.equal(a.requests.length,1);assert.deepEqual(a.mic,[true,false]);
   if(mode==='tap'){a.ids.get('start').onclick();await delay(10);a.event({audioEvent:{audioPcm:new Uint8Array(9600)}});a.ids.get('stop').onclick();await delay(30);assert.equal(a.requests.length,2);}
  }finally{a.dispose();}
 }
});
test('ring hold release works and cancelled capture never erases saved answer',async()=>{
 const a=await app('hold');try{
  a.event({sysEvent:{eventType:9}});await delay(10);a.event({audioEvent:{audioPcm:new Uint8Array(9600)}});
  a.ids.get('cancel').onclick();await delay(10);assert.equal(a.ids.get('question').textContent,'Old question?');assert.equal(a.requests.length,0);
  a.event({sysEvent:{eventType:9}});await delay(10);a.event({audioEvent:{audioPcm:new Uint8Array(9600)}});a.event({sysEvent:{eventType:10}});await delay(30);assert.equal(a.requests.length,1);
 }finally{a.dispose();}
});
test('app menu foreground return rebuilds the lens and both layouts use question/answer panels',async()=>{
 const a=await app();try{
  a.event({sysEvent:{eventType:5}});await delay(10);a.event({sysEvent:{eventType:4}});await delay(30);assert.ok(a.pages.length>=2);
  a.ids.get('answer-layout').value='side';a.ids.get('answer-layout').onchange();await delay(150);
  const p=a.pages.at(-1);assert.equal(p.textObject[1].containerName,'question');assert.equal(p.textObject[2].containerName,'answer');assert.ok(p.textObject[2].xPosition>p.textObject[1].xPosition);
 }finally{a.dispose();}
});
