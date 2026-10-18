"""Start a preview accessible only from this computer, alongside the original portal."""
import argparse
import threading
import time
import web_portal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8081)
    parser.add_argument('--tcp-port', type=int, default=65433)
    parser.add_argument('--demo', action='store_true', help='Enable the separate localhost correction lab')
    args = parser.parse_args()
    web_portal.DEMO_ENABLED = args.demo
    web_portal.WEB_PORT = args.port
    web_portal.TCP_SERVER_PORT = args.tcp_port
    web_portal.server.SERVER_HOST = '127.0.0.1'
    with web_portal.ThreadingHTTPServer(('127.0.0.1', args.port), web_portal.PortalHTTPHandler) as httpd:
        threading.Thread(target=web_portal.server.start_server,
                         kwargs={'mode': 'adaptive', 'port': args.tcp_port, 'window_size': 10},
                         daemon=True).start()
        time.sleep(0.5)
        print(f'\nCollege portal preview: http://127.0.0.1:{args.port}\nPress Ctrl+C to stop.\n', flush=True)
        if args.demo:
            print(f'Local correction lab: http://127.0.0.1:{args.port}/demo\n', flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\nPreview stopped.')


if __name__ == '__main__':
    main()
