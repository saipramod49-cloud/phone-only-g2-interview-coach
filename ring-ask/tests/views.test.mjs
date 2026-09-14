import test from 'node:test';
import assert from 'node:assert/strict';
import {answerVariants} from '../src/views.mjs';

test('splits spoken and flow views',()=>{
 const value=answerVariants('SPOKEN:\nI would start small.\nFLOW:\nDISCOVER — choose a use case\n-> PILOT — verify value');
 assert.equal(value.spoken,'I would start small.');
 assert.match(value.flow,/DISCOVER/);
});

test('streams spoken content before flow arrives',()=>{
 const value=answerVariants('SPOKEN:\nI would assess the data first.');
 assert.equal(value.spoken,'I would assess the data first.');assert.equal(value.flow,'');
});
