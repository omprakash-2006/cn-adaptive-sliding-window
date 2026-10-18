import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../backend/cloud_demo.py',import.meta.url),'utf8');
const script=source.split('<script nonce="__NONCE__">')[1].split('</script>')[0];
function setup(fetch) {
 const elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{hidden:false,disabled:false,dataset:{action:id},addEventListener(event,fn){this[event]=fn}});return elements.get(id)};
 const context=vm.createContext({document:{getElementById:element,querySelectorAll:()=>['run','slow','burst','normal'].map(element)},fetch,setInterval(){}});
 vm.runInContext(script,context);return {context,element};
}
const state=running=>({running,total:26,completed:0,passed:0,failed:0,elapsed:0,metrics:{window_size:3,active_window:3,queue_length:23},tracked:{}});
test('cloud status refresh does not overlap a slow request',async()=>{
 let resolve,calls=0;const waiting=new Promise(r=>resolve=r);
 const ui=setup(()=>{calls++;return waiting});
 await ui.context.refresh();assert.equal(calls,1);
 resolve({ok:true,json:async()=>state(false)});
 await new Promise(r=>setImmediate(r));assert.equal(ui.element('dashboard').hidden,false);
});
test('burst controls stay disabled until the run completes',async()=>{
 const ui=setup(async()=>({ok:true,json:async()=>state(true)}));
 await new Promise(r=>setImmediate(r));
 await ui.element('run').click();
 for(const id of ['run','slow','burst'])assert.equal(ui.element(id).disabled,true);
 ui.context.render(state(false));
 for(const id of ['run','slow','burst'])assert.equal(ui.element(id).disabled,false);
});
