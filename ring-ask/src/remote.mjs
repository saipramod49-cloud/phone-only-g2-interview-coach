export class RemoteCaptions {
  socket = null;
  active = false;

  start(backend, token, handler) {
    this.stop();
    return new Promise(resolve => {
      const url = new URL(backend);
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      url.pathname = '/ws/remote-captions/receive';
      url.search = '';
      const socket = new WebSocket(url);
      this.socket = socket;
      let settled = false;
      const finish = value => { if (!settled) { settled = true; resolve(value); } };
      const timer = setTimeout(() => { finish(false); socket.close(); }, 12000);
      socket.onopen = () => socket.send(JSON.stringify({type: 'auth', token}));
      socket.onmessage = event => {
        const message = JSON.parse(event.data);
        if (message.type === 'session') {
          clearTimeout(timer);
          this.active = true;
          finish(true);
        }
        handler(message);
      };
      socket.onerror = () => finish(false);
      socket.onclose = event => {
        clearTimeout(timer);
        const wasActive = this.active;
        this.active = false;
        if (!settled) finish(false);
        if (wasActive) handler({type: 'closed', text: event.reason || 'Remote caption session ended.'});
      };
    });
  }

  stop() {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({type: 'stop'}));
    this.active = false;
    this.socket?.close();
    this.socket = null;
  }
}
