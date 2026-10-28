# PairVPN 代理池结论：0 节点，不入池

**结论：`complete`（分析完成） / 代理池产出 = 0**

---

## 1. 为什么是 0

| 判据 | 观测 | 结论 |
| --- | --- | --- |
| UI 有没有服务器列表？ | 客户端面板只有 `Select Server (New Server)` 一个入口（`shots/14_client.png`、`s2.xml`） | 无 |
| 有没有内置节点配置？ | `assets/` 无 config/json 节点文件；`res/raw` 只有 Firebase keep 规则 | 无 |
| 有没有下发节点列表的 API？ | 地址服务器仅 3 个 action：`client_pairing` / `server_pairing` / `remove_pairing`，响应固定 64 字符令牌，**无列表结构** | 无 |
| 出口 IP 是谁的？ | `session_cli_ice_server_address` = **服务端设备自己注册的**地址；隧道内 `Server: 192.128.11.1` 是用户自己的机器 | 用户设备 |
| 有没有可匿名复用的凭证？ | Firebase RTDB 401；配对码 10 分钟过期且由服务端设备本人显示；单服务端限 10 客户端 | 无 |

PairVPN 的产品定位是「把你 PC 的网络共享给手机」（官网 pairvpn.com），服务端永远是用户自己的设备。
**它不是机场，收割不到任何第三方出口 IP。**

---

## 2. 与已入池项目的对比

| 项目 | 节点来源 | 可入池 | 本次 PairVPN |
| --- | --- | --- | --- |
| SuperVPN Pro | hysteria2 配置下发 | ✅ 73 节点全活 | — |
| ZeroPing VPN | 双层加密节点表 | ✅ 139 节点 | — |
| Russia VPN | 白标 SaaS 零鉴权 API | ✅ 1167 条 | — |
| Indonesia VPN | 配置下发 | ✅ 664 存 / 342 唯一出口 | — |
| VPN Super | AES 配置 + 1199 节点 | ✅（协议面待抓包） | — |
| VIP / 商业机场类 | 服务器列表 API | ✅ | — |
| **PairVPN** | **无（P2P 配对）** | **❌** | ✅ 就是这个 |

⇒ 你的池子已经有 3000+ 节点，PairVPN 提供不了增量，**不建议花时间做对接**。

---

## 3. 唯一能"用上"的姿势（不是池）

PairVPN 的 `Run as VPN Server` 能把**任何一台安卓设备**变成出口节点，客户端是标准 `VpnService` tun。
如果目标不是「拉池」而是「要一个固定 IP 的私有出口」，可以：

1. 一台常开安卓机（或模拟器）跑 Server 模式；
2. 从你的 new-api 侧按配对协议（`client_pairing` → 令牌 → ICE/中继握手）接入；
3. 出口 IP = 该设备所在网络的公网 IP。

**但这不满足「长久稳定代理池」**：单设备单 IP、需要人工配对、断网即失效、性能受设备和家庭宽带上行限制。
如果确实需要私有固定出口，**自建 VPS + xray/socks5 是更省事、更稳定的方案**，没必要绕 PairVPN。

---

## 4. 需要你拍板的（下一步）

- **A（建议）**：PairVPN 到此为止，不做对接，资源投到已有的 hysteria2 / ZeroPing / Russia 池的存活率维护上。
- **B**：如果你就是想要「私有固定 IP 出口」，我直接给 new-api 出一份 VPS + xray 单节点方案（含订阅链接格式），成本与维护都远低于 PairVPN 路线。
- **C**：如果你仍想验证 PairVPN 端到端（拿到真实 6 位码 + 打通隧道），需要再给一台可控设备/模拟器（当前那台被 mod 推广壳 + `system_server` 崩溃拖住了），我按 `docs/逆向报告.md` §7 的三项待验证项继续。

---

## 5. 已交付物

```
PairVPN_1.8.51/
├─ docs/逆向报告.md          完整逆向报告（架构 / 协议 / 数据面 / 复现方式）
├─ docs/NEWAPI_INTEGRATION.md ★ 交接包：给「对接会话」的 10 节对接文档
├─ POOL_VERDICT.md           本文件
├─ tools/find_url_refs.py    ARM64 ADRP+ADD 交叉引用扫描器（定位 pairv.net 常量用）
├─ tools/probe_addrserver.py 线上探活 + 低并发压测（实测 24/24 成功，P50 1855ms）
├─ tools/mock_addrserver.py  离线协议 mock（三 action + 64 字符令牌语义）
├─ tools/health_loop.py      ★ 代理清单健康检查器（四要素，可在任何 SOCKS5/HTTP 池复用）
├─ tools/socks5_testserver.py health_loop 测试夹具
├─ demo/server.py            demo 后端 :8912（实测三接口全通）
├─ demo/index.html           demo 页面（探活 / 配对复现 / 压测）
├─ shots/                    模拟器实测截图
└─ raw/ apktool_out/ jadx_out/ strings_native.txt   解包与反编译产物
```
