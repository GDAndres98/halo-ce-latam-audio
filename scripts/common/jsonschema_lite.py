"""Minimal, stdlib-only JSON Schema (draft 2020-12 subset) validator.

The project's schemas in schemas/*.schema.json are standard JSON Schema,
so any full validator can check them too. This subset exists because no
third-party package may be installed without approval. It refuses any
keyword it doesn't implement (`UnsupportedKeyword`), so a schema can never
appear to enforce something that is silently ignored.

Supported: $schema $id $ref(#/$defs/...) $defs title description $comment
type enum const pattern minLength maxLength minimum maximum required
properties additionalProperties patternProperties propertyNames items
minItems maxItems uniqueItems allOf anyOf oneOf not if then else.
"""
import json
import re
from pathlib import Path

ANNOTATIONS = {"$schema", "$id", "$defs", "title", "description", "$comment", "default", "examples"}
SUPPORTED = ANNOTATIONS | {
    "$ref", "type", "enum", "const", "pattern", "minLength", "maxLength", "minimum", "maximum", "required",
    "properties", "additionalProperties", "patternProperties", "propertyNames", "items", "minItems", "maxItems",
    "uniqueItems", "allOf", "anyOf", "oneOf", "not", "if", "then", "else"}
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


class UnsupportedKeyword(ValueError):
    pass


def _check_keywords(schema, where="#"):
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise UnsupportedKeyword(f"{where}: schema must be an object or boolean")
    bad = set(schema) - SUPPORTED
    if bad:
        raise UnsupportedKeyword(f"{where}: unsupported keyword(s) {sorted(bad)}")
    for k in ("properties", "patternProperties", "$defs"):
        for name, sub in (schema.get(k) or {}).items():
            _check_keywords(sub, f"{where}/{k}/{name}")
    for k in ("additionalProperties", "items", "not", "if", "then", "else", "propertyNames"):
        if k in schema:
            _check_keywords(schema[k], f"{where}/{k}")
    for k in ("allOf", "anyOf", "oneOf"):
        for i, sub in enumerate(schema.get(k) or []):
            _check_keywords(sub, f"{where}/{k}/{i}")


def load_schema(name_or_path):
    p = Path(name_or_path)
    if not p.suffix:
        p = SCHEMA_DIR / f"{name_or_path}.schema.json"
    schema = json.loads(p.read_text(encoding="utf-8"))
    _check_keywords(schema)
    return schema


def _type_ok(v, t):
    if t == "null":
        return v is None
    if t == "boolean":
        return isinstance(v, bool)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "string":
        return isinstance(v, str)
    if t == "array":
        return isinstance(v, list)
    if t == "object":
        return isinstance(v, dict)
    raise UnsupportedKeyword(f"unknown type {t}")


def _ptr(path):
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in path) if path else "/"


def validate(instance, schema, root=None, path=()):
    """-> list of 'json/pointer: message' strings (empty when valid)."""
    root = schema if root is None else root
    if schema is True:
        return []
    if schema is False:
        return [f"{_ptr(path)}: not allowed"]
    errs = []
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise UnsupportedKeyword(f"only local #/$defs refs are supported: {ref}")
        errs += validate(instance, root["$defs"][ref[len("#/$defs/"):]], root, path)
    if "type" in schema:
        ts = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(instance, t) for t in ts):
            return errs + [f"{_ptr(path)}: expected {'/'.join(ts)}, got {type(instance).__name__}"]
    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{_ptr(path)}: {instance!r} not in {schema['enum']}")
    if "const" in schema and instance != schema["const"]:
        errs.append(f"{_ptr(path)}: must equal {schema['const']!r}")
    if isinstance(instance, str):
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errs.append(f"{_ptr(path)}: {instance!r} does not match {schema['pattern']}")
        if len(instance) < schema.get("minLength", 0):
            errs.append(f"{_ptr(path)}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errs.append(f"{_ptr(path)}: longer than {schema['maxLength']}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errs.append(f"{_ptr(path)}: below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errs.append(f"{_ptr(path)}: above maximum {schema['maximum']}")
    if isinstance(instance, dict):
        for k in schema.get("required", []):
            if k not in instance:
                errs.append(f"{_ptr(path)}: missing required property {k!r}")
        props = schema.get("properties", {})
        pprops = schema.get("patternProperties", {})
        for k, v in instance.items():
            if "propertyNames" in schema:
                errs += validate(k, schema["propertyNames"], root, path + (k,))
            matched = False
            if k in props:
                matched = True
                errs += validate(v, props[k], root, path + (k,))
            for pat, sub in pprops.items():
                if re.search(pat, k):
                    matched = True
                    errs += validate(v, sub, root, path + (k,))
            if not matched and "additionalProperties" in schema:
                ap = schema["additionalProperties"]
                if ap is False:
                    errs.append(f"{_ptr(path + (k,))}: unexpected property")
                elif isinstance(ap, dict):
                    errs += validate(v, ap, root, path + (k,))
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errs.append(f"{_ptr(path)}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errs.append(f"{_ptr(path)}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen = [json.dumps(x, sort_keys=True) for x in instance]
            if len(seen) != len(set(seen)):
                errs.append(f"{_ptr(path)}: items are not unique")
        if "items" in schema:
            for i, v in enumerate(instance):
                errs += validate(v, schema["items"], root, path + (i,))
    for sub in schema.get("allOf", []):
        errs += validate(instance, sub, root, path)
    if "anyOf" in schema and not any(not validate(instance, s, root, path) for s in schema["anyOf"]):
        errs.append(f"{_ptr(path)}: matches none of anyOf")
    if "oneOf" in schema:
        n = sum(1 for s in schema["oneOf"] if not validate(instance, s, root, path))
        if n != 1:
            errs.append(f"{_ptr(path)}: matches {n} of oneOf (exactly 1 required)")
    if "not" in schema and not validate(instance, schema["not"], root, path):
        errs.append(f"{_ptr(path)}: must not match 'not' schema")
    if "if" in schema:
        if not validate(instance, schema["if"], root, path):
            if "then" in schema:
                errs += validate(instance, schema["then"], root, path)
        elif "else" in schema:
            errs += validate(instance, schema["else"], root, path)
    return errs
