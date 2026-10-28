# PairVPN → new-api 对接文档（交接包）

> 写给「对接会话」：**你不需要读逆向报告也能完成本文档里的任何一步。**
> 本文档只覆盖 PairVPN 这一条链路；new-api 侧其它渠道不在范围内。

---

## 0. 边界声明（先读这一节，能省你两小时）

### 0.1 一句话前提

**PairVPN 不产出任何第三方出口节点。** 它是「设备对设备」P2P VPN，服务端跑在用户自己的手机/电脑上，
地址服务器 `pairv.net` 只发会话令牌、不发服务器列表。

⇒ **不存在"把 PairVPN 接成 OpenAI/API 代理渠道"这件事。** 你手上没有节点可填，`TRYINGOPEN_PROXY_FILE`
里写不出任何一条来自 PairVPN 的代理 URL。若你是被派来"接 PairVPN 渠道"的，**请先向上游确认需求**，
默认动作是：**不做**。

### 0.2 唯一可能要做的改动

只有当需求是「我要一个**私有固定 IP 出口**」时才有下文，路线是：

```
你自己的设备跑 PairVPN Server 模式  →  一个本机 bridge 把 tun 流量变成 SOCKS5
                                   →  写进 TRYINGOPEN_PROXY_FILE
                                   →  new-api 现有代理池机制（一行代码都不用改）
```

**new-api 侧不需要改任何业务代码**，唯一改动点是环境变量 `TRYINGOPEN_PROXY_FILE` 指向的文件内容。

### 0.3 谁负责存活

- **bridge 进程**（本项目范围外，需自建）负责 SOCKS5 可用性
- **健康检查器**负责把死条目从清单摘掉（见 §5，**不是可选项**）
- **new-api 不负责**住宅/自建代理的存活探测（源码事实见 §7.1）

### 0.4 合规

`pairv.net` 是厂商自有基础设施。本项目工具只做**只读 GET 探活/压测**，不写入、不遍历、不爆破配对码。
自建 Server 模式使用的是**你自己的设备与自己的网络**，不涉及他人流量、不涉及他人账号。

---

## 1. 现状

### 1.1 组件状态表

| 组件 | 状态 | 位置 | 说明 |
| --- | --- | --- | --- |
| 协议还原（控制面） | ✅ 完成 | `docs/逆向报告.md` §3 | 三端点 + 参数模板 + 令牌格式全部实测 |
| 线上地址服务器连通性 | ✅ 实测 | `tools/probe_addrserver.py` | 24/24 成功，P50 1855 ms |
| 协议复现 demo | ✅ 可用 | `demo/server.py` :8912 | Playwright 全路径验证通过 |
| 离线协议 mock | ✅ 可用 | `tools/mock_addrserver.py` :8911 | 三 action + 64 字符令牌语义 |
| 可收割节点 | ❌ **0 个** | — | 结构上不存在，见 §1.2 |
| tunnel → SOCKS5 bridge | ❌ 未实现 | — | 需自建，见 §2 路线 B |
| 真实配对码端到端打通 | ⚠️ 待验证 | `docs/逆向报告.md` §7 | 需一台可控的 Server 端设备 |

### 1.2 为什么是 0（给不懂逆向的人看的版本）

App 的客户端界面只有一个 `Select Server → (New Server)` 入口 —— 它的意思是"去和你自己的另一台设备配对"，
不是"选一个厂商的服务器"。配对流程是：

1. 你在 A 设备（电脑/手机）打开 Server 模式 → 屏幕上出现 **6 位配对码**（10 分钟过期）；
2. 你在 B 设备打开 Client 模式 → 输入这 6 位码；
3. B 向 `pairv.net` 换一个会话令牌，A 把自己的公网地址注册到 `pairv.net`；
4. A、B 尝试 UDP 打洞直连，失败则走厂商中继；
5. 流量从 B 的 tun 出来，经隧道到 A，再由 **A 的网络**出公网。

**出口 IP 永远是你自己 A 设备的 IP。** 没有任何"别人的服务器"可以拿来用。
一个 Server 端最多配对 **10 个**客户端（native 硬限制）。

⇒ 结论：**任何试图"从 PairVPN 拉节点池"的方案都会失败，不是难度问题，是不存在。**

### 1.3 开箱先跑一遍（确认基线）

