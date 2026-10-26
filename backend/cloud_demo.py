"""Authenticated, bounded cloud demonstration of the existing TCP controller."""
import copy
import hashlib
import hmac
from http.cookies import SimpleCookie
import json
import os
import secrets
import threading
import time
import uuid
from request_evidence import utc_now
from urllib.parse import urlsplit

COOKIE = '__Host-cn_demo'
ROUTES = {'/demo', '/api/cloud-demo/login', '/api/cloud-demo/logout',
          '/api/cloud-demo/status', '/api/cloud-demo/control', '/api/cloud-demo/evidence'}


class CloudDemo:
    def __init__(self, server, client, tcp_port, password=None, secure=True, origin=None):
        self.server, self.client, self.tcp_port = server, client, tcp_port
        self.password = password if password is not None else os.environ.get('CN_DEMO_PASSWORD', '')
        self.secure = secure
        self.origin = origin or os.environ.get('CN_DEMO_ORIGIN', 'https://cn-adaptive-sliding-window.vercel.app')
        self.key = hashlib.sha256((self.password + secrets.token_hex(32)).encode()).digest()
        self.lock = threading.RLock()
        self.attempts = []
        self.lease = None
        self.state = {'running': False, 'total': 0, 'completed': 0, 'passed': 0,
                      'failed': 0, 'tracked': {}, 'started': None, 'finished': None, 'requests': {}}

    def authenticated(self, handler):
        if len(self.password) < 12:
            return False
        try:
            jar = SimpleCookie(); jar.load(handler.headers.get('Cookie', '')[:4096])
            value = jar[COOKIE].value
            expiry, nonce, signature = value.split('.')
            message = expiry + '.' + nonce
            valid = hmac.compare_digest(signature, hmac.new(self.key, message.encode(), 'sha256').hexdigest())
            return valid and time.time() < int(expiry) <= time.time() + 7200
        except (KeyError, ValueError, TypeError):
            return False

    def reply(self, handler, data, status=200, cookie=None, html=False, nonce=None, filename=None):
        body = data.encode() if html else json.dumps(data).encode()
        handler.send_response(status)
        handler.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Referrer-Policy', 'same-origin')
        handler.send_header('X-Frame-Options', 'DENY')
        if html:
            handler.send_header('Content-Security-Policy', "default-src 'self'; script-src 'nonce-" + nonce + "'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if filename:
            handler.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
        if cookie is not None:
            handler.send_header('Set-Cookie', cookie)
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers(); handler.wfile.write(body)

    def cookie(self, value, age=7200):
        return f'{COOKIE}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}' + ('; Secure' if self.secure else '')

    def handle(self, handler):
        route = urlsplit(handler.path).path
        if route not in ROUTES:
            return False
        if route == '/demo' and handler.command == 'GET':
            nonce = secrets.token_urlsafe(18)
            self.reply(handler, PAGE.replace('__NONCE__', nonce), html=True, nonce=nonce)
            return True
        if handler.command == 'POST':
            # Browsers must submit from the configured student website, even on direct backend access.
            if handler.headers.get('Origin') != self.origin:
                self.reply(handler, {'error': 'Open the testing page on the student website.'}, 403)
                return True
            try:
                size = int(handler.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096 or handler.headers.get_content_type() != 'application/json':
                    raise ValueError()
                data = json.loads(handler.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError()
            except (ValueError, TypeError, UnicodeError):
                self.reply(handler, {'error': 'Invalid request.'}, 400); return True
            if route == '/api/cloud-demo/login':
                if len(self.password) < 12:
                    self.reply(handler, {'error': 'Testing password is not configured. Set CN_DEMO_PASSWORD (at least 12 characters) in Render Environment.'}, 503)
                    return True
                with self.lock:
                    now = time.monotonic()
                    self.attempts = [t for t in self.attempts if now-t < 60]
                    if len(self.attempts) >= 10:
                        self.reply(handler, {'error': 'Too many attempts. Wait one minute.'}, 429); return True
                    self.attempts.append(now)
                supplied = data.get('password', '')
                if not isinstance(supplied, str) or not hmac.compare_digest(hashlib.sha256(supplied.encode()).digest(), hashlib.sha256(self.password.encode()).digest()):
                    self.reply(handler, {'error': 'Incorrect testing password.'}, 401); return True
                message = str(int(time.time()) + 7199) + '.' + secrets.token_urlsafe(18)
                value = message + '.' + hmac.new(self.key, message.encode(), 'sha256').hexdigest()
                self.reply(handler, {'success': True}, cookie=self.cookie(value))
                return True
        elif route not in ('/api/cloud-demo/status', '/api/cloud-demo/evidence'):
            self.reply(handler, {'error': 'Use POST for testing actions.'}, 405); return True
        if not self.authenticated(handler):
            self.reply(handler, {'error': 'Sign in to use testing controls.'}, 401); return True
        if route in ('/api/cloud-demo/status', '/api/cloud-demo/evidence') and handler.command == 'GET':
            self.reply(handler, self.snapshot(), filename='cn-queue-evidence.json' if route.endswith('/evidence') else None); return True
        if handler.command != 'POST':
            self.reply(handler, {'error': 'Method not allowed.'}, 405); return True
        if route == '/api/cloud-demo/logout':
            self.reply(handler, {'success': True}, cookie=self.cookie('', 0)); return True
        if route != '/api/cloud-demo/control':
            self.reply(handler, {'error': 'Method not allowed.'}, 405); return True
        action = data.get('action')
        with self.lock:
            if action in ('run', 'burst'):
                if self.state['running']:
                    self.reply(handler, {'error': 'A demonstration is already running.'}, 409); return True
                # At most 26 synthetic TCP clients per authenticated run; no arbitrary count/input.
                self.state = {'running': True, 'total': 26, 'completed': 0, 'passed': 0,
                              'failed': 0, 'tracked': {'roll': '24BAD130', 'position': 0, 'max_position': 0},
                              'started': time.monotonic(), 'finished': None}
                self.state['run_id'] = uuid.uuid4().hex
                self.state['started_at'] = utc_now()
                rolls = [f'24BAD{i+1:03d}' for i in range(25)] + ['24BAD130']
                self.state['requests'] = {roll: {'roll': roll, 'request_id': uuid.uuid4().hex,
                    'role': 'tracked' if roll == '24BAD130' else 'background',
                    'status': 'STARTING', 'position': 0, 'max_position': 0,
                    'done': False, 'success': False, 'crc_verified': False, 'version_verified': False,
                    'client_started_at': None, 'client_finished_at': None, 'latency_ms': None}
                    for roll in rolls}
                self.server.REQUEST_EVIDENCE.start(self.state['run_id'], self.state['requests'].values())
                if action == 'run':
                    self.set_slow()
                threading.Thread(target=self.run, daemon=True).start()
            elif action == 'slow':
                if self.state['running']:
                    self.reply(handler, {'error': 'Wait for the current demonstration to finish.'}, 409); return True
                self.set_slow()
            elif action == 'normal':
                self.restore()
            else:
                self.reply(handler, {'error': 'Unknown testing action.'}, 400); return True
        self.reply(handler, self.snapshot())
        return True

    def set_slow(self):
        if self.lease:
            self.lease.cancel()
        self.server.set_demo_mode('slowmo')
        self.lease = threading.Timer(90, self.restore)
        self.lease.daemon = True; self.lease.start()

    def restore(self):
        with self.lock:
            if self.lease:
                self.lease.cancel(); self.lease = None
            self.server.set_demo_mode('normal')

    def snapshot(self):
        with self.lock:
            state = copy.deepcopy(self.state)
            if state['started'] is not None:
                state['elapsed'] = round((state['finished'] or time.monotonic()) - state['started'], 1)
            else:
                state['elapsed'] = 0
            state.pop('started'); state.pop('finished')
            state['metrics'] = self.server.get_live_metrics()
            observations = self.server.REQUEST_EVIDENCE.snapshot(state.get('run_id'))
            rows = list(state.pop('requests', {}).values())
            for row in rows:
                row.update(observations.get(row['request_id'], {}))
            state['requests'] = rows
            state['evidence'] = {'instance_id': self.server.REQUEST_EVIDENCE.instance_id,
                'source': 'Real TCP handler events and CRC/version-verified TCP client replies',
                'tcp_received': sum(bool(r.get('server_received_at')) for r in rows),
                'tcp_admitted': sum(bool(r.get('server_admitted_at')) for r in rows),
                'distinct_tcp_connections': len({r['tcp_peer'] for r in rows if r.get('tcp_peer')}),
                'background_received': sum(r['role'] == 'background' and bool(r.get('server_received_at')) for r in rows)}
            return state

    def run(self):
        threads = []
        barrier = threading.Barrier(25)
        queued = threading.Event()
        run_id = self.state['run_id']

        def request(roll, tracked=False):
            row = self.state['requests'][roll]
            request_id = row['request_id']
            def telemetry(position, total, status):
                if position > 0:
                    queued.set()
                with self.lock:
                    row.update(position=position, total_queued=total,
                               status='QUEUED' if position > 0 else 'PROCESSING')
                    row['max_position'] = max(row['max_position'], position)
                    if tracked:
                        item = self.state['tracked']
                        item.update(position=position, total_queued=total, status=status)
                        item['max_position'] = max(item['max_position'], position)
            try:
                if not tracked:
                    barrier.wait(timeout=10)
                with self.lock:
                    row.update(client_started_at=utc_now(), status='CONNECTING')
                result = self.client.request_result(roll, port=self.tcp_port, timeout=40, verbose=False,
                                                    queue_callback=telemetry, request_id=request_id)
                ok = (result.get('success') and result.get('crc_verified')
                      and result.get('version_verified') and (result.get('result_data') or {}).get('roll_number') == roll
                      and result.get('request_id') == request_id
                      and self.server.REQUEST_EVIDENCE.admitted(run_id, request_id))
                with self.lock:
                    row.update(done=True, success=bool(ok), status='DELIVERED' if ok else 'FAILED',
                               position=0, client_finished_at=utc_now(),
                               latency_ms=round(result.get('latency', 0)*1000, 2),
                               crc_verified=bool(result.get('crc_verified')),
                               version_verified=bool(result.get('version_verified')))
                    self.state['completed'] += 1
                    self.state['passed' if ok else 'failed'] += 1
                    if tracked:
                        self.state['tracked'].update(done=True, success=bool(ok), position=0,
                            status=result.get('status_message'), result=result.get('result_data') if ok else None,
                            crc_verified=bool(result.get('crc_verified')), version_verified=bool(result.get('version_verified')))
            except Exception:
                with self.lock:
                    row.update(done=True, success=False, status='FAILED', client_finished_at=utc_now())
                    self.state['completed'] += 1; self.state['failed'] += 1
                    if tracked:
                        self.state['tracked'].update(done=True, success=False, status='Request failed')
        try:
            for i in range(25):
                t = threading.Thread(target=request, args=(f'24BAD{i+1:03d}',), daemon=True)
                threads.append(t); t.start()
            queued.wait(timeout=2)
            tracked = threading.Thread(target=request, args=('24BAD130', True), daemon=True)
            threads.append(tracked); tracked.start()
            for t in threads:
                t.join()
        finally:
            with self.lock:
                self.restore()
                self.state['running'] = False
                self.state['finished'] = time.monotonic()


PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Queue Testing · CN Project</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f2f6fc;color:#193453;font:15px system-ui,sans-serif}main{max-width:1050px;margin:40px auto;padding:0 20px}header{display:flex;justify-content:space-between;align-items:center;gap:20px}h1{font-size:28px;margin-bottom:8px}h2{font-size:20px}p{line-height:1.7;color:#526782}a{color:#075cc5}section{background:white;border:1px solid #dce5f1;border-radius:16px;padding:24px;margin:22px 0;box-shadow:0 8px 30px #18345609}label{display:block;margin:18px 0 8px}input,button{font:inherit;border:1px solid #bed0e5;border-radius:8px;padding:12px}input{width:100%;max-width:420px}button{background:#eaf2ff;color:#154e97;cursor:pointer}button.primary{background:#075cc5;color:white;border-color:#075cc5}button:disabled{opacity:.5;cursor:wait}.actions{display:flex;gap:10px;flex-wrap:wrap}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.metric{padding:16px;background:#f4f8ff;border-radius:10px}.metric span{display:block;font-size:28px;font-weight:650;margin-top:6px}.small{font-size:13px}.pill{display:inline-block;border-radius:20px;padding:5px 12px;background:#edf5ff;color:#075cc5}.error{color:#ae2039}#queuePosition{font-size:48px;font-weight:700;color:#075cc5}#notice{padding:12px 16px;background:#fff7df;border-radius:8px}#resultDetails{white-space:pre-line}button:focus-visible,input:focus-visible,a:focus-visible{outline:3px solid #ffb830;outline-offset:3px}.evidence-scroll{overflow:auto;max-height:560px;border:1px solid #dce5f1;border-radius:10px}table{border-collapse:collapse;width:100%;min-width:1080px;font-size:12px}th,td{text-align:left;padding:12px 10px;border-bottom:1px solid #e3ebf6;vertical-align:top}th{position:sticky;top:0;background:#edf4fd;color:#264b76;z-index:1}td code{font-size:11px;overflow-wrap:anywhere;display:block;max-width:160px}.stage{font-weight:650;color:#075cc5}.stage.delivered{color:#14763d}.stage.failed{color:#ae2039}.evidence-summary{display:flex;gap:12px;flex-wrap:wrap}.evidence-summary strong{color:#193453}#runMeta{overflow-wrap:anywhere}.download{display:inline-block;padding:10px 14px;border:1px solid #bed0e5;border-radius:8px;text-decoration:none;background:#edf5ff}[hidden]{display:none!important}@media(max-width:640px){main{margin-top:20px}.metrics{grid-template-columns:repeat(2,1fr)}header{align-items:flex-start;flex-direction:column}section{padding:18px}}</style></head><body><main>
<header><div><div class="pill">MEPCO · COMPUTER NETWORKS PROJECT</div><h1>Queue demonstration</h1><p>Actual cloud TCP requests, live admission window and verified results.</p></div><a href="/" target="_blank" rel="noopener">Open student portal ↗</a></header>
<section id="login"><h2>Presenter sign in</h2><p>Testing controls are available only with the presenter password.</p><form id="loginForm"><label for="password">Testing password</label><input id="password" type="password" autocomplete="current-password" required minlength="12"><button class="primary" type="submit">Sign in</button></form></section>
<div id="dashboard" hidden><p id="notice">This demonstration uses the same synthetic-result backend as the student portal. Slow mode briefly affects its processing speed and automatically restores within 90 seconds.</p>
<section><h2>Show the queue in one click</h2><p>Start 25 background students and track student <strong>24BAD130</strong>. The demo uses 3 processing slots so waiting is visible. Normal mode returns automatically when the run finishes.</p><div class="actions"><button id="run" class="primary" data-action="run">Run queue demo</button><button id="slow" data-action="slow">Slow mode · W=3</button><button id="burst" data-action="burst">25-student burst</button><button data-action="normal">Restore normal mode</button><button id="logout">Sign out</button></div></section>
<section><h2>Live server activity</h2><div class="metrics"><div class="metric">Processing slots<span id="window">—</span></div><div class="metric">Active requests<span id="active">—</span></div><div class="metric">Waiting requests<span id="waiting">—</span></div><div class="metric">Verified deliveries<span id="passed">—</span></div></div><p class="small" id="progress">Ready to demonstrate.</p></section>
<section aria-live="polite"><h2>Tracked student · 24BAD130</h2><div id="queuePosition">Ready</div><p id="trackedStatus">Start the queue demo to observe live waiting.</p><p id="resultDetails"></p><a id="marksheet" href="/result?roll=24BAD130" target="_blank" rel="noopener" hidden>Open verified marksheet ↗</a></section><section><h2>Actual backend request evidence</h2><p class="small">25 generated background clients + 1 tracked client. Every received/admitted timestamp and TCP address below is recorded by the real server handler. Times are UTC.</p><p id="runMeta" class="small">No run yet.</p><div class="evidence-summary small"><span>Background requests received: <strong id="backgroundReceived">0 / 25</strong></span><span>Distinct TCP connections: <strong id="tcpConnections">0</strong></span><span>Server admissions: <strong id="serverAdmissions">0</strong></span></div><p><a id="evidenceDownload" class="download" href="/api/cloud-demo/evidence" download="cn-queue-evidence.json" hidden>Download backend evidence (JSON)</a></p><div class="evidence-scroll" role="region" aria-label="Individual backend requests" tabindex="0"><table><thead><tr><th scope="col">Student / role</th><th scope="col">Request ID</th><th scope="col">Live status</th><th scope="col">Queue / highest</th><th scope="col">TCP client address</th><th scope="col">Server received (UTC)</th><th scope="col">Server admitted (UTC)</th><th scope="col">Delivery time</th><th scope="col">CRC / version</th></tr></thead><tbody id="requestRows"></tbody></table></div><p class="small">Cross-check the run ID and request ID in Render Logs using <code>CN_EVIDENCE</code>. Each request records TCP_RECEIVED, TCP_ADMITTED and TCP_CLOSED events. These are concurrent synthetic test clients using real TCP sockets.</p></section></div>
<p id="message" role="status"></p><p class="small">This is a bounded sample demonstration, not evidence of 1,000-student capacity. No real college database is connected.</p></main>
<script nonce="__NONCE__">const $=id=>document.getElementById(id);let signedIn=false,pending=false,refreshing=false,lastStatus=null;
async function api(path,data){const r=await fetch('/api/cloud-demo/'+path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined,cache:'no-store'});let d;try{d=await r.json()}catch{throw Error('The server is starting. Please try again shortly.')}if(!r.ok){if(r.status===401){signedIn=false;showLogin()}throw Error(d.error||'Request failed')}return d}
function showLogin(){$('login').hidden=false;$('dashboard').hidden=true}function message(s,error=false){$('message').textContent=s;$('message').className=error?'error':''}
function evidence(d){const rows=d.requests||[],proof=d.evidence||{};$('runMeta').textContent=d.run_id?'Run: '+d.run_id+' · Server instance: '+proof.instance_id:'No run yet.';$('backgroundReceived').textContent=(proof.background_received||0)+' / 25';$('tcpConnections').textContent=proof.distinct_tcp_connections||0;$('serverAdmissions').textContent=proof.tcp_admitted||0;$('evidenceDownload').hidden=!d.run_id;const body=$('requestRows');body.replaceChildren();const clock=value=>value?value.slice(11,23):'—';for(const item of rows){const row=document.createElement('tr');const status=item.status==='DELIVERED'?'DELIVERED':item.status==='FAILED'?'FAILED':item.server_admitted_at?'PROCESSING':item.status==='QUEUED'?'QUEUED':item.server_received_at?'RECEIVED':item.status;const values=[item.roll+' · '+item.role,item.request_id,status,item.position+' / '+item.max_position,item.tcp_peer||'Awaiting TCP connection',clock(item.server_received_at),clock(item.server_admitted_at),item.latency_ms==null?'—':(item.latency_ms/1000).toFixed(2)+' s',item.done?(item.success&&item.crc_verified&&item.version_verified?'Both verified':'Not verified'):'Pending'];values.forEach((value,index)=>{const cell=document.createElement('td');if(index===1){const code=document.createElement('code');code.textContent=value;cell.append(code)}else cell.textContent=value;if(index===2)cell.className='stage '+status.toLowerCase();row.append(cell)});body.append(row)}}
function render(d){evidence(d);lastStatus=d;signedIn=true;$('login').hidden=true;$('dashboard').hidden=false;const m=d.metrics,t=d.tracked||{};$('window').textContent=m.window_size;$('active').textContent=m.active_window;$('waiting').textContent=m.queue_length;$('passed').textContent=d.passed+'/'+d.total;$('progress').textContent=d.total?(d.running?'Running':'Finished')+' · '+d.completed+'/'+d.total+' complete · '+d.failed+' failed · '+d.elapsed+' seconds':'Normal capacity: 10 slots. Slow mode: 3 slots.';for(const id of ['run','slow','burst'])$(id).disabled=d.running||pending;$('queuePosition').textContent=t.done?(t.success?'Delivered':'Failed'):t.position>0?'#'+t.position:d.running?'Processing…':'Ready';$('trackedStatus').textContent=t.done?'Highest observed queue position: '+t.max_position:t.position>0?'Waiting fairly in FIFO order. Keep this page open.':d.running?'Waiting for live TCP updates…':'Start the queue demo to observe live waiting.';$('marksheet').hidden=!(t.done&&t.success);$('resultDetails').textContent=t.done&&t.success?'CRC-32: verified · Publication version: verified\n'+t.result.name+' · SGPA '+t.result.gpa+' · '+t.result.status:''}
$('loginForm').addEventListener('submit',async e=>{e.preventDefault();try{await api('login',{password:$('password').value});$('password').value='';render(await api('status'));message('Signed in. Testing controls are ready.')}catch(e){message(e.message,true)}});
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',async()=>{if(pending)return;pending=true;b.disabled=true;try{render(await api('control',{action:b.dataset.action}));message(b.dataset.action==='normal'?'Normal mode restored.':'Testing action started. Live activity updates below.')}catch(e){message(e.message,true)}finally{pending=false;if(signedIn&&lastStatus)render(lastStatus);else b.disabled=false}}));
$('logout').addEventListener('click',async()=>{try{await api('logout',{});signedIn=false;showLogin();message('Signed out. Any active demonstration will finish and restore normal mode.')}catch(e){message(e.message,true)}});
async function refresh(){if(refreshing)return;refreshing=true;try{render(await api('status'))}catch(e){if(signedIn)message(e.message,true)}finally{refreshing=false}}refresh();setInterval(()=>{if(signedIn&&!pending)refresh()},700);
</script></body></html>'''
