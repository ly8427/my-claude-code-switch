#!/usr/bin/env bash
# bridge-health.sh — 检测 feishu-bridge 容器网络健康，并提供一键恢复
#
# 故障模式：v2rayN 系统代理关闭/失效时，networkingMode=mirrored 会把
# 容器的域名流量劫持到无监听的 10808，导致容器出站全断 → claude 调 API
# 挂起 → turn 卡死 → bridge 阻塞 → 飞书无回复。
#
# 核心检测信号（可靠）：容器能否出站访问国内 API。
#   - 这是整个故障链的根因检测点，比猜测日志格式可靠得多。
#
# 用法：
#   bridge-health.sh            # 仅检测，打印诊断
#   bridge-health.sh --fix      # 检测到故障则自动重启 bridge
#   bridge-health.sh --watch    # 每 60s 检测一次（可放后台/cron）

set -u

BRIDGE_SERVICE="feishu-bridge"
CONTAINER="${FEISHU_CONTAINER:-feishu-claude-agent}"
PROBE_HOST="${PROBE_HOST:-api.deepseek.com}"
INTERVAL=60
BRIDGE_LOG="${BRIDGE_LOG:-/bridge.log}"

# --- 颜色（非 tty 退化）---
if [ -t 1 ]; then
  G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; D=$'\033[2m'; N=$'\033[0m'
else
  G=""; R=""; Y=""; D=""; N=""
fi

log()  { printf "%s\n" "$*"; }
ok()   { log "${G}[OK]${N} $*"; }
fail() { log "${R}[FAIL]${N} $*"; }
warn() { log "${Y}[WARN]${N} $*"; }

# --- 单次检测，返回 0=健康 / 1=故障 ---
# 只用确实可靠的信号判故障；不确定的仅 warn，不影响退出码。
check_once() {
  local rc=0

  # 1. bridge 进程在不在
  if ! pgrep -f bridge.py >/dev/null 2>&1; then
    fail "bridge.py 进程不在"
    rc=1
  else
    ok "bridge.py 运行中 ($(pgrep -f bridge.py | head -1))"
  fi

  # 2. 容器在不在
  if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
    fail "容器 $CONTAINER 未运行"
    rc=1
  else
    ok "容器 $CONTAINER 运行中"
  fi

  # 3. ★核心★：容器能否出站（整个故障链的根因检测点）
  #    v2rayN 关闭导致 mirrored 劫持时，这里会 SSL_ERROR_SYSCALL / 000。
  local probe
  probe=$(docker exec "$CONTAINER" sh -c \
    "curl -sS -o /dev/null -w '%{http_code}' --max-time 6 https://$PROBE_HOST" 2>/dev/null || echo "000")
  if [ "$probe" = "000" ]; then
    fail "容器出站失败 ($PROBE_HOST)"
    warn "极可能是 v2rayN 代理关闭，mirrored 劫持流量到死端口 10808"
    warn "修复：开启 v2rayN（系统代理模式）；或执行 $0 --fix 重启 bridge"
    rc=1
  else
    ok "容器出站正常 ($PROBE_HOST → HTTP $probe)"
  fi

  # 4. （仅信息）bridge 与飞书 WebSocket 是否连着
  #    看最近 5 分钟内日志有无 connected/disconnected，纯参考，不判故障。
  if [ -f "$BRIDGE_LOG" ]; then
    local recent
    recent=$(find "$BRIDGE_LOG" -mmin -5 -print 2>/dev/null)
    if tail -20 "$BRIDGE_LOG" 2>/dev/null | grep -q "connected to wss://"; then
      : # 连着，静默
    elif tail -20 "$BRIDGE_LOG" 2>/dev/null | grep -q "trying to reconnect"; then
      warn "bridge 日志显示正在重连飞书（可能尚未恢复）"
    fi
  fi

  return $rc
}

# --- 修复：重启 bridge ---
# 注意：重启只能清除"僵死 turn"这类阻塞，无法修复"容器出站断"
# （那是 v2rayN/mirrored 层的问题，重启 bridge 不解决）。所以 --fix
# 主要用于：容器出站已恢复但 bridge 卡在旧 turn 时，让它重连。
do_fix() {
  log "${Y}重启 $BRIDGE_SERVICE...${N}"
  if systemctl --user restart "$BRIDGE_SERVICE" 2>/dev/null; then
    sleep 4
    if pgrep -f bridge.py >/dev/null 2>&1; then
      ok "bridge 已重启"
    else
      fail "bridge 重启后进程未起来，请检查 systemctl --user status $BRIDGE_SERVICE"
    fi
  else
    fail "重启失败（权限或服务不存在）"
  fi
}

# --- 主流程 ---
case "${1:-}" in
  --fix)
    if check_once; then
      log "一切正常，无需修复"
    else
      # 容器出站断时，--fix 重启 bridge 通常无效（根因在 v2rayN），
      # 但仍执行，以处理"出站已恢复但 bridge 卡死"的情况。
      warn "注意：若故障是容器出站断（v2rayN 关），需先开 v2rayN"
      do_fix
      log "修复后复检..."
      sleep 3
      check_once && ok "已恢复" || fail "仍异常——请确认 v2rayN 是否开启"
    fi
    ;;
  --watch)
    log "守护模式：每 ${INTERVAL}s 检测一次（Ctrl-C 退出）"
    while true; do
      if ! check_once >/dev/null 2>&1; then
        log "$(date '+%H:%M:%S') 检测到故障"
        check_once   # 打印详情
      fi
      sleep "$INTERVAL"
    done
    ;;
  *)
    check_once
    ;;
esac
