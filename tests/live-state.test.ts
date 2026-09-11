import {describe,it,expect} from 'vitest';
import {LiveState} from '../src/live-state';
describe('live answer lifecycle',()=>{
 it('keeps the answer across pause, listening, errors and a pending question',()=>{
  const s=new LiveState();s.apply({type:'answer.start',answer_id:'1',question:'CDC?'});s.apply({type:'answer.delta',answer_id:'1',text:'Use CDC.'});
  for(const type of ['capture','ready','error','state'])s.apply({type});
  s.apply({type:'answer.start',answer_id:'2',question:'Why?'});expect(s.answer).toBe('Use CDC.');
  s.apply({type:'answer.delta',answer_id:'1',text:'stale'});expect(s.answer).toBe('Use CDC.');
  s.apply({type:'answer.delta',answer_id:'2',text:'Lower latency.'});expect(s.answer).toBe('Lower latency.');
 });
 it('paginates without losing words and clamps page navigation',()=>{
  const s=new LiveState();s.answer=Array.from({length:150},(_,i)=>`word${i}`).join(' ');
  expect(s.pages().join(' ').replace(/\s+/g,' ')).toBe(s.answer);
  s.page=999;s.frame();expect(s.page).toBe(s.pages().length-1);
  s.page=-1;s.frame();expect(s.page).toBe(0);
 });
});
