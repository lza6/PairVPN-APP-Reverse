"""手写 ARM64 ADRP+ADD/LDR 扫描器（capstone 在本机不可用）。
定位引用指定只读字符串的函数，并列出该函数引用的所有其它字符串，
用于还原 https://%s/dev/%s?%s 的 host / path 常量来源。
"""
import sys
import struct

SO = "raw/lib/arm64-v8a/libnative-lib.so"
raw = open(SO, "rb").read()

# 只读段：整个镜像 file_offset==vaddr（PIE 常见），先用 ELF program headers 粗略切分
import lief
bin_ = lief.parse(SO)
segs = [(s.virtual_address, s.file_offset, s.virtual_size, str(s.flags)) for s in bin_.segments]
xseg = [s for s in segs if "X" in s[3]][0]

def va_to_off(va):
    for vaddr, off, size, _ in segs:
        if vaddr <= va < vaddr + size:
            return off + (va - vaddr)
    return None

def cstr(va, maxn=220):
    off = va_to_off(va)
    if off is None or off >= len(raw):
        return None
    end = raw.find(b"\x00", off, off + maxn)
    if end < 0:
        return None
    try:
        return raw[off:end].decode("utf-8")
    except UnicodeDecodeError:
        return None

TARGETS = sys.argv[1:] or ["https://%s/dev/%s?%s"]
tvas = {}
for t in TARGETS:
    needle = t.encode() + b"\x00"
    pos = raw.find(needle)
    while pos >= 0:
        va = None
        for vaddr, off, size, _ in segs:
            if off <= pos < off + size:
                va = vaddr + (pos - off)
        if va is not None:
            tvas.setdefault(t, []).append(va)
        pos = raw.find(needle, pos + 1)

print("target VAs:", {k: [hex(x) for x in v] for k, v in tvas.items()})

# 扫描整个可执行段
base, off0, size0, _ = xseg
code = raw[off0:off0 + size0]
refs = []  # (insn_va, target_va, kind)
adrp = {}  # reg -> page
n = len(code) // 4
for i in range(n):
    w = struct.unpack_from("<I", code, i * 4)[0]
    pc = base + i * 4
    if (w & 0x9F000000) == 0x90000000:          # ADRP
        immlo = (w >> 29) & 3
        immhi = (w >> 5) & 0x7FFFF
        imm = (immhi << 2) | immlo
        if imm & (1 << 20):
            imm -= (1 << 21)
        page = ((pc & ~0xFFF) + (imm << 12)) & 0xFFFFFFFFFFFF
        adrp[w & 0x1F] = page
    elif (w & 0xFF800000) == 0x91000000:        # ADD (imm, 64-bit)
        rn = (w >> 5) & 0x1F
        if rn in adrp:
            sh = (w >> 22) & 1
            imm12 = (w >> 10) & 0xFFF
            if sh:
                imm12 <<= 12
            refs.append((pc, adrp[rn] + imm12, "add"))
    elif (w & 0xFFC00000) == 0xF9400000:        # LDR (imm, 64-bit unsigned)
        rn = (w >> 5) & 0x1F
        if rn in adrp:
            imm12 = ((w >> 10) & 0xFFF) * 8
            refs.append((pc, adrp[rn] + imm12, "ldr"))

print("refs:", len(refs))

for t, vas in tvas.items():
    for tv in vas:
        hits = [a for a, v, k in refs if v == tv]
        print(f"\n=== {t} @ {hex(tv)}  引用点: {[hex(h) for h in hits]}")
        for h in hits:
            print(f"\n--- 引用点 {hex(h)} 前后 0x400 字节范围内的其它字符串引用:")
            lo, hi = h - 0x600, h + 0x600
            seen = set()
            for a, v, k in refs:
                if lo <= a <= hi:
                    s = cstr(v)
                    if s and len(s) >= 3 and s not in seen:
                        seen.add(s)
                        mark = " <== TARGET" if v == tv else ""
                        print(f"   {hex(a)} {k} -> {s!r}{mark}")
