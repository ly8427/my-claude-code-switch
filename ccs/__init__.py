"""Claude Code Switch (ccs).

Flexibly switch the 7 first-class Claude Code env vars —
ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL /
ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL /
CLAUDE_CODE_SUBAGENT_MODEL / CLAUDE_CODE_EFFORT_LEVEL — across WSL and
Docker-container targets, with built-in compatibility shims for the
known relay-endpoint pitfalls.
"""
from __future__ import annotations

__version__ = "0.1.0"
