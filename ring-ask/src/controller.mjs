export const MAX_BYTES = 16000 * 2 * 90;
export function pages(text, columns = 40, rows = 6) {
  const lines = [];
  for (const paragraph of text.split('\n')) {
    let line = '';
    for (const word of paragraph.split(/\s+/).filter(Boolean)) {
      if (line && line.length + word.length + 1 > columns) { lines.push(line); line = ''; }
      let rest = word;
      while (rest.length > columns) { if (line) { lines.push(line); line = ''; } lines.push(rest.slice(0, columns)); rest = rest.slice(columns); }
      line += (line ? ' ' : '') + rest;
    }
    lines.push(line);
  }
  const result = [];
  for (let i = 0; i < lines.length; i += rows) result.push(lines.slice(i, i + rows).join('\n'));
  return result.length ? result : [''];
}
export function gesture(event) {
  if (event.sysEvent?.eventType != null) return event.sysEvent.eventType;
  const input = event.textEvent ?? event.listEvent;
  return input ? input.eventType ?? 0 : null;
}
export class Recorder {
  constructor(mic, change, submit) {
    this.mic=mic; this.change=change; this.submit=submit; this.state='ready'; this.mode='tap'; this.chunks=[]; this.bytes=0; this.held=false; this.queue=Promise.resolve();
  }
  dispatch(type) {
    this.queue = this.queue.then(async () => {
      if ([5,6,7].includes(type)) return this.cancel();
      if ((type === 0 && this.mode === 'tap') || (type === 9 && this.mode === 'hold')) {
        if (this.state !== 'ready') return;
        this.held = type === 9;
        this.chunks = []; this.bytes = 0; this.state = 'starting'; this.change('Starting microphone…');
        try {
          if (!await this.mic(true)) throw new Error('Microphone unavailable. Check G2 connection and permission.');
          this.state = 'listening'; this.change('Listening');
          this.timer = setTimeout(() => { void this.dispatch(3); }, 90000);
        } catch (error) { await this.cancel(); this.change(error.message); }
      } else if (type === 3 || (type === 10 && this.held)) {
        if (this.state !== 'listening') return;
        this.held = false; clearTimeout(this.timer); this.state = 'stopping'; this.change('Finishing question…');
        try {
          if (!await this.mic(false)) throw new Error('Could not stop microphone. Reopen the plugin.');
          const pcm = new Uint8Array(this.bytes); let offset = 0;
          for (const chunk of this.chunks) { pcm.set(chunk, offset); offset += chunk.length; }
          this.chunks = []; this.bytes = 0;
          if (pcm.length < 6400) throw new Error('No question captured. Wait for Listening, then speak.');
          this.state = 'busy'; this.change('Transcribing…');
          // Do not hold the gesture queue while the network runs: cancellation must remain responsive.
          const job = ++this.job;
          Promise.resolve(this.submit(pcm)).catch(error => { if (job === this.job) this.change(error.message); })
            .finally(() => { if (job === this.job) { this.state = 'ready'; this.change(null); } });
        } catch (error) { await this.cancel(); this.change(error.message); }
      }
    }).catch(error => { this.state = 'ready'; this.change(error.message); });
    return this.queue;
  }
  job = 0;
  audio(chunk) {
    if (!['starting','listening','stopping'].includes(this.state)) return;
    const take = Math.min(chunk.length, MAX_BYTES - this.bytes);
    if (take > 0) { this.chunks.push(chunk.slice(0,take)); this.bytes += take; }
    if (this.bytes >= MAX_BYTES && this.state === 'listening') void this.dispatch(3);
  }
  async cancel() {
    ++this.job; clearTimeout(this.timer); this.held = false;
    await this.mic(false).catch(() => false);
    this.chunks = []; this.bytes = 0; this.state = 'ready'; this.change('Ready');
  }
}
