"""ccs command-line interface.

Usage:
    ccs init                          create a starter profiles.yaml
    ccs list                          list profiles (mark active)
    ccs show <profile>                show a profile's vars (secrets masked)
    ccs use <profile> [options]       apply a profile to targets
    ccs set <profile> <var> <value>   set one var on a profile
    ccs unset <profile> <var>         clear one var on a profile
    ccs new <profile>                 create a profile interactively
    ccs rm <profile>                  delete a profile
    ccs diff [profile] [options]      show what would change vs current env
    ccs targets                       list registered targets
    ccs health [options]              check target reachability
    ccs edit                          open profiles.yaml in $EDITOR
    ccs tui                           launch the interactive TUI
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .core.config import Config, ConfigError
from .core.env_compat import build_env
from .core.models import (
    ENV_KEY_TO_SHORT,
    Profile,
    VAR_MAP,
    field_label,
    mask_secret,
    profile_fieldnames,
)
from .core.targets import apply_to_targets, make_target, resolve_targets

# ANSI colours (kept simple; degrade fine on non-terminal output)
_C = {
    "green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m",
    "cyan": "\033[36m", "dim": "\033[2m", "bold": "\033[1m", "reset": "\033[0m",
}


def _c(name: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{_C[name]}{text}{_C['reset']}"


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------
def _err(msg: str) -> None:
    print(_c("red", f"error: {msg}"), file=sys.stderr)


def _load_config() -> Config | None:
    try:
        return Config.load()
    except ConfigError as e:
        _err(str(e))
        return None


def _confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_init(args: argparse.Namespace) -> int:
    path = Config.default_path()
    if path.exists() and not args.force:
        _err(f"{path} already exists (use --force to overwrite)")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_STARTER_YAML, encoding="utf-8")
    print(_c("green", f"created {path}"))
    print("Edit it with: ccs edit")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    cfg = _load_config()
    if cfg is None:
        return 1
    if not cfg.profiles:
        print("(no profiles yet — run `ccs init` then `ccs edit`, or `ccs new`)")
        return 0
    width = max(len(n) for n in cfg.profiles)
    for name, p in cfg.profiles.items():
        marker = _c("green", "*") if name == cfg.active else " "
        summary = p.model or p.sonnet_model or p.base_url or "-"
        note = f"  {_c('dim', p.note)}" if p.note else ""
        print(f" {marker} {_c('bold', name.ljust(width))}  {summary}{note}")
    print()
    print(_c("dim", f"(* = active last applied)  [{len(cfg.profiles)} profiles, "
                    f"{len(cfg.targets)} targets]"))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    cfg = _load_config()
    if cfg is None:
        return 1
    try:
        p = cfg.get_profile(args.profile)
    except ConfigError as e:
        _err(str(e))
        return 1
    print(_c("bold", f"profile: {p.name}"))
    if p.note:
        print(f"  {_c('dim', p.note)}")
    print()
    for short in profile_fieldnames():
        value = getattr(p, short)
        label = field_label(short)
        if short in ("auth_token",):
            shown = mask_secret(value) if value else _c("dim", "-")
        elif value is None:
            shown = _c("dim", "-")
        else:
            shown = value
        print(f"  {label.ljust(38)} {shown}")
    return 0


def _add_target_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-t", "--target", action="append", default=None,
        help="target name (repeatable) or kind glob (wsl:*, docker:*); "
             "default: all registered targets",
    )
    p.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    p.add_argument("-n", "--dry-run", action="store_true", help="preview only")


def cmd_use(args: argparse.Namespace) -> int:
    cfg = _load_config()
    if cfg is None:
        return 1
    try:
        profile = cfg.get_profile(args.profile)
        targets = resolve_targets(cfg, args.target)
    except ConfigError as e:
        _err(str(e))
        return 1

    env, report = build_env(profile)
    if not env:
        _err(f"profile {profile.name!r} has no variables set")
        return 1

    print(f"Applying {_c('bold', profile.name)} to "
          f"{len(targets)} target(s): {[n for n, _ in targets]}\n")

    # show compatibility advisories up front
    if report.has_advisories:
        print(_c("yellow", "compat notes:"))
        for line in report.advisories:
            print(f"  {_c('dim', '-')} {line}")
        print()

    # preview diffs for all targets
    print("planned changes:")
    any_change = False
    for name, target in targets:
        diff = target.preview(env)
        print(f"  [{name}]")
        if not diff:
            print(f"    {_c('dim', '(no change)')}")
        else:
            any_change = True
            for line in diff:
                print(f"  {line}")
    print()

    if args.dry_run:
        print(_c("cyan", "dry-run: no changes written"))
        return 0

    if not any_change:
        print(_c("dim", "nothing to do — all targets already in sync"))
        # still mark active
        cfg.set_active(profile.name)
        cfg.save()
        return 0

    if not args.yes and not _confirm("apply these changes? [y/N] "):
        print("aborted")
        return 1

    results = apply_to_targets(env, targets, dry_run=False)
    print()
    rc = 0
    for r in results:
        tag = _c("green", "OK") if r.success else _c("red", "FAIL")
        print(f"  [{tag}] {r.target}: {r.message}")
        if not r.success:
            rc = 1

    # mark active only if at least one succeeded
    if any(r.success for r in results):
        cfg.set_active(profile.name)
        cfg.save()
    return rc


def cmd_diff(args: argparse.Namespace) -> int:
    """Show diff between a profile and the current env on targets."""
    cfg = _load_config()
    if cfg is None:
        return 1
    try:
        profile = (
            cfg.get_profile(args.profile) if args.profile else _active_or_prompt(cfg)
        )
        targets = resolve_targets(cfg, args.target)
    except ConfigError as e:
        _err(str(e))
        return 1

    env, _ = build_env(profile)
    print(f"diff: {_c('bold', profile.name)} vs current env\n")
    rc = 0
    for name, target in targets:
        diff = target.preview(env)
        print(f"[{name}]")
        if not diff:
            print(f"  {_c('dim', '(in sync)')}")
        else:
            rc = 1
            for line in diff:
                print(f"  {line}")
        print()
    return rc


def _active_or_prompt(cfg: Config) -> Profile:
    if cfg.active:
        return cfg.get_profile(cfg.active)
    if len(cfg.profiles) == 1:
        return next(iter(cfg.profiles.values()))
    raise ConfigError("specify a profile name, or set one as active first")


def cmd_set(args: argparse.Namespace) -> int:
    cfg = _load_config()
    if cfg is None:
        return 1
    short = _resolve_varname(args.var)
    if short is None:
        _err(f"unknown variable {args.var!r}. Use a short name "
             f"({', '.join(VAR_MAP)}) or an env key "
             f"({', '.join(VAR_MAP.values())}).")
        return 1
    try:
        p = cfg.get_profile(args.profile)
    except ConfigError as e:
        # allow setting on a brand-new profile
        if args.profile not in cfg.profiles:
            p = Profile(name=args.profile)
            cfg.upsert_profile(p)
        else:
            _err(str(e))
            return 1
    setattr(p, short, args.value)
    cfg.save()
    print(_c("green", f"set {VAR_MAP[short]} = {mask_if_secret(short, args.value)} "
                       f"on {p.name}"))
    return 0


def cmd_unset(args: argparse.Namespace) -> int:
    cfg = _load_config()
    if cfg is None:
        return 1
    short = _resolve_varname(args.var)
    if short is None:
        _err(f"unknown variable {args.var!r}")
        return 1
    try:
        p = cfg.get_profile(args.profile)
    except ConfigError as e:
        _err(str(e))
        return 1
    setattr(p, short, None)
    cfg.save()
    print(_c("green", f"unset {VAR_MAP[short]} on {p.name}"))
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    cfg = _load_config() or Config(profiles={}, targets={}, active=None,
                                   path=Config.default_path())
    if args.profile in cfg.profiles and not args.force:
        _err(f"profile {args.profile!r} exists (use --force to overwrite)")
        return 1
    print(f"Creating profile {args.profile!r}. Press Enter to leave a field blank.")
    values: dict[str, Any] = {"name": args.profile}
    for short in profile_fieldnames():
        label = field_label(short)
        cur = ""
        raw = input(f"  {label}: ").strip()
        if raw:
            cur = raw
        values[short] = cur or None
    note = input("  note (optional): ").strip() or None
    values["note"] = note
    p = Profile(**values)
    cfg.upsert_profile(p)
    cfg.save()
    print(_c("green", f"saved profile {p.name}"))
    return 0


def cmd_rm(args: argparse.Namespace) -> int:
    cfg = _load_config()
    if cfg is None:
        return 1
    try:
        cfg.delete_profile(args.profile)
    except ConfigError as e:
        _err(str(e))
        return 1
    cfg.save()
    print(_c("green", f"deleted profile {args.profile}"))
    return 0


def cmd_targets(args: argparse.Namespace) -> int:
    cfg = _load_config()
    if cfg is None:
        return 1
    if not cfg.targets:
        print("(no targets registered — add one under `targets:` in profiles.yaml)")
        return 0
    width = max(len(n) for n in cfg.targets)
    for name, t in cfg.targets.items():
        detail = t.container or "~/.claude"
        if t.path:
            detail += f"  path={t.path}"
        print(f"  {_c('bold', name.ljust(width))}  {t.kind:7} {detail}")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    cfg = _load_config()
    if cfg is None:
        return 1
    try:
        targets = resolve_targets(cfg, args.target)
    except ConfigError as e:
        _err(str(e))
        return 1
    rc = 0
    for name, target in targets:
        ok, msg = target.health_check()
        tag = _c("green", "OK") if ok else _c("red", "DOWN")
        print(f"  [{tag}] {name:12} {msg}")
        if not ok:
            rc = 1
    return rc


def cmd_edit(args: argparse.Namespace) -> int:
    path = Config.default_path()
    if not path.exists():
        _err(f"{path} does not exist. Run `ccs init` first.")
        return 1
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or (
        "nano" if sys.platform != "win32" else "notepad"
    )
    subprocess.run([editor, str(path)])
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    try:
        from .tui.app import run_tui
    except ImportError as e:
        _err(f"TUI needs the 'textual' package: pip install 'ccs[tui]'  ({e})")
        return 1
    return run_tui()


# ---------------------------------------------------------------------------
# arg parsing
# ---------------------------------------------------------------------------
def _resolve_varname(token: str) -> str | None:
    """Accept either a short name (model) or env key (ANTHROPIC_MODEL)."""
    if token in VAR_MAP:
        return token
    if token in ENV_KEY_TO_SHORT:
        return ENV_KEY_TO_SHORT[token]
    return None


def mask_if_secret(short: str, value: str) -> str:
    return mask_secret(value) if short in ("auth_token",) else value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ccs",
        description="Switch Claude Code ANTHROPIC_*/CLAUDE_CODE_* env vars "
                    "across WSL and Docker targets.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="create a starter profiles.yaml")
    sp.add_argument("--force", action="store_true", help="overwrite existing")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("list", help="list profiles")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("show", help="show a profile's variables")
    sp.add_argument("profile")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("use", help="apply a profile to targets")
    sp.add_argument("profile")
    _add_target_args(sp)
    sp.set_defaults(func=cmd_use)

    sp = sub.add_parser("set", help="set one variable on a profile")
    sp.add_argument("profile")
    sp.add_argument("var", help="short name (model) or env key (ANTHROPIC_MODEL)")
    sp.add_argument("value")
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser("unset", help="clear one variable on a profile")
    sp.add_argument("profile")
    sp.add_argument("var")
    sp.set_defaults(func=cmd_unset)

    sp = sub.add_parser("new", help="create a profile interactively")
    sp.add_argument("profile")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("rm", help="delete a profile")
    sp.add_argument("profile")
    sp.set_defaults(func=cmd_rm)

    sp = sub.add_parser("diff", help="show what would change vs current env")
    sp.add_argument("profile", nargs="?", default=None)
    _add_target_args(sp)
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("targets", help="list registered targets")
    sp.set_defaults(func=cmd_targets)

    sp = sub.add_parser("health", help="check target reachability")
    _add_target_args(sp)
    sp.set_defaults(func=cmd_health)

    sp = sub.add_parser("edit", help="open profiles.yaml in $EDITOR")
    sp.set_defaults(func=cmd_edit)

    sp = sub.add_parser("tui", help="launch interactive TUI")
    sp.set_defaults(func=cmd_tui)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as e:
        _err(str(e))
        return 1
    except KeyboardInterrupt:
        print()
        return 130


_STARTER_YAML = """\
# ccs profiles.yaml — see https://github.com/ for docs
# Secrets: use ${ENV_VAR} to pull from the environment, e.g.
#   auth_token: ${ANTHROPIC_AUTH_TOKEN}
# so they never land in this file in plaintext.

profiles:
  official:
    base_url: https://api.anthropic.com
    auth_token: ${ANTHROPIC_API_KEY}
    model: sonnet
    effort_level: medium
    note: official Anthropic API

targets:
  wsl:
    kind: wsl
  # feishu:
  #   kind: docker
  #   container: feishu-claude-agent
  #   path: /root/.claude/settings.json
"""


if __name__ == "__main__":
    sys.exit(main())
