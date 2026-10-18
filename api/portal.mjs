import {createPortalProxy} from '../lib/proxy.mjs';

export default function handler(req, res) {
  return createPortalProxy({backendUrl: process.env.BACKEND_URL})(req, res);
}
