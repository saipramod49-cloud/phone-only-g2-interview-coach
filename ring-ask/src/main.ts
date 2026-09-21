import {waitForEvenAppBridge,CreateStartUpPageContainer,RebuildPageContainer,MenuContainerProperty,MenuItemProperty,TextContainerProperty,TextContainerUpgrade,AudioInputSource,type EvenAppBridge} from '@evenrealities/even_hub_sdk';
import {Recorder,gestures,recoveryDelay} from './controller.mjs';
import {LiveQuestion} from './live.mjs';
import {RemoteCaptions} from './remote.mjs';
import {InterviewPackClient,activeProfile,targetStack} from './preparation.mjs';
import {readingSettings,deadline,textWidth,emphasisParts} from './reader.mjs';
import {AnswerHistory,RingInput,readingFrame} from './session.mjs';
import {BitmapDisplay,imageContainers,measureFont} from './bitmap';
import './style.css';
const el=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
const backend=el<HTMLInputElement>('backend'),token=el<HTMLInputElement>('token');
let reading=readingSettings(),listenMode='tap',conversationMode='manual',answerLayout='top',answerInstructions='',keepInstructions=false;
let bridge:EvenAppBridge|undefined,screenReady=false,created=false,active=true,backgrounded=false,connecting=false,touched=false;
let displayBlanked=false;
let recoveryAttempts=0,status='Ready',recordStarted=0,lastAudioAt=0,inputCount=0;
let layoutDirty=false,painting=false,dirty=false,lastPaint='',checking=false,apiReady=false;
let paintTimer:ReturnType<typeof setTimeout>|undefined,recovering:ReturnType<typeof setTimeout>|undefined;
let abort:AbortController|undefined,retryAudio:Uint8Array|undefined,requestSerial=0;
let draft:{question:string,answer:string}|undefined,showDraft=false;
let autoActive=false,autoStarted=0,autoFirst=0;
let remoteActive=false,remoteCode='',remoteSenderUrl='';
let packState:any=null,packLoading=false;
const bitmap=new BitmapDisplay();
function restore(raw:any){
 backend.value=raw.backend||backend.value;token.value=raw.token||'';reading=readingSettings(raw.reading);
 listenMode=raw.listenMode==='hold'?'hold':'tap';conversationMode=raw.conversationMode==='auto'?'auto':'manual';answerLayout=raw.answerLayout==='side'?'side':'top';
 answerInstructions=raw.answerInstructions||'';keepInstructions=!!raw.keepInstructions;
 for(const id of ['font','rows','words','width','x','y'] as const)el<HTMLInputElement>(id).value=String(reading[id]);
 el<HTMLSelectElement>('listen-mode').value=listenMode;el<HTMLSelectElement>('conversation-mode').value=conversationMode;el<HTMLSelectElement>('answer-layout').value=answerLayout;
 el<HTMLTextAreaElement>('answer-instructions').value=answerInstructions;el<HTMLInputElement>('keep-instructions').checked=keepInstructions;
}
let saved=[];
try{restore(JSON.parse(localStorage.getItem('ring-ask-settings')||'{}'));saved=JSON.parse(localStorage.getItem('ring-ask-history')||'[]');
 if(!saved.length){const old=JSON.parse(localStorage.getItem('ring-ask-answer')||'{}');if(old.answer&&old.question?.trim())saved=[{question:old.question||'',answer:old.spokenAnswer||old.answer,time:Date.now()}];}}
