"""profiles.yaml loading, validation, and persistence.

Layout of ``profiles.yaml``::

    profiles:
      <name>:
        base_url: ...
        auth_token: ${ENV_VAR}      # resolved from os.environ at load time
        model: ...
        opus_model: ...
        sonnet_model: ...
        haiku_model: ...
        subagent_model: ...
        effort_level: high|medium|low
        note: optional free text
    targets:
      wsl:        { kind: wsl }
      feishu:     { kind: docker, container: feishu-claude-agent }
    active:       <profile-name>    # last applied profile (informational)

Config file location resolves in this order:
  1. ``$CCS_CONFIG`` env var (explicit path)
  2. ``~/.config/ccs/profiles.yaml`` (XDG-ish default)
  3. ``./profiles.yaml`` (cwd, for project-local setups)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import (
    Profile,
    TargetSpec,
    VALID_EFFORT_LEVELS,
    profile_fieldnames,
)

# ${VAR} or ${VAR:-default}
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*))?\}")

# Fields allowed in a profile entry (value fields + name + note).
_ALLOWED_PROFILE_KEYS = set(profile_fieldnames()) | {"name", "note"}


class ConfigError(Exception):
    """Raised when profiles.yaml is missing, malformed, or invalid."""


@dataclass
class Config:
    """Parsed and validated configuration."""

    profiles: dict[str, Profile]
    targets: dict[str, TargetSpec]
    active: str | None
    path: Path

    # ------------------------------------------------------------------
    # resolution
    # ------------------------------------------------------------------
    @classmethod
    def default_path(cls) -> Path:
        """Resolve the config path per the documented precedence."""
        explicit = os.environ.get("CCS_CONFIG")
        if explicit:
            return Path(explicit).expanduser()
        xdg = Path.home() / ".config" / "ccs" / "profiles.yaml"
        if xdg.exists():
            return xdg
        local = Path.cwd() / "profiles.yaml"
        return local  # may not exist yet -> caller decides

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load and validate config. Raises ConfigError on any problem."""
        path = (path or cls.default_path()).expanduser()
        if not path.exists():
            raise ConfigError(
                f"Config file not found: {path}\n"
                f"Create one with `ccs init`, or set $CCS_CONFIG to point at "
                f"an existing profiles.yaml."
            )
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in {path}: {e}") from e
        if not isinstance(raw, dict):
            raise ConfigError(f"Top level of {path} must be a mapping.")
        return cls._build(raw, path)

    # ------------------------------------------------------------------
    # construction / validation
    # ------------------------------------------------------------------
    @classmethod
    def _build(cls, raw: dict[str, Any], path: Path) -> "Config":
        profiles_raw = raw.get("profiles") or {}
        targets_raw = raw.get("targets") or {}
        active = raw.get("active")

        if not isinstance(profiles_raw, dict):
            raise ConfigError("`profiles` must be a mapping.")
        if not isinstance(targets_raw, dict):
            raise ConfigError("`targets` must be a mapping.")

        profiles: dict[str, Profile] = {}
        for name, body in profiles_raw.items():
            profiles[name] = cls._build_profile(name, body)

        if active and active not in profiles:
            raise ConfigError(
                f"`active: {active}` references a profile that does not exist."
            )

        targets: dict[str, TargetSpec] = {}
        for name, body in targets_raw.items():
            targets[name] = cls._build_target(name, body)

        return cls(profiles=profiles, targets=targets, active=active, path=path)

    @staticmethod
    def _build_profile(name: str, body: Any) -> Profile:
        if not isinstance(body, dict):
            raise ConfigError(f"profile '{name}' must be a mapping.")
        unknown = set(body) - _ALLOWED_PROFILE_KEYS
        if unknown:
            raise ConfigError(
                f"profile '{name}' has unknown keys: {sorted(unknown)}.\n"
                f"Allowed: {sorted(_ALLOWED_PROFILE_KEYS)}"
            )
        eff = body.get("effort_level")
        if eff is not None and eff not in VALID_EFFORT_LEVELS:
            raise ConfigError(
                f"profile '{name}' effort_level must be one of "
                f"{sorted(VALID_EFFORT_LEVELS)}, got {eff!r}."
            )
        try:
            return Profile(
                name=name,
                auth_token=_resolve_ref(body.get("auth_token")),
                base_url=body.get("base_url"),
                model=body.get("model"),
                opus_model=body.get("opus_model"),
                sonnet_model=body.get("sonnet_model"),
                haiku_model=body.get("haiku_model"),
                subagent_model=body.get("subagent_model"),
                effort_level=eff,
                note=body.get("note"),
            )
        except TypeError as e:
            raise ConfigError(f"profile '{name}': {e}") from e

    @staticmethod
    def _build_target(name: str, body: Any) -> TargetSpec:
        if not isinstance(body, dict):
            raise ConfigError(f"target '{name}' must be a mapping.")
        kind = body.get("kind", "wsl")
        if kind not in ("wsl", "docker"):
            raise ConfigError(
                f"target '{name}' kind must be 'wsl' or 'docker', got {kind!r}."
            )
        container = body.get("container")
        if kind == "docker" and not container:
            raise ConfigError(f"docker target '{name}' requires a 'container'.")
        return TargetSpec(
            name=name,
            kind=kind,
            container=container,
            path=body.get("path"),
        )

    # ------------------------------------------------------------------
    # accessors
    # ------------------------------------------------------------------
    def get_profile(self, name: str) -> Profile:
        if name not in self.profiles:
            raise ConfigError(
                f"No profile named {name!r}. "
                f"Available: {', '.join(self.profiles) or '(none)'}."
            )
        return self.profiles[name]

    def get_target(self, name: str) -> TargetSpec:
        if name not in self.targets:
            raise ConfigError(
                f"No target named {name!r}. "
                f"Available: {', '.join(self.targets) or '(none)'}."
            )
        return self.targets[name]

    def target_names(self) -> list[str]:
        return list(self.targets)

    # ------------------------------------------------------------------
    # mutation + save
    # ------------------------------------------------------------------
    def upsert_profile(self, profile: Profile) -> None:
        self.profiles[profile.name] = profile

    def delete_profile(self, name: str) -> None:
        if name not in self.profiles:
            raise ConfigError(f"No profile named {name!r}.")
        del self.profiles[name]
        if self.active == name:
            self.active = None

    def set_active(self, name: str | None) -> None:
        if name is not None and name not in self.profiles:
            raise ConfigError(f"No profile named {name!r}.")
        self.active = name

    def save(self) -> None:
        """Persist current state back to ``self.path`` (atomic write)."""
        data: dict[str, Any] = {
            "profiles": {n: _profile_to_yaml(p) for n, p in self.profiles.items()},
            "targets": {n: _target_to_yaml(t) for n, t in self.targets.items()},
        }
        if self.active:
            data["active"] = self.active
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000),
            encoding="utf-8",
        )
        tmp.replace(self.path)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _resolve_ref(value: Any) -> Any:
    """Resolve ``${ENV}`` / ``${ENV:-default}`` references against os.environ.

    Non-string values pass through unchanged. An unresolved ``${VAR}`` with
    no default becomes None (treated as unset), never a literal string — so
    a missing secret simply omits the var rather than leaking the template.
    """
    if not isinstance(value, str):
        return value
    match = _ENV_REF.fullmatch(value)
    if not match:
        return value
    var, default = match.group(1), match.group(2)
    resolved = os.environ.get(var)
    if resolved is None or resolved == "":
        return default if default is not None else None
    return resolved


def _profile_to_yaml(p: Profile) -> dict[str, Any]:
    """Profile -> dict for YAML dump. Omits None fields. Keeps secrets as-is
    (the file is the source of truth); masking happens only in display."""
    out: dict[str, Any] = {}
    for key in profile_fieldnames() + ["note"]:
        v = getattr(p, key)
        if v is not None and v != "":
            out[key] = v
    return out


def _target_to_yaml(t: TargetSpec) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": t.kind}
    if t.container:
        out["container"] = t.container
    if t.path:
        out["path"] = t.path
    return out


__all__ = ["Config", "ConfigError"]
