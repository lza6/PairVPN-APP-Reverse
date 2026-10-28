#!/usr/bin/env python3
"""PairVPN 地址服务器探针 / 压测

PairVPN 1.8.51 的"地址服务器"是 https://pairv.net/dev/<action>?<params>
已通过 libnative-lib.so 的字符串交叉引用确认：
    https://%s/dev/%s?%s   +   pairv.net

三个已确认 action:
    client_pairing   客户端凭 6 位配对码换取会话
    server_pairing   服务端注册自身 ICE 地址
    remove_pairing   删除配对

注意: pairv.net 是厂商自有基础设施，本工具只做只读 GET 探活/压测，
不写入、不遍历、不做破坏性操作。压测请保持低并发小样本。
"""
import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://pairv.net/dev/{action}"

ACTIONS = {
    # 客户端侧：rand / ver / os / osver / code 为必带参数
    "client_pairing": "rand={rand}&ver=1851&os=android&osver=30&code={code}",
    # 服务端侧：iceId / pairCode / flags / svrName / hwId
    "server_pairing": "iceId={rand}&pairCode={code}&flags=1&svrName=probe&hwId=probe",
    "remove_pairing": "rand={rand}&ver=1851&os=android&osver=30&code={code}",
}


def one(action, code, timeout):
    import random

    url = BASE.format(action=action) + "?" + ACTIONS[action].format(
        rand=random.randint(1, 10 ** 6), code=code
    )
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PairVPN/1851 (probe)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        body, status = b"", e.code
    except Exception as e:  # noqa: BLE001 - 探针需要吞掉所有网络异常
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000, "err": type(e).__name__, "status": 0, "len": 0}
    ms = (time.perf_counter() - t0) * 1000
    txt = body.decode("utf-8", "replace").strip()
    return {"ok": status == 200 and len(txt) > 0, "ms": ms, "status": status, "len": len(txt), "sample": txt}


def probe(args):
    for action in args.actions:
        r = one(action, args.code, args.timeout)
        print(json.dumps({"action": action, **r}, ensure_ascii=False))


def bench(args):
    results = []
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(one, args.action, args.code, args.timeout) for _ in range(args.n)]
        for f in futs:
            results.append(f.result())
    wall = time.perf_counter() - t0

    ok = [r for r in results if r["ok"]]
    lat = sorted(r["ms"] for r in ok)
    def pct(p):
        if not lat:
            return None
        k = max(0, min(len(lat) - 1, int(round((p / 100) * len(lat) + 0.5)) - 1))
        return round(lat[k], 1)

    lens = sorted({r.get("len", 0) for r in ok})
    summary = {
        "action": args.action,
        "requests": args.n,
        "concurrency": args.concurrency,
        "wall_s": round(wall, 2),
        "success": len(ok),
        "success_rate": round(len(ok) / args.n * 100, 1),
        "rps": round(args.n / wall, 2) if wall else None,
        "p50_ms": pct(50),
        "p95_ms": pct(95),
        "max_ms": round(lat[-1], 1) if lat else None,
        "resp_len_values": lens,
        "errors": sorted({r.get("err") or f"http{r.get('status')}" for r in results if not r["ok"]}),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="PairVPN 地址服务器探针/压测")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="单发探活三个 action")
    p.add_argument("--code", default="123456")
    p.add_argument("--timeout", type=float, default=12)
    p.add_argument("--actions", nargs="*", default=list(ACTIONS))
    p.set_defaults(func=probe)

    b = sub.add_parser("bench", help="低并发压测")
    b.add_argument("--action", default="client_pairing", choices=list(ACTIONS))
    b.add_argument("-n", type=int, default=24)
    b.add_argument("-c", "--concurrency", type=int, default=4)
    b.add_argument("--code", default="123456")
    b.add_argument("--timeout", type=float, default=12)
    b.set_defaults(func=bench)

    args = ap.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
