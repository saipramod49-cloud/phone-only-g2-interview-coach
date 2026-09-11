export function appendInstruction(current:string,next:string){const text=next.trim();if(!text)throw new Error('Enter a suggestion first.');const combined=[current,text].filter(Boolean).join('\n');if(combined.length>4000)throw new Error('Instructions exceed 4,000 characters. Clear them and add a shorter combined instruction.');return combined;}
export function mountCoachInstructions(send:(text:string)=>boolean,changed:()=>void=()=>{}){
 const root=document.querySelector<HTMLElement>('#coach-instructions')!;
 root.innerHTML=`<details><summary>Talk to your coach</summary>
 <p>Type a suggestion or use your phone keyboard's dictation. Suggestions affect future answers; they are not interview questions.</p>
 <label>Your suggestion<textarea id="coach-draft" maxlength="2000" placeholder="From the next answer, highlight 3 keywords and use a short example from my uploaded project when relevant."></textarea></label>
 <button id="coach-apply">Apply to next answers</button><button id="coach-clear">Clear suggestions</button>
 <p id="coach-status" role="status">Using default answer style.</p>
 <label>Active suggestions<textarea id="coach-active" readonly></textarea></label>
 <p>Latest conflicting suggestion wins. Suggestions are saved with your selected profile on this phone. Clear restores defaults. Language uses the answer-language selector. Highlighting uses UPPERCASE on the lens.</p></details>`;
 const $=<T extends HTMLElement=HTMLElement>(s:string)=>root.querySelector<T>(s)!;
 let active='';
 function sync(){changed();$('#coach-status').textContent=send(active)?'Sending suggestions…':'Saved for this page. Start practice to apply.';}
 $('#coach-apply').onclick=()=>{try{active=appendInstruction(active,$<HTMLTextAreaElement>('#coach-draft').value);$<HTMLTextAreaElement>('#coach-active').value=active;$<HTMLTextAreaElement>('#coach-draft').value='';sync();}catch(e){$('#coach-status').textContent=e instanceof Error?e.message:'Could not apply suggestion';}};
 $('#coach-clear').onclick=()=>{active='';$<HTMLTextAreaElement>('#coach-active').value='';sync();};
 return {sync,read:()=>active,restore:(text:string)=>{active=typeof text==='string'?text.slice(0,4000):'';$<HTMLTextAreaElement>('#coach-active').value=active;},ack:(enabled:boolean)=>{$('#coach-status').textContent=enabled?'Applied. Your next answer or Retry will use these suggestions.':'Suggestions cleared. Default answer style restored.';}};
}