catch{restore({});}
const history=new AnswerHistory(saved);
function persist(){try{localStorage.setItem('ring-ask-history',JSON.stringify(history.entries));}catch{el('hint').textContent='Phone storage is full; history is kept for this session only.';}}
const liveQuestion=new LiveQuestion();
const remoteCaptions=new RemoteCaptions();
function packClient(){return new InterviewPackClient(backend.value.trim(),token.value.trim());}
function refreshLiveDossier(){if(liveQuestion.ready)liveQuestion.configure(answerInstructions.trim());}
function renderPack(){
 const select=el<HTMLSelectElement>('profile-select'),files=el('pack-files'),profile=activeProfile(packState);
 select.replaceChildren();
 for(const item of packState?.profiles||[]){const option=document.createElement('option');option.value=item.id;option.textContent=`${item.active?'✓ ':''}${item.name}`;option.selected=item.id===profile?.id;select.append(option);}
 if(!profile){const option=document.createElement('option');option.value='';option.textContent='No interview packs yet';select.append(option);files.replaceChildren();return;}
 el('pack-status').textContent=`Active: ${profile.name} · target stack: ${targetStack(profile.job_description)} · ${profile.documents.length} file${profile.documents.length===1?'':'s'}`;
 files.replaceChildren();const summary=document.createElement('p');summary.className='pack-summary';summary.textContent=profile.job_description?`JD saved · ${profile.job_description.length} characters. Changes are applied to the current Live session.`:'No JD saved yet. Create a new pack with the target job description for stack-specific answers.';files.append(summary);
 for(const document of profile.documents){const chip=document.createElement('span');chip.className='pack-file';chip.textContent=`${document.kind} · ${document.name}`;files.append(chip);}
}
async function loadPacks(message=''){
 if(packLoading)return;if(!token.value.trim()){el('pack-status').textContent='Enter and save your bridge token first.';return;}packLoading=true;
 try{packState=await packClient().state();renderPack();if(message)el('pack-status').textContent=message+' '+el('pack-status').textContent;}
 catch(error){el('pack-status').textContent=(error as Error).message;}finally{packLoading=false;}
}
async function updatePack(action:()=>Promise<any>,success:string){
 const priorStatus=status;if(autoActive)status='Updating the active Interview Pack…';el('pack-status').textContent='Saving…';
 try{await action();await loadPacks();refreshLiveDossier();el('pack-status').textContent=`${success} ${autoActive?'The running Live session has been refreshed.':'It will load when listening starts.'}`;}
 catch(error){el('pack-status').textContent=(error as Error).message;}finally{status=autoActive?'Auto Conversation · listening':priorStatus;}render();
}
const recorder=new Recorder(async(on:boolean)=>{
 if(on&&(!bridge||!screenReady||backgrounded))throw new Error('Glasses reconnecting. Wait for Connected and try again.');
 if(!bridge)return true;
 try{return await deadline(bridge.audioControl(on,AudioInputSource.Glasses),6500,'Microphone timed out. Try reconnecting.');}
 catch(error){screenReady=false;scheduleRecovery();throw error;}
},(message:string|null)=>{
 if(message){status=message;if(message==='Listening'){recordStarted=Date.now();lastAudioAt=Date.now();}}
 if(recorder.state==='ready')recordStarted=0;render();
},submit,{
 start:async()=>{
  status='Connecting GPT Live…';render();
  const connected=await liveQuestion.start(backend.value.trim().replace(/\/$/,''),token.value.trim(),(event:any)=>{
   if(event.type==='transcript.partial'&&event.text){draft={question:event.text,answer:''};status='Listening · live transcript';render();}
   if(event.type==='capture'&&event.active===false&&!autoActive&&recorder.state==='listening')void recorder.dispatch(3);
   if(event.type==='error'){status='GPT Live unavailable · batch fallback ready';render();}
  });
  if(connected)liveQuestion.configure(answerInstructions.trim());
  else{status='Listening · batch fallback';render();}
 },
 audio:(chunk:Uint8Array)=>liveQuestion.audio(chunk),
 cancel:()=>liveQuestion.cancel()
});
recorder.mode=listenMode;

function consumeAuto(event:any){
 if(!autoActive)return;
 if(event.type==='answer.start'){draft={question:event.question||draft?.question||'',answer:''};showDraft=false;autoFirst=0;status='Thinking…';}
 if(event.type==='transcript.partial'&&event.text){draft={question:event.text,answer:draft?.answer||''};status='Listening · possible question';}
 if(event.type==='transcript'){draft={question:event.text||draft?.question||'',answer:draft?.answer||''};status='Question detected · thinking…';}
 if(event.type==='delta'){
  if(!draft)draft={question:'Question detected',answer:''};
  if(!autoFirst){autoFirst=performance.now();showDraft=true;history.page=0;el('timing').textContent=`First words ${((autoFirst-autoStarted)/1000).toFixed(1)}s`;}
  draft.answer+=event.text||'';status='Answer arriving…';
 }
 if(event.type==='done'&&draft?.answer){
  history.add(draft.question,draft.answer);draft=undefined;showDraft=false;history.latest();persist();
  status='Auto Conversation · listening for the next question';
  el('timing').textContent=`Last answer complete${event.model?' · '+event.model:''}`;
 }
 if(event.type==='capture'&&event.active===true)status='Auto Conversation · listening';
 if(event.type==='state'&&event.message)status=event.message;
 if(event.type==='error')status=event.text||'Live session needs attention';
 render();
}

async function startAutoConversation(){
 if(autoActive)return;
 if(!token.value.trim()){status='Enter your bridge token in Agent connection';render();return;}
 if(!bridge||!screenReady||backgrounded){status='Glasses reconnecting. Wait for Connected.';render();return;}
 status='Connecting Auto Conversation…';render();
 const connected=await liveQuestion.start(
  backend.value.trim().replace(/\/$/,''),
  token.value.trim(),
  consumeAuto,
  {continuous:true},
 );
 if(!connected){status='Could not start GPT-Live Auto Conversation';render();return;}
 liveQuestion.configure(answerInstructions.trim());
 try{
  if(!await deadline(bridge.audioControl(true,AudioInputSource.Glasses),6500,'Microphone timed out.'))throw Error('Microphone unavailable.');
  autoActive=true;autoStarted=performance.now();lastAudioAt=Date.now();status='Auto Conversation · listening';render();
 }catch(error){liveQuestion.cancel();status=(error as Error).message;render();}
}

