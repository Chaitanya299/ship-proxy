import argparse
import io
import socket
import threading
import time
from typing import Dict, List, Optional

import requests

from . import proto
from .httpx import copy_headers, HOP_BY_HOP

# Use a single Requests session. Disable env proxies to avoid accidental
# re-proxying, and set a simple User-Agent for friendlier upstreams.
session = requests.Session()
session.trust_env = False  # do not honor HTTP(S)_PROXY env vars
session.headers.update({
    # Use a browser-like UA to avoid CDN/anti-bot 503s on some endpoints
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})


class OffshoreServer:
    def __init__(self, listen_host: str, listen_port: int):
        self.listen_host = listen_host
        self.listen_port = listen_port

    def serve(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.listen_host, self.listen_port))
            s.listen(1)
            print(f"Offshore proxy server listening on {self.listen_host}:{self.listen_port}")
            while True:
                conn, addr = s.accept()
                print(f"Client connected from {addr}")
                t = threading.Thread(target=self.handle_client, args=(conn,), daemon=True)
                t.start()

    def handle_client(self, sock: socket.socket):
        with sock:
            r = sock.makefile('rb')
            w = sock.makefile('wb')
            try:
                while True:
                    t, payload = proto.read_frame(r)
                    if t == proto.TypeRequestStart:
                        self.handle_http(r, w, payload)
                    elif t == proto.TypeConnectOpen:
                        self.handle_connect(r, w, payload)
                    else:
                        raise RuntimeError(f"unexpected frame type: {t}")
            except EOFError:
                return
            except Exception as e:
                print(f"[SERVER] error: {e}")
                return

    def handle_http(self, r: io.BufferedReader, w: io.BufferedWriter, start_payload: bytes):
        rs = proto.decode_json(start_payload)
        method: str = rs.get('method', 'GET')
        absolute_url: str = rs.get('absolute_url')
        headers_in: Dict[str, List[str]] = rs.get('header', {})

        # Build outgoing headers (exclude hop-by-hop)
        out_headers: Dict[str, str] = {}
        tmp: Dict[str, List[str]] = {}
        copy_headers(tmp, headers_in)
        # Let requests set Host from URL to avoid mismatches
        tmp.pop('Host', None)
        for k, vv in tmp.items():
            if not vv:
                continue
            out_headers[k] = ", ".join(vv)

        # Determine if we can buffer the request body (to send Content-Length)
        content_length: Optional[int] = None
        cl_vals = headers_in.get('Content-Length') or headers_in.get('content-length')
        if cl_vals:
            try:
                content_length = int(cl_vals[0])
            except Exception:
                content_length = None

        MAX_BUFFER = 10 * 1024 * 1024  # 10 MB safety cap

        def read_body_frames_to_end() -> bytes:
            buf = bytearray()
            while True:
                t, payload = proto.read_frame(r)
                if t == proto.TypeRequestBodyChunk:
                    if payload:
                        buf.extend(payload)
                        # Keep reading until RequestEnd to maintain framing alignment
                elif t == proto.TypeRequestEnd:
                    return bytes(buf)
                else:
                    raise RuntimeError(f"unexpected frame in request body: {t}")

        # Streaming request body generator (used if no/large Content-Length)
        def body_iter():
            while True:
                t, payload = proto.read_frame(r)
                if t == proto.TypeRequestBodyChunk:
                    if payload:
                        yield payload
                elif t == proto.TypeRequestEnd:
                    return
                else:
                    raise RuntimeError(f"unexpected frame in request body: {t}")

        try:
            # Make request upstream
            if content_length is not None and content_length <= MAX_BUFFER:
                body_bytes = read_body_frames_to_end()
                resp = session.request(
                    method=method,
                    url=absolute_url,
                    headers=out_headers,
                    data=body_bytes,
                    stream=True,
                    allow_redirects=False,
                    timeout=30,
                )
            else:
                resp = session.request(
                    method=method,
                    url=absolute_url,
                    headers=out_headers,
                    data=body_iter(),
                    stream=True,
                    allow_redirects=False,
                    timeout=30,
                )
        except Exception as e:
            # Send 502 response back
            proto.write_json_frame(w, proto.TypeResponseStart, {
                'status_code': 502,
                'status': 'Bad Gateway',
                'header': {'Content-Type': ['text/plain']},
            })
            proto.write_frame(w, proto.TypeResponseBodyChunk, f"Bad Gateway: {e}".encode('utf-8'))
            proto.write_frame(w, proto.TypeResponseEnd, b'')
            return

        try:
            # Prepare response headers excluding hop-by-hop
            res_hdr_dict: Dict[str, List[str]] = {}
            for k, v in resp.headers.items():
                if k.lower() in HOP_BY_HOP:
                    continue
                res_hdr_dict.setdefault(k, []).append(v)

            proto.write_json_frame(w, proto.TypeResponseStart, {
                'status_code': int(resp.status_code),
                'status': resp.reason or '',
                'header': res_hdr_dict,
            })

            for chunk in resp.iter_content(chunk_size=32 * 1024):
                if chunk:
                    proto.write_frame(w, proto.TypeResponseBodyChunk, chunk)
            proto.write_frame(w, proto.TypeResponseEnd, b'')
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def handle_connect(self, r: io.BufferedReader, w: io.BufferedWriter, payload: bytes):
        obj = proto.decode_json(payload)
        host = obj.get('host')
        print(f"[SERVER] CONNECT request to {host}")
        try:
            if ':' in host:
                h, ps = host.split(':', 1)
                print(f"[SERVER] Connecting to {h}:{ps}")
                remote = socket.create_connection((h, int(ps)), timeout=15)
            else:
                print(f"[SERVER] Connecting to {host}:443")
                remote = socket.create_connection((host, 443), timeout=15)
            print(f"[SERVER] Successfully connected to {host}")
        except Exception as e:
            print(f"[SERVER] Failed to connect to {host}: {e}")
            proto.write_json_frame(w, proto.TypeConnectOpenResult, {'ok': False, 'error': str(e)})
            return

        proto.write_json_frame(w, proto.TypeConnectOpenResult, {'ok': True})

        # Start S2C reader thread
        done_s2c = threading.Event()
        def s2c():
            try:
                while True:
                    data = remote.recv(32 * 1024)
                    if data:
                        proto.write_frame(w, proto.TypeConnectDataS2C, data)
                    else:
                        proto.write_frame(w, proto.TypeConnectClose, b'')
                        done_s2c.set()
                        return
            except Exception:
                try:
                    proto.write_frame(w, proto.TypeConnectClose, b'')
                except Exception:
                    pass
                done_s2c.set()

        th = threading.Thread(target=s2c, daemon=True)
        th.start()

        # Read frames C2S and write to remote
        try:
            while True:
                t, payload = proto.read_frame(r)
                if t == proto.TypeConnectDataC2S:
                    if payload:
                        remote.sendall(payload)
                elif t == proto.TypeConnectClose:
                    remote.shutdown(socket.SHUT_WR)
                    break
                else:
                    raise RuntimeError(f"unexpected frame in CONNECT: {t}")
        finally:
            done_s2c.wait(timeout=10)
            try:
                remote.close()
            except Exception:
                pass


def main():
    p = argparse.ArgumentParser(description='Offshore proxy server')
    p.add_argument('--listen', default=':9090', help='listen address, default :9090')
    args = p.parse_args()

    if args.listen.startswith(':'):
        host = '0.0.0.0'
        port = int(args.listen[1:])
    else:
        host, ps = args.listen.split(':', 1)
        port = int(ps)

    srv = OffshoreServer(host, port)
    srv.serve()


if __name__ == '__main__':
    main()
