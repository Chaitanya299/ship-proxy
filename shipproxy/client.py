import argparse
import io
import queue
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple

from . import proto
from .httpx import copy_headers


class SingleLink:
    def __init__(self, server_host: str, server_port: int):
        self.server_host = server_host
        self.server_port = server_port
        self._lock = threading.Lock()
        self.sock: Optional[socket.socket] = None
        self.r: Optional[io.BufferedReader] = None
        self.w: Optional[io.BufferedWriter] = None

    def ensure(self) -> None:
        with self._lock:
            if self.sock is not None:
                return
            last_err: Optional[Exception] = None
            for i in range(5):
                try:
                    sock = socket.create_connection((self.server_host, self.server_port), timeout=10)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    self.sock = sock
                    self.r = sock.makefile("rb")
                    self.w = sock.makefile("wb")
                    return
                except Exception as e:
                    last_err = e
                    time.sleep(0.2 * (2 ** i))
            raise RuntimeError(f"connect offshore failed: {last_err}")

    def reset(self) -> None:
        with self._lock:
            try:
                if self.r:
                    self.r.close()
                if self.w:
                    self.w.close()
                if self.sock:
                    self.sock.close()
            finally:
                self.sock = None
                self.r = None
                self.w = None


class RequestJob:
    def __init__(self, handler: BaseHTTPRequestHandler):
        self.handler = handler
        self.method = handler.command
        self.path = handler.path
        # Convert headers to dict[str, list[str]]
        hdr: Dict[str, List[str]] = {}
        for k in handler.headers.keys():
            vv = handler.headers.get_all(k) or []
            hdr[k] = vv
        self.headers = hdr
        self.body: bytes = b""
        if self.method not in ("GET", "HEAD", "CONNECT"):
            # Read fixed-length body if provided
            clen = handler.headers.get("Content-Length")
            if clen:
                try:
                    n = int(clen)
                    if n > 0:
                        self.body = handler.rfile.read(n)
                except Exception:
                    self.body = handler.rfile.read(0)
        self._done = threading.Event()
        self.error: Optional[Exception] = None

    def wait(self) -> Optional[Exception]:
        self._done.wait()
        return self.error

    def finish(self, err: Optional[Exception]) -> None:
        self.error = err
        self._done.set()


class ConnectJob:
    def __init__(self, handler: BaseHTTPRequestHandler):
        self.handler = handler
        self.hostport = handler.path  # host:port
        self._done = threading.Event()
        self.error: Optional[Exception] = None

    def wait(self) -> Optional[Exception]:
        self._done.wait()
        return self.error

    def finish(self, err: Optional[Exception]):
        self.error = err
        self._done.set()


