import {describe,it,expect} from 'vitest';
import {RingMenu} from './ring-menu';
import {geometry,normalizeDisplay,defaultDisplay} from './display-settings';
import {LiveState} from './live-state';
describe('ring controls and readable display',()=>{
 it('opens actions without starting capture and selects retry',()=>{const menu=new RingMenu();expect(menu.tap()).toBeNull();menu.move(3);expect(menu.tap()).toBe('retry');expect(menu.open).toBe(false);});
 it('backs out of menu before allowing root exit',()=>{const menu=new RingMenu();menu.tap();expect(menu.back()).toBe(true);expect(menu.back()).toBe(false);});
 it('clamps corrupt preferences and keeps the window on canvas',()=>{const s=normalizeDisplay({words:99,lines:-3,width:999,horizontal:'right',vertical:'bottom'});const g=geometry(s);expect(s.words).toBe(8);expect(s.lines).toBe(2);expect(g.x+g.width).toBeLessThanOrEqual(576);expect(g.y+g.height).toBeLessThanOrEqual(288);expect(normalizeDisplay({words:NaN}).words).toBe(defaultDisplay.words);});
 it('wraps words and lines without dropping answer content',()=>{const s=new LiveState();s.wordsPerLine=2;s.linesPerPage=2;s.answer='one two three four five six seven eight nine ten';const pages=s.pages();expect(pages).toHaveLength(3);expect(pages.join(' ').replace(/\s+/g,' ')).toBe(s.answer);for(const page of pages){expect(page.split('\n').length).toBeLessThanOrEqual(2);for(const line of page.split('\n'))expect(line.split(' ').length).toBeLessThanOrEqual(2);}});
});
