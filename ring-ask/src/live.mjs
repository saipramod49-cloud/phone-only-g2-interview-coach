export function liveEndpoint(backend) {
  const url = new URL(backend);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = '/ws/ring-live';
  url.search = '';
  url.hash = '';
  return url.toString();
}

export class LiveQuestion {
  constructor(socketFactory = url => new WebSocket(url), timeout = 25000) {
    this.socketFactory = socketFactory;
    this.timeout = timeout;
    this.socket = null;
    this.ready = false;
    this.handler = null;
    this.finishResolve = null;
    this.finishReject = null;
    this.pending = [];
    this.answerStarted = false;
    this.completed = false;
    this.continuous = false;
  }

  async start(backend, token, preview = _event => {}, options = {}) {
    this.cancel();
    this.handler = preview;
    this.continuous = options.continuous === true;
    this.pending = []; this.answerStarted = false; this.completed = false;
    let socket;
    try { socket = this.socketFactory(liveEndpoint(backend)); }
    catch { return false; }
    this.socket = socket;
    return new Promise(resolve => {
      let settled = false;
      const finish = value => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value);
      };
      const timer = setTimeout(() => { this.cancel(); finish(false); }, this.timeout);
      socket.onopen = () => socket.send(JSON.stringify({type:'auth', token}));
      socket.onmessage = message => {
        let event;
        try { event = JSON.parse(message.data); } catch { return; }
        if (event.type === 'ready') {
          if (this.continuous) socket.send(JSON.stringify({type:'conversation.mode', active:true}));
          socket.send(JSON.stringify({type:'listen'}));
          return;
        }
        if (event.type === 'capture' && event.active === true && !this.ready) {
          this.ready = true; finish(true); return;
        }
        if (event.type === 'answer.start') {
          this.answerStarted = true;
          if (this.continuous) this.handler?.(event);
          return;
        }
        const mapped = event.type === 'transcript.final'
          ? {type:'transcript', text:event.text || '', transcriptionMs:0, source:'gpt-live-1'}
          : event.type === 'answer.delta'
            ? {type:'delta', text:event.text || ''}
            : event.type === 'answer.done'
              ? {type:'done', model:event.model || 'GPT-Live backend', transport:'gpt-live-1'}
              : event.type === 'error'
                ? {type:'error', text:event.message || event.text || 'GPT Live question failed.'}
                : event;
        if (mapped.type === 'error') {
          if (this.continuous && event.recoverable !== false) {
            this.handler?.(mapped);
            return;
          }
          this.ready = false;
          const error = new Error(mapped.text);
          if (this.finishReject) this.finishReject(error);
          this.finishResolve = null; this.finishReject = null; finish(false);
          return;
        }
        if (!this.continuous && !this.finishResolve && ['transcript','delta','done'].includes(mapped.type)) this.pending.push(mapped);
        else this.handler?.(mapped);
        if (mapped.type === 'done') {
          this.completed = true;
          if (this.continuous) {
            this.answerStarted = false;
            this.completed = false;
            return;
          }
          if (this.finishResolve) {
            this.finishResolve(true); this.finishResolve = null; this.finishReject = null;
            try { socket.close(); } catch {}
          }
        }
      };
      socket.onerror = () => { this.ready = false; finish(false); this.finishReject?.(new Error('GPT Live connection failed.')); };
      socket.onclose = () => {
        const wasReady = this.ready; this.ready = false; finish(false);
        if (wasReady && this.finishReject) this.finishReject(new Error('GPT Live connection closed.'));
        this.finishResolve = null; this.finishReject = null;
      };
    });
  }

  audio(chunk) {
    if (this.ready && this.socket?.readyState === 1 && chunk?.length) this.socket.send(chunk.slice());
  }

  configure(instructions) {
    if (this.ready && this.socket?.readyState === 1) {
      this.socket.send(JSON.stringify({type:'coach.instructions', text:String(instructions || '')}));
    }
  }

  async finish(instructions, handler) {
    if (!this.ready || this.socket?.readyState !== 1) return false;
    this.handler = handler;
    const result = new Promise((resolve, reject) => { this.finishResolve = resolve; this.finishReject = reject; });
    for (const event of this.pending.splice(0)) this.handler(event);
    if (this.completed) {
      this.finishResolve?.(true); this.finishResolve = null; this.finishReject = null;
      try { this.socket.close(); } catch {}
      return result;
    }
    this.configure(instructions);
    if (!this.answerStarted) this.socket.send(JSON.stringify({type:'finish'}));
    return result;
  }

  cancel() {
    const socket = this.socket;
    this.socket = null; this.ready = false; this.handler = null;
    if (socket && socket.readyState < 2) {
      if (this.continuous && socket.readyState === 1) {
        try { socket.send(JSON.stringify({type:'conversation.mode', active:false})); } catch {}
      }
      try { socket.send(JSON.stringify({type:'cancel'})); } catch {}
      try { socket.close(); } catch {}
    }
    if (this.finishReject) this.finishReject(new Error('Question cancelled.'));
    this.finishResolve = null; this.finishReject = null;
    this.continuous = false;
  }
}
