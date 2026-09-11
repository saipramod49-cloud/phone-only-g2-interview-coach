import {it,expect} from 'vitest';
import {appendInstruction} from './coach-instructions';
it('keeps suggestions ordered so later changes can override earlier defaults',()=>{expect(appendInstruction('Highlight three keywords.','  Stop highlighting. ')).toBe('Highlight three keywords.\nStop highlighting.');});
it('rejects empty and oversized instruction updates',()=>{expect(()=>appendInstruction('',' ')).toThrow();expect(()=>appendInstruction('x'.repeat(3999),'y')).toThrow();expect(appendInstruction('','x'.repeat(4000))).toHaveLength(4000);});
