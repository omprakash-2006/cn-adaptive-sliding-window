"""Bounded evidence for demo clients and actual student-portal TCP requests."""
from collections import OrderedDict
import copy
from datetime import datetime, timezone
import json
import threading
import time
import uuid


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class RequestEvidence:
    def __init__(self):
        self.instance_id = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.runs = OrderedDict()
        self.watched = {}
        self.portal_requests = OrderedDict()
        self.sequence = 0

    def start_portal(self, request_id, roll):
        with self.lock:
            self.portal_requests[request_id] = {
                'request_id': request_id, 'roll': roll, 'role': 'portal',
                'status': 'CONNECTING', 'position': 0, 'max_position': 0,
                'done': False, 'success': False, 'crc_verified': False,
                'version_verified': False, 'client_started_at': utc_now(),
                'client_finished_at': None, 'latency_ms': None,
                'server_received_at': None, 'server_admitted_at': None,
                'server_finished_at': None, 'tcp_peer': None, 'server_wait_ms': None,
                'events': []}
            # Retain the most recent 100 portal requests, independently of demo runs.
            while len(self.portal_requests) > 100:
                self.portal_requests.popitem(last=False)

    def portal_queue(self, request_id, position):
        with self.lock:
            item = self.portal_requests.get(request_id)
            if item is not None:
                item.update(position=position, status='QUEUED' if position > 0 else 'PROCESSING')
                item['max_position'] = max(item['max_position'], position)

    def finish_portal(self, request_id, result):
        with self.lock:
            item = self.portal_requests.get(request_id)
            if item is None:
                return
            ok = bool(result.get('success') and result.get('crc_verified')
                      and result.get('version_verified') and item['server_admitted_at']
                      and result.get('request_id') == request_id
                      and (result.get('result_data') or {}).get('roll_number') == item['roll'])
            item.update(done=True, success=ok, status='DELIVERED' if ok else 'FAILED',
                        position=0, client_finished_at=utc_now(),
                        latency_ms=round(result.get('latency', 0)*1000, 2),
                        crc_verified=bool(result.get('crc_verified')),
                        version_verified=bool(result.get('version_verified')))

    def portal_snapshot(self):
        with self.lock:
            records = copy.deepcopy(list(self.portal_requests.values()))
            for item in records:
                item.pop('_received_tick', None)
            return records

    def start(self, run_id, requests):
        with self.lock:
            self.runs[run_id] = {item['request_id']: {'request_id': item['request_id'],
                'roll': item['roll'], 'server_received_at': None, 'server_admitted_at': None,
                'server_finished_at': None, 'tcp_peer': None, 'server_wait_ms': None,
                'events': []} for item in requests}
            self.watched.update({item['request_id']: run_id for item in requests})
            while len(self.runs) > 4:
                _, removed = self.runs.popitem(last=False)
                for request_id in removed:
                    self.watched.pop(request_id, None)

    def record(self, request_id, roll, phase, peer=None):
        with self.lock:
            run_id = self.watched.get(request_id)
            item = (self.runs[run_id][request_id] if run_id
                    else self.portal_requests.get(request_id))
            if item is None:
                return
            if item['roll'] != roll:
                return
            now, tick = utc_now(), time.monotonic()
            if phase == 'TCP_RECEIVED':
                item['server_received_at'] = now
                item['_received_tick'] = tick
                item['tcp_peer'] = f'{peer[0]}:{peer[1]}'
            elif phase == 'TCP_ADMITTED':
                item['server_admitted_at'] = now
                item['server_wait_ms'] = round((tick-item['_received_tick'])*1000, 2)
            elif phase == 'TCP_CLOSED':
                item['server_finished_at'] = now
            else:
                return
            self.sequence += 1
            event = {'sequence': self.sequence, 'time': now, 'event': phase,
                     'run_id': run_id, 'instance_id': self.instance_id,
                     'request_id': request_id, 'roll': roll, 'tcp_peer': item['tcp_peer']}
            item['events'].append(event)
            # This trace is written by the TCP handler, independently of the browser UI.
            try:
                print('CN_EVIDENCE ' + json.dumps(event, separators=(',', ':')), flush=True)
            except (OSError, ValueError):
                pass  # A log sink failure must not interrupt TCP service.

    def snapshot(self, run_id):
        with self.lock:
            records = copy.deepcopy(self.runs.get(run_id, {}))
            for item in records.values():
                item.pop('_received_tick', None)
            return records

    def admitted(self, run_id, request_id):
        with self.lock:
            return bool(self.runs.get(run_id, {}).get(request_id, {}).get('server_admitted_at'))
