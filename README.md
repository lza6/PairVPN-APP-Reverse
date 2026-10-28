# PairVPN 1.8.51 逆向 · 交付包

`com.pairvpn` v1.8.51 (versionCode 1851) — ElaMods 渠道包

## 一句话

**P2P 设备对设备 VPN，无服务器列表 ⇒ 可收割出口节点 = 0，不可入代理池。**
详见 [POOL_VERDICT.md](POOL_VERDICT.md)；完整技术细节见 [docs/逆向报告.md](docs/逆向报告.md)。

## 它是什么

- `Run as VPN Client` / `Run as VPN Server` 双模，两端都是**用户自己的设备**
- 业务内核在 `lib/arm64-v8a/libnative-lib.so`（C++，未 strip，符号完整）
- UI 是 `assets/html/main.html`（WebView），native 通过 `uiCallJS()` 注入状态
- 地址服务器 `https://pairv.net/dev/<action>`，只有会话发放，没有节点下发

## 已实测的事实

| 项 | 结果 |
| --- | --- |
| 地址服务器三端点 `client_pairing` / `server_pairing` / `remove_pairing` | 全部 200 |
| 响应格式 | `\n\n` + 64 字符不透明令牌，字符表 `[A-Za-z0-9-_.]`（`.` 是表内字符，不是分隔符） |
| 未注册配对码 | 不报错，照样返回随机令牌 |
| 压测 `-n 24 -c 4` | 24/24 成功，P50 1855 ms，P95 2871 ms，1.72 rps |
| Firebase `pairvpn-5fdd7` RTDB | 401 Permission denied（不可匿名枚举） |

## 快速开始

```bash
# 线上探活（只读 GET，低量）
python tools/probe_addrserver.py probe
python tools/probe_addrserver.py bench -n 24 -c 4

# demo 页面（真实探活 + 配对流程复现 + 压测）
python demo/server.py --port 8912
#   → http://127.0.0.1:8912/

# 纯离线协议 mock
python tools/mock_addrserver.py --port 8911

# 重新定位 host 常量（不依赖 capstone，自写 ARM64 扫描器）
python tools/find_url_refs.py "https://%s/dev/%s?%s"
python tools/find_url_refs.py "pairv.net"
```

## 目录

```
docs/逆向报告.md            架构 / 控制面协议 / 数据面 / 复现 / 待验证项
docs/NEWAPI_INTEGRATION.md  ★ 交接包：给「对接会话」的 10 节对接文档
docs/evidence-ui-clientscreen.xml  客户端面板 UI 元素树（无服务器列表的证据）
POOL_VERDICT.md             代理池结论与下一步选项
tools/find_url_refs.py      ARM64 ADRP+ADD 交叉引用扫描器
tools/probe_addrserver.py   探活 + 压测
tools/mock_addrserver.py    离线协议 mock
tools/health_loop.py        ★ 代理清单健康检查器（四要素齐全，可直接用于任何 SOCKS5/HTTP 池）
tools/socks5_testserver.py  health_loop 的测试夹具（最小 SOCKS5 服务端）
tools/analysis/             动态分析脚本（Frida hook / spawn 注入）
demo/server.py|index.html   demo
verify_demo.py              Playwright 浏览器验证脚本
shots/                      模拟器实测截图 + demo 截图
strings_native.txt          libnative-lib.so 全量可读字符串（7808 条）
```

## new-api 对接（一句话版）

**不要接成渠道** —— 没有节点。只有当需求是「私有固定 IP 出口」时才看
[docs/NEWAPI_INTEGRATION.md](docs/NEWAPI_INTEGRATION.md)，那里给了路线 B（自建 exit node）
和路线 C（VPS 直接替代，推荐），以及 new-api 侧唯一要改的 `TRYINGOPEN_PROXY_FILE`。

## 健康检查器独立可用

`tools/health_loop.py` 不依赖 PairVPN，任何 SOCKS5 / HTTP CONNECT 代理清单都能用：

```bash
python tools/health_loop.py --source pool.src.txt --target pool.txt --dry-run
python tools/health_loop.py --source pool.src.txt --target pool.txt   # 原子重写 + 状态文件
```

四要素：真实协议握手 / 出口 IP == 节点 IP / 双阈值（新节点首轮不过就不入池）/ `os.replace` 原子替换。

## 合规

`pairv.net` 是厂商自有基础设施。本包内的工具只做**只读 GET 探活/压测**，不写入、不遍历、不做破坏性操作。
PairVPN 不提供任何第三方出口，本项目不涉及他人流量或账号。