class ProxyApp:
    def __init__(self, server_addr: Tuple[str, int]):
        self.link = SingleLink(*server_addr)
        self.queue: "queue.Queue[object]" = queue.Queue(maxsize=128)
        self.worker_th = threading.Thread(target=self._worker, daemon=True)
        self.worker_th.start()

    def enqueue(self, job):
        self.queue.put(job)

    def _worker(self):
        while True:
            job = self.queue.get()
            try:
                if isinstance(job, RequestJob):
                    self._process_http(job)
                elif isinstance(job, ConnectJob):
                    self._process_connect(job)
                else:
                    raise RuntimeError("unknown job type")
                job.finish(None)
            except Exception as e:
                job.finish(e)

    def _process_http(self, job: RequestJob):
        self.link.ensure()
        assert self.link.r and self.link.w

        # Prepare headers dictionary and strip hop-by-hop ones
        hdr: Dict[str, List[str]] = {}
        copy_headers(hdr, job.headers)

        abs_url = job.path
        if not abs_url.startswith("http://") and not abs_url.startswith("https://"):
            # Some clients may send relative; default to http://<host>
            abs_url = f"http://{job.handler.headers.get('Host')}{job.path}"

        # Send request start
        proto.write_json_frame(self.link.w, proto.TypeRequestStart, {
            "method": job.method,
            "absolute_url": abs_url,
            "header": hdr,
        })
        # Send body if any
        if job.body:
            # Chunk transfer to server side
            off = 0
            while off < len(job.body):
                chunk = job.body[off: off + 32 * 1024]
                proto.write_frame(self.link.w, proto.TypeRequestBodyChunk, chunk)
                off += len(chunk)
        proto.write_frame(self.link.w, proto.TypeRequestEnd, b"")

        # Read response start
        t, payload = proto.read_frame(self.link.r)
        if t != proto.TypeResponseStart:
            self.link.reset()
            raise RuntimeError(f"unexpected frame waiting response start: {t}")
        rs = proto.decode_json(payload)
        status_code = int(rs["status_code"]) if isinstance(rs.get("status_code"), int) else int(rs.get("status_code"))
        headers = rs.get("header", {})

        # Write response headers
        job.handler.send_response(status_code)
        for k, vv in headers.items():
            for v in vv:
                job.handler.send_header(k, v)
        job.handler.end_headers()
        # Stream body frames
        while True:
            t, payload = proto.read_frame(self.link.r)
            if t == proto.TypeResponseBodyChunk:
                if payload:
                    job.handler.wfile.write(payload)
                    job.handler.wfile.flush()
            elif t == proto.TypeResponseEnd:
                break
            else:
                self.link.reset()
                raise RuntimeError(f"unexpected frame in response: {t}")

    def _process_connect(self, job: ConnectJob):
        print(f"[CLIENT] CONNECT to {job.hostport}")
        self.link.ensure()
        assert self.link.r and self.link.w

        # Ensure host:port format is correct
        hostport = job.hostport
        if ':' not in hostport:
            hostport = f"{hostport}:443"  # Default HTTPS port
        
        print(f"[CLIENT] Asking offshore to connect to {hostport}")
        # Ask server to open connection
        proto.write_json_frame(self.link.w, proto.TypeConnectOpen, {"host": hostport})
        t, payload = proto.read_frame(self.link.r)
        if t != proto.TypeConnectOpenResult:
            self.link.reset()
            raise RuntimeError(f"unexpected frame waiting open result: {t}")
        res = proto.decode_json(payload)
        if not res.get("ok"):
            print(f"[CLIENT] Offshore connect failed: {res.get('error')}")
            raise RuntimeError(f"offshore connect failed: {res.get('error')}")
        
        print(f"[CLIENT] Offshore connected successfully to {hostport}")

        # Send 200 Connection Established to the browser and hijack raw socket
        client_sock = job.handler.connection  # type: ignore[attr-defined]
        client_w = job.handler.wfile
        client_w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        client_w.flush()

        done_s2c = threading.Event()
        err_holder = {"err": None}

        def s2c_reader():
            try:
                while True:
                    t, payload = proto.read_frame(self.link.r)
                    if t == proto.TypeConnectDataS2C:
                        if payload:
                            client_sock.sendall(payload)
                    elif t == proto.TypeConnectClose:
                        done_s2c.set()
                        return
                    else:
                        raise RuntimeError(f"unexpected frame in CONNECT S2C: {t}")
            except Exception as e:  # capture error
                err_holder["err"] = e
                done_s2c.set()

        th = threading.Thread(target=s2c_reader, daemon=True)
        th.start()

        try:
            while True:
                data = client_sock.recv(32 * 1024)
                if data:
                    proto.write_frame(self.link.w, proto.TypeConnectDataC2S, data)
                else:
                    # client closed
                    proto.write_frame(self.link.w, proto.TypeConnectClose, b"")
                    break
        finally:
            # Wait for server to signal close
            done_s2c.wait(timeout=10)
        if err_holder["err"]:
            raise err_holder["err"]


class ProxyHandler(BaseHTTPRequestHandler):
    server_version = "ShipProxy/py"
    protocol_version = "HTTP/1.1"

    def do_CONNECT(self):
        app: ProxyApp = self.server.app  # type: ignore[attr-defined]
        job = ConnectJob(self)
        app.enqueue(job)
        err = job.wait()
        if err:
            try:
                self.send_error(502, f"CONNECT failed: {err}")
            except Exception:
                pass

    def do_ANY(self):
        app: ProxyApp = self.server.app  # type: ignore[attr-defined]
        job = RequestJob(self)
        app.enqueue(job)
        err = job.wait()
        if err:
            self.send_error(502, f"Proxy error: {err}")

    def do_GET(self): self.do_ANY()
    def do_POST(self): self.do_ANY()
    def do_PUT(self): self.do_ANY()
    def do_DELETE(self): self.do_ANY()
    def do_HEAD(self): self.do_ANY()
    def do_OPTIONS(self): self.do_ANY()
    def do_PATCH(self): self.do_ANY()

    # Enable logging to see what's happening
    def log_message(self, fmt, *args):
        print(f"[CLIENT] {fmt % args}")


class ProxyHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, app: ProxyApp):
        super().__init__(server_address, RequestHandlerClass)
        self.app = app


def main():
    parser = argparse.ArgumentParser(description="Ship proxy client (sequential over single TCP)")
    parser.add_argument("--listen", default=":8080", help="listen address, default :8080")
    parser.add_argument("--server", default="127.0.0.1:9090", help="offshore server host:port")
    args = parser.parse_args()

    if args.listen.startswith(":"):
        host = "0.0.0.0"
        port = int(args.listen[1:])
    else:
        host, p = args.listen.split(":", 1)
        port = int(p)

    srv_host, srv_port_s = args.server.split(":", 1)
    srv_port = int(srv_port_s)

    app = ProxyApp((srv_host, srv_port))
    httpd = ProxyHTTPServer((host, port), ProxyHandler, app)
    print(f"Ship proxy listening on {host}:{port}, offshore={srv_host}:{srv_port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
