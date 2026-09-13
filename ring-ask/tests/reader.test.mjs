import test from 'node:test';
import assert from 'node:assert/strict';
import {settings,layout,lines,frame,deadline,textWidth,emphasize} from '../src/reader.mjs';
test('reader obeys chosen line and word limits without losing text',()=>{
 const text='A useful answer explains the actual mechanism and gives a grounded example from the project. '.repeat(12).trim();
 const s=settings({rows:3,words:4,width:540});const all=lines(text,s);
 assert.equal(all.join(' ').replace(/\s+/g,' '),text.replace(/\s+/g,' '));
 assert.ok(all.every(line=>line.split(' ').length<=4));assert.equal(frame(text,2,s).text.split('\n').length,3);
});
test('one-line scroll preserves overlap and reaches the final word',()=>{
 const s=settings({rows:3,words:2}),text='one two three four five six seven eight nine ten eleven twelve';
 const first=frame(text,0,s),second=frame(text,1,s),last=frame(text,999,s);
 assert.equal(first.all[1],second.text.split('\n')[0]);assert.ok(last.text.endsWith('twelve'));assert.equal(last.start,last.last);
});
test('all display settings remain inside the physical canvas',()=>{
 for(const rows of [2,4,7,99])for(const width of [1,280,564,999])for(const x of [-100,0,50,100,999])for(const y of [0,50,100]){
 const box=layout({rows,width,x,y});assert.ok(box.x>=0&&box.y>=0&&box.x+box.width<=576&&box.y+box.height<=288);
 }
});
test('deadline releases a stuck bridge call',async()=>{
 await assert.rejects(deadline(new Promise(()=>{}),10,'stuck'),/stuck/);
 assert.equal(await deadline(Promise.resolve(true),10),true);
});

test('position changes never shrink the block or rewrap the answer',()=>{
 const text='I use Snowflake SQL to reconcile the final extracts before publication.';
 for(const width of [360,440,540,564]){
  const reference=lines(text,{width,x:0});
  for(const x of [0,25,50,75,100]){
   const box=layout({width,x});assert.equal(box.width,width);
   assert.deepEqual(lines(text,{width,x}),reference);
   assert.equal(box.x,Math.round((576-width)*x/100));
  }
 }
});
test('complete pages do not repeat the previous page at the end',()=>{
 const s=settings({rows:3,words:1,navigation:'page'}),text='one\ntwo\nthree\nfour\nfive\nsix\nseven';
 const pages=[0,3,6].map(offset=>frame(text,offset,s));
 assert.equal(pages.map(p=>p.text).join('\n'),lines(text,s).join('\n'));
 assert.equal(pages[2].text,'seven');assert.equal(frame(text,999,s).start,6);
});

test('numbered lens test stays on one line at minimum width',()=>{
 const text=Array.from({length:16},(_,i)=>`${i+1}. Read this complete line.`).join('\n');
 for(const x of [0,50,100])assert.equal(lines(text,{width:360,words:12,x}).length,16);
});
test('wide glyphs and capitalized keywords are counted before wrapping',()=>{
 const s=settings({width:360,words:12}),text='WWWWWWWWWWWWWWWWWWWWWWWW Snowflake reconciliation SQL BigQuery';
 assert.ok(textWidth('WWWW')>textWidth('iiii'));
 assert.ok(lines(text,s).every(line=>textWidth(emphasize(line,s))<=336));
 assert.equal(lines(text,s).join('').replace(/ /g,''),text.replace(/ /g,''));
});

test('full-screen pages retain the complete answer through the last page',async()=>{
 const {fullPage}=await import('../src/reader.mjs');
 const text='This answer explains a concrete engineering decision and its result. '.repeat(50).trim();
 const count=fullPage(text).count;
 const restored=Array.from({length:count},(_,i)=>fullPage(text,i).text).join(' ').replace(/\s+/g,' ');
 assert.equal(restored,text);assert.equal(fullPage(text,999).page,count-1);
 assert.ok(Array.from({length:count},(_,i)=>fullPage(text,i).text.split('\n').length).every(n=>n<=9));
});

test('new reading settings cap lines and words at ten',async()=>{
 const {readingSettings,fullPage,measuredPage}=await import('../src/reader.mjs');
 assert.deepEqual(readingSettings({rows:99,words:99,font:'bogus'}),{rows:10,words:10,font:'native'});
 const text='one two three four five six seven eight nine ten eleven twelve '.repeat(30).trim();
 for(const rows of [1,5,10])for(const words of [1,4,10]){
  const p=fullPage(text,0,{rows,words});assert.ok(p.text.split('\n').length<=rows);
  assert.ok(p.text.split('\n').every(line=>line.split(/\s+/).length<=words));
 }
 const large=measuredPage(text,0,{rows:10,words:10,font:'30'},x=>x.length*16);
 assert.equal(large.rows,8);assert.ok(large.text.split('\n').length<=8);
 const n=large.count;
 const reconstructed=Array.from({length:n},(_,i)=>measuredPage(text,i,{rows:10,words:10,font:'30'},x=>x.length*16).text).join(' ').replace(/\s+/g,' ');
 assert.equal(reconstructed,text);
});
