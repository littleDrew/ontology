from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionFeatureFlags:
    """Feature gates for stage-2 capabilities.

    Defaults are intentionally OFF for phase-1 rollout.
    """

    side_effects_enabled: bool = False
    saga_enabled: bool = False
    revert_enabled: bool = False
