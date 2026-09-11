export type Speaker='candidate'|'interviewer'|'unknown';
export class SpeakerTracker {
 private recent: {role:Speaker;ms:number}[]=[];
 role:Speaker='unknown';
 update(pcm:Uint8Array,raw:string,override:string):Speaker {
  if(override==='candidate'||override==='interviewer'){this.role=override;return this.role;}
  const view=new DataView(pcm.buffer,pcm.byteOffset,pcm.byteLength);let energy=0;
  for(let i=0;i+1<pcm.length;i+=2){const sample=view.getInt16(i,true)/32768;energy+=sample*sample;}
  const speech=Math.sqrt(energy/Math.max(1,pcm.length/2))>0.008;
  const role:Speaker=speech?(raw==='self'?'candidate':raw==='other'?'interviewer':'unknown'):'unknown';
  this.recent.push({role,ms:pcm.length/32});
  let duration=this.recent.reduce((sum,item)=>sum+item.ms,0);
  while(this.recent.length>1&&duration-this.recent[0].ms>=300){duration-=this.recent.shift()!.ms;}
  const candidate=this.recent.filter(x=>x.role==='candidate').reduce((a,x)=>a+x.ms,0);
  const interviewer=this.recent.filter(x=>x.role==='interviewer').reduce((a,x)=>a+x.ms,0);
  this.role=duration>=200&&candidate/duration>=0.8?'candidate':duration>=200&&interviewer/duration>=0.8?'interviewer':'unknown';
  return this.role;
 }
 reset(){this.recent=[];this.role='unknown';}
}
export function manualRole(raw:string){return raw==='candidate'||raw==='interviewer'?raw:'unknown';}
export function pageForQuote(pages:string[],quote:string):number|null {
 const compact=(s:string)=>s.toLocaleLowerCase().replace(/\s+/g,' ').trim();
 const needle=compact(quote);if(needle.length<8)return null;
 const joined=pages.map(compact).join(' ');const index=joined.indexOf(needle);
 if(index<0||joined.indexOf(needle,index+1)>=0)return null;
 let end=0;for(let page=0;page<pages.length;page++){end+=compact(pages[page]).length+1;if(index+needle.length<=end)return page;}
 return null;
}
