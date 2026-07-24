#!/usr/bin/env python3
"""Small dependency-light guard for the checked-in OpenAPI contract."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "openapi.yaml"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def resolve_pointer(document: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        return None
    current: Any = document
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"unresolved OpenAPI reference: {ref}")
        current = current[part]
    return current


def walk_refs(value: Any, document: dict[str, Any]) -> None:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            resolve_pointer(document, ref)
        for child in value.values():
            walk_refs(child, document)
    elif isinstance(value, list):
        for child in value:
            walk_refs(child, document)


def validate(document: Any) -> None:
    if not isinstance(document, dict):
        raise ValueError("OpenAPI document must be an object")
    if document.get("openapi") != "3.1.0":
        raise ValueError("openapi must be 3.1.0")
    if not isinstance(document.get("info"), dict):
        raise ValueError("info is required")
    paths = document.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("paths must be a non-empty object")

    for path, path_item in paths.items():
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError(f"invalid path key: {path!r}")
        if not isinstance(path_item, dict):
            raise ValueError(f"path item must be an object: {path}")
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                raise ValueError(f"operation must be an object: {method.upper()} {path}")
            if not isinstance(operation.get("responses"), dict) or not operation["responses"]:
                raise ValueError(f"responses are required: {method.upper()} {path}")

    walk_refs(document, document)


def main() -> int:
    try:
        with CONTRACT.open(encoding="utf-8") as file:
            document = yaml.safe_load(file)
        validate(document)
    except Exception as error:  # noqa: BLE001 - command should return one concise failure
        print(f"OpenAPI validation failed: {error}", file=sys.stderr)
        return 1
    print(f"OpenAPI validation passed: {CONTRACT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

