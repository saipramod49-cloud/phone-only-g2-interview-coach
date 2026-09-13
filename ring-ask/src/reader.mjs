export const defaults = {rows:4,words:7,width:440,x:50,y:50,step:1,wpm:120,style:'natural',navigation:'line',emphasis:'on'};
const clamp=(n,lo,hi,fallback)=>Number.isFinite(Number(n))?Math.max(lo,Math.min(hi,Math.round(Number(n)))):fallback;
export function settings(raw={}) {
  return {rows:clamp(raw.rows,2,7,4),words:clamp(raw.words,1,12,7),width:clamp(raw.width,360,564,440),
    x:clamp(raw.x,0,100,50),y:clamp(raw.y,0,100,50),step:clamp(raw.step,1,3,1),wpm:clamp(raw.wpm,60,240,120),
    navigation:raw.navigation==='page'?'page':'line',emphasis:raw.emphasis==='off'?'off':'on',
    style:['brief','natural','detailed'].includes(raw.style)?raw.style:'natural'};
}
export function layout(raw) {
  const s=settings(raw),height=38+s.rows*30;
  const width=s.width,x=Math.round((576-width)*s.x/100);
  return {width,height,x,y:Math.round((288-height)*s.y/100)};
}
// Approximate the proportional firmware font rather than charging every glyph 14px.
// Leave extra room for firmware differences; uppercase emphasis is measured too.
export function textWidth(text) {
  return Array.from(text).reduce((sum,char)=>sum+(
    /[ilI1.,'`:;!|]/.test(char)?5:
    /\s/.test(char)?6:
    /[mwMW@%]/.test(char)?19:
    /[A-Z0-9]/.test(char)?13:
    /[a-z]/.test(char)?11:20),0);
}
export function lines(text,raw) {
  const s=settings(raw),budget=layout(s).width-24,out=[];
  const fits=value=>textWidth(emphasize(value,s))<=budget;
  for(const paragraph of text.replace(/\r/g,'').split('\n')) {
    if(!paragraph.trim()) {if(out.length && out.at(-1)!=='')out.push('');continue;}
    let line='',count=0;
    for(const word of paragraph.trim().split(/\s+/)) {
      if(line && (count>=s.words || !fits(line+' '+word))){out.push(line);line='';count=0;}
      let fragment='';
      for(const char of word){
        if(fragment&&!fits(fragment+char)){out.push(fragment);fragment='';}
        fragment+=char;
      }
      if(fragment){line+=(line?' ':'')+fragment;count++;}
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

export function readingSettings(raw={}){
 return {rows:clamp(raw.rows,1,10,9),words:clamp(raw.words,1,10,10),font:['native','18','22','26','30'].includes(String(raw.font))?String(raw.font):'native'};
}
export function fullPage(text,index=0,raw={}){
 const pref=readingSettings(raw);
 const all=lines(text,{width:564,words:pref.words,emphasis:'off'}),count=Math.max(1,Math.ceil(all.length/pref.rows));
 const page=Math.max(0,Math.min(count-1,index));
 return {text:all.slice(page*pref.rows,page*pref.rows+pref.rows).map(line=>line===''?'----------------------------------------':line).join('\n'),page,count,rows:pref.rows};
}
export function measuredPage(text,index,raw,measure){
 const pref=readingSettings(raw),size=Number(pref.font),rows=Math.min(pref.rows,Math.floor(280/(size+4))),all=[];
 for(const paragraph of text.split('\n')){
  if(!paragraph.trim()){if(all.length&&all.at(-1)!=='')all.push('');continue;}
  let line='',words=0;
  for(const word of paragraph.trim().split(/\s+/)){
   if(line&&(words>=pref.words||measure(line+' '+word)>560)){all.push(line);line='';words=0;}
   let part='';for(const char of word){if(part&&measure(part+char)>560){all.push(part);part='';}part+=char;}
   line+=(line?' ':'')+part;words++;
  }
  if(line)all.push(line);
 }
 if(!all.length)all.push('');
 const count=Math.ceil(all.length/rows),page=Math.max(0,Math.min(count-1,index));
 return {text:all.slice(page*rows,page*rows+rows).map(line=>line===''?'---':line).join('\n'),page,count,rows};
}
