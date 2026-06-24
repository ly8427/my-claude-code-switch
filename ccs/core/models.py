"""Data models and the canonical variable map.

A Profile is a named bundle of the 7 first-class Claude Code env vars.
Profile fields use short, human-friendly names (``model`` rather than
``ANTHROPIC_MODEL``); ``VAR_MAP`` is the single source of truth mapping
those short names to the env-var keys that get written into the target's
``settings.json`` → ``env`` object.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Canonical variable map
# ---------------------------------------------------------------------------
# short name (Profile field)  ->  env-var key written to settings.json
# Order matters: it defines display order in `ccs show` / TUI / diff.
VAR_MAP: dict[str, str] = {
    "auth_token": "ANTHROPIC_AUTH_TOKEN",
    "base_url": "ANTHROPIC_BASE_URL",
    "model": "ANTHROPIC_MODEL",
    "opus_model": "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "sonnet_model": "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "haiku_model": "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "subagent_model": "CLAUDE_CODE_SUBAGENT_MODEL",
    "effort_level": "CLAUDE_CODE_EFFORT_LEVEL",
}

# Reverse lookup: env-var key -> short name
ENV_KEY_TO_SHORT: dict[str, str] = {v: k for k, v in VAR_MAP.items()}

# The set of env keys this tool owns. Used by diff/merge to recognise
# "our" keys vs keys the user may have added by hand.
OWNED_ENV_KEYS: frozenset[str] = frozenset(VAR_MAP.values())

# Effort level vocabulary. "max"/"auto" appear in real relay setups
# (e.g. deepseek bridge), so we accept them alongside the documented values.
VALID_EFFORT_LEVELS: frozenset[str] = frozenset(
    {"low", "medium", "high", "max", "auto"}
)

# Fields that are credentials and must be masked in display.
SECRET_FIELDS: frozenset[str] = frozenset({"auth_token"})


@dataclass
class Profile:
    """A named bundle of the 7 first-class Claude Code env vars.

    All value fields are optional: a profile only needs to set the vars
    it cares about. Unset vars are omitted from the generated env object
    (they will NOT be deleted from a target unless explicitly unset).
    """

    name: str
    auth_token: str | None = None
    base_url: str | None = None
    model: str | None = None
    opus_model: str | None = None
    sonnet_model: str | None = None
    haiku_model: str | None = None
    subagent_model: str | None = None
    effort_level: str | None = None
    # Free-form note shown in `ccs list`/`show`; not written anywhere.
    note: str | None = None

    def to_env(self) -> dict[str, str]:
        """Build the ``env`` dict this profile contributes.

        Only non-None fields are included. ``note`` is metadata, never
        written. The compatibility layer (env_compat) may add further
        derived keys (e.g. ANTHROPIC_API_KEY mirror) on top of this.
        """
        env: dict[str, str] = {}
        for short_name, env_key in VAR_MAP.items():
            value = getattr(self, short_name)
            if value is not None and value != "":
                env[env_key] = str(value)
        return env

    def to_public_dict(self) -> dict[str, Any]:
        """Profile as a YAML-safe dict, with secrets masked."""
        d = asdict(self)
        for f in SECRET_FIELDS:
            if d.get(f):
                d[f] = mask_secret(d[f])
        return d


@dataclass
class TargetSpec:
    """A registered write target (WSL path or a Docker container)."""

    name: str
    kind: Literal["wsl", "docker"]
    # docker only: container name
    container: str | None = None
    # optional explicit settings.json path; None => target-specific default
    path: str | None = None


@dataclass
class ApplyResult:
    """Outcome of applying a profile to one target."""

    target: str
    success: bool
    message: str
    # human-readable diff lines (empty if nothing changed)
    diff: list[str] = field(default_factory=list)
    # backup path written, if any
    backup: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def mask_secret(value: str) -> str:
    """Mask a secret, showing head/tail only. Empty -> <empty>."""
    if not value:
        return "<empty>"
    if len(value) <= 10:
        return "***"
    return f"{value[:4]}…{value[-4:]}"


def field_label(short_name: str) -> str:
    """Human label for a short field name, showing the env key too."""
    env_key = VAR_MAP.get(short_name, short_name)
    return f"{short_name}  ({env_key})"


def profile_fieldnames() -> list[str]:
    """Ordered list of the value field names (excluding name/note)."""
    return [f.name for f in fields(Profile) if f.name not in ("name", "note")]


__all__ = [
    "VAR_MAP",
    "ENV_KEY_TO_SHORT",
    "OWNED_ENV_KEYS",
    "VALID_EFFORT_LEVELS",
    "SECRET_FIELDS",
    "Profile",
    "TargetSpec",
    "ApplyResult",
    "mask_secret",
    "field_label",
    "profile_fieldnames",
]
