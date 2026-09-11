import {it,expect} from 'vitest';
import {lensSafeFrame} from './language';
it('keeps readable Romanized Telugu unchanged',()=>{const s='ANSWER 1/1\n\nNenu munduga CDC data ni validate chestanu.';expect(lensSafeFrame(s)).toBe(s);});
it('does not send unreadable Telugu script to text containers',()=>{expect(lensSafeFrame('ANSWER\nతెలుగు')).toContain('Retry last answer');expect(lensSafeFrame('QUESTION\nతెలుగు')).toContain('question on phone');});
