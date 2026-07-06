#!/usr/bin/env python3
"""finance_math — deterministic calculator for the /deep CALC branch.

FinQA-style: the model never does mental arithmetic. It grounds typed facts and
emits an explicit step program; this script executes it deterministically and
reports unit/pp checks. (See plan §5.3.)

Operations
  FinQA 10: add subtract multiply divide exp greater
            table_sum table_average table_max table_min
  ryze ext (unit-aware): pp_to_bps bps_to_pp

I/O contract
  stdin  JSON {typed_facts:[{id,value,unit,...}], program:[{op,args,out}],
              constants?:{name:num}, claim?:num}
  stdout JSON {result:{value,unit}, steps:[{out,value,unit}],
              checks:{units_consistent,pp_checked,reexec_equal}, errors:[]}
  exit   0 ok | 2 malformed | 3 unit mismatch | 4 division by zero

Args in a program step are resolved in order: typed-fact id, prior step `out`
name, named constant, or an inline numeric literal / {"const":n,"unit":u}.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation, getcontext

getcontext().prec = 34

DIMLESS = {"num", "ratio"}


class FinanceMathError(Exception):
    """Base; carries a CLI exit code."""
    exit_code = 2


class MalformedProgram(FinanceMathError):
    exit_code = 2


class UnitMismatch(FinanceMathError):
    exit_code = 3


class DivisionByZero(FinanceMathError):
    exit_code = 4


def _dec(x) -> Decimal:
    try:
        return Decimal(str(x).replace(",", ""))
    except InvalidOperation as exc:
        raise MalformedProgram(f"not a number: {x!r}") from exc


def _num(d):
    """Decimal/bool -> JSON-friendly int|float|bool."""
    if isinstance(d, bool):
        return d
    if d == d.to_integral_value():
        return int(d)
    return float(d)


class _State:
    def __init__(self, payload):
        facts = payload.get("typed_facts", [])
        self.facts = {f["id"]: (_dec(f["value"]), f.get("unit", "num")) for f in facts}
        self.constants = {k: (_dec(v), "num") for k, v in payload.get("constants", {}).items()}
        self.env = {}  # step out -> (Decimal, unit)
        self.units_consistent = True

    def resolve(self, arg):
        if isinstance(arg, bool):
            raise MalformedProgram(f"bad arg: {arg!r}")
        if isinstance(arg, (int, float)):
            return (_dec(arg), "num")
        if isinstance(arg, dict) and "const" in arg:
            return (_dec(arg["const"]), arg.get("unit", "num"))
        if isinstance(arg, str):
            if arg in self.facts:
                return self.facts[arg]
            if arg in self.env:
                return self.env[arg]
            if arg in self.constants:
                return self.constants[arg]
            raise MalformedProgram(f"unknown arg reference: {arg!r}")
        raise MalformedProgram(f"bad arg: {arg!r}")


def _same_unit(items):
    units = {u for _, u in items}
    if len(units) != 1:
        raise UnitMismatch(f"operands must share a unit, got {sorted(units)}")
    return units.pop()


def _binary(state, op, args):
    if len(args) != 2:
        raise MalformedProgram(f"{op} needs 2 args, got {len(args)}")
    (va, ua), (vb, ub) = state.resolve(args[0]), state.resolve(args[1])

    if op == "add":
        if ua != ub:
            raise UnitMismatch(f"add: {ua} vs {ub}")
        return va + vb, ua
    if op == "subtract":
        if ua != ub:
            raise UnitMismatch(f"subtract: {ua} vs {ub}")
        unit = "pp" if ua == "percent" else ua  # the percentage-point rule
        return va - vb, unit
    if op == "multiply":
        return va * vb, _mul_unit(state, ua, va, ub, vb)
    if op == "divide":
        if vb == 0:
            raise DivisionByZero("divide by zero")
        if ua == ub:
            unit = "ratio"
        elif ub in DIMLESS:
            unit = ua
        elif ua in DIMLESS:
            unit = "ratio"
        else:
            unit = "num"
            state.units_consistent = False
        return va / vb, unit
    if op == "exp":
        return va ** vb, "num"
    if op == "greater":
        return (va > vb), "bool"
    raise MalformedProgram(f"unknown op: {op}")


def _mul_unit(state, ua, va, ub, vb):
    if ua in DIMLESS and ub in DIMLESS:
        if ua == "ratio" and ub == "num" and vb == 100:
            return "percent"
        if ub == "ratio" and ua == "num" and va == 100:
            return "percent"
        if ua == "ratio" and ub == "ratio":
            return "ratio"
        return "num"
    if ua in DIMLESS:
        return ub
    if ub in DIMLESS:
        return ua
    state.units_consistent = False
    return "num"


def _table(state, op, args):
    if not args:
        raise MalformedProgram(f"{op} needs >=1 arg")
    items = [state.resolve(a) for a in args]
    unit = _same_unit(items)
    vals = [v for v, _ in items]
    if op == "table_sum":
        return sum(vals, Decimal(0)), unit
    if op == "table_average":
        return sum(vals, Decimal(0)) / Decimal(len(vals)), unit
    if op == "table_max":
        return max(vals), unit
    if op == "table_min":
        return min(vals), unit
    raise MalformedProgram(f"unknown op: {op}")


def _convert(state, op, args):
    if len(args) != 1:
        raise MalformedProgram(f"{op} needs 1 arg")
    v, u = state.resolve(args[0])
    if op == "pp_to_bps":
        if u != "pp":
            raise UnitMismatch(f"pp_to_bps expects pp, got {u}")
        return v * 100, "bps"
    if op == "bps_to_pp":
        if u != "bps":
            raise UnitMismatch(f"bps_to_pp expects bps, got {u}")
        return v / 100, "pp"
    raise MalformedProgram(f"unknown op: {op}")


_BINARY = {"add", "subtract", "multiply", "divide", "exp", "greater"}
_TABLE = {"table_sum", "table_average", "table_max", "table_min"}
_CONVERT = {"pp_to_bps", "bps_to_pp"}


def evaluate(payload: dict) -> dict:
    state = _State(payload)
    program = payload.get("program", [])
    if not program:
        raise MalformedProgram("empty program")

    last = None
    for step in program:
        op = step.get("op")
        args = step.get("args", [])
        out = step.get("out")
        if not op or out is None:
            raise MalformedProgram(f"step missing op/out: {step!r}")
        if op in _BINARY:
            value, unit = _binary(state, op, args)
        elif op in _TABLE:
            value, unit = _table(state, op, args)
        elif op in _CONVERT:
            value, unit = _convert(state, op, args)
        else:
            raise MalformedProgram(f"unknown op: {op}")
        state.env[out] = (value, unit)
        last = (value, unit)

    value, unit = last
    reexec_equal = None
    if "claim" in payload and not isinstance(value, bool):
        reexec_equal = bool(abs(value - _dec(payload["claim"])) <= Decimal("0.0001"))

    return {
        "result": {"value": _num(value), "unit": unit},
        "steps": [{"out": k, "value": _num(v), "unit": u} for k, (v, u) in state.env.items()],
        "checks": {
            "units_consistent": state.units_consistent,
            "pp_checked": True,
            "reexec_equal": reexec_equal,
        },
        "errors": [],
    }


def main(argv=None) -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"result": None, "errors": [f"bad input json: {exc}"]}))
        return 2
    try:
        out = evaluate(payload)
    except FinanceMathError as exc:
        print(json.dumps({"result": None, "checks": {}, "errors": [str(exc)]}))
        return exc.exit_code
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
