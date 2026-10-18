import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../backend/web_portal.py',import.meta.url),'utf8');
const script=source.slice(source.indexOf('    async function queueRequest'),source.indexOf('  </script>',source.indexOf('    async function queueRequest')));
function setup(responses) {
  const elements=new Map(), timers=[], calls=[];
  const element=id=>{if(!elements.has(id))elements.set(id,{value:'24BAD025',disabled:false,hidden:true,style:{},focus(){},querySelector(){return element('dialog')}});return elements.get(id)};
  let active=0,peak=0;
  const context=vm.createContext({document:{getElementById:element,querySelector:element},window:{location:{href:''}},AbortController,
    fetch:async(url)=>{calls.push(url);active++;peak=Math.max(peak,active);try{return await responses.shift()(url)}finally{active--}},
    setTimeout:(fn,ms)=>{const timer={fn,ms};timers.push(timer);return timer},clearTimeout:t=>{const i=timers.indexOf(t);if(i>=0)timers.splice(i,1)}});
  vm.runInContext(script,context);
  return {context,element,calls,timers,get peak(){return peak},async next(){await timers.shift().fn()}};
}
const response=(body,ok=true)=>async()=>({ok,json:async()=>body});
const event={preventDefault(){}};
test('one outstanding poll, normal waiting and verified completion',async()=>{
 const ui=setup([response({session_id:'abc'}),response({done:false,position:5,total_queued:7}),response({done:false,position:0}),response({done:true,result:{success:true}})]);
 await ui.context.handleQuerySubmit(event);
 assert.equal(ui.element('queuePosVal').innerText,'#5 of 7');
 assert.equal(ui.element('queueEstVal').innerText,'Calculating…');
 assert.equal(ui.timers.length,1);assert.equal(ui.timers[0].ms,500);
 await ui.next(); assert.equal(ui.element('queuePercentText').innerText,'Preparing result');
 await ui.next();assert.equal(ui.context.window.location.href,'/result?roll=24BAD025');
 assert.equal(ui.peak,1); assert.equal(ui.timers.length,0);
});
test('server failures stop after bounded retries without duplicate result request',async()=>{
 const ui=setup([response({session_id:'abc'}),...Array.from({length:3},()=>response({error:'unavailable'},false))]);
 await ui.context.handleQuerySubmit(event);await ui.next();await ui.next();
 assert.equal(ui.element('queueRetry').hidden,false);assert.equal(ui.timers.length,0);
 assert.equal(ui.context.window.location.href,'');assert.equal(ui.calls.filter(x=>x.includes('query_start')).length,1);
});
test('malformed start response shows recovery link without polling undefined session',async()=>{
 const ui=setup([response({error:'starting'})]);await ui.context.handleQuerySubmit(event);
 assert.equal(ui.calls.length,1);assert.equal(ui.element('queueRetry').hidden,false);assert.equal(ui.timers.length,0);
});
test('double submit does not start a second student request',async()=>{
 let resolve;const blocked=new Promise(r=>resolve=r);
 const ui=setup([()=>blocked,response({done:true,result:{success:true}})]);
 const first=ui.context.handleQuerySubmit(event);await ui.context.handleQuerySubmit(event);
 resolve({ok:true,json:async()=>({session_id:'abc'})});await first;
 assert.equal(ui.calls.filter(x=>x.includes('query_start')).length,1);
});
test('unknown registration terminates with clear error',async()=>{
 const ui=setup([response({session_id:'abc'}),response({done:true,result:{success:false,status_message:'RECORD_NOT_FOUND'}})]);
 await ui.context.handleQuerySubmit(event);assert.match(ui.element('queueStatusText').innerText,/Register number not found/);
 assert.equal(ui.timers.length,0);assert.equal(ui.context.window.location.href,'');
});
test('transient poll failure resumes existing session',async()=>{
 const ui=setup([response({session_id:'abc'}),response({},false),response({done:true,result:{success:true}})]);
 await ui.context.handleQuerySubmit(event);await ui.next();assert.equal(ui.calls[1],ui.calls[2]);
 assert.equal(ui.context.window.location.href,'/result?roll=24BAD025');
});