```bash
cd PairVPN_1.8.51
python tools/probe_addrserver.py probe          # 三端点探活
python tools/probe_addrserver.py bench -n 24 -c 4
```

期望输出（2026-10-28 实测基线）：

```json
{"requests":24,"concurrency":4,"success":24,"success_rate":100.0,
 "rps":1.72,"p50_ms":1855.0,"p95_ms":2871.1,"max_ms":3929.3,"resp_len_values":[64]}
```

---

## 2. 部署形态

> 只在**需求确认为"私有固定 IP 出口"**时才往下走。三选一。

### 2.1 路线 A（默认推荐）：不做

PairVPN 到此为止。你的池子里已有 3000+ 节点（SuperVPN Pro hysteria2 / ZeroPing / Russia / Indonesia / VPN Super），
PairVPN 提供不了增量。**维护现有池的存活率比多一条 0 节点链路有价值得多。**

### 2.2 路线 B：自建 PairVPN 出口节点（真的要用 PairVPN 时）

```
[ 出口设备 ]                      [ 宿主 / VPS ]                       [ new-api ]
 Android 手机/模拟器              bridge.py                            proxy_pool.go
 PairVPN Server 模式   ──tun──►   tun→SOCKS5 监听              ◄──   TRYINGOPEN_PROXY_FILE
 (需要 App + 人工配对一次)        127.0.0.1:1080                       每行一个 socks5:// URL
```

**关键事实（别猜）：**

- `PairVPN Server` 模式只在 **Android / Windows / macOS** 客户端提供，没有 Linux 命令行版；
  ⇒ bridge 必须跑在能和 Server 端同局域网、且能拿到隧道流量的机器上；
- App 的客户端侧是标准 `VpnService` tun；服务端侧是 `MyService` 前台服务 + native 转发；
- **没有官方的"开放 SOCKS5"开关**，bridge 需要自己在 Server 端做（root + iptables REDIRECT 到 redsocks/sing-box）；
- 一个 Server 端最多 10 客户端 → **一个出口节点最多服务 10 个并发隧道**，做池要靠"多设备 × 多 IP"。

**最小可行部署（Android Server 端 + redsocks，需 root）：**

```bash
# 出口设备（Android, root）
# 1) 打开 PairVPN → Run as VPN Server → 记下 6 位配对码（10 分钟有效）
# 2) 起 redsocks，把 tun 网段流量重定向到本地 SOCKS5
cat > /data/local/tmp/redsocks.conf <<'EOF'
base: { log_debug: off; daemon: on; redirector: redsocks; ip: 127.0.0.1; port: 12345; type: socks5; }
redsocks: { local_ip: 127.0.0.1; local_port: 12345; ip: 127.0.0.1; port: 1080; type: socks5; }
redudp: { local_ip: 127.0.0.1; local_port: 10053; ip: 127.0.0.1; port: 1080; type: socks5; }
EOF
# 3) 手机上的 pvhost 网段 = 192.128.11.0/24（服务端 .1，客户端 .12）
#    从宿主侧访问手机暴露的 1080 端口做 SOCKS5（needs port forward / adb forward）
adb forward tcp:11080 tcp:1080
```

```python
# bridge.py 骨架（宿主侧最小实现，只做"探活 + 输出清单"，不含隧道逻辑）
# 完整实现按你们的 redsocks/port-forward 方案落地
import socks, socket   # pip install PySocks
def check(socks_host, socks_port, target="https://one.one.one.one/cdn-cgi/trace"):
    s = socks.socksocket(); s.set_proxy(socks.SOCKS5, socks_host, socks_port)
    s.settimeout(8); s.connect(("1.1.1.1", 443))   # 只验连通
    return True
```

> ⚠️ 上面只是骨架。**真正的 tun→SOCKS5 转换是这块工作量的 90%**，且强依赖设备可 root 与否。

### 2.3 路线 C（我建议你直接走这条）：用 VPS 取代 PairVPN

PairVPN 唯一卖点是"不用买服务器，用家里电脑当出口"。你要的是"长久稳定代理池"，这条不成立：
家庭宽带上行有限、设备会睡眠（App 自己都写了 `PairVPN terminated (battery saving?)`）、断网即失效、单 IP。

等价且稳定 10 倍的方案：

