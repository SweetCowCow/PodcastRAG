"""Validate a golden-set dataset against backend/eval/datasets/_schema.json.

Usage:
    python -m backend.eval.scripts.validate_schema [PATH ...]

If PATH omitted, validates both `this-not-that-cool.json` and `_pending_review.json`.
Exit code 0 = all valid; 1 = any validation error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft7Validator

DATASETS_DIR = Path(__file__).resolve().parents[1] / "datasets"
SCHEMA_PATH = DATASETS_DIR / "_schema.json"


def _load_schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def validate_dataset(path: Path, schema: dict | None = None) -> list[str]:
    """Return list of error messages; empty list = valid."""
    schema = schema or _load_schema()
    validator = Draft7Validator(schema)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    errors: list[str] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{loc}: {err.message}")
    return errors


def validate_item(item: dict, schema: dict | None = None) -> list[str]:
    """Validate a single item against #/definitions/Item."""
    schema = schema or _load_schema()
    item_schema = {**schema["definitions"]["Item"], "definitions": schema["definitions"]}
    validator = Draft7Validator(item_schema)
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in validator.iter_errors(item)]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        paths = [Path(a) for a in argv]
    else:
        paths = [DATASETS_DIR / "this-not-that-cool.json", DATASETS_DIR / "_pending_review.json"]

    schema = _load_schema()
    total_errors = 0
    for path in paths:
        if not path.exists():
            print(f"[skip] {path} (not found)", file=sys.stderr)
            continue
        errors = validate_dataset(path, schema)
        if errors:
            print(f"[FAIL] {path}: {len(errors)} error(s)")
            for e in errors:
                print(f"  - {e}")
            total_errors += len(errors)
        else:
            print(f"[ok]   {path}")
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
