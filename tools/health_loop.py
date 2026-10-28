#!/usr/bin/env python3
"""代理清单健康检查器（new-api TRYINGOPEN_PROXY_FILE 专用）

为什么必须自带：new-api 的 TraceProbes() 只探 source=="free" 的条目
（proxy_pool.go:1180），而 TRYINGOPEN_PROXY_FILE 加载的条目 source 恒为
"residential" —— 死节点不会被摘除，会被反复选中。

四要素（少一个就是假实现）：
  1. 真实协议探测：SOCKS5/HTTP CONNECT 握手 + 经代理访问目标站
  2. 出口 IP 必须 == 节点 IP，不等则 exit_mismatch 摘除
  3. 双阈值：连续 N 轮失败才摘除；从未通过过的新节点首轮不入池
  4. os.replace 原子重写，避免 new-api 读到半个文件

用法：
  python tools/health_loop.py --source proxies/pool.src.txt --target proxies/pool.txt
  python tools/health_loop.py --source pool.src.txt --target pool.txt --dry-run

清单格式：每行一个 URL，# 开头为注释，尾部 #tag 作为来源标签
  socks5://user:pass@198.51.100.10:1080#vps-exit-01
  http://user:pass@203.0.113.7:3128#home-exit
"""
from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import socket
import ssl
import struct
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

TRACE_DEFAULT = "https://one.one.one.one/cdn-cgi/trace"
TIMEOUT = 8.0


# ---------------- 代理握手（手写，零第三方依赖） ----------------

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("peer closed")
        buf += chunk
    return buf


def sock_connect(host: str, port: int, timeout: float = TIMEOUT) -> socket.socket:
    return socket.create_connection((host, port), timeout=timeout)


def socks5_handshake(sock: socket.socket, host: str, port: int, user: str = "", pwd: str = "") -> None:
    """完成 SOCKS5 无认证/用户名密码认证 + CONNECT。"""
    if user or pwd:
        sock.sendall(b"\x05\x02\x00\x02")
    else:
        sock.sendall(b"\x05\x01\x00")
    ver, method = _recv_exact(sock, 2)
    if ver != 5:
        raise ConnectionError(f"socks5: bad ver {ver}")
    if method == 0x02:
        u, p = user.encode(), pwd.encode()
        sock.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        _, status = _recv_exact(sock, 2)
        if status != 0:
            raise ConnectionError("socks5: auth failed")
    elif method != 0x00:
        raise ConnectionError(f"socks5: no acceptable method ({method})")

    try:
        ip = ipaddress.ip_address(host)
        if ip.version == 4:
            addr = b"\x01" + ip.packed
        else:
            addr = b"\x04" + ip.packed
    except ValueError:
        hb = host.encode()
        addr = b"\x03" + bytes([len(hb)]) + hb
    sock.sendall(b"\x05\x01\x00" + addr + struct.pack(">H", port))
    _, rep, _, atyp = _recv_exact(sock, 4)
    if rep != 0:
        raise ConnectionError(f"socks5: connect rep={rep}")
    if atyp == 0x01:
        _recv_exact(sock, 4 + 2)
    elif atyp == 0x04:
        _recv_exact(sock, 16 + 2)
    else:
        ln = _recv_exact(sock, 1)[0]
        _recv_exact(sock, ln + 2)


def http_connect(sock: socket.socket, host: str, port: int, user: str = "", pwd: str = "") -> None:
    """HTTP 代理 CONNECT。"""
    req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
    if user or pwd:
        tok = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        req += f"Proxy-Authorization: Basic {tok}\r\n"
    req += "\r\n"
    sock.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("proxy closed during CONNECT")
        buf += chunk
    if b" 200" not in buf.split(b"\r\n")[0]:
        raise ConnectionError(f"CONNECT rejected: {buf.split(chr(13).encode() + chr(10).encode())[0]!r}")


