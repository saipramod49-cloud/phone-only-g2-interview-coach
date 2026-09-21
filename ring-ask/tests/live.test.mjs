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
 socket.receive({type:'ready',model:'gpt-live-1'});assert.deepEqual(JSON.parse(socket.sent[1]),{type:'listen'});
 socket.receive({type:'capture',active:true});assert.equal(await starting,true);
 live.audio(new Uint8Array([1,2,3,4]));assert.deepEqual([...socket.sent[2]],[1,2,3,4]);
 const finishing=live.finish('Be brief',event=>events.push(event));
 assert.deepEqual(JSON.parse(socket.sent[3]),{type:'coach.instructions',text:'Be brief'});assert.deepEqual(JSON.parse(socket.sent[4]),{type:'finish'});
 socket.receive({type:'transcript.final',text:'What is Kafka?'});socket.receive({type:'answer.delta',text:'Kafka is'});socket.receive({type:'answer.done',model:'test'});
 assert.equal(await finishing,true);assert.deepEqual(events.map(event=>event.type),['transcript','delta','done']);
});

test('live setup failure returns false so batch transcription can take over',async()=>{
 const socket=new Socket(),live=new LiveQuestion(()=>socket,1000);
 const starting=live.start('https://example.test','secret');socket.open();socket.receive({type:'error',message:'Unavailable'});
 assert.equal(await starting,false);assert.equal(live.ready,false);
});

test('live processing failure rejects finish so recorded audio can fall back',async()=>{
 const socket=new Socket(),live=new LiveQuestion(()=>socket,1000);
 const starting=live.start('https://example.test','secret');socket.open();socket.receive({type:'ready'});socket.receive({type:'capture',active:true});await starting;
 const finishing=live.finish('',()=>{});socket.receive({type:'error',message:'Live failed'});
 await assert.rejects(finishing,/Live failed/);assert.equal(live.ready,false);
});

test('semantic answer completed before ring release is buffered and replayed',async()=>{
 const socket=new Socket(),live=new LiveQuestion(()=>socket,1000),events=[];
 const starting=live.start('https://example.test','secret');socket.open();socket.receive({type:'ready'});socket.receive({type:'capture',active:true});await starting;
 socket.receive({type:'transcript.final',text:'Explain BigQuery.'});socket.receive({type:'answer.start'});socket.receive({type:'answer.delta',text:'BigQuery is'});
 socket.receive({type:'answer.done',model:'test'});
 assert.equal(await live.finish('',event=>events.push(event)),true);
 assert.deepEqual(events.map(event=>event.type),['transcript','delta','done']);
 assert.equal(socket.sent.filter(value=>typeof value==='string'&&JSON.parse(value).type==='finish').length,0);
});

test('continuous mode keeps one socket open and receives multiple answers',async()=>{
 const socket=new Socket(),events=[];
 const live=new LiveQuestion(()=>socket,1000);
 const starting=live.start('https://example.test','secret',event=>events.push(event),{continuous:true});
 socket.open();socket.receive({type:'ready'});
 assert.deepEqual(JSON.parse(socket.sent[1]),{type:'conversation.mode',active:true});
 assert.deepEqual(JSON.parse(socket.sent[2]),{type:'listen'});
 socket.receive({type:'capture',active:true});assert.equal(await starting,true);
 for(const [question,answer] of [['What is Kafka?','Kafka is a log.'],['Why partition it?','Partitions scale throughput.']]){
  socket.receive({type:'transcript.final',text:question});
  socket.receive({type:'answer.start',question});
  socket.receive({type:'answer.delta',text:answer});
  socket.receive({type:'answer.done',model:'test'});
  socket.receive({type:'capture',active:true});
 }
 assert.equal(socket.readyState,1);
 assert.equal(events.filter(event=>event.type==='done').length,2);
 live.cancel();
 assert.ok(socket.sent.some(value=>typeof value==='string'&&JSON.parse(value).type==='conversation.mode'));
});
