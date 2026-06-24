"""Target abstraction and shared merge/diff logic.

A Target is somewhere we can read and write a Claude Code
``settings.json``. Two concrete implementations exist:
  - WslTarget   : a local filesystem path (the WSL ``~/.claude/settings.json``)
  - DockerTarget: a path inside a running container (via ``docker exec``)

Both share the *same* merge/diff semantics, defined here once:
  - We only ever touch the ``env`` sub-object of settings.json.
  - Top-level keys (model, statusLine, permissions, hooks, theme, ...) are
    preserved untouched.
  - Within ``env``, keys we own get set/updated; keys we don't own are
    preserved unless the profile explicitly clears them.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..core.models import ApplyResult, OWNED_ENV_KEYS


class TargetError(Exception):
    """A target could not be reached or written."""


# ---------------------------------------------------------------------------
# shared merge / diff
# ---------------------------------------------------------------------------
def merge_env(current_env: dict[str, Any], new_env: dict[str, str]) -> dict[str, str]:
    """Merge ``new_env`` into a copy of ``current_env``.

    Our owned keys are overwritten with the new value (or removed if the
    new value is None/empty). Foreign keys (anything outside
    OWNED_ENV_KEYS, e.g. a user's custom PATH) are preserved as-is.
    """
    merged: dict[str, str] = {
        k: v for k, v in current_env.items() if k not in OWNED_ENV_KEYS
    }
    for k, v in new_env.items():
        if v is None or v == "":
            continue
        merged[k] = str(v)
    return merged


def compute_env_diff(
    current_env: dict[str, Any], desired_env: dict[str, str]
) -> list[str]:
    """Return unified-ish diff lines between current and desired env.

    Only considers the union of owned keys (we never report foreign keys
    as changed, since we preserve them). Lines look like:
        + ANTHROPIC_MODEL = sonnet
        - ANTHROPIC_BASE_URL = https://old.example.com
    """
    keys = sorted(
        k for k in (set(current_env) | set(desired_env)) if k in OWNED_ENV_KEYS
        or k == "ANTHROPIC_API_KEY"  # mirror key, tracked too
    )
    lines: list[str] = []
    for k in keys:
        cur = current_env.get(k)
        new = desired_env.get(k)
        if cur == new:
            continue
        if cur is not None and new is None:
            lines.append(f"  - {k}  (will be removed)")
        elif cur is None and new is not None:
            lines.append(f"  + {k} = {new}")
        else:
            lines.append(f"  ~ {k}: {cur} -> {new}")
    return lines


@dataclass
class _SettingsDoc:
    """Parsed settings.json: top-level dict with an isolated env object."""

    raw: dict[str, Any]

    @property
    def env(self) -> dict[str, Any]:
        env = self.raw.get("env")
        if not isinstance(env, dict):
            env = {}
            self.raw["env"] = env
        return env

    def with_env(self, new_env: dict[str, str]) -> "_SettingsDoc":
        clone = _SettingsDoc(raw=json.loads(json.dumps(self.raw)))
        clone.raw["env"] = new_env
        return clone

    def to_json(self) -> str:
        return json.dumps(self.raw, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Target ABC
# ---------------------------------------------------------------------------
class Target(ABC):
    """Abstract write target for a Claude Code settings.json."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        ...

    @abstractmethod
    def _read_settings(self) -> _SettingsDoc:
        """Read current settings.json. Missing file -> empty doc."""
        ...

    @abstractmethod
    def _write_settings(self, doc: _SettingsDoc) -> None:
        """Atomically write settings.json."""
        ...

    @abstractmethod
    def _backup(self) -> str | None:
        """Back up the existing file. Return backup path or None if N/A."""
        ...

    @abstractmethod
    def health_check(self) -> tuple[bool, str]:
        """Return (reachable, message)."""
        ...

    # ------------------------------------------------------------------
    # high-level operations (shared)
    # ------------------------------------------------------------------
    def preview(self, desired_env: dict[str, str]) -> list[str]:
        """Compute diff lines without writing."""
        try:
            doc = self._read_settings()
        except TargetError as e:
            return [f"  ! cannot read: {e}"]
        return compute_env_diff(doc.env, desired_env)

    def apply(self, desired_env: dict[str, str], dry_run: bool = False) -> ApplyResult:
        """Apply desired env to this target.

        On ``dry_run`` no write happens; the result still carries the diff.
        """
        try:
            doc = self._read_settings()
        except TargetError as e:
            return ApplyResult(
                target=self.display_name, success=False, message=str(e)
            )

        diff = compute_env_diff(doc.env, desired_env)
        if not diff:
            return ApplyResult(
                target=self.display_name,
                success=True,
                message="already in sync — no changes",
                diff=[],
            )
        if dry_run:
            return ApplyResult(
                target=self.display_name,
                success=True,
                message="dry-run: would apply the changes below",
                diff=diff,
            )

        backup = None
        try:
            backup = self._backup()
            new_doc = doc.with_env(desired_env)
            self._write_settings(new_doc)
        except TargetError as e:
            return ApplyResult(
                target=self.display_name,
                success=False,
                message=f"write failed: {e}",
                diff=diff,
                backup=backup,
            )
        msg = "applied"
        if backup:
            msg += f" (backup: {backup})"
        return ApplyResult(
            target=self.display_name,
            success=True,
            message=msg,
            diff=diff,
            backup=backup,
        )

    def current_env(self) -> dict[str, Any]:
        """Return the current env object (owned keys + any foreign keys)."""
        try:
            return dict(self._read_settings().env)
        except TargetError:
            return {}

    # shared helper for backups naming
    @staticmethod
    def _ts() -> str:
        return time.strftime("%Y%m%d-%H%M%S")


__all__ = ["Target", "TargetError", "compute_env_diff", "merge_env"]