def fetch_through(proxy: str, target: str = TRACE_DEFAULT) -> str:
    """经代理 GET target，返回响应正文。"""
    pu = urlparse(proxy)
    scheme = (pu.scheme or "").lower()
    phost, pport = pu.hostname, pu.port or (1080 if scheme.startswith("socks") else 8080)
    if not phost:
        raise ValueError("bad proxy url: no host")
    user, pwd = unquote(pu.username or ""), unquote(pu.password or "")
    tu = urlparse(target)
    thost, tport = tu.hostname, tu.port or 443

    sock = sock_connect(phost, pport)
    try:
        if scheme.startswith("socks5"):
            socks5_handshake(sock, thost, tport, user, pwd)
        elif scheme in ("http", "https"):
            http_connect(sock, thost, tport, user, pwd)
        else:
            raise ValueError(f"unsupported scheme: {scheme}")

        if tu.scheme == "https":
            ctx = ssl.create_default_context()
            tls = ctx.wrap_socket(sock, server_hostname=thost)
        else:
            tls = sock
        try:
            path = tu.path or "/"
            if tu.query:
                path += "?" + tu.query
            tls.sendall(
                f"GET {path} HTTP/1.1\r\nHost: {thost}\r\nUser-Agent: health-loop/1.0\r\n"
                f"Connection: close\r\n\r\n".encode()
            )
            data = b""
            while True:
                chunk = tls.recv(4096)
                if not chunk:
                    break
                data += chunk
                if len(data) > 65536:
                    break
        finally:
            try:
                tls.close()
            except OSError:
                pass
        head, _, body = data.partition(b"\r\n\r\n")
        if b" 200" not in head.split(b"\r\n")[0]:
            raise ConnectionError(f"http status: {head.split(b'\r\n')[0]!r}")
        return body.decode("utf-8", "replace")
    finally:
        try:
            sock.close()
        except OSError:
            pass


def exit_ip_of(proxy: str, target: str) -> str:
    body = fetch_through(proxy, target)
    for line in body.splitlines():
        if line.startswith("ip="):
            return line[3:].strip()
    raise ValueError("no ip= in trace response")


# ---------------- 清单读写 ----------------

def read_entries(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def write_atomic(path: Path, entries: list[str], header: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".pool-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(header) + "\n")
            f.write("\n".join(entries) + ("\n" if entries else ""))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)   # 原子替换
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


# ---------------- 主流程 ----------------

def main() -> int:
    ap = argparse.ArgumentParser(description="代理清单健康检查器")
    ap.add_argument("--source", required=True, help="候选清单（每行一个代理 URL）")
    ap.add_argument("--target", required=True, help="输出清单（new-api 读取）")
    ap.add_argument("--state", default="", help="状态文件（默认 <target>.state.json）")
    ap.add_argument("--trace", default=TRACE_DEFAULT, help="探测目标（与 new-api 一致）")
    ap.add_argument("--max-fail", type=int, default=3, help="连续失败多少轮摘除")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    src, dst = Path(a.source), Path(a.target)
    state_path = Path(a.state) if a.state else dst.with_suffix(dst.suffix + ".state.json")
    state = load_state(state_path)
    entries = read_entries(src)

    kept, dropped = [], []
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for proxy in entries:
        st = state.get(proxy) or {"fails": 0, "passes": 0}
        try:
            ip = exit_ip_of(proxy, a.trace)
            host = urlparse(proxy).hostname or ""
            # 出口 IP 必须等于节点 IP（防上游偷偷改中转）；host 为域名时跳过强校验
            try:
                same = ipaddress.ip_address(ip) == ipaddress.ip_address(host)
            except ValueError:
                same = True
            if not same:
                raise ValueError(f"exit_mismatch: exit={ip} node={host}")
            st["fails"] = 0
            st["passes"] = st.get("passes", 0) + 1
            st["last_ok"] = stamp
            st["exit_ip"] = ip
            kept.append(proxy)
        except Exception as e:  # noqa: BLE001 - 探活失败种类繁多，统一计数
            st["fails"] = st.get("fails", 0) + 1
            st["last_err"] = f"{type(e).__name__}: {e}"[:160]
            st["last_fail"] = stamp
            # 双阈值：从未通过过 → 首轮就不入池；通过过的 → 连续 max_fail 轮才摘
            if st.get("passes", 0) == 0 or st["fails"] >= a.max_fail:
                dropped.append((proxy, st["last_err"]))
            else:
                kept.append(proxy)
        state[proxy] = st

    header = [
        f"# auto-generated by health_loop.py at {stamp}",
        f"# kept={len(kept)} dropped={len(dropped)} source={src}",
    ]
    if a.dry_run:
        print(json.dumps({"kept": kept, "dropped": dropped, "dry_run": True}, ensure_ascii=False, indent=1))
        return 0

    write_atomic(dst, kept, header)
    save_state(state_path, state)
    print(f"[{stamp}] kept={len(kept)} dropped={len(dropped)} -> {dst}")
    for p, err in dropped:
        print(f"  DROP {p}  ({err})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
