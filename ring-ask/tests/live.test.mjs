import test from 'node:test';
import assert from 'node:assert/strict';
import {LiveQuestion,liveEndpoint} from '../src/live.mjs';

class Socket {
  readyState=0; sent=[];
  open(){this.readyState=1;this.onopen();}
  receive(event){this.onmessage({data:JSON.stringify(event)});}
  send(value){this.sent.push(value);}
  close(){this.readyState=3;this.onclose?.();}
}

test('live endpoint keeps the configured host and uses a secure websocket',()=>{
 assert.equal(liveEndpoint('https://example.test/ring/'),'wss://example.test/ws/ring-live');
});

test('live question authenticates, streams PCM, and completes with server events',async()=>{
 const socket=new Socket(),events=[];
 const live=new LiveQuestion(()=>socket,1000);
 const starting=live.start('https://example.test','secret',event=>events.push(event));
 socket.open();assert.deepEqual(JSON.parse(socket.sent[0]),{type:'auth',token:'secret'});
 socket.receive({type:'ready',model:'gpt-live-1'});assert.equal(await starting,true);
 live.audio(new Uint8Array([1,2,3,4]));assert.deepEqual([...socket.sent[1]],[1,2,3,4]);
 const finishing=live.finish('Be brief',event=>events.push(event));
 assert.deepEqual(JSON.parse(socket.sent[2]),{type:'finish',instructions:'Be brief'});
 socket.receive({type:'transcript',text:'What is Kafka?'});socket.receive({type:'delta',text:'Kafka is'});socket.receive({type:'done'});
 assert.equal(await finishing,true);assert.deepEqual(events.map(event=>event.type),['transcript','delta','done']);
});

test('live setup failure returns false so batch transcription can take over',async()=>{
 const socket=new Socket(),live=new LiveQuestion(()=>socket,1000);
 const starting=live.start('https://example.test','secret');socket.open();socket.receive({type:'error',text:'Unavailable'});
 assert.equal(await starting,false);assert.equal(live.ready,false);
});

test('live processing failure rejects finish so recorded audio can fall back',async()=>{
 const socket=new Socket(),live=new LiveQuestion(()=>socket,1000);
 const starting=live.start('https://example.test','secret');socket.open();socket.receive({type:'ready'});await starting;
 const finishing=live.finish('',()=>{});socket.receive({type:'error',text:'Live failed'});
 await assert.rejects(finishing,/Live failed/);assert.equal(live.ready,false);
});
