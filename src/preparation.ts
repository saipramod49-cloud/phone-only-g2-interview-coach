type Profile={id:string;name:string;active:number;documents:{id:string;name:string;kind:string}[]};
export function mountPreparation(host:string,token:()=>string){
 const root=document.querySelector<HTMLElement>('#preparation')!;
 root.innerHTML=`<summary>Resume & preparation</summary>
 <p>Upload your resume and notes for personalized answers. Files stay on your server; relevant excerpts are sent to OpenAI when answering. Scanned PDFs need readable text.</p>
 <button id="load-prep">Load profiles</button><label>Active profile<select id="profiles"></select></label>
 <label>New profile name<input id="profile-name" maxlength="120" placeholder="GCP Data Engineer"></label>
 <label>Job description<textarea id="job-description" maxlength="30000"></textarea></label><button id="create-profile">Create and select profile</button>
 <label>Document type<select id="doc-kind"><option value="resume">Resume</option><option value="notes">Prep notes</option><option value="core_profile">Core profile — always included</option></select></label>
 <p>Core profile: one short fact sheet, up to 4,000 characters, included with every answer. Uploading a new core replaces the previous core for this profile. Longer study material belongs in Prep notes.</p>
 <label>File (PDF, DOCX, TXT, MD, CSV; up to 8 MB)<input id="prep-file" type="file" accept=".pdf,.docx,.txt,.md,.csv"></label><button id="upload-prep">Upload file</button>
 <label>Or paste preparation notes<textarea id="prep-notes" maxlength="60000"></textarea></label><button id="save-notes">Save pasted notes</button>
 <p id="prep-status" role="status"></p><ul id="documents"></ul>`;
 const $=<T extends HTMLElement=HTMLElement>(s:string)=>root.querySelector<T>(s)!;
 const select=$<HTMLSelectElement>('#profiles');let profiles:Profile[]=[];let working=false;
 async function api(path:string,method='GET',body?:FormData){
  const key=token();if(!key)throw new Error('Enter your app access token first.');
  const response=await fetch(`https://${host}${path}`,{method,headers:{'X-App-Token':key},body,signal:AbortSignal.timeout(60000)});
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:`Request failed (${response.status})`);return data;
 }
 async function run(work:()=>Promise<void>){if(working)return;working=true;root.querySelectorAll('button,select').forEach(e=>e.setAttribute('disabled',''));$('#prep-status').textContent='Working…';try{await work();$('#prep-status').textContent='Saved / loaded. This profile will be used for subsequent answers.';}catch(e){$('#prep-status').textContent=e instanceof Error?e.message:'Request failed';}finally{working=false;root.querySelectorAll('button,select').forEach(e=>e.removeAttribute('disabled'));}}
 function list(){const ul=$('#documents');ul.replaceChildren();for(const doc of profiles.find(p=>p.id===select.value)?.documents??[]){const li=document.createElement('li');const text=document.createElement('span');text.textContent=`${doc.kind}: ${doc.name}`;const button=document.createElement('button');button.textContent='Remove';button.onclick=()=>{if(confirm(`Remove ${doc.name}?`))void run(async()=>{await api(`/api/documents/${encodeURIComponent(doc.id)}`,'DELETE');await load();});};li.append(text,button);ul.append(li);}}
 async function load(){const data=await api('/api/state');profiles=data.profiles;select.replaceChildren();for(const p of profiles){const option=document.createElement('option');option.value=p.id;option.textContent=p.name;option.selected=Boolean(p.active);select.append(option);}list();}
 function pid(){if(!select.value)throw new Error('Load or create a profile first.');return encodeURIComponent(select.value);}
 async function upload(file:File,kind:string){if(file.size>8*1024*1024)throw new Error('File exceeds 8 MB.');const form=new FormData();form.set('kind',kind);form.set('file',file);await api(`/api/profiles/${pid()}/documents`,'POST',form);await load();}
 $('#load-prep').onclick=()=>void run(load);
 select.onchange=()=>void run(async()=>{await api(`/api/profiles/${pid()}/activate`,'POST');await load();});
 $('#create-profile').onclick=()=>void run(async()=>{const name=$<HTMLInputElement>('#profile-name').value.trim();if(!name)throw new Error('Enter a profile name.');const form=new FormData();form.set('name',name);form.set('job_description',$<HTMLTextAreaElement>('#job-description').value);await api('/api/profiles','POST',form);await load();});
 $('#upload-prep').onclick=()=>void run(async()=>{const file=$<HTMLInputElement>('#prep-file').files?.[0];if(!file)throw new Error('Choose a file first.');await upload(file,$<HTMLSelectElement>('#doc-kind').value);$<HTMLInputElement>('#prep-file').value='';});
 $('#save-notes').onclick=()=>void run(async()=>{const text=$<HTMLTextAreaElement>('#prep-notes').value.trim();if(!text)throw new Error('Paste notes first.');await upload(new File([text],'Preparation notes.txt',{type:'text/plain'}),'notes');$<HTMLTextAreaElement>('#prep-notes').value='';});
}