async function stopAutoConversation(message='Auto Conversation stopped'){
 if(!autoActive&& !liveQuestion.ready)return;
 autoActive=false;liveQuestion.cancel();
 try{await bridge?.audioControl(false,AudioInputSource.Glasses);}catch{}
 status=message;render();
}
function consumeRemote(event:any){
 if(event.type==='session'){remoteCode=event.code||'';remoteSenderUrl=event.sender_url||'';status='Remote captions · share the code';}
 if(event.type==='sender.connected')status='Remote captions · sender connected';
 if((event.type==='caption.partial'||event.type==='caption.final')&&event.text){draft={question:'REMOTE CAPTIONS',answer:event.text};showDraft=true;history.page=0;status='Remote captions · live';}
 if(event.type==='sender.disconnected')status='Remote captions · waiting for sender';
 if(event.type==='expired')stopRemoteCaptions('Remote caption session expired');
 if(event.type==='error')status=event.text||'Remote captions stopped';
 if(event.type==='closed'&&remoteActive)stopRemoteCaptions(event.text||'Remote captions stopped');
 render();
}
async function startRemoteCaptions(){
 if(remoteActive){stopRemoteCaptions();return;}
 if(!token.value.trim()){status='Enter your bridge token in Agent connection';render();return;}
 if(autoActive)await stopAutoConversation('Switching to remote captions…');else await recorder.dispatch(5);
 status='Creating remote caption session…';render();
 const connected=await remoteCaptions.start(backend.value.trim().replace(/\/$/,''),token.value.trim(),consumeRemote);
 if(!connected){status='Could not create remote caption session';render();return;}
 remoteActive=true;status='Remote captions · share the code';layoutDirty=true;render();
}
function stopRemoteCaptions(message='Remote captions stopped'){
 remoteActive=false;remoteCaptions.stop();remoteCode='';remoteSenderUrl='';
 if(draft?.question==='REMOTE CAPTIONS'){draft=undefined;showDraft=false;history.latest();}
 status=message;layoutDirty=true;render();
}
const ringInput=new RingInput(dispatch);
function captureStatus(){
 if(remoteActive)return remoteCode?`Remote captions · ${remoteCode}`:'Remote captions · connecting';
 if(autoActive){const secs=Math.floor((Date.now()-autoStarted)/1000);return `🐶 Auto listening ${Math.floor(secs/60)}:${String(secs%60).padStart(2,'0')} · tap to stop`;}
 if(recorder.state==='listening'){const secs=Math.floor((Date.now()-recordStarted)/1000);return `🐶 Listening ${Math.floor(secs/60)}:${String(secs%60).padStart(2,'0')} · ${listenMode==='tap'?'tap to stop':'release to answer'}`;}
 if(['starting','stopping','busy'].includes(recorder.state)||['Sending question…','Transcribing…','Thinking…','Answer arriving…'].includes(status))return '🐶💭 Thinking…';
 if(status==='Ready'||status==='Answer ready')return '🐶 Ready for next question';
 return status;
}
function puppyState(){return autoActive||recorder.state==='listening'?'listening':(['starting','stopping','busy'].includes(recorder.state)||['Sending question…','Transcribing…','Thinking…','Answer arriving…'].includes(status))?'thinking':(status==='Ready'||status==='Answer ready')?'ready':'notice';}
function puppyHeader(){
 if(remoteActive)return remoteCode?`Remote · ${remoteCode}`:'Remote captions';
 if(autoActive)return '🐶 Auto listening';
 if(recorder.state==='listening'){const secs=Math.floor((Date.now()-recordStarted)/1000);return `🐶 Listening ${Math.floor(secs/60)}:${String(secs%60).padStart(2,'0')}`;}
 if(puppyState()==='thinking')return '🐶💭 Thinking';
 if(puppyState()==='ready')return '🐶 Ready';
 return status;
}
function displayed(){return showDraft&&draft?.answer?draft:history.current;}
function frame(){const f=readingFrame(displayed(),history.page,reading,(text:string)=>reading.font==='native'?textWidth(text):measureFont(text,reading.font),answerLayout,showDraft&&draft?.answer?'Current answer':history.label());history.page=f.page;return f;}
function appendRich(target:HTMLElement,text:string){
 target.replaceChildren();let code=false;
 for(const line of text.split('\n')){
  if(/^\s*```/.test(line)){code=!code;continue;}
  const row=document.createElement('div');if(code){row.className='code-line';row.textContent=line||' ';}
  else{for(const part of line.split(/(\*\*.*?\*\*)/g)){const n=document.createElement(part.startsWith('**')?'strong':'span');n.textContent=part.startsWith('**')?part.slice(2,-2):part;row.append(n);}}
  target.append(row);
 }
}
function render(){
 const f=frame();el('status').textContent=captureStatus();el('page').textContent=f.header;
 el('question').textContent=displayed()?.question||'Ready for your question';el('display').replaceChildren();for(const part of emphasisParts(f.answer)){const node=document.createElement(part.bold?'strong':'span');node.textContent=part.text;el('display').append(node);}
 el('qa-panels').classList.toggle('side',answerLayout==='side');appendRich(el('full-answer'),displayed()?.answer||'');
 el('reading-note').textContent=`${f.rows} answer lines per page. Long questions are shortened on the lens; the complete question is shown on this phone.`;
 el<HTMLButtonElement>('start').textContent=conversationMode==='auto'?(autoActive?'Stop Auto Conversation':'Start Auto Conversation'):(listenMode==='hold'?'Hold to listen':'Tap to '+(['starting','listening'].includes(recorder.state)?'stop & answer':'start listening'));
 el<HTMLButtonElement>('restore-listen').hidden=screenReady&&active&&!backgrounded;
 el<HTMLButtonElement>('start').disabled=conversationMode==='manual'&&['busy','stopping'].includes(recorder.state);
 el<HTMLButtonElement>('stop').disabled=conversationMode==='auto'?!autoActive:!['starting','listening'].includes(recorder.state);
 el<HTMLButtonElement>('stop').textContent=conversationMode==='auto'?'Stop Auto Conversation':'Stop & answer';
 el<HTMLButtonElement>('listen-mode').disabled=conversationMode==='auto'||recorder.state!=='ready';
 el<HTMLButtonElement>('conversation-mode').disabled=autoActive||recorder.state!=='ready';
 el<HTMLButtonElement>('up').disabled=history.index<=0;el<HTMLButtonElement>('down').disabled=history.isLatest&&!draft?.answer;
 el<HTMLButtonElement>('previous-page').disabled=f.page===0;el<HTMLButtonElement>('next-page').disabled=f.count<=1;
 el<HTMLButtonElement>('retry').disabled=!retryAudio||recorder.state!=='ready';
 el<HTMLButtonElement>('remote-toggle').textContent=remoteActive?'Stop remote captions':'Start remote captions';
 el('remote-code').textContent=remoteCode||'No active session';
 const remoteLink=el<HTMLAnchorElement>('remote-link');remoteLink.hidden=!remoteSenderUrl;remoteLink.href=remoteSenderUrl;
 dirty=true;if(!paintTimer)paintTimer=setTimeout(()=>{paintTimer=undefined;void paint();},reading.font==='native'?100:350);
}
function ringMenu(){return new MenuContainerProperty({menuItems:[new MenuItemProperty({itemName:conversationMode==='auto'?(autoActive?'Stop Auto Conversation':'Start Auto Conversation'):'Start listening',itemID:1}),new MenuItemProperty({itemName:'Resume Ring Ask',itemID:2}),new MenuItemProperty({itemName:'Previous answer',itemID:3}),new MenuItemProperty({itemName:'Current answer',itemID:4}),new MenuItemProperty({itemName:remoteActive?'Stop Remote Captions':'Start Remote Captions',itemID:5})]});}
function pageDefinition(){
 const f=frame(),custom=reading.font!=='native';
 if(displayBlanked)return {containerTotalNum:1,menuObject:ringMenu(),textObject:[new TextContainerProperty({containerID:1,containerName:'blank-input',xPosition:0,yPosition:0,width:576,height:288,paddingLength:0,isEventCapture:1,content:'',zOrderIndex:0})]};
 if(custom)return {containerTotalNum:5,menuObject:ringMenu(),textObject:[new TextContainerProperty({containerID:1,containerName:'input',xPosition:0,yPosition:0,width:576,height:288,paddingLength:0,isEventCapture:1,content:'',zOrderIndex:0})],imageObject:imageContainers()};
 return {containerTotalNum:3,menuObject:ringMenu(),textObject:[
  new TextContainerProperty({containerID:1,containerName:'header',xPosition:0,yPosition:0,width:576,height:32,paddingLength:2,isEventCapture:1,content:header(f)}),
  ...f.panels.map((p:any,i:number)=>new TextContainerProperty({containerID:i+2,containerName:i?'answer':'question',xPosition:p.x,yPosition:p.y,width:p.width,height:p.height,paddingLength:3,borderWidth:1,borderColor:15,isEventCapture:0,content:p.text}))]};
}
function header(f:any){return `${f.label} · Page ${f.page+1}/${f.count} · ${puppyHeader()}`;}
async function paint(){
 if(painting||!bridge||!screenReady||!active||backgrounded)return;painting=true;
 try{while(dirty&&screenReady&&active&&!backgrounded){dirty=false;
  if(layoutDirty){layoutDirty=false;const ok=await deadline(bridge!.rebuildPageContainer(new RebuildPageContainer(pageDefinition())),6000);if(!ok)throw Error('Display rebuild failed');lastPaint='';bitmap.reset();}
  if(displayBlanked){lastPaint='blank';continue;}
  const f=frame(),key=JSON.stringify([f,header(f)]);if(key===lastPaint)continue;
  if(reading.font!=='native')await bitmap.paintFrame(bridge,{...f,header:header(f)},reading.font);
  else for(const [id,name,content] of [[1,'header',header(f)],[2,'question',f.question],[3,'answer',f.answer]] as const){
   const ok=await deadline(bridge.textContainerUpgrade(new TextContainerUpgrade({containerID:id,containerName:name,content,contentOffset:0,contentLength:0})),5000);if(!ok)throw Error('Display update failed');}
  lastPaint=key;
 }}catch{screenReady=false;el('connection').textContent='Glasses reconnecting…';scheduleRecovery();}finally{painting=false;}
}
function scheduleRecovery(){if(recovering||connecting||!active||backgrounded)return;recovering=setTimeout(()=>{recovering=undefined;void connect();},recoveryDelay(recoveryAttempts++));}
async function connect(){
 if(connecting||!active||backgrounded)return;connecting=true;
 try{
  if(!bridge){bridge=await deadline(waitForEvenAppBridge(),8000,'Open Ring Ask through Even Hub.');subscribe();
   if(!touched)try{const raw=await deadline(bridge!.getLocalStorage('ring-ask-settings'),2000);if(raw&&!touched){restore(JSON.parse(raw));recorder.mode=listenMode;}}catch{}}
  if(created){try{created=!!await deadline(bridge!.rebuildPageContainer(new RebuildPageContainer(pageDefinition())),6000);}catch{created=false;}}
  if(!created){const result=await deadline(bridge!.createStartUpPageContainer(new CreateStartUpPageContainer(pageDefinition())),6000);if(result!==0)throw Error(`Glasses page unavailable (${result})`);created=true;}
  screenReady=true;layoutDirty=false;recoveryAttempts=0;lastPaint='';bitmap.reset();el('connection').textContent='Glasses connected';render();
  if(token.value&&!apiReady)void checkConnection(false);
 }catch(error){screenReady=false;el('connection').textContent='Glasses reconnecting…';el('hint').textContent=(error as Error).message;}
 finally{connecting=false;if(!screenReady)scheduleRecovery();}
}
function suspend(closed=false){backgrounded=true;screenReady=false;if(closed){active=false;created=false;}ringInput.reset();if(remoteActive)stopRemoteCaptions('Remote captions stopped');if(autoActive)void stopAutoConversation('Glasses controls paused');else void recorder.dispatch(5);status='Glasses controls paused';el('connection').textContent='Restore controls from phone';persist();render();}
function resume(){active=true;backgrounded=false;recoveryAttempts=0;if(!screenReady)void connect();render();}
async function restoreLensControls(startListening=false){
 if(startListening&&['busy','stopping'].includes(recorder.state))return;
 if(startListening&&!token.value.trim()){status='Enter your bridge token in Agent connection';render();return;}
 status=startListening?'Restoring controls & microphone…':'Restoring glasses controls…';
 active=true;backgrounded=false;recoveryAttempts=0;screenReady=false;ringInput.reset();lastPaint='';
 if(startListening||['starting','listening','stopping'].includes(recorder.state))await recorder.dispatch(5);
 if(autoActive)await stopAutoConversation('Restoring glasses controls…');
 await connect();
 if(!screenReady){status='Could not restore glasses controls. Open this lens menu and try again.';render();return;}
 if(startListening){
  if(conversationMode==='auto')await startAutoConversation();
  else{recorder.mode=listenMode;await recorder.dispatch(listenMode==='hold'?9:0);}
 }
 else{status='Ready';render();}
}
async function recoverFromInput(types:number[]){
 active=true;backgrounded=false;recoveryAttempts=0;created=false;screenReady=false;ringInput.reset();
 await connect();
 if(!screenReady)return;
 for(const type of types){el('input-status').textContent=`Wake input ${++inputCount}: ${type}`;ringInput.feed(type);}
}
async function restoreAndListen(){
 el('connection').textContent='Restoring glasses…';render();
 await restoreLensControls(true);
}
function subscribe(){
 bridge!.onEvenHubEvent(event=>{
  if(event.audioEvent){lastAudioAt=Date.now();if(autoActive)liveQuestion.audio(event.audioEvent.audioPcm);else recorder.audio(event.audioEvent.audioPcm);}
  const menu=event.menuItemClickEvent?.itemID;if(menu){
   if(menu===1){void restoreLensControls(true);return;}
   if(menu===2){void restoreLensControls(false);return;}
   if(menu===5){resume();void startRemoteCaptions();return;}
   resume();if(menu===3)navigateHistory(-1);if(menu===4){history.latest();showDraft=!!draft?.answer;render();}return;
  }
   const system=event.sysEvent?.eventType;
   // 4/5 belong to the EvenOS contextual-menu overlay. The Ring Ask page stays
   // mounted beneath it, so rebuilding or suspending here drops ring capture.
   if(system===4||system===5)return;if(system===6||system===7){suspend(true);return;}
  const types=gestures(event);
  if(types.length&&(!active||backgrounded||!screenReady)){void recoverFromInput(types);return;}
  for(const type of types){el('input-status').textContent=`Input ${++inputCount}: ${type} · ${recorder.state}`;ringInput.feed(type);}
 });
 bridge!.onDeviceStatusChanged(device=>{if(device.isDisconnected()||device.isConnectionFailed()){screenReady=false;ringInput.reset();if(autoActive)void stopAutoConversation('Glasses disconnected');else void recorder.dispatch(5);scheduleRecovery();}else if(device.isConnected())resume();});
}
function navigatePage(direction:number){const f=frame();history.page=direction>0?(f.page+1)%f.count:Math.max(0,f.page-1);render();}
function toggleLensDisplay(){displayBlanked=!displayBlanked;layoutDirty=true;status=displayBlanked?'Lens blanked · triple tap to restore':'Ready';render();}
function navigateHistory(direction:number){
 if(showDraft&&draft?.answer&&direction<0){showDraft=false;history.latest();}
 else if(direction>0&&history.isLatest&&draft?.answer){showDraft=true;history.page=0;}
 else{showDraft=false;history.move(direction);}
 render();
}
function dispatch(type:number){
 if(!active||backgrounded)return;
 if(type===3){navigatePage(1);return;}if(type===11){toggleLensDisplay();return;}if(type===1||type===2){navigateHistory(type===1?-1:1);return;}
 if(conversationMode==='auto'){
  if(type===0||type===9){if(autoActive)void stopAutoConversation();else void startAutoConversation();}
  return;
 }
 if(type===10){if(listenMode==='hold')void recorder.dispatch(10);return;}
 if((listenMode==='tap'&&type!==0)||(listenMode==='hold'&&type!==9))return;
 if(['busy','stopping'].includes(recorder.state))return;
 if(!token.value.trim()){status='Enter your bridge token in Agent connection';render();return;}
 if(!screenReady){status='Reconnecting · try again when Connected';void connect();render();return;}
 recorder.mode=listenMode;void recorder.dispatch(type);
}
function cancel(){requestSerial++;abort?.abort();draft=undefined;showDraft=false;ringInput.reset();if(remoteActive)stopRemoteCaptions('Remote captions cancelled');if(autoActive||liveQuestion.continuous)void stopAutoConversation('Auto Conversation cancelled');else void recorder.dispatch(5);persist();render();}
async function submit(pcm:Uint8Array){
 retryAudio=pcm;abort?.abort();const current=new AbortController();abort=current;const serial=++requestSerial;
 const timeout=setTimeout(()=>current.abort(),195000),start=performance.now();let first=0,done=false;
 draft={question:'',answer:''};showDraft=false;status='Sending question…';render();
 try{
  const instructions=answerInstructions.trim();
  const consume=(line:string)=>{
   if(!line.trim()||serial!==requestSerial)return;const event=JSON.parse(line);
   if(event.type==='status')status=event.text;
   if(event.type==='transcript.partial'){draft!.question=event.text;status='Finishing live transcript…';}
   if(event.type==='transcript'){draft!.question=event.text;status='Thinking…';el('timing').textContent=`Transcribed in ${(event.transcriptionMs/1000).toFixed(1)}s`;}
   if(event.type==='delta'){
    if(!first){first=performance.now();showDraft=true;history.page=0;el('timing').textContent=`First words ${((first-start)/1000).toFixed(1)}s`;}
    draft!.answer+=event.text;status='Answer arriving…';
   }
   if(event.type==='done'){
    done=true;const viewingDraft=showDraft;const oldEntry=history.current,oldPage=history.page;
    history.add(draft!.question,draft!.answer);draft=undefined;showDraft=false;
    if(viewingDraft)history.page=oldPage;else{history.index=Math.max(0,history.entries.indexOf(oldEntry));history.page=oldPage;}
    retryAudio=undefined;status='Answer ready';persist();
    el('timing').textContent=`First words ${first?((first-start)/1000).toFixed(1):'—'}s · complete ${((performance.now()-start)/1000).toFixed(1)}s${event.model?' · '+event.model:''}`;
    if(instructions&&!keepInstructions){answerInstructions='';el<HTMLTextAreaElement>('answer-instructions').value='';void saveSettings();}
   }
   if(event.type==='error')throw Error(event.text);render();
  };
  let liveFailed=false;
  if(liveQuestion.ready){
   status='Finishing GPT Live transcript…';render();
   try{await liveQuestion.finish(instructions,(event:any)=>consume(JSON.stringify(event)));}
   catch{liveFailed=true;}
  }else liveFailed=true;
  if(liveFailed&&!draft!.answer){
   status='Using batch fallback…';draft={question:'',answer:''};render();
   const response=await fetch(backend.value.replace(/\/$/,'')+'/api/ask',{method:'POST',headers:{'Content-Type':'application/octet-stream',Authorization:`Bearer ${token.value.trim()}`,'X-Answer-Instructions':encodeURIComponent(instructions)},body:new Blob([new Uint8Array(pcm)]),signal:current.signal});
   if(!response.ok){const error=await response.json().catch(()=>({}));throw Error(error.error||`Server error ${response.status}`);}
   if(!response.body)throw Error('Streaming unavailable. Try again.');
   const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
   while(true){const chunk=await reader.read();if(chunk.done){buffer+=decoder.decode();break;}buffer+=decoder.decode(chunk.value,{stream:true});let pos;while((pos=buffer.indexOf('\n'))>=0){consume(buffer.slice(0,pos));buffer=buffer.slice(pos+1);}}
   if(buffer.trim())consume(buffer);
  }
  if(!done)throw Error('Answer interrupted. Retry last question.');
 }catch(error){if(serial===requestSerial){draft=undefined;showDraft=false;status=current.signal.aborted?'Question stopped; previous answer restored':(error as Error).message;render();throw Error(status);}}
 finally{clearTimeout(timeout);if(abort===current)abort=undefined;}
}
async function saveSettings(){
 const raw=JSON.stringify({backend:backend.value.trim().replace(/\/$/,''),token:token.value.trim(),reading,listenMode,conversationMode,answerLayout,answerInstructions,keepInstructions});
 try{localStorage.setItem('ring-ask-settings',raw);}catch{}
 if(bridge)try{await deadline(bridge.setLocalStorage('ring-ask-settings',raw),2500);}catch{}
}
async function checkConnection(save:boolean){
 if(checking)return;checking=true;el<HTMLButtonElement>('save').disabled=true;
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
 try{
  backend.value=backend.value.trim().replace(/\/$/,'');token.value=token.value.trim();if(!token.value)throw Error('Enter your existing bridge token.');
  const response=await fetch(backend.value+'/api/health',{headers:{Authorization:`Bearer ${token.value}`},signal:controller.signal});const result=await response.json();if(!response.ok||!result.configured)throw Error(result.error||'Server API key is not configured.');
  apiReady=true;if(save)await saveSettings();el<HTMLDetailsElement>('setup').open=false;
  el('health').textContent=`Connected · ${result.live_model||'batch audio'} → ${result.model} · reasoning ${result.reasoning||'default'} · v${result.version}`;
 }catch(error){apiReady=false;el('health').textContent=(error as Error).message;}finally{clearTimeout(timer);checking=false;el<HTMLButtonElement>('save').disabled=false;}
}
let recoveryPress=false;
el('start').onpointerdown=event=>{if(conversationMode==='manual'&&listenMode==='hold'){el('start').setPointerCapture(event.pointerId);if(!active||backgrounded||!screenReady){recoveryPress=true;void restoreAndListen();}else dispatch(9);}};
el('start').onpointerup=()=>{if(conversationMode==='manual'&&listenMode==='hold'){if(recoveryPress){recoveryPress=false;return;}dispatch(10);}};
el('start').onclick=()=>{if(conversationMode==='auto'||listenMode==='tap'){if(!active||backgrounded||!screenReady)void restoreAndListen();else dispatch(0);}};
el('start').onpointercancel=cancel;
el('start').onkeydown=e=>{if(listenMode==='hold'&&[' ','Enter'].includes(e.key)&&!e.repeat){e.preventDefault();dispatch(9);}};
el('start').onkeyup=e=>{if(listenMode==='hold'&&[' ','Enter'].includes(e.key)){e.preventDefault();dispatch(10);}};
el('stop').onclick=()=>{ringInput.reset();if(autoActive)void stopAutoConversation();else void recorder.dispatch(3);};el('cancel').onclick=cancel;
el('restore-listen').onclick=()=>{void restoreAndListen();};
el('up').onclick=()=>navigateHistory(-1);el('down').onclick=()=>navigateHistory(1);
el('next-page').onclick=()=>navigatePage(1);el('previous-page').onclick=()=>navigatePage(-1);
el('retry').onclick=()=>{if(retryAudio&&recorder.state==='ready'){recorder.state='busy';void submit(retryAudio).catch(()=>{}).finally(()=>{recorder.state='ready';render();});}};
el('save').onclick=()=>{touched=true;void checkConnection(true);};
for(const input of [backend,token])input.oninput=()=>{touched=true;};
el('reconnect').onclick=()=>{resume();void checkConnection(false);};
el('remote-toggle').onclick=()=>void startRemoteCaptions();
el('exit').onclick=async()=>{if(remoteActive)stopRemoteCaptions();if(autoActive)await stopAutoConversation();else cancel();active=false;await bridge?.shutDownPageContainer(1);};
el<HTMLSelectElement>('conversation-mode').onchange=()=>{touched=true;conversationMode=el<HTMLSelectElement>('conversation-mode').value==='auto'?'auto':'manual';ringInput.reset();void saveSettings();layoutDirty=true;render();};
el<HTMLSelectElement>('listen-mode').onchange=()=>{touched=true;ringInput.reset();listenMode=el<HTMLSelectElement>('listen-mode').value;recorder.mode=listenMode;void saveSettings();render();};
el<HTMLSelectElement>('answer-layout').onchange=()=>{touched=true;answerLayout=el<HTMLSelectElement>('answer-layout').value;layoutDirty=true;history.page=0;void saveSettings();render();};
for(const id of ['font','rows','words','width','x','y'])el<HTMLInputElement>(id).onchange=()=>{touched=true;reading=readingSettings(Object.fromEntries(['font','rows','words','width','x','y'].map(key=>[key,el<HTMLInputElement>(key).value])));layoutDirty=true;history.page=0;void saveSettings();render();};
el('reset-reading').onclick=()=>{reading=readingSettings({font:'native',rows:10,words:'auto',width:576,x:50,y:50});for(const id of ['font','rows','words','width','x','y'] as const)el<HTMLInputElement>(id).value=String(reading[id]);layoutDirty=true;history.page=0;void saveSettings();render();};
el('apply-instructions').onclick=()=>{answerInstructions=el<HTMLTextAreaElement>('answer-instructions').value.trim();keepInstructions=el<HTMLInputElement>('keep-instructions').checked;el('instruction-status').textContent=keepInstructions?'Saved for future answers':'Applies to the next answer';void saveSettings();};
el<HTMLDetailsElement>('interview-pack').ontoggle=()=>{if(el<HTMLDetailsElement>('interview-pack').open&&!packState)void loadPacks();};
el('refresh-packs').onclick=()=>void loadPacks('Refreshed.');
el<HTMLSelectElement>('profile-select').onchange=()=>{const id=el<HTMLSelectElement>('profile-select').value;if(id)void updatePack(()=>packClient().activate(id),'Interview pack activated.');};
el('create-pack').onclick=()=>{const name=el<HTMLInputElement>('pack-name').value.trim(),jd=el<HTMLTextAreaElement>('pack-jd').value.trim();if(!name){el('pack-status').textContent='Enter a pack name.';return;}if(!jd){el('pack-status').textContent='Paste the target job description so answers can match its stack.';return;}void updatePack(()=>packClient().create(name,jd),'Interview pack created and activated.');};
el('upload-material').onclick=()=>{const profile=activeProfile(packState),file=el<HTMLInputElement>('pack-file').files?.[0],kind=el<HTMLSelectElement>('document-kind').value;if(!profile){el('pack-status').textContent='Create or load an interview pack first.';return;}if(!file){el('pack-status').textContent='Choose a PDF, DOCX, TXT, MD or CSV file.';return;}void updatePack(()=>packClient().upload(profile.id,kind,file),'Material uploaded.');};
el('save-prep-notes').onclick=()=>{const profile=activeProfile(packState),notes=el<HTMLTextAreaElement>('prep-notes').value.trim();if(!profile){el('pack-status').textContent='Create or load an interview pack first.';return;}if(!notes){el('pack-status').textContent='Enter prep notes first.';return;}void updatePack(()=>packClient().addNotes(profile.id,notes),'Prep notes saved.');};
el('demo').onclick=()=>{history.add('How would you move website events into GCS and BigQuery?',"I’d capture website events through the application ingestion pipeline and land the raw files in **GCS**. Keeping the original files gives us a way to audit and replay data.\n\n**Airflow** would orchestrate processing, dependencies, retries, and alerts. Python or PySpark jobs would validate schemas, handle duplicates, and apply business rules.\n\nI’d load clean data into **BigQuery staging**, then build curated reporting tables with SQL. I’d check reconciliation and freshness before publishing.\n\n**Website → Ingestion → Raw GCS → Processing → BigQuery staging → Curated tables**");showDraft=false;persist();render();};
window.addEventListener('online',resume);window.addEventListener('pageshow',resume);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')resume();else persist();});
window.addEventListener('pagehide',()=>{cancel();persist();});
setInterval(()=>{
 if(autoActive&&Date.now()-lastAudioAt>10000){void stopAutoConversation('Audio stopped · Auto Conversation ended');screenReady=false;scheduleRecovery();}
 else if(recorder.state==='listening'&&Date.now()-lastAudioAt>10000){void recorder.dispatch(5);status='Audio stopped · previous answer preserved';screenReady=false;scheduleRecovery();}
 if(autoActive||recorder.state==='listening')render();
},1000);
render();void connect();if(token.value)void checkConnection(false);
