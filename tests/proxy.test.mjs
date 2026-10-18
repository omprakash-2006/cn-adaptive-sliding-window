import test from 'node:test';
import assert from 'node:assert/strict';
import {createPortalProxy} from '../lib/proxy.mjs';

async function run(url, options = {}, method = 'GET') {
  const result = {headers: {}};
  const res = {
    setHeader(k, v) {result.headers[k] = v;},
    end(body) {result.body = body; result.status = this.statusCode;},
  };
  await createPortalProxy(options)({url, method, headers: {}}, res);
  return result;
}

test('public routes cannot expose demo controls, source files, or arbitrary hosts', async () => {
  let calls = 0;
  for (const path of ['/demo', '/api/demo/status', '/api/set_mode', '/backend/server.py', '//other.test', '/%2fdemo']) {
    const res = await run('/api/portal?__path='+encodeURIComponent(path), {
      backendUrl:'https://backend.test', fetchImpl:async()=>{calls++;throw Error();},
    });
    assert.equal(res.status,404);
  }
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
