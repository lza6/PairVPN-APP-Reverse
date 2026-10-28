"""真实浏览器验证 demo 页面（Playwright + Chromium）"""
import sys
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8912/"
SHOT = "shots/"

errors = []

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1180, "height": 1400})
    pg.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    pg.goto(URL, wait_until="networkidle")
    assert "PairVPN" in pg.title(), pg.title()
    print("[ok] 标题:", pg.title())
    print("[ok] 结论块:", pg.locator(".verdict").inner_text().replace("\n", " "))
    pg.screenshot(path=SHOT + "demo_01_initial.png", full_page=True)

    # 1) 真实地址服务器探活
    pg.click("#btnProbe")
    pg.wait_for_function("document.querySelectorAll('#probeTable tbody tr').length === 3", timeout=60000)
    rows = pg.locator("#probeTable tbody tr")
    print(f"[ok] 探活返回 {rows.count()} 行")
    for i in range(rows.count()):
        print("   ", rows.nth(i).inner_text().replace("\n", " | ")[:140])
    pg.screenshot(path=SHOT + "demo_02_probe.png", full_page=True)

    # 2) 配对流程复现
    pg.click("#btnNewSvr")
    pg.wait_for_function("document.getElementById('pairLog').textContent.includes('pairCode')", timeout=10000)
    log1 = pg.inner_text("#pairLog")
    print("[ok] 服务端注册:", [l for l in log1.split("\n") if "pairCode" in l][0][:120])

    pg.click("#btnCli")
    pg.wait_for_function("document.getElementById('pairLog').textContent.includes('令牌长度')", timeout=10000)
    log2 = pg.inner_text("#pairLog")
    tok_line = [l for l in log2.split("\n") if "令牌长度" in l][0]
    print("[ok] 客户端取会话:", tok_line.strip())
    assert "64 一致" in tok_line, tok_line

    pg.click("#btnCliBad")
    pg.wait_for_function("document.getElementById('pairLog').textContent.includes('未注册码')", timeout=10000)
    bad_line = [l for l in pg.inner_text("#pairLog").split("\n") if "令牌长度" in l][0].strip()
    print("[ok] 未注册码分支:", bad_line)
    assert "False" in bad_line or "false" in bad_line, bad_line
    pg.screenshot(path=SHOT + "demo_03_pairing.png", full_page=True)

    # 3) 压测
    pg.fill("#benchN", "8")
    pg.fill("#benchC", "4")
    pg.click("#btnBench")
    pg.wait_for_function("document.getElementById('benchOut').textContent.includes('success_rate')", timeout=90000)
    print("[ok] 压测:", pg.inner_text("#benchOut").replace("\n", " ")[:300])
    pg.screenshot(path=SHOT + "demo_04_bench.png", full_page=True)

    b.close()

if errors:
    print("[FAIL] 浏览器控制台错误:")
    for e in errors:
        print("   ", e)
    sys.exit(1)
print("[PASS] 无 console/page 错误，全部交互路径通过")
