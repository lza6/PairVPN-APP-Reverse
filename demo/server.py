#!/usr/bin/env python3
"""PairVPN 逆向 demo 服务

  GET  /                  demo 页面
  POST /api/probe         实测 pairv.net 三个 action（只读 GET）
  POST /api/bench         低并发压测（n<=40, c<=6）
  POST /api/pair/new      本地生成 6 位配对码并"注册服务端"
  POST /api/pair/client   本地模拟客户端凭码取会话令牌
  GET  /api/state         本地配对表状态
"""
import json
import random
import statistics
import string
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
REAL = "https://pairv.net/dev/{action}?{q}"
ALPHABET = string.ascii_letters + string.digits + "-_."
TOKEN_LEN = 64

ACTIONS_Q = {
    "client_pairing": "rand={rand}&ver=1851&os=android&osver=30&code={code}",
    "server_pairing": "iceId={rand}&pairCode={code}&flags=1&svrName=demo&hwId=demo",
    "remove_pairing": "rand={rand}&ver=1851&os=android&osver=30&code={code}",
}

PAIRS = {}  # code -> dict


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_token():
    return "".join(random.choice(ALPHABET) for _ in range(TOKEN_LEN))


def call_real(action, code, timeout=12.0):
    q = ACTIONS_Q[action].format(rand=random.randint(1, 10 ** 6), code=code)
    url = REAL.format(action=action, q=q)
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PairVPN/1851 (demo)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace").strip()
            status = r.status
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "ms": round((time.perf_counter() - t0) * 1000, 1), "err": "HTTPError"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": 0, "ms": round((time.perf_counter() - t0) * 1000, 1), "err": type(e).__name__}
    return {
        "ok": status == 200 and bool(body),
        "status": status,
        "ms": round((time.perf_counter() - t0) * 1000, 1),
        "len": len(body),
        "token": body,
        "url": url,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _file(self, path: Path, ctype):
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self._file(HERE / "index.html", "text/html; charset=utf-8")
        if u.path == "/api/state":
            return self._json(200, {"pairs": list(PAIRS.values()), "at": now()})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad json"})

        if u.path == "/api/probe":
            code = str(body.get("code") or "123456")
            return self._json(200, {"results": {a: call_real(a, code) for a in ACTIONS_Q}})

        if u.path == "/api/bench":
            action = body.get("action") or "client_pairing"
            if action not in ACTIONS_Q:
                return self._json(400, {"error": "bad action"})
            n_req = max(1, min(40, int(body.get("n") or 12)))
            conc = max(1, min(6, int(body.get("c") or 4)))
            t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=conc) as ex:
                res = list(ex.map(lambda _: call_real(action, str(body.get("code") or "123456")), range(n_req)))
            wall = time.perf_counter() - t0
            ok = [r for r in res if r["ok"]]
            lat = sorted(r["ms"] for r in ok)

            def pct(p):
                if not lat:
                    return None
                k = max(0, min(len(lat) - 1, int(round(p / 100 * len(lat) + 0.5)) - 1))
                return lat[k]

            return self._json(
                200,
                {
                    "action": action,
                    "requests": n_req,
                    "concurrency": conc,
                    "wall_s": round(wall, 2),
                    "success": len(ok),
                    "success_rate": round(len(ok) / n_req * 100, 1),
                    "rps": round(n_req / wall, 2) if wall else None,
                    "p50_ms": pct(50),
                    "p95_ms": pct(95),
                    "max_ms": lat[-1] if lat else None,
                    "errors": sorted({r.get("err") or f"http{r.get('status')}" for r in res if not r["ok"]}),
                },
            )

        if u.path == "/api/pair/new":
            code = f"{random.randint(0, 999999):06d}"
            PAIRS[code] = {
                "pairCode": code,
                "token": new_token(),
                "svrName": str(body.get("svrName") or "pvhost"),
                "permission": str(body.get("permission") or "all"),
                "createdAt": now(),
            }
            return self._json(200, PAIRS[code])

        if u.path == "/api/pair/client":
            code = str(body.get("code") or "")
            rec = PAIRS.get(code)
            if rec:
                # 已注册：客户端拿到服务端会话令牌（真实协议里再用于 ICE/中继握手）
                return self._json(200, {"registered": True, "pairCode": code, "token": rec["token"], "svrName": rec["svrName"]})
            # 未注册：线上实测返回等价随机令牌，不报错
            return self._json(200, {"registered": False, "pairCode": code, "token": new_token()})

        return self._json(404, {"error": "not found"})

    def log_message(self, fmt, *a):
        print(f"{now()} {fmt % a}", flush=True)


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8912)
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"PairVPN demo on http://{a.host}:{a.port}/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
