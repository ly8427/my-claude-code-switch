"""Docker container target.

Reads/writes settings.json *inside* a running container via
``docker exec`` — the same injection pattern validated in the
feishu-bridge ``simulate_bridge.sh``. We pipe the merged JSON in over
stdin to avoid quoting hell, and back up the existing file in place.
"""
from __future__ import annotations

import json
import shlex
import subprocess

from ..core.models import TargetSpec
from .base import Target, TargetError, _SettingsDoc


class DockerTarget(Target):
    def __init__(self, spec: TargetSpec):
        if not spec.container:
            raise TargetError("docker target requires a container name")
        self.spec = spec
        self.container = spec.container
        # default to root's claude dir, matching the feishu-claude-agent image
        self.path = spec.path or "/root/.claude/settings.json"

    @property
    def display_name(self) -> str:
        return f"docker:{self.container}{self.path}"

    # ------------------------------------------------------------------
    # docker exec helpers
    # ------------------------------------------------------------------
    def _exec(self, args: list[str], stdin: bytes | None = None) -> bytes:
        """Run a command in the container; return stdout. Raise on failure."""
        cmd = ["docker", "exec", "-i", self.container, *args]
        proc = subprocess.run(
            cmd, input=stdin, capture_output=True, check=False
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", "replace").strip()
            raise TargetError(f"docker exec failed: {err or 'exit ' + str(proc.returncode)}")
        return proc.stdout

    def _container_state(self) -> str:
        """Return container state: 'running' / 'exists' / 'missing' / 'no-docker'."""
        try:
            proc = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", self.container],
                capture_output=True, check=False, text=True,
            )
        except FileNotFoundError:
            return "no-docker"
        if proc.returncode != 0:
            return "missing"
        return "running" if proc.stdout.strip() == "true" else "exists"

    # ------------------------------------------------------------------
    # Target implementation
    # ------------------------------------------------------------------
    def health_check(self) -> tuple[bool, str]:
        state = self._container_state()
        if state == "running":
            return True, f"container {self.container} running"
        return False, f"container {self.container} {state}"

    def _read_settings(self) -> _SettingsDoc:
        # cat with a guard so a missing file yields empty doc, not an error
        out = self._exec(
            ["sh", "-c", f"cat {shlex.quote(self.path)} 2>/dev/null || true"]
        )
        text = out.decode("utf-8", "replace").strip()
        if not text:
            return _SettingsDoc(raw={})
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise TargetError(f"{self.path} in {self.container} not valid JSON: {e}") from e
        if not isinstance(data, dict):
            raise TargetError(f"{self.path} in {self.container} top level not an object")
        return _SettingsDoc(raw=data)

    def _write_settings(self, doc: _SettingsDoc) -> None:
        payload = doc.to_json().encode("utf-8")
        qpath = shlex.quote(self.path)
        # ensure parent dir exists, then atomically move a tmp file into place
        script = (
            f"mkdir -p \"$(dirname {qpath})\" && "
            f"cat > {qpath}.tmp && "
            f"mv {qpath}.tmp {qpath}"
        )
        self._exec(["sh", "-c", script], stdin=payload)

    def _backup(self) -> str | None:
        qpath = shlex.quote(self.path)
        # only back up if the file exists inside the container
        exists = self._exec(
            ["sh", "-c", f"test -f {qpath} && echo yes || echo no"]
        ).decode().strip()
        if exists != "yes":
            return None
        bak = f"{self.path}.bak.{self._ts()}"
        self._exec(["sh", "-c", f"cp -p {qpath} {shlex.quote(bak)}"])
        return f"{self.container}:{bak}"


__all__ = ["DockerTarget"]
