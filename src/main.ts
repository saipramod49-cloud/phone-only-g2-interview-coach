import {connectG2} from './g2';
import {ProfileMemory,type SavedProfile} from './saved-settings';
import {mountCoachInstructions} from './coach-instructions';
import {mountModels,formatTiming} from './models';
import {LiveState} from './live-state';
import './style.css';
import {SpeakerTracker,lineForSpeech,type Speaker} from './speaker';
import {lensSafeFrame} from './language';
import {RingMenu} from './ring-menu';
import {mountPreparation} from './preparation';
import {mountDisplay,geometry,defaultDisplay} from './display-settings';
const HOST='phone-only-g2-interview-coach-fawf.onrender.com';
const state=new LiveState();
const menu=new RingMenu();
let display={...defaultDisplay};
const speakerTracker=new SpeakerTracker();
let speaker:Speaker='unknown';
let lastSentRole='';
let lastAudioAt=0;
let recovery:ReturnType<typeof setTimeout>|undefined;
let recoveryAttempts=0;
let wantsListening=false;
document.querySelector<HTMLDivElement>('#app')!.innerHTML=`
<header><h1>Practice Coach · 0.2.8</h1><p id="backend-build">Backend version: connect to check</p></header>
<section id="saved-profile-area" class="card"><h2>Your profile</h2><p id="saved-status">Choose a profile to restore its settings.</p>
<label>App access token<input id="token" type="password" autocomplete="off" placeholder="Your Render APP_TOKEN"></label>
<label><input id="remember-token" type="checkbox" checked> Remember app token on this phone</label>
<p class="muted">Settings and, if selected, the app token are stored on this phone. Your OpenAI key stays on Render.</p>
<button id="save-settings">Save profile settings</button><button id="forget-settings">Forget saved settings & token</button>
<button id="open-preparation">Resume, notes & profiles</button></section>
<section class="live-controls"><p id="mode-status" role="status">Stopped</p><p id="speaker-status">Speaker: Unknown</p>
<button id="start">Start practice</button><button id="pause" disabled>Pause microphone</button><button id="stop">Stop</button>
<p id="status" role="status">Ready to connect</p><p id="capture">Microphone off</p></section>
<section class="card"><h2>What I’m hearing</h2><p id="transcript" aria-live="polite">No question captured yet.</p>
<p id="candidate-heard"></p><button id="finish" disabled>Answer captured question</button><button id="clear-question">Clear captured question</button>
<button id="next" disabled>Resume question listening</button></section>
<section class="card"><h2>Answer</h2><p id="context-note"></p><p id="follow-status">Manual scrolling</p><pre id="frame"></pre>
<div class="button-row"><button id="prev">Previous page</button><button id="page">Next page</button></div>
<button id="actions">Ring actions</button><button id="retry">Retry captured question</button><button id="reconnect">Reconnect & listen</button>
<details><summary>Full answer on phone</summary><p id="full-answer"></p></details></section>
<details id="behavior"><summary>Listening & answer display</summary>
<label>Question capture<select id="turn-mode"><option value="semantic">Understand complete question / story</option><option value="pause">Pause-based — no completeness check</option></select></label>
<label>Pause before checking the question<select id="quiet-seconds"><option value="1.5">1.5 seconds — fast</option><option value="3" selected>3 seconds — balanced</option><option value="5">5 seconds — longer stories</option><option value="8">8 seconds — long pauses</option></select></label>
<p>A pause starts the completeness check. Incomplete story context stays visible. Tap Answer captured question to finish explicitly.</p>
<label><input id="continuous" type="checkbox" checked> Keep listening between questions</label>
<label><input id="manual" type="checkbox"> Wait for Answer captured question every time</label>
<label>Speaker control<select id="speaker-mode"><option value="questions">Conversation content — speaker unknown</option><option value="device">Strict Even device speaker estimate</option><option value="interviewer">Interviewer — manual</option><option value="candidate">Candidate — manual</option></select></label>
<p>Content detection is not voice identification. Strict mode holds uncertain speech; manual roles override it.</p>
<label>Project answers<select id="presentation"><option value="stream">Teleprompter — show text as generated</option><option value="complete">Completed answer — wait until ready</option></select></label>
<label>Scrolling<select id="scroll-mode"><option value="manual">Manual — phone, glasses or ring</option><option value="timed">Automatic — chosen reading speed</option><option value="voice">Voice follow — match my spoken answer</option></select></label>
<label>Automatic reading speed (words/minute)<input id="reading-speed" type="number" min="60" max="240" value="120"></label>
<label><input id="lens-question" type="checkbox" checked> Show the live question on glasses while capturing it</label>
<p>The full answer is available on the phone. The glasses window holds a few lines; choose scrolling to read longer answers. A manual swipe switches automatic scrolling to Manual.</p>
<label>Use preparation<select id="grounding-mode"><option value="personalized">My profile and relevant notes</option><option value="general">Technical reasoning — ignore my documents</option></select></label>
<label>Answer language<select id="answer-language"><option value="english">English</option><option value="telugu_latin">Telugu in English letters</option></select></label>
<button id="open-display">Words, characters & window</button></details>
<section id="coach-instructions" aria-label="Talk to your coach"></section>
<details><summary>Answer model & timing</summary><section id="model-controls"></section></details>
<details id="preparation"></details><details id="display-settings"></details>
<details id="service-panel"><summary>Service & deployment</summary><p id="service-info">Connect to view backend version.</p>
<p>Manage Render in Safari, then return to Even. This panel stays in the coach.</p><button id="copy-render">Copy Render link for Safari</button>
<input id="render-url" readonly value="https://dashboard.render.com/" aria-label="Render dashboard URL">
<button id="back-practice">Back to practice</button></details>`;
const $=<T extends HTMLElement=HTMLElement>(s:string)=>document.querySelector<T>(s)!;
let g2: Awaited<ReturnType<typeof connectG2>>|undefined;
let connecting: Promise<void>|undefined;
let ws: WebSocket|undefined;
let active=false, busy=false, capture=false, armed=false, epoch=0;
let phase='stopped',draftQuestion='',settingsReady=false,restoring=false,currentProfile='';
let scrollDue=0,persistEnabled=true;let defaults:SavedProfile|undefined;let memory:ProfileMemory|undefined;
try{memory=new ProfileMemory(localStorage,HOST);}catch{}
let ping:ReturnType<typeof setInterval>|undefined;
let connectionTimer:ReturnType<typeof setTimeout>|undefined;
const status=(s:string)=>{$('#status').textContent=s;};
function render(){
 const labels:Record<string,string>={stopped:'Stopped',paused:'Microphone paused',listening:'Listening for the interviewer’s question',checking:'Checking whether the question is complete',waiting:'Holding story context — waiting for the ending',generating:'Preparing the answer',following:'Following spoken answer',candidate:'Hearing candidate speech',reconnecting:'Reconnecting'};
 $('#mode-status').textContent=labels[phase]??phase;
 let frame=state.frame();
 if(draftQuestion&&$<HTMLInputElement>('#lens-question').checked&&['listening','waiting','checking'].includes(phase)){
  const lines=state.lines(draftQuestion);frame='QUESTION · LIVE\n\n'+lines.slice(-state.linesPerPage).join('\n');
 }
 const f=menu.open?menu.frame():`${speaker==='unknown'?'SPEAKER ?':speaker.toUpperCase()} · ${phase.toUpperCase()}\n${frame.replace('\n\n','\n')}`;
 $('#frame').textContent=f;$('#full-answer').textContent=state.answer;
 g2?.layout(menu.open?{x:0,y:0,width:576,height:288}:geometry(display));g2?.show(lensSafeFrame(f));
 $('#finish').toggleAttribute('disabled',!armed);$('#next').toggleAttribute('disabled',!active||armed);
 $('#pause').toggleAttribute('disabled',!active);
}
const modelControls=mountModels(HOST,()=>$<HTMLInputElement>('#token').value.trim(),()=>{send('settings');saveSettings();});
const coach=mountCoachInstructions((text)=>{if(ws?.readyState!==WebSocket.OPEN)return false;ws.send(JSON.stringify({type:"coach.instructions",text}));return true;},()=>saveSettings());
function send(type:string){
 try{const selection=['listen','retry','settings'].includes(type)?modelControls.read():{};
  if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type,...selection,manual_finish:$<HTMLInputElement>('#manual').checked,continuous:$<HTMLInputElement>('#continuous').checked,output_language:$<HTMLSelectElement>('#answer-language').value,speaker_gate:$<HTMLSelectElement>('#speaker-mode').value==='device',voice_follow:$<HTMLSelectElement>('#scroll-mode').value==='voice',turn_mode:$<HTMLSelectElement>('#turn-mode').value,quiet_seconds:Number($<HTMLSelectElement>('#quiet-seconds').value),flow_events:true,profile_id:currentProfile||null,grounding_mode:$<HTMLSelectElement>('#grounding-mode').value}));
  return true;
 }catch(e){status(e instanceof Error?e.message:'Invalid model settings');return false;}
}
// Serialize mic changes so an old enable cannot win after Stop/Pause.
let micQueue=Promise.resolve();let enabledMic:boolean|undefined=false;
function mic(on:boolean){
 capture=on;$('#capture').textContent=on?'Microphone on — ask your question':'Microphone off';
 micQueue=micQueue.then(async()=>{
  const target=capture;
  if(!g2)return;
  if(target===enabledMic)return;
  const ok=await g2.mic(target);
  enabledMic=ok?target:undefined;
  if(target&&!ok){enabledMic=false;capture=false;armed=false;phase='paused';send('pause');status('G2 microphone was not enabled. Reconnect glasses and tap Reconnect & listen.');$('#capture').textContent='Microphone off';render();}
 }).catch(()=>{enabledMic=undefined;capture=false;armed=false;send('pause');status('Microphone control failed');$('#capture').textContent='Microphone off';render();});
 return micQueue;
}
function stop(){saveSettings();phase='stopped';wantsListening=false;clearTimeout(recovery);speakerTracker.reset();speaker='unknown';epoch++;active=false;busy=false;armed=false;void mic(false);clearInterval(ping);clearTimeout(connectionTimer);const old=ws;ws=undefined;old?.close();$('#start').removeAttribute('disabled');status('Stopped — last answer retained');render();}
function next(){if(!active||(!($<HTMLInputElement>('#continuous').checked)&&busy)||armed)return;wantsListening=true;lastSentRole='';armed=true;$('#transcript').textContent='Listening for the complete question…';status('Starting question capture…');if(!send('listen'))armed=false;render();}
async function connect(){
 if(connecting)return connecting;
 connecting=(async()=>{try{
  status('Connecting to G2…');
  g2=await connectG2({audio:(pcm,rawRole)=>{
   if(!capture||ws?.readyState!==WebSocket.OPEN)return;
   if(ws.bufferedAmount>128000){armed=false;void mic(false);send('pause');status('Network too slow. Capture paused; tap Next question to retry.');render();return;}
   lastAudioAt=Date.now();
   const mode=$<HTMLSelectElement>('#speaker-mode').value;
   const previous=speaker;
   speaker=mode==='questions'?'unknown':speakerTracker.update(pcm,rawRole,mode);
   const role=mode==='candidate'||mode==='interviewer'?mode:mode==='device'?(rawRole==='self'?'candidate':rawRole==='other'?'interviewer':'unknown'):'unknown';
   if(role!==lastSentRole){socketRole(role);lastSentRole=role;}
   if(previous!==speaker){$('#speaker-status').textContent='Speaker: '+speaker+(mode==='device'&&speaker!=='unknown'?' (device estimate)':'');render();}
   ws.send(new Uint8Array(pcm));
  },action:(type,direction)=>{
   if(type==='navigate'){if(menu.open)menu.move(direction??0);else {manualScroll();state.page+=direction??0;}render();}
   if(type==='resume'){const action=menu.tap();if(action)runAction(action);render();}
   if(type==='menu'){menu.open=true;render();}
   if(type==='back'){const handled=menu.back();render();return handled;}
   if(type==='end'){stop();enabledMic=false;g2=undefined;connecting=undefined;}
  },status,ack:()=>{}});
  render();
 }catch(e){connecting=undefined;throw e;}})();return connecting;
}
$('#start').onclick=async()=>{
 const token=$<HTMLInputElement>('#token').value.trim();
 if(!token){status('Enter APP_TOKEN from Render.');return;}
 if(active)return;
 active=true;const run=++epoch;$('#start').setAttribute('disabled','');
 connectionTimer=setTimeout(()=>{if(run===epoch){stop();status('Connection timed out. Check Render is awake and the glasses are connected.');}},45000);
 try{
  await preparation.ensure();if(run!==epoch)return;saveSettings();
  await connect();if(run!==epoch)return;
  status('Connecting to Render…');
  const socket=new WebSocket(`wss://${HOST}/ws/live`);ws=socket;
  socket.onopen=()=>{if(run!==epoch)return;socket.send(JSON.stringify({type:'auth',token}));};
  socket.onmessage=event=>{if(ws!==socket)return;try{
   const m=JSON.parse(String(event.data));
   if(m.type==='ready'){clearTimeout(connectionTimer);$('#backend-build').textContent='Backend: '+(m.build??'older version');$('#service-info').textContent='Backend '+(m.build??'unknown')+' — connected';if(!m.features?.includes('natural_flow')){stop();status('Backend update needed. Deploy the 0.2.8 patch to Render, then reconnect.');return;}coach.sync();ping=setInterval(()=>send('ping'),10000);next();}
   else if(m.type==='coach.instructions.saved'){coach.ack(m.active);}
   else if(m.type==='flow'){phase=m.phase;if(m.reason)status(m.reason);if(m.sources)$('#context-note').textContent=(m.profile||'No profile')+' · '+(m.grounding==='general'?'Documents disabled.':m.sources.length?'Relevant notes: '+m.sources.join(', '):'No matching note excerpts.');}
   else if(m.type==='capture'){
    armed=Boolean(m.active);phase=m.active?'listening':'paused';if(m.active&&!state.answer)state.question='Listening…';void mic(Boolean(m.active));if(m.active){recoveryAttempts=0;lastAudioAt=Date.now();}if(m.active)status('Listening — short pauses are allowed');
   }else if(m.type==='transcript.partial'||m.type==='transcript.final'){
    $('#transcript').textContent=m.text||'No question captured yet.';draftQuestion=m.text;state.question=m.text;
    if($<HTMLSelectElement>('#scroll-mode').value==='voice'&&state.answer&&lineForSpeech(state.lines(),m.text)!==null){followSpeech(m.text);draftQuestion='';}
   }else if(m.type==='candidate.transcript'||m.type==='candidate.partial'){$('#candidate-heard').textContent='Answer speech: '+m.text;draftQuestion='';phase='candidate';followSpeech(m.text);}
   else if(m.type==='follow'){if(m.answer_id===state.answerId)followSpeech(m.quote);}
   else if(m.type==='follow.state'){$('#follow-status').textContent=m.message;}
   else if(m.type==='answer.start'){busy=true;phase='generating';draftQuestion='';scrollDue=0;$('#service-info').textContent='Backend '+ '0.2.8'+' — answer model: '+m.model+' · reasoning: '+m.reasoning;$('#model-timing').textContent=formatTiming(null);state.apply(m);status('Generating answer…');}
   else if(m.type==='answer.delta'){if(m.answer_id===state.answerId&&typeof m.first_text_ms==='number')$('#model-timing').textContent=formatTiming(m.first_text_ms);state.apply(m);}
   else if(m.type==='answer.done'){busy=false;phase=capture?'listening':'paused';if(m.answer_id===state.answerId&&typeof m.total_ms==='number')$('#model-timing').textContent=formatTiming(m.first_text_ms??null,m.total_ms)+' (backend generation time; excludes speech capture and lens delivery)';state.apply(m);status(capture?'Answer ready — still listening for the next question.':'Answer ready. Resume listening when ready.');}
   else if(m.type==='error'){busy=false;if(!m.keep_capture){armed=false;void mic(false);}status(m.message);if(m.recoverable)scheduleRecovery();}
   else if(m.type==='state')status(m.message);
   render();
  }catch{status('Unexpected server message');}};
  socket.onclose=event=>{if(ws!==socket)return;stop();status(event.code===1008?'Invalid APP_TOKEN. Copy the app token from Render.':'Disconnected. Last answer retained; Start practice opens a new conversation.');};
  socket.onerror=()=>{status('Backend connection failed. Confirm the live backend has been deployed.');};
 }catch(e){if(run!==epoch)return;stop();status(e instanceof Error?e.message:String(e));}
};
function pause(){phase='paused';wantsListening=false;clearTimeout(recovery);speakerTracker.reset();speaker='unknown';armed=false;void mic(false);send('pause');status('Microphone paused — last answer retained');render();}
$('#pause').onclick=pause;
$('#finish').onclick=()=>send('finish');
$('#clear-question').onclick=()=>{send('clear.question');draftQuestion='';state.question='';$('#transcript').textContent='No question captured yet.';render();};
$('#stop').onclick=stop;$('#next').onclick=next;
$('#prev').onclick=()=>{manualScroll();state.page--;render();};$('#page').onclick=()=>{manualScroll();state.page++;render();};
function runAction(action:string){
 if(action==='follow'){const el=$<HTMLSelectElement>('#scroll-mode');el.value=el.value==='voice'?'manual':'voice';setFollow();}
 if(action==='candidate'||action==='interviewer'||action==='device'){$<HTMLSelectElement>('#speaker-mode').value=action;changeSpeaker();}
 if(action==='listen'){if(!active)$('#start').click();else next();}
 if(action==='finish')send('finish');
 if(action==='pause')pause();
 if(action==='retry'){if(!active){status('Reconnect, then repeat the question. The old connection history is unavailable.');return;}send('retry');}
 if(action==='reconnect'){void (async()=>{stop();await micQueue;await g2?.close();g2=undefined;connecting=undefined;enabledMic=false;$('#start').click();})();}
}
$('#actions').onclick=()=>{menu.open=!menu.open;render();};
$('#retry').onclick=()=>runAction('retry');$('#reconnect').onclick=()=>runAction('reconnect');
const languageSelect=$<HTMLSelectElement>('#answer-language');
try{const saved=localStorage.getItem('coach-answer-language');if(saved==='english'||saved==='telugu_latin')languageSelect.value=saved;}catch{}
languageSelect.onchange=()=>{try{localStorage.setItem('coach-answer-language',languageSelect.value);}catch{}saveSettings();send('settings');status('Language saved for the next answer.');};
const preparation=mountPreparation(HOST,()=>$<HTMLInputElement>('#token').value.trim(),()=>memory?.last()??'',selectProfile);
$('#saved-profile-area').prepend($('#profile-selector'));
const displayControls=mountDisplay(value=>{display=value;state.wordsPerLine=value.words;state.linesPerPage=value.lines;state.charsPerLine=Math.min(value.characters,Math.max(20,Math.floor(value.width/576*38)));state.page=0;render();saveSettings();});
$('#open-preparation').onclick=()=>{const panel=$<HTMLDetailsElement>('#preparation');panel.open=true;panel.scrollIntoView({behavior:'smooth',block:'start'});};
$('#open-display').onclick=()=>{const panel=$<HTMLDetailsElement>('#display-settings');panel.open=true;panel.scrollIntoView({behavior:'smooth',block:'start'});};
$('#continuous').onchange=()=>{saveSettings();if(active){pause();next();}};
$('#manual').onchange=()=>{saveSettings();send('settings');};
function socketRole(role:string){if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'speaker',role}));}
function manualScroll(){$<HTMLSelectElement>('#scroll-mode').value='manual';setFollow();}
function setFollow(){const mode=$<HTMLSelectElement>('#scroll-mode').value;scrollDue=0;$('#follow-status').textContent=mode==='voice'?'Voice follow: waiting for a phrase match. If speech is not recognized, choose Candidate manually.':mode==='timed'?'Automatic scrolling at your reading speed.':'Manual scrolling';if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'follow.mode',enabled:mode==='voice'}));saveSettings();}
function followSpeech(text:string){if($<HTMLSelectElement>('#scroll-mode').value!=='voice'||menu.open)return;const line=lineForSpeech(state.lines(),text);if(line!==null){state.followLine(line);phase='following';$('#follow-status').textContent='Following matched words in your answer';}else{$('#follow-status').textContent='Speech heard, no reliable answer match — holding position';}render();}

