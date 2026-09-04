#!/usr/bin/env python3
"""Validate a stored market report against the checked-in OpenAPI schema."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "openapi.yaml"


class ContractError(ValueError):
    """A value does not satisfy its OpenAPI schema."""


def resolve_ref(document: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ContractError(f"external reference is unsupported: {ref}")
    current: Any = document
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise ContractError(f"unresolved OpenAPI reference: {ref}")
        current = current[part]
    if not isinstance(current, dict):
        raise ContractError(f"schema reference is not an object: {ref}")
    return current


def matches_type(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def validate(value: Any, schema: dict[str, Any], document: dict[str, Any], path: str) -> None:
    if "$ref" in schema:
        validate(value, resolve_ref(document, schema["$ref"]), document, path)
        return

    if "allOf" in schema:
        for child in schema["allOf"]:
            validate(value, child, document, path)
    if "oneOf" in schema:
        matches = 0
        failures = []
        for child in schema["oneOf"]:
            try:
                validate(value, child, document, path)
                matches += 1
            except ContractError as error:
                failures.append(str(error))
        if matches != 1:
            raise ContractError(f"{path}: oneOf matched {matches} schemas ({'; '.join(failures)})")
        return

    expected = schema.get("type")
    if expected:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(matches_type(value, item) for item in expected_types):
            raise ContractError(f"{path}: expected {'|'.join(expected_types)}, got {type(value).__name__}")

    if "const" in schema and value != schema["const"]:
        raise ContractError(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"{path}: value {value!r} is not in enum {schema['enum']!r}")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ContractError(f"{path}: minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ContractError(f"{path}: maxLength {schema['maxLength']}")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise ContractError(f"{path}: does not match pattern {schema['pattern']!r}")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ContractError(f"{path}: invalid date-time") from error
            if parsed.tzinfo is None:
                raise ContractError(f"{path}: date-time must include a timezone")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ContractError(f"{path}: minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ContractError(f"{path}: maximum {schema['maximum']}")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ContractError(f"{path}: minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ContractError(f"{path}: maxItems {schema['maxItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate(item, item_schema, document, f"{path}[{index}]")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for field in schema.get("required", []):
            if field not in value:
                raise ContractError(f"{path}.{field}: required field is missing")
        for field, child in properties.items():
            if field in value:
                validate(value[field], child, document, f"{path}.{field}")
        extras = set(value) - set(properties)
        additional = schema.get("additionalProperties", True)
        if additional is False and extras:
            raise ContractError(f"{path}: unexpected fields {sorted(extras)!r}")
        if isinstance(additional, dict):
            for field in extras:
                validate(value[field], additional, document, f"{path}.{field}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_market_report.py <report.json>", file=sys.stderr)
        return 2
    try:
        document = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        schema = document["components"]["schemas"]["MarketReport"]
        validate(report, schema, document, "MarketReport")
    except (ContractError, KeyError, OSError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"MarketReport contract validation failed: {error}", file=sys.stderr)
        return 1
    print("MarketReport contract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
