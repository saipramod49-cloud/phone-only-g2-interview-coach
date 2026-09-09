import { waitForEvenAppBridge, CreateStartUpPageContainer, TextContainerProperty, TextContainerUpgrade, AudioInputSource, OsEventTypeList } from "@evenrealities/even_hub_sdk";
import "./style.css";
import { connectionUrl, glassesText } from "./format";
import { parseMessage } from "./protocol";

const STORAGE = "interviewlens.profile.v1";
type Profile = { serviceUrl: string; token: string; selectedProfile?: string };

async function boot() {
  const root = document.querySelector<HTMLElement>("#app")!;
  const bridge = await waitForEvenAppBridge();
  let profile = await loadProfile(bridge);
  let ws: WebSocket | undefined;
  let body = "Open Interview Lens on your phone\nto connect your service.";
  let status = "NOT CONNECTED";
  let answer = "";
  let reconnect: ReturnType<typeof setTimeout> | undefined;

  await bridge.createStartUpPageContainer(new CreateStartUpPageContainer({
    containerTotalNum: 2,
    textObject: [
      new TextContainerProperty({containerID:1,containerName:"answer",xPosition:0,yPosition:0,width:576,height:246,paddingLength:10,content:body,isEventCapture:1}),
      new TextContainerProperty({containerID:2,containerName:"status",xPosition:0,yPosition:250,width:576,height:38,paddingLength:6,content:status})
    ]
  }));

  const setText = async (id: number, name: string, content: string) => bridge.textContainerUpgrade(new TextContainerUpgrade({containerID:id,containerName:name,contentOffset:0,contentLength:0,content}));
  const show = async () => { await setText(1,"answer",glassesText(body)); await setText(2,"status",status); };
  const renderPhone = (message = "") => {
    root.innerHTML = `<div class="shell"><div class="card"><h1>Interview Lens</h1><div class="muted">Phone + Even G2</div><div class="status"><b>${escapeHtml(status)}</b><br>${escapeHtml(message)}</div><form id="setup"><label>Hosted service URL</label><input id="url" type="url" inputmode="url" placeholder="https://your-service.onrender.com" value="${escapeHtml(profile?.serviceUrl ?? "")}" required><label>Access token</label><input id="token" type="password" autocomplete="current-password" value="${escapeHtml(profile?.token ?? "")}" required><button>Save & connect</button></form><button id="stop" class="danger">Stop listening</button><small>Keep this Even Hub app open during the interview. Audio is sent only while listening.</small></div></div>`;
    root.querySelector<HTMLFormElement>("#setup")!.onsubmit = e => { e.preventDefault(); void save(); };
    root.querySelector<HTMLButtonElement>("#stop")!.onclick = () => { void bridge.audioControl(false, AudioInputSource.Glasses); ws?.close(); status="STOPPED"; void show(); renderPhone("Microphone off"); };
  };
  async function save() {
    try {
      const next = {serviceUrl:(root.querySelector<HTMLInputElement>("#url")!).value.trim().replace(/\/$/,""),token:(root.querySelector<HTMLInputElement>("#token")!).value.trim()};
      connectionUrl(next.serviceUrl); profile = next; await bridge.setLocalStorage(STORAGE, JSON.stringify(next)); connect();
    } catch (e) { renderPhone(e instanceof Error ? e.message : "Invalid setup"); }
  }
  function connect() {
    if (!profile) return;
    clearTimeout(reconnect); ws?.close(); status="CONNECTING"; void show(); renderPhone();
    ws = new WebSocket(`${connectionUrl(profile.serviceUrl)}?token=${encodeURIComponent(profile.token)}`);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => { status="LISTENING"; body="Listening for the interviewer’s question…"; void show(); renderPhone("Connected securely"); void bridge.audioControl(true, AudioInputSource.Glasses); };
    ws.onmessage = async e => {
      const m = parseMessage(String(e.data));
      if (m.type === "state") { status=m.state.toUpperCase(); if(m.transcript) body=`Q · ${m.transcript}`; }
      else if (m.type === "answer.delta") {
        if(m.first) answer=""; answer += m.text; body=answer; status="ANSWERING";
        const displayStart=performance.now(); await show();
        ws?.send(JSON.stringify({type:"display.ack",answer_id:m.answer_id,seq:m.seq,display_call_ms:performance.now()-displayStart}));
        renderPhone(); return;
      }
      else if (m.type === "answer.done") { body=m.text; status=`READY · ${Math.round(m.metrics.total_ms ?? 0)}ms`; }
      else if (m.type === "error") { status="ERROR"; body=m.message; }
      await show(); renderPhone();
    };
    ws.onclose = () => { void bridge.audioControl(false, AudioInputSource.Glasses); status="RECONNECTING"; void show(); reconnect=setTimeout(connect,1500); };
  }
  bridge.onEvenHubEvent(e => {
    const pcm = e.audioEvent?.audioPcm;
    if (pcm && pcm.length && ws?.readyState === WebSocket.OPEN) ws.send(pcm);
    const eventType = e.sysEvent?.eventType;
    if (eventType === OsEventTypeList.SYSTEM_EXIT_EVENT || eventType === OsEventTypeList.ABNORMAL_EXIT_EVENT) { clearTimeout(reconnect); ws?.close(); }
  });
  renderPhone(); if(profile) connect();
}

async function loadProfile(bridge: Awaited<ReturnType<typeof waitForEvenAppBridge>>): Promise<Profile|null> {
  try { const raw=await bridge.getLocalStorage(STORAGE); return raw ? JSON.parse(raw) : null; } catch { return null; }
}
function escapeHtml(v:string){return v.replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]!));}
void boot();
