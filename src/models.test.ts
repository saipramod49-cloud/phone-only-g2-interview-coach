import {it,expect} from 'vitest';
import {validModelId,reasoningChoices,formatTiming} from './models';
it('accepts exact snapshot and fine-tuned IDs without accepting endpoints or HTML',()=>{expect(validModelId('ft:gpt-4.1:org:coach:id')).toBe(true);expect(validModelId('https://api.openai.com/v1/responses')).toBe(false);expect(validModelId('<script>')).toBe(false);expect(validModelId('')).toBe(false);});
it('offers reasoning controls supported by known presets',()=>{expect(reasoningChoices('gpt-6-astra')).not.toContain('none');expect(reasoningChoices('gpt-5.6-sol')).toContain('none');expect(reasoningChoices('gpt-4.1')).toEqual(['auto','default']);expect(reasoningChoices('custom-model')).toContain('high');});
it('labels first text and completed timing without inventing an unmeasured value',()=>{expect(formatTiming(null)).toContain('waiting');expect(formatTiming(0,1500)).toBe('First text: 0.00 s · Complete: 1.50 s');});
