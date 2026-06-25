# feishu-bridge 容器网络故障诊断记录

记录一次 bridge 失联问题的完整诊断过程与根因，供日后排查参考。

## 症状

飞书发消息无响应。`bridge.log` 显示 `turn started` 后无后续，
但**注意**：bridge 不记录 `turn finished`，回复通过飞书卡片异步推送，
所以"日志无后续"≠卡死，不能据此判断僵死 turn（踩过的坑）。

## 根因

`v2rayN`（系统代理模式）+ `.wslconfig` 的 `networkingMode=mirrored`
共同作用：

```
v2rayN 系统代理模式 → Windows 注册表设 ProxyServer=127.0.0.1:10808
        ↓
v2rayN 关闭后，注册表 ProxyServer 残留（v2rayN 退出不清理）
        ↓
.wslconfig: networkingMode=mirrored → 容器流量经 Windows 网络栈
        ↓
Windows 系统代理按域名/SNI 劫持容器流量 → 导向 10808（无监听）
        ↓
容器所有"域名"连接失败（国内海外全断），但 IP 直连正常
        ↓
claude 调 deepseek API（域名连接）→ TLS 永久挂起 → turn 卡死 → bridge 阻塞
```

## 关键证据（v2rayN 关闭态实测）

| 测试 | 结果 |
|------|------|
| WSL 宿主直连国内 | ✅ 401/404 正常（宿主 eth0 不被劫持）|
| 容器 **IP 直连** deepseek:443 | ✅ TCP OK（路由层正常）|
| 容器 **域名**连 deepseek | ❌ `SSL_ERROR_SYSCALL`（被劫持）|
| 容器内代理环境变量 | 无（劫持不在环境变量层，在 Windows 网络栈层）|

判定要点：**IP 直连通 + 域名连接断** = 域名/SNI 层劫持。

## 为什么 v2rayN 路由规则救不了

v2rayN 的"绕过大陆"路由规则只在**流量到达 v2rayN 之后**生效。
但 v2rayN 关闭时，流量被 Windows 残留系统代理导向无监听的 10808，
**根本到不了 v2rayN**，路由规则无从生效。

## 方案

**v2rayN 保持常开（系统代理模式）** —— 实测此状态下：
- 容器连国内 API（deepseek/feishu）✅ 直连正常
- 容器连海外（github/anthropic）✅ 走代理正常
- 国内直连 + 海外代理分流都工作

辅助规则：v2rayN 路由里给 `*.deepseek.com`、`*.feishu.cn`、
`*.bigmodel.cn` 等加 direct，让国内 API 不绕代理（v2rayN 常开时生效）。

## v2rayN 偶尔关闭时的处理

不做复杂兜底（改 .wslconfig 关 autoProxy 或容器走 host 网络都有副作用）。
偶发时手动重开 v2rayN 即可。用 `scripts/bridge-health.sh` 检测：

```bash
bash scripts/bridge-health.sh          # 检测
bash scripts/bridge-health.sh --fix    # 检测+重启 bridge
```

核心检测点是**容器能否出站**（整个故障链的根），不是猜日志格式。

## 踩过的坑（避免重犯）

1. **误判 DNS 故障**：早期看到 `Failed to resolve` 以为是 DNS，
   实际是更底层的域名/SNI 劫持。
2. **误判环境变量劫持**：以为容器 `HTTP_PROXY` 注入导致，实际容器内无代理变量。
3. **误判僵死 turn**：以为日志无 `turn finished` = 卡死，实际 bridge 不记这个，
   turn 正常完成（用户收到回复）。**判定僵死要用容器出站检测，不能猜日志格式。**
4. **v2rayN 开着时测不出关时的故障**：必须复现故障态（关 v2rayN）才能确诊。
