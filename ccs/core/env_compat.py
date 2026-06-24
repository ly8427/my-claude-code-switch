"""Compatibility shims for known relay-endpoint pitfalls.

Historical context (from the feishu-bridge .commit_bridge.txt):
  - claude-code CLI >= 2.1.x historically authenticated ONLY via
    ANTHROPIC_API_KEY and ignored ANTHROPIC_AUTH_TOKEN ("Not logged in").
    That's why an early version of this module *mirrored* AUTH_TOKEN into
    API_KEY.

  - HOWEVER, current Claude Code (v2.1.159+) detects when BOTH
    ANTHROPIC_AUTH_TOKEN and ANTHROPIC_API_KEY are set and emits an
    "Auth conflict" warning — even when the values are identical. The
    mirror shim therefore became actively harmful on modern versions.

So the modern, recommended approach for third-party / relay endpoints is:
  - set ONLY ANTHROPIC_AUTH_TOKEN (sent as Authorization: Bearer), and
  - leave ANTHROPIC_API_KEY unset.

This module's default ``auth_mode="token"`` follows that. For the rare
case of an old CLI build that genuinely ignores AUTH_TOKEN, set
``auth_mode="api_key"`` on the profile to emit API_KEY instead (and drop
AUTH_TOKEN), avoiding the conflict while keeping old builds working.

Other shims (unchanged):
  - relay endpoint -> Bearer heads-up
  - SDK mode ignores ANTHROPIC_MODEL -> heads-up
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Profile

# Hosts that serve the official Anthropic API.
_OFFICIAL_HOSTS = ("api.anthropic.com",)

# Valid auth strategies.
#   token   -> emit only ANTHROPIC_AUTH_TOKEN (Bearer; modern default)
#   api_key -> emit only ANTHROPIC_API_KEY    (x-api-key; old-CLI compat)
VALID_AUTH_MODES = frozenset({"token", "api_key"})


@dataclass
class CompatReport:
    """What the compatibility layer added / flagged for a profile."""

    # env key -> value that was added or derived
    added: dict[str, str] = field(default_factory=dict)
    # env keys that were intentionally suppressed (e.g. to avoid conflicts)
    removed: dict[str, str] = field(default_factory=dict)
    # human-readable advisory lines shown to the user after apply
    advisories: list[str] = field(default_factory=list)

    @property
    def has_additions(self) -> bool:
        return bool(self.added)

    @property
    def has_advisories(self) -> bool:
        return bool(self.advisories)


def is_relay_endpoint(base_url: str | None) -> bool:
    """True if base_url points at a non-official (relay/proxy) host."""
    if not base_url:
        return False
    host = base_url.lower()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split(":", 1)[0]
    return not any(host == off or host.endswith("." + off) for off in _OFFICIAL_HOSTS)


def _auth_mode(profile: Profile) -> str:
    """Resolve the effective auth mode for a profile.

    Defaults to ``token``. Profiles may override via a free-form attribute
    if present (``auth_mode``), else we infer:
      - relay endpoint + auth_token set -> token (Bearer, the modern way)
      - official endpoint             -> token is fine too
    """
    mode = getattr(profile, "auth_mode", None)
    if mode in VALID_AUTH_MODES:
        return mode
    return "token"


def build_env(profile: Profile) -> tuple[dict[str, str], CompatReport]:
    """Turn a profile into the final env dict + a compatibility report.

    The key rule: never emit BOTH ANTHROPIC_AUTH_TOKEN and
    ANTHROPIC_API_KEY — modern Claude Code treats that as an auth
    conflict. Pick one based on ``auth_mode``.
    """
    env = profile.to_env()
    report = CompatReport()

    token = env.get("ANTHROPIC_AUTH_TOKEN")
    api_key = env.get("ANTHROPIC_API_KEY")  # user may have set it explicitly

    mode = _auth_mode(profile)

    if token and api_key:
        # Both present (e.g. from an old mirror) -> conflict on modern CLI.
        # Keep the one matching auth_mode, drop the other.
        if mode == "token":
            env.pop("ANTHROPIC_API_KEY", None)
            report.removed["ANTHROPIC_API_KEY"] = api_key
            report.advisories.append(
                "Removed ANTHROPIC_API_KEY (was set alongside AUTH_TOKEN) — "
                "modern Claude Code flags both-set as an 'Auth conflict'. "
                "Keeping ANTHROPIC_AUTH_TOKEN only (Bearer)."
            )
        else:  # api_key mode
            env.pop("ANTHROPIC_AUTH_TOKEN", None)
            report.removed["ANTHROPIC_AUTH_TOKEN"] = token
            report.advisories.append(
                "Removed ANTHROPIC_AUTH_TOKEN (was set alongside API_KEY) — "
                "keeping ANTHROPIC_API_KEY only (x-api-key, old-CLI compat)."
            )
    elif token and mode == "token":
        # The normal, recommended relay path: token only, no mirror.
        report.advisories.append(
            "Using ANTHROPIC_AUTH_TOKEN only (Bearer). Do NOT also set "
            "ANTHROPIC_API_KEY — modern Claude Code reports an 'Auth conflict' "
            "when both are present."
        )
    # If only api_key is set, or neither, leave as-is.

    # --- relay Bearer heads-up -------------------------------------------
    if is_relay_endpoint(profile.base_url):
        report.advisories.append(
            f"base_url {profile.base_url} is a relay endpoint — the token "
            f"travels as 'Authorization: Bearer' (set via AUTH_TOKEN)."
        )

    # --- SDK model-forwarding heads-up -----------------------------------
    if profile.model:
        report.advisories.append(
            "ANTHROPIC_MODEL is set but is NOT read by the Claude Agent SDK — "
            "in SDK-driven flows pass model explicitly to ClaudeAgentOptions "
            "(the interactive CLI reads it fine)."
        )

    return env, report


__all__ = [
    "CompatReport",
    "is_relay_endpoint",
    "build_env",
    "VALID_AUTH_MODES",
]
