#!/usr/bin/env python3
"""PairVPN 地址服务器本地 mock（离线协议复现）

还原 pairv.net/dev/<action> 的握手语义：
  GET /dev/server_pairing?iceId=&pairCode=&flags=&svrName=&hwId=
      -> 注册一个"服务端设备"，占住 pairCode，返回 64 字符会话令牌
  GET /dev/client_pairing?rand=&ver=&os=&osver=&code=
      -> 若 code 已注册，返回该会话令牌；未注册返回等价随机令牌（与真实服务器观测一致）
  GET /dev/remove_pairing?...
      -> 注销

令牌格式与线上实测一致：64 个字符，取自 [A-Za-z0-9-_.] 共 65 字符表（'.' 也是表内字符，
不是分隔符；线上响应里 '.' 位置随机即由此而来）。

真实服务器不校验未注册的 code，只回随机令牌 —— 这是本 mock 与线上一致的行为。
"""
import argparse
import json
import random
import string
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ALPHABET = string.ascii_letters + string.digits + "-_."
TOKEN_LEN = 64
LOCK = threading.Lock()
REGISTRY = {}  # pairCode -> {token, iceId, flags, svrName, hwId, at}


def new_token():
    return "".join(random.choice(ALPHABET) for _ in range(TOKEN_LEN))


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        raw = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [p for p in u.path.split("/") if p]
        action = parts[1] if len(parts) >= 2 and parts[0] == "dev" else None

        if u.path == "/" or u.path == "/health":
            with LOCK:
                body = json.dumps(
                    {"ok": True, "service": "pairvpn-mock-addrserver", "registered": len(REGISTRY), "at": now()},
                    ensure_ascii=False,
                )
            return self._send(200, body, "application/json; charset=utf-8")

        if action == "server_pairing":
            code = q.get("pairCode", "")
            with LOCK:
                tok = new_token()
                REGISTRY[code] = {
                    "token": tok,
                    "iceId": q.get("iceId", ""),
                    "flags": q.get("flags", ""),
                    "svrName": q.get("svrName", ""),
                    "hwId": q.get("hwId", ""),
                    "at": now(),
                }
            return self._send(200, "\n\n" + tok)

        if action == "client_pairing":
            code = q.get("code", "")
            with LOCK:
                rec = REGISTRY.get(code)
                tok = rec["token"] if rec else new_token()
            return self._send(200, "\n\n" + tok)

        if action == "remove_pairing":
            code = q.get("code", "")
            with LOCK:
                existed = REGISTRY.pop(code, None) is not None
            return self._send(200, "\n\n" + new_token() if not existed else "\n\n" + new_token())

        return self._send(404, "<h1>Not Found</h1>", "text/html; charset=utf-8")

    def log_message(self, fmt, *a):
        print("%s %s" % (now(), fmt % a), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8911)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"mock addrserver on http://{args.host}:{args.port}/dev/<action>", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