```yaml
# docker-compose.yml（VPS 上起一个 SOCKS5 出口，new-api 直接吃）
services:
  exit:
    image: ghcr.io/xtls/xray-core:latest
    network_mode: host
    volumes: [./xray.json:/etc/xray/config.json:ro]
    restart: unless-stopped
```

```json
// xray.json —— 只开 socks5 inbound + 认证
{
  "inbounds": [{
    "listen": "0.0.0.0", "port": 1080, "protocol": "socks",
    "settings": {"auth": "password", "accounts": [{"user":"<USER>","pass":"<PASS>"}], "udp": true}
  }],
  "outbounds": [{"protocol": "freedom"}]
}
```

然后 `TRYINGOPEN_PROXY_FILE` 里写一行：

```
socks5://<USER>:<PASS>@<VPS_IP>:1080#vps-exit-01
```

**这一行就是"订阅"。** 成本一个月几美元，稳定性、并发、可观测性全面碾压 PairVPN 路线。

---

## 3. 环境变量

new-api 侧**唯一需要动的**：

| 变量 | 值 | 说明 |
| --- | --- | --- |
| `TRYINGOPEN_PROXY_FILE` | `/opt/new-api/proxies/pool.txt`（绝对路径，可多个文件逗号分隔） | 每行一个代理 URL，`#` 开头为注释 |
| `TRYINGOPEN_PROXY_MAX_USE_PER_DAY` | 默认不限，建议 `2000` | 单代理每日使用上限，超过进冷却 |
| `TRYINGOPEN_USE_COOLDOWN_MAP` | 默认 `true` | 失败后进冷却表，避免反复选死节点 |
| `TRYINGOPEN_PROXIES` | 不设 | 与文件二选一 |
| `TRYINGOPEN_FREE_FETCH_DISABLED` | 建议 `true`（若有自建池） | 关掉免费源自动抓取，避免混池看不清健康度 |

清单文件格式（**每行一个，URL 语法，`#片段` 会作为来源标签**）：

```
# 自建出口
socks5://user:pass@198.51.100.10:1080#vps-exit-01
http://user:pass@203.0.113.7:3128#home-exit
```

> 支持的 scheme 以 `proxy_pool.go` 的解析为准（`socks5` / `http` / `https`）。
> 写入后 **new-api 只在启动或配置变更时 `LoadProxies()`** —— 清单变化需要重启容器，别指望热更新。

---

## 4. 三层验收

每一层都要有命令 + 判据，缺一层就是"看起来完成"。

### 4.1 隧道层（出口设备）

```bash
# 出口设备上，确认 tun 起没起
ip addr show tun0            # 期望有 192.128.11.x
ip route | grep -E '192\.128\.11|default'
```

判据：`tun0` 存在且拿到 `192.128.11.x`；路由默认走 tun。

### 4.2 代理层（bridge）

```bash
curl -s -x socks5h://user:pass@127.0.0.1:11080 https://one.one.one.one/cdn-cgi/trace | grep '^ip='
```

判据：返回的 `ip=` **必须等于出口设备的公网 IP**（不是宿主的、不是 VPS 的）。
不等 ⇒ 隧道没生效，流量走了宿主直连。**这是最容易误判成"通了"的地方。**

### 4.3 业务层（new-api）

```bash
# 1) 池子读进来了没有
curl -s http://127.0.0.1:3000/api/status | head -c 200

# 2) 管理端代理池统计（需管理员 token）
curl -s -H "Authorization: Bearer <ADMIN_TOKEN>" \
  "http://127.0.0.1:3000/api/channel/tryingopen/pool/stats" | python -m json.tool
```

判据：`total ≥ 1`、`available ≥ 1`、`residential ≥ 1`；
然后随便发一个真实业务请求，看后台日志里是否出现该代理的引用。

---

## 5. 常驻健康检查（**不是可选项**）

### 5.1 为什么必须

读 `relay/channel/tryingopen/proxy_pool.go` 确认的事实（行号为当前仓库版本）：

```go
// line 1162
func TraceProbes() int {
    ...
    // line 1180
    if e.source != "free" {
        continue
    }
```

`TRYINGOPEN_PROXY_FILE` 加载进来的条目 `source` 恒为 `"residential"`（line 400 `addSource(lines, "residential", ...)`），
**所以它们永远不会被 `TraceProbes()` 探活**。死条目会被反复选中，表现为「渠道高概率超时」。

