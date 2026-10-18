const STUDENT_PATHS = new Set([
  '/', '/index.html', '/result', '/api/query_start', '/api/query_poll', '/api/query',
  '/college-background.jpg', '/college-logo.gif', '/poppins-400.ttf',
  '/poppins-500.ttf', '/poppins-700.ttf', '/mepco_crest.png',
  '/mepco_campus.jpg', '/mepco_entrance.jpg',
]);

function failure(res, status, message) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify({error: message}));
}

export function createPortalProxy({backendUrl, fetchImpl = fetch, allowLocalHttp = false} = {}) {
  return async (req, res) => {
    if (req.method !== 'GET') {
      res.setHeader('Allow', 'GET');
      return failure(res, 405, 'This page accepts GET requests only.');
    }
    const incoming = new URL(req.url, 'https://portal.invalid');
    const requestedPath = incoming.searchParams.get('__path') ?? incoming.pathname;
    if (!STUDENT_PATHS.has(requestedPath)) return failure(res, 404, 'Page not found.');
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
        method: 'GET', redirect: 'error', signal: AbortSignal.timeout(110000),
        headers: {'Accept': req.headers?.accept || '*/*'},
      });
      const body = Buffer.from(await upstream.arrayBuffer());
      if (body.length > 4_000_000) throw new Error('Unexpected response size');
      res.statusCode = upstream.status;
      res.setHeader('Content-Type', upstream.headers.get('content-type') || 'application/octet-stream');
      const asset = /\.(jpg|png|gif|ttf)$/.test(requestedPath);
      res.setHeader('Cache-Control', asset ? 'public, max-age=3600' : 'no-store');
      res.setHeader('Content-Length', String(body.length));
      res.end(body);
    } catch {
      return failure(res, 503, 'The result service is starting or temporarily unavailable. Please try again shortly.');
    }
  };
}
