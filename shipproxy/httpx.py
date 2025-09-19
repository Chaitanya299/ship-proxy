from typing import Dict, List

# Hop-by-hop headers per RFC 7230 section 6.1
HOP_BY_HOP = {
    "connection",
    "proxy-connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def copy_headers(dst: Dict[str, List[str]], src: Dict[str, List[str]]):
    for k, vv in src.items():
        if k.lower() in HOP_BY_HOP:
            continue
        for v in vv:
            dst.setdefault(k, []).append(v)
