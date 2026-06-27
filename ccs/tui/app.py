"""Interactive TUI for ccs (built with textual).

Three-pane layout:
  - left: profile list (active one highlighted)
  - top-right: selected profile's 7 vars (masked)
  - bottom-right: target selector (multi-select)
Footer keys: [Enter] apply  [e] edit profile  [n] new  [d] diff  [r] refresh  [q] quit
"""
from __future__ import annotations

import os
import subprocess

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from ..core.config import Config, ConfigError
from ..core.env_compat import build_env
from ..core.models import field_label, mask_secret, profile_fieldnames
from ..core.targets import apply_to_targets, resolve_targets


class ProfileList(ListView):
    """Left pane: list of profiles."""


class VarPanel(Static):
    """Top-right pane: variable details of the selected profile."""


class TargetPanel(ListView):
    """Bottom-right pane: multi-selectable targets."""


class CCSApp(App):
    CSS = """
    Screen { layout: horizontal; }
    #left   { width: 1fr; border: round $primary; }
    #right  { width: 2fr; }
    #vars   { height: 1fr; border: round $accent; padding: 0 1; }
    #targets{ height: 1fr; border: round $success; }
    .selected-target { background: $success 30%; }
    """

    BINDINGS = [
        Binding("enter", "apply", "Apply"),
        Binding("e", "edit_profile", "Edit"),
        Binding("n", "new_profile", "New"),
        Binding("d", "diff", "Diff"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config: Config | None = None
        self._selected_targets: set[str] = set()

    # ------------------------------------------------------------------
    def load_config(self) -> bool:
        try:
            self.config = Config.load()
        except ConfigError as e:
            self.exit(message=f"error: {e}")
            return False
        return True

    def compose(self) -> ComposeResult:
        yield Header(name="ccs")
        with Horizontal():
            with Vertical(id="left"):
                yield ProfileList(id="profile-list")
            with Vertical(id="right"):
                yield VarPanel(id="vars")
                yield TargetPanel(id="targets")
        yield Footer()

    def on_mount(self) -> None:
        if not self.load_config():
            return
        self._refresh_profiles()
        self._refresh_targets()

    # ------------------------------------------------------------------
    def _refresh_profiles(self) -> None:
        if not self.config:
            return
        lv = self.query_one(ProfileList)
        lv.clear()
        for name in self.config.profiles:
            marker = "* " if name == self.config.active else "  "
            lv.append(ListItem(Label(f"{marker}{name}"), name=name))
        if self.config.profiles and lv.index is None:
            lv.index = 0

    def _refresh_targets(self) -> None:
        if not self.config:
            return
        tp = self.query_one(TargetPanel)
        tp.clear()
        for name in self.config.targets:
            kind = self.config.targets[name].kind
            tp.append(ListItem(Label(f"[{'x' if name in self._selected_targets else ' '}] {name} ({kind})"), name=name))

    @on(ListView.Selected, "#targets")
    def _toggle_target(self, event: ListView.Selected) -> None:
        event.stop()
        name = event.item.name
        if name in self._selected_targets:
            self._selected_targets.discard(name)
        else:
            self._selected_targets.add(name)
        self._refresh_targets()

    @on(ListView.Highlighted, "#profile-list")
    def _show_profile(self, event: ListView.Highlighted) -> None:
        if event.item is None or not self.config:
            return
        name = event.item.name
        p = self.config.profiles.get(name)
        if not p:
            return
        lines = [f"[b]{p.name}[/b]"]
        if p.note:
            lines.append(f"[dim]{p.note}[/dim]")
        lines.append("")
        for short in profile_fieldnames():
            value = getattr(p, short)
            label = field_label(short)
            if short in ("auth_token",):
                shown = mask_secret(value) if value else "-"
            elif value is None:
                shown = "-"
            else:
                shown = value
            lines.append(f"{label}  {shown}")
        self.query_one(VarPanel).update("\n".join(lines))

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def action_refresh(self) -> None:
        if self.load_config():
            self._refresh_profiles()
            self._refresh_targets()

    def _current_profile_name(self) -> str | None:
        lv = self.query_one(ProfileList)
        if lv.index is None or lv.highlighted_child is None:
            return None
        return lv.highlighted_child.name

    def action_diff(self) -> None:
        name = self._current_profile_name()
        if not name or not self.config:
            return
        profile = self.config.get_profile(name)
        env, _ = build_env(profile)
        target_names = sorted(self._selected_targets) or None
        try:
            targets = resolve_targets(self.config, target_names)
        except ConfigError as e:
            self.bell()
            return
        out = [f"diff: {name}"]
        for tname, target in targets:
            diff = target.preview(env)
            out.append(f"\n[{tname}]")
            out.extend(diff or ["(in sync)"])
        self.notify("\n".join(out), title=f"Diff: {name}", timeout=10)

    def action_apply(self) -> None:
        name = self._current_profile_name()
        if not name or not self.config:
            return
        profile = self.config.get_profile(name)
        env, report = build_env(profile)
        target_names = sorted(self._selected_targets) or None
        try:
            targets = resolve_targets(self.config, target_names)
        except ConfigError as e:
            self.bell()
            return
        results = apply_to_targets(env, targets, dry_run=False)
        msg_lines = [f"applied {name}:"]
        for r in results:
            tag = "OK" if r.success else "FAIL"
            msg_lines.append(f"[{tag}] {r.target}: {r.message}")
        if report.has_advisories:
            msg_lines.append("[yellow]notes:[/yellow]")
            msg_lines.extend(f"  - {a}" for a in report.advisories)
        if any(r.success for r in results):
            self.config.set_active(name)
            self.config.save()
            self._refresh_profiles()
        self.notify("\n".join(msg_lines), title=f"Apply: {name}", timeout=8)

    def action_edit_profile(self) -> None:
        path = Config.default_path()
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or (
            "nano" if os.name != "nt" else "notepad"
        )
        with self.suspend():
            subprocess.run([editor, str(path)])
        self.action_refresh()

    def action_new_profile(self) -> None:
        self.notify(
            "Run 'ccs new <name>' from the CLI, or press [b]e[/b] to edit profiles.yaml directly.",
            title="New Profile",
            timeout=6,
        )


def run_tui() -> int:
    app = CCSApp()
    app.run()
    return 0


__all__ = ["run_tui"]
