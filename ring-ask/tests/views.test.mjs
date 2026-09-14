import test from 'node:test';
import assert from 'node:assert/strict';
import {answerVariants,pairedViews} from '../src/views.mjs';

test('splits flow, spoken and keyword views in display order',()=>{
 const value=answerVariants('FLOW:\nDISCOVER — choose a use case\n-> PILOT — verify value\nSPOKEN:\nI would start small.\n\nThen I would measure the result.\nKEYWORDS:\nDISCOVER · PILOT · MEASURE');
 assert.match(value.flow,/DISCOVER/);assert.match(value.spoken,/start small/);assert.equal(value.keywords,'DISCOVER · PILOT · MEASURE');
});

test('streams the flow before later views arrive',()=>{
 const value=answerVariants('FLOW:\nASSESS — inspect the data');
 assert.equal(value.flow,'ASSESS — inspect the data');assert.equal(value.spoken,'');assert.equal(value.keywords,'');
});

test("spoken streams before flow arrives",()=>{const value=answerVariants("SPOKEN:\nI would start with the requirements.");assert.equal(value.spoken,"I would start with the requirements.");assert.equal(value.flow,"");});


test('pairs each flow step with its matching explanation',()=>{
 const value=answerVariants('SPOKEN:\nStart small.\nFLOW:\nDISCOVER — choose one use case\n-> PILOT — test safely\nEXPLAIN:\nDISCOVER — This limits risk while confirming the required data.\nPILOT — Measure quality, access, latency, and cost.\nKEYWORDS:\nDISCOVER · PILOT');
 const pairs=pairedViews(value.flow,value.explain);
 assert.deepEqual(pairs,[
  {flow:'DISCOVER — choose one use case',explanation:'This limits risk while confirming the required data.'},
  {flow:'PILOT — test safely',explanation:'Measure quality, access, latency, and cost.'}
 ]);
});
