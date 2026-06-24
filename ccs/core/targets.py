"""Target factory and multi-target dispatcher.

Turns TargetSpec objects into concrete Target instances and applies a
profile's env to one or many of them, aggregating ApplyResults.
"""
from __future__ import annotations

from ..targets.base import Target, TargetError
from ..targets.docker_target import DockerTarget
from ..targets.wsl_target import WslTarget
from .config import Config, ConfigError
from .models import ApplyResult, TargetSpec


def make_target(spec: TargetSpec) -> Target:
    """Instantiate the right Target subclass for a spec."""
    if spec.kind == "wsl":
        return WslTarget(spec)
    if spec.kind == "docker":
        return DockerTarget(spec)
    raise TargetError(f"unknown target kind: {spec.kind!r}")


def resolve_targets(config: Config, names: list[str] | None) -> list[tuple[str, Target]]:
    """Resolve target names to (name, Target) pairs.

    ``names=None`` (or empty) -> all registered targets. Each name may
    also be a glob like 'docker:*' or 'wsl:*' to select by kind.
    """
    selected: list[tuple[str, Target]] = []
    pool = list(config.targets.items())
    if not names:
        names = list(config.targets)
    for name in names:
        # kind glob: docker:* / wsl:*
        if name.endswith(":*"):
            kind = name[:-2]
            matched = [(n, t) for n, t in pool if t.kind == kind]
            if not matched:
                raise ConfigError(f"no targets of kind '{kind}'")
            selected.extend((n, make_target(t)) for n, t in matched)
            continue
        spec = config.targets.get(name)
        if spec is None:
            raise ConfigError(
                f"unknown target {name!r}. Available: {', '.join(config.targets) or '(none)'}"
            )
        selected.append((name, make_target(spec)))
    return selected


def apply_to_targets(
    env: dict[str, str], targets: list[tuple[str, Target]], dry_run: bool = False
) -> list[ApplyResult]:
    """Apply env to each target, returning one ApplyResult per target."""
    results: list[ApplyResult] = []
    for _name, target in targets:
        results.append(target.apply(env, dry_run=dry_run))
    return results


__all__ = ["make_target", "resolve_targets", "apply_to_targets"]
