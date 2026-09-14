import {waitForEvenAppBridge,CreateStartUpPageContainer,RebuildPageContainer,TextContainerProperty,TextContainerUpgrade,AudioInputSource,type EvenAppBridge} from '@evenrealities/even_hub_sdk';
import {Recorder,gesture,controlAction,recoveryDelay} from './controller.mjs';
import {fullPage,readingSettings,readingLayout,deadline,emphasisParts} from './reader.mjs';
import './style.css';
import {bitmapPage,imageContainers,BitmapDisplay} from './bitmap';
import {answerVariants} from './views.mjs';
const el=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
const backend=el<HTMLInputElement>('backend'),token=el<HTMLInputElement>('token');
let bridge:EvenAppBridge|undefined,screenReady=false,created=false,active=true,connecting=false,recoveryAttempts=0,pendingListen=false;
let reading=readingSettings(),layoutDirty=false;const bitmap=new BitmapDisplay();
type AnswerView='flow'|'spoken'|'keywords';
let status='Ready',answer='',spokenAnswer='',flowAnswer='',keywordsAnswer='',rawAnswer='',viewMode:AnswerView='spoken',offset=0;
let answerStyle='natural',answerInstructions='',keepInstructions=false;
let abort:AbortController|undefined,retryAudio:Uint8Array|undefined;
let recovering:ReturnType<typeof setTimeout>|undefined,paintTimer:ReturnType<typeof setTimeout>|undefined,painting=false,dirty=false;
let lastAudioAt=0,lastPaintedAnswer:string|undefined;
let inputCount=0,touched=false,apiReady=false,checking=false,questionText='',questionStart=0,firstText=0;
function restore(raw:any) {backend.value=raw.backend||backend.value;token.value=raw.token||'';reading=readingSettings(raw.reading);if(raw.nativeLayoutVersion!==3&&reading.font==='native')reading=readingSettings({...reading,rows:10,words:'auto',width:576,x:50,y:50});for(const id of ['font','rows','words','width','x','y'] as const)el<HTMLInputElement>(id).value=String(reading[id]);answerStyle=raw.answerStyle||'natural';answerInstructions=raw.answerInstructions||'';keepInstructions=!!raw.keepInstructions;el<HTMLSelectElement>('answer-style').value=answerStyle;el<HTMLTextAreaElement>('answer-instructions').value=answerInstructions;el<HTMLInputElement>('keep-instructions').checked=keepInstructions;}
try {restore(JSON.parse(localStorage.getItem('ring-ask-settings')||'{}'));const old=JSON.parse(localStorage.getItem('ring-ask-answer')||'{}');if(old.answer){spokenAnswer=old.spokenAnswer||'';flowAnswer=old.flowAnswer||old.answer;keywordsAnswer=old.keywordsAnswer||'';viewMode=['flow','spoken','keywords'].includes(old.viewMode)?old.viewMode:'flow';answer=viewMode==='flow'?flowAnswer:viewMode==='spoken'?spokenAnswer:keywordsAnswer;if(!answer){viewMode='flow';answer=flowAnswer;}offset=0;status='Saved answer · '+viewMode.toUpperCase();questionText=old.question||'';}}
catch{restore({});}
const recorder=new Recorder(async(on:boolean)=>{
  if(on && (!bridge || !screenReady)) {scheduleRecovery();throw new Error('Glasses reconnecting. Wait for Ready, then tap again.');}
  if(!bridge)return true;
  try {return await deadline(bridge.audioControl(on,AudioInputSource.Glasses),6500,'Microphone connection timed out. Reconnecting…');}
  catch(error){screenReady=false;scheduleRecovery();throw error;}
},(message:string|null)=>{if(message){status=message;if(message==='Listening'){lastAudioAt=Date.now();}}render();},submit);
recorder.mode='press';
function saveAnswer(){try{localStorage.setItem('ring-ask-answer',JSON.stringify({answer,spokenAnswer,flowAnswer,keywordsAnswer,viewMode,offset,question:questionText}));}catch{}}
function selectView(next:AnswerView){const content={flow:flowAnswer,spoken:spokenAnswer,keywords:keywordsAnswer}[next];if(!content)return;viewMode=next;answer=content;offset=0;const position={spoken:1,flow:2,keywords:3}[viewMode];status=`Answer ${position}/3 · ${viewMode.toUpperCase()}`;render();saveAnswer();}
function toggleView(){const order:AnswerView[]=['spoken','flow','keywords'];for(let step=1;step<=order.length;step++){const next=order[(order.indexOf(viewMode)+step)%order.length];if({flow:flowAnswer,spoken:spokenAnswer,keywords:keywordsAnswer}[next]){selectView(next);return;}}}
async function saveSettings(){
  const raw=JSON.stringify({backend:backend.value.trim().replace(/\/$/,''),token:token.value.trim(),reading,nativeLayoutVersion:3,answerStyle,answerInstructions,keepInstructions});
  let saved=false;try{localStorage.setItem('ring-ask-settings',raw);saved=true;}catch{}
  if(bridge)try{await deadline(bridge.setLocalStorage('ring-ask-settings',raw),2500);saved=true;}catch{}
  return saved;
}
function answerPage(text:string,index:number){return reading.font==='native'?fullPage(text,index,reading):bitmapPage(text,index,reading);}
function lensContent(){
 if(['starting','listening','stopping'].includes(recorder.state))return status+'\n\nKeep holding while speaking. Release to answer.';
 return answer?answerPage(answer,offset).text:status+'\n\nTap to listen. Hold while speaking. Release to answer.\nSwipe down for the next page.';
}
function pageDefinition(){
 const custom=reading.font!=='native',box=readingLayout(reading);
 return {containerTotalNum:custom?5:1,textObject:[new TextContainerProperty({containerID:1,containerName:'answer',xPosition:custom?0:box.x,yPosition:custom?0:box.y,width:custom?576:box.width,height:custom?288:box.height,paddingLength:custom?0:3,borderWidth:1,borderColor:15,isEventCapture:1,content:custom?'':lensContent(),...(custom?{zOrderIndex:0}:{})})],...(custom?{imageObject:imageContainers()}:{})};
}
function render(){
 const f=answerPage(answer,offset);offset=f.page;
 el('status').textContent=status;el('page').textContent=`Page ${f.page+1} / ${f.count}`;el('display').replaceChildren();for(const part of emphasisParts(lensContent())){const node=document.createElement(part.bold?'strong':'span');node.textContent=part.text;el('display').append(node);}
 el('reading-note').textContent=`${f.rows} lines fit per page · ${reading.words==='auto'?'automatic full-width wrapping':`up to ${reading.words} words per line`}${reading.font==='native'?'':'. Custom font may update more slowly on glasses.'}`;
 const box=readingLayout(reading),preview=el('geometry-box');preview.style.width=`${box.width/5.76}%`;preview.style.height=`${box.height/2.88}%`;preview.style.left=`${box.x/5.76}%`;preview.style.top=`${box.y/2.88}%`;
 el('display').style.fontSize=reading.font==='native'?'':`${reading.font}px`;
 el('full-answer').textContent=(spokenAnswer?'SPOKEN VIEW\n'+spokenAnswer:'')+(flowAnswer?'\n\nFLOW VIEW\n'+flowAnswer:'')+(keywordsAnswer?'\n\nKEYWORDS\n'+keywordsAnswer:'');const labels={spoken:'Next: flow',flow:'Next: keywords',keywords:'Next: spoken'};el<HTMLButtonElement>('view').textContent=labels[viewMode];el<HTMLButtonElement>('view').disabled=![flowAnswer,spokenAnswer,keywordsAnswer].filter(Boolean).length;el('question').textContent=questionText?`Heard: ${questionText}`:'';
 el<HTMLButtonElement>('start').disabled=recorder.state==='busy';
 el<HTMLButtonElement>('stop').disabled=!['starting','listening'].includes(recorder.state);
 el<HTMLButtonElement>('up').disabled=offset===0;el<HTMLButtonElement>('down').disabled=offset>=f.count-1;
 el<HTMLButtonElement>('retry').disabled=!retryAudio||recorder.state!=='ready';
 dirty=true;if(!paintTimer)paintTimer=setTimeout(()=>{paintTimer=undefined;void paint();},reading.font==='native'?80:250);
}
async function paint(){
  if(painting||!bridge||!screenReady||!active)return;
  painting=true;
  try{
    // Coalesce updates: never build up a queue while BLE is slow or disconnected.
    while(dirty&&screenReady&&active){
      dirty=false;
      if(layoutDirty){layoutDirty=false;const ok=await deadline(bridge.rebuildPageContainer(new RebuildPageContainer(pageDefinition())),6000);if(!ok)throw new Error('Display rebuild failed');bitmap.reset();lastPaintedAnswer=undefined;}
      const content=lensContent();
      if(content!==lastPaintedAnswer){
        if(reading.font!=='native'){await bitmap.paint(bridge,content,reading.font,reading);}else{
        const ok=await deadline(bridge.textContainerUpgrade(new TextContainerUpgrade({containerID:1,containerName:'answer',content,contentOffset:0,contentLength:0})),5000);
        if(!ok)throw new Error('Display update failed');}
        lastPaintedAnswer=content;
      }

    }
  }catch{screenReady=false;el('connection').textContent='Glasses reconnecting…';scheduleRecovery();}
  finally{painting=false;}
}
function scheduleRecovery(){
  if(recovering||connecting||!active)return;
  const delay=recoveryDelay(recoveryAttempts++);
  recovering=setTimeout(()=>{recovering=undefined;void connect();},delay);
}
async function connect(){
  if(connecting||!active)return;connecting=true;
  try{
    if(!bridge){bridge=await deadline(waitForEvenAppBridge(),8000,'Open through Even Hub to connect your glasses.');subscribe();
      if(!touched)try{const raw=await deadline(bridge!.getLocalStorage('ring-ask-settings'),2000);if(raw&&!touched){restore(JSON.parse(raw));recorder.mode='press';}}catch{}
    }
    if(created){try{const ok=await deadline(bridge!.rebuildPageContainer(new RebuildPageContainer({...pageDefinition()})),6000);if(!ok)created=false;}catch{created=false;}}
    if(!created) {const result=await deadline(bridge!.createStartUpPageContainer(new CreateStartUpPageContainer({...pageDefinition()})),6000);if(result!==0)throw new Error(`Glasses page unavailable (${result})`);created=true;}
    bitmap.reset();layoutDirty=false;lastPaintedAnswer=undefined;screenReady=true;recoveryAttempts=0;el('connection').textContent='Glasses connected';el('hint').textContent='Tap, wait for Listening, then speak. Your last answer stays available after reconnecting.';render();
    if(pendingListen&&recorder.state==='ready'&&token.value.trim()){
      pendingListen=false;status='Starting microphone…';render();void recorder.dispatch(0);
    }
    if(token.value&&!apiReady)void checkConnection(false);
  }catch(error){screenReady=false;el('connection').textContent='Glasses reconnecting…';el('hint').textContent=`${(error as Error).message} Retrying automatically.`;}
  finally{connecting=false;if(!screenReady)scheduleRecovery();}
}
function subscribe(){
  bridge!.onEvenHubEvent(event=>{
    if(event.audioEvent){lastAudioAt=Date.now();recorder.audio(event.audioEvent.audioPcm);}
    const type=gesture(event);if(type===null)return;
    if(type===4){active=true;recoveryAttempts=0;if(!screenReady)void connect();return;}
    if([5,6,7].includes(type)){active=false;pendingListen=false;screenReady=false;abort?.abort();void recorder.dispatch(5);saveAnswer();return;}
    if([0,1,2,3,9,10].includes(type))el('input-status').textContent=`Input ${++inputCount}: ${['tap','up','down','double tap'][type]||(type===9?'hold':'release')}`;
    dispatch(type);
  });
  bridge!.onDeviceStatusChanged(device=>{
    if(device.isDisconnected()||device.isConnectionFailed()){
      screenReady=false;void recorder.dispatch(5);el('connection').textContent='Device disconnected · reconnecting…';recoveryAttempts=0;scheduleRecovery();
    }else if(device.isConnected()){recoveryAttempts=0;if(active&&!screenReady)void connect();}
  });
}
function scroll(direction:number){offset+=direction;render();saveAnswer();const f=answerPage(answer,offset);el('hint').textContent=`Page ${f.page+1} of ${f.count}${f.count===1?' · this answer fits on one page':''}`;}
function dispatch(type:number){
 if(type===3&&recorder.state==='ready'&&[flowAnswer,spokenAnswer,keywordsAnswer].filter(Boolean).length>1){toggleView();el('hint').textContent='Showing '+viewMode+' view. Swipe to change pages.';return;}
 const action=controlAction(type,active);
 if(action==='previous'||action==='next'){scroll(action==='previous'?-1:1);return;}
 if(action==='listen'){
  if(recorder.state!=='ready')return;
  if(!token.value.trim()){status='Set up connection on phone';el('health').textContent='Enter your bridge token and save.';render();return;}
  if(!screenReady){pendingListen=true;recoveryAttempts=0;void connect();status='Reconnecting · listening will start automatically';render();return;}
  retryAudio=undefined;void recorder.dispatch(type);
 }else if(action==='answer'&&['starting','listening'].includes(recorder.state))void recorder.dispatch(10);
 else if(action==='answer'&&pendingListen){pendingListen=false;status='Reconnecting · tap when Ready';render();}
}
async function submit(pcm:Uint8Array){
  retryAudio=pcm;abort?.abort();const current=new AbortController();abort=current;
  const timeout=setTimeout(()=>current.abort(),95000);answer='';spokenAnswer='';flowAnswer='';keywordsAnswer='';rawAnswer='';viewMode='spoken';offset=0;questionText='';questionStart=performance.now();firstText=0;el('timing').textContent='Sending your question…';render();
  try{
    const requestInstructions=answerInstructions.trim();
    const response=await fetch(backend.value.replace(/\/$/,'')+'/api/ask',{method:'POST',headers:{'Content-Type':'application/octet-stream',Authorization:`Bearer ${token.value.trim()}`,'X-Answer-Style':answerStyle,'X-Answer-Instructions':encodeURIComponent(requestInstructions)},body:new Blob([new Uint8Array(pcm)]),signal:current.signal});
    if(!response.ok){const error=await response.json().catch(()=>({}));throw new Error(error.error||`Server error ${response.status}`);}
    const consume=(line:string)=>{
      if(!line.trim())return;const event=JSON.parse(line);
      if(event.type==='status')status=event.text;
      if(event.type==='transcript'){questionText=event.text;status='Thinking…';el('timing').textContent=`Transcribed in ${(event.transcriptionMs/1000).toFixed(1)}s · waiting for first words…`;}
      if(event.type==='delta'){if(!firstText){firstText=performance.now();el('timing').textContent=`First words in ${((firstText-questionStart)/1000).toFixed(1)}s`; }status='Answer arriving…';rawAnswer+=event.text;const partial=answerVariants(rawAnswer);flowAnswer=partial.flow;spokenAnswer=partial.spoken;keywordsAnswer=partial.keywords;answer=spokenAnswer;}
      if(event.type==='done'){done=true;const parsed=answerVariants(rawAnswer);spokenAnswer=parsed.spoken;flowAnswer=parsed.flow;keywordsAnswer=parsed.keywords;viewMode=spokenAnswer?'spoken':flowAnswer?'flow':'keywords';answer=spokenAnswer||flowAnswer||keywordsAnswer;status=spokenAnswer?'Answer 1/3 · SPOKEN':'Answer ready';retryAudio=undefined;if(requestInstructions&&!keepInstructions){answerInstructions='';el<HTMLTextAreaElement>('answer-instructions').value='';el('instruction-status').textContent='Next-answer request used and cleared.';void saveSettings();}el('timing').textContent=`First words ${firstText?((firstText-questionStart)/1000).toFixed(1):'—'}s · complete ${((performance.now()-questionStart)/1000).toFixed(1)}s`;saveAnswer();}
      if(event.type==='error')throw new Error(event.text);
      render();
    };
    let done=false;
    if(response.body){const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
      while(true){const chunk=await reader.read();if(chunk.done){buffer+=decoder.decode();break;}buffer+=decoder.decode(chunk.value,{stream:true});let pos;while((pos=buffer.indexOf('\n'))>=0){consume(buffer.slice(0,pos));buffer=buffer.slice(pos+1);}}
      if(buffer.trim())consume(buffer);
    }else{for(const line of (await response.text()).split('\n'))consume(line);}
    if(!done)throw new Error('Answer interrupted. Tap Retry last question; your partial answer is preserved.');
  }catch(error){saveAnswer();throw new Error(current.signal.aborted?'Request stopped. Retry last question when connected.':(error as Error).message);}
  finally{clearTimeout(timeout);if(abort===current)abort=undefined;}
}
async function checkConnection(save:boolean){
  if(checking)return;checking=true;el<HTMLButtonElement>('save').disabled=true;el('save').textContent='Checking…';el('health').textContent='Checking connection…';
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
  try{
    backend.value=backend.value.trim().replace(/\/$/,'');token.value=token.value.trim();const url=new URL(backend.value);
    if(!['https:','http:'].includes(url.protocol))throw new Error('Enter a valid server URL.');if(!token.value)throw new Error('Enter your existing bridge token first.');
    const response=await fetch(backend.value+'/api/health',{headers:{Authorization:`Bearer ${token.value}`},signal:controller.signal});const result=await response.json();if(!response.ok)throw new Error(result.error||'Connection failed');
    apiReady=!!result.configured;if(!apiReady)throw new Error('Server API key is not configured.');
    if(save)await saveSettings();el<HTMLDetailsElement>('setup').open=false;el('health').textContent=`Connected · ${result.model} · ${result.profile_loaded?'your profile loaded':'profile unavailable'} · v${result.version||'unknown'}`;
  }catch(error){apiReady=false;el('health').textContent=controller.signal.aborted?'Connection timed out. Will recheck when you reconnect.':(error as Error).message;}
  finally{clearTimeout(timer);checking=false;el<HTMLButtonElement>('save').disabled=false;el('save').textContent='Save & check connection';}
}
el('start').onpointerdown=event=>{el('start').setPointerCapture(event.pointerId);dispatch(0);};
el('start').onpointerup=()=>dispatch(10);
el('start').onpointercancel=()=>{void recorder.dispatch(5);};
el('start').onkeydown=event=>{if([' ','Enter'].includes(event.key)&&!event.repeat){event.preventDefault();dispatch(0);}};
el('start').onkeyup=event=>{if([' ','Enter'].includes(event.key)){event.preventDefault();dispatch(10);}};
el('stop').onclick=()=>dispatch(10);
el('cancel').onclick=()=>{abort?.abort();void recorder.dispatch(5);};
el('up').onclick=()=>scroll(-1);el('down').onclick=()=>scroll(1);el('view').onclick=toggleView;
el('retry').onclick=()=>{if(!retryAudio||recorder.state!=='ready')return;recorder.state='busy';status='Retrying…';render();void submit(retryAudio).catch(error=>status=error.message).finally(()=>{recorder.state='ready';render();});};
el('reconnect').onclick=()=>{active=true;recoveryAttempts=0;void connect();void checkConnection(false);};
el('exit').onclick=async()=>{active=false;abort?.abort();await recorder.dispatch(5);await bridge?.shutDownPageContainer(1);};
for(const id of ['font','rows','words','width','x','y'])el<HTMLInputElement>(id).onchange=()=>{touched=true;reading=readingSettings(Object.fromEntries(['font','rows','words','width','x','y'].map(key=>[key,el<HTMLInputElement>(key).value])));offset=0;layoutDirty=true;render();void saveSettings();};
el('reset-reading').onclick=()=>{reading=readingSettings({font:'native',rows:10,words:'auto',width:576,x:50,y:50});for(const id of ['font','rows','words','width','x','y'] as const)el<HTMLInputElement>(id).value=String(reading[id]);layoutDirty=true;offset=0;render();void saveSettings();};
el('apply-instructions').onclick=()=>{answerStyle=el<HTMLSelectElement>('answer-style').value;answerInstructions=el<HTMLTextAreaElement>('answer-instructions').value.trim();keepInstructions=el<HTMLInputElement>('keep-instructions').checked;const label=el<HTMLSelectElement>('answer-style').selectedOptions[0]?.textContent||'Selected format';el('instruction-status').textContent=`${label}${answerInstructions?` · ${keepInstructions?'saved for every answer':'applies to the next answer'}`:''}.`;void saveSettings();};
el('save').onclick=()=>{touched=true;void checkConnection(true);};
for(const input of [backend,token])input.oninput=()=>{touched=true;};
el('demo').onclick=()=>{if(recorder.state!=='ready')return;status='Reading sample';spokenAnswer="Right now, my work is focused on the QFC regulatory reporting platform at Mizuho. I work with Snowflake SQL and TIDAL to move source data through staging, work, and extract tables.\n\nA big part of my role is checking that the final extracts reconcile correctly before publication. That means tracing missing records, duplicate positions, and mapping issues back through the transformations rather than assuming a successful load means the data is correct.";flowAnswer='QFC REPORTING — build Snowflake transformations\n-> RECONCILE — compare extracts with source\n-> INVESTIGATE — trace missing or duplicate records\n-> PUBLISH — release only after checks pass';keywordsAnswer='SNOWFLAKE · TIDAL · RECONCILIATION · VALIDATION';viewMode='spoken';answer=spokenAnswer;offset=0;render();saveAnswer();};
function resume(){active=true;recoveryAttempts=0;if(!screenReady)void connect();if(token.value)void checkConnection(false);render();}
window.addEventListener('online',resume);window.addEventListener('pageshow',resume);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')resume();else saveAnswer();});
window.addEventListener('pagehide',()=>{abort?.abort();void recorder.dispatch(5);saveAnswer();});
setInterval(()=>{if(recorder.state==='listening'&&Date.now()-lastAudioAt>6500){screenReady=false;void recorder.dispatch(5).then(()=>{status='Microphone dropped · tap to record again';render();});el('hint').textContent='No microphone audio received. Restoring the glasses connection.';recoveryAttempts=0;scheduleRecovery();}},2000);
setInterval(()=>{if(active&&token.value&&navigator.onLine&&!checking)void checkConnection(false);},240000);
render();void connect();if(token.value)void checkConnection(false);
