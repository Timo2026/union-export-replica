"""schema_validator.py — 运行时 JSON-Schema 校验 (维度 6.2: schema mismatch → fail fast).

让 schemas/*.json 真正生效: 校验 canonical RFQ / quote / context。
jsonschema 可用→Draft7 严格校验; 不可用→轻量 type/required 兜底。
默认非致命(返回 errors 供上层决策); strict=True 时抛 SchemaValidationError。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_SCHEMAS = _ROOT / "schemas"

try:
    import jsonschema  # type: ignore
    _HAS = True
except ModuleNotFoundError:
    _HAS = False


class SchemaValidationError(ValueError):
    def __init__(self, name: str, errors: List[str]):
        super().__init__(f"{name} schema violation: {errors}")
        self.name = name
        self.errors = errors


_CACHE: Dict[str, Dict[str, Any]] = {}


def _load(name: str) -> Dict[str, Any]:
    if name not in _CACHE:
        p = _SCHEMAS / f"{name}.schema.json"
        _CACHE[name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _CACHE[name]


_TYPE_MAP = {
    "object": (dict,), "array": (list,), "string": (str,), "boolean": (bool,),
    "integer": (int,), "number": (int, float), "null": (type(None),),
}


def _light(instance: Any, schema: Dict[str, Any], path: str = "<root>") -> List[str]:
    """轻量兜底校验 (无 jsonschema 时): type + required + enum + 递归 properties."""
    errs: List[str] = []
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        py_types = tuple(pt for x in types for pt in _TYPE_MAP.get(x, ()))
        if py_types and not isinstance(instance, py_types):
            # bool 是 int 子类: integer/number 不接受 True/False
            if isinstance(instance, bool) and "boolean" not in types:
                errs.append(f"{path}: expected {types}, got boolean")
                return errs
            if not isinstance(instance, bool):
                errs.append(f"{path}: expected {types}")
                return errs
    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} not in enum {schema['enum']}")
    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance or instance[req] is None:
                errs.append(f"missing required: {req}")
        for key, sub in (schema.get("properties") or {}).items():
            if key in instance and isinstance(sub, dict):
                errs.extend(_light(instance[key], sub, f"{path}/{key}"))
    return errs


def validate(instance: Any, schema_name: str, strict: bool = False) -> Dict[str, Any]:
    schema = _load(schema_name)
    if not schema:
        return {"valid": True, "errors": [], "schema": schema_name, "skipped": "schema not found"}
    if _HAS:
        v = jsonschema.Draft7Validator(schema)
        errors = [f"{'/'.join(str(x) for x in e.path) or '<root>'}: {e.message}"
                  for e in sorted(v.iter_errors(instance), key=lambda e: list(e.path))]
    else:
        errors = _light(instance, schema)
    result = {"valid": not errors, "errors": errors, "schema": schema_name,
              "engine": "jsonschema" if _HAS else "light"}
    if strict and errors:
        raise SchemaValidationError(schema_name, errors)
    return result


def validate_rfq(rfq: Dict[str, Any], strict: bool = False) -> Dict[str, Any]:
    return validate(rfq, "rfq", strict=strict)


def validate_context(ctx: Dict[str, Any], strict: bool = False) -> Dict[str, Any]:
    return validate(ctx, "context", strict=strict)


# quote 无独立 schema 文件 → 内联最小 schema (unit_price 数值/非负)
_QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "unit_price": {"type": ["number", "null"], "minimum": 0},
        "final_price": {"type": ["number", "null"], "minimum": 0},
        "quantity": {"type": ["integer", "null"], "minimum": 0},
    },
}


def validate_quote(quote: Optional[Dict[str, Any]], strict: bool = False) -> Dict[str, Any]:
    if quote is None:
        return {"valid": True, "errors": [], "schema": "quote(inline)", "skipped": "no quote"}
    if _HAS:
        v = jsonschema.Draft7Validator(_QUOTE_SCHEMA)
        errors = [e.message for e in v.iter_errors(quote)]
    else:
        errors = []
        for k in ("unit_price", "final_price"):
            val = quote.get(k)
            if val is not None:
                try:
                    if float(val) < 0:
                        errors.append(f"{k} negative")
                except (TypeError, ValueError):
                    errors.append(f"{k} not numeric")
    res = {"valid": not errors, "errors": errors, "schema": "quote(inline)",
           "engine": "jsonschema" if _HAS else "light"}
    if strict and errors:
        raise SchemaValidationError("quote", errors)
    return res
