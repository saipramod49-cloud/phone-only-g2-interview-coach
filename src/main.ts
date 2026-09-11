import {connectG2} from './g2';
import {LiveState} from './live-state';
import './style.css';
import {RingMenu} from './ring-menu';
import {mountPreparation} from './preparation';
import {mountDisplay,geometry,defaultDisplay} from './display-settings';
const HOST='phone-only-g2-interview-coach-fawf.onrender.com';
const state=new LiveState();
const menu=new RingMenu();
let display={...defaultDisplay};
document.querySelector<HTMLDivElement>('#app')!.innerHTML=`
<h1>Practice Coach · Live test</h1>
<p>Ask your complete question. Short pauses are combined; after a quiet pause, your answer starts. Choose manual finish for longer pauses.</p>
<label>App access token <input id="token" type="password" autocomplete="off" placeholder="Your Render APP_TOKEN"></label>
<p>Your OpenAI key stays on Render. This token is kept only while this page is open.</p>
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
function render(){const f=menu.open?menu.frame():state.frame();$('#frame').textContent=f;g2?.layout(menu.open?{x:0,y:0,width:576,height:288}:geometry(display));g2?.show(f);$('#finish').toggleAttribute('disabled',!armed||busy);$('#next').toggleAttribute('disabled',!active||busy||armed);$('#pause').toggleAttribute('disabled',!active);}
function send(type:string){if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type,manual_finish:$<HTMLInputElement>('#manual').checked}));}
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
   if(m.type==='ready'){clearTimeout(connectionTimer);ping=setInterval(()=>send('ping'),10000);next();}
   else if(m.type==='capture'){
    armed=Boolean(m.active);if(m.active&&!state.answer)state.question='Listening…';void mic(Boolean(m.active));if(m.active)status('Listening — short pauses are allowed');
   }else if(m.type==='transcript.partial'||m.type==='transcript.final'){
    $('#transcript').textContent=m.text; if(!state.answer){state.question=m.text;render();}
   }else if(m.type==='answer.start'){busy=true;state.apply(m);status('Generating answer…');}
   else if(m.type==='answer.delta'){state.apply(m);}
   else if(m.type==='answer.done'){busy=false;state.apply(m);status('Answer ready. Tap Next question for a follow-up.');}
   else if(m.type==='error'){busy=false;armed=false;void mic(false);status(m.message);}
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
mountPreparation(HOST,()=>$<HTMLInputElement>('#token').value.trim());
mountDisplay(value=>{display=value;state.wordsPerLine=value.words;state.linesPerPage=value.lines;state.charsPerLine=Math.max(20,Math.floor(value.width/576*38));state.page=0;render();});
window.addEventListener('pagehide',stop);render();
