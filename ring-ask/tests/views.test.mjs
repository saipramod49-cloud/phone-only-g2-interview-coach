import test from 'node:test';
import assert from 'node:assert/strict';
import {answerVariants} from '../src/views.mjs';

test('splits flow, spoken and keyword views in display order',()=>{
 const value=answerVariants('FLOW:\nDISCOVER — choose a use case\n-> PILOT — verify value\nSPOKEN:\nI would start small.\n\nThen I would measure the result.\nKEYWORDS:\nDISCOVER · PILOT · MEASURE');
 assert.match(value.flow,/DISCOVER/);assert.match(value.spoken,/start small/);assert.equal(value.keywords,'DISCOVER · PILOT · MEASURE');
});

test('streams the flow before later views arrive',()=>{
 const value=answerVariants('FLOW:\nASSESS — inspect the data');
 assert.equal(value.flow,'ASSESS — inspect the data');assert.equal(value.spoken,'');assert.equal(value.keywords,'');
});
