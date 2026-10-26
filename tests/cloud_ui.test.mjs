import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../backend/cloud_demo.py',import.meta.url),'utf8');
const script=source.split('<script nonce="__NONCE__">')[1].split('</script>')[0];
function setup(fetch) {
 const elements=new Map();
 const node=()=>({children:[],replaceChildren(){this.children=[]},append(child){this.children.push(child)}});
 const element=id=>{if(!elements.has(id))elements.set(id,{...node(),hidden:false,disabled:false,dataset:{action:id},addEventListener(event,fn){this[event]=fn}});return elements.get(id)};
 const context=vm.createContext({document:{getElementById:element,createElement:node,querySelectorAll:()=>['run','slow','burst','normal'].map(element)},fetch,setInterval(){}});
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

test('evidence rows display only server-provided observations and reset for a new run',async()=>{
 const ui=setup(async()=>({ok:true,json:async()=>state(false)}));
 await new Promise(r=>setImmediate(r));
 const proof={...state(false),run_id:'run-one',evidence:{instance_id:'server-one',background_received:1,distinct_tcp_connections:1,tcp_admitted:1},requests:[{roll:'24BAD001',role:'background',request_id:'a'.repeat(32),status:'DELIVERED',position:0,max_position:20,tcp_peer:'127.0.0.1:54321',server_received_at:'2026-10-26T09:00:00.100+00:00',server_admitted_at:'2026-10-26T09:00:01.100+00:00',latency_ms:1200,done:true,success:true,crc_verified:true,version_verified:true}]};
 ui.context.render(proof);
 assert.equal(ui.element('backgroundReceived').textContent,'1 / 25');
 const cells=ui.element('requestRows').children[0].children;
 assert.equal(cells[1].children[0].textContent,'a'.repeat(32));
 assert.equal(cells[2].textContent,'DELIVERED');assert.equal(cells[4].textContent,'127.0.0.1:54321');
 assert.equal(cells[5].textContent,'09:00:00.100');assert.equal(cells[8].textContent,'Both verified');
 ui.context.render(state(false));assert.equal(ui.element('requestRows').children.length,0);
 assert.equal(ui.element('evidenceDownload').hidden,true);
});
