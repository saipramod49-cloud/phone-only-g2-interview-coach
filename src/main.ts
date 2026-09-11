import {connectG2} from './g2';
import {mountCoachInstructions} from './coach-instructions';
import {mountModels,formatTiming} from './models';
import {LiveState} from './live-state';
import './style.css';
import {SpeakerTracker,pageForQuote,type Speaker} from './speaker';
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
<h1>Practice Coach · 0.2.7</h1>
<p id="backend-build">Backend version: connect to check</p>
<nav><button id="open-preparation">Upload resume & notes</button><button id="open-display">Words, characters & window</button></nav>
<p>Start once for continuous questions. Short pauses are combined. Pause or Stop when finished. Keep the Even app active; background capture is not verified.</p>
<label>App access token <input id="token" type="password" autocomplete="off" placeholder="Your Render APP_TOKEN"></label>
<p>Your OpenAI key stays on Render. This token is kept only while this page is open.</p>
<p id="speaker-status" role="status">Speaker: Unknown</p>
<label>Speaker control<select id="speaker-mode"><option value="questions">Question detection (speaker unknown)</option><option value="device">Automatic — Even device estimate</option><option value="interviewer">Interviewer — manual</option><option value="candidate">Candidate — manual</option></select></label>
<p>Automatic mode maps the wearer's voice to Candidate and another voice to Interviewer. Verify this with both people before relying on it. Unknown or mixed speech will not trigger answers in automatic mode.</p>
<label>Answer scrolling<select id="scroll-mode"><option value="manual">Manual — ring or phone</option><option value="voice">Voice follow — candidate speech</option></select></label><p id="follow-status">Manual scrolling</p>
<section id="coach-instructions" aria-label="Talk to your coach"></section>
<section id="model-controls" aria-label="Model selection"></section>
<label>Answer language<select id="answer-language"><option value="english">English</option><option value="telugu_latin">Telugu in English letters</option></select></label>
<p>Ask in Telugu, English, or a mix. Lens answers use English or Romanized Telugu. Original question text stays visible on the phone. A language change applies to the next question or Retry last answer.</p>
<label><input id="continuous" type="checkbox" checked> Keep listening for new questions</label>
<p>Question detection can miss indirect questions or mistake your speech for a question. Ring controls remain available.</p>
<label><input id="manual" type="checkbox"> Manual finish — wait until I tap Finish question</label>
<button id="finish" disabled>Finish question</button>
<h2>Captured question</h2><p id="transcript" aria-live="polite">No question captured yet.</p>
<button id="start">Start practice</button><button id="next" disabled>Next question</button>
<button id="actions">Ring actions</button><button id="retry">Retry last answer</button><button id="reconnect">Reconnect & listen</button>
<button id="pause" disabled>Pause microphone</button><button id="stop">Stop</button>
<p id="status" role="status">Ready to connect</p><p id="capture">Microphone off</p>
<pre id="frame"></pre><button id="prev">Previous page</button><button id="page">Next page</button>
<p>Ring / glasses: swipe for answer pages; tap for actions; swipe to choose, tap to run. Double-tap closes the menu, or opens the exit dialog from the answer.</p>
<details id="preparation"></details><details id="display-settings"></details>
<details><summary>Service & deployment</summary><p id="service-info">Connect to view backend version.</p><p>Manage your Render service in Safari: <a href="https://dashboard.render.com/" target="_blank" rel="noopener noreferrer">Render Dashboard</a>. Deployments can interrupt an active practice session.</p></details>`;
const $=<T extends HTMLElement=HTMLElement>(s:string)=>document.querySelector<T>(s)!;
let g2: Awaited<ReturnType<typeof connectG2>>|undefined;
let connecting: Promise<void>|undefined;
let ws: WebSocket|undefined;
let active=false, busy=false, capture=false, armed=false, epoch=0;
let ping:ReturnType<typeof setInterval>|undefined;
let connectionTimer:ReturnType<typeof setTimeout>|undefined;
const status=(s:string)=>{$('#status').textContent=s;};
function render(){const f=menu.open?menu.frame():`${speaker==='unknown'?'SPEAKER ?':speaker.toUpperCase()}\n${state.frame().replace('\n\n','\n')}`;$('#frame').textContent=f;g2?.layout(menu.open?{x:0,y:0,width:576,height:288}:geometry(display));g2?.show(lensSafeFrame(f));$('#finish').toggleAttribute('disabled',!armed||busy);$('#next').toggleAttribute('disabled',!active||busy||armed);$('#pause').toggleAttribute('disabled',!active);}
const modelControls=mountModels(HOST,()=>$<HTMLInputElement>('#token').value.trim(),()=>send('settings'));
const coach=mountCoachInstructions((text)=>{if(ws?.readyState!==WebSocket.OPEN)return false;ws.send(JSON.stringify({type:"coach.instructions",text}));return true;});
function send(type:string){
 try{const selection=['listen','retry','settings'].includes(type)?modelControls.read():{};
  if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type,...selection,manual_finish:$<HTMLInputElement>('#manual').checked,continuous:$<HTMLInputElement>('#continuous').checked,output_language:$<HTMLSelectElement>('#answer-language').value,speaker_gate:$<HTMLSelectElement>('#speaker-mode').value!=='questions',voice_follow:$<HTMLSelectElement>('#scroll-mode').value==='voice'}));
  return true;
 }catch(e){status(e instanceof Error?e.message:'Invalid model settings');return false;}
}
// Serialize mic changes so an old enable cannot win after Stop/Pause.
let micQueue=Promise.resolve();
function mic(on:boolean){
 capture=on;$('#capture').textContent=on?'Microphone on — ask your question':'Microphone off';
 micQueue=micQueue.then(async()=>{
  const target=capture;
  if(!g2)return;
  const ok=await g2.mic(target);
  if(target&&!ok){capture=false;armed=false;send('pause');status('G2 microphone was not enabled. Check the glasses connection and permissions.');$('#capture').textContent='Microphone off';render();}
 }).catch(()=>{capture=false;armed=false;send('pause');status('Microphone control failed');$('#capture').textContent='Microphone off';render();});
 return micQueue;
}
function stop(){wantsListening=false;clearTimeout(recovery);speakerTracker.reset();speaker='unknown';epoch++;active=false;busy=false;armed=false;void mic(false);clearInterval(ping);clearTimeout(connectionTimer);const old=ws;ws=undefined;old?.close();$('#start').removeAttribute('disabled');status('Stopped — last answer retained');render();}
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
   if(type==='end'){stop();g2=undefined;connecting=undefined;}
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
  await connect();if(run!==epoch)return;
  status('Connecting to Render…');
  const socket=new WebSocket(`wss://${HOST}/ws/live`);ws=socket;
  socket.onopen=()=>{if(run!==epoch)return;socket.send(JSON.stringify({type:'auth',token}));};
  socket.onmessage=event=>{if(ws!==socket)return;try{
   const m=JSON.parse(String(event.data));
   if(m.type==='ready'){clearTimeout(connectionTimer);$('#backend-build').textContent='Backend: '+(m.build??'older version');$('#service-info').textContent='Backend '+(m.build??'unknown')+' — connected';if(!m.features?.includes('coach_instructions')){stop();status('Backend update needed. Deploy the 0.2.7 patch to Render, then reconnect.');return;}coach.sync();ping=setInterval(()=>send('ping'),10000);next();}
   else if(m.type==='coach.instructions.saved'){coach.ack(m.active);}
   else if(m.type==='capture'){
    armed=Boolean(m.active);if(m.active&&!state.answer)state.question='Listening…';void mic(Boolean(m.active));if(m.active){recoveryAttempts=0;lastAudioAt=Date.now();}if(m.active)status('Listening — short pauses are allowed');
   }else if(m.type==='transcript.partial'||m.type==='transcript.final'){
    $('#transcript').textContent=m.text; if(!state.answer){state.question=m.text;render();}
   }else if(m.type==='candidate.transcript'){$('#follow-status').textContent='Candidate: '+m.text;}
   else if(m.type==='follow'){if($<HTMLSelectElement>('#scroll-mode').value==='voice'&&m.answer_id===state.answerId&&!menu.open){const page=pageForQuote(state.pages(),m.quote);if(page!==null&&page>=state.page){state.page=Math.min(page,state.page+1);$('#follow-status').textContent='Following your speech';}}}
   else if(m.type==='follow.state'){$('#follow-status').textContent=m.message;}
   else if(m.type==='answer.start'){busy=true;$('#service-info').textContent='Backend '+ '0.2.7'+' — answer model: '+m.model+' · reasoning: '+m.reasoning;$('#model-timing').textContent=formatTiming(null);state.apply(m);status('Generating answer…');}
   else if(m.type==='answer.delta'){if(m.answer_id===state.answerId&&typeof m.first_text_ms==='number')$('#model-timing').textContent=formatTiming(m.first_text_ms);state.apply(m);}
   else if(m.type==='answer.done'){busy=false;if(m.answer_id===state.answerId&&typeof m.total_ms==='number')$('#model-timing').textContent=formatTiming(m.first_text_ms??null,m.total_ms)+' (backend generation time; excludes speech capture and lens delivery)';state.apply(m);status(capture?'Answer ready — still listening for the next question.':'Answer ready. Resume listening when ready.');}
   else if(m.type==='error'){busy=false;if(!m.keep_capture){armed=false;void mic(false);}status(m.message);if(m.recoverable)scheduleRecovery();}
   else if(m.type==='state')status(m.message);
   render();
  }catch{status('Unexpected server message');}};
  socket.onclose=event=>{if(ws!==socket)return;stop();status(event.code===1008?'Invalid APP_TOKEN. Copy the app token from Render.':'Disconnected. Last answer retained; Start practice opens a new conversation.');};
  socket.onerror=()=>{status('Backend connection failed. Confirm the live backend has been deployed.');};
 }catch(e){if(run!==epoch)return;stop();status(e instanceof Error?e.message:String(e));}
};
function pause(){wantsListening=false;clearTimeout(recovery);speakerTracker.reset();speaker='unknown';armed=false;void mic(false);send('pause');status('Microphone paused — last answer retained');render();}
$('#pause').onclick=pause;
$('#finish').onclick=()=>send('finish');
$('#stop').onclick=stop;$('#next').onclick=next;
$('#prev').onclick=()=>{manualScroll();state.page--;render();};$('#page').onclick=()=>{manualScroll();state.page++;render();};
function runAction(action:string){
 if(action==='follow'){const el=$<HTMLSelectElement>('#scroll-mode');el.value=el.value==='voice'?'manual':'voice';setFollow();}
 if(action==='candidate'||action==='interviewer'||action==='device'){$<HTMLSelectElement>('#speaker-mode').value=action;changeSpeaker();}
 if(action==='listen'){if(!active)$('#start').click();else next();}
 if(action==='finish')send('finish');
 if(action==='pause')pause();
 if(action==='retry'){if(!active){status('Reconnect, then repeat the question. The old connection history is unavailable.');return;}send('retry');}
 if(action==='reconnect'){stop();$('#start').click();}
}
$('#actions').onclick=()=>{menu.open=!menu.open;render();};
$('#retry').onclick=()=>runAction('retry');$('#reconnect').onclick=()=>runAction('reconnect');
const languageSelect=$<HTMLSelectElement>('#answer-language');
try{const saved=localStorage.getItem('coach-answer-language');if(saved==='english'||saved==='telugu_latin')languageSelect.value=saved;}catch{}
languageSelect.onchange=()=>{try{localStorage.setItem('coach-answer-language',languageSelect.value);}catch{}send('settings');status('Language saved for the next answer.');};
mountPreparation(HOST,()=>$<HTMLInputElement>('#token').value.trim());
mountDisplay(value=>{display=value;state.wordsPerLine=value.words;state.linesPerPage=value.lines;state.charsPerLine=Math.min(value.characters,Math.max(20,Math.floor(value.width/576*38)));state.page=0;render();});
$('#open-preparation').onclick=()=>{const panel=$<HTMLDetailsElement>('#preparation');panel.open=true;panel.scrollIntoView({behavior:'smooth',block:'start'});};
$('#open-display').onclick=()=>{const panel=$<HTMLDetailsElement>('#display-settings');panel.open=true;panel.scrollIntoView({behavior:'smooth',block:'start'});};
$('#continuous').onchange=()=>{if($<HTMLInputElement>('#continuous').checked)$<HTMLInputElement>('#manual').checked=false;if(active){pause();status('Mode changed. Resume listening to apply.');}};
$('#manual').onchange=()=>{if($<HTMLInputElement>('#manual').checked)$<HTMLInputElement>('#continuous').checked=false;if(active){pause();status('Mode changed. Resume listening to apply.');}};
function socketRole(role:string){if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'speaker',role}));}
function manualScroll(){$<HTMLSelectElement>('#scroll-mode').value='manual';setFollow();}
function setFollow(){const enabled=$<HTMLSelectElement>('#scroll-mode').value==='voice';$('#follow-status').textContent=enabled?'Voice follow enabled; waiting for candidate speech.':'Manual scrolling';if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'follow.mode',enabled}));}
function changeSpeaker(){speakerTracker.reset();lastSentRole='';if(active){pause();next();}render();}
$('#speaker-mode').onchange=changeSpeaker;$('#scroll-mode').onchange=setFollow;
function scheduleRecovery(){
 if(!active||!wantsListening||recoveryAttempts>=3)return;
 const run=epoch;const deadline=Date.now()+60000;const delay=2000*2**recoveryAttempts++;
 const attempt=()=>{if(run!==epoch||!active||!wantsListening)return;if(busy){if(Date.now()<deadline)recovery=setTimeout(attempt,1000);return;}next();};
 clearTimeout(recovery);recovery=setTimeout(attempt,delay);
}
setInterval(()=>{if(capture&&lastAudioAt&&Date.now()-lastAudioAt>5000){speaker='unknown';$('#speaker-status').textContent='Speaker: Unknown — no recent audio frames';$('#capture').textContent='No recent audio frames. Check Even is active and the glasses are connected.';render();}},2000);
window.addEventListener('pagehide',stop);render();
