"""Object-priority policy helper.

Current policy is intentionally simple: keyframe-like frames are marked high
priority and all others are normal priority.
"""

from __future__ import annotations

from tigas.shared.types import ObjectPriority


def assign_object_priority(is_keyframe: bool) -> ObjectPriority:
    """Map frame role to transport priority class."""
    return "high" if is_keyframe else "normal"
