# ccs — Claude Code Switch

灵活切换 Claude Code 的 7 个一等环境变量，跨 **WSL** 和 **Docker 容器**两个目标统一管理。

## 为什么需要它

现有工具（cc-switch、claude-code-router 等）都不能同时满足：
1. 把这 7 个变量都当**一等字段**管理（而非塞进通用 env）
2. 同时写 **WSL 本地**和**Docker 容器内**的 `settings.json`
3. 内建你在中转端点（relay）场景踩过的坑的兜底

ccs 就是为此而做。

## 管理的 7 个变量

| 字段（短名） | 写入的环境变量 |
|---|---|
| `auth_token` | `ANTHROPIC_AUTH_TOKEN`（+ 自动镜像到 `ANTHROPIC_API_KEY`）|
| `base_url` | `ANTHROPIC_BASE_URL` |
| `model` | `ANTHROPIC_MODEL` |
| `opus_model` | `ANTHROPIC_DEFAULT_OPUS_MODEL` |
| `sonnet_model` | `ANTHROPIC_DEFAULT_SONNET_MODEL` |
| `haiku_model` | `ANTHROPIC_DEFAULT_HAIKU_MODEL` |
| `subagent_model` | `CLAUDE_CODE_SUBAGENT_MODEL` |
| `effort_level` | `CLAUDE_CODE_EFFORT_LEVEL`（low/medium/high）|

## 安装

```bash
# 在 WSL 里
cd /path/to/ccs
pip install --user --break-system-packages .          # CLI（依赖 pyyaml）
pip install --user --break-system-packages '.[tui]'   # 加上 TUI（依赖 textual）
```

或直接运行：`python3 -m ccs ...`

## 快速开始

```bash
ccs init                      # 生成 ~/.config/ccs/profiles.yaml 模板
ccs edit                      # 用 $EDITOR 编辑配置
ccs list                      # 列出所有 profile
ccs show relay                # 查看某 profile（token 打码）
ccs health                    # 检查所有目标连通性
ccs use relay                 # 应用 profile 到所有目标（默认询问确认）
ccs use relay -t wsl -y       # 只应用到 WSL，跳过确认
ccs use relay --dry-run       # 只预览，不写入
ccs diff relay                # 看当前配置与 profile 的差异
ccs tui                       # 交互式界面
```

单变量操作：
```bash
ccs set relay model deepseek-v4-pro
ccs set relay ANTHROPIC_MODEL sonnet    # 也可用完整环境变量名
ccs unset relay effort_level
```

## 配置文件 profiles.yaml

位置查找顺序：`$CCS_CONFIG` → `~/.config/ccs/profiles.yaml` → `./profiles.yaml`

```yaml
profiles:
  official:
    base_url: https://api.anthropic.com
    auth_token: ${ANTHROPIC_API_KEY}     # 从环境变量取值，避免明文
    model: sonnet
    effort_level: medium

  relay-deepseek:
    base_url: https://api.deepseek.com/anthropic
    auth_token: ${DEEPSEEK_KEY}
    model: deepseek-v4-pro
    opus_model: deepseek-v4-pro
    sonnet_model: deepseek-v4-pro
    haiku_model: deepseek-chat
    subagent_model: deepseek-chat
    effort_level: high
    note: 中转端点

targets:
  wsl:
    kind: wsl
    # path: ~/.claude/settings.json    # 留空用默认
  feishu:
    kind: docker
    container: feishu-claude-agent
    path: /root/.claude/settings.json
```

## 安全保证

- **合并而非覆盖**：只改 `env` 子对象，绝不碰 `model`/`statusLine`/`permissions`/`hooks` 等其他字段
- **写前备份**：每次 apply 前备份到 `<dir>/backups/settings.json.bak.<时间戳>`（WSL）或容器内 `settings.json.bak.<时间戳>`（docker）
- **密钥脱敏**：`show`/`list` 中 token 仅显示首尾；`${ENV_VAR}` 引用解析自环境，不落明文
- **apply 前预览**：默认展示 diff 并要求确认，`--yes` 跳过

## 内建的 3 个兼容兜底

这些坑来自实战（中转端点 relay 场景），现有工具大多未处理：

1. **AUTH_TOKEN → API_KEY 镜像**：Claude Code CLI ≥ 2.1.x 只读 `ANTHROPIC_API_KEY`，会忽略 `ANTHROPIC_AUTH_TOKEN`（表现："Not logged in"）。设了 `auth_token` 时自动镜像。
2. **relay 端点 Bearer 提示**：非官方 base_url 需走 `Authorization: Bearer`，工具检测到 relay 会给出提醒。
3. **SDK 模式模型提示**：`ANTHROPIC_MODEL` 在 Claude Agent SDK 下不会被自动读取，需显式传给 `ClaudeAgentOptions`；交互式 CLI 正常。

## 命令速查

| 命令 | 作用 |
|---|---|
| `init` | 生成配置模板 |
| `list` | 列出 profile（标记 active）|
| `show <p>` | 查看 profile 明细 |
| `use <p> [-t ...] [-y] [-n]` | 应用 profile |
| `set <p> <var> <val>` | 设置单变量 |
| `unset <p> <var>` | 清除单变量 |
| `new <p>` | 交互式新建 |
| `rm <p>` | 删除 profile |
| `diff [p] [-t ...]` | 显示差异 |
| `targets` | 列出目标 |
| `health [-t ...]` | 目标连通性体检 |
| `edit` | 用 $EDITOR 编辑配置 |
| `tui` | 交互式界面 |

`-t/--target` 可重复，或用 glob：`wsl:*`、`docker:*`。留空默认所有目标。
