import test from 'node:test';
import assert from 'node:assert/strict';
import {createPortalProxy} from '../lib/proxy.mjs';

async function run(url, options = {}, method = 'GET', request = {}) {
  const result = {headers: {}};
  const res = {
    setHeader(k, v) {result.headers[k] = v;},
    end(body) {result.body = body; result.status = this.statusCode;},
  };
  await createPortalProxy(options)({url, method, headers: {}, ...request}, res);
  return result;
}

test('public routes cannot expose demo controls, source files, or arbitrary hosts', async () => {
  let calls = 0;
  for (const path of ['/api/demo/status', '/api/set_mode', '/backend/server.py', '//other.test', '/%2fdemo']) {
    const res = await run('/api/portal?__path='+encodeURIComponent(path), {
      backendUrl:'https://backend.test', fetchImpl:async()=>{calls++;throw Error();},
    });
    assert.equal(res.status,404);
  }
  assert.equal(calls,0);
});

test('cloud controls forward only their session cookie and preserve secure login cookies',async()=>{
  let observed;
  const result=await run('/api/portal?__path=/api/cloud-demo/control',{
    backendUrl:'https://backend.test',fetchImpl:async(url,options)=>{
      observed={url:String(url),options};
      return new Response('{"success":true}',{headers:{'set-cookie':'__Host-cn_demo=token; Path=/; Secure; HttpOnly; SameSite=Strict'}});
    },
  },'POST',{headers:{host:'portal.test',origin:'https://portal.test','content-type':'application/json',cookie:'private_login=secret; __Host-cn_demo=123.nonce.signature','x-demo-token':'do-not-forward'},body:{action:'run'}});
  assert.equal(result.status,200);
  assert.equal(observed.options.headers.Cookie,'__Host-cn_demo=123.nonce.signature');
  assert.equal(observed.options.headers['x-demo-token'],undefined);
  assert.equal(observed.options.headers.Origin,'https://portal.test');
  assert.deepEqual(JSON.parse(observed.options.body),{action:'run'});
  assert.match(result.headers['Set-Cookie'],/Secure; HttpOnly/);
});

test('cloud controls reject cross-origin, missing-origin and oversized requests before forwarding',async()=>{
  let calls=0;
  const opts={backendUrl:'https://backend.test',fetchImpl:async()=>{calls++;throw Error()}};
  for(const origin of [undefined,'https://evil.test','http://portal.test']){
    const r=await run('/api/cloud-demo/control',opts,'POST',{headers:{host:'portal.test',origin,'content-type':'application/json'},body:{action:'run'}});
    assert.equal(r.status,403);
  }
  const oversized=await run('/api/cloud-demo/login',opts,'POST',{headers:{host:'portal.test',origin:'https://portal.test','content-type':'application/json'},body:{password:'x'.repeat(4096)}});
  assert.equal(oversized.status,400);
  assert.equal((await run('/api/cloud-demo/control',opts)).status,405);
  assert.equal(calls,0);
});

test('requests retain roll/session parameters and cannot send administration headers', async () => {
  let observed;
  const res = await run('/api/portal?__path=/api/query_poll&session_id=abc-123', {
    backendUrl:'https://backend.test', fetchImpl:async(url,options)=>{
      observed={url:String(url),options};
      return new Response('{"done":true}',{status:200,headers:{'Content-Type':'application/json'}});
    },
  });
  assert.equal(observed.url,'https://backend.test/api/query_poll?session_id=abc-123');
  assert.deepEqual(Object.keys(observed.options.headers),['Accept']);
  assert.equal(res.status,200);
  assert.equal(res.headers['Cache-Control'],'no-store');
});

test('service failures and missing deployment configuration produce clear errors', async () => {
  assert.equal((await run('/api/portal?__path=/')).status,503);
  assert.equal((await run('/api/portal?__path=/',{backendUrl:'https://backend.test',fetchImpl:async()=>{throw Error('network');}})).status,503);
  assert.equal((await run('/api/portal?__path=/',{backendUrl:'http://backend.test'})).status,503);
  assert.equal((await run('/api/portal?__path=/',{},'POST')).status,405);
});

test('authenticated evidence downloads retain their cookie, attachment header and no-store policy',async()=>{
  let observed;
  const result=await run('/api/cloud-demo/evidence',{
    backendUrl:'https://backend.test',fetchImpl:async(url,options)=>{
      observed={url:String(url),cookie:options.headers.Cookie};
      return new Response('{"requests":[]}',{headers:{'content-type':'application/json','content-disposition':'attachment; filename="cn-queue-evidence.json"'}});
    },
  },'GET',{headers:{cookie:'unrelated=private; __Host-cn_demo=123.nonce.signature'}});
  assert.equal(observed.url,'https://backend.test/api/cloud-demo/evidence');
  assert.equal(observed.cookie,'__Host-cn_demo=123.nonce.signature');
  assert.equal(result.headers['Content-Disposition'],'attachment; filename="cn-queue-evidence.json"');
  assert.equal(result.headers['Cache-Control'],'no-store');
  assert.equal(result.status,200);
});
