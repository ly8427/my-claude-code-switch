# ccs — Claude Code Switch

[English](README.md) | [简体中文](README.zh-CN.md)

Flexibly switch the 7 first-class Claude Code environment variables across **WSL** and **Docker** targets — with built-in compatibility shims for relay endpoints.

## Why

Existing tools (cc-switch, claude-code-router, …) don't simultaneously:

1. Treat these 7 variables as **first-class fields** (instead of stuffing them into a generic env blob),
2. Write to **both WSL-local and in-container** `settings.json`,
3. **Auto-handle the pitfalls** you hit on relay/proxy endpoints.

`ccs` exists to fill that gap.

## The 7 managed variables

| Field (short name) | Env var written |
|---|---|
| `auth_token` | `ANTHROPIC_AUTH_TOKEN` |
| `base_url` | `ANTHROPIC_BASE_URL` |
| `model` | `ANTHROPIC_MODEL` |
| `opus_model` | `ANTHROPIC_DEFAULT_OPUS_MODEL` |
| `sonnet_model` | `ANTHROPIC_DEFAULT_SONNET_MODEL` |
| `haiku_model` | `ANTHROPIC_DEFAULT_HAIKU_MODEL` |
| `subagent_model` | `CLAUDE_CODE_SUBAGENT_MODEL` |
| `effort_level` | `CLAUDE_CODE_EFFORT_LEVEL` (`low`/`medium`/`high`/`max`/`auto`) |

## Install

```bash
# inside WSL
cd /path/to/ccs
pip install --user --break-system-packages .          # CLI (depends on pyyaml)
pip install --user --break-system-packages '.[tui]'   # adds the TUI (depends on textual)
```

Or run directly: `python3 -m ccs ...`

## Quick start

```bash
ccs init                      # generate ~/.config/ccs/profiles.yaml
ccs edit                      # open it in $EDITOR
ccs list                      # list profiles
ccs show relay                # inspect a profile (secrets masked)
ccs health                    # check all targets are reachable
ccs use relay                 # apply a profile to all targets (asks first)
ccs use relay -t wsl -y       # apply to WSL only, no prompt
ccs use relay --dry-run       # preview, write nothing
ccs diff relay                # show diff vs current env
ccs tui                       # interactive UI
```

Single-variable edits:
```bash
ccs set relay model deepseek-v4-pro
ccs set relay ANTHROPIC_MODEL sonnet    # full env-key name also accepted
ccs unset relay effort_level
```

## Configuration: profiles.yaml

Lookup order: `$CCS_CONFIG` → `~/.config/ccs/profiles.yaml` → `./profiles.yaml`

```yaml
profiles:
  official:
    base_url: https://api.anthropic.com
    auth_token: ${ANTHROPIC_API_KEY}     # resolved from env, never plaintext here
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
    note: relay endpoint

targets:
  wsl:
    kind: wsl
    # path: ~/.claude/settings.json    # default if omitted
  feishu:
    kind: docker
    container: feishu-claude-agent
    path: /root/.claude/settings.json
```

## Safety guarantees

- **Merge, never overwrite** — only the `env` sub-object is touched; `model`, `statusLine`, `permissions`, `hooks`, `theme`, … are preserved untouched.
- **Backup before write** — each apply backs up to `<dir>/backups/settings.json.bak.<timestamp>` (WSL) or in-container `settings.json.bak.<timestamp>` (docker).
- **Secret masking** — tokens show only head/tail in `show`/`list`; `${ENV_VAR}` references resolve from the environment, never stored plaintext.
- **Preview before apply** — a diff is shown and confirmation required by default; `--yes` skips it.

## The 3 built-in compatibility shims

These come from real-world relay-endpoint pain; most off-the-shelf switchers miss them:

1. **Auth-conflict avoidance.** Modern Claude Code (v2.1.159+) flags *both* `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_API_KEY` being set as an "Auth conflict" — even when identical. `ccs` therefore emits **only** `ANTHROPIC_AUTH_TOKEN` by default (Bearer). (An `auth_mode: api_key` override exists for old CLI builds that ignored the token.)
2. **Relay Bearer heads-up.** When `base_url` is a non-official host, you get a reminder that the token must travel as `Authorization: Bearer`.
3. **SDK model heads-up.** `ANTHROPIC_MODEL` is **not** read by the Claude Agent SDK — you're warned to pass `model` explicitly to `ClaudeAgentOptions` (the interactive CLI reads it fine).

## Command reference

| Command | Purpose |
|---|---|
| `init` | generate a starter config |
| `list` | list profiles (marks active) |
| `show <p>` | inspect a profile |
| `use <p> [-t ...] [-y] [-n]` | apply a profile |
| `set <p> <var> <val>` | set one variable |
| `unset <p> <var>` | clear one variable |
| `new <p>` | create a profile interactively |
| `rm <p>` | delete a profile |
| `diff [p] [-t ...]` | show differences |
| `targets` | list targets |
| `health [-t ...]` | check target reachability |
| `edit` | open config in `$EDITOR` |
| `tui` | interactive UI |

`-t/--target` repeats, or use a kind glob: `wsl:*`, `docker:*`. Empty = all targets.

## License

MIT
