import {waitForEvenAppBridge,CreateStartUpPageContainer,RebuildPageContainer,TextContainerProperty,TextContainerUpgrade,AudioInputSource,type EvenAppBridge} from '@evenrealities/even_hub_sdk';
import {Recorder,gesture} from './controller.mjs';
import {settings,layout,frame,readDelay,deadline} from './reader.mjs';
import './style.css';
const el=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
const backend=el<HTMLInputElement>('backend'),token=el<HTMLInputElement>('token'),mode=el<HTMLSelectElement>('mode');
let bridge:EvenAppBridge|undefined,screenReady=false,created=false,active=true,connecting=false,recoveryAttempts=0;
let status='Ready',answer='Tap to record a question. Double-tap to finish.',offset=0,view=settings();
let abort:AbortController|undefined,retryAudio:Uint8Array|undefined,playing=false,autoscroll:ReturnType<typeof setTimeout>|undefined;
let recovering:ReturnType<typeof setTimeout>|undefined,paintTimer:ReturnType<typeof setTimeout>|undefined,painting=false,dirty=false,rebuild=false;
let lastAudioAt=0;
let inputCount=0,touched=false,apiReady=false,checking=false,questionText='',questionStart=0,firstText=0;
const inputIds=['rows','words','width','x','y','step','wpm','style'] as const;
function restore(raw:any) {
  backend.value=raw.backend||backend.value;token.value=raw.token||'';mode.value=raw.mode||'tap';view=settings(raw.view);
  for(const id of inputIds)el<HTMLInputElement>(id).value=String(view[id]);
}
try {restore(JSON.parse(localStorage.getItem('ring-ask-settings')||'{}'));const old=JSON.parse(localStorage.getItem('ring-ask-answer')||'{}');if(old.answer){answer=old.answer;offset=old.offset||0;status='Saved answer';questionText=old.question||'';}}
catch{restore({});}
const recorder=new Recorder(async(on:boolean)=>{
  if(on && (!bridge || !screenReady)) {scheduleRecovery();throw new Error('Glasses reconnecting. Wait for Ready, then tap again.');}
  if(!bridge)return true;
  try {return await deadline(bridge.audioControl(on,AudioInputSource.Glasses),6500,'Microphone connection timed out. Reconnecting…');}
  catch(error){screenReady=false;scheduleRecovery();throw error;}
},(message:string|null)=>{if(message){status=message;if(message==='Listening'){lastAudioAt=Date.now();playing=false;clearTimeout(autoscroll);}}render();},submit);
recorder.mode=mode.value;
function saveAnswer(){try{localStorage.setItem('ring-ask-answer',JSON.stringify({answer,offset,question:questionText}));}catch{}}
async function saveSettings(){
  const raw=JSON.stringify({backend:backend.value.trim().replace(/\/$/,''),token:token.value.trim(),mode:mode.value,view});
  let saved=false;try{localStorage.setItem('ring-ask-settings',raw);saved=true;}catch{}
  if(bridge)try{await deadline(bridge.setLocalStorage('ring-ask-settings',raw),2500);saved=true;}catch{}
  return saved;
}
function containers(){
  const box=layout(view);
  return [new TextContainerProperty({containerID:2,containerName:'status',xPosition:box.x,yPosition:box.y,width:box.width,height:26,paddingLength:2,borderWidth:0,isEventCapture:0,content:status.slice(0,38)}),
    new TextContainerProperty({containerID:1,containerName:'answer',xPosition:box.x,yPosition:box.y+30,width:box.width,height:view.rows*30+8,paddingLength:4,borderWidth:0,isEventCapture:1,content:frame(answer,offset,view).text})];
}
function render(){
  const f=frame(answer,offset,view);offset=f.start;
  el('status').textContent=status;el('page').textContent=`Lines ${f.start+1}–${f.end} / ${f.all.length}`;el('display').textContent=f.text;
  el('question').textContent=questionText?`Heard: ${questionText}`:'';
  el<HTMLButtonElement>('start').disabled=recorder.state!=='ready';el<HTMLButtonElement>('stop').disabled=!['starting','listening'].includes(recorder.state);
  el<HTMLButtonElement>('up').disabled=offset===0;el<HTMLButtonElement>('down').disabled=offset>=f.last;
  el<HTMLButtonElement>('retry').disabled=!retryAudio||recorder.state!=='ready';el('play').textContent=playing?'Pause reading':'Auto-scroll';
  el('reader-summary').textContent=`${view.rows} lines · up to ${view.words} words/line · ${view.wpm} words/min`;
  dirty=true;if(!paintTimer)paintTimer=setTimeout(()=>{paintTimer=undefined;void paint();},160);
}
async function paint(){
  if(painting||!bridge||!screenReady||!active)return;
  painting=true;
  try{
    // Coalesce updates: never build up a queue while BLE is slow or disconnected.
    while(dirty&&screenReady&&active){
      dirty=false;
      if(rebuild){rebuild=false;const ok=await deadline(bridge!.rebuildPageContainer(new RebuildPageContainer({containerTotalNum:2,textObject:containers()})),5000);if(!ok)throw new Error('Display rebuild failed');}
      const content=frame(answer,offset,view).text;
      const a=await deadline(bridge.textContainerUpgrade(new TextContainerUpgrade({containerID:1,containerName:'answer',content})),5000);
      const b=await deadline(bridge.textContainerUpgrade(new TextContainerUpgrade({containerID:2,containerName:'status',content:status.slice(0,38)})),5000);
      if(!a||!b)throw new Error('Display update failed');
    }
  }catch{screenReady=false;el('connection').textContent='Glasses reconnecting…';scheduleRecovery();}
  finally{painting=false;}
}
function scheduleRecovery(){
  if(recovering||connecting||!active||recoveryAttempts>=5)return;
  const delay=[1000,2000,4000,8000,12000][recoveryAttempts++];
  recovering=setTimeout(()=>{recovering=undefined;void connect();},delay);
}
async function connect(){
  if(connecting||!active)return;connecting=true;
  try{
    if(!bridge){bridge=await deadline(waitForEvenAppBridge(),8000,'Open through Even Hub to connect your glasses.');subscribe();
      if(!touched)try{const raw=await deadline(bridge!.getLocalStorage('ring-ask-settings'),2000);if(raw&&!touched){restore(JSON.parse(raw));recorder.mode=mode.value;}}catch{}
    }
    if(created){try{const ok=await deadline(bridge!.rebuildPageContainer(new RebuildPageContainer({containerTotalNum:2,textObject:containers()})),6000);if(!ok)created=false;}catch{created=false;}}
    if(!created) {const result=await deadline(bridge!.createStartUpPageContainer(new CreateStartUpPageContainer({containerTotalNum:2,textObject:containers()})),6000);if(result!==0)throw new Error(`Glasses page unavailable (${result})`);created=true;}
    screenReady=true;recoveryAttempts=0;el('connection').textContent='Glasses connected';el('hint').textContent='Tap, wait for Listening, then speak. Your last answer stays available after reconnecting.';render();
    if(token.value&&!apiReady)void checkConnection(false);
  }catch(error){screenReady=false;el('connection').textContent=recoveryAttempts>=5?'Open or resume Ring Ask in Even Hub':'Glasses reconnecting…';el('hint').textContent=(error as Error).message;}
  finally{connecting=false;if(!screenReady)scheduleRecovery();}
}
function subscribe(){
  bridge!.onEvenHubEvent(event=>{
    if(event.audioEvent){lastAudioAt=Date.now();recorder.audio(event.audioEvent.audioPcm);}
    const type=gesture(event);if(type===null)return;
    if(type===4){active=true;recoveryAttempts=0;void connect();return;}
    if([5,6,7].includes(type)){active=false;screenReady=false;playing=false;clearTimeout(autoscroll);abort?.abort();void recorder.dispatch(5);saveAnswer();return;}
    if([0,1,2,3,9,10].includes(type))el('input-status').textContent=`Input ${++inputCount}: ${['tap','up','down','double tap'][type]||(type===9?'hold':'release')}`;
    dispatch(type);
  });
  bridge!.onDeviceStatusChanged(device=>{
    if(device.isDisconnected()||device.isConnectionFailed()){
      screenReady=false;playing=false;clearTimeout(autoscroll);void recorder.dispatch(5);el('connection').textContent='Device disconnected · reconnecting…';recoveryAttempts=0;scheduleRecovery();
    }else if(device.isConnected()){recoveryAttempts=0;if(active&&!screenReady)void connect();}
  });
}
function scroll(direction:number){playing=false;clearTimeout(autoscroll);offset+=direction*view.step;render();saveAnswer();}
function readingTick(){
  clearTimeout(autoscroll);if(!playing||!active)return;
  const f=frame(answer,offset,view);
  if(offset>=f.last){if(recorder.state==='busy'){autoscroll=setTimeout(readingTick,800);return;}playing=false;render();return;}
  autoscroll=setTimeout(()=>{offset++;render();saveAnswer();readingTick();},readDelay(f.all[offset],view.wpm));
}
function dispatch(type:number){
  if(type===1||type===2){scroll(type===1?-1:1);return;}
  if(type===3&&recorder.state==='ready'){playing=!playing;render();readingTick();return;}
  if((type===0||type===9)&&recorder.state==='ready'){
    if(!token.value.trim()){el('health').textContent='Enter your existing bridge token once, then save.';status='Set up connection on phone';render();return;}
    playing=false;clearTimeout(autoscroll);retryAudio=undefined;
  }
  void recorder.dispatch(type);
}
async function submit(pcm:Uint8Array){
  retryAudio=pcm;abort?.abort();const current=new AbortController();abort=current;
  const timeout=setTimeout(()=>current.abort(),95000);answer='';offset=0;questionText='';questionStart=performance.now();firstText=0;el('timing').textContent='Sending your question…';render();
  try{
    const response=await fetch(backend.value.replace(/\/$/,'')+'/api/ask',{method:'POST',headers:{'Content-Type':'application/octet-stream',Authorization:`Bearer ${token.value.trim()}`,'X-Answer-Style':view.style},body:new Blob([new Uint8Array(pcm)]),signal:current.signal});
    if(!response.ok){const error=await response.json().catch(()=>({}));throw new Error(error.error||`Server error ${response.status}`);}
    const consume=(line:string)=>{
      if(!line.trim())return;const event=JSON.parse(line);
      if(event.type==='status')status=event.text;
      if(event.type==='transcript'){questionText=event.text;status='Thinking…';el('timing').textContent=`Transcribed in ${(event.transcriptionMs/1000).toFixed(1)}s · waiting for first words…`;}
      if(event.type==='delta'){if(!firstText){firstText=performance.now();el('timing').textContent=`First words in ${((firstText-questionStart)/1000).toFixed(1)}s`; }status='Answer arriving…';answer+=event.text;}
      if(event.type==='done'){done=true;status='Answer ready';retryAudio=undefined;el('timing').textContent=`First words ${firstText?((firstText-questionStart)/1000).toFixed(1):'—'}s · complete ${((performance.now()-questionStart)/1000).toFixed(1)}s`;saveAnswer();}
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
el('start').onclick=()=>dispatch(mode.value==='hold'?9:0);el('stop').onclick=()=>dispatch(3);
el('cancel').onclick=()=>{abort?.abort();playing=false;clearTimeout(autoscroll);void recorder.dispatch(5);};
el('up').onclick=()=>scroll(-1);el('down').onclick=()=>scroll(1);
el('play').onclick=()=>{playing=!playing;render();readingTick();};
el('retry').onclick=()=>{if(!retryAudio||recorder.state!=='ready')return;recorder.state='busy';status='Retrying…';render();void submit(retryAudio).catch(error=>status=error.message).finally(()=>{recorder.state='ready';render();});};
el('reconnect').onclick=()=>{active=true;recoveryAttempts=0;void connect();void checkConnection(false);};
el('exit').onclick=async()=>{active=false;abort?.abort();playing=false;clearTimeout(autoscroll);await recorder.dispatch(5);await bridge?.shutDownPageContainer(1);};
el('save').onclick=()=>{touched=true;void checkConnection(true);};
for(const input of [backend,token,mode])input.oninput=()=>{touched=true;};
mode.onchange=()=>{touched=true;void recorder.dispatch(5).then(()=>{recorder.mode=mode.value;void saveSettings();});};
for(const id of inputIds)el<HTMLInputElement>(id).onchange=()=>{
  touched=true;const values=Object.fromEntries(inputIds.map(key=>[key,el<HTMLInputElement>(key).value]));view=settings(values);offset=0;rebuild=true;render();readingTick();void saveSettings();
};
el('demo').onclick=()=>{if(recorder.state!=='ready')return;status='Reading sample';answer="Right now, my work is focused on the QFC regulatory reporting platform at Mizuho. I work with Snowflake SQL and TIDAL to move source data through staging, work, and extract tables.\n\nA big part of my role is checking that the final extracts reconcile correctly before publication. That means tracing missing records, duplicate positions, and mapping issues back through the transformations rather than assuming a successful load means the data is correct.";offset=0;render();saveAnswer();};
function resume(){active=true;recoveryAttempts=0;if(!screenReady)void connect();if(token.value)void checkConnection(false);render();}
window.addEventListener('online',resume);window.addEventListener('pageshow',resume);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')resume();else saveAnswer();});
window.addEventListener('pagehide',()=>{abort?.abort();void recorder.dispatch(5);saveAnswer();});
setInterval(()=>{if(recorder.state==='listening'&&Date.now()-lastAudioAt>6500){screenReady=false;void recorder.dispatch(5).then(()=>{status='Microphone dropped · tap to record again';render();});el('hint').textContent='No microphone audio received. Restoring the glasses connection.';recoveryAttempts=0;scheduleRecovery();}},2000);
render();void connect();if(token.value)void checkConnection(false);
