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
    if "if" in schema:
        try:
            validate(value, schema["if"], document, path)
        except ContractError:
            branch = schema.get("else")
        else:
            branch = schema.get("then")
        if isinstance(branch, dict):
            validate(value, branch, document, path)
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
        # JSON Schema/OpenAPI의 pattern은 전체 일치가 아니라 검색 의미다.
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
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
        contains_schema = schema.get("contains")
        if isinstance(contains_schema, dict):
            matches = 0
            for item in value:
                try:
                    validate(item, contains_schema, document, path)
                    matches += 1
                except ContractError:
                    pass
            minimum = schema.get("minContains", 1)
            maximum = schema.get("maxContains")
            if matches < minimum or (maximum is not None and matches > maximum):
                expected = f"{minimum}..{maximum}" if maximum is not None else f">={minimum}"
                raise ContractError(f"{path}: contains matched {matches} items; expected {expected}")
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


def validate_market_report_semantics(report: dict[str, Any]) -> None:
    """Validate topics_v1 relationships that JSON Schema cannot compare directly."""
    if report.get("axisModel") != "topics_v1":
        return

    cards = report.get("cards", [])
    topic_keys = [card.get("topicKey", "").strip() for card in cards]
    if len(topic_keys) != len(set(topic_keys)):
        raise ContractError("MarketReport.cards: topics_v1 topicKey values must be unique")

    for card in cards:
        if card.get("error") and not str(card.get("error")).strip():
            raise ContractError("MarketReport.cards: error must contain visible text")
        for scenario in card.get("scenarios", []):
            if not str(scenario.get("thesis", "")).strip():
                raise ContractError("MarketReport.cards: scenario thesis must contain visible text")
            for beneficiary in scenario.get("beneficiaries", []):
                if not str(beneficiary.get("name", "")).strip():
                    raise ContractError("MarketReport.cards: beneficiary name must contain visible text")
                if (beneficiary.get("kind") == "stock"
                        and not str(beneficiary.get("evidence", "")).strip()):
                    raise ContractError(
                        "MarketReport.cards: topics_v1 stock evidence must contain visible text")

    lead_axis = report.get("leadAxis")
    lead_cards = [card for card in cards if card.get("axis") == lead_axis]
    if len(lead_cards) != 1 or report.get("title") != lead_cards[0].get("title"):
        raise ContractError("MarketReport.title: must equal the leadAxis card title")

    if report.get("readerModel") == "brief_v1":
        editorial = report.get("editorial")
        if not isinstance(editorial, dict) or editorial.get("baseReportId") != report.get("id"):
            raise ContractError(
                "MarketReport.editorial: brief_v1 must be integrated into its own report id")
        generated_at = report.get("generatedAt")
        if (editorial.get("baseGeneratedAt") != generated_at
                or editorial.get("editedAt") != generated_at):
            raise ContractError(
                "MarketReport.editorial: brief_v1 provenance timestamps must equal generatedAt")
        internal = re.compile(
            r"(?:(?<![A-Za-z0-9_])[A-Za-z0-9][A-Za-z0-9.,]*_[A-Za-z0-9_]+(?![A-Za-z0-9_])|"
            r"(?<![A-Za-z])(?:QoQ|MoM|YoY|DoD|WoW|CAPEX|backlog)(?![A-Za-z])|"
            r"@\d{4}-\d{2}(?:-\d{2})?|"
            r"\d[\d,.]*\s*b원)", re.I)
        known_ticker = re.compile(
            r"(?:\d{4,6}\.[A-Za-z0-9]{1,8}|"
            r"(?<![A-Z0-9.])(?:LRCX|AMAT|KLAC|MU|GOOGL|GOOG|MSFT|AMZN|ORCL|AVGO|"
            r"BRCM|META|NVDA|INTC|QCOM|AAPL|TSLA|TSM|BRK(?:-[AB])?)"
            r"(?:\.[A-Za-z0-9]{1,8})?(?![A-Z0-9.]))", re.I)
        contextual_ticker = re.compile(
            r"(?<![A-Za-z0-9])(?:종목\s*코드|티커|ticker)\s*[:：]?\s*"
            r"[A-Za-z0-9][A-Za-z0-9=.-]{0,63}",
            re.I)
        qualified_ticker = re.compile(
            r"(?<![A-Za-z0-9])(?:[A-Za-z][A-Za-z0-9]{1,15}(?:-[A-Za-z0-9]{1,8})?"
            r"(?:\.[A-Za-z0-9]{1,8})+|[A-Za-z][A-Za-z0-9]{1,31}=[A-Za-z0-9]{1,32}|"
            r"\d{4,6}(?:\.[A-Za-z0-9]{1,8})+)(?![A-Za-z0-9])", re.I)
        mixed_case_ric = re.compile(
            r"(?<![A-Za-z0-9])[A-Z]{1,6}[a-z]{1,2}[0-9]{1,3}(?![A-Za-z0-9])")
        suffix = re.compile(
            r"\s*\((?P<code>[^()\s]{1,64})\)\s*$")
        parenthesized_code = re.compile(
            r"\(\s*(?P<code>[A-Za-z0-9][A-Za-z0-9=.-]{0,63})\s*\)", re.I)
        non_ticker_acronyms = {
            "AI", "GPU", "CPU", "HBM", "DRAM", "NAND", "CPI", "PPI",
            "GDP", "ETF", "FX", "USD", "KRW", "JPY", "EUR", "API", "KST", "UTC",
            "ASML", "KLA", "TSMC", "KOSIS", "FRED", "SEC", "IMF", "BIS", "OECD",
            "EIA", "IEA", "BEA", "BLS", "FED", "BOJ", "ECB", "PBOC", "RBNZ",
            "CME", "WSJ", "CNBC", "USTR", "FDA", "FTC", "FCC", "EPA", "MOF",
            "NBS", "CEO", "IPO", "EPS", "EBITDA", "FCF", "PMI", "SOFR", "TIPS",
            "JGB", "DXY", "WTI", "LNG", "ADR", "YTD", "QT", "TAM", "ASP", "MOU",
            "UAE", "EU", "GMT", "EDT", "SGT",
        }

        def reader_strings(value: Any):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from reader_strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from reader_strings(item)

        scan_first = {
            "editorial": report.get("editorial", {}),
            "briefs": [card.get("brief", {}) for card in cards],
        }
        for value in reader_strings(scan_first):
            if (internal.search(value) or known_ticker.search(value)
                    or contextual_ticker.search(value) or qualified_ticker.search(value)
                    or mixed_case_ric.search(value)):
                raise ContractError(
                    "MarketReport.readerModel: scan-first text exposes internal syntax or ticker")
            if any(match.group("code") not in non_ticker_acronyms
                   for match in parenthesized_code.finditer(value)):
                raise ContractError(
                    "MarketReport.readerModel: scan-first text exposes parenthesized ticker")

        for card in cards:
            for scenario in card.get("scenarios", []):
                for beneficiary in scenario.get("beneficiaries", []):
                    copy = beneficiary.get("readerCopy")
                    if not isinstance(copy, dict):
                        raise ContractError("MarketReport.cards: brief_v1 readerCopy is required")
                    if beneficiary.get("evidence", "").strip() and not copy.get("evidence", "").strip():
                        raise ContractError("MarketReport.cards: readerCopy must preserve evidence")
                    if beneficiary.get("financials", "").strip() and not copy.get("financials", "").strip():
                        raise ContractError("MarketReport.cards: readerCopy must preserve financials")
                    values = [str(copy.get(field, "")) for field in (
                        "displayName", "rationale", "causalChain", "evidence", "financials")]
                    suffix_match = suffix.search(values[0])
                    suffix_code = suffix_match.group("code").upper() if suffix_match else ""
                    forbidden_suffix = (
                        suffix_match
                        and re.fullmatch(r"[A-Z0-9][A-Z0-9=.-]{0,63}", suffix_code)
                        and suffix_code not in non_ticker_acronyms
                    )
                    if forbidden_suffix or any(
                            internal.search(value) or known_ticker.search(value)
                            or contextual_ticker.search(value)
                            or qualified_ticker.search(value)
                            or mixed_case_ric.search(value)
                            for value in values):
                        raise ContractError(
                            "MarketReport.cards: readerCopy exposes internal syntax or ticker")
                    if any(
                            match.group("code") not in non_ticker_acronyms
                            for value in values
                            for match in parenthesized_code.finditer(value)):
                        raise ContractError(
                            "MarketReport.cards: readerCopy exposes parenthesized ticker")
                    ticker_match = re.search(
                        r"\s*\((?P<ticker>[^()\s]{1,64})\)\s*$",
                        str(beneficiary.get("name", ""))) if (
                            beneficiary.get("kind") == "stock") else None
                    raw_name = str(beneficiary.get("name", "")).strip()
                    base_name = (raw_name[:ticker_match.start()].strip()
                                 if ticker_match else raw_name)
                    display_aliases = {base_name}
                    if ticker_match:
                        full_ticker = ticker_match.group("ticker").upper()
                        root_ticker = re.split(r"[.\-=]", full_ticker, maxsplit=1)[0]
                        mapped = {
                            "005930.KS": "삼성전자", "000660.KS": "SK하이닉스",
                            "LRCX": "램리서치", "AMAT": "어플라이드 머티어리얼즈",
                            "KLAC": "KLA", "MU": "마이크론", "GOOGL": "알파벳",
                            "GOOG": "알파벳", "META": "메타", "MSFT": "마이크로소프트",
                            "AMZN": "아마존", "ORCL": "오라클", "AVGO": "브로드컴",
                            "BRCM": "브로드컴", "NVDA": "엔비디아", "INTC": "인텔",
                            "QCOM": "퀄컴", "AAPL": "애플", "TSLA": "테슬라",
                            "TSM": "TSMC", "BRK": "버크셔 해서웨이",
                        }
                        if mapped.get(full_ticker):
                            display_aliases.add(mapped[full_ticker])
                        if mapped.get(root_ticker):
                            display_aliases.add(mapped[root_ticker])
                        ticker_values = tuple(dict.fromkeys((full_ticker, root_ticker)))
                        if root_ticker in {"ASML", "KLA"}:
                            ticker_values = ((full_ticker,)
                                             if full_ticker != root_ticker else ())
                        ticker_patterns = [re.compile(
                            rf"(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])",
                            re.I,
                        ) for ticker in ticker_values]
                        if any(pattern.search(value)
                               for pattern in ticker_patterns for value in values):
                            raise ContractError(
                                "MarketReport.cards: readerCopy exposes its source ticker")
                    if str(copy.get("displayName", "")).strip() not in display_aliases:
                        raise ContractError(
                            "MarketReport.cards: readerCopy displayName changes its source subject")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_market_report.py <report.json>", file=sys.stderr)
        return 2
    try:
        document = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        schema = document["components"]["schemas"]["MarketReport"]
        validate(report, schema, document, "MarketReport")
        validate_market_report_semantics(report)
    except (ContractError, KeyError, OSError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"MarketReport contract validation failed: {error}", file=sys.stderr)
        return 1
    print("MarketReport contract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