⇒ 任何自建/自维护代理池都必须**自带健康检查器重写清单**。

### 5.2 四要素（少一个就是假实现）

1. **真实协议探测**：SOCKS5 握手 + 目标站可达，不能只测 TCP 连通；
2. **出口 IP 必须 == 节点 IP**，不等则 `exit_mismatch` 摘除；
3. **双阈值**：连续 N 轮失败才摘除（容忍抖动）；从未通过过的**新节点首轮不入池**；
4. **`os.replace` 原子重写**，避免 new-api 读到半个文件。

### 5.3 cron 写法

```bash
# 每 5 分钟一轮，输出清单原子替换
*/5 * * * * /usr/bin/python3 /opt/new-api/tools/health_loop.py \
  --source /opt/new-api/proxies/pool.src.txt \
  --target /opt/new-api/proxies/pool.txt \
  --exit-check https://one.one.one.one/cdn-cgi/trace >> /var/log/health_loop.log 2>&1
```

清单替换后，**每天固定时段重启一次 new-api 容器**让其重载（`LoadProxies()` 不热更新）。

---

## 6. 故障排查表

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| 池 `total=0` | `TRYINGOPEN_PROXY_FILE` 路径错 / 文件为空 / 容器内路径不存在 | 容器里 `ls -l` 该路径；用绝对路径 + volume 挂载 |
| `total>0, available=0` | 条目 scheme 不被识别，或全部在冷却表 | 检查 URL scheme；重启清冷却 |
| 渠道高概率超时 | 死节点没被摘除（`TraceProbes` 跳过 residential） | 上 §5 健康检查器 |
| 改了清单没生效 | 只有启动/配置变更才 `LoadProxies()` | 重启容器 |
| `curl -x socks5h` 返回宿主 IP | 隧道没生效，流量走直连 | 查 `tun0` 与路由；查 redsocks 规则 |
| PairVPN 客户端连不上服务端 | 配对码过期（10 分钟）/ 已满 10 客户端 / NAT 对称需中继 | 重新出码；删旧配对；看是否走 `relay` |
| Server 模式莫名断开 | 安卓省电杀进程（App 原文：`PairVPN terminated (battery saving?)`） | 关闭电池优化 + 保持屏幕/前台服务常驻 |
| 地址服务器探活 100% 失败 | 本机出网被墙 / DNS 污染 | 换出口再测；`pairv.net` → 45.33.111.235 |

---

## 7. 池内行为（全部"读源码确认"，不猜）

### 7.1 探活范围
`TraceProbes()` 只探 `source == "free"` 的条目（`proxy_pool.go:1180`）。
`residential`（含 `TRYINGOPEN_PROXY_FILE` 全部条目）**不探**。

### 7.2 来源标记
`TRYINGOPEN_PROXY_FILE` 的每个文件被记成一个来源（origin = `filepath.Base(file)`），
`loadFromFiles()` 里就是 `addSource(lines, "residential", filepath.Base(file), 1.0)`（`proxy_pool.go:400`，
`addSource` 定义在 `:357`），`source` 字段统一为 `residential`。
⇒ 想按池子看健康度，**用多文件而不是一个大文件**（代码注释原话：「否则全被归成 residential 一个大桶，看不出哪个池子健康」）。

### 7.3 选路与上限
- `Acquire()` / `AcquireForChannel()`（`proxy_pool.go:682` / `691`）：三级策略选可用代理；
- 冷却：`TRYINGOPEN_USE_COOLDOWN_MAP`（默认开）；
- 日上限：`TRYINGOPEN_PROXY_MAX_USE_PER_DAY`（超过进冷却，不是删除）。

### 7.4 探针目标
`traceEndpoints`（`proxy_pool.go:1247-1249`）→ `https://one.one.one.one/cdn-cgi/trace`、
`https://cloudflare-dns.com/cdn-cgi/trace`、`https://1.0.0.1/cdn-cgi/trace`；
实际探测在 `traceOnce(proxy)` 里，走 `url.Parse` + `http.ProxyURL`（`:1258` 起），`Timeout: 8s`。
⇒ 自建健康检查器用**同样目标 + 同样超时**，结论才和池子口径一致。
（`url.Parse` + `http.ProxyURL` 也决定了 scheme 支持面：`http` / `https` / `socks5`。）

