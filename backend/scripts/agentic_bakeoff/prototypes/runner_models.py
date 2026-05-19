"""Re-export shim so prototypes don't reach into ../runner directly.

Lets adapters import shared protocols from one place. Keeps each prototype
file's import block stable even if metric_runner internals shuffle.
"""
from ..runner.metric_runner import (
    ToolCallTrace,
    TurnResult,
    FrameworkAdapter,
    GoldenItem,
    GoldenTurn,
)


def import_for_adapter():
    """No-op marker used in adapter files to ensure this module is imported."""
    return True


__all__ = [
    "ToolCallTrace",
    "TurnResult",
    "FrameworkAdapter",
    "GoldenItem",
    "GoldenTurn",
    "import_for_adapter",
]
