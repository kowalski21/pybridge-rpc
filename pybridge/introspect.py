from __future__ import annotations

import datetime as _dt
import enum
import types
import typing as t
import uuid

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from .uploads import UploadFile


PRIMITIVES: dict[type, str] = {
    str: "string",
    int: "number",
    float: "number",
    bool: "boolean",
    bytes: "string",
    type(None): "null",
    _dt.datetime: "string",
    _dt.date: "string",
    _dt.time: "string",
    uuid.UUID: "string",
}


class TSRegistry:
    """Tracks named interface/enum definitions discovered during type rendering."""

    def __init__(self, overrides: dict[type, str] | None = None) -> None:
        self.models: dict[str, type[BaseModel]] = {}
        self.enums: dict[str, type[enum.Enum]] = {}
        self.overrides: dict[type, str] = dict(overrides or {})

    def add_model(self, model: type[BaseModel]) -> str:
        name = model.__name__
        existing = self.models.get(name)
        if existing is not None and existing is not model:
            raise ValueError(f"duplicate model name {name!r}")
        self.models[name] = model
        return name

    def add_enum(self, e: type[enum.Enum]) -> str:
        name = e.__name__
        existing = self.enums.get(name)
        if existing is not None and existing is not e:
            raise ValueError(f"duplicate enum name {name!r}")
        self.enums[name] = e
        return name


def render_type(tp: t.Any, reg: TSRegistry) -> str:
    if tp is None or tp is type(None):
        return "null"
    if tp is t.Any:
        return "unknown"

    if isinstance(tp, type) and tp in reg.overrides:
        return reg.overrides[tp]

    if tp is UploadFile:
        return "File"

    if tp in PRIMITIVES:
        return PRIMITIVES[tp]

    origin = t.get_origin(tp)
    args = t.get_args(tp)

    if origin is t.Literal:
        parts = [_literal_value(a) for a in args]
        return " | ".join(parts)

    if origin in (t.Union, types.UnionType):
        parts = [render_type(a, reg) for a in args]
        return " | ".join(parts)

    if origin in (list, set, frozenset):
        inner = args[0] if args else t.Any
        return f"{_paren(render_type(inner, reg))}[]"

    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return f"{_paren(render_type(args[0], reg))}[]"
        return "[" + ", ".join(render_type(a, reg) for a in args) + "]"

    if origin in (dict, t.Dict):
        _key, value = args if args else (str, t.Any)
        return f"Record<string, {render_type(value, reg)}>"

    if isinstance(tp, type):
        if issubclass(tp, BaseModel):
            return reg.add_model(tp)
        if issubclass(tp, enum.Enum):
            return reg.add_enum(tp)

    return "unknown"


def _paren(s: str) -> str:
    return f"({s})" if " | " in s else s


def _literal_value(v: t.Any) -> str:
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    return str(v)


def _is_optional(tp: t.Any) -> bool:
    origin = t.get_origin(tp)
    if origin in (t.Union, types.UnionType):
        return type(None) in t.get_args(tp)
    return False


def render_model_interface(model: type[BaseModel], reg: TSRegistry) -> str:
    lines = [f"export interface {model.__name__} {{"]
    for name, field in model.model_fields.items():
        ts = render_type(field.annotation, reg)
        optional = _field_optional(field)
        lines.append(f"  {name}{'?' if optional else ''}: {ts};")
    lines.append("}")
    return "\n".join(lines)


def _field_optional(field: FieldInfo) -> bool:
    if field.is_required():
        return False
    return True


def render_enum(e: type[enum.Enum], reg: TSRegistry) -> str:
    parts = []
    for member in e:
        v = member.value
        if isinstance(v, str):
            parts.append(f'"{v}"')
        else:
            parts.append(str(v))
    return f"export type {e.__name__} = " + " | ".join(parts) + ";"


def collect_all(reg: TSRegistry) -> str:
    """Expand transitively-referenced models/enums and render all declarations."""
    out: list[str] = []
    rendered_models: set[str] = set()
    rendered_enums: set[str] = set()

    while True:
        before_models = set(reg.models)
        before_enums = set(reg.enums)
        for name, model in list(reg.models.items()):
            if name in rendered_models:
                continue
            out.append(render_model_interface(model, reg))
            rendered_models.add(name)
        for name, e in list(reg.enums.items()):
            if name in rendered_enums:
                continue
            out.append(render_enum(e, reg))
            rendered_enums.add(name)
        if set(reg.models) == before_models and set(reg.enums) == before_enums:
            break

    return "\n\n".join(out)