---

## 8. 红线

1. **不要**为了"有数据"而把不可达条目写进清单 —— 会造成渠道长尾超时，比空池更糟；
2. **不要**改 `TraceProbes()` 让 `residential` 也进探活循环 —— 现有实现有并发预算假设，改了会拖慢整个网关（部署安全条款：负载生成类工作不得占用生产主机资源）；
3. **不要**在生产主机上跑大规模探活/压测；用 staging 或临时机器；
4. **不要**手工 `docker restart` 生产容器（走 `/opt/new-api/deploy-zero-downtime.sh <tag>`）；
5. **不要**把 App 内资产（APK / `libnative-lib.so` / `assets/html/*`）提交到公开仓库；
6. **不要**在仓库里写真实配对码、真实设备 IP、真实 `hwId`。

---

## 9. 验收清单

- [ ] §1.3 探活 + 压测跑出基线（三端点 200，成功率 100%）
- [ ] 需求已确认：**是"私有出口"而非"节点池"**，否则本条链路直接关掉
- [ ] 出口设备 `tun0` 起来，拿到 `192.128.11.x`
- [ ] `curl -x socks5h://…` 返回的 IP **== 出口设备公网 IP**
- [ ] 清单按 URL 语法写入 `TRYINGOPEN_PROXY_FILE` 指向的文件
- [ ] 管理端 pool stats：`total/available/residential` 均 ≥1
- [ ] 健康检查器上线（四要素齐），cron 已配
- [ ] 每日定时重启容器让清单重载
- [ ] 真实业务请求成功一次，且日志能看到代理引用
- [ ] 仓库内无 APK / 无真实 IP / 无真实配对码

---

## 10. 复现上游

节点"全挂"（对 PairVPN 而言是"设备离线"）时怎么办：

1. **协议本身不会挂** —— `pairv.net` 是厂商基础设施，探活在 §1.3 一分钟确认；
2. **出口设备挂了**：重新打开 Server 模式拿新配对码，客户端重新配对；
3. **App 改版导致参数变化**：用 `tools/find_url_refs.py` 重新定位 URL 常量：
   ```bash
   python tools/find_url_refs.py "https://%s/dev/%s?%s"
   # 输出里紧邻的 ADRP+ADD 目标就是 host 常量；参数模板串也在同一函数内
   ```
4. **厂商换了域名**：同上，`find_url_refs.py "pairv.net"` 会列该域名所有引用函数，
   同函数内的字符串就是新端点/新参数。
5. **要重跑全量认知**：`docs/逆向报告.md` §6 复现方式（解包 → 字符串 → xref → 探活）。

---

## 附：协议速查（对接时唯一需要的表）

| 项 | 值 |
| --- | --- |
| 地址服务器 | `https://pairv.net/dev/<action>?<params>`（`pairv.net` → `45.33.111.235`） |
| `client_pairing` | `rand=%d&ver=%d&os=%s&osver=%d&code=%s&%s` |
| `server_pairing` | `iceId=%s&pairCode=%s&flags=%d&svrName=%s&hwId=%s` |
| `remove_pairing` | 同 `client_pairing`，`code` 为目标配对 |
| 会话校验串 | `seq=%d&deviceId=%s&pairId=%s&key=%s&flags=%d&rs=%d&carrier=%s&model=%s` |
| 响应 | `\n\n` + 固定 64 字符令牌；字符表 `[A-Za-z0-9-_.]`（`.` 是表内字符，**不是分隔符**） |
| 未注册 code | 不报错，返回等价随机令牌（失败延后到握手阶段） |
| 配对码 | 6 位数字，**10 分钟过期** |
| 单服务端上限 | **10** 个客户端 |
| 隧道内网段 | 服务端 `192.128.11.1`（`pvhost`）/ 客户端 `192.128.11.12` |
| 连接状态机 | 直连 → UDP 打洞（`Verifying NAT…`）→ 失败回落中继（`Handshaking with relay server…`） |
| 认证 | 可选 4 位 PIN（`pref_cli_need_authenticate`）+ 设备指纹 `hwId` |
| 权限档位 | `lan` / `lancast` / `all`（`pref_svr_permission`） |
