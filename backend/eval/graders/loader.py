"""Plugin discovery for chat-rag grader modules.

Each grader module under backend/eval/graders/ exposes top-level grade(item, response).
Modules starting with '_' or named 'loader' are skipped.
"""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from typing import Any

GraderFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None]

_PACKAGE = "backend.eval.graders"


def discover_graders() -> dict[str, GraderFn]:
    """Return {grader_name: grade_fn}. Excludes underscore-prefixed and helper modules."""
    out: dict[str, GraderFn] = {}
    pkg = importlib.import_module(_PACKAGE)
    for mod in pkgutil.iter_modules(pkg.__path__):
        name = mod.name
        if name.startswith("_") or name == "loader":
            continue
        module = importlib.import_module(f"{_PACKAGE}.{name}")
        fn = getattr(module, "grade", None)
        if callable(fn):
            out[name] = fn
    return out


def run_all(
    item: dict[str, Any],
    agent_response: dict[str, Any],
    *,
    extra_kwargs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any] | None]:
    """Run every discovered grader on the item. None results mean inapplicable."""
    results: dict[str, dict[str, Any] | None] = {}
    extra = extra_kwargs or {}
    for name, fn in discover_graders().items():
        try:
            results[name] = fn(item, agent_response, **extra.get(name, {}))
        except TypeError:
            # grader doesn't accept extra kwargs — call basic shape
            results[name] = fn(item, agent_response)
        except Exception as e:  # noqa: BLE001 — surface as error rather than crash run
            results[name] = {"score": None, "passed": False, "details": {"error": str(e)[:200]}}
    return results
