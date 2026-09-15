export class AnswerHistory {
  constructor(saved = []) { this.entries = (Array.isArray(saved)?saved:[]).filter(e=>e && typeof e.answer==='string' && e.answer).slice(-30); this.index=this.entries.length-1; this.page=0; }
  get current(){return this.entries[this.index];}
  get isLatest(){return this.index===this.entries.length-1;}
  add(question,answer){this.entries.push({question,answer,time:Date.now()});this.entries=this.entries.slice(-30);this.index=this.entries.length-1;this.page=0;}
  move(direction){this.index=Math.max(0,Math.min(this.entries.length-1,this.index+direction));this.page=0;return this.current;}
  latest(){this.index=this.entries.length-1;this.page=0;}
  label(){return this.isLatest?'Current answer':`History ${this.index+1}/${this.entries.length}`;}
}

// SDK protobuf enum zero is sometimes omitted. Only input envelopes imply tap.
export function inputGestures(event){
 const values=[];
 for(const name of ['textEvent','listEvent'])if(event[name])values.push(Number(event[name].eventType??0));
 if(event.sysEvent?.eventType!=null)values.push(Number(event.sysEvent.eventType));
 return [...new Set(values.filter(v=>[0,1,2,3,9,10].includes(v)))];
}

// Wait for a single click to be disambiguated from the firmware's double-click.
export class RingInput {
 constructor(action,{set=setTimeout,clear=clearTimeout,now=Date.now,delay=450}={}){Object.assign(this,{action,set,clear,now,delay});this.timer=null;this.blockUntil=0;}
 reset(){if(this.timer!==null)this.clear(this.timer);this.timer=null;}
 feed(type){
  const now=this.now();
  if(type===0){
   if(now<this.blockUntil)return;
   if(this.timer!==null){this.reset();this.blockUntil=now+this.delay;this.action(3);return;}
   this.timer=this.set(()=>{this.timer=null;this.action(0);},this.delay);return;
  }
  if(type===3){this.reset();if(now<this.blockUntil)return;this.blockUntil=now+this.delay;this.action(3);return;}
  this.reset();
  if(type===9||type===10)this.blockUntil=now+this.delay;
  this.action(type);
 }
}

export function plain(text){return String(text||'').replace(/\*\*(.*?)\*\*/g,(_,s)=>s.toUpperCase()).replace(/`([^`\n]+)`/g,'$1');}
export function wrap(text,width,measure,words=Infinity){
 const output=[];let inCode=false;
 for(const raw of String(text||'').replace(/\r/g,'').split('\n')){
  if(/^\s*```/.test(raw)){inCode=!inCode;continue;}
  const line=inCode?raw.replace(/\t/g,'    '):plain(raw);
  if(!line.trim()){if(output.length&&output.at(-1)!=='')output.push('');continue;}
  if(inCode){
   // Never collapse indentation or split code on whitespace.
   let part='';for(const char of line){if(part&&measure(part+char)>width){output.push(part);part='';}part+=char;}output.push(part);continue;
  }
  let part='',count=0;
  for(const word of line.trim().split(/\s+/)){
   if(part&&(count>=words||measure(part+' '+word)>width)){output.push(part);part='';count=0;}
   for(const char of word){if(part&&measure(part+char)>width){output.push(part);part='';}part+=char;}
   count++;part+=' ';
  }
  if(part.trim())output.push(part.trimEnd());
 }
 return output.length?output:[''];
}
export function readingFrame(entry,index,pref,measure,layout='top',label='Current answer'){
 const width=pref.width||576,lh=pref.font==='native'?28:Number(pref.font)+4;
 const side=layout==='side';const qWidth=side?Math.round(width*.36):width;
 const aWidth=side?width-qWidth-6:width;
 const qRows=side?Math.max(1,Math.floor(240/lh)):2;
 const question=wrap(entry?.question||'Ready for your question',qWidth-12,measure);
 const q=question.slice(0,qRows);
 if(question.length>qRows){while(q.at(-1)&&measure(q.at(-1)+'…')>qWidth-12)q[q.length-1]=q.at(-1).slice(0,-1);q[q.length-1]+='…';}
 const qHeight=qRows*lh+8;
 const available=side?248:Math.max(lh+8,248-qHeight-6);
 const rows=Math.max(1,Math.min(pref.rows,Math.floor((available-8)/lh)));
 const aHeight=rows*lh+8;
 const blockHeight=side?Math.max(qHeight,aHeight):qHeight+6+aHeight;
 const y=36+Math.round(Math.max(0,248-blockHeight)*(pref.y??50)/100);
 const all=wrap(entry?.answer||'Choose a listening mode. Your answer will appear here.',aWidth-12,measure,pref.words==='auto'?Infinity:pref.words);
 const count=Math.max(1,Math.ceil(all.length/rows)),page=Math.max(0,Math.min(count-1,index));
 const x=Math.round((576-width)*(pref.x??50)/100);
 return {page,count,rows,label,header:`${label} · Page ${page+1}/${count}`,question:q.join('\n'),answer:all.slice(page*rows,(page+1)*rows).join('\n'),
  panels:[{x,y,width:qWidth,height:qHeight,text:q.join('\n')},{x:side?x+qWidth+6:x,y:side?y:y+qHeight+6,width:aWidth,height:aHeight,text:all.slice(page*rows,(page+1)*rows).join('\n')}]};
}
