"""Share the student portal through a temporary HTTPS tunnel.

The forwarding gateway exposes student routes only. The local correction lab
cannot be reached through the public tunnel.
"""
import argparse
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
STUDENT_PATHS = frozenset({
    '/', '/index.html', '/result', '/api/query_start', '/api/query_poll', '/api/query',
    '/college-background.jpg', '/college-logo.gif', '/poppins-400.ttf',
    '/poppins-500.ttf', '/poppins-700.ttf', '/mepco_crest.png',
    '/mepco_campus.jpg', '/mepco_entrance.jpg',
})
VERSION = '2026.10.0'
MAC_ARM_ARCHIVE_HASH = 'a2f79ff7b9420aa537d74af239f376da170bbabeb529aec416002adac6a72e70'


def cloudflared_binary(explicit=None):
    if explicit:
        candidate = Path(explicit).resolve()
        if not candidate.is_file():
            raise RuntimeError('The selected cloudflared executable does not exist.')
        return str(candidate)
    installed = shutil.which('cloudflared')
    if installed:
        return installed
    binary = ROOT / '.tools' / 'cloudflared'
    if binary.is_file():
        return str(binary)
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('Install cloudflared for this computer, then run this launcher again.')
    print('Downloading the official Cloudflare connector for this Mac...', flush=True)
    url = f'https://github.com/cloudflare/cloudflared/releases/download/{VERSION}/cloudflared-darwin-arm64.tgz'
    binary.parent.mkdir(exist_ok=True)
    archive = binary.parent / 'cloudflared.tgz'
    urllib.request.urlretrieve(url, archive)
    try:
        if hashlib.sha256(archive.read_bytes()).hexdigest() != MAC_ARM_ARCHIVE_HASH:
            raise RuntimeError('Cloudflare download checksum did not match.')
        with tarfile.open(archive) as bundle:
            member = bundle.getmember('cloudflared')
            if not member.isfile():
                raise RuntimeError('Cloudflare archive has no executable.')
            binary.write_bytes(bundle.extractfile(member).read())
        binary.chmod(0o755)
    finally:
        archive.unlink(missing_ok=True)
    return str(binary)


class StudentGateway(BaseHTTPRequestHandler):
    portal_port = 8082

    def do_GET(self):
        if urllib.parse.urlsplit(self.path).path not in STUDENT_PATHS:
            self.send_error(404, 'Student page not found')
            return
        connection = http.client.HTTPConnection('127.0.0.1', self.portal_port, timeout=20)
        try:
            connection.request('GET', self.path, headers={'Host': f'127.0.0.1:{self.portal_port}'})
            response = connection.getresponse()
            body = response.read()
            self.send_response(response.status)
            for name in ('Content-Type', 'Cache-Control'):
                value = response.getheader(name)
                if value:
                    self.send_header(name, value)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (OSError, http.client.HTTPException):
            self.send_error(502, 'Start the local project server, then reload.')
        finally:
            connection.close()

    def do_POST(self):
        self.send_error(405, 'Student gateway accepts GET requests only')

    def log_message(self, *_):
        pass


def portal_ready(port):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
    try:
        connection.request('GET', '/')
        response = connection.getresponse()
        body = response.read()
        return response.status == 200 and b'24BAD' in body and b'Mepco' in body
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portal-port', type=int, default=8082)
    parser.add_argument('--tcp-port', type=int, default=65434)
    parser.add_argument('--gateway-port', type=int, default=8090)
    parser.add_argument('--cloudflared')
    args = parser.parse_args()
    binary = cloudflared_binary(args.cloudflared)
    portal_process = None
    tunnel = None
    gateway = None
    serving = False
    published_address = None
    try:
        if not portal_ready(args.portal_port):
            portal_process = subprocess.Popen([
                sys.executable, '-u', str(ROOT / 'launch.py'),
                '--port', str(args.portal_port), '--tcp-port', str(args.tcp_port),
            ], cwd=str(ROOT))
            for _ in range(40):
                if portal_ready(args.portal_port):
                    break
                if portal_process.poll() is not None:
                    raise RuntimeError('The project server could not start. Check its port and error above.')
                time.sleep(0.25)
            else:
                raise RuntimeError('The project server did not become ready.')
        StudentGateway.portal_port = args.portal_port
        gateway = ThreadingHTTPServer(('127.0.0.1', args.gateway_port), StudentGateway)
        threading.Thread(target=gateway.serve_forever, daemon=True).start()
        serving = True
        tunnel = subprocess.Popen([
            binary, 'tunnel', '--no-autoupdate', '--protocol', 'http2',
            '--url', f'http://127.0.0.1:{args.gateway_port}',
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        print('\nConnecting the student portal to the public HTTPS link...', flush=True)
        for output in tunnel.stdout:
            match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', output)
            if match:
                address = match.group(0)
                (ROOT / '.public-link.txt').write_text(address + '\n', encoding='utf-8')
                published_address = address
                print(f'\nPUBLIC STUDENT LINK: {address}', flush=True)
                print('Share this link with phones and other computers using an internet connection.', flush=True)
                print('Keep this terminal, the Mac and its internet connection running.', flush=True)
                print('Restarting the tunnel creates a different public link. Ctrl+C stops sharing.\n', flush=True)
            elif 'ERR' in output or 'Registered tunnel connection' in output:
                print(output.rstrip(), flush=True)
        raise RuntimeError(f'The public connector stopped with exit code {tunnel.wait()}.')
    except KeyboardInterrupt:
        print('\nPublic sharing stopped.', flush=True)
    finally:
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait()
        if gateway:
            if serving:
                gateway.shutdown()
            gateway.server_close()
        if portal_process and portal_process.poll() is None:
            portal_process.terminate()
            portal_process.wait(timeout=5)
        link_file = ROOT / '.public-link.txt'
        if published_address and link_file.is_file():
            if link_file.read_text(encoding='utf-8').strip() == published_address:
                link_file.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError) as error:
        print(f'Unable to start public sharing: {error}', file=sys.stderr)
        sys.exit(1)
