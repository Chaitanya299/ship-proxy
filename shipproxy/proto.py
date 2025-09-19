import io
import json
import struct
from typing import Tuple, Optional

# Frame types
TypeRequestStart = 1
TypeRequestBodyChunk = 2
TypeRequestEnd = 3

TypeResponseStart = 4
TypeResponseBodyChunk = 5
TypeResponseEnd = 6

TypeConnectOpen = 10
TypeConnectOpenResult = 11
TypeConnectDataC2S = 12
TypeConnectDataS2C = 13
TypeConnectClose = 14


def write_frame(w: io.BufferedWriter, t: int, payload: Optional[bytes]) -> None:
    if payload is None:
        payload = b""
    w.write(bytes([t]))
    w.write(struct.pack("!I", len(payload)))
    if payload:
        w.write(payload)
    w.flush()


def _read_exact(r: io.BufferedReader, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = r.read(n - len(buf))
        if not chunk:
            raise EOFError("unexpected EOF while reading frame")
        buf += chunk
    return buf


def read_frame(r: io.BufferedReader) -> Tuple[int, bytes]:
    t_b = _read_exact(r, 1)
    t = t_b[0]
    ln_b = _read_exact(r, 4)
    (ln,) = struct.unpack("!I", ln_b)
    payload = b""
    if ln:
        payload = _read_exact(r, ln)
    return t, payload


def encode_json(v) -> bytes:
    return json.dumps(v, separators=(",", ":")).encode("utf-8")


def decode_json(data: bytes):
    return json.loads(data.decode("utf-8"))


def write_json_frame(w: io.BufferedWriter, t: int, v) -> None:
    write_frame(w, t, encode_json(v))
