import {connectG2} from './g2';
import {LiveState} from './live-state';
import './style.css';
import {lensSafeFrame} from './language';
import {RingMenu} from './ring-menu';
import {mountPreparation} from './preparation';
import {mountDisplay,geometry,defaultDisplay} from './display-settings';
const HOST='phone-only-g2-interview-coach-fawf.onrender.com';
const state=new LiveState();
const menu=new RingMenu();
let display={...defaultDisplay};
document.querySelector<HTMLDivElement>('#app')!.innerHTML=`
<h1>Practice Coach · 0.2.4</h1>
<p id="backend-build">Backend version: connect to check</p>
<nav><button id="open-preparation">Upload resume & notes</button><button id="open-display">Words, characters & window</button></nav>
<p>Start once for continuous questions. Short pauses are combined. Pause or Stop when finished. Keep the Even app active; background capture is not verified.</p>
<label>App access token <input id="token" type="password" autocomplete="off" placeholder="Your Render APP_TOKEN"></label>
<p>Your OpenAI key stays on Render. This token is kept only while this page is open.</p>
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
<p>Speaker recognition and speech-follow scrolling are not enabled in this test.</p>`;
const $=<T extends HTMLElement=HTMLElement>(s:string)=>document.querySelector<T>(s)!;
let g2: Awaited<ReturnType<typeof connectG2>>|undefined;
let connecting: Promise<void>|undefined;
let ws: WebSocket|undefined;
let active=false, busy=false, capture=false, armed=false, epoch=0;
let ping:ReturnType<typeof setInterval>|undefined;
let connectionTimer:ReturnType<typeof setTimeout>|undefined;
const status=(s:string)=>{$('#status').textContent=s;};
function render(){const f=menu.open?menu.frame():state.frame();$('#frame').textContent=f;g2?.layout(menu.open?{x:0,y:0,width:576,height:288}:geometry(display));g2?.show(lensSafeFrame(f));$('#finish').toggleAttribute('disabled',!armed||busy);$('#next').toggleAttribute('disabled',!active||busy||armed);$('#pause').toggleAttribute('disabled',!active);}
function send(type:string){if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type,manual_finish:$<HTMLInputElement>('#manual').checked,continuous:$<HTMLInputElement>('#continuous').checked,output_language:$<HTMLSelectElement>('#answer-language').value}));}
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
function stop(){epoch++;active=false;busy=false;armed=false;void mic(false);clearInterval(ping);clearTimeout(connectionTimer);const old=ws;ws=undefined;old?.close();$('#start').removeAttribute('disabled');status('Stopped — last answer retained');render();}
function next(){if(!active||busy||armed)return;armed=true;$('#transcript').textContent='Listening for the complete question…';status('Starting question capture…');send('listen');render();}
async function connect(){
 if(connecting)return connecting;
 connecting=(async()=>{try{
  status('Connecting to G2…');
  g2=await connectG2({audio:(pcm)=>{
   if(!capture||ws?.readyState!==WebSocket.OPEN)return;
   if(ws.bufferedAmount>128000){armed=false;void mic(false);send('pause');status('Network too slow. Capture paused; tap Next question to retry.');render();return;}
   ws.send(new Uint8Array(pcm));
  },action:(type,direction)=>{
   if(type==='navigate'){if(menu.open)menu.move(direction??0);else state.page+=direction??0;render();}
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
   if(m.type==='ready'){clearTimeout(connectionTimer);$('#backend-build').textContent='Backend: '+(m.build??'older version');if(!m.features?.includes('continuous_questions')){stop();status('Backend update needed. Deploy the 0.2.4 patch to Render, then reconnect.');return;}ping=setInterval(()=>send('ping'),10000);next();}
   else if(m.type==='capture'){
    armed=Boolean(m.active);if(m.active&&!state.answer)state.question='Listening…';void mic(Boolean(m.active));if(m.active)status('Listening — short pauses are allowed');
   }else if(m.type==='transcript.partial'||m.type==='transcript.final'){
    $('#transcript').textContent=m.text; if(!state.answer){state.question=m.text;render();}
   }else if(m.type==='answer.start'){busy=true;state.apply(m);status('Generating answer…');}
   else if(m.type==='answer.delta'){state.apply(m);}
   else if(m.type==='answer.done'){busy=false;state.apply(m);status(capture?'Answer ready — still listening for the next question.':'Answer ready. Resume listening when ready.');}
   else if(m.type==='error'){busy=false;if(!m.keep_capture){armed=false;void mic(false);}status(m.message);}
   else if(m.type==='state')status(m.message);
   render();
  }catch{status('Unexpected server message');}};
  socket.onclose=event=>{if(ws!==socket)return;stop();status(event.code===1008?'Invalid APP_TOKEN. Copy the app token from Render.':'Disconnected. Last answer retained; Start practice opens a new conversation.');};
  socket.onerror=()=>{status('Backend connection failed. Confirm the live backend has been deployed.');};
 }catch(e){if(run!==epoch)return;stop();status(e instanceof Error?e.message:String(e));}
};
function pause(){armed=false;void mic(false);send('pause');status('Microphone paused — last answer retained');render();}
$('#pause').onclick=pause;
$('#finish').onclick=()=>send('finish');
$('#stop').onclick=stop;$('#next').onclick=next;
$('#prev').onclick=()=>{state.page--;render();};$('#page').onclick=()=>{state.page++;render();};
function runAction(action:string){
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
languageSelect.onchange=()=>{try{localStorage.setItem('coach-answer-language',languageSelect.value);}catch{}status('Language saved. Use Next question or Retry last answer to apply.');};
mountPreparation(HOST,()=>$<HTMLInputElement>('#token').value.trim());
mountDisplay(value=>{display=value;state.wordsPerLine=value.words;state.linesPerPage=value.lines;state.charsPerLine=Math.min(value.characters,Math.max(20,Math.floor(value.width/576*38)));state.page=0;render();});
$('#open-preparation').onclick=()=>{const panel=$<HTMLDetailsElement>('#preparation');panel.open=true;panel.scrollIntoView({behavior:'smooth',block:'start'});};
$('#open-display').onclick=()=>{const panel=$<HTMLDetailsElement>('#display-settings');panel.open=true;panel.scrollIntoView({behavior:'smooth',block:'start'});};
$('#continuous').onchange=()=>{if($<HTMLInputElement>('#continuous').checked)$<HTMLInputElement>('#manual').checked=false;if(active){pause();status('Mode changed. Resume listening to apply.');}};
$('#manual').onchange=()=>{if($<HTMLInputElement>('#manual').checked)$<HTMLInputElement>('#continuous').checked=false;if(active){pause();status('Mode changed. Resume listening to apply.');}};
window.addEventListener('pagehide',stop);render();
