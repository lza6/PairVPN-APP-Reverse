"""最小 SOCKS5 服务端，仅用于验证 health_loop.py 的握手实现（不用于生产）"""
import socket
import struct
import threading


def recv_exact(s, n):
    b = b""
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c:
            raise ConnectionError("closed")
        b += c
    return b


def handle(c):
    try:
        ver, nm = recv_exact(c, 2)
        methods = recv_exact(c, nm)
        if 2 in methods:
            c.sendall(b"\x05\x02")
            ver, ulen = recv_exact(c, 2)
            u = recv_exact(c, ulen).decode()
            plen = recv_exact(c, 1)[0]
            p = recv_exact(c, plen).decode()
            ok = (u, p) == ("user", "pass")
            c.sendall(b"\x01" + (b"\x00" if ok else b"\x01"))
            if not ok:
                return
        else:
            c.sendall(b"\x05\x00")
        ver, cmd, rsv, atyp = recv_exact(c, 4)
        if atyp == 1:
            host = socket.inet_ntoa(recv_exact(c, 4))
        elif atyp == 3:
            ln = recv_exact(c, 1)[0]
            host = recv_exact(c, ln).decode()
        else:
            host = socket.inet_ntop(socket.AF_INET6, recv_exact(c, 16))
        port = struct.unpack(">H", recv_exact(c, 2))[0]
        up = socket.create_connection((host, port), timeout=8)
        c.sendall(b"\x05\x00\x00\x01" + socket.inet_aton("0.0.0.0") + struct.pack(">H", 0))
        def pipe(a, b):
            try:
                while True:
                    d = a.recv(4096)
                    if not d:
                        break
                    b.sendall(d)
            except OSError:
                pass
            finally:
                for x in (a, b):
                    try:
                        x.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
        t = threading.Thread(target=pipe, args=(c, up), daemon=True)
        t.start()
        pipe(up, c)
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            c.close()
        except OSError:
            pass


srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 11080))
srv.listen(16)
print("test socks5 on 127.0.0.1:11080 (user/pass)", flush=True)
while True:
    conn, _ = srv.accept()
    threading.Thread(target=handle, args=(conn,), daemon=True).start()
