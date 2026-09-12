import test from 'node:test';
import assert from 'node:assert/strict';
import {settings,layout,lines,frame,deadline} from '../src/reader.mjs';
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
