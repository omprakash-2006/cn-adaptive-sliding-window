const STUDENT_PATHS = new Set([
  '/', '/index.html', '/result', '/api/query_start', '/api/query_poll', '/api/query',
  '/college-background.jpg', '/college-logo.gif', '/poppins-400.ttf',
  '/poppins-500.ttf', '/poppins-700.ttf', '/mepco_crest.png',
  '/mepco_campus.jpg', '/mepco_entrance.jpg',
]);
const DEMO_GET = new Set(['/demo', '/api/cloud-demo/status']);
const DEMO_POST = new Set(['/api/cloud-demo/login', '/api/cloud-demo/logout', '/api/cloud-demo/control']);

function failure(res, status, message) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify({error: message}));
}

export function createPortalProxy({backendUrl, fetchImpl = fetch, allowLocalHttp = false} = {}) {
  return async (req, res) => {
    const incoming = new URL(req.url, 'https://portal.invalid');
    const requestedPath = incoming.searchParams.get('__path') ?? incoming.pathname;
    const demo = DEMO_GET.has(requestedPath) || DEMO_POST.has(requestedPath);
    if (!STUDENT_PATHS.has(requestedPath) && !demo) return failure(res, 404, 'Page not found.');
    const expectedMethod = DEMO_POST.has(requestedPath) ? 'POST' : 'GET';
    if (req.method !== expectedMethod) {
      res.setHeader('Allow', expectedMethod);
      return failure(res, 405, 'Method not allowed.');
    }
    const headers = {'Accept': req.headers?.accept || '*/*'};
    let postBody;
    if (demo) {
      const cookie = (req.headers?.cookie || '').split(';').map(x=>x.trim())
        .find(x=>/^__Host-cn_demo=[A-Za-z0-9_.-]+$/.test(x) && x.length < 512);
      if (cookie) headers.Cookie = cookie;
      if (req.method === 'POST') {
        try {
          const origin = new URL(req.headers?.origin);
          if (origin.host !== req.headers?.host || origin.pathname !== '/' || origin.search || origin.hash
              || (origin.protocol !== 'https:' && !(allowLocalHttp && origin.hostname === '127.0.0.1' && origin.protocol === 'http:'))) throw Error();
          if ((req.headers?.['content-type'] || '').split(';')[0] !== 'application/json') throw Error();
          headers.Origin = origin.origin;
          headers['Content-Type'] = 'application/json';
        } catch { return failure(res,403,'Submit testing actions from this website.'); }
        try {
          if (Number(req.headers?.['content-length']) > 4096) throw Error();
          if (req.body !== undefined) {
            postBody = typeof req.body === 'string' || Buffer.isBuffer(req.body) ? req.body : JSON.stringify(req.body);
          } else {
            const chunks=[]; let size=0;
            for await (const chunk of req) {
              const buf=Buffer.from(chunk); size+=buf.length;
              if(size>4096) throw Error();
              chunks.push(buf);
            }
            postBody=Buffer.concat(chunks);
          }
          if (Buffer.byteLength(postBody)>4096) throw Error();
          const parsed=JSON.parse(postBody.toString());
          if(!parsed || Array.isArray(parsed) || typeof parsed!=='object') throw Error();
        } catch { return failure(res,400,'Invalid testing request.'); }
      }
    }
    let target;
    try {
      const base = new URL(backendUrl);
      const local = ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname);
      if (base.username || base.password || base.pathname !== '/' || base.search || base.hash
          || (base.protocol !== 'https:' && !(allowLocalHttp && local && base.protocol === 'http:'))) {
        throw new Error('Unsupported backend address');
      }
      target = new URL(requestedPath, base);
      incoming.searchParams.delete('__path');
      target.search = incoming.searchParams.toString();
    } catch {
      return failure(res, 503, 'The result service is not configured yet. Please try again later.');
    }
    try {
      const upstream = await fetchImpl(target, {
        method: req.method, redirect: 'error', signal: AbortSignal.timeout(110000),
        headers, body: postBody,
      });
      const body = Buffer.from(await upstream.arrayBuffer());
      if (body.length > 4_000_000) throw new Error('Unexpected response size');
      res.statusCode = upstream.status;
      res.setHeader('Content-Type', upstream.headers.get('content-type') || 'application/octet-stream');
      if (demo) {
        for (const name of ['content-security-policy','x-frame-options','x-content-type-options','referrer-policy']) {
          const value=upstream.headers.get(name); if(value) res.setHeader(name,value);
        }
        const cookie=upstream.headers.get('set-cookie');
        if(cookie?.startsWith('__Host-cn_demo=')) res.setHeader('Set-Cookie',cookie);
      }
      const asset = /\.(jpg|png|gif|ttf)$/.test(requestedPath);
      res.setHeader('Cache-Control', asset ? 'public, max-age=3600' : 'no-store');
      res.setHeader('Content-Length', String(body.length));
      res.end(body);
    } catch {
      return failure(res, 503, 'The result service is starting or temporarily unavailable. Please try again shortly.');
    }
  };
}
