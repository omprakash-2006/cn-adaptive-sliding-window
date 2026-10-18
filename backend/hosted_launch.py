"""HTTP hosting entry point for the actual framed TCP admission server."""
import argparse
import json
import os
from pathlib import Path
import socket
import threading
import time
import urllib.parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '10000')))
    parser.add_argument('--tcp-port', type=int, default=int(os.environ.get('CN_TCP_PORT', '65434')))
    args = parser.parse_args()
    database = Path(os.environ.get('CN_PUBLICATION_DB', str(Path(__file__).parent / 'publications.sqlite3')))
    database.parent.mkdir(parents=True, exist_ok=True)
    os.environ['CN_PUBLICATION_DB'] = str(database)

    import web_portal
    from public_access import STUDENT_PATHS
    from cloud_demo import CloudDemo
    web_portal.DEMO_ENABLED = False
    web_portal.TCP_SERVER_PORT = args.tcp_port
    web_portal.WEB_PORT = args.port
    web_portal.server.SERVER_HOST = '127.0.0.1'
    worker = threading.Thread(target=web_portal.server.start_server,
                              kwargs={'mode': 'adaptive', 'port': args.tcp_port, 'window_size': 10},
                              daemon=True)
    worker.start()
    for _ in range(100):
        if not worker.is_alive():
            raise RuntimeError('The TCP admission server could not start.')
        try:
            with socket.create_connection(('127.0.0.1', args.tcp_port), timeout=.1):
                break
        except OSError:
            time.sleep(.05)
    else:
        raise RuntimeError('The TCP admission server did not become ready.')

    demo = CloudDemo(web_portal.server, web_portal.client, args.tcp_port)

    class StudentHandler(web_portal.PortalHTTPHandler):
        def do_GET(self):
            if demo.handle(self):
                return
            route = urllib.parse.urlsplit(self.path).path
            if route == '/healthz':
                healthy = worker.is_alive()
                try:
                    healthy = healthy and bool(web_portal.server.PUBLICATIONS.snapshot('24BAD001'))
                except Exception:
                    healthy = False
                self._json({'status': 'ready' if healthy else 'unavailable'}, 200 if healthy else 503)
                return
            if route not in STUDENT_PATHS:
                self.send_error(404, 'Student page not found')
                return
            super().do_GET()

        def do_POST(self):
            if demo.handle(self):
                return
            self.send_error(405, 'Student portal accepts GET requests only')

    web_portal.ThreadingHTTPServer.request_queue_size = 256
    with web_portal.ThreadingHTTPServer((args.host, args.port), StudentHandler) as httpd:
        print(f'Hosted student portal ready on {args.host}:{args.port}; TCP stays on loopback.', flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
