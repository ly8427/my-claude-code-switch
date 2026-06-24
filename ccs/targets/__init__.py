"""targets package — pluggable write targets for settings.json."""
from __future__ import annotations

from .base import Target, TargetError, compute_env_diff, merge_env

__all__ = ["Target", "TargetError", "compute_env_diff", "merge_env"]
