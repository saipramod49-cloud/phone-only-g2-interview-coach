import presets from '../backend/app/model_catalog.json';
export const allEfforts=['none','minimal','low','medium','high','xhigh','max'];
export function validModelId(value:string){return /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(value);}
export function reasoningChoices(model:string){const entry=presets.find(p=>p.id===model);return ['auto','default',...(entry?.efforts??allEfforts)];}
export function formatTiming(first:number|null,total:number|null=null){
 const seconds=(n:number)=>`${(n/1000).toFixed(2)} s`;
 return `First text: ${first===null?'waiting…':seconds(first)}${total===null?'':` · Complete: ${seconds(total)}`}`;
}
export function mountModels(host:string,token:()=>string,changed:()=>void){
 const root=document.querySelector<HTMLElement>('#model-controls')!;
 root.innerHTML=`<label>Answer model<select id="answer-model"></select></label>
 <label id="custom-model-label" hidden>Custom OpenAI model ID<input id="custom-model" maxlength="200" placeholder="Paste an exact model ID"></label>
 <label>Reasoning effort<select id="answer-effort"></select></label>
 <button id="apply-model">Apply model settings</button><button id="load-models">Load models from my OpenAI account</button>
 <p id="model-status" role="status">Presets are not an access check. Load account models using the API key stored on Render.</p>
 <p>Model and reasoning changes apply to the next answer. Audio transcription stays unchanged. Higher reasoning can take longer and cost more. Listed account models may still require a different API.</p>
 <p id="model-timing" role="status">Response timing will appear here.</p>`;
 const $=<T extends HTMLElement=HTMLElement>(selector:string)=>root.querySelector<T>(selector)!;
 const select=$<HTMLSelectElement>('#answer-model'),custom=$<HTMLInputElement>('#custom-model'),effort=$<HTMLSelectElement>('#answer-effort');
 function option(parent:HTMLElement,value:string,label:string,disabled=false){const o=document.createElement('option');o.value=value;o.textContent=label;o.disabled=disabled;parent.append(o);}
 option(select,'','Server default');
 const group=document.createElement('optgroup');group.label='Presets — access not checked';select.append(group);
 for(const entry of presets)option(group,entry.id,entry.label);
 option(select,'__custom__','Custom model ID…');
 let accounts:HTMLOptGroupElement|undefined;
 function model(){return select.value==='__custom__'?custom.value.trim():select.value;}
 function updateEfforts(){const previous=effort.value;effort.replaceChildren();for(const value of reasoningChoices(model()))option(effort,value,value==='auto'?'Auto — preset recommendation':value==='default'?'API default (omit setting)':value);effort.value=Array.from(effort.options).some(o=>o.value===previous)?previous:'auto';}
 function read(){const id=model();if(select.value==='__custom__'&&!id)throw new Error('Enter a custom model ID before applying.');if(id&&!validModelId(id))throw new Error('Enter an exact model ID, not a URL.');return {model:id,reasoning_effort:effort.value};}
 function apply(){try{read();changed();$('#model-status').textContent='Selected for the next answer. The answer panel shows which model actually ran.';}catch(e){$('#model-status').textContent=e instanceof Error?e.message:'Invalid model settings';}}
 select.onchange=()=>{$('#custom-model-label').hidden=select.value!=='__custom__';effort.value='auto';updateEfforts();if(select.value!=='__custom__'||custom.value.trim())apply();};
 custom.onchange=()=>{updateEfforts();apply();};effort.onchange=apply;$('#apply-model').onclick=apply;
 $('#load-models').onclick=async()=>{
  const key=token();if(!key){$('#model-status').textContent='Enter your app access token first.';return;}
  const button=$<HTMLButtonElement>('#load-models');button.disabled=true;$('#model-status').textContent='Loading account models…';
  try{
   const response=await fetch(`https://${host}/api/models`,{headers:{'X-App-Token':key},signal:AbortSignal.timeout(25000)});
   const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:`Model list failed (${response.status}).`);
   const previous=select.value,previousModel=model();accounts?.remove();accounts=document.createElement('optgroup');accounts.label='Account models — endpoint compatibility unverified';select.append(accounts);
   const rows=(data.models as {id:string;selectable:boolean}[]).filter(row=>typeof row.id==='string'&&validModelId(row.id));
   const available=new Set(rows.map(row=>row.id));group.label='Presets';for(const o of group.querySelectorAll('option')){const entry=presets.find(p=>p.id===o.value)!;o.textContent=entry.label+(available.has(o.value)?' — listed':' — not listed');}
   for(const row of rows)if(!presets.some(p=>p.id===row.id))option(accounts,row.id,row.id+(row.selectable?'':' — different integration'),!row.selectable);
   select.value=previous;if(select.value!==previous){select.value="__custom__";custom.value=previousModel;$("#custom-model-label").hidden=false;}updateEfforts();
   $('#model-status').textContent=`Loaded ${rows.length} account model IDs. Specialized audio/image models are disabled. Text-model access and streaming support are checked when you request an answer.`;
  }catch(e){$('#model-status').textContent=e instanceof Error?e.message:'Could not load models. Presets and custom IDs remain available.';}finally{button.disabled=false;}
 };
 updateEfforts();return {read};
}