function changeSpeaker(){speakerTracker.reset();lastSentRole='';saveSettings();send('settings');render();}
$('#speaker-mode').onchange=changeSpeaker;$('#scroll-mode').onchange=setFollow;
function scheduleRecovery(){
 if(!active||!wantsListening||recoveryAttempts>=3)return;
 const run=epoch;const deadline=Date.now()+60000;const delay=2000*2**recoveryAttempts++;
 const attempt=()=>{if(run!==epoch||!active||!wantsListening)return;if(busy){if(Date.now()<deadline)recovery=setTimeout(attempt,1000);return;}next();};
 clearTimeout(recovery);recovery=setTimeout(attempt,delay);
}
setInterval(()=>{if(capture&&lastAudioAt&&Date.now()-lastAudioAt>5000){speaker='unknown';$('#speaker-status').textContent='Speaker: Unknown — no recent audio frames';$('#capture').textContent='No recent audio frames. Check Even is active and the glasses are connected.';render();}},2000);

const preferenceIds=['speaker-mode','scroll-mode','answer-language','continuous','manual','presentation','reading-speed','turn-mode','quiet-seconds','lens-question','grounding-mode'];
function saveSettings(){
 if(!settingsReady||restoring||!memory||!persistEnabled)return;
 try{const values:Record<string,string|boolean>={};for(const id of preferenceIds){const el=$<HTMLInputElement>('#'+id);values[id]=el.type==='checkbox'?el.checked:el.value;}
  memory.save(currentProfile||'default',{values,model:modelControls.read(),instructions:coach.read(),display:{...display}},$<HTMLInputElement>('#token').value.trim(),$<HTMLInputElement>('#remember-token').checked);
  $('#saved-status').textContent='Settings saved on this phone for '+(currentProfile?'the selected profile.':'your next session.');
 }catch{$('#saved-status').textContent='Could not save these settings. Check the selected model and phone storage.';}
}
function restoreProfile(saved?:SavedProfile){
 saved=saved??defaults;restoring=true;
 if(saved){for(const [id,value] of Object.entries(saved.values)){if(!preferenceIds.includes(id))continue;const el=$<HTMLInputElement>('#'+id);if(el.type==='checkbox')el.checked=value===true;else if(typeof value==='string'){const prior=el.value;el.value=value;if(el.tagName==='SELECT'&&!el.value)el.value=prior;}}
 modelControls.restore(saved.model);coach.restore(saved.instructions);displayControls.restore(saved.display);
 }
 state.setPresentation($<HTMLSelectElement>('#presentation').value==='complete'?'complete':'stream');setFollow();restoring=false;render();
}
function selectProfile(id:string){
 if(id===currentProfile)return;
 if(currentProfile)saveSettings();
 if(currentProfile&&active)stop();
 currentProfile=id;
 restoreProfile(memory?.load(id)??memory?.load('default'));saveSettings();
}
$('#save-settings').onclick=()=>{persistEnabled=true;saveSettings();};
$('#forget-settings').onclick=()=>{stop();persistEnabled=false;memory?.forget();$<HTMLInputElement>('#token').value='';$<HTMLInputElement>('#remember-token').checked=false;$('#saved-status').textContent='Saved settings and token removed from this phone. Server documents are unchanged.';};
$('#token').onchange=()=>{if(active)stop();persistEnabled=true;saveSettings();if($<HTMLInputElement>('#token').value.trim())void preparation.load();};
$('#remember-token').onchange=saveSettings;
for(const id of ['presentation','reading-speed','turn-mode','quiet-seconds','lens-question','grounding-mode'])$('#'+id).addEventListener('change',()=>{state.setPresentation($<HTMLSelectElement>('#presentation').value==='complete'?'complete':'stream');scrollDue=0;saveSettings();send('settings');render();});
$('#copy-render').onclick=async()=>{saveSettings();try{await navigator.clipboard.writeText('https://dashboard.render.com/');status('Render link copied. Paste it into Safari; return to Even afterward.');}catch{$<HTMLInputElement>('#render-url').select();status('Copy the selected Render link and paste it into Safari.');}};
$('#back-practice').onclick=()=>{$<HTMLDetailsElement>('#service-panel').open=false;$('#mode-status').scrollIntoView({block:'start',behavior:'smooth'});};
setInterval(()=>{
 if($<HTMLSelectElement>('#scroll-mode').value!=='timed'||menu.open||!state.answer||draftQuestion||!active)return;
 if(state.pending&&state.presentation==='complete')return;
 const now=Date.now();const wpm=Math.max(60,Math.min(240,Number($<HTMLInputElement>('#reading-speed').value)||120));
 if(!scrollDue){scrollDue=now+Math.max(1200,60000/wpm*state.wordsPerLine);return;}
 if(now<scrollDue)return;state.scrollLines(1);scrollDue=now+60000/wpm*state.wordsPerLine;render();
},200);
const initialValues:Record<string,string|boolean>={};for(const id of preferenceIds){const el=$<HTMLInputElement>('#'+id);initialValues[id]=el.type==='checkbox'?el.checked:el.value;}
defaults={values:initialValues,model:modelControls.read(),instructions:'',display:{...defaultDisplay}};
settingsReady=true;
const remembered=memory?.token();if(remembered)$<HTMLInputElement>('#token').value=remembered;
restoreProfile(memory?.load(memory.last())??memory?.load('default'));
if(remembered)void preparation.load();
window.addEventListener('pagehide',()=>{saveSettings();stop();});
render();
