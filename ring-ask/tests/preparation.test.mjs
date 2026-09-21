import test from 'node:test';
import assert from 'node:assert/strict';
import {InterviewPackClient,activeProfile,targetStack} from '../src/preparation.mjs';

test('target stack follows the JD rather than a generic data-engineering default',()=>{
  assert.equal(targetStack('Azure Data Factory, ADLS Gen2 and Synapse'), 'Azure');
  assert.equal(targetStack('Build BigQuery pipelines with Composer and GCS'), 'GCP');
  assert.equal(targetStack('AWS Glue, S3 and Redshift'), 'AWS');
  assert.equal(targetStack('Senior data engineer with SQL'), 'JD-driven');
});

test('active interview pack is selected from saved state',()=>{
  const state={profiles:[{id:'old',active:0},{id:'azure',active:1}]};
  assert.equal(activeProfile(state).id,'azure');
  assert.equal(activeProfile({profiles:[]}),null);
});

test('interview pack client authenticates profile and upload requests',async()=>{
  const calls=[];
  const fetcher=async(url,options={})=>{calls.push({url,options});return {ok:true,json:async()=>({ok:true})};};
  const client=new InterviewPackClient('https://example.test/','secret',fetcher);
  await client.state();
  await client.create('Azure role','Use ADF and ADLS');
  await client.activate('profile 1');
  await client.addNotes('profile 1','Reconciliation and replay notes');
  assert.equal(calls.length,4);
  assert.equal(calls[0].url,'https://example.test/api/state');
  assert.equal(calls[0].options.headers['X-App-Token'],'secret');
  assert.equal(calls[1].options.body.get('job_description'),'Use ADF and ADLS');
  assert.match(calls[2].url,/profile%201\/activate$/);
  assert.equal(calls[3].options.body.get('kind'),'prep notes');
  assert.equal(await calls[3].options.body.get('file').text(),'Reconciliation and replay notes');
});
