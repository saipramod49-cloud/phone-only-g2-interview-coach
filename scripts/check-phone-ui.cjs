const {JSDOM}=require(process.env.UI_TEST_NODE_MODULES?process.env.UI_TEST_NODE_MODULES+'/jsdom':'jsdom');
const fs=require('node:fs');const assert=require('node:assert/strict');
const root=require('node:path').resolve(__dirname,'../dist');
const html=fs.readFileSync(root+'/index.html','utf8').replace(/<script[^>]*src=[^>]*><\/script>/,'');
const code=fs.readFileSync(root+'/assets/'+fs.readdirSync(root+'/assets').find(n=>n.endsWith('.js')),'utf8');
const profiles=[{id:'profile-a',name:'Profile A',active:1,documents:[{id:'a',name:'A resume',kind:'resume'}]},{id:'profile-b',name:'Profile B',active:0,documents:[{id:'b',name:'B notes',kind:'notes'}]}];
const tick=()=>new Promise(r=>setTimeout(r,10));
function boot(saved={}){
 const dom=new JSDOM(html,{url:'https://coach.test',runScripts:'outside-only',pretendToBeVisual:true});const w=dom.window;const errors=[];
 w.addEventListener('error',e=>errors.push(e.error));w.HTMLElement.prototype.scrollIntoView=function(){};
 w.fetch=async url=>({ok:true,json:async()=>({profiles})});
 Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async()=>{}}});
 for(const [k,v] of Object.entries(saved))w.localStorage.setItem(k,v);
 w.eval(code);
 const $=s=>w.document.querySelector(s);
 const set=(s,v)=>{const el=$(s);if(el.type==='checkbox')el.checked=v;else el.value=v;el.dispatchEvent(new w.Event('change',{bubbles:true}));};
 return {dom,w,$,set,errors,saved:()=>Object.fromEntries(Array.from({length:w.localStorage.length},(_,i)=>{const key=w.localStorage.key(i);return [key,w.localStorage.getItem(key)]}))};
}
(async()=>{
 let a=boot();assert.equal(a.$('h1').textContent,'Practice Coach · 0.2.8');
 a.set('#token','test-app-token');await tick();assert.equal(a.$('#profiles').value,'profile-a');assert.match(a.$('#documents').textContent,/A resume/);
 a.set('#presentation','complete');a.set('#scroll-mode','timed');a.$('#coach-draft').value='Highlight three keywords.';a.$('#coach-apply').click();
 a.set('#profiles','profile-b');assert.equal(a.$('#coach-active').value,'');assert.equal(a.$('#presentation').value,'stream');assert.match(a.$('#documents').textContent,/B notes/);
 a.set('#answer-language','telugu_latin');a.set('#scroll-mode','voice');
 a.set('#profiles','profile-a');assert.equal(a.$('#presentation').value,'complete');assert.equal(a.$('#scroll-mode').value,'timed');assert.equal(a.$('#coach-active').value,'Highlight three keywords.');
 a.set('#profiles','profile-b');assert.equal(a.$('#answer-language').value,'telugu_latin');assert.equal(a.$('#scroll-mode').value,'voice');
 const saved=a.saved();assert.deepEqual(a.errors,[]);a.dom.window.close();
 a=boot(saved);await tick();assert.equal(a.$('#token').value,'test-app-token');assert.equal(a.$('#profiles').value,'profile-b');assert.equal(a.$('#scroll-mode').value,'voice');assert.match(a.$('#documents').textContent,/B notes/);
 a.$('#service-panel').open=true;a.$('#back-practice').click();assert.equal(a.$('#service-panel').open,false);assert.equal(a.$('#token').value,'test-app-token');
 a.set('#remember-token',false);const withoutToken=a.saved();assert.equal(JSON.parse(Object.values(withoutToken).find(v=>v.includes('"profiles"'))).token,'');
 a.$('#forget-settings').click();a.w.dispatchEvent(new a.w.Event('pagehide'));assert.equal(a.w.localStorage.getItem('coach-profile-v2:phone-only-g2-interview-coach-fawf.onrender.com'),null);
 assert.deepEqual(a.errors,[]);a.dom.window.close();
 console.log('PASS: app boot, profile-specific settings/instructions/documents, reload with token, Render Back, token opt-out and Forget without resaving. DOM simulation only; no hardware/layout claim.');
})().catch(e=>{console.error(e);process.exit(1)});
