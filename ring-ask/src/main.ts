import {waitForEvenAppBridge, CreateStartUpPageContainer, TextContainerProperty, TextContainerUpgrade, AudioInputSource, type EvenAppBridge} from '@evenrealities/even_hub_sdk';
import {Recorder, pages, gesture} from './controller.mjs';
import './style.css';
const el = <T extends HTMLElement>(id:string) => document.getElementById(id) as T;
const backend = el<HTMLInputElement>('backend'), token = el<HTMLInputElement>('token'), mode = el<HTMLSelectElement>('mode');
let bridge:EvenAppBridge|undefined, screenReady=false, status='Ready', answer='Tap the ring to begin a question.', page=0;
let abort:AbortController|undefined, displayQueue=Promise.resolve(), renderTimer:ReturnType<typeof setTimeout>|undefined;
try {
  const saved=JSON.parse(localStorage.getItem('ring-ask-settings')||'{}');
  backend.value=saved.backend||backend.value; token.value=saved.token||''; mode.value=saved.mode||'tap';
  const fragment=new URLSearchParams(location.hash.slice(1));
  if(fragment.get('token')) {token.value=fragment.get('token')!; backend.value=location.origin; history.replaceState(null,'',location.pathname);}
} catch { /* An unavailable store does not prevent entering settings manually. */ }
const recorder = new Recorder(async(on:boolean)=>{
  if(!bridge || !screenReady) throw new Error('Open Ring Ask through Even Hub and connect your G2 first.');
  return bridge.audioControl(on,AudioInputSource.Glasses);
},(message:string|null)=>{if(message) status=message;render();},submit);
recorder.mode=mode.value;
function render() {
  const sheets=pages(answer); page=Math.max(0,Math.min(page,sheets.length-1));
  el('status').textContent=status;el('page').textContent=`${page+1} / ${sheets.length}`;el('display').textContent=sheets[page];
  el<HTMLButtonElement>('start').disabled=recorder.state!=='ready';el<HTMLButtonElement>('stop').disabled=recorder.state!=='listening';
  el<HTMLButtonElement>('up').disabled=page===0;el<HTMLButtonElement>('down').disabled=page===sheets.length-1;
  if(bridge && screenReady && !renderTimer) renderTimer=setTimeout(()=>{
    renderTimer=undefined;
    displayQueue=displayQueue.then(async()=>{
      const current=pages(answer); const content=`${status.slice(0,42)}  ${page+1}/${current.length}\n\n${current[page]||''}`;
      if(!await bridge!.textContainerUpgrade(new TextContainerUpgrade({containerID:1,containerName:'answer',content}))) throw new Error('Glasses display update failed. Reopen Ring Ask.');
    }).catch(error=>{el('hint').textContent=error.message;});
  },180);
}
async function submit(pcm:Uint8Array) {
  answer='';page=0;abort?.abort();const current=new AbortController();abort=current;
  const timeout=setTimeout(()=>current.abort(),95000);
  try {
    const response=await fetch(backend.value.replace(/\/$/,'')+'/api/ask',{method:'POST',headers:{'Content-Type':'application/octet-stream',Authorization:`Bearer ${token.value}`},body:new Blob([new Uint8Array(pcm)]),signal:current.signal});
    if(!response.ok) {const error=await response.json().catch(()=>({}));throw new Error(error.error || `Server error ${response.status}.`);}
    if(!response.body) throw new Error('This WebView does not support streamed responses.');
    const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',done=false;
    while(true) {
      const chunk=await reader.read();if(chunk.done) break;
      buffer+=decoder.decode(chunk.value,{stream:true});
      let lineEnd;
      while((lineEnd=buffer.indexOf('\n'))>=0) {
        const line=buffer.slice(0,lineEnd);buffer=buffer.slice(lineEnd+1);if(!line.trim())continue;
        const event=JSON.parse(line);
        if(event.type==='transcript') {status='Thinking…';el('hint').textContent=`Question: ${event.text}`;}
        if(event.type==='delta') {status='Answer';answer+=event.text;}
        if(event.type==='done') {done=true;status='Answer · tap for next question';}
        if(event.type==='error') throw new Error(event.text);
        render();
      }
    }
    if(!done) throw new Error('Connection interrupted before the answer finished.');
  } finally {clearTimeout(timeout);if(abort===current)abort=undefined;}
}
function dispatch(type:number) {
  if([5,6,7].includes(type)) abort?.abort();
  if(type===1 || type===2) {page+=type===1?-1:1;render();return;}
  // Double-tap is reserved for submission only during a question; otherwise use the OS exit prompt.
  if(type===3 && recorder.state==='ready') {void bridge?.shutDownPageContainer(1);return;}
  void recorder.dispatch(type);
}
el('start').onclick=()=>dispatch(mode.value==='hold'?9:0);
el('stop').onclick=()=>dispatch(3);
el('cancel').onclick=()=>{abort?.abort();void recorder.dispatch(5);};
el('up').onclick=()=>dispatch(1);el('down').onclick=()=>dispatch(2);
el('exit').onclick=async()=>{abort?.abort();await recorder.dispatch(5);await bridge?.shutDownPageContainer(1);};
mode.onchange=()=>{abort?.abort();void recorder.dispatch(5).then(()=>{recorder.mode=mode.value;});};
el('save').onclick=async()=>{
  const save=el<HTMLButtonElement>('save');
  save.disabled=true; save.textContent='Checking…'; el('health').textContent='Checking connection…';
  const check=new AbortController(); const checkTimer=setTimeout(()=>check.abort(),10000);
  try {
    const url=new URL(backend.value);if(!['http:','https:'].includes(url.protocol))throw new Error('Enter an HTTP or HTTPS server URL.');
    backend.value=backend.value.trim().replace(/\/$/,''); token.value=token.value.trim();
    if(!token.value) throw new Error('Enter your existing bridge token first.');
    let saved=true;
    try { localStorage.setItem('ring-ask-settings',JSON.stringify({backend:backend.value,token:token.value,mode:mode.value})); } catch { saved=false; }
    const response=await fetch(backend.value.replace(/\/$/,'')+'/api/health',{headers:{Authorization:`Bearer ${token.value}`},signal:check.signal});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'Connection failed.');
    el('health').textContent=result.configured?(saved?'Connected. Ready for questions.':'Connected for this session. Settings storage is unavailable.'):'Connected. Add the OpenAI key to the server configuration.';
  }catch(error){el('health').textContent=check.signal.aborted?'Connection timed out. Check your internet and try again.':(error as Error).message;}
  finally {clearTimeout(checkTimer);save.disabled=false;save.textContent='Save & check connection';}
};
el('demo').onclick=()=>{if(recorder.state!=='ready')return;status='Sample answer · no AI call';page=0;answer='Manual capture gives you control over the question.\n\nTap once before speaking. Wait until the display says Listening. Double-tap when the question is complete.\n\nThe microphone then stops. Your selected audio goes to the AI server for transcription and an answer.\n\nScroll the ring to move through these pages. Tap again when you want to ask another question.';render();};
window.addEventListener('pagehide',()=>{abort?.abort();void recorder.dispatch(5);});
render();
void (async()=>{
  bridge=await waitForEvenAppBridge();
  const result=await bridge.createStartUpPageContainer(new CreateStartUpPageContainer({containerTotalNum:1,textObject:[new TextContainerProperty({containerID:1,containerName:'answer',xPosition:0,yPosition:0,width:576,height:288,paddingLength:6,borderWidth:0,isEventCapture:1,content:'Ring Ask\n\nTap to listen.\nDouble-tap to submit.\nScroll to read.'})]}));
  if(result!==0) throw new Error(`Glasses page failed to initialize (${result}).`);
  screenReady=true;el('connection').textContent='Even bridge connected';el('hint').textContent='Ready. Wait for Listening before speaking.';
  let inputCount=0;
  bridge.onEvenHubEvent(event=>{
    if(event.audioEvent)recorder.audio(event.audioEvent.audioPcm);
    const type=gesture(event);
    if(type!==null){
      if([0,1,2,3,9,10].includes(type)) el('input-status').textContent=`Ring/glasses events: ${++inputCount} · last ${['tap','up','down','double tap'][type]|| (type===9?'hold':'release')} · ${recorder.state}`;
      dispatch(type);
    }
  });
  render();
})().catch(error=>{el('connection').textContent='Glasses connection unavailable';el('hint').textContent=error.message;});
