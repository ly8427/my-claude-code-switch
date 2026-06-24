"""WSL (local filesystem) target.

Reads/writes ``~/.claude/settings.json`` directly. Backups go to the
existing ``~/.claude/backups/`` directory (the convention already in use
on this machine), named ``settings.json.bak.<timestamp>``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..core.models import TargetSpec
from .base import Target, TargetError, _SettingsDoc


class WslTarget(Target):
    def __init__(self, spec: TargetSpec):
        self.spec = spec
        path = spec.path or os.path.join(
            os.path.expanduser("~"), ".claude", "settings.json"
        )
        self.path = Path(path).expanduser()
        self._backup_dir = self.path.parent / "backups"

    @property
    def display_name(self) -> str:
        return f"wsl:{self.path}"

    def health_check(self) -> tuple[bool, str]:
        if not self.path.parent.exists():
            return False, f"directory missing: {self.path.parent}"
        return True, str(self.path)

    def _read_settings(self) -> _SettingsDoc:
        if not self.path.exists():
            return _SettingsDoc(raw={})
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise TargetError(f"{self.path} is not valid JSON: {e}") from e
        if not isinstance(data, dict):
            raise TargetError(f"{self.path} top level is not an object")
        return _SettingsDoc(raw=data)

    def _write_settings(self, doc: _SettingsDoc) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(doc.to_json(), encoding="utf-8")
        os.replace(tmp, self.path)

    def _backup(self) -> str | None:
        if not self.path.exists():
            return None
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        bak = self._backup_dir / f"settings.json.bak.{self._ts()}"
        bak.write_bytes(self.path.read_bytes())
        return str(bak)


__all__ = ["WslTarget"]
