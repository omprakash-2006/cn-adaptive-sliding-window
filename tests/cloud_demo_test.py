"""Real HTTP/TCP integration on isolated ports and a disposable database."""
import concurrent.futures
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class DemoIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.origin = 'http://127.0.0.1:' + str(free_port())
        cls.password = secrets.token_urlsafe(24)
        env = dict(os.environ, PORT=cls.origin.rsplit(':',1)[1], CN_TCP_PORT=str(free_port()),
                   CN_DEMO_PASSWORD=cls.password, CN_DEMO_ORIGIN=cls.origin,
                   CN_PUBLICATION_DB=cls.temp.name+'/results.sqlite3', PYTHONDONTWRITEBYTECODE='1')
        cls.log = open(cls.temp.name+'/server.log','w+')
        cls.proc = subprocess.Popen([sys.executable,'-u','hosted_launch.py'],cwd=ROOT/'backend',env=env,stdout=cls.log,stderr=cls.log)
        for _ in range(100):
            try:
                if cls.call('/healthz')[0] == 200:
                    break
            except OSError:
                time.sleep(.05)
        else:
            cls.proc.terminate(); cls.proc.wait(timeout=5)
            cls.log.seek(0); raise RuntimeError(cls.log.read())

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate(); cls.proc.wait(timeout=5)
        cls.log.close(); cls.temp.cleanup()

    @classmethod
    def call(cls, path, data=None, cookie=None, origin=True):
        headers={}
        if data is not None:
            headers['Content-Type']='application/json'
            if origin:
                headers['Origin']=cls.origin
        if cookie:
            headers['Cookie']=cookie
        req=urllib.request.Request(cls.origin+path, data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try:
            r=urllib.request.urlopen(req,timeout=8)
        except urllib.error.HTTPError as e:
            r=e
        with r:
            raw=r.read().decode()
            body=json.loads(raw) if r.headers.get_content_type()=='application/json' else raw
            return r.code,body,r.headers

    def test_01_authentication_and_legacy_controls(self):
        self.assertEqual(self.call('/demo')[0],200)
        self.assertEqual(self.call('/api/cloud-demo/status')[0],401)
        self.assertEqual(self.call('/api/cloud-demo/evidence')[0],401)
        self.assertEqual(self.call('/api/cloud-demo/control',{'action':'run'})[0],401)
        self.assertEqual(self.call('/api/cloud-demo/login',{'password':self.password},origin=False)[0],403)
        self.assertEqual(self.call('/api/cloud-demo/login',{'password':'incorrect'})[0],401)
        for route in ['/api/demo/status','/api/set_mode?mode=slowmo','/api/simulate_burst?count=1000','/student_data.json']:
            self.assertEqual(self.call(route)[0],404)

    def test_02_actual_queue_demo_and_normal_restore(self):
        code,_,headers=self.call('/api/cloud-demo/login',{'password':self.password})
        self.assertEqual(code,200)
        self.assertIn('Secure',headers['Set-Cookie'])
        cookie=headers['Set-Cookie'].split(';')[0]
        forged=cookie[:-1]+('a' if cookie[-1]!='a' else 'b')
        self.assertEqual(self.call('/api/cloud-demo/status',cookie=forged)[0],401)
        self.assertEqual(self.call('/api/cloud-demo/control',{'action':'unknown'},cookie)[0],400)
        code, state, _ = self.call('/api/cloud-demo/control', {'action':'slow'}, cookie)
        self.assertEqual(code, 200)
        self.assertEqual(state['metrics']['window_size'], 3)
        code, state, _ = self.call('/api/cloud-demo/control', {'action':'normal'}, cookie)
        self.assertEqual(code, 200)
        self.assertEqual(state['metrics']['window_size'], 10)
        self.assertEqual(self.call('/api/cloud-demo/control',{'action':'run'},cookie)[0],200)
        self.assertEqual(self.call('/api/cloud-demo/control',{'action':'burst'},cookie)[0],409)
        # A real student submission joins the same queue, outside the fixed demo roster.
        for _ in range(100):
            _, loading, _ = self.call('/api/cloud-demo/status', cookie=cookie)
            if loading['metrics']['queue_length'] > 0:
                break
            time.sleep(.02)
        self.assertGreater(loading['metrics']['queue_length'], 0)
        code, started, _ = self.call('/api/query_start?roll=24BAD114')
        self.assertEqual(code, 200)
        portal_queued = False
        observed=False
        for _ in range(160):
            code,d,_=self.call('/api/cloud-demo/status',cookie=cookie)
            self.assertEqual(code,200)
            observed |= d['metrics']['queue_length']>0
            portal_queued |= any(r['roll']=='24BAD114' and r['max_position']>0
                                 for r in d['portal_requests'])
            if not d['running']:
                break
            time.sleep(.2)
        self.assertFalse(d['running'])
        self.assertTrue(observed)
        self.assertTrue(portal_queued)
        self.assertEqual(d['completed'],26)
        self.assertEqual(d['passed'],26)
        self.assertEqual(d['failed'],0)
        self.assertTrue(d['tracked']['success'])
        self.assertGreater(d['tracked']['max_position'],0)
        self.assertTrue(d['tracked']['crc_verified'])
        self.assertTrue(d['tracked']['version_verified'])
        self.assertEqual(d['metrics']['window_size'],10)
        self.assertEqual(d['metrics']['processing_delay'],.2)
        code, evidence, headers = self.call('/api/cloud-demo/evidence', cookie=cookie)
        self.assertEqual(code, 200)
        self.assertIn('attachment;', headers['Content-Disposition'])
        self.assertEqual(evidence['run_id'], d['run_id'])
        self.assertEqual(evidence['evidence']['background_received'], 25)
        self.assertEqual(evidence['evidence']['tcp_received'], 26)
        self.assertEqual(evidence['evidence']['tcp_admitted'], 26)
        self.assertEqual(evidence['evidence']['distinct_tcp_connections'], 26)
        rows = evidence['requests']
        self.assertEqual(len(rows), 26)
        self.assertEqual(len({r['request_id'] for r in rows}), 26)
        code, polled, _ = self.call('/api/query_poll?session_id='+started['session_id'])
        self.assertEqual(code, 200)
        self.assertTrue(polled['done'] and polled['result']['success'])
        manual = next(r for r in evidence['portal_requests'] if r['roll']=='24BAD114')
        self.assertEqual(manual['request_id'], polled['result']['request_id'])
        self.assertEqual(manual['role'], 'portal')
        self.assertEqual(manual['status'], 'DELIVERED')
        self.assertTrue(manual['crc_verified'] and manual['version_verified'])
        self.assertTrue(manual['tcp_peer'] and manual['server_received_at'] and manual['server_admitted_at'])
        self.assertGreater(manual['max_position'], 0)
        self.assertEqual(evidence['portal_evidence']['tcp_received'], 1)
        self.assertEqual([r['roll'] for r in rows if r['role']=='background'], [f'24BAD{i:03d}' for i in range(1,26)])
        trace = [json.loads(line.split('CN_EVIDENCE ',1)[1]) for line in (Path(self.temp.name)/'server.log').read_text().splitlines() if line.startswith('CN_EVIDENCE ')]
        for row in rows + [manual]:
            self.assertTrue(row['success'] and row['done'])
            self.assertEqual(row['status'], 'DELIVERED')
            self.assertTrue(row['crc_verified'] and row['version_verified'])
            self.assertLessEqual(row['server_received_at'], row['server_admitted_at'])
            self.assertLessEqual(row['server_admitted_at'], row['client_finished_at'])
            self.assertGreaterEqual(row['server_wait_ms'], 0)
            events = [e for e in trace if e['request_id']==row['request_id']]
            self.assertEqual([e['event'] for e in events], ['TCP_RECEIVED','TCP_ADMITTED','TCP_CLOSED'])
            expected_run = None if row['role']=='portal' else evidence['run_id']
            self.assertTrue(all(e['run_id']==expected_run and e['tcp_peer']==row['tcp_peer'] for e in events))
        # Repeating the same roll creates a second row and a distinct actual TCP ID.
        _, second, _ = self.call('/api/query_start?roll=24BAD114')
        for _ in range(60):
            _, completed, _ = self.call('/api/query_poll?session_id='+second['session_id'])
            if completed['done']:
                break
            time.sleep(.05)
        self.assertTrue(completed['result']['success'])
        _, latest, _ = self.call('/api/cloud-demo/status', cookie=cookie)
        manual_rows = [r for r in latest['portal_requests'] if r['roll']=='24BAD114']
        self.assertEqual(len(manual_rows), 2)
        self.assertEqual(len({r['request_id'] for r in manual_rows}), 2)
        # Opening the cached marksheet doesn't invent another TCP request.
        self.assertEqual(self.call('/result?roll=24BAD114')[0], 200)
        _, latest, _ = self.call('/api/cloud-demo/status', cookie=cookie)
        self.assertEqual(len(latest['portal_requests']), 2)
        self.assertEqual(self.call('/api/cloud-demo/logout',{},cookie)[0],200)
        # Existing student result service remains available after the demonstration.
        code,r,_=self.call('/api/query?roll=24BAD130&force=1')
        self.assertEqual(code,200)
        self.assertTrue(r['success'])


if __name__ == '__main__':
    unittest.main()
