export const defaults = {rows:4,words:7,width:440,x:50,y:50,step:1,wpm:120,style:'natural',navigation:'line',emphasis:'on'};
const clamp=(n,lo,hi,fallback)=>Number.isFinite(Number(n))?Math.max(lo,Math.min(hi,Math.round(Number(n)))):fallback;
export function settings(raw={}) {
  return {rows:clamp(raw.rows,2,7,4),words:clamp(raw.words,2,12,7),width:clamp(raw.width,360,564,440),
    x:clamp(raw.x,0,100,50),y:clamp(raw.y,0,100,50),step:clamp(raw.step,1,3,1),wpm:clamp(raw.wpm,60,240,120),
    navigation:raw.navigation==='page'?'page':'line',emphasis:raw.emphasis==='off'?'off':'on',
    style:['brief','natural','detailed'].includes(raw.style)?raw.style:'natural'};
}
export function layout(raw) {
  const s=settings(raw),height=38+s.rows*30;
  const width=s.width,x=Math.round((576-width)*s.x/100);
  return {width,height,x,y:Math.round((288-height)*s.y/100)};
}
export function lines(text,raw) {
  const s=settings(raw),columns=Math.max(12,Math.floor((layout(s).width-12)/14)),out=[];
  for(const paragraph of text.replace(/\r/g,'').split('\n')) {
    if(!paragraph.trim()) {if(out.length && out.at(-1)!=='')out.push('');continue;}
    let line='',count=0;
    for(let word of paragraph.trim().split(/\s+/)) {
      if(line && (count>=s.words || line.length+word.length+1>columns)){out.push(line);line='';count=0;}
      while(word.length>columns){out.push(word.slice(0,columns));word=word.slice(columns);}
      if(word){line+=(line?' ':'')+word;count++;}
    }
    if(line)out.push(line);
  }
  return out.length?out:[''];
}
export function frame(text,offset,raw) {
  const s=settings(raw),all=lines(text,s),last=s.navigation==='page'?Math.floor((all.length-1)/s.rows)*s.rows:Math.max(0,all.length-s.rows),start=Math.max(0,Math.min(last,offset));
  return {all,start,last,text:all.slice(start,start+s.rows).join('\n'),end:Math.min(all.length,start+s.rows)};
}
export function readDelay(line,wpm) {return Math.max(700,(line.trim().split(/\s+/).filter(Boolean).length||2)*60000/wpm);}
export function deadline(promise,ms,message='Connection timed out') {
  let timer;
  return Promise.race([promise,new Promise((_,reject)=>timer=setTimeout(()=>reject(new Error(message)),ms))]).finally(()=>clearTimeout(timer));
}

export const keywordPattern=/\b(?:Snowflake|TIDAL|BigQuery|SQL|Python|PySpark|Kafka|Airflow|Composer|QFC|MERGE|CTEs?|reconciliation|backfill|\d+(?:\.\d+)?%)\b/gi;
export function emphasize(text,raw){return settings(raw).emphasis==='off'?text:text.replace(keywordPattern,word=>word.toUpperCase());}
