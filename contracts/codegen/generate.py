#!/usr/bin/env python3
"""Eunomia contract codegen (Run 0b): the real contract, ONE neutral YAML source per entity ->
THREE targets (JSON Schema Draft 2020-12, Python dataclass + table-driven stdlib validator, and a
flat C++ header for firmware-relevant records). Deterministic output (sorted keys, fixed order,
no timestamps) so the codegen-drift gate is meaningful.

DSL (per field): name · type(int|number|string|bool|object|array) · required(hard|warn) · description
  optional: enum:[…] · non_empty:true · nullable:true · conditional:true (the v1-extra hard set,
  OQ-4) · items:<type> (array) · fields:[…] (object, ONE nesting level).

OQ-3 boundary: this emits DATA (hard/warn tables, enum sets, non-empty/nullable paths, the one
conditional rule) into each entity module; the hand-written engine + cross-field LOGIC live in the
vendored ``_semantics`` overlay (templates/semantics.py.tmpl). No rule-DSL/logic is generated.

OQ-8 note: kept as a single sectioned file (NOT an emitters/ subpackage) because an intra-codegen
import breaks ``mypy .``-from-root resolution under the no-[tool.mypy]-config gate. STOP-and-flag
(OQ-10) still holds: if any emitter needs real recursion / a type system, stop — don't grow it.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
GEN = ROOT / "contracts" / "_generated"
TEMPLATES = HERE / "templates"
# Source manifest: every contracts/<area>/<name>.schema.yaml (operational/interfaces are 0c).
SOURCES = sorted((ROOT / "contracts").glob("*/*.schema.yaml"))

JSON_TYPE = {
    "int": "integer",
    "number": "number",
    "string": "string",
    "bool": "boolean",
    "object": "object",
    "array": "array",
}
PY_TYPE = {
    "int": "int",
    "number": "float",
    "string": "str",
    "bool": "bool",
    "array": "list",
}
PY_DEFAULT = {"int": "0", "number": "0.0", "string": '""', "bool": "False"}
CPP_TYPE = {"int": "long long", "number": "double", "string": "std::string"}


def fill(template: str, **slots: str) -> str:
    for key, value in slots.items():
        template = template.replace(f"@{key}@", value)
    return template


def module_base(spec: dict) -> str:
    """eunomia-sidecar/v1 -> 'sidecar'; eunomia-telemetry-event/v1 -> 'telemetry_event'."""
    name = spec["schema"].split("/")[0]
    return name.removeprefix("eunomia-").replace("-", "_")


def cond_pattern(spec: dict) -> str:
    base = spec["schema"].split("/")[0]
    return f"^{base}/v[1-9][0-9]*$"


# ---- shared: flatten the field tree (depth-first; yields containers then their leaves) ----


def flatten(fields: list, prefix: str = "") -> list:
    out: list = []
    for f in fields:
        path = prefix + f["name"]
        out.append((path, f))
        if f["type"] == "object" and f.get("fields"):
            out.extend(flatten(f["fields"], path + "."))
    return out


# ---- target: JSON Schema (Draft 2020-12, spec-compliant, browser/ajv-validatable) ----


def prop_schema(f: dict) -> dict:
    t = f["type"]
    if t == "object":
        base: dict
        if f.get("fields"):
            base = {
                "type": "object",
                "properties": {sub["name"]: prop_schema(sub) for sub in f["fields"]},
                "required": [
                    sub["name"]
                    for sub in f["fields"]
                    if sub["required"] == "hard" and not sub.get("conditional")
                ],
                "additionalProperties": True,
            }
        else:
            base = {"type": "object"}
    elif t == "array":
        base = {"type": "array", "items": {"type": JSON_TYPE[f["items"]]}}
    else:
        base = {"type": JSON_TYPE[t]}
        if f.get("enum"):
            base["enum"] = f["enum"]
        if f.get("non_empty"):
            base["minLength"] = 1
    if f.get("nullable"):
        base["type"] = [base["type"], "null"]
    base["description"] = f.get("description", "")
    return base


def emit_jsonschema(spec: dict, msg: str) -> str:
    doc: dict = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$comment": msg,
        "title": spec["title"],
        "description": spec.get("description", ""),
        "type": "object",
        "properties": {f["name"]: prop_schema(f) for f in spec["fields"]},
        "required": [f["name"] for f in spec["fields"] if f["required"] == "hard"],
        "additionalProperties": True,  # additive semver: new fields added, never renamed (§5)
    }
    # The v1-extra conditional set: HARD only when `schema` matches the version pattern (OQ-4).
    cond = [(p, f) for p, f in flatten(spec["fields"]) if f.get("conditional")]
    if cond:
        then_top: list = []
        then_nested: dict = {}
        for path, _f in cond:
            if "." in path:
                parent, leaf = path.rsplit(".", 1)
                then_nested.setdefault(parent, []).append(leaf)
            else:
                then_top.append(path)
        then: dict = {}
        if then_top:
            then["required"] = then_top
        if then_nested:
            then["properties"] = {
                p: {"required": leaves} for p, leaves in then_nested.items()
            }
        doc["if"] = {
            "properties": {"schema": {"pattern": cond_pattern(spec)}},
            "required": ["schema"],
        }
        doc["then"] = then
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


# ---- target: Python (dataclass + DATA tables + table-driven stdlib validator) ----


def py_class(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def emit_dataclass(name: str, fields: list) -> str:
    lines = ["@dataclass", f"class {name}:"]
    for f in fields:
        t = f["type"]
        if t == "object" and f.get("fields"):
            cls = py_class(f["name"])
            anno, default = cls, f"field(default_factory={cls})"
        elif t == "object":
            anno, default = "dict", "field(default_factory=dict)"
        elif t == "array":
            anno, default = "list", "field(default_factory=list)"
        else:
            anno, default = PY_TYPE[t], PY_DEFAULT[t]
        if f.get("nullable") and t not in ("object", "array"):
            anno, default = f"{anno} | None", "None"
        lines.append(f"    {f['name']}: {anno} = {default}")
    return "\n".join(lines)


def py_pairs(items: list) -> str:
    """Emit a ruff-canonical exploded list of (path, type) tuples (magic trailing comma)."""
    if not items:
        return "[]"
    body = "".join(f'        ("{p}", "{t}"),\n' for p, t in items)
    return "[\n" + body + "    ]"


def py_strs(items: list) -> str:
    if not items:
        return "[]"
    return "[\n" + "".join(f'        "{s}",\n' for s in items) + "    ]"


def py_enums(enums: dict) -> str:
    if not enums:
        return "{}"
    body = ""
    for path in sorted(enums):
        values = ", ".join(f'"{v}"' for v in enums[path])
        body += f'        "{path}": [{values}],\n'
    return "{\n" + body + "    }"


def emit_python(spec: dict, msg: str) -> str:
    flat = flatten(spec["fields"])
    hard = [
        (p, f["type"])
        for p, f in flat
        if f["required"] == "hard" and not f.get("conditional")
    ]
    warn = [
        (p, f["type"])
        for p, f in flat
        if f["required"] == "warn" and not f.get("conditional")
    ]
    cond_fields = [(p, f["type"]) for p, f in flat if f.get("conditional")]
    enums = {p: f["enum"] for p, f in flat if f.get("enum")}
    non_empty = [p for p, f in flat if f.get("non_empty")]
    nullable = [p for p, f in flat if f.get("nullable")]

    subs = [f for f in spec["fields"] if f["type"] == "object" and f.get("fields")]
    blocks = [emit_dataclass(py_class(s["name"]), s["fields"]) for s in subs]
    blocks.append(emit_dataclass(spec["title"], spec["fields"]))

    pattern = f'"{cond_pattern(spec)}"' if cond_fields else '""'
    tables = (
        "_TABLES = _semantics.Tables(\n"
        f"    hard={py_pairs(hard)},\n"
        f"    warn={py_pairs(warn)},\n"
        f"    enums={py_enums(enums)},\n"
        f"    non_empty={py_strs(non_empty)},\n"
        f"    nullable={py_strs(nullable)},\n"
        f"    cond_pattern={pattern},\n"
        f"    cond_fields={py_pairs(cond_fields)},\n"
        ")"
    )
    return (
        f'"""{msg}"""\n\n'
        "from __future__ import annotations\n\n"
        "from dataclasses import dataclass, field\n\n"
        "from eunomia_contracts import _semantics\n\n\n"
        + "\n\n\n".join(blocks)
        + "\n\n\n"
        f'SCHEMA_ID = "{spec["schema"]}"\n\n'
        f"{tables}\n\n\n"
        "def validate(obj: dict) -> list[str]:\n"
        '    """Return HARD errors only (empty == safe to ingest, CONTRACT §6)."""\n'
        "    return _semantics.validate(obj, _TABLES, SCHEMA_ID)\n\n\n"
        "def validate_full(obj: dict) -> tuple[list[str], list[str]]:\n"
        '    """Return (hard_errors, warnings)."""\n'
        "    return _semantics.validate_full(obj, _TABLES, SCHEMA_ID)\n"
    )


def emit_python_init(specs: list, msg: str) -> str:
    classes = sorted(s["title"] for s in specs)
    modules = sorted(module_base(s) for s in specs)
    lines = [f'"""{msg}"""', "", "from __future__ import annotations", ""]
    for mod in modules:
        lines.append(f"from eunomia_contracts import {mod}")
    for cls in classes:
        mod = next(module_base(s) for s in specs if s["title"] == cls)
        lines.append(f"from eunomia_contracts.{mod} import {cls}")
    names = ", ".join(f'"{n}"' for n in sorted(classes + modules))
    lines += ["", f"__all__ = [{names}]", ""]
    return "\n".join(lines)


# ---- target: C++ (flat field-bag header; firmware-relevant records only, OQ-5) ----


def cpp_leaves(spec: dict) -> list:
    """Scalar/string leaves only (int/number/string); flattened by leaf key. Skip bool/array/object."""
    out: list = []
    for path, f in flatten(spec["fields"]):
        if f["type"] in ("int", "number", "string"):
            leaf = path.rsplit(".", 1)[-1]
            out.append((leaf, f["type"], f["required"]))
    return out


def emit_cpp(spec: dict, msg: str) -> str:
    leaves = cpp_leaves(spec)
    members = "\n".join(f"  {CPP_TYPE[t]} {leaf}{{}};" for leaf, t, _r in leaves)
    parse_lines = []
    for leaf, t, req in leaves:
        fn = "parse_string" if t == "string" else "parse_number"
        if req == "hard":
            parse_lines.append(f'  if (!{fn}(s, "{leaf}", out.{leaf})) return false;')
        else:
            parse_lines.append(f'  {fn}(s, "{leaf}", out.{leaf});')
    ser = []
    for i, (leaf, t, _r) in enumerate(leaves):
        sep = "" if i == 0 else ","
        if t == "string":
            ser.append(f'  o += "{sep}\\"{leaf}\\":\\"" + v.{leaf} + "\\"";')
        else:
            ser.append(f'  o += "{sep}\\"{leaf}\\":" + std::to_string(v.{leaf});')
    return fill(
        (TEMPLATES / "header.h.tmpl").read_text(),
        MSG=msg,
        GUARD=f"EUNOMIA_{module_base(spec).upper()}_H",
        TITLE=spec["title"],
        LOW=module_base(spec),
        MEMBERS=members,
        PARSE="\n".join(parse_lines),
        SER="\n".join(ser),
    )


def vendor_semantics(msg: str) -> str:
    return fill((TEMPLATES / "semantics.py.tmpl").read_text(), MSG=msg)


def emit_cpp_detail(msg: str) -> str:
    return fill((TEMPLATES / "detail.h.tmpl").read_text(), MSG=msg)


# ---- driver ----


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"  wrote {path.relative_to(ROOT)}")


def main() -> None:
    specs = [yaml.safe_load(src.read_text()) for src in SOURCES]
    print(f"codegen: {len(specs)} source(s) -> targets")
    write(
        GEN / "python" / "eunomia_contracts" / "_semantics.py", vendor_semantics(_MSG)
    )
    if any("cpp" in spec.get("targets", []) for spec in specs):
        write(GEN / "cpp" / "eunomia_detail.h", emit_cpp_detail(_MSG))
    for spec in specs:
        base = module_base(spec)
        msg = f"GENERATED by contracts/codegen/generate.py from {base}.schema.yaml - DO NOT EDIT."
        write(
            GEN / "jsonschema" / f"{spec['schema'].split('/')[0]}.schema.json",
            emit_jsonschema(spec, msg),
        )
        write(
            GEN / "python" / "eunomia_contracts" / f"{base}.py", emit_python(spec, msg)
        )
        if "cpp" in spec.get("targets", []):
            write(GEN / "cpp" / f"eunomia_{base}.h", emit_cpp(spec, msg))
    write(
        GEN / "python" / "eunomia_contracts" / "__init__.py",
        emit_python_init(specs, _MSG),
    )


_MSG = "GENERATED by contracts/codegen/generate.py - DO NOT EDIT (edit the source + run `make codegen`)."


if __name__ == "__main__":
    main()
